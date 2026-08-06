#!/usr/bin/env python3
"""

Local Lucy Router — Python-Native Main Orchestrator

Single authoritative entry point for all execution surfaces:
- CLI: `python -m router_py.main "question"`
- HMI: `runtime_bridge._run_submit_request_direct()` → `run()`
- Voice: `streaming_voice.py`, `voice_tool.py`, `runtime_voice.py` → `run()`

Architecture (post Stage 9):
    run() ──→ execute_plan_python() ──→ request_pipeline.process()
                                            │
    ├─ classify_intent() ──→ select_route() ─┤
    │                                          │
    ├─ provider_resolver.apply_provider() ────┤
    │                                          │
    └─ ExecutionEngine.execute() ─────────────┘

All shell/parity fallback paths have been removed. Python-native is
authoritative.

State is loaded from `current_state.json` via `ensure_control_env()`
before classification. Memory persistence, feedback detection, and
outcome telemetry are handled in the wrapper, not in the engine.
"""

from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()  # Load .env file for API keys

import argparse
import fcntl
import json
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py import request_pipeline
from router_py.execution_engine import DEFAULT_CHAT_MEMORY_FILE
from router_py.logging_config import setup_logging
from router_py.request_constraints import extract_request_constraints
from router_py.request_types import RouterOutcome
from router_py.security_guard import validate_input
from router_py.shutdown_handler import install as install_shutdown_handler
from router_py.shutdown_handler import register_closeable
from router_py.structured_logging import get_structured_logger
from router_py.utils import sha256_text
from tools.xdg_paths import lucy_runtime_namespace_root

# Configuration
DEFAULT_TIMEOUT = 130


# ============================================================================
# Unified Entry Point
# ============================================================================


def run(
    question: str,
    *,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
    surface: str = "cli",
    augmented_direct_once: bool = False,
    self_review: bool = False,
    context: dict[str, Any] | None = None,
    model: str | None = None,
) -> RouterOutcome:
    """
    Unified entry point for all execution surfaces (HMI, CLI, voice).

    This is the single entry point that runtime_bridge.py, CLI, and voice
    pipelines should call. It handles state resolution, feedback detection,
    classification, routing, execution, memory persistence, and telemetry.

    Args:
        question: The user's query text
        policy: Augmentation policy (disabled, fallback_only, direct_allowed)
        timeout: Request timeout in seconds
        surface: Origin surface (hmi, cli, voice)
        augmented_direct_once: Force augmented route for this query
        self_review: Whether this is a self-review request
        context: Extra execution context (merged into engine context)
        model: Override LLM model (e.g., "local-lucy-llama31" for voice safety)

    Returns:
        RouterOutcome with status, route, provider, response_text, etc.
    """
    return execute_plan_python(
        question=question,
        policy=policy,
        timeout=timeout,
        surface=surface,
        augmented_direct_once=augmented_direct_once,
        self_review=self_review,
        context=context,
        model=model,
    )


# Configuration


def resolve_state_dir(root: Path) -> Path:
    """Resolve state directory, respecting LUCY_SHARED_STATE_NAMESPACE like shell does."""
    namespace = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if namespace:
        # Sanitize: s/[^A-Za-z0-9._-]+/_/g; s/^_+|_+$//
        sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", namespace)
        sanitized = sanitized.strip("_")
        if sanitized:
            return root / "state" / "namespaces" / sanitized
    # Default: use "default" namespace (consistent with shell behavior)
    return root / "state" / "namespaces" / "default"


# State files (same as runtime_request.py uses)
STATE_DIR = resolve_state_dir(ROOT_DIR)
LAST_ROUTE_FILE = STATE_DIR / "last_route.env"
LAST_OUTCOME_FILE = STATE_DIR / "last_outcome.env"


