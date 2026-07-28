"""Memory-aware routing gate and feedback-buffer cache."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

_FEEDBACK_BUF_CACHE: dict | None = None
_FEEDBACK_BUF_MTIME: float = 0.0
_FEEDBACK_BUF_PATH: Path | None = None

# Patterns that indicate the query references prior conversation context.
# STRONG markers are specific enough to trigger override on their own.
# WEAK markers (common pronouns/adverbs) are too broad and cause false positives
# on standalone queries; they only count inside _memory_routing_gate which checks
# for actual conversation history in SQLite.
_MEMORY_FOLLOWUP_STRONG_RE = re.compile(
    r"\b(him|her|they|them|their|those|the same|"
    r"earlier|previous|before|above|mentioned|discussed|agreed|decided|said|stated)\b",
    re.IGNORECASE,
)

_MEMORY_FOLLOWUP_RE = re.compile(
    r"\b(him|her|it|that|this|they|them|their|those|the same|such|so|thus|there|then|"
    r"earlier|previous|before|above|mentioned|discussed|agreed|decided|said|stated)\b",
    re.IGNORECASE,
)

_MEMORY_EXPLICIT_RECALL_RE = re.compile(
    r"\b(what did I say|what was my|what is my|remind me|do you remember|"
    r"did I tell you|what did we discuss|what did I ask|what did you say|"
    r"repeat that|say that again|what about that|how about that)\b",
    re.IGNORECASE,
)

# Continuation prompts like "more details" or "tell me more" should inherit the
# previous route (especially AUGMENTED/EVIDENCE/NEWS) rather than dropping to LOCAL.
_CONTINUATION_FOLLOWUP_RE = re.compile(
    r"\b(tell me more|elaborate|continue|go on|expand on|follow up|"
    r"more details|more info|more context|explain more|can you give me more)\b",
    re.IGNORECASE,
)

# Live-data keywords that should NOT be overridden even with follow-up markers
_LIVE_DATA_KEYWORDS = (
    "weather",
    "forecast",
    "temperature",
    "rain",
    "snow",
    "sunny",
    "cloudy",
    "windy",
    "news",
    "headlines",
    "latest news",
    "breaking",
    "time is it",
    "time in",
    "current time",
    "what time",
    "stock",
    "price",
    "bitcoin",
    "crypto",
    "trading",
    "market",
    "live",
    "today",
    "week",
    "month",
    "year",
)


def _load_feedback_buffer(path: Path) -> dict:
    """Load and cache feedback buffer JSON by mtime."""
    global _FEEDBACK_BUF_CACHE, _FEEDBACK_BUF_MTIME, _FEEDBACK_BUF_PATH
    try:
        mtime = path.stat().st_mtime
        if (
            _FEEDBACK_BUF_CACHE is not None
            and _FEEDBACK_BUF_PATH == path
            and _FEEDBACK_BUF_MTIME == mtime
        ):
            return _FEEDBACK_BUF_CACHE

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _FEEDBACK_BUF_CACHE = data
        _FEEDBACK_BUF_MTIME = mtime
        _FEEDBACK_BUF_PATH = path
        return data
    except Exception:
        return {}


def _memory_routing_gate(
    query: str, embedding_route: str, session_id: str = "default"
) -> str | None:
    """
    Lightweight memory-aware routing gate.

    Returns "LOCAL" if memory should take precedence over a live-data route,
    or None to keep the embedding router's decision.

    Rules:
    1. Memory must be enabled (LUCY_SESSION_MEMORY == "1").
    2. Query must look like it needs prior context (pronouns, follow-ups, explicit recall).
    3. There must be recent conversation turns in SQLite.
    4. Only overrides live-data routes (WEATHER, NEWS, TIME, STOCKS, AUGMENTED).
    5. If query contains live-data keywords alongside follow-up markers, preserve embedding decision.
    """
    # Fast reject — memory disabled, BUT explicit memory recall queries
    # should route LOCAL so the model can say "memory is disabled" in
    # first person instead of wasting an augmented provider call.
    if os.environ.get("LUCY_SESSION_MEMORY", "0") != "1":
        q = query.strip()
        if q and _MEMORY_EXPLICIT_RECALL_RE.search(q):
            return "LOCAL"
        return None

    # Fast reject — kill switch
    if os.environ.get("LUCY_MEMORY_GATE", "1") == "0":
        return None

    # Fast reject — already LOCAL (memory will be used in execution anyway)
    if embedding_route == "LOCAL":
        return None

    # Fast reject — not a follow-up or recall query
    q = query.strip()
    if not q:
        return None

    has_followup = bool(_MEMORY_FOLLOWUP_RE.search(q) or _MEMORY_EXPLICIT_RECALL_RE.search(q))
    if not has_followup:
        return None

    # Live-data guard: if query contains live-data keywords AND follow-up markers,
    # preserve the embedding router's decision (e.g. "What about the weather?")
    q_lower = q.lower()
    has_live_data = any(kw in q_lower for kw in _LIVE_DATA_KEYWORDS)
    if has_live_data:
        return None

    # Lightweight memory check: fetch recent turns from SQLite
    has_memory_context = False
    try:
        from memory.memory_service import get_recent_turns

        turns = get_recent_turns(session_id=session_id, limit=2)
        has_memory_context = bool(turns)
    except Exception:
        pass

    if not has_memory_context:
        # Explicit memory recall with no context: route LOCAL so the model
        # can say "I don't have memory" in first person instead of letting
        # an augmented provider hallucinate a fake conversation.
        if _MEMORY_EXPLICIT_RECALL_RE.search(q):
            return "LOCAL"
        return None

    # All conditions met — override to LOCAL
    return "LOCAL"
