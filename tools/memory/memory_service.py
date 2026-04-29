#!/usr/bin/env python3
"""
Memory Service - SQLite-backed conversation turn storage + auto-summarization
+ semantic cross-session recall + archived history.

This module provides:
- Persistent store for conversation turns
- Automatic session summarization when turn count exceeds threshold
- Semantic relevance ranking for cross-session context recall
- Archive table preserving full turn history forever
- Session auto-naming from first user query

Design goals:
- Zero external dependencies beyond numpy (already installed)
- WAL mode for concurrent read/write safety
- Graceful degradation: if DB/Ollama fails, callers fall back to text file
- Separate DB from lucy_state.db to avoid schema migration risk
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DEFAULT_MEMORY_DB = Path("~/.codex-api-home/lucy/runtime-v8/state/memory.db")


def _resolve_db_path() -> Path:
    """Resolve the SQLite DB path, respecting env overrides."""
    raw = os.environ.get("LUCY_MEMORY_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(DEFAULT_MEMORY_DB).expanduser()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL DEFAULT 'default',
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
    text TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_turns_session_created
    ON conversation_turns(session_id, created_at);

CREATE TABLE IF NOT EXISTS session_summaries (
    session_id TEXT PRIMARY KEY,
    summary_text TEXT NOT NULL,
    summarized_turn_count INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS summary_embeddings (
    session_id TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS archived_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    turn_index INTEGER NOT NULL,
    archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_archived_session
    ON archived_turns(session_id, turn_index);

CREATE TABLE IF NOT EXISTS session_metadata (
    session_id TEXT PRIMARY KEY,
    display_name TEXT,
    first_query TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(_SCHEMA)
    conn.commit()


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

_CONN_CACHE: sqlite3.Connection | None = None


def _get_connection() -> sqlite3.Connection:
    """Return a cached SQLite connection (per-process)."""
    global _CONN_CACHE
    if _CONN_CACHE is None:
        db_path = _resolve_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _CONN_CACHE = sqlite3.connect(str(db_path), check_same_thread=False)
        _CONN_CACHE.execute("PRAGMA journal_mode=WAL")
        _CONN_CACHE.execute("PRAGMA synchronous=NORMAL")
        _ensure_schema(_CONN_CACHE)
    return _CONN_CACHE


def _close_connection() -> None:
    """Close the cached connection (mainly useful for tests)."""
    global _CONN_CACHE
    if _CONN_CACHE is not None:
        try:
            _CONN_CACHE.close()
        except Exception:
            pass
        _CONN_CACHE = None


# ---------------------------------------------------------------------------
# Turn storage
# ---------------------------------------------------------------------------

def store_turn(role: str, text: str, *, session_id: str = "default") -> None:
    """
    Store a single conversation turn in SQLite.

    Args:
        role: One of "user" or "assistant".
        text: The turn text (will be stripped).
        session_id: Session identifier (default "default").

    Raises:
        ValueError: If role is not "user" or "assistant".
        sqlite3.Error: On database errors (callers should catch and fall back).
    """
    if role not in {"user", "assistant"}:
        raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")

    text = text.strip()
    if not text:
        return

    conn = _get_connection()
    conn.execute(
        "INSERT INTO conversation_turns (session_id, role, text) VALUES (?, ?, ?)",
        (session_id, role, text),
    )
    conn.commit()

    # Auto-record first user query as session name
    if role == "user":
        _record_session_first_query(session_id, text)


def get_recent_turns(session_id: str = "default", limit: int = 6) -> list[dict[str, Any]]:
    """
    Return recent conversation turns for a session.

    Args:
        session_id: Session identifier.
        limit: Maximum number of turns to return (user+assistant pairs).

    Returns:
        List of dicts: [{"role": "user", "text": "..."}, ...]
        ordered oldest → newest.
    """
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT role, text FROM conversation_turns WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (session_id, limit),
    )
    rows = cursor.fetchall()
    # Reverse to restore oldest-first ordering
    return [{"role": row[0], "text": row[1]} for row in reversed(rows)]


def get_all_turns(session_id: str = "default") -> list[dict[str, Any]]:
    """
    Return all conversation turns for a session, oldest first.

    Args:
        session_id: Session identifier.

    Returns:
        List of dicts: [{"role": "user", "text": "..."}, ...]
    """
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT role, text FROM conversation_turns WHERE session_id = ? ORDER BY created_at, id",
        (session_id,),
    )
    rows = cursor.fetchall()
    return [{"role": row[0], "text": row[1]} for row in rows]


def format_turns_for_prompt(turns: list[dict[str, Any]]) -> str:
    """
    Format turns into the legacy 'User: ...\nAssistant: ...' string.

    Args:
        turns: List of turn dicts from get_recent_turns() / get_all_turns().

    Returns:
        Formatted string with blank lines between turn blocks.
    """
    lines: list[str] = []
    for turn in turns:
        role_label = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{role_label}: {turn['text']}")
    return "\n\n".join(lines)


def clear_session(session_id: str = "default") -> None:
    """Delete all turns for a session."""
    conn = _get_connection()
    conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
    conn.commit()


def get_session_count() -> int:
    """Return the number of distinct sessions with stored turns."""
    conn = _get_connection()
    cursor = conn.execute("SELECT COUNT(DISTINCT session_id) FROM conversation_turns")
    row = cursor.fetchone()
    return row[0] if row else 0


def get_turn_count(session_id: str = "default") -> int:
    """Return the number of turns for a session."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT COUNT(*) FROM conversation_turns WHERE session_id = ?",
        (session_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# Archive
# ---------------------------------------------------------------------------

def _archive_turns(session_id: str = "default") -> None:
    """
    Copy all current turns to archived_turns, then clear them.
    Preserves full history even after summarization.
    """
    conn = _get_connection()
    turns = get_all_turns(session_id)
    for idx, turn in enumerate(turns):
        conn.execute(
            "INSERT INTO archived_turns (session_id, role, text, turn_index) VALUES (?, ?, ?, ?)",
            (session_id, turn["role"], turn["text"], idx),
        )
    conn.execute("DELETE FROM conversation_turns WHERE session_id = ?", (session_id,))
    conn.commit()


def get_archived_turns(session_id: str = "default") -> list[dict[str, Any]]:
    """Return full archived turn history for a session, oldest first."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT role, text, turn_index FROM archived_turns WHERE session_id = ? ORDER BY turn_index",
        (session_id,),
    )
    rows = cursor.fetchall()
    return [{"role": row[0], "text": row[1], "turn_index": row[2]} for row in rows]


# ---------------------------------------------------------------------------
# Session metadata / naming
# ---------------------------------------------------------------------------

def _record_session_first_query(session_id: str, query_text: str) -> None:
    """Store first user query as session metadata (best effort, silent)."""
    try:
        name = query_text.strip()
        if len(name) > 60:
            name = name[:60].rsplit(" ", 1)[0] + "..."
        conn = _get_connection()
        conn.execute(
            "INSERT INTO session_metadata (session_id, display_name, first_query) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(session_id) DO NOTHING",
            (session_id, name, query_text),
        )
        conn.commit()
    except Exception:
        pass


def get_session_display_name(session_id: str = "default") -> str:
    """Return human-readable session name, or session_id if none set."""
    try:
        conn = _get_connection()
        cursor = conn.execute(
            "SELECT display_name FROM session_metadata WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        if row and row[0]:
            return row[0]
    except Exception:
        pass
    return session_id


# ---------------------------------------------------------------------------
# Summarization
# ---------------------------------------------------------------------------

def _summarize_turns_with_ollama(
    turns: list[dict[str, Any]],
    timeout: float = 30.0,
) -> str | None:
    """
    Call the local Ollama model to summarize a list of conversation turns.

    Args:
        turns: List of turn dicts (oldest first).
        timeout: HTTP timeout in seconds.

    Returns:
        Summary text, or None if the call fails.
    """
    if not turns:
        return None

    conversation_text = format_turns_for_prompt(turns)
    prompt = (
        "Summarize the following conversation in 2-3 sentences. "
        "Preserve key facts, decisions, and user preferences mentioned. Be concise.\n\n"
        f"{conversation_text}"
    )

    payload = {
        "model": os.environ.get("LUCY_OLLAMA_MODEL", "local-lucy"),
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.0,
            "num_predict": 96,
        },
    }

    url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            summary = data.get("response", "").strip()
            return summary if summary else None
    except Exception as exc:
        logger.warning(f"Summarization call failed: {exc}")
        return None


def maybe_summarize_session(session_id: str = "default", threshold: int | None = None) -> bool:
    """
    If turn count exceeds threshold, generate a summary and archive/clear the turns.

    Args:
        session_id: Session to evaluate.
        threshold: Turn count threshold. Defaults to LUCY_MEMORY_SUMMARIZE_THRESHOLD env var (20).

    Returns:
        True if summarization occurred, False otherwise.
    """
    if threshold is None:
        raw = os.environ.get("LUCY_MEMORY_SUMMARIZE_THRESHOLD", "20").strip()
        try:
            threshold = int(raw)
        except ValueError:
            threshold = 20
    if threshold <= 0:
        return False

    turn_count = get_turn_count(session_id)
    if turn_count <= threshold:
        return False

    turns = get_all_turns(session_id)
    summary = _summarize_turns_with_ollama(turns)
    if not summary:
        return False

    conn = _get_connection()
    conn.execute(
        "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) "
        "VALUES (?, ?, ?) "
        "ON CONFLICT(session_id) DO UPDATE SET "
        "summary_text=excluded.summary_text, "
        "summarized_turn_count=excluded.summarized_turn_count, "
        "created_at=CURRENT_TIMESTAMP",
        (session_id, summary, turn_count),
    )
    conn.commit()

    # Generate and store embedding for the summary
    embedding = _get_embedding(summary)
    if embedding is not None:
        _store_summary_embedding(session_id, embedding)

    # Archive turns before clearing
    _archive_turns(session_id)

    logger.info(
        "Summarized session %r (%d turns → %d chars)",
        session_id,
        turn_count,
        len(summary),
    )
    return True


def get_session_summary(session_id: str = "default") -> str | None:
    """Return the summary text for a session, or None if no summary exists."""
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT summary_text FROM session_summaries WHERE session_id = ?",
        (session_id,),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_other_session_summaries(
    current_session_id: str = "default",
    limit: int = 2,
) -> list[dict[str, Any]]:
    """
    Return summaries from sessions other than the current one.

    Args:
        current_session_id: Session to exclude.
        limit: Maximum number of summaries to return.

    Returns:
        List of dicts: [{"session_id": "...", "summary_text": "..."}, ...]
        ordered newest first.
    """
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT session_id, summary_text FROM session_summaries "
        "WHERE session_id != ? ORDER BY created_at DESC LIMIT ?",
        (current_session_id, limit),
    )
    rows = cursor.fetchall()
    return [{"session_id": row[0], "summary_text": row[1]} for row in rows]


# ---------------------------------------------------------------------------
# Embeddings & semantic search
# ---------------------------------------------------------------------------

def _get_embedding(text: str, timeout: float = 15.0) -> list[float] | None:
    """
    Call Ollama /api/embeddings to get a vector for the given text.

    Args:
        text: Text to embed.
        timeout: HTTP timeout in seconds.

    Returns:
        List of floats (the embedding vector), or None on failure.
    """
    if not text:
        return None

    payload = {
        "model": os.environ.get("LUCY_OLLAMA_MODEL", "local-lucy"),
        "prompt": text.strip(),
    }
    url = os.environ.get("LUCY_OLLAMA_EMBED_URL", "http://127.0.0.1:11434/api/embeddings")

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            embedding = data.get("embedding")
            if isinstance(embedding, list) and len(embedding) > 0:
                return embedding
            return None
    except Exception as exc:
        logger.debug(f"Embedding call failed: {exc}")
        return None


def _store_summary_embedding(session_id: str, embedding: list[float]) -> None:
    """Store a summary embedding vector in SQLite."""
    try:
        conn = _get_connection()
        blob = json.dumps(embedding).encode("utf-8")
        conn.execute(
            "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET embedding=excluded.embedding, created_at=CURRENT_TIMESTAMP",
            (session_id, blob),
        )
        conn.commit()
    except Exception as exc:
        logger.warning(f"Failed to store embedding for {session_id}: {exc}")


def _load_all_summary_embeddings() -> list[tuple[str, list[float]]]:
    """Load all stored summary embeddings: [(session_id, vector), ...]."""
    try:
        conn = _get_connection()
        cursor = conn.execute("SELECT session_id, embedding FROM summary_embeddings")
        rows = cursor.fetchall()
        results = []
        for session_id, blob in rows:
            try:
                vector = json.loads(blob.decode("utf-8"))
                if isinstance(vector, list) and len(vector) > 0:
                    results.append((session_id, vector))
            except Exception:
                continue
        return results
    except Exception:
        return []


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    try:
        import numpy as np

        va = np.array(a, dtype=np.float32)
        vb = np.array(b, dtype=np.float32)
        dot = np.dot(va, vb)
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
    except Exception:
        # Fallback pure-Python if numpy fails
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)


def find_relevant_sessions(
    query: str,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """
    Find past sessions whose summaries are semantically similar to the query.

    Uses environment-configured thresholds if parameters are not provided:
      - LUCY_MEMORY_SIMILARITY_THRESHOLD (default 0.55)
      - LUCY_MEMORY_MAX_INJECTED_SESSIONS (default 1)
      - LUCY_MEMORY_REQUIRE_TOP_GAP (default disabled)

    Args:
        query: The current user query.
        top_k: Maximum number of results. None = use env default.
        similarity_threshold: Minimum cosine similarity. None = use env default.

    Returns:
        List of dicts: [{"session_id": "...", "summary_text": "...", "similarity": 0.87}, ...]
        Sorted by similarity descending.
    """
    if not query.strip():
        return []

    threshold = similarity_threshold if similarity_threshold is not None else _similarity_threshold()
    limit = top_k if top_k is not None else _max_injected_sessions()
    gap = _top_gap_threshold()

    query_vector = _get_embedding(query)
    if query_vector is None:
        return []

    embeddings = _load_all_summary_embeddings()
    if not embeddings:
        return []

    # Fetch summary texts
    conn = _get_connection()
    session_ids = [sid for sid, _ in embeddings]
    if not session_ids:
        return []

    placeholders = ",".join("?" * len(session_ids))
    cursor = conn.execute(
        f"SELECT session_id, summary_text FROM session_summaries WHERE session_id IN ({placeholders})",
        session_ids,
    )
    summary_map = {row[0]: row[1] for row in cursor.fetchall()}

    scored = []
    for session_id, vector in embeddings:
        sim = _cosine_similarity(query_vector, vector)
        if sim >= threshold and session_id in summary_map:
            scored.append({
                "session_id": session_id,
                "summary_text": summary_map[session_id],
                "similarity": sim,
            })

    scored.sort(key=lambda x: x["similarity"], reverse=True)

    # Apply top-gap filter: the #1 match must beat #2 by at least the gap margin.
    if gap is not None and len(scored) >= 2:
        if (scored[0]["similarity"] - scored[1]["similarity"]) < gap:
            return []

    return scored[:limit]


# ---------------------------------------------------------------------------
# Context depth detection (Mode Auto)
# ---------------------------------------------------------------------------

# Patterns that indicate the query references prior conversation context
# and therefore needs "deep" context (summaries + semantic recall).
_DEEP_CONTEXT_RE = re.compile(
    r"\b(him|her|it|that|this|they|them|their|those|the same|such|so|thus|there|then|"
    r"earlier|previous|before|above|mentioned|discussed|agreed|decided|said|stated)\b",
    re.IGNORECASE,
)

_FOLLOWUP_RE = re.compile(
    r"\b(what about|how about|tell me more|elaborate|continue|go on|expand on|"
    r"follow up|follow-up|more details|more info|why|how come|and\?|ok and)\b",
    re.IGNORECASE,
)


def _detect_context_depth(query: str) -> str:
    """
    Auto-detect whether a query needs shallow or deep context.

    Returns:
        "deep" if the query references prior context or asks for continuation.
        "shallow" if the query appears self-contained.
    """
    q = query.strip()
    if not q:
        return "shallow"
    # Short pronoun-heavy queries are almost always context-dependent
    if len(q) <= 15 and _DEEP_CONTEXT_RE.search(q):
        return "deep"
    if _FOLLOWUP_RE.search(q):
        return "deep"
    if _DEEP_CONTEXT_RE.search(q):
        return "deep"
    return "shallow"


# ---------------------------------------------------------------------------
# Configurable similarity thresholds
# ---------------------------------------------------------------------------

def _similarity_threshold() -> float:
    """Return configured semantic similarity threshold (default 0.70)."""
    raw = os.environ.get("LUCY_MEMORY_SIMILARITY_THRESHOLD", "0.70").strip()
    try:
        v = float(raw)
    except ValueError:
        v = 0.70
    return max(0.0, min(1.0, v))


def _max_injected_sessions() -> int:
    """Return configured max semantic sessions to inject (default 1)."""
    raw = os.environ.get("LUCY_MEMORY_MAX_INJECTED_SESSIONS", "1").strip()
    try:
        v = int(raw)
    except ValueError:
        v = 1
    return max(0, v)


def _top_gap_threshold() -> float | None:
    """
    Return configured minimum gap between top and second match (default 0.10).
    The top match must beat the second by at least this margin to be injected.
    """
    raw = os.environ.get("LUCY_MEMORY_REQUIRE_TOP_GAP", "0.10").strip()
    if not raw:
        return 0.10
    try:
        v = float(raw)
    except ValueError:
        return 0.10
    return max(0.0, min(1.0, v))


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def assemble_context(
    current_session_id: str = "default",
    max_chars: int = 500,
    recent_turn_limit: int = 4,
    other_summary_limit: int = 2,
    query: str = "",
    depth: str = "auto",
    mode: str = "local",
) -> str:
    """
    Assemble the session memory context string.

    LOCAL mode (default):
        - Shallow: recent turns only
        - Deep: current session summary + recent turns
        - NEVER injects other sessions (no cross-session recall)

    AUGMENTED mode:
        - Deep: semantic recall + current summary + recent turns + other sessions
        - Cross-session recall permitted with strict thresholds

    Args:
        current_session_id: The active session.
        max_chars: Maximum length of the returned context.
        recent_turn_limit: Number of recent turns to include.
        other_summary_limit: Number of other-session summaries to include.
        query: Current user query for semantic recall (optional).
        depth: "auto", "shallow", or "deep". Auto uses _detect_context_depth(query).
        mode: "local" or "augmented". Local never injects other sessions.

    Returns:
        Formatted context string, or empty string if nothing available.
    """
    if depth == "auto":
        depth = _detect_context_depth(query)

    parts: list[str] = []

    # SHALLOW (both modes): recent turns only. Fast, low risk.
    if depth == "shallow":
        recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
        if recent_turns:
            return format_turns_for_prompt(recent_turns)[:max_chars]
        return ""

    # DEEP — LOCAL: current session only. No cross-session recall.
    if mode == "local":
        current_summary = get_session_summary(current_session_id)
        if current_summary:
            parts.append(f"Session summary: {current_summary}")
        recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
        if recent_turns:
            parts.append(format_turns_for_prompt(recent_turns))
        if not parts:
            return ""
        context = "\n\n".join(parts)
        if len(context) > max_chars:
            context = context[-max_chars:]
        return context

    # DEEP — AUGMENTED: full context assembly with cross-session recall
    included_session_ids: set[str] = set()

    # 1. Semantic recall (uses env-configured thresholds)
    if query.strip():
        try:
            relevant = find_relevant_sessions(query)
            for item in relevant:
                text = item["summary_text"]
                if len(text) > 150:
                    text = text[:150].rsplit(" ", 1)[0] + "..."
                parts.append(f"Related session: {text}")
                included_session_ids.add(item["session_id"])
        except Exception:
            pass

    # 2. Chronological fallback — only when no query (semantic already handled it)
    if not query.strip() and len(parts) < other_summary_limit:
        other_summaries = get_other_session_summaries(current_session_id, limit=other_summary_limit)
        for summary in other_summaries:
            if summary["session_id"] in included_session_ids:
                continue
            text = summary["summary_text"]
            if len(text) > 150:
                text = text[:150].rsplit(" ", 1)[0] + "..."
            parts.append(f"Previous session: {text}")
            if len(parts) >= other_summary_limit:
                break

    # 3. Current session summary
    current_summary = get_session_summary(current_session_id)
    if current_summary:
        parts.append(f"Session summary: {current_summary}")

    # 4. Recent turns
    recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
    if recent_turns:
        parts.append(format_turns_for_prompt(recent_turns))

    if not parts:
        return ""

    context = "\n\n".join(parts)
    if len(context) > max_chars:
        context = context[-max_chars:]
    return context