def _write_outcome_telemetry(
    outcome: RouterOutcome,
    question: str,
    execution_time_ms: int,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Write outcome telemetry to last_outcome.env (mirror shell path)."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        lines = [
            f"OUTCOME_CODE={outcome.outcome_code}",
            f"FINAL_MODE={outcome.route}",
            f"PROVIDER={outcome.provider}",
            f"PROVIDER_USAGE_CLASS={outcome.provider_usage_class}",
            f"INTENT_FAMILY={outcome.intent_family}",
            f"CONFIDENCE={outcome.confidence}",
            f"EXECUTION_TIME_MS={execution_time_ms}",
            f"STATUS={outcome.status}",
            f"QUESTION={question}",
            f"TRUST_CLASS={'unverified' if outcome.route in ('AUGMENTED', 'NEWS', 'WEATHER', 'TIME') else 'local'}",
        ]
        # Keel visibility
        meta = metadata or {}
        if "keel_status" in meta:
            lines.append(f"KEEL_STATUS={meta['keel_status']}")
            lines.append(f"KEEL_PATH={meta.get('keel_path', '')}")
            lines.append(f"KEEL_VERSION={meta.get('keel_version', '')}")
            lines.append(f"KEEL_SHA256={meta.get('keel_sha256', '')}")
            lines.append(f"KEEL_ERROR={meta.get('keel_error', '')}")
        LAST_OUTCOME_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def load_state_from_file() -> dict[str, Any]:
    """Load control state from state file (fallback when env vars not set).

    Respects LUCY_RUNTIME_STATE_FILE and LUCY_RUNTIME_NAMESPACE_ROOT env vars
    to stay in sync with runtime_control.py and the HMI state store.
    """
    import json

    candidates: list[Path] = []

    # 1. Explicit env var override (same contract as runtime_control.py)
    env_path = os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())

    # 2. Namespace-root env var
    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        candidates.append(Path(namespace_root).expanduser() / "state" / "current_state.json")

    # 3. Canonical XDG namespace
    candidates.append(lucy_runtime_namespace_root() / "state" / "current_state.json")

    # 4. Legacy fallback (project root state dir)
    candidates.append(ROOT_DIR / "state" / "state" / "current_state.json")

    for state_file in candidates:
        try:
            if state_file.exists():
                with open(state_file) as f:
                    return json.load(f)
        except Exception:
            pass

    return {}


def ensure_control_env() -> None:
    """
    Ensure control environment variables reflect the current state file.

    The state file is the authoritative source when no explicit environment
    override is present (e.g. from the HMI).  Explicit environment values are
    preserved so tests and CLI one-shots can override state without editing
    current_state.json.
    """
    # Snapshot explicit environment overrides before touching them.
    env_overrides = {
        "LUCY_EVIDENCE_ENABLED": os.environ.get("LUCY_EVIDENCE_ENABLED"),
        "LUCY_ENABLE_INTERNET": os.environ.get("LUCY_ENABLE_INTERNET"),
        "LUCY_AUGMENTATION_POLICY": os.environ.get("LUCY_AUGMENTATION_POLICY"),
        "LUCY_AUGMENTED_PROVIDER": os.environ.get("LUCY_AUGMENTED_PROVIDER"),
        "LUCY_CONVERSATION_MODE_FORCE": os.environ.get("LUCY_CONVERSATION_MODE_FORCE"),
        "LUCY_SESSION_MEMORY": os.environ.get("LUCY_SESSION_MEMORY"),
        "LUCY_VOICE_ENABLED": os.environ.get("LUCY_VOICE_ENABLED"),
        "LUCY_MODEL": os.environ.get("LUCY_MODEL"),
        "LUCY_LOCAL_MODEL": os.environ.get("LUCY_LOCAL_MODEL"),
        "LUCY_GEMMA4_SMART_ROUTING": os.environ.get("LUCY_GEMMA4_SMART_ROUTING"),
    }

    state = load_state_from_file()
    if not state:
        # Apply safe defaults when no state file exists, without clobbering
        # explicit environment overrides.
        defaults = {
            "LUCY_EVIDENCE_ENABLED": "1",
            "LUCY_ENABLE_INTERNET": "1",
            "LUCY_AUGMENTATION_POLICY": "disabled",
            "LUCY_AUGMENTED_PROVIDER": "wikipedia",
            "LUCY_CONVERSATION_MODE_FORCE": "0",
            "LUCY_SESSION_MEMORY": "0",
            "LUCY_VOICE_ENABLED": "0",
            "LUCY_MODEL": "local-lucy-llama31",
            "LUCY_LOCAL_MODEL": "local-lucy-llama31",
            "LUCY_GEMMA4_SMART_ROUTING": "0",
        }
        for key, default in defaults.items():
            if env_overrides.get(key) is None:
                os.environ[key] = default
        return

    evidence = state.get("evidence", "off")
    if env_overrides.get("LUCY_EVIDENCE_ENABLED") is None:
        os.environ["LUCY_EVIDENCE_ENABLED"] = "1" if evidence in ("on", "true", "1") else "0"
    if env_overrides.get("LUCY_ENABLE_INTERNET") is None:
        # Mirror evidence for the legacy internet flag.
        os.environ["LUCY_ENABLE_INTERNET"] = os.environ.get("LUCY_EVIDENCE_ENABLED", "0")

    policy = state.get("augmentation_policy", "disabled")
    if env_overrides.get("LUCY_AUGMENTATION_POLICY") is None:
        os.environ["LUCY_AUGMENTATION_POLICY"] = policy

    provider = state.get("augmented_provider", "wikipedia")
    if env_overrides.get("LUCY_AUGMENTED_PROVIDER") is None:
        os.environ["LUCY_AUGMENTED_PROVIDER"] = provider

    conv = state.get("conversation", "off")
    if env_overrides.get("LUCY_CONVERSATION_MODE_FORCE") is None:
        os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1" if conv in ("on", "true", "1") else "0"

    mem = state.get("memory", "off")
    if env_overrides.get("LUCY_SESSION_MEMORY") is None:
        os.environ["LUCY_SESSION_MEMORY"] = "1" if mem in ("on", "true", "1") else "0"

    voice = state.get("voice", "off")
    if env_overrides.get("LUCY_VOICE_ENABLED") is None:
        os.environ["LUCY_VOICE_ENABLED"] = "1" if voice in ("on", "true", "1") else "0"

    model = state.get("model", "local-lucy-llama31")
    if env_overrides.get("LUCY_MODEL") is None:
        os.environ["LUCY_MODEL"] = model
    if env_overrides.get("LUCY_LOCAL_MODEL") is None:
        os.environ["LUCY_LOCAL_MODEL"] = model

    gemma4_smart_routing = state.get("gemma4_smart_routing", "off")
    if env_overrides.get("LUCY_GEMMA4_SMART_ROUTING") is None:
        os.environ["LUCY_GEMMA4_SMART_ROUTING"] = (
            "1" if gemma4_smart_routing in ("on", "true", "1") else "0"
        )


