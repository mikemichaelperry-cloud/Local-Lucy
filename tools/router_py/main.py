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
authoritative. Legacy entry points (`execute_plan_shell`,
`execute_plan_parity`) delegate to `execute_plan_python` with a
deprecation warning.

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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import RouterOutcome
from router_py.utils import sha256_text
from router_py.execution_engine import DEFAULT_CHAT_MEMORY_FILE
from router_py import request_pipeline
from router_py.security_guard import validate_input
from router_py.shutdown_handler import install as install_shutdown_handler
from router_py.structured_logging import get_structured_logger


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
    )


# Configuration


def resolve_state_dir(root: Path) -> Path:
    """Resolve state directory, respecting LUCY_SHARED_STATE_NAMESPACE like shell does."""
    namespace = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if namespace:
        # Sanitize: s/[^A-Za-z0-9._-]+/_/g; s/^_+|_+$//
        sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', namespace)
        sanitized = sanitized.strip('_')
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
        LAST_OUTCOME_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception:
        pass


def load_state_from_file() -> dict[str, Any]:
    """Load control state from state file (fallback when env vars not set)."""
    try:
        # Try to find state file similar to runtime_request.py
        state_file = ROOT_DIR / "state" / "state" / "current_state.json"
        if state_file.exists():
            import json
            with open(state_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def ensure_control_env() -> None:
    """
    Ensure control environment variables are set from state file if not in environment.
    This matches behavior of runtime_request.py's build_request_env.
    """
    if os.environ.get("LUCY_EVIDENCE_ENABLED") and os.environ.get("LUCY_AUGMENTATION_POLICY"):
        # Already set, nothing to do
        return
    
    state = load_state_from_file()
    if not state:
        return
    
    # Set from state file if not already in environment
    if "LUCY_EVIDENCE_ENABLED" not in os.environ:
        evidence = state.get("evidence", "off")
        os.environ["LUCY_EVIDENCE_ENABLED"] = "1" if evidence in ("on", "true", "1") else "0"
    
    if "LUCY_ENABLE_INTERNET" not in os.environ:
        # Mirror LUCY_EVIDENCE_ENABLED
        os.environ["LUCY_ENABLE_INTERNET"] = os.environ.get("LUCY_EVIDENCE_ENABLED", "0")
    
    if "LUCY_AUGMENTATION_POLICY" not in os.environ:
        policy = state.get("augmentation_policy", "disabled")
        os.environ["LUCY_AUGMENTATION_POLICY"] = policy
    
    if "LUCY_AUGMENTED_PROVIDER" not in os.environ:
        provider = state.get("augmented_provider", "wikipedia")
        os.environ["LUCY_AUGMENTED_PROVIDER"] = provider
    
    if "LUCY_CONVERSATION_MODE_FORCE" not in os.environ:
        conv = state.get("conversation", "off")
        os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1" if conv in ("on", "true", "1") else "0"
    
    if "LUCY_SESSION_MEMORY" not in os.environ:
        mem = state.get("memory", "off")
        os.environ["LUCY_SESSION_MEMORY"] = "1" if mem in ("on", "true", "1") else "0"
    
    if "LUCY_VOICE_ENABLED" not in os.environ:
        voice = state.get("voice", "off")
        os.environ["LUCY_VOICE_ENABLED"] = "1" if voice in ("on", "true", "1") else "0"





def _persist_memory_turn(question: str, response_text: str, session_id: str = "default") -> None:
    """Persist a conversation turn to chat memory (SQLite + text file)."""
    # Dual-write: SQLite first (best effort)
    try:
        from memory.memory_service import store_turn, maybe_summarize_session
        store_turn("user", question, session_id=session_id)
        store_turn("assistant", response_text, session_id=session_id)
        maybe_summarize_session()
    except Exception:
        pass  # Text-file write below still happens

    try:
        mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            mem_file = DEFAULT_CHAT_MEMORY_FILE
        mem_path = Path(mem_file).expanduser()
        mem_path.parent.mkdir(parents=True, exist_ok=True)

        assistant_text = (
            response_text.replace("BEGIN_VALIDATED", " ")
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


def execute_plan_python(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
    surface: str = "cli",
    augmented_direct_once: bool = False,
    self_review: bool = False,
    context: dict[str, Any] | None = None,
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
    request_id = sha256_text(question)[:16]

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
        )
    question = validation.sanitized

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
        if os.environ.get("LUCY_SHARED_STATE_PARALLEL_ALLOW", "").lower() not in ("1", "on", "true", "yes"):
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX)
            lock_acquired = True
    except Exception:
        pass

    try:
        # --- Feedback detection: check if user is correcting a prior response ---
        try:
            from router_py.feedback_parser import parse_feedback, log_user_feedback, trigger_background_learning
            fb = parse_feedback(question)
            if fb is not None:
                print(f"[Feedback detected] {fb.feedback_type.name}: {question}")
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
                )
        except Exception as e:
            print(f"[Feedback check warning] {e}")

        # --- Delegate to unified pipeline ---
        pipeline_context = dict(context or {})
        pipeline_context["_logger"] = logger
        result, classification, decision = request_pipeline.process(
            question,
            policy=policy,
            timeout=timeout,
            surface=surface,
            augmented_direct_once=augmented_direct_once,
            route_prefix=route_prefix,
            context=pipeline_context,
        )

        # --- Memory persistence ---
        if os.environ.get("LUCY_SESSION_MEMORY") == "1" and result.response_text:
            session_id = os.environ.get("LUCY_SESSION_ID", "default") or "default"
            _persist_memory_turn(question, result.response_text, session_id=session_id)

        # --- Record exchange in feedback buffer for future attribution ---
        if classification:
            try:
                from router_py.feedback_buffer import record_exchange
                record_exchange(
                    query=question,
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


def execute_plan_shell(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
) -> RouterOutcome:
    """DEPRECATED: Shell path removed. Delegates to Python-native execution."""
    logging.warning("execute_plan_shell is deprecated; using Python-native path")
    return execute_plan_python(question, policy, timeout)


def execute_plan_parity(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
) -> RouterOutcome:
    """DEPRECATED: Parity mode removed. Delegates to Python-native execution."""
    logging.warning("execute_plan_parity is deprecated; using Python-native path")
    return execute_plan_python(question, policy, timeout)


# Backwards-compatibility alias — deprecated.


def main() -> int:
    """Main entry point."""
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


if __name__ == "__main__":
    raise SystemExit(main())
