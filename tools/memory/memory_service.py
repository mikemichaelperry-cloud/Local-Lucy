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

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _truncate_at_turn_boundary(text: str, max_chars: int) -> str:
    """Truncate text cleanly at a turn boundary, never mid-turn.

    Splits on double-newlines (turn separators) and keeps as many
    complete turns as fit within max_chars. If the text is already
    within budget, returns it unchanged.
    """
    if len(text) <= max_chars:
        return text
    turns = text.split("\n\n")
    kept: list[str] = []
    current_len = 0
    for turn in turns:
        add = len(turn) + 2  # +2 for the "\n\n" separator
        if current_len + add > max_chars and kept:
            break
        kept.append(turn)
        current_len += add
    return "\n\n".join(kept)


# Models that emit reasoning/thinking blocks (e.g., qwen3) can pollute memory
# with meta-commentary. Strip those blocks before storage or prompt injection.
# Strip <think>...</think> reasoning blocks. Some truncated summaries may
# contain an unclosed <think> tag; remove from the tag to the end of text.
_THINKING_BLOCK_RE = re.compile(r"<think\b.*?(?:</think>|$)", re.DOTALL | re.IGNORECASE)


def _strip_thinking_blocks(text: str) -> str:
    """Remove <think>...</think> reasoning blocks from model output."""
    if not text:
        return text
    return _THINKING_BLOCK_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def _resolve_db_path() -> Path:
    """Resolve the SQLite DB path, respecting env overrides and XDG paths."""
    raw = os.environ.get("LUCY_MEMORY_DB_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()

    # Prefer the shared XDG path resolver; fall back to a legacy default if
    # the import is unavailable (e.g., standalone use without full repo path).
    try:
        from tools.xdg_paths import lucy_memory_db_path

        return lucy_memory_db_path()
    except Exception:
        return Path.home() / ".codex-api-home" / "lucy" / "runtime-v10" / "state" / "memory.db"


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

CREATE TABLE IF NOT EXISTS persistent_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_text TEXT NOT NULL,
    category TEXT,
    embedding BLOB,
    embedding_model TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_facts_category ON persistent_facts(category);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(_SCHEMA)
    _migrate_fact_embedding_columns(conn)
    conn.commit()


def _migrate_fact_embedding_columns(conn: sqlite3.Connection) -> None:
    """Add embedding columns to persistent_facts if missing (idempotent)."""
    cursor = conn.execute("PRAGMA table_info(persistent_facts)")
    columns = {row[1] for row in cursor.fetchall()}
    if "embedding" not in columns:
        conn.execute("ALTER TABLE persistent_facts ADD COLUMN embedding BLOB")
    if "embedding_model" not in columns:
        conn.execute("ALTER TABLE persistent_facts ADD COLUMN embedding_model TEXT")


# ---------------------------------------------------------------------------
# Fact embedding engine (MiniLM-L6-v2 primary, Ollama fallback)
# ---------------------------------------------------------------------------

_MINILM_MODEL: Any | None = None
_MINILM_LOCK = threading.Lock()
_MINILM_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Module-level telemetry cache for the most recent fact-retrieval call.
# Populated by get_relevant_persistent_facts; read by execution_engine.
_LAST_FACT_TELEMETRY: dict[str, Any] = {}


def _get_minilm_model() -> Any | None:
    """Lazy-load MiniLM-L6-v2. Returns None if sentence_transformers unavailable."""
    global _MINILM_MODEL
    if _MINILM_MODEL is not None:
        return _MINILM_MODEL
    with _MINILM_LOCK:
        if _MINILM_MODEL is not None:
            return _MINILM_MODEL
        try:
            from sentence_transformers import SentenceTransformer

            _MINILM_MODEL = SentenceTransformer(_MINILM_MODEL_NAME, device="cpu")
            _MINILM_MODEL.eval()
            logger.info("Loaded MiniLM-L6-v2 for fact embeddings")
            return _MINILM_MODEL
        except Exception as exc:
            logger.debug(f"MiniLM-L6-v2 unavailable for fact embeddings: {exc}")
            return None


def _get_fact_embedding_engine_name() -> str:
    """Return identifier for the currently active fact-embedding engine."""
    if _get_minilm_model() is not None:
        return "minilm"
    return f"ollama:{os.environ.get('LUCY_OLLAMA_MODEL', 'local-lucy')}"


def _compute_fact_embedding(text: str) -> list[float] | None:
    """Embed *text* using MiniLM-L6-v2 if available, else Ollama."""
    if not text or not text.strip():
        return None
    stripped = text.strip()
    model = _get_minilm_model()
    if model is not None:
        try:
            vec = model.encode(stripped, convert_to_numpy=True, normalize_embeddings=True)
            return vec.tolist()
        except Exception as exc:
            logger.debug(f"MiniLM embedding failed: {exc}")
    return _get_embedding(stripped)


def _store_fact_embedding(conn: sqlite3.Connection, fact_id: int, embedding: list[float]) -> None:
    """Persist a computed embedding alongside its model identifier."""
    blob = json.dumps(embedding).encode("utf-8")
    model_name = _get_fact_embedding_engine_name()
    conn.execute(
        "UPDATE persistent_facts SET embedding = ?, embedding_model = ? WHERE id = ?",
        (blob, model_name, fact_id),
    )


def _load_fact_with_embeddings(conn: sqlite3.Connection, category: str | None = None):
    """Load facts. Backfill missing/stale embeddings on demand. Returns rows."""
    current_engine = _get_fact_embedding_engine_name()
    if category:
        cursor = conn.execute(
            "SELECT id, fact_text, embedding, embedding_model FROM persistent_facts WHERE category = ? ORDER BY id",
            (category,),
        )
    else:
        cursor = conn.execute(
            "SELECT id, fact_text, embedding, embedding_model FROM persistent_facts ORDER BY id"
        )
    rows = cursor.fetchall()
    result = []
    for fact_id, fact_text, embedding_blob, embedding_model in rows:
        if embedding_blob is None or embedding_model != current_engine:
            # Backfill missing or stale embedding
            embedding = _compute_fact_embedding(fact_text)
            if embedding is not None:
                _store_fact_embedding(conn, fact_id, embedding)
                embedding_blob = json.dumps(embedding).encode("utf-8")
                embedding_model = current_engine
        if embedding_blob is not None:
            try:
                embedding = json.loads(embedding_blob.decode("utf-8"))
                result.append((fact_id, fact_text, embedding))
            except Exception:
                continue
    if result:
        conn.commit()
    return result


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

_CONN_CACHE: sqlite3.Connection | None = None


def _connection_is_closed(conn: sqlite3.Connection) -> bool:
    """Return True if the given connection has been closed."""
    try:
        conn.execute("SELECT 1")
        return False
    except sqlite3.ProgrammingError:
        return True


def _get_connection() -> sqlite3.Connection:
    """Return a cached SQLite connection (per-process), reopening if it was closed."""
    global _CONN_CACHE
    if _CONN_CACHE is None or _connection_is_closed(_CONN_CACHE):
        _CONN_CACHE = None
        db_path = _resolve_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _CONN_CACHE = sqlite3.connect(str(db_path), check_same_thread=False)
        _CONN_CACHE.execute("PRAGMA journal_mode=WAL")
        _CONN_CACHE.execute("PRAGMA synchronous=NORMAL")
        _ensure_schema(_CONN_CACHE)
        # Harden DB file permissions (production readiness)
        try:
            os.chmod(db_path, 0o600)
        except OSError:
            pass
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

    text = _strip_thinking_blocks(text.strip())
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
        List of dicts: [{"role": "user", "text": "...", "created_at": "..."}, ...]
        ordered oldest → newest.
    """
    conn = _get_connection()
    cursor = conn.execute(
        "SELECT role, text, created_at FROM conversation_turns WHERE session_id = ? ORDER BY created_at DESC, id DESC LIMIT ?",
        (session_id, limit),
    )
    rows = cursor.fetchall()
    # Reverse to restore oldest-first ordering
    return [{"role": row[0], "text": row[1], "created_at": row[2]} for row in reversed(rows)]


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
        text = _strip_thinking_blocks(turn.get("text", ""))
        if text:
            lines.append(f"{role_label}: {text}")
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Persistent facts (human-curated, read-only to Lucy)
# ---------------------------------------------------------------------------


def store_persistent_fact(fact_text: str, category: str | None = None) -> int:
    """Store a persistent fact with its embedding. Returns the new row id."""
    fact_text = fact_text.strip()
    if not fact_text:
        raise ValueError("fact_text must be non-empty")
    conn = _get_connection()
    cur = conn.execute(
        "INSERT INTO persistent_facts (fact_text, category) VALUES (?, ?)",
        (fact_text, category),
    )
    fact_id = cur.lastrowid
    embedding = _compute_fact_embedding(fact_text)
    if embedding is not None:
        _store_fact_embedding(conn, fact_id, embedding)
    conn.commit()
    return fact_id


def get_persistent_facts(category: str | None = None) -> list[str]:
    """Return all persistent facts, optionally filtered by category."""
    conn = _get_connection()
    if category:
        cursor = conn.execute(
            "SELECT fact_text FROM persistent_facts WHERE category = ? ORDER BY id",
            (category,),
        )
    else:
        cursor = conn.execute("SELECT fact_text FROM persistent_facts ORDER BY id")
    return [row[0] for row in cursor.fetchall()]


def get_relevant_persistent_facts(
    query: str,
    category: str | None = None,
    limit: int = 3,
    threshold: float = 0.30,
) -> list[str]:
    """Return up to *limit* persistent facts relevant to *query*.

    Facts are pre-embedded at storage time using MiniLM-L6-v2 (primary) or
    Ollama (fallback). At query time the query is embedded once and compared
    against cached fact embeddings via cosine similarity. This is O(N) with a
    single embedding call instead of O(N) embedding calls.

    If semantic retrieval cannot run, returns an empty list.
    """
    global _LAST_FACT_TELEMETRY
    _LAST_FACT_TELEMETRY = {}

    if not query or not query.strip() or limit <= 0:
        _LAST_FACT_TELEMETRY["fallback_reason"] = "invalid_query"
        return []

    try:
        conn = _get_connection()
        facts = _load_fact_with_embeddings(conn, category)
        if not facts:
            _LAST_FACT_TELEMETRY["fallback_reason"] = "no_facts_in_db"
            return []

        query_embedding = _compute_fact_embedding(query.strip())
        engine_used = _get_fact_embedding_engine_name()
        _LAST_FACT_TELEMETRY["successful_backend"] = engine_used
        _LAST_FACT_TELEMETRY["fallback_used"] = engine_used.startswith("ollama")
        _LAST_FACT_TELEMETRY["primary_failed"] = (
            "minilm" if engine_used.startswith("ollama") else ""
        )
        _LAST_FACT_TELEMETRY["fallback_to"] = "ollama" if engine_used.startswith("ollama") else ""
        _LAST_FACT_TELEMETRY["degradation_level"] = (
            "limited" if engine_used.startswith("ollama") else "none"
        )

        if query_embedding is None:
            _LAST_FACT_TELEMETRY["fallback_reason"] = "embedding_failed"
            return []

        scored: list[tuple[float, int, str]] = []
        for fact_id, fact_text, fact_embedding in facts:
            similarity = _cosine_similarity(query_embedding, fact_embedding)
            if similarity >= threshold:
                scored.append((similarity, int(fact_id), str(fact_text)))

        scored.sort(key=lambda item: (-item[0], item[1]))
        results = [fact_text for _, _, fact_text in scored[:limit]]
        _LAST_FACT_TELEMETRY["facts_returned"] = len(results)
        _LAST_FACT_TELEMETRY["facts_considered"] = len(facts)
        return results
    except Exception as exc:
        logger.debug("Relevant persistent-fact retrieval failed", exc_info=True)
        _LAST_FACT_TELEMETRY["fallback_reason"] = f"exception:{type(exc).__name__}"
        return []


def get_last_fact_telemetry() -> dict[str, Any]:
    """Return telemetry from the most recent get_relevant_persistent_facts call."""
    return dict(_LAST_FACT_TELEMETRY)


def delete_persistent_fact(fact_id: int) -> None:
    """Delete a persistent fact by its id."""
    conn = _get_connection()
    conn.execute("DELETE FROM persistent_facts WHERE id = ?", (fact_id,))
    conn.commit()


def get_persistent_facts_revision(category: str | None = None) -> str:
    """Return a revision token that changes when facts are added or deleted.

    Uses MAX(id), COUNT(*), and MAX(created_at) for an O(1) index scan.
    Because there is no UPDATE API for facts today, this is sufficient to
    detect any mutation (insert or delete).
    """
    conn = _get_connection()
    if category:
        cursor = conn.execute(
            "SELECT COALESCE(MAX(id),0), COUNT(*), COALESCE(MAX(created_at),'') "
            "FROM persistent_facts WHERE category = ?",
            (category,),
        )
    else:
        cursor = conn.execute(
            "SELECT COALESCE(MAX(id),0), COUNT(*), COALESCE(MAX(created_at),'') "
            "FROM persistent_facts"
        )
    max_id, count, latest = cursor.fetchone()
    return f"{max_id}:{count}:{latest}"


# ---------------------------------------------------------------------------
# User identity (persona selection)
# ---------------------------------------------------------------------------

_IDENTITY_CATEGORY = "identity"
_IDENTITY_FACT_PREFIX = "Current user is "

_USER_IDENTITY_RE = re.compile(
    r"^(?:\s*)(?:"
    r"i\s+am\s+(?P<name1>[A-Za-z]+)|"
    r"my\s+name\s+is\s+(?P<name2>[A-Za-z]+)|"
    r"this\s+is\s+(?P<name3>[A-Za-z]+)|"
    r"(?P<name4>[A-Za-z]+)\s+speaking|"
    r"(?P<name5>[A-Za-z]+)\s+here"
    r")(?:\s*[.!?]?\s*)$",
    re.IGNORECASE,
)

# Recognized personas. The key is the canonical name; values are acceptable
# spoken forms (case-insensitive).
_RECOGNIZED_PERSONAS: dict[str, set[str]] = {
    "Michael": {"michael", "mike", "mikey"},
}


def _normalize_identity_name(raw_name: str) -> str | None:
    """Map a spoken name to a canonical persona name, or None if unknown."""
    lowered = raw_name.strip().lower()
    for canonical, aliases in _RECOGNIZED_PERSONAS.items():
        if lowered in aliases:
            return canonical
    return None


def detect_user_identity(query: str) -> str | None:
    """
    Detect a user identity declaration like 'I am Michael'.

    Returns the canonical persona name (e.g. 'Michael') if the query is a
    standalone identity declaration for a recognized persona, otherwise None.
    """
    if not query or not query.strip():
        return None
    match = _USER_IDENTITY_RE.match(query.strip())
    if not match:
        return None
    raw_name = (
        match.group("name1")
        or match.group("name2")
        or match.group("name3")
        or match.group("name4")
        or match.group("name5")
    )
    if not raw_name:
        return None
    return _normalize_identity_name(raw_name)


def get_current_user_identity() -> str | None:
    """Return the canonical name of the currently active user persona, or None."""
    facts = get_persistent_facts(category=_IDENTITY_CATEGORY)
    if not facts:
        return None
    # The most recently stored identity fact is authoritative.
    latest = facts[-1]
    prefix = _IDENTITY_FACT_PREFIX
    if latest.startswith(prefix):
        return latest[len(prefix) :].strip() or None
    return None


def set_current_user_identity(name: str) -> int:
    """
    Persist the active user identity, replacing any previous identity fact.

    Args:
        name: Canonical persona name (e.g. 'Michael').

    Returns:
        The new persistent-fact row id.
    """
    canonical = _normalize_identity_name(name)
    if canonical is None:
        raise ValueError(f"Unrecognized persona: {name}")
    conn = _get_connection()
    # Remove any previous identity facts so only one is active.
    conn.execute("DELETE FROM persistent_facts WHERE category = ?", (_IDENTITY_CATEGORY,))
    conn.commit()
    return store_persistent_fact(f"{_IDENTITY_FACT_PREFIX}{canonical}", category=_IDENTITY_CATEGORY)


def clear_current_user_identity() -> None:
    """Remove the persisted user identity, reverting to the default persona."""
    conn = _get_connection()
    conn.execute("DELETE FROM persistent_facts WHERE category = ?", (_IDENTITY_CATEGORY,))
    conn.commit()


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
        "Preserve key facts, decisions, and user preferences mentioned. Be concise. "
        "Do not include chain-of-thought, reasoning, or <think> tags. "
        "Output only the summary.\n\n"
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
            if not summary:
                return None
            # Strip chain-of-thought / reasoning artifacts some models emit.
            summary = re.sub(r"<think>.*?</think>", "", summary, flags=re.DOTALL).strip()
            summary = re.sub(r"\banswers\s*", "", summary, flags=re.IGNORECASE).strip()
            summary = re.sub(r"^summary:\s*", "", summary, flags=re.IGNORECASE).strip()
            summary = re.sub(r"\s+", " ", summary).strip()
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
    return _strip_thinking_blocks(row[0]) if row else None


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
    return [{"session_id": row[0], "summary_text": _strip_thinking_blocks(row[1])} for row in rows]


def strip_thinking_blocks_from_db() -> tuple[int, int, int]:
    """
    Remove <think>...</think> reasoning blocks from all stored turns and
    summaries, and delete summaries that become empty after stripping.

    Returns:
        Tuple of (turns_updated, summaries_updated, summaries_deleted).
    """
    conn = _get_connection()
    turns_updated = 0
    summaries_updated = 0
    summaries_deleted = 0

    cursor = conn.execute("SELECT id, text FROM conversation_turns")
    for row_id, text in cursor.fetchall():
        cleaned = _strip_thinking_blocks(text)
        if cleaned != text:
            conn.execute(
                "UPDATE conversation_turns SET text = ? WHERE id = ?",
                (cleaned, row_id),
            )
            turns_updated += 1

    cursor = conn.execute("SELECT session_id, summary_text FROM session_summaries")
    for session_id, summary_text in cursor.fetchall():
        cleaned = _strip_thinking_blocks(summary_text)
        if not cleaned:
            conn.execute("DELETE FROM session_summaries WHERE session_id = ?", (session_id,))
            summaries_deleted += 1
        elif cleaned != summary_text:
            conn.execute(
                "UPDATE session_summaries SET summary_text = ? WHERE session_id = ?",
                (cleaned, session_id),
            )
            summaries_updated += 1

    conn.commit()
    return turns_updated, summaries_updated, summaries_deleted


# ---------------------------------------------------------------------------
# Embeddings & semantic search
# ---------------------------------------------------------------------------

# Thread-safe in-process cache for Ollama embeddings.
# Eliminates redundant POSTs when the same text is embedded multiple times
# within a single request (e.g. semantic recall + topic-shift check).
_EMBEDDING_CACHE: dict[str, list[float]] = {}
_EMBEDDING_CACHE_LOCK = threading.Lock()
_EMBEDDING_CACHE_MAXSIZE = 256


def _get_embedding(text: str, timeout: float = 15.0) -> list[float] | None:
    """
    Return a normalized embedding vector for the given text.

    Primary: MiniLM-L6-v2 (local, no network, works for all models).
    Fallback: Ollama /api/embeddings with LUCY_OLLAMA_MODEL.

    Results are cached in a bounded thread-safe dict keyed by SHA-256 of
    the text to avoid redundant calls for identical prompts.

    Args:
        text: Text to embed.
        timeout: HTTP timeout in seconds (only used for Ollama fallback).

    Returns:
        List of floats (the embedding vector), or None on failure.
    """
    if not text:
        return None

    # Prefer MiniLM-L6-v2: it is always available in the venv and independent
    # of whichever generative model is loaded in Ollama.
    minilm = _get_minilm_model()
    if minilm is not None:
        try:
            import numpy as np

            vec = minilm.encode(text.strip(), convert_to_numpy=True, normalize_embeddings=True)
            if isinstance(vec, np.ndarray):
                return vec.tolist()
            return list(vec)
        except Exception as exc:
            logger.debug(f"MiniLM embedding failed: {exc}")

    model = os.environ.get("LUCY_OLLAMA_MODEL", "local-lucy")
    key = hashlib.sha256(f"{text.strip()}:{model}".encode("utf-8")).hexdigest()
    with _EMBEDDING_CACHE_LOCK:
        cached = _EMBEDDING_CACHE.pop(key, None)
        if cached is not None:
            # Move to end (LRU) and return
            _EMBEDDING_CACHE[key] = cached
            return cached

    payload = {
        "model": model,
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
                with _EMBEDDING_CACHE_LOCK:
                    _EMBEDDING_CACHE[key] = embedding
                    while len(_EMBEDDING_CACHE) > _EMBEDDING_CACHE_MAXSIZE:
                        _EMBEDDING_CACHE.pop(next(iter(_EMBEDDING_CACHE)))
                return embedding
            return None
    except Exception as exc:
        logger.debug(f"Embedding call failed: {exc}")
        return None


def get_embedding_cached(text: str) -> list[float] | None:
    """Return a cached embedding for *text*, computing it via Ollama if necessary."""
    return _get_embedding(text)


def _clear_embedding_cache() -> None:
    """Clear the in-process embedding cache. Useful for tests."""
    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE.clear()


def _get_embedding_cached(text: str, embedding: list[float] | None = None) -> list[float] | None:
    """Return *embedding* if provided, otherwise compute via _get_embedding()."""
    if embedding is not None:
        return embedding
    return _get_embedding(text)


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


def _find_relevant_sessions_with_diagnostics_impl(
    query: str,
    query_embedding: list[float] | None = None,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Internal implementation with optional pre-computed query embedding."""
    diagnostics: dict[str, Any] = {
        "threshold_applied": 0.0,
        "gap_applied": None,
        "embedding_count": 0,
        "candidates_above_threshold": 0,
        "top_score": None,
        "second_score": None,
        "top_gap": None,
        "gap_blocked": False,
    }

    if not query.strip():
        return [], diagnostics

    threshold = (
        similarity_threshold if similarity_threshold is not None else _similarity_threshold()
    )
    limit = top_k if top_k is not None else _max_injected_sessions()
    gap = _top_gap_threshold()

    diagnostics["threshold_applied"] = threshold
    diagnostics["gap_applied"] = gap

    query_vector = _get_embedding_cached(query.strip(), query_embedding)
    if query_vector is None:
        return [], diagnostics

    embeddings = _load_all_summary_embeddings()
    diagnostics["embedding_count"] = len(embeddings)
    if not embeddings:
        return [], diagnostics

    # Fetch summary texts
    conn = _get_connection()
    session_ids = [sid for sid, _ in embeddings]
    if not session_ids:
        return [], diagnostics

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
            scored.append(
                {
                    "session_id": session_id,
                    "summary_text": summary_map[session_id],
                    "similarity": sim,
                }
            )

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    diagnostics["candidates_above_threshold"] = len(scored)

    if scored:
        diagnostics["top_score"] = scored[0]["similarity"]
        if len(scored) >= 2:
            diagnostics["second_score"] = scored[1]["similarity"]
            diagnostics["top_gap"] = scored[0]["similarity"] - scored[1]["similarity"]
            if gap is not None and diagnostics["top_gap"] < gap:
                diagnostics["gap_blocked"] = True
                return [], diagnostics

    return scored[:limit], diagnostics


def find_relevant_sessions_with_diagnostics(
    query: str,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Find past sessions whose summaries are semantically similar to the query.

    Returns both the filtered results and diagnostic telemetry about the
    semantic search (top score, gap, whether gap blocked, etc.).

    Uses environment-configured thresholds if parameters are not provided.
    """
    return _find_relevant_sessions_with_diagnostics_impl(query, None, top_k, similarity_threshold)


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
    results, _ = find_relevant_sessions_with_diagnostics(query, top_k, similarity_threshold)
    return results


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

# Temporal uses of "this" (e.g., "this evening") are not conversational
# references, so exclude them from deep-context detection.
_TEMPORAL_THIS_RE = re.compile(
    r"\bthis\s+(?:evening|morning|afternoon|night|today|tonight|week|month|year|"
    r"weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)

_FOLLOWUP_RE = re.compile(
    r"\b("
    r"what about|how about|tell me more|elaborate|continue|go on|expand on|"
    r"follow up|follow-up|more details|more info|why|how come|and\?|ok and|"
    r"back to|return(?:ing)? to|as for|speaking of|regarding|with regard to|in regards to|"
    r"one more thing|one more question|another thing|another question|"
    r"also|plus|in addition|additionally|moreover|furthermore"
    r")\b",
    re.IGNORECASE,
)

# Vague follow-up phrases that intentionally reference the immediately preceding
# conversation but do not name a topic.  These queries must keep recent turns
# and must NOT be answered from a possibly-stale session summary.
# Anchored to the whole utterance (with optional trailing "please" and
# punctuation) so that standalone requests like "Full details please." match,
# while topic-bearing queries like "What are the full details of X?" do not.
_VAGUE_FOLLOWUP_RE = re.compile(
    r"^(?:\s*)(?:"
    r"tell me more|elaborate|continue|go on|expand on|"
    r"follow up|follow-up|more details|more info|"
    r"why|how come|and\?|ok and|"
    r"full details|all details|complete details|all the details|"
    r"give me (?:the )?details|details please|tell me everything"
    r")(?:\s+please)?[\s\W]*$",
    re.IGNORECASE,
)

# Short affirmations that continue the prior turn (e.g. "Yes, please.",
# "Sure", "Go ahead").  These carry no topic of their own and must keep context.
_AFFIRMATION_FOLLOWUP_RE = re.compile(
    r"^(?:\s*)(?:"
    r"yes|yeah|yep|yup|sure|absolutely|definitely|exactly|right|correct|"
    r"ok|okay|please|go ahead|do it"
    r")(?:\s*[,.]?\s*please)?[\s\W]*$",
    re.IGNORECASE,
)

# Explicit continuation markers that may be followed by a topic phrase.
# "Back to what we discussed earlier", "One more thing about relativity",
# "What about this evening?" and "Also, why does it work?" all keep context.
_EXPLICIT_CONTINUATION_RE = re.compile(
    r"^(?:\s*)(?:"
    r"(?:and |but |so )?"
    r"(?:"
    r"what about|how about|"
    r"back to|return(?:ing)? to|as for|speaking of|regarding|with regard to|in regards to|"
    r"one more thing|one more question|another thing|another question|"
    r"also|plus|in addition|additionally|moreover|furthermore"
    r")"
    r")\b",
    re.IGNORECASE,
)

# Standalone greetings and social openers should never pull deep context.
_GREETING_PATTERNS = [
    re.compile(r"^(?:hi+|hello|hey|greetings|howdy|yo|sup)$", re.IGNORECASE),
    re.compile(r"^good\s+(?:morning|afternoon|evening|night|day)$", re.IGNORECASE),
    re.compile(
        r"^how\s+(?:are|is|do|have|was|were)\s+(?:you|it|things|everything)(?:\s+doing)?$",
        re.IGNORECASE,
    ),
    re.compile(r"^how'?s\s+(?:it|things|everything)(?:\s+going)?$", re.IGNORECASE),
    re.compile(r"^what'?s\s+up$", re.IGNORECASE),
    re.compile(r"^how\s+are\s+things$", re.IGNORECASE),
    re.compile(r"^how\s+do\s+you\s+do$", re.IGNORECASE),
    # Spanish
    re.compile(r"^hola$", re.IGNORECASE),
    re.compile(r"^buenos?\s+(?:dias|tardes|noches)$", re.IGNORECASE),
    re.compile(r"^que\s+tal$", re.IGNORECASE),
    re.compile(r"^como\s+estas?$", re.IGNORECASE),
    # French
    re.compile(r"^bonjour$", re.IGNORECASE),
    re.compile(r"^bonsoir$", re.IGNORECASE),
    re.compile(r"^salut$", re.IGNORECASE),
    re.compile(r"^ca\s+va$", re.IGNORECASE),
    re.compile(r"^comment\s+(?:allez[- ]vous|vas?[- ]tu)$", re.IGNORECASE),
    # German
    re.compile(r"^hallo$", re.IGNORECASE),
    re.compile(r"^guten\s+(?:tag|morgen|abend|nachmittag)$", re.IGNORECASE),
    re.compile(r"^wie\s+geht(?:'s| es dir| es ihnen)$", re.IGNORECASE),
    # Italian
    re.compile(r"^ciao$", re.IGNORECASE),
    re.compile(r"^buongiorno$", re.IGNORECASE),
    re.compile(r"^buonasera$", re.IGNORECASE),
    re.compile(r"^come\s+stai$", re.IGNORECASE),
    # Portuguese
    re.compile(r"^ola$", re.IGNORECASE),
    re.compile(r"^bom\s+dia$", re.IGNORECASE),
    re.compile(r"^boa\s+(?:tarde|noite)$", re.IGNORECASE),
    re.compile(r"^tudo\s+bem$", re.IGNORECASE),
]


def _is_greeting(query: str) -> bool:
    """Return True when the query is a standalone greeting or social opener."""
    q = query.strip()
    if not q:
        return False
    # Strip optional name / addressee and temporal suffixes so that
    # "Hi Lucy, how are you this evening?" is still detected as a greeting.
    q = re.sub(r"\b(?:lucy|there|friend|buddy|mate)\b", "", q, flags=re.IGNORECASE)
    q = re.sub(
        r"\bthis\s+(?:evening|morning|afternoon|night|today|tonight|week|month|year)\b",
        "",
        q,
        flags=re.IGNORECASE,
    )
    q = re.sub(r"\b(?:tonight|today|now)\b", "", q, flags=re.IGNORECASE)
    # Remove punctuation and collapse whitespace
    q = re.sub(r"[^\w\s]", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return any(p.search(q) for p in _GREETING_PATTERNS)


def _strip_greeting_prefix(query: str) -> str:
    """Remove a leading greeting word and any following separator/punctuation."""
    q = query.strip()
    if not q:
        return q
    q = re.sub(
        r"^(?:hi+|hello|hey|greetings|howdy|yo|sup|hola|buenos?\s+(?:dias|tardes|noches)|"
        r"que\s+tal|como\s+estas?|bonjour|bonsoir|salut|ca\s+va|"
        r"comment\s+(?:allez[- ]vous|vas?[- ]tu)|hallo|guten\s+(?:tag|morgen|abend|nachmittag)|"
        r"wie\s+geht(?:'s| es dir| es ihnen)|ciao|buongiorno|buonasera|come\s+stai|"
        r"ola|bom\s+dia|boa\s+(?:tarde|noite)|tudo\s+bem)"
        r"(?:\s+\w+)?[\s\W]*",
        "",
        q,
        flags=re.IGNORECASE,
    )
    return q.strip()


def _has_explicit_continuation(query: str) -> bool:
    """Return True if the query contains an explicit continuation marker.

    Allows for a leading greeting prefix such as 'Hello—one more thing...'.
    """
    return bool(_EXPLICIT_CONTINUATION_RE.search(_strip_greeting_prefix(query)))


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
    # Standalone greetings/social openers are self-contained.
    if _is_greeting(q):
        return "shallow"
    # Temporal "this" does not reference prior conversation.
    if _TEMPORAL_THIS_RE.search(q):
        q_no_temporal = _TEMPORAL_THIS_RE.sub("", q)
        if not _DEEP_CONTEXT_RE.search(q_no_temporal):
            return "shallow"
    # Short pronoun-heavy queries are almost always context-dependent
    if len(q) <= 15 and _DEEP_CONTEXT_RE.search(q):
        return "deep"
    if _FOLLOWUP_RE.search(q) or _VAGUE_FOLLOWUP_RE.search(q) or _has_explicit_continuation(q):
        return "deep"
    if _DEEP_CONTEXT_RE.search(q):
        return "deep"
    return "shallow"


def _is_vague_followup(query: str) -> bool:
    """
    Return True when the query is a vague continuation of the prior turn.

    Such queries rely on recent conversation context to make sense and must
    never be answered from a stale session summary or treated as a topic shift.
    """
    q = query.strip()
    if not q:
        return False
    if _VAGUE_FOLLOWUP_RE.search(q):
        return True
    if _AFFIRMATION_FOLLOWUP_RE.search(q):
        return True
    if _has_explicit_continuation(q):
        return True
    # Short pronoun-heavy queries (already deep-context) are also vague follow-ups.
    if len(q) <= 15 and _DEEP_CONTEXT_RE.search(q):
        return True
    return False


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


def _topic_shift_threshold() -> float:
    """Return configured topic-shift cosine-similarity threshold (default 0.50)."""
    raw = os.environ.get("LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD", "0.50").strip()
    try:
        v = float(raw)
        return max(0.0, min(1.0, v))
    except ValueError:
        return 0.50


def _topic_shift_max_age_seconds() -> float:
    """Return configured max age (seconds) for topic-shift comparison (default 900)."""
    raw = os.environ.get("LUCY_MEMORY_TOPIC_SHIFT_MAX_AGE_SECONDS", "900").strip()
    try:
        v = float(raw)
        return max(0.0, v)
    except ValueError:
        return 900.0


def _parse_iso_timestamp(ts: str | None) -> float | None:
    """Parse an ISO-8601 timestamp string into epoch seconds, or None on failure."""
    if not ts:
        return None
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return None


def _is_topic_shift_impl(
    current_query: str,
    previous_text: str,
    current_embedding: list[float] | None = None,
    previous_created_at: str | None = None,
) -> bool:
    """Internal implementation with optional pre-computed current query embedding."""
    if not current_query.strip() or not previous_text.strip():
        return False
    # Vague follow-ups intentionally reference prior context; never treat them
    # as a topic shift regardless of embedding similarity.
    if _is_vague_followup(current_query):
        return False
    # Very short prior turns carry no meaningful topic to pollute a new query.
    # Skip the embedding gate for them so innocuous placeholders like "Q1" do
    # not trigger a false topic shift against a standalone follow-up question.
    if len(previous_text.strip()) < 12:
        return False
    # After a long pause the last user turn is a poor anchor for a similarity
    # gate; short follow-ups should keep context rather than be rejected.
    previous_ts = _parse_iso_timestamp(previous_created_at)
    if previous_ts is not None:
        now = time.time()
        if now - previous_ts > _topic_shift_max_age_seconds():
            return False
    try:
        current_emb = _get_embedding_cached(current_query.strip(), current_embedding)
        previous_emb = _get_embedding(previous_text.strip())
        if current_emb is None or previous_emb is None:
            return False
        sim = _cosine_similarity(current_emb, previous_emb)
        return sim < _topic_shift_threshold()
    except Exception:
        return False


def _is_topic_shift(current_query: str, previous_text: str) -> bool:
    """
    Detect a topic shift by comparing embeddings of the current query
    and the previous user turn.

    Returns:
        True if the cosine similarity is below the topic-shift threshold
        (meaning the topics are dissimilar and context should not be injected).
        False on any error or when similarity is above threshold.
    """
    return _is_topic_shift_impl(current_query, previous_text)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


def assemble_context_with_telemetry(
    current_session_id: str = "default",
    max_chars: int = 500,
    recent_turn_limit: int = 4,
    other_summary_limit: int = 2,
    query: str = "",
    depth: str = "auto",
    mode: str = "local",
) -> tuple[str, dict[str, str]]:
    """
    Assemble the session memory context string with telemetry.

    LOCAL mode (default):
        - Shallow: recent turns only
        - Deep: current session summary + recent turns
        - NEVER injects other sessions (no cross-session recall)

    AUGMENTED mode:
        - Deep: semantic recall + current summary + recent turns + other sessions
        - Cross-session recall permitted with strict thresholds

    Returns:
        Tuple of (context_string, telemetry_dict).
        telemetry_dict contains:
            memory_context_used: "true" or "false"
            memory_mode_used: "local", "augmented", or "none"
            memory_depth_used: "shallow", "deep", or "none"
            memory_top_score: similarity of top match or "none"
            memory_session_injected: session_id of top injected match or "none"
            memory_top_gap: gap between top 1 and top 2 or "none"
    """
    telemetry: dict[str, str] = {
        "memory_context_used": "false",
        "memory_mode_used": "none",
        "memory_depth_used": "none",
        "memory_top_score": "none",
        "memory_session_injected": "none",
        "memory_top_gap": "none",
    }

    if depth == "auto":
        depth = _detect_context_depth(query)

    parts: list[str] = []

    # SHALLOW (both modes): recent turns only. Fast, low risk.
    if depth == "shallow":
        recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
        if recent_turns:
            # Topic-shift gate: don't inject stale context for radically different queries
            if query.strip():
                last_user_text, last_user_created_at = next(
                    (
                        (t["text"], t.get("created_at"))
                        for t in reversed(recent_turns)
                        if t["role"] == "user"
                    ),
                    ("", None),
                )
                if last_user_text:
                    query_embedding = _get_embedding(query.strip())
                    if _is_topic_shift_impl(
                        query,
                        last_user_text,
                        query_embedding,
                        previous_created_at=last_user_created_at,
                    ):
                        telemetry["memory_topic_shift_detected"] = "true"
                        return "", telemetry
            context = _truncate_at_turn_boundary(format_turns_for_prompt(recent_turns), max_chars)
            telemetry["memory_context_used"] = "true"
            telemetry["memory_mode_used"] = mode
            telemetry["memory_depth_used"] = "shallow"
            return context, telemetry
        return "", telemetry

    # DEEP — LOCAL: current session only. No cross-session recall.
    if mode == "local":
        recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
        vague_followup = _is_vague_followup(query)
        # Topic-shift gate: don't inject stale context for radically different queries.
        # Vague follow-ups intentionally reference prior context, so bypass the gate.
        if query.strip() and recent_turns and not vague_followup:
            last_user_text, last_user_created_at = next(
                (
                    (t["text"], t.get("created_at"))
                    for t in reversed(recent_turns)
                    if t["role"] == "user"
                ),
                ("", None),
            )
            if last_user_text:
                query_embedding = _get_embedding(query.strip())
                if _is_topic_shift_impl(
                    query, last_user_text, query_embedding, previous_created_at=last_user_created_at
                ):
                    telemetry["memory_topic_shift_detected"] = "true"
                    return "", telemetry
        # Vague follow-ups must use recent turns, not a possibly-stale summary.
        if not vague_followup:
            current_summary = get_session_summary(current_session_id)
            if current_summary:
                parts.append(f"Session summary: {current_summary}")
        if recent_turns:
            parts.append(format_turns_for_prompt(recent_turns))
        if not parts:
            return "", telemetry
        context = "\n\n".join(parts)
        context = _truncate_at_turn_boundary(context, max_chars)
        telemetry["memory_context_used"] = "true"
        telemetry["memory_mode_used"] = "local"
        telemetry["memory_depth_used"] = "deep"
        return context, telemetry

    # DEEP — AUGMENTED: full context assembly with cross-session recall
    included_session_ids: set[str] = set()
    top_session: str | None = None

    query_embedding = _get_embedding(query.strip()) if query.strip() else None

    # 1. Semantic recall (uses env-configured thresholds)
    if query.strip():
        try:
            relevant, diag = _find_relevant_sessions_with_diagnostics_impl(query, query_embedding)
            if diag.get("top_score") is not None:
                telemetry["memory_top_score"] = f"{diag['top_score']:.3f}"
            if diag.get("top_gap") is not None:
                telemetry["memory_top_gap"] = f"{diag['top_gap']:.3f}"
            for item in relevant:
                text = item["summary_text"]
                if len(text) > 150:
                    text = text[:150].rsplit(" ", 1)[0] + "..."
                parts.append(f"Related session: {text}")
                included_session_ids.add(item["session_id"])
                if top_session is None:
                    top_session = item["session_id"]
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

    # 3. Current session summary and recent turns (topic-shift gated)
    recent_turns = get_recent_turns(current_session_id, limit=recent_turn_limit)
    vague_followup = _is_vague_followup(query)
    topic_shift = False
    if query.strip() and recent_turns and not vague_followup:
        last_user_text, last_user_created_at = next(
            (
                (t["text"], t.get("created_at"))
                for t in reversed(recent_turns)
                if t["role"] == "user"
            ),
            ("", None),
        )
        if last_user_text and _is_topic_shift_impl(
            query, last_user_text, query_embedding, previous_created_at=last_user_created_at
        ):
            topic_shift = True
            telemetry["memory_topic_shift_detected"] = "true"
    if not topic_shift:
        current_summary = get_session_summary(current_session_id)
        if current_summary and not vague_followup:
            parts.append(f"Session summary: {current_summary}")
        if recent_turns:
            parts.append(format_turns_for_prompt(recent_turns))

    if not parts:
        return "", telemetry

    context = "\n\n".join(parts)
    context = _truncate_at_turn_boundary(context, max_chars)

    telemetry["memory_context_used"] = "true"
    telemetry["memory_mode_used"] = "augmented"
    telemetry["memory_depth_used"] = "deep"
    if top_session:
        telemetry["memory_session_injected"] = top_session
    return context, telemetry


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
    context, _ = assemble_context_with_telemetry(
        current_session_id=current_session_id,
        max_chars=max_chars,
        recent_turn_limit=recent_turn_limit,
        other_summary_limit=other_summary_limit,
        query=query,
        depth=depth,
        mode=mode,
    )
    return context


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Local Lucy memory service CLI")
    parser.add_argument(
        "--clear-identity", action="store_true", help="Clear the current user identity"
    )
    parser.add_argument(
        "--set-identity", type=str, default=None, help="Set the current user identity (Michael)"
    )
    parser.add_argument(
        "--strip-thinking",
        action="store_true",
        help="Strip <think> blocks from all stored turns/summaries",
    )
    args = parser.parse_args()

    if args.clear_identity:
        clear_current_user_identity()
        print("Current user identity cleared.")
    elif args.set_identity:
        row_id = set_current_user_identity(args.set_identity)
        print(f"Current user identity set to: {args.set_identity} (row {row_id})")
    elif args.strip_thinking:
        turns_updated, summaries_updated, summaries_deleted = strip_thinking_blocks_from_db()
        print(
            f"Stripped <think> blocks: {turns_updated} turn(s) updated, "
            f"{summaries_updated} summary(s) updated, {summaries_deleted} summary(s) removed."
        )
    else:
        parser.print_help()