def _persist_memory_turn(
    question: str,
    response_text: str,
    session_id: str = "default",
    *,
    constraints: "RequestConstraints | None" = None,
) -> None:
    """Persist a conversation turn to chat memory (SQLite + text file).

    Args:
        question: User query text.
        response_text: Assistant response text.
        session_id: Session identifier.
        constraints: Optional request-scoped capability constraints. When
            ``memory_write`` is explicitly ``False``, persistence is skipped.
    """
    from router_py.request_constraints import RequestConstraints

    if isinstance(constraints, RequestConstraints) and constraints.memory_write is False:
        logging.debug("Skipping memory persistence: memory_write denied by request constraints")
        return

    # Dual-write: SQLite first (best effort)
    try:
        from memory.memory_service import maybe_summarize_session, store_turn

        store_turn("user", question, session_id=session_id)
        store_turn("assistant", response_text, session_id=session_id)
        maybe_summarize_session(session_id=session_id)
    except Exception:
        logging.warning("SQLite memory write failed, falling back to text file", exc_info=True)

    try:
        mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            mem_file = str(lucy_runtime_namespace_root() / "state" / "chat_session_memory.txt")
        mem_path = Path(mem_file).expanduser()
        mem_path.parent.mkdir(parents=True, exist_ok=True)

        from router_py.privacy import strip_untrusted_source_annotations

        assistant_text = strip_untrusted_source_annotations(response_text)
        assistant_text = (
            assistant_text.replace("BEGIN_VALIDATED", " ")
            .replace("END_VALIDATED", " ")
            .replace("\r", " ")
            .replace("\n", " ")
        )
        assistant_text = re.sub(r"\s+", " ", assistant_text).strip()
        if len(assistant_text) > 500:
            assistant_text = assistant_text[:500]

        refusal_patterns = [
            "state the specific question",
            "tell me the practical question",
            "i cannot answer",
            "i'm not able to",
            "i cannot provide",
            "i don't know",
            "error:",
        ]
        assistant_lower = assistant_text.lower()
        if len(assistant_text) < 10 or any(p in assistant_lower for p in refusal_patterns):
            logging.debug("Skipping memory storage for refusal/short response")
            assistant_text = ""

        if assistant_text:
            existing = ""
            try:
                existing = mem_path.read_text(encoding="utf-8")
            except FileNotFoundError:
                pass

            block = f"User: {question.strip()}\nAssistant: {assistant_text}\n\n"
            blocks = [item.strip() for item in re.split(r"\n\s*\n", existing) if item.strip()]
            blocks.append(block.strip())

            max_turns = 6
            trimmed = "\n\n".join(blocks[-max_turns:]).strip()
            if trimmed:
                trimmed += "\n\n"

            mem_path.write_text(trimmed, encoding="utf-8")
    except Exception as e:
        logging.warning(f"Failed to persist chat memory: {e}")


# ---------------------------------------------------------------------------
# Location-fact extraction
# ---------------------------------------------------------------------------

_LOCATION_PATTERNS = [
    re.compile(
        r"(?:\b|^)i\s+(?:live|reside|am\s+located|am\s+based)\s+in\s+(.+?)(?:\.|$|\s+(?:and|but|,|;))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\b|^)my\s+(?:location|address|home\s+town|hometown|city|village|kibbutz)\s+is\s+(.+?)(?:\.|$|\s+(?:and|but|,|;))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\b|^)i\s+moved\s+(?:to|into)\s+(.+?)(?:\.|$|\s+(?:and|but|,|;))",
        re.IGNORECASE,
    ),
]


def _extract_location_fact(
    question: str,
    *,
    constraints: "RequestConstraints | None" = None,
) -> None:
    """Detect a user statement of location and persist it as a fact.

    Examples that trigger storage:
      - "I live in Kibbutz Magal in Israel."
      - "My location is Jerusalem."
      - "I moved to Tel Aviv."

    The fact is stored with category ``location`` so ``_get_current_context``
    and ``_build_prompt`` can use it for location-aware queries.
    """
    from router_py.request_constraints import RequestConstraints

    if isinstance(constraints, RequestConstraints) and constraints.memory_write is False:
        logging.debug("Skipping location extraction: memory_write denied")
        return

    for pattern in _LOCATION_PATTERNS:
        match = pattern.search(question)
        if match:
            location = match.group(1).strip()
            if not location:
                continue
            try:
                from memory.memory_service import store_persistent_fact

                store_persistent_fact(f"User lives in {location}.", category="location")
                logging.info(f"Stored location fact: User lives in {location}.")
            except ImportError:
                try:
                    from tools.memory.memory_service import store_persistent_fact

                    store_persistent_fact(f"User lives in {location}.", category="location")
                    logging.info(f"Stored location fact: User lives in {location}.")
                except Exception as e:
                    logging.warning(f"Failed to store location fact: {e}")
            except Exception as e:
                logging.warning(f"Failed to store location fact: {e}")
            return


# ---------------------------------------------------------------------------
# Search-imperative anaphora resolution
# ---------------------------------------------------------------------------

# Bare imperatives that ask Lucy to run a web search without specifying a topic.
# When these appear immediately after a web-route exchange, inherit the prior
# topic instead of routing LOCAL and denying the capability.
_SEARCH_TOOL_IMPERATIVE_PATTERN = re.compile(
    r"^(?:please\s+)?(?:use\s+(?:duckduckgo|ddg|google|bing)\s+(?:search|to\s+search)|"
    r"(?:run|do|perform)\s+(?:a\s+)?(?:duckduckgo|ddg|google|bing|web)\s+search|"
    r"search\s+(?:with|using)\s+(?:duckduckgo|ddg|google|bing)|"
    r"(?:duckduckgo|ddg|google|bing)\s+(?:search|it)|"
    r"search\s+(?:the\s+web|online)|"
    r"(?:can you\s+)?search\s+(?:again|once\s+more))(?:\s+please)?\s*(?:\.|\?|!)?$",
    re.IGNORECASE,
)


def _maybe_resolve_search_imperative(query: str) -> str:
    """Resolve a bare search-tool imperative to the prior web topic, if any.

    If the user says "Use DuckDuckGo search" immediately after a web-route
    exchange (AUGMENTED, EVIDENCE, NEWS, WEATHER, TIME, FINANCE), return the
    prior user query so the pipeline routes to the web fallback on the same
    topic. Otherwise return the original query unchanged.
    """
    if not query or not _SEARCH_TOOL_IMPERATIVE_PATTERN.search(query.strip()):
        return query

    try:
        from router_py.feedback_buffer import get_buffer

        buffer = get_buffer()
        last = buffer.last()
        if last is None:
            return query
        if last.route not in ("AUGMENTED", "EVIDENCE", "NEWS", "WEATHER", "TIME", "FINANCE"):
            return query
        prior_query = (last.query or "").strip()
        if not prior_query:
            return query
        # Avoid infinite loops: if the prior query is itself a search imperative,
        # do not inherit it.
        if _SEARCH_TOOL_IMPERATIVE_PATTERN.search(prior_query):
            return query
        logging.info(
            "Resolved search imperative to prior web topic",
            extra={"original": query, "resolved": prior_query},
        )
        return prior_query
    except Exception as e:
        logging.debug(f"Search-imperative resolution failed: {e}")
        return query


# ---------------------------------------------------------------------------
# Location-anaphora resolution
# ---------------------------------------------------------------------------

# Phrases that refer to the user's own location but do not name it. When a
# stored location fact exists, replacing the anaphora with the actual location
# makes web routes (AUGMENTED/EVIDENCE) useful instead of searching for "near me".
_LOCATION_ANAPHORA_PATTERNS = [
    re.compile(r"\bnear\s+me\b", re.IGNORECASE),
    re.compile(r"\bin\s+my\s+area\b", re.IGNORECASE),
    re.compile(r"\bin\s+this\s+area\b", re.IGNORECASE),
    re.compile(r"\baround\s+here\b", re.IGNORECASE),
    re.compile(r"\bclose\s+to\s+me\b", re.IGNORECASE),
    re.compile(r"\bmy\s+area\b", re.IGNORECASE),
]


_LOCATION_FACT_PREFIX = "User lives in "


def _maybe_resolve_location_anaphora(query: str) -> str:
    """Replace location anaphora with the stored user location, if available.

    Examples:
      - "restaurant near me" -> "restaurant near Kibbutz Magal, Israel"
      - "restaurants in this area" -> "restaurants in Kibbutz Magal, Israel"

    Returns the original query unchanged when no location fact is stored or
    the query already contains an explicit location.
    """
    if not query:
        return query
    try:
        from router_py.local_answer_core.self_knowledge import _load_location_facts_direct

        facts = _load_location_facts_direct()
        if not facts:
            return query
        fact = facts[0]
        if fact.startswith(_LOCATION_FACT_PREFIX):
            location = fact[len(_LOCATION_FACT_PREFIX) :].rstrip(".").strip()
        else:
            location = fact.strip()
        if not location:
            return query
        resolved = query
        for pattern in _LOCATION_ANAPHORA_PATTERNS:
            resolved = pattern.sub(f" near {location}", resolved)
        if resolved != query:
            resolved = re.sub(r"\s{2,}", " ", resolved).strip()
            logging.info(
                "Resolved location anaphora",
                extra={"original": query, "resolved": resolved},
            )
        return resolved
    except Exception as e:
        logging.debug(f"Location-anaphora resolution failed: {e}")
        return query


def execute_plan_python(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
    surface: str = "cli",
    augmented_direct_once: bool = False,
    self_review: bool = False,
    context: dict[str, Any] | None = None,
    model: str | None = None,
) -> RouterOutcome:
    """
    Execute routing plan using Python implementation.

    This is now a thin wrapper around request_pipeline.process() that handles
    entry-point concerns (prefix parsing, locks, feedback, telemetry, memory)
    while delegating the classify → route → execute flow to the pipeline.
    """
    # Ensure control environment is set from state file if not in env
    ensure_control_env()

    start_time = time.time()
    # request_id must be unique per execution so the StateWriter does not
    # deduplicate reruns of the same question.  Prefix with question hash
    # so logs remain correlatable; suffix with nanoseconds for uniqueness.
    # If the caller supplied a request_id (e.g. runtime_request), reuse it so
    # StateWriter-produced files share the same ID as the canonical payload.
    request_id = (context or {}).get("request_id")
    if not request_id:
        request_id = f"{sha256_text(question)[:16]}_{time.time_ns()}"

    # --- Input validation / prompt injection guard ---
    validation = validate_input(question, surface=surface)
    if not validation.accepted:
        return RouterOutcome(
            status="failed",
            outcome_code="input_rejected",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            response_text="",
            error_message=validation.reason or "input_rejected",
            execution_time_ms=int((time.time() - start_time) * 1000),
            request_id=request_id,
            evidence_reason="",
            policy_reason="input_rejected",
        )
    question = validation.sanitized
    original_question = question

    # --- Request-scoped capability constraints ---
    # Extract explicit user restrictions ("do not use network access", etc.) and
    # pass them into the pipeline so they are enforced before route selection or
    # evidence planning. Callers can also supply request_constraints directly.
    request_constraints = (context or {}).get("request_constraints")
    if request_constraints is None:
        request_constraints = extract_request_constraints(question)

    # --- Location fact extraction ---
    # User statements like "I live in ..." should persist as authoritative facts
    # for location-aware follow-ups. This runs before the pipeline so the fact is
    # available to the current request if storage is fast, and to future requests.
    _extract_location_fact(question, constraints=request_constraints)

    # --- Search-imperative anaphora resolution ---
    # Bare imperatives such as "Use DuckDuckGo search" should inherit the prior
    # web topic when one exists, rather than routing LOCAL and denying capability.
    question = _maybe_resolve_search_imperative(question)

    # --- Location-anaphora resolution ---
    # Replace "near me" / "in this area" with the stored user location so web
    # routes can actually search the right place. This runs after location
    # extraction so a just-stated location is available immediately.
    question = _maybe_resolve_location_anaphora(question)

    # --- Structured logger ---
    logger = get_structured_logger("router_py.main").bind(
        request_id=request_id,
        surface=surface,
        question=question[:100],
    )
    logger.info("pipeline_start")

    # --- Route prefix parsing (mirror execute_plan.sh) ---
    route_prefix = ""
    prefix_patterns = [
        (r"^local:\s*(.*)$", "LOCAL"),
        (r"^news:\s*(.*)$", "NEWS"),
        (r"^evidence:\s*(.*)$", "EVIDENCE"),
        (r"^augmented:\s*(.*)$", "AUGMENTED"),
    ]
    for pattern, prefix_route in prefix_patterns:
        match = re.match(pattern, question, re.IGNORECASE)
        if match:
            route_prefix = prefix_route
            question = match.group(1).strip()
            break

    # --- Shared execution lock (mirror execute_plan.sh) ---
    lock_file = STATE_DIR / "execute_plan.active.lock"
    lock_acquired = False
    lock_fd = None
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_fd = open(lock_file, "w")
        if os.environ.get("LUCY_SHARED_STATE_PARALLEL_ALLOW", "").lower() not in (
            "1",
            "on",
            "true",
            "yes",
        ):
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            lock_acquired = True
    except Exception:
        pass

    try:
        # --- Feedback detection: check if user is correcting a prior response ---
        try:
            from router_py.feedback_parser import (
                log_user_feedback,
                parse_feedback,
                trigger_background_learning,
            )

            fb = parse_feedback(question)
            if fb is not None:
                logger.info(
                    "feedback_detected",
                    extra={
                        "feedback_type": fb.feedback_type.name,
                        "question": question,
                    },
                )
                logged = log_user_feedback(fb)
                if logged:
                    trigger_background_learning()

                if fb.feedback_type.name == "ROUTE_CORRECTION":
                    msg = f"Got it. I'll remember that should route to {fb.corrected_route}."
                elif fb.feedback_type.name == "ANSWER_NEGATIVE":
                    msg = "Noted. I'll work on improving that answer."
                elif fb.feedback_type.name == "ANSWER_POSITIVE":
                    msg = "Thanks for the feedback!"
                elif fb.feedback_type.name == "RETRACTION":
                    msg = "Okay, I've forgotten that."
                else:
                    msg = "Noted."

                execution_time = int((time.time() - start_time) * 1000)
                return RouterOutcome(
                    status="completed",
                    outcome_code="feedback_acknowledged",
                    route="LOCAL",
                    provider="local",
                    provider_usage_class="local",
                    intent_family="feedback",
                    confidence=1.0,
                    response_text=msg,
                    error_message="",
                    execution_time_ms=execution_time,
                    request_id=request_id,
                    evidence_reason="",
                    policy_reason="feedback_acknowledged",
                )
        except Exception as e:
            logger.warning(
                "feedback_check_failed",
                extra={"error": str(e)},
                exc_info=True,
            )

        # --- Persona identity detection: "I am Michael" etc. ---
        try:
            from memory.memory_service import (
                detect_user_identity,
                set_current_user_identity,
            )

            detected = detect_user_identity(question)
            if detected:
                row_id = set_current_user_identity(detected)
                logger.info(
                    "persona_identity_detected",
                    extra={"persona": detected, "row_id": row_id},
                )
        except ImportError:
            try:
                from tools.memory.memory_service import (
                    detect_user_identity,
                    set_current_user_identity,
                )

                detected = detect_user_identity(question)
                if detected:
                    row_id = set_current_user_identity(detected)
                    logger.info(
                        "persona_identity_detected",
                        extra={"persona": detected, "row_id": row_id},
                    )
            except Exception as e:
                logger.warning(
                    "persona_detection_failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )
        except Exception as e:
            logger.warning(
                "persona_detection_failed",
                extra={"error": str(e)},
                exc_info=True,
            )

        # --- Delegate to unified pipeline ---
        pipeline_context = dict(context or {})
        pipeline_context["_logger"] = logger
        pipeline_context["request_id"] = request_id
        pipeline_context.setdefault("request_constraints", request_constraints)
        result, classification, decision = request_pipeline.process(
            question,
            policy=policy,
            timeout=timeout,
            surface=surface,
            augmented_direct_once=augmented_direct_once,
            route_prefix=route_prefix,
            context=pipeline_context,
            model=model,
        )

        # --- Memory persistence ---
        if os.environ.get("LUCY_SESSION_MEMORY") == "1" and result.response_text:
            session_id = os.environ.get("LUCY_SESSION_ID", "default") or "default"
            _persist_memory_turn(
                original_question,
                result.response_text,
                session_id=session_id,
                constraints=request_constraints,
            )

        # --- Record exchange in feedback buffer for future attribution ---
        if classification:
            try:
                from router_py.feedback_buffer import record_exchange

                record_exchange(
                    query=original_question,
                    route=result.route,
                    intent_family=classification.intent_family,
                    response_text=result.response_text or "",
                    confidence=classification.confidence,
                )
            except Exception:
                pass

        # --- Execution time + request ID ---
        execution_time = int((time.time() - start_time) * 1000)
        result = result.with_execution_time(execution_time).with_request_id(request_id)

        # --- Outcome telemetry: write last_outcome.env (mirror shell path) ---
        try:
            _write_outcome_telemetry(
                outcome=result,
                question=question,
                execution_time_ms=execution_time,
                metadata=result.metadata,
            )
        except Exception:
            pass

        logger.info(
            "pipeline_complete",
            extra={
                "latency_ms": execution_time,
                "route": result.route,
                "provider": result.provider,
                "status": result.status,
                "outcome_code": result.outcome_code,
            },
        )
        return result

    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        logger.error(
            "pipeline_error",
            extra={
                "latency_ms": execution_time,
                "error": str(e),
            },
        )
        return RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message=str(e),
            execution_time_ms=execution_time,
            request_id=request_id,
            evidence_reason="",
            policy_reason="router_error",
        )
    finally:
        if lock_acquired and lock_fd:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
        if lock_fd:
            try:
                lock_fd.close()
            except Exception:
                pass


def main() -> int:
    """Main entry point."""
    setup_logging(level=logging.INFO, json=True)

    # Start recurring Ollama warmup ping to eliminate cold-start latency.
    # This lives inside main() so importing this module (e.g. in tests) does not
    # spawn a background thread that pings Ollama.
    try:
        from router_py.local_answer import LocalAnswer

        LocalAnswer.start_recurring_warmup()
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Local Lucy Router (Python)")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument("--policy", default="fallback_only", help="Augmentation policy")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    # Get question from args or stdin
    question = args.question
    if not question:
        if not sys.stdin.isatty():
            question = sys.stdin.read().strip()
        else:
            parser.print_help()
            return 1

    # Determine policy: command line arg > environment variable > default
    policy = args.policy
    if policy == "fallback_only" and os.environ.get("LUCY_AUGMENTATION_POLICY"):
        policy = os.environ.get("LUCY_AUGMENTATION_POLICY")

    # Execute via Python-native path (shell path removed in Stage 9)
    result = execute_plan_python(question, policy, args.timeout)

    # Output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.status == "completed":
            print(result.response_text)
        else:
            print(f"Error: {result.error_message}", file=sys.stderr)
            return 1

    return 0


# Install graceful shutdown handlers once at module load
install_shutdown_handler()

# Register Ollama model cleanup so VRAM is released when Local Lucy exits.
try:
    from router_py.ollama_cleanup import shutdown_cleanup

    register_closeable(shutdown_cleanup)
except Exception:
    pass

if __name__ == "__main__":
    raise SystemExit(main())
