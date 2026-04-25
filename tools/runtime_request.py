#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime_control import (
    MODE_TO_ROUTE_CONTROL,
    RuntimeControlError,
    enforce_authority_contract,
    iso_now,
    load_or_create_state,
    locked_state_file,
    resolve_state_file,
    toggle_to_flag,
)

# Import StateManager for SQLite-backed state (Phase 3: Primary state source)
# Add router_py to path for imports
ROUTER_PY_PATH = Path(__file__).parent / "router_py"
if str(ROUTER_PY_PATH) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_PATH))

try:
    from state_manager import get_state_manager
    HAS_STATE_MANAGER = True
except ImportError:
    HAS_STATE_MANAGER = False


DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_ACTIVE_HISTORY_MAX_ENTRIES = 200
AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"
SELF_REVIEW_TRIGGER_RE = re.compile(r"^\s*review your own code\b[\s:,-]*", re.IGNORECASE)
SELF_REVIEW_PATH_TOKEN_RE = re.compile(r"(/?[A-Za-z0-9_./-]+\.(?:py|sh|md|json|txt|env|tsv))")
SELF_REVIEW_ALLOWED_SUFFIXES = {".py", ".sh", ".md", ".json", ".txt", ".env", ".tsv"}
SELF_REVIEW_MAX_TARGETS = 6
SELF_REVIEW_MAX_SEARCH_TERMS = 8
SELF_REVIEW_MAX_SNIPPET_LINES = 48
SELF_REVIEW_MAX_PROMPT_CHARS = 16000
SELF_REVIEW_MAX_SECTION_ITEMS = 6
SELF_REVIEW_STOPWORDS = {
    "review",
    "your",
    "own",
    "code",
    "look",
    "looks",
    "for",
    "with",
    "this",
    "that",
    "from",
    "into",
    "only",
    "about",
    "around",
    "check",
    "focus",
    "please",
    "specific",
    "details",
}
SELF_REVIEW_DEFAULT_BASENAMES = (
    "runtime_request.py",
    "execute_plan.sh",
    "main_window.py",
    "runtime_bridge.py",
    "conversation_panel.py",
    "policy_engine.py",
    "route_manifest.py",
    "runtime_governor.py",
)
SELF_REVIEW_TOPIC_BASENAMES = (
    (
        {"hmi", "ui", "decision", "trace", "panel", "conversation", "layout"},
        ("main_window.py", "conversation_panel.py", "status_panel.py", "runtime_bridge.py"),
    ),
    (
        {"route", "router", "routing", "manifest", "governor", "provider", "augmented", "evidence"},
        ("execute_plan.sh", "policy_engine.py", "route_manifest.py", "runtime_governor.py", "runtime_request.py"),
    ),
    (
        {"runtime", "request", "submit", "metadata", "bridge"},
        ("runtime_request.py", "runtime_bridge.py", "main_window.py"),
    ),
)


class RuntimeRequestError(RuntimeError):
    pass


@dataclass(frozen=True)
class RequestPaths:
    root: Path
    chat_bin: Path
    local_answer_bin: Path
    last_route_file: Path
    last_outcome_file: Path
    result_file: Path
    history_file: Path


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_authority_contract(expected_authority_root=Path(__file__).resolve().parents[1])
        request_text = (args.text or "").strip()
        augmented_direct_once = bool(getattr(args, "augmented_direct_once", False))
        if args.command == "submit":
            if not request_text:
                payload = build_rejected_payload("empty submit text")
                persist_payload(resolve_result_file(), payload)
                print(json.dumps(payload, sort_keys=True))
                return 1
            payload = handle_submit(request_text, augmented_direct_once=augmented_direct_once)
        elif args.command == "submit-review":
            if not request_text:
                payload = build_rejected_payload("empty self-review text")
                persist_payload(resolve_result_file(), payload)
                print(json.dumps(payload, sort_keys=True))
                return 1
            payload = handle_self_review_submit(request_text)
        else:
            raise RuntimeRequestError(f"unsupported command: {args.command}")
        persist_payload(resolve_result_file(), payload)
        print(json.dumps(payload, sort_keys=True))
        return 0 if payload["status"] == "completed" else 1
    except (RuntimeRequestError, RuntimeControlError) as exc:
        payload = build_failed_payload(
            request_text=(args.text or "").strip(),
            error=str(exc),
            status="failed",
            accepted=False,
            augmented_direct_request="1" if bool(getattr(args, "augmented_direct_once", False)) else "0",
        )
        persist_payload(resolve_result_file(), payload)
        print(json.dumps(payload, sort_keys=True))
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authoritative Local Lucy non-interactive request endpoint.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    submit_parser = subparsers.add_parser("submit")
    submit_parser.add_argument("--text", required=True, help="Single user prompt text to submit.")
    submit_parser.add_argument(
        "--augmented-direct-once",
        action="store_true",
        help="Set one-shot direct augmented request override for this submit only.",
    )
    submit_review_parser = subparsers.add_parser("submit-review")
    submit_review_parser.add_argument("--text", required=True, help="Read-only self-review request text.")
    return parser


def resolve_root() -> Path:
    env_root = os.environ.get(AUTHORITY_ROOT_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def resolve_result_file() -> Path:
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_RESULT_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "state" / "last_request_result.json"


def resolve_history_file() -> Path:
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "state" / "request_history.jsonl"


def default_runtime_namespace_root() -> Path:
    explicit_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser()
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


def legacy_runtime_namespace_root() -> Path:
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / "lucy" / "runtime-v8"


def legacy_runtime_namespace_status(
    *,
    runtime_namespace_root: Path | None = None,
    legacy_root: Path | None = None,
) -> str:
    resolved_runtime_root = (runtime_namespace_root or default_runtime_namespace_root()).expanduser().resolve()
    resolved_legacy_root = (legacy_root or legacy_runtime_namespace_root()).expanduser().resolve()
    if resolved_runtime_root == resolved_legacy_root:
        return "same"
    if resolved_legacy_root.exists():
        return "stale_parallel_tree_present"
    return "absent"


DEFAULT_RESULT_FILE = str(default_runtime_namespace_root() / "state" / "last_request_result.json")
DEFAULT_HISTORY_FILE = str(default_runtime_namespace_root() / "state" / "request_history.jsonl")
DEFAULT_CHAT_MEMORY_FILE = str(default_runtime_namespace_root() / "state" / "chat_session_memory.txt")


def resolve_ui_state_dir() -> Path:
    raw = os.environ.get("LUCY_UI_STATE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return resolve_result_file().expanduser().parent


def resolve_chat_memory_file() -> Path:
    raw = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(DEFAULT_CHAT_MEMORY_FILE)


def should_use_chat_memory(root: Path, state: dict[str, Any], request_text: str) -> bool:
    if state.get("memory") != "on":
        return False
    tool = root / "tools" / "query_policy.sh"
    if not tool.exists():
        return True
    completed = subprocess.run(
        [str(tool), "is-memory-unsafe", request_text],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return completed.returncode != 0


def append_chat_memory_turn(memory_file: Path, request_text: str, response_text: str, *, max_turns: int = 6) -> None:
    memory_file.parent.mkdir(parents=True, exist_ok=True)
    assistant_text = (
        response_text.replace("BEGIN_VALIDATED", " ")
        .replace("END_VALIDATED", " ")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    assistant_text = re.sub(r"\s+", " ", assistant_text).strip()
    if len(assistant_text) > 500:
        assistant_text = assistant_text[:500]
    block = f"User: {request_text.strip()}\nAssistant: {assistant_text}\n\n"
    existing = ""
    try:
        existing = memory_file.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except OSError:
        return
    blocks = [item.strip() for item in re.split(r"\n\s*\n", existing) if item.strip()]
    blocks.append(block.strip())
    trimmed = "\n\n".join(blocks[-max_turns:]).strip()
    if trimmed:
        trimmed += "\n\n"
    try:
        memory_file.write_text(trimmed, encoding="utf-8")
    except OSError:
        return


def resolve_history_max_entries() -> int:
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES", "").strip()
    if not raw:
        return DEFAULT_ACTIVE_HISTORY_MAX_ENTRIES
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeRequestError(f"invalid LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES: {raw}") from exc
    if value <= 0:
        raise RuntimeRequestError("LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES must be greater than zero")
    return value


def handle_submit(request_text: str, *, augmented_direct_once: bool = False) -> dict[str, Any]:
    return run_backend_submit(
        request_text=request_text,
        execution_text=request_text,
        augmented_direct_once=augmented_direct_once,
        extra_env=None,
    )


def handle_self_review_submit(request_text: str) -> dict[str, Any]:
    ensure_self_review_allowed()
    if not SELF_REVIEW_TRIGGER_RE.search(request_text):
        raise RuntimeRequestError("self-review requests must start with 'review your own code'")

    paths = resolve_paths()
    state = load_or_create_state(resolve_state_file(None), refresh_timestamp=False)
    request_id = make_request_id()
    review_roots = resolve_self_review_roots(paths.root)
    targets = extract_self_review_targets(request_text, review_roots)
    if not targets:
        targets = infer_self_review_targets(request_text, review_roots)
    if not targets:
        raise RuntimeRequestError("read-only self-review could not resolve any allowed Local Lucy v6 review targets")

    search_terms = extract_self_review_search_terms(request_text)
    execution_text = build_self_review_execution_text(request_text, targets, search_terms)
    route_meta, outcome_meta = build_self_review_meta(
        request_text=request_text,
        request_id=request_id,
        targets=targets,
    )
    try:
        response_text = run_self_review_generation(paths, state, execution_text)
    except subprocess.TimeoutExpired as exc:
        return build_failed_payload(
            request_text=request_text,
            error="self-review request timed out",
            status="timeout",
            accepted=True,
            request_id=request_id,
            control_state=state,
            response_text=strip_validated_text(exc.stdout or ""),
            route_meta=route_meta,
            outcome_meta=outcome_meta,
        )
    except RuntimeRequestError as exc:
        outcome_meta["ERROR_MESSAGE"] = str(exc)
        outcome_meta["ACTION_HINT"] = "review local generation backend"
        outcome_meta["OUTCOME_CODE"] = "self_review_error"
        return build_failed_payload(
            request_text=request_text,
            error=str(exc),
            status="failed",
            accepted=True,
            request_id=request_id,
            control_state=state,
            response_text="",
            route_meta=route_meta,
            outcome_meta=outcome_meta,
        )

    response_text = format_self_review_output(response_text, targets)
    return {
        "accepted": True,
        "authority": build_authority_payload(),
        "completed_at": iso_now(),
        "control_state": {
            "mode": state["mode"],
            "conversation": state.get("conversation", "off"),
            "memory": state["memory"],
            "evidence": state["evidence"],
            "voice": state["voice"],
            "augmentation_policy": state.get("augmentation_policy", "disabled"),
            "augmented_provider": state.get("augmented_provider", "wikipedia"),
            "model": state["model"],
            "profile": state["profile"],
        },
        "error": "",
        "outcome": build_outcome_payload(
            outcome_meta,
            response_text=response_text,
            request_text=request_text,
        ),
        "request_id": request_id,
        "request_text": request_text,
        "response_text": response_text,
        "route": build_route_payload(route_meta, outcome_meta, request_text=request_text),
        "status": "completed",
    }


def _run_backend_submit_python(
    *,
    request_text: str,
    execution_text: str,
    augmented_direct_once: bool,
    extra_env: dict[str, str] | None,
    paths: RequestPaths,
) -> dict[str, Any]:
    """
    Python-native backend submit using router_py.
    
    This bypasses lucy_chat.sh and uses the Python ExecutionEngine directly.
    """
    import subprocess
    import sys
    
    root = paths.root
    request_id = make_request_id()
    
    # Build router_py command
    cmd = [
        sys.executable,
        str(root / "tools" / "router_py" / "main.py"),
        "--mode", "python",
        "--json",
        execution_text,
    ]
    
    env = os.environ.copy()
    env["LUCY_EXEC_PY"] = "1"  # Use Python execution engine
    env["LUCY_AUGMENTATION_POLICY"] = "fallback_only"
    if augmented_direct_once:
        env["LUCY_AUGMENTATION_POLICY"] = "direct_allowed"
    if extra_env:
        env.update(extra_env)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            env=env,
            cwd=str(root),
        )
        
        if result.returncode != 0:
            error_text = result.stderr or "Python router failed"
            return build_failed_payload(
                request_text=request_text,
                error=error_text,
                status="failed",
                accepted=True,
                request_id=request_id,
            )
        
        # Parse router result
        router_result = json.loads(result.stdout)
        
        # Load state for control_state
        state = load_or_create_state(resolve_state_file(None), refresh_timestamp=False)
        
        # Build route_meta and outcome_meta from router result
        route_meta = {
            "INTENT_FAMILY": router_result.get("intent_family", "unknown"),
            "FINAL_MODE": router_result.get("route", "LOCAL"),
            "CONFIDENCE": str(router_result.get("confidence", 0.0)),
        }
        
        outcome_meta = {
            "OUTCOME_CODE": router_result.get("outcome_code", "unknown"),
            "AUGMENTED_PROVIDER_USED": router_result.get("provider", "local"),
        }
        
        response_text = router_result.get("response_text", "")
        
        # Persist to history
        payload = {
            "accepted": True,
            "authority": build_authority_payload(),
            "completed_at": iso_now(),
            "control_state": {
                "mode": state.get("mode", "auto"),
                "conversation": state.get("conversation", "off"),
                "memory": state.get("memory", "off"),
                "evidence": state.get("evidence", "off"),
                "voice": state.get("voice", "off"),
                "augmentation_policy": state.get("augmentation_policy", "disabled"),
                "augmented_provider": state.get("augmented_provider", "wikipedia"),
                "model": state.get("model", "local-lucy"),
                "profile": state.get("profile", "opt-experimental-v8-dev"),
            },
            "error": "",
            "outcome": build_outcome_payload(
                outcome_meta,
                response_text=response_text,
                request_text=request_text,
                history_file=resolve_history_file(),
            ),
            "request_id": request_id,
            "request_text": request_text,
            "response_text": response_text,
            "route": build_route_payload(route_meta, outcome_meta, request_text=request_text),
            "status": router_result.get("status", "completed"),
        }
        
        # Persist to history file
        append_history_entry(resolve_history_file(), payload)
        
        return payload
        
    except subprocess.TimeoutExpired:
        return build_failed_payload(
            request_text=request_text,
            error="Python router timeout",
            status="timeout",
            accepted=True,
            request_id=request_id,
        )
    except Exception as e:
        return build_failed_payload(
            request_text=request_text,
            error=f"Python router error: {e}",
            status="failed",
            accepted=True,
            request_id=request_id,
        )


def run_backend_submit(
    *,
    request_text: str,
    execution_text: str,
    augmented_direct_once: bool,
    extra_env: dict[str, str] | None,
) -> dict[str, Any]:
    paths = resolve_paths()
    
    # Check if we should use Python-native execution (lucy_chat.sh archived)
    use_python_path = (
        os.environ.get("LUCY_ROUTER_PY", "") == "1" or
        not paths.chat_bin.exists() or
        os.environ.get("LUCY_DIRECT_EXECUTION", "") == "1"
    )
    
    if use_python_path:
        return _run_backend_submit_python(
            request_text=request_text,
            execution_text=execution_text,
            augmented_direct_once=augmented_direct_once,
            extra_env=extra_env,
            paths=paths,
        )
    
    # Shell path (legacy)
    state = load_or_create_state(resolve_state_file(None), refresh_timestamp=False)
    request_id = make_request_id()
    chat_memory_file = resolve_chat_memory_file() if should_use_chat_memory(paths.root, state, request_text) else None
    env = build_request_env(
        paths.root,
        state,
        augmented_direct_once=augmented_direct_once,
        chat_memory_file=chat_memory_file,
    )
    if extra_env:
        env.update(extra_env)
    route_signature_before = file_signature(paths.last_route_file)
    outcome_signature_before = file_signature(paths.last_outcome_file)

    try:
        completed = subprocess.run(
            [str(paths.chat_bin), execution_text],
            check=False,
            capture_output=True,
            text=True,
            timeout=DEFAULT_TIMEOUT_SECONDS,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        return build_failed_payload(
            request_text=request_text,
            error="request timed out",
            status="timeout",
            accepted=True,
            request_id=request_id,
            control_state=state,
            response_text=strip_validated_text(exc.stdout or ""),
            augmented_direct_request="1" if augmented_direct_once else "0",
        )

    # Phase 3: Try StateManager (SQLite) first, fall back to env files
    route_meta = load_route_from_state_manager(execution_text)
    if not route_meta:
        # Fall back to file-based state for backwards compatibility
        route_meta = load_fresh_env_file(paths.last_route_file, route_signature_before, execution_text)
    
    outcome_meta = load_outcome_from_state_manager(execution_text)
    if not outcome_meta:
        # Fall back to file-based state for backwards compatibility
        outcome_meta = load_valid_outcome_env_file(paths.last_outcome_file, outcome_signature_before, execution_text)
    response_text = strip_validated_text(completed.stdout)

    if not outcome_meta:
        if completed.returncode != 0:
            error_text = choose_failure_error(
                stderr_text=completed.stderr or "",
                stdout_text=completed.stdout or "",
                fallback="backend request failed",
            )
        else:
            error_text = "backend did not publish valid outcome state"
        outcome_meta = synthesize_failure_outcome_meta(
            request_text=execution_text,
            route_meta=route_meta,
            control_state=state,
            returncode=completed.returncode,
            error_text=error_text,
            augmented_direct_once=augmented_direct_once,
        )
        write_outcome_env_file(paths.last_outcome_file, outcome_meta)

    if completed.returncode != 0:
        error_text = choose_failure_error(
            outcome_meta=outcome_meta,
            stderr_text=completed.stderr or "",
            stdout_text=completed.stdout or "",
            fallback="backend request failed",
        )
        return build_failed_payload(
            request_text=request_text,
            error=error_text,
            status="failed",
            accepted=True,
            request_id=request_id,
            control_state=state,
            response_text=response_text,
            route_meta=route_meta,
            outcome_meta=outcome_meta,
            returncode=completed.returncode,
            augmented_direct_request="1" if augmented_direct_once else "0",
        )

    if outcome_meta.get("OUTCOME_CODE") == "execution_error":
        return build_failed_payload(
            request_text=request_text,
            error=choose_failure_error(
                outcome_meta=outcome_meta,
                stdout_text=response_text,
                fallback="backend did not publish valid outcome state",
            ),
            status="failed",
            accepted=True,
            request_id=request_id,
            control_state=state,
            response_text=response_text,
            route_meta=route_meta,
            outcome_meta=outcome_meta,
            returncode=completed.returncode,
            augmented_direct_request="1" if augmented_direct_once else "0",
        )

    if chat_memory_file is not None:
        append_chat_memory_turn(chat_memory_file, request_text, response_text)

    return {
        "accepted": True,
        "authority": build_authority_payload(),
        "completed_at": iso_now(),
        "control_state": {
            "mode": state["mode"],
            "conversation": state.get("conversation", "off"),
            "memory": state["memory"],
            "evidence": state["evidence"],
            "voice": state["voice"],
            "augmentation_policy": state.get("augmentation_policy", "disabled"),
            "augmented_provider": state.get("augmented_provider", "wikipedia"),
            "model": state["model"],
            "profile": state["profile"],
        },
        "error": "",
        "outcome": build_outcome_payload(
            outcome_meta,
            response_text=response_text,
            request_text=request_text,
            history_file=resolve_history_file(),
        ),
        "request_id": request_id,
        "request_text": request_text,
        "response_text": response_text,
        "route": build_route_payload(route_meta, outcome_meta, request_text=request_text),
        "status": "completed",
    }


def resolve_paths() -> RequestPaths:
    root = resolve_root()
    state_dir = resolve_state_dir(root)
    return RequestPaths(
        root=root,
        chat_bin=root / "lucy_chat.sh",
        local_answer_bin=root / "tools" / "local_answer.sh",
        last_route_file=state_dir / "last_route.env",
        last_outcome_file=state_dir / "last_outcome.env",
        result_file=resolve_result_file(),
        history_file=resolve_history_file(),
    )


def resolve_state_dir(root: Path) -> Path:
    state_dir = root / "state"
    namespace_raw = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if not namespace_raw:
        return state_dir
    namespace = re.sub(r"[^A-Za-z0-9._-]+", "_", namespace_raw).strip("_")
    if not namespace:
        namespace = "unnamed"
    return state_dir / "namespaces" / namespace


def ensure_self_review_allowed() -> None:
    if str(os.environ.get("LUCY_SELF_REVIEW_ALLOWED", "")).strip().lower() not in {"1", "true", "yes", "on"}:
        raise RuntimeRequestError("self-review unavailable without explicit HMI authorization")


def resolve_self_review_roots(root: Path) -> list[Path]:
    raw = os.environ.get("LUCY_SELF_REVIEW_ROOTS", "").strip()
    ui_root = os.environ.get("LUCY_UI_ROOT", "").strip()
    default_candidates = [str(root)]
    if ui_root:
        default_candidates.append(ui_root)
    candidates = raw.split(os.pathsep) if raw else default_candidates
    roots: list[Path] = []
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def extract_self_review_targets(request_text: str, roots: list[Path]) -> list[Path]:
    targets: list[Path] = []
    body = strip_self_review_trigger(request_text)
    for match in SELF_REVIEW_PATH_TOKEN_RE.finditer(body):
        resolved = resolve_self_review_target(match.group(1), roots)
        if resolved is None or resolved in targets:
            continue
        targets.append(resolved)
        if len(targets) >= SELF_REVIEW_MAX_TARGETS:
            break
    return targets


def infer_self_review_targets(request_text: str, roots: list[Path]) -> list[Path]:
    requested = strip_self_review_trigger(request_text).lower()
    ordered_basenames: list[str] = []
    for keywords, basenames in SELF_REVIEW_TOPIC_BASENAMES:
        if any(keyword in requested for keyword in keywords):
            for basename in basenames:
                if basename not in ordered_basenames:
                    ordered_basenames.append(basename)
    for basename in SELF_REVIEW_DEFAULT_BASENAMES:
        if basename not in ordered_basenames:
            ordered_basenames.append(basename)

    targets: list[Path] = []
    for basename in ordered_basenames:
        resolved = resolve_self_review_target(basename, roots)
        if resolved is None or resolved in targets:
            continue
        targets.append(resolved)
        if len(targets) >= SELF_REVIEW_MAX_TARGETS:
            break
    return targets


def strip_self_review_trigger(request_text: str) -> str:
    return SELF_REVIEW_TRIGGER_RE.sub("", request_text, count=1).strip()


def resolve_self_review_target(token: str, roots: list[Path]) -> Path | None:
    cleaned = token.strip().strip("\"'").rstrip(",.;:)]}")
    if not cleaned:
        return None

    candidate_path = Path(cleaned).expanduser()
    if candidate_path.is_absolute():
        return candidate_path.resolve() if is_allowed_self_review_file(candidate_path.resolve(), roots) else None

    direct_matches: list[Path] = []
    for root in roots:
        candidate = (root / cleaned).resolve()
        if is_allowed_self_review_file(candidate, roots):
            direct_matches.append(candidate)
    unique_direct = unique_paths(direct_matches)
    if len(unique_direct) == 1:
        return unique_direct[0]
    if len(unique_direct) > 1:
        return None

    basename = Path(cleaned).name
    if "." not in basename:
        return None

    basename_matches: list[Path] = []
    for root in roots:
        try:
            for candidate in root.rglob(basename):
                resolved = candidate.resolve()
                if is_allowed_self_review_file(resolved, roots):
                    basename_matches.append(resolved)
                    if len(basename_matches) > 1:
                        break
        except OSError:
            continue
        if len(basename_matches) > 1:
            break
    unique_basename = unique_paths(basename_matches)
    return unique_basename[0] if len(unique_basename) == 1 else None


def unique_paths(paths: list[Path]) -> list[Path]:
    unique: list[Path] = []
    for path in paths:
        if path not in unique:
            unique.append(path)
    return unique


def is_allowed_self_review_file(candidate: Path, roots: list[Path]) -> bool:
    if not candidate.exists() or not candidate.is_file():
        return False
    if candidate.suffix.lower() not in SELF_REVIEW_ALLOWED_SUFFIXES:
        return False
    for root in roots:
        try:
            candidate.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def extract_self_review_search_terms(request_text: str) -> list[str]:
    body = SELF_REVIEW_PATH_TOKEN_RE.sub(" ", strip_self_review_trigger(request_text))
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", body.lower()):
        if token in SELF_REVIEW_STOPWORDS or token in terms:
            continue
        terms.append(token)
        if len(terms) >= SELF_REVIEW_MAX_SEARCH_TERMS:
            break
    return terms


def build_self_review_execution_text(
    request_text: str,
    targets: list[Path],
    search_terms: list[str],
) -> str:
    focus = normalize_single_line(strip_self_review_trigger(request_text))
    parts = [
        "Read-only self-review task for Local Lucy.",
        "Do not edit code, propose patches, or imply self-modification.",
        "Return only these sections: Findings, Risks, Suggestions, Files reviewed.",
        "Do not repeat task instructions, tool commands, or raw prompt scaffolding.",
        f"Operator review request: {focus or 'review the provided code scope'}.",
    ]
    if search_terms:
        parts.append(f"Focus terms: {', '.join(search_terms)}.")
    for target in targets:
        excerpt = build_self_review_excerpt(target, search_terms)
        if excerpt:
            parts.append(excerpt)
        candidate = normalize_single_line(" ".join(parts))
        if len(candidate) > SELF_REVIEW_MAX_PROMPT_CHARS:
            parts.pop()
            break
    prompt = normalize_single_line(" ".join(parts))
    return prompt[:SELF_REVIEW_MAX_PROMPT_CHARS].strip()


def build_self_review_excerpt(path: Path, search_terms: list[str]) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"File {path}: unreadable ({exc})."

    windows = matched_line_windows(lines, search_terms)
    if not windows:
        windows = [(0, min(len(lines), 24))]

    rendered_lines: list[str] = []
    for start, end in windows:
        for index in range(start, min(end, len(lines))):
            rendered_lines.append(f"L{index + 1}: {normalize_single_line(lines[index])}")
            if len(rendered_lines) >= SELF_REVIEW_MAX_SNIPPET_LINES:
                break
        if len(rendered_lines) >= SELF_REVIEW_MAX_SNIPPET_LINES:
            break

    return f"File {path}: {' | '.join(rendered_lines)}"


def matched_line_windows(lines: list[str], search_terms: list[str]) -> list[tuple[int, int]]:
    if not search_terms:
        return []
    windows: list[tuple[int, int]] = []
    for index, raw_line in enumerate(lines):
        line = raw_line.lower()
        if not any(term in line for term in search_terms):
            continue
        start = max(0, index - 2)
        end = min(len(lines), index + 3)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
        if len(windows) >= 3:
            break
    return windows


def normalize_single_line(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def format_self_review_output(raw_text: str, targets: list[Path]) -> str:
    sections: dict[str, list[str]] = {
        "Findings": [],
        "Risks": [],
        "Suggestions": [],
        "Files reviewed": [],
    }
    for target in targets:
        append_unique_item(sections["Files reviewed"], str(target))

    current_section: str | None = None
    in_code_block = False
    for raw_line in (raw_text or "").replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        section = match_self_review_section(line)
        if section:
            current_section = section
            continue
        if is_self_review_scaffolding_line(line):
            continue

        if current_section == "Files reviewed":
            for path_text in extract_self_review_paths(line):
                append_unique_item(sections["Files reviewed"], path_text)
            continue

        item = normalize_self_review_item(line)
        if not item:
            continue

        if current_section in {"Findings", "Risks", "Suggestions"}:
            append_unique_item(sections[current_section], item)
            continue

        classified_section = classify_self_review_item(item)
        append_unique_item(sections[classified_section], item)

    if not sections["Findings"]:
        sections["Findings"].append("No concrete findings were extracted from this bounded self-review pass.")
    if not sections["Risks"]:
        sections["Risks"].append("No additional risks were isolated beyond the bounded findings above.")
    if not sections["Suggestions"]:
        sections["Suggestions"].append("No additional suggestions were extracted beyond the bounded findings above.")

    rendered_sections: list[str] = []
    for section_name in ("Findings", "Risks", "Suggestions", "Files reviewed"):
        rendered_sections.append(section_name)
        for item in sections[section_name][:SELF_REVIEW_MAX_SECTION_ITEMS]:
            rendered_sections.append(f"- {item}")
        rendered_sections.append("")
    return "\n".join(rendered_sections).strip()


def match_self_review_section(line: str) -> str | None:
    normalized = normalize_single_line(line).lower().rstrip(":")
    if normalized in {"finding", "findings"}:
        return "Findings"
    if normalized in {"risk", "risks"}:
        return "Risks"
    if normalized in {"suggestion", "suggestions", "recommendations"}:
        return "Suggestions"
    if normalized in {"files reviewed", "reviewed files"}:
        return "Files reviewed"
    if normalized in {"excerpt", "excerpts"}:
        return None
    return None


def is_self_review_scaffolding_line(line: str) -> bool:
    normalized = normalize_single_line(line).lower()
    if not normalized:
        return True
    if normalized.startswith(
        (
            "read-only self-review task",
            "do not edit code",
            "return findings",
            "return only these sections",
            "do not repeat task instructions",
            "operator review request:",
            "focus terms:",
            "run:",
            "instructions:",
            "task:",
        )
    ):
        return True
    if normalized.startswith("file ") and " l1:" in normalized:
        return True
    if re.search(r"\bL\d+:\b", line):
        return True
    return False


def normalize_self_review_item(line: str) -> str:
    item = line.strip()
    item = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", item)
    item = re.sub(r"^\s*\[[^\]]+\]\s*", "", item)
    item = normalize_single_line(item)
    return item.strip(" -")


def classify_self_review_item(item: str) -> str:
    lowered = item.lower()
    if any(token in lowered for token in ("risk", "fragile", "drift", "regress", "leak", "ambiguous", "confus", "brittle")):
        return "Risks"
    if any(
        token in lowered
        for token in ("suggest", "recommend", "consider", "should ", "could ", "prefer", "keep ", "avoid ", "tighten", "normalize", "consolidate")
    ):
        return "Suggestions"
    return "Findings"


def extract_self_review_paths(line: str) -> list[str]:
    paths: list[str] = []
    for match in re.finditer(r"(/?[A-Za-z0-9_./-]+\.(?:py|sh|md|json|txt|env|tsv))", line):
        candidate = normalize_single_line(match.group(1)).rstrip(",.;:")
        if candidate:
            paths.append(candidate)
    return paths


def append_unique_item(items: list[str], value: str) -> None:
    cleaned = normalize_single_line(value)
    if cleaned and cleaned not in items:
        items.append(cleaned)


def build_self_review_meta(
    *,
    request_text: str,
    request_id: str,
    targets: list[Path],
) -> tuple[dict[str, str], dict[str, str]]:
    target_text = " | ".join(str(path) for path in targets)
    utc = iso_now()
    route_meta = {
        "UTC": utc,
        "MODE": "SELF_REVIEW",
        "ROUTE_REASON": "authorized_read_only_self_review",
        "SESSION_ID": request_id,
        "QUERY": request_text,
    }
    outcome_meta = {
        "UTC": utc,
        "MODE": "SELF_REVIEW",
        "ROUTE_MODE": "SELF_REVIEW",
        "ROUTE_REASON": "authorized_read_only_self_review",
        "SESSION_ID": request_id,
        "EVIDENCE_CREATED": "false",
        "OUTCOME_CODE": "self_review_answered",
        "ACTION_HINT": "read_only_findings",
        "RC": "0",
        "QUERY": request_text,
        "REQUESTED_MODE": "SELF_REVIEW",
        "FINAL_MODE": "SELF_REVIEW",
        "FALLBACK_USED": "false",
        "FALLBACK_REASON": "none",
        "TRUST_CLASS": "read_only_self_review",
        "INTENT_FAMILY": "self_review",
        "MANIFEST_INTENT_FAMILY": "self_review",
        "AUGMENTED_PROVIDER": "none",
        "AUGMENTED_ALLOWED": "false",
        "AUGMENTED_PROVIDER_SELECTED": "none",
        "AUGMENTED_PROVIDER_USED": "none",
        "AUGMENTED_PROVIDER_USAGE_CLASS": "none",
        "AUGMENTED_PROVIDER_CALL_REASON": "not_needed",
        "AUGMENTED_PROVIDER_COST_NOTICE": "false",
        "AUGMENTED_PAID_PROVIDER_INVOKED": "false",
        "AUGMENTATION_POLICY": "disabled",
        "AUGMENTED_DIRECT_REQUEST": "0",
        "SELF_REVIEW_REQUEST": "true",
        "SELF_REVIEW_MODE": "read_only",
        "SELF_REVIEW_TARGETS": target_text,
        "SELF_REVIEW_TARGET_COUNT": str(len(targets)),
    }
    return route_meta, outcome_meta


def run_self_review_generation(paths: RequestPaths, state: dict[str, Any], execution_text: str) -> str:
    if not paths.local_answer_bin.exists():
        raise RuntimeRequestError(f"missing self-review local generator: {paths.local_answer_bin}")

    env = build_request_env(paths.root, state, augmented_direct_once=False)
    env["LUCY_SELF_REVIEW_ACTIVE"] = "1"
    env["LUCY_LOCAL_GEN_ROUTE_MODE"] = "SELF_REVIEW"
    env["LUCY_LOCAL_GEN_OUTPUT_MODE"] = "CHAT"
    completed = subprocess.run(
        [str(paths.local_answer_bin), execution_text],
        check=False,
        capture_output=True,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        shell=False,
        env=env,
    )
    response_text = strip_validated_text(completed.stdout)
    if completed.returncode != 0:
        raise RuntimeRequestError(
            choose_failure_error(
                stderr_text=completed.stderr or "",
                stdout_text=completed.stdout or "",
                fallback="self-review local generation failed",
            )
        )
    if not response_text:
        raise RuntimeRequestError("self-review local generation returned no text")
    return response_text


def build_request_env(
    root: Path,
    state: dict[str, Any],
    *,
    augmented_direct_once: bool = False,
    chat_memory_file: Path | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env["LUCY_ROOT"] = str(root)
    env[AUTHORITY_ROOT_ENV] = str(root)
    env["LUCY_ROUTE_CONTROL_MODE"] = MODE_TO_ROUTE_CONTROL[state["mode"]]
    env["LUCY_CONVERSATION_MODE_FORCE"] = toggle_to_flag(str(state.get("conversation", "off")))
    env["LUCY_SESSION_MEMORY"] = toggle_to_flag(state["memory"])
    if chat_memory_file is not None:
        env["LUCY_CHAT_MEMORY_FILE"] = str(chat_memory_file)
    env["LUCY_EVIDENCE_ENABLED"] = toggle_to_flag(state["evidence"])
    env["LUCY_ENABLE_INTERNET"] = toggle_to_flag(state["evidence"])
    env["LUCY_VOICE_ENABLED"] = toggle_to_flag(state["voice"])
    env["LUCY_AUGMENTATION_POLICY"] = str(state.get("augmentation_policy", "disabled"))
    env["LUCY_AUGMENTED_PROVIDER"] = str(state.get("augmented_provider", "wikipedia"))
    if augmented_direct_once:
        env["LUCY_AUGMENTED_DIRECT_REQUEST"] = "1"
    env["LUCY_LOCAL_MODEL"] = state["model"]
    env["LUCY_RUNTIME_PROFILE"] = state["profile"]
    # Propagate Python router/execution engine flags for voice path compatibility
    if os.environ.get("LUCY_ROUTER_PY"):
        env["LUCY_ROUTER_PY"] = os.environ["LUCY_ROUTER_PY"]
    if os.environ.get("LUCY_EXEC_PY"):
        env["LUCY_EXEC_PY"] = os.environ["LUCY_EXEC_PY"]
    return env


def make_request_id() -> str:
    return f"{iso_now()}-{os.getpid()}"


def query_sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="ignore")).hexdigest()


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    try:
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            if "=" not in raw_line:
                continue
            key, value = raw_line.split("=", 1)
            values[key.strip()] = value.strip()
    except OSError:
        return {}
    return values


def file_signature(path: Path) -> tuple[int, int, int] | None:
    try:
        stat_result = path.stat()
    except OSError:
        return None
    return (stat_result.st_mtime_ns, stat_result.st_size, stat_result.st_ino)


def load_fresh_env_file(path: Path, previous_signature: tuple[int, int, int] | None, expected_query: str) -> dict[str, str]:
    current_signature = file_signature(path)
    if current_signature is None or current_signature == previous_signature:
        return {}
    values = load_env_file(path)
    expected_query_hash = query_sha256(expected_query)
    actual_query_hash = values.get("QUERY_SHA256", "").strip().lower()
    query_matches = actual_query_hash == expected_query_hash if actual_query_hash else values.get("QUERY", "") == expected_query
    if not query_matches:
        return {}
    values["QUERY"] = expected_query
    values["QUERY_SHA256"] = expected_query_hash
    return values


def load_valid_outcome_env_file(path: Path, previous_signature: tuple[int, int, int] | None, expected_query: str) -> dict[str, str]:
    values = load_fresh_env_file(path, previous_signature, expected_query)
    if not values.get("OUTCOME_CODE", ""):
        return {}
    return values


# ============================================================================
# StateManager (SQLite) State Functions - Phase 3: Primary State Source
# ============================================================================

def load_route_from_state_manager(expected_query: str) -> dict[str, str] | None:
    """
    Load route from StateManager (SQLite) - PRIMARY source.
    
    Phase 3 migration: StateManager is now the authoritative source for state.
    Falls back to None if StateManager unavailable or no matching record.
    
    Args:
        expected_query: The query text to match
        
    Returns:
        Route metadata dict or None if not found
    """
    if not HAS_STATE_MANAGER:
        return None
    
    try:
        sm = get_state_manager()
        route_data = sm.read_last_route()
        
        if not route_data:
            return None
            
        # Verify query matches
        route_query = route_data.get("metadata", {}).get("question", "")
        if route_query != expected_query:
            return None
            
        # Convert StateManager format to env-style format
        return {
            "MODE": route_data.get("strategy", "LOCAL"),
            "INTENT": route_data.get("intent", ""),
            "CONFIDENCE": str(route_data.get("confidence", 0.0)),
            "ROUTE_REASON": route_data.get("metadata", {}).get("final_mode", "route_selected"),
            "QUERY": expected_query,
            "QUERY_SHA256": query_sha256(expected_query),
            "PROVIDER": route_data.get("metadata", {}).get("provider", "local"),
            "IS_MEDICAL_QUERY": str(route_data.get("metadata", {}).get("is_medical_query", False)).lower(),
        }
    except Exception as e:
        # Silently fall back to file-based state
        return None


def load_outcome_from_state_manager(expected_query: str) -> dict[str, str] | None:
    """
    Load outcome from StateManager (SQLite) - PRIMARY source.
    
    Phase 3 migration: StateManager is now the authoritative source for state.
    Falls back to None if StateManager unavailable or no matching record.
    
    Args:
        expected_query: The query text to match
        
    Returns:
        Outcome metadata dict or None if not found
    """
    if not HAS_STATE_MANAGER:
        return None
    
    try:
        sm = get_state_manager()
        outcome_data = sm.read_last_outcome()
        
        if not outcome_data:
            return None
            
        # Verify query matches via outcome result
        # Note: StateManager stores query in metadata, we need to match carefully
        result = outcome_data.get("result", {})
        
        # Convert StateManager format to env-style format
        success = outcome_data.get("success", False)
        outcome_code = "completed" if success else outcome_data.get("result", {}).get("outcome_code", "unknown")
        
        return {
            "UTC": outcome_data.get("timestamp", iso_now()),
            "MODE": result.get("route", "LOCAL"),
            "OUTCOME_CODE": outcome_code,
            "TRUST_CLASS": result.get("trust_class", "local"),
            "FINAL_MODE": result.get("route", "LOCAL"),
            "QUERY": expected_query,
            "QUERY_SHA256": query_sha256(expected_query),
            "ERROR_MESSAGE": outcome_data.get("error_message", ""),
        }
    except Exception as e:
        # Silently fall back to file-based state
        return None


def synthesize_failure_outcome_meta(
    *,
    request_text: str,
    route_meta: dict[str, str],
    control_state: dict[str, Any],
    returncode: int,
    error_text: str,
    augmented_direct_once: bool,
) -> dict[str, str]:
    requested_mode = route_meta.get("MODE", "") or "unknown"
    route_reason = route_meta.get("ROUTE_REASON", "") or "backend_failure_no_outcome"
    return {
        "UTC": iso_now(),
        "MODE": "ERROR",
        "ROUTE_REASON": route_reason,
        "SESSION_ID": "",
        "EVIDENCE_CREATED": "false",
        "OUTCOME_CODE": "execution_error",
        "ACTION_HINT": "check backend logs",
        "RC": str(returncode),
        "QUERY": request_text,
        "QUERY_SHA256": query_sha256(request_text),
        "REQUESTED_MODE": requested_mode,
        "FINAL_MODE": "ERROR",
        "FALLBACK_USED": "false",
        "FALLBACK_REASON": "none",
        "TRUST_CLASS": "unknown",
        "AUGMENTED_PROVIDER": "none",
        "AUGMENTED_ALLOWED": "false",
        "AUGMENTED_PROVIDER_SELECTED": str(control_state.get("augmented_provider", "none")),
        "AUGMENTED_PROVIDER_USED": "none",
        "AUGMENTED_PROVIDER_USAGE_CLASS": "none",
        "AUGMENTED_PROVIDER_CALL_REASON": "error",
        "AUGMENTED_PROVIDER_COST_NOTICE": "false",
        "AUGMENTED_PAID_PROVIDER_INVOKED": "false",
        "AUGMENTATION_POLICY": str(control_state.get("augmentation_policy", "disabled")),
        "AUGMENTED_DIRECT_REQUEST": "1" if augmented_direct_once else "0",
        "ERROR_MESSAGE": error_text,
    }


def write_outcome_env_file(path: Path, outcome_meta: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=".last_outcome.",
        suffix=".tmp",
    ) as handle:
        for key, value in outcome_meta.items():
            handle.write(f"{key}={value}\n")
        tmp_path = Path(handle.name)
    os.replace(tmp_path, path)


def strip_validated_text(raw_text: str) -> str:
    lines = []
    for line in (raw_text or "").replace("\r", "").splitlines():
        stripped = line.strip()
        if stripped in {"BEGIN_VALIDATED", "END_VALIDATED"}:
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def choose_failure_error(
    *,
    outcome_meta: dict[str, str] | None = None,
    stderr_text: str = "",
    stdout_text: str = "",
    fallback: str = "backend request failed",
) -> str:
    meta = outcome_meta or {}
    for key in ("ERROR_MESSAGE", "ACTION_HINT"):
        value = str(meta.get(key, "")).strip()
        if value:
            return value
    return first_nonempty_line(stderr_text) or first_nonempty_line(stdout_text) or fallback


def parse_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def evidence_mode_selection_label(evidence_mode: str, evidence_reason: str) -> str:
    if not evidence_mode:
        return "not_applicable"
    if evidence_reason == "default_light":
        return "default-light"
    if evidence_reason.startswith("explicit_") or evidence_reason == "source_request":
        return "explicit-user-triggered"
    if evidence_reason.startswith("policy_") or evidence_reason in {"medical_context", "geopolitics", "conflict_live"}:
        return "policy-triggered"
    return "manifest-selected"


def _truthy_text(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _mode_candidate(outcome_meta: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = str(outcome_meta.get(key, "")).strip()
        if value:
            return value.upper()
    return ""


def determine_answer_class(outcome_meta: dict[str, str]) -> str:
    final_mode = _mode_candidate(
        outcome_meta,
        "FINAL_MODE",
        "MANIFEST_SELECTED_ROUTE",
        "ROUTE_MODE",
        "MODE",
        "REQUESTED_MODE",
    )
    outcome_code = str(outcome_meta.get("OUTCOME_CODE", "")).strip().lower()
    trust_class = str(outcome_meta.get("TRUST_CLASS", "")).strip().lower()
    action_hint = str(outcome_meta.get("ACTION_HINT", "")).strip().lower()

    if outcome_code == "clarification_requested" or final_mode == "CLARIFY":
        return "clarification_required"
    if outcome_code == "best_effort_recovery_answer":
        return "best_effort_recovery_answer"
    if outcome_code == "validation_failed" and action_hint == "enable evidence":
        return "operator_blocked"
    if outcome_code == "validation_failed":
        return "validation_failed"
    if outcome_code == "requires_evidence_mode":
        return "requires_evidence_mode"
    if trust_class == "evidence_backed" or final_mode == "EVIDENCE":
        return "evidence_backed_answer"
    if final_mode == "AUGMENTED":
        if _truthy_text(outcome_meta.get("FALLBACK_USED")):
            return "augmented_unverified_fallback"
        return "augmented_unverified_answer"
    if final_mode == "LOCAL" or outcome_code == "answered":
        return "local_answer"
    return "unknown"


def determine_provider_authorization(outcome_meta: dict[str, str], answer_class: str) -> str:
    if answer_class not in {"augmented_unverified_fallback", "augmented_unverified_answer"}:
        return "not_applicable"
    if _truthy_text(outcome_meta.get("AUGMENTED_DIRECT_REQUEST")) or str(
        outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_REASON", "")
    ).strip().lower() == "explicit provider selection":
        return "explicit_provider_selection"
    if str(outcome_meta.get("AUGMENTATION_POLICY", "")).strip().lower() == "disabled":
        return "not_authorized"
    provider_used = str(
        outcome_meta.get("AUGMENTED_PROVIDER_USED")
        or outcome_meta.get("AUGMENTED_PROVIDER")
        or outcome_meta.get("AUGMENTED_PROVIDER_SELECTED")
        or ""
    ).strip()
    if provider_used and provider_used.lower() != "none":
        return "authorized_by_runtime_state"
    return "local_only"


def _operator_answer_text(raw_text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in (raw_text or "").replace("\r", "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("augmented fallback (unverified answer):"):
            continue
        if lowered.startswith("augmented mode (unverified answer):"):
            continue
        if lowered.startswith("augmented route (unverified answer):"):
            continue
        if lowered.startswith("best-effort recovery (not source-backed answer):"):
            continue
        if lowered.startswith("run:"):
            continue
        if lowered.startswith("instruction:"):
            continue
        if lowered.startswith("unverified context source class:"):
            continue
        if lowered.startswith("unverified context reference:"):
            continue
        if lowered.startswith("unverified context excerpt:"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _source_basis_for_answer_contract(outcome_meta: dict[str, str], answer_class: str) -> list[str]:
    basis: list[str] = []
    provider_status = str(outcome_meta.get("AUGMENTED_PROVIDER_STATUS", "")).strip().lower()
    provider = str(
        outcome_meta.get("AUGMENTED_PROVIDER_USED")
        or outcome_meta.get("AUGMENTED_PROVIDER")
        or outcome_meta.get("AUGMENTED_PROVIDER_SELECTED")
        or ""
    ).strip().lower()
    context_used = _truthy_text(outcome_meta.get("UNVERIFIED_CONTEXT_USED"))

    if answer_class in {"augmented_unverified_fallback", "augmented_unverified_answer"}:
        if provider and provider != "none" and (context_used or provider_status == "available"):
            basis.append(f"augmented_provider_{provider}")
        basis.append("local_model_background")
    elif answer_class == "best_effort_recovery_answer":
        basis.append("local_model_background")
    return basis


def _verification_status_for_answer_contract(
    outcome_meta: dict[str, str],
    answer_class: str,
    source_basis: list[str],
) -> str:
    del outcome_meta
    del answer_class
    if "allowlisted_evidence" in source_basis:
        return "partially_verified"
    return "unverified"


def _has_temporal_currentness_terms(text: str) -> bool:
    return bool(
        re.search(
            r"\b(latest|current|currently|today|recent|right now|at the moment|doing now|up to date)\b",
            text,
        )
    )


def _is_abstract_general_question(outcome_meta: dict[str, str]) -> bool:
    query = normalize_single_line(str(outcome_meta.get("QUERY", "")).lower())
    return bool(
        re.search(
            r"\b(explain|overview|background|plain language|plain english|simple terms)\b",
            query,
        )
    )


def _is_structured_or_well_known_question(outcome_meta: dict[str, str]) -> bool:
    query = normalize_single_line(str(outcome_meta.get("QUERY", "")).lower())
    if not query or _has_temporal_currentness_terms(query):
        return False
    if re.search(
        r"\b(who is|who was|what is|what was|when was|where is|where was|define|definition of|biography|brief history|tell me about)\b",
        query,
    ):
        return True
    provider_selection_reason = normalize_single_line(str(outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_REASON", "")).lower())
    provider_selection_rule = normalize_single_line(str(outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_RULE", "")).lower())
    if provider_selection_rule == "background_overview":
        return True
    return "stable factual overview" in provider_selection_reason


def _multiple_consistent_signals_modifier(outcome_meta: dict[str, str], source_basis: list[str]) -> int:
    provider_status = normalize_single_line(str(outcome_meta.get("AUGMENTED_PROVIDER_STATUS", "")).lower())
    provider_present = any(item.startswith("augmented_provider_") for item in source_basis)
    context_used = _truthy_text(outcome_meta.get("UNVERIFIED_CONTEXT_USED")) or bool(
        str(outcome_meta.get("UNVERIFIED_CONTEXT_TITLE", "")).strip()
        or str(outcome_meta.get("UNVERIFIED_CONTEXT_URL", "")).strip()
    )
    signal_count = 0
    if provider_present:
        signal_count += 1
    if "local_model_background" in source_basis:
        signal_count += 1
    if provider_status == "available":
        signal_count += 1
    if context_used:
        signal_count += 1
    if signal_count >= 4:
        return 4
    if signal_count >= 3 and provider_present:
        return 2
    return 0


def _confidence_base_for_answer_contract(answer_class: str, source_basis: list[str], verification_status: str) -> int:
    if verification_status == "verified":
        return 85
    if answer_class == "best_effort_recovery_answer":
        return 26
    if "augmented_provider_wikipedia" in source_basis:
        return 42
    if "augmented_provider_openai" in source_basis or "augmented_provider_grok" in source_basis:
        return 32
    if any(item.startswith("augmented_provider_") for item in source_basis):
        return 30
    return 24


def _read_history_entries(history_file: Path | None, *, limit: int = 240) -> list[dict[str, Any]]:
    if history_file is None:
        return []
    entries: list[dict[str, Any]] = []
    for path in _history_scan_paths(history_file):
        try:
            raw_lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw_line in raw_lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
    if len(entries) > limit:
        return entries[-limit:]
    return entries


def _history_provider_stability_modifier(outcome_meta: dict[str, str], history_file: Path | None) -> int:
    provider = normalize_single_line(
        str(
            outcome_meta.get("AUGMENTED_PROVIDER_USED")
            or outcome_meta.get("AUGMENTED_PROVIDER")
            or outcome_meta.get("AUGMENTED_PROVIDER_SELECTED")
            or ""
        ).lower()
    )
    if not provider or provider == "none":
        return 0
    unstable_statuses = {"external_unavailable", "misconfigured", "provider_error", "unavailable", "unstable"}
    unstable_count = 0
    observed_count = 0
    for entry in reversed(_read_history_entries(history_file)):
        outcome = entry.get("outcome")
        if not isinstance(outcome, dict):
            continue
        historical_provider = normalize_single_line(
            str(
                outcome.get("augmented_provider_used")
                or outcome.get("augmented_provider")
                or outcome.get("augmented_provider_selected")
                or ""
            ).lower()
        )
        if historical_provider != provider:
            continue
        provider_status = normalize_single_line(str(outcome.get("augmented_provider_status", "")).lower())
        if not provider_status or provider_status in {"none", "not_used"}:
            continue
        observed_count += 1
        if provider_status in unstable_statuses:
            unstable_count += 1
        if observed_count >= 6:
            break
    if unstable_count >= 2:
        return -4
    if unstable_count == 1:
        return -2
    return 0


def _normalized_answer_text(text: str) -> str:
    return normalize_single_line(_operator_answer_text(text).lower())


def _answer_similarity_metrics(current_text: str, previous_text: str) -> tuple[float, float]:
    current_normalized = _normalized_answer_text(current_text)
    previous_normalized = _normalized_answer_text(previous_text)
    if not current_normalized or not previous_normalized:
        return 0.0, 0.0
    ratio = difflib.SequenceMatcher(a=current_normalized, b=previous_normalized).ratio()
    current_tokens = set(re.findall(r"[a-z0-9]{3,}", current_normalized))
    previous_tokens = set(re.findall(r"[a-z0-9]{3,}", previous_normalized))
    if not current_tokens or not previous_tokens:
        return ratio, 0.0
    overlap = len(current_tokens & previous_tokens)
    union = len(current_tokens | previous_tokens)
    jaccard = overlap / union if union else 0.0
    return ratio, jaccard


def _repeat_consistency_modifier(
    request_text: str,
    response_text: str,
    history_file: Path | None,
) -> tuple[int, str]:
    request_key = normalize_single_line(request_text.lower())
    current_answer = _operator_answer_text(response_text)
    if not request_key or not current_answer:
        return 0, "not_checked"
    for entry in reversed(_read_history_entries(history_file)):
        historical_request = normalize_single_line(str(entry.get("request_text", "")).lower())
        if historical_request != request_key:
            continue
        previous_response = str(entry.get("response_text", "") or "")
        if not previous_response:
            continue
        ratio, jaccard = _answer_similarity_metrics(current_answer, previous_response)
        if ratio >= 0.86 or (ratio >= 0.74 and jaccard >= 0.58):
            return 4, "stable_repeat"
        if (ratio <= 0.45 and jaccard <= 0.35) or (ratio <= 0.62 and jaccard <= 0.30):
            return -6, "divergent_repeat"
        return 0, "mixed_repeat"
    return 0, "first_seen"


def _estimated_confidence_for_answer_contract(
    outcome_meta: dict[str, str],
    answer_class: str,
    source_basis: list[str],
    verification_status: str,
    *,
    request_text: str,
    response_text: str,
    history_file: Path | None,
) -> tuple[int, str]:
    provider_status = str(outcome_meta.get("AUGMENTED_PROVIDER_STATUS", "")).strip().lower()
    clarification_required = _truthy_text(outcome_meta.get("AUGMENTED_CLARIFICATION_REQUIRED"))
    confidence = _confidence_base_for_answer_contract(answer_class, source_basis, verification_status)
    confidence += _multiple_consistent_signals_modifier(outcome_meta, source_basis)
    if clarification_required:
        confidence -= 8
    if provider_status in {"external_unavailable", "misconfigured", "provider_error", "unstable"}:
        confidence -= 6
    confidence += _history_provider_stability_modifier(outcome_meta, history_file)
    if _is_abstract_general_question(outcome_meta):
        confidence -= 3
    if _is_structured_or_well_known_question(outcome_meta):
        confidence += 4
    repeat_modifier, repeat_signal = _repeat_consistency_modifier(request_text, response_text, history_file)
    confidence += repeat_modifier
    return max(20, min(90, int(confidence))), repeat_signal


def _confidence_band_for_pct(estimated_confidence_pct: int) -> str:
    if estimated_confidence_pct >= 70:
        return "High"
    if estimated_confidence_pct >= 40:
        return "Moderate"
    return "Low"


def _confidence_label_for_pct(estimated_confidence_pct: int, confidence_band: str) -> str:
    return f"{estimated_confidence_pct}% ({confidence_band}, estimated)"


def _answer_contract_notes(
    outcome_meta: dict[str, str],
    answer_class: str,
    source_basis: list[str],
    verification_status: str,
) -> str:
    if verification_status == "verified":
        return ""
    if _truthy_text(outcome_meta.get("AUGMENTED_CLARIFICATION_REQUIRED")):
        return "The augmented lane preferred a narrower question, so this answer is especially tentative."
    if answer_class == "best_effort_recovery_answer":
        return "No allowlisted evidence confirmed this directly."
    provider_status = str(outcome_meta.get("AUGMENTED_PROVIDER_STATUS", "")).strip().lower()
    if provider_status in {"external_unavailable", "misconfigured", "provider_error"} and source_basis == ["local_model_background"]:
        return "Provider background was unavailable, so this answer uses only local model background."
    return "No allowlisted evidence confirmed this directly."


def build_augmented_answer_contract(
    outcome_meta: dict[str, str],
    answer_class: str,
    response_text: str,
    *,
    request_text: str = "",
    history_file: Path | None = None,
) -> dict[str, Any]:
    if answer_class not in {"augmented_unverified_fallback", "augmented_unverified_answer", "best_effort_recovery_answer"}:
        return {}

    answer_text = _operator_answer_text(response_text)
    if not answer_text:
        return {}

    source_basis = _source_basis_for_answer_contract(outcome_meta, answer_class)
    verification_status = _verification_status_for_answer_contract(outcome_meta, answer_class, source_basis)
    estimated_confidence_pct, consistency_signal = _estimated_confidence_for_answer_contract(
        outcome_meta,
        answer_class,
        source_basis,
        verification_status,
        request_text=request_text or str(outcome_meta.get("QUERY", "")).strip(),
        response_text=response_text,
        history_file=history_file,
    )
    estimated_confidence_band = _confidence_band_for_pct(estimated_confidence_pct)
    contract: dict[str, Any] = {
        "answer": answer_text,
        "verification_status": verification_status,
        "estimated_confidence_pct": estimated_confidence_pct,
        "estimated_confidence_band": estimated_confidence_band,
        "estimated_confidence_label": _confidence_label_for_pct(estimated_confidence_pct, estimated_confidence_band),
        "source_basis": source_basis,
        "notes": _answer_contract_notes(
            outcome_meta,
            answer_class,
            source_basis,
            verification_status,
        ),
    }
    if consistency_signal != "not_checked":
        contract["consistency_signal"] = consistency_signal
    provider_status = str(outcome_meta.get("AUGMENTED_PROVIDER_STATUS", "")).strip()
    if answer_class in {"augmented_unverified_fallback", "augmented_unverified_answer"} and provider_status:
        contract["provider_status"] = provider_status
    return contract


def operator_trust_label(answer_class: str) -> str:
    if answer_class == "evidence_backed_answer":
        return "evidence-backed"
    if answer_class in {"augmented_unverified_fallback", "augmented_unverified_answer"}:
        return "unverified"
    if answer_class == "operator_blocked":
        return "blocked"
    if answer_class == "validation_failed":
        return "unresolved"
    if answer_class == "requires_evidence_mode":
        return "evidence-required"
    if answer_class == "best_effort_recovery_answer":
        return "best-effort"
    if answer_class == "clarification_required":
        return "clarify-first"
    if answer_class == "local_answer":
        return "local"
    return "unknown"


def operator_answer_path(outcome_meta: dict[str, str], answer_class: str) -> str:
    provider = str(
        outcome_meta.get("AUGMENTED_PROVIDER_USED")
        or outcome_meta.get("AUGMENTED_PROVIDER")
        or outcome_meta.get("AUGMENTED_PROVIDER_SELECTED")
        or ""
    ).strip()
    provider_label = provider.upper() if provider and provider.lower() != "none" else "augmented"
    fallback_reason = str(outcome_meta.get("FALLBACK_REASON", "")).strip()

    if answer_class == "augmented_unverified_fallback":
        if fallback_reason == "local_generation_degraded":
            return f"Local degraded -> {provider_label} fallback"
        if fallback_reason == "validated_insufficient":
            return f"Evidence insufficient -> {provider_label} fallback"
        return f"{provider_label} fallback"
    if answer_class == "augmented_unverified_answer":
        if _truthy_text(outcome_meta.get("AUGMENTED_DIRECT_REQUEST")):
            return f"Forced augmented -> {provider_label}"
        return f"Augmented via {provider_label}"
    if answer_class == "best_effort_recovery_answer":
        return "Evidence insufficient -> local best-effort recovery"
    if answer_class == "evidence_backed_answer":
        return "Evidence-backed answer"
    if answer_class == "operator_blocked":
        return "Evidence route blocked"
    if answer_class == "validation_failed":
        if final_mode := _mode_candidate(outcome_meta, "FINAL_MODE", "REQUESTED_MODE", "MODE"):
            if final_mode == "EVIDENCE":
                return "Evidence validation failed"
            if final_mode == "LOCAL":
                return "Local validation failed"
        return "Validation failed"
    if answer_class == "requires_evidence_mode":
        return "Evidence mode required"
    if answer_class == "clarification_required":
        return "Clarification requested"
    if answer_class == "local_answer":
        return "Local answer"
    return "unknown"


def operator_note(outcome_meta: dict[str, str], answer_class: str) -> str:
    fallback_reason = str(outcome_meta.get("FALLBACK_REASON", "")).strip()
    action_hint = str(outcome_meta.get("ACTION_HINT", "")).strip()
    if answer_class == "augmented_unverified_fallback" and fallback_reason == "local_generation_degraded":
        return "Escalated because the local answer degraded."
    if answer_class == "augmented_unverified_fallback" and fallback_reason == "validated_insufficient":
        return "Escalated because the evidence path was insufficient."
    if answer_class == "operator_blocked":
        return "Evidence is disabled by operator control."
    if answer_class == "validation_failed":
        if action_hint:
            return f"Could not validate a reliable answer. Next step: {action_hint}."
        return "Could not validate a reliable answer from the selected route."
    if answer_class == "requires_evidence_mode":
        return "This request needs evidence mode to answer reliably."
    if answer_class == "best_effort_recovery_answer":
        return "Verification was insufficient, so a local best-effort answer was shown."
    if answer_class == "evidence_backed_answer":
        return "Answer is grounded in current evidence."
    if answer_class == "clarification_required":
        return "A narrower question is required for correctness."
    if answer_class == "local_answer":
        return "No escalation was needed."
    if answer_class == "augmented_unverified_answer":
        return "Answer used unverified augmented background."
    return "No concise operator note is available."


def build_authority_payload() -> dict[str, Any]:
    authority_root = resolve_root()
    runtime_namespace = default_runtime_namespace_root()
    legacy_root = legacy_runtime_namespace_root()
    return {
        "active_root": str(authority_root),
        "authority_root": str(authority_root),
        "runtime_namespace_root": str(runtime_namespace),
        "legacy_runtime_namespace_root": str(legacy_root),
        "legacy_runtime_namespace_present": legacy_root.exists(),
        "legacy_runtime_namespace_status": legacy_runtime_namespace_status(
            runtime_namespace_root=runtime_namespace,
            legacy_root=legacy_root,
        ),
    }


def build_outcome_payload(
    outcome_meta: dict[str, str],
    *,
    response_text: str = "",
    request_text: str = "",
    augmented_direct_request: str = "",
    returncode: int | None = None,
    history_file: Path | None = None,
) -> dict[str, Any]:
    evidence_mode = outcome_meta.get("MANIFEST_EVIDENCE_MODE", "")
    evidence_mode_reason = outcome_meta.get("MANIFEST_EVIDENCE_MODE_REASON", "")
    answer_class = determine_answer_class(outcome_meta)
    provider_authorization = determine_provider_authorization(outcome_meta, answer_class)
    return {
        "action_hint": outcome_meta.get("ACTION_HINT", ""),
        "requested_mode": outcome_meta.get("REQUESTED_MODE", ""),
        "final_mode": outcome_meta.get("FINAL_MODE", ""),
        "answer_class": answer_class,
        "provider_authorization": provider_authorization,
        "operator_trust_label": operator_trust_label(answer_class),
        "operator_answer_path": operator_answer_path(outcome_meta, answer_class),
        "operator_note": operator_note(outcome_meta, answer_class),
        "fallback_used": outcome_meta.get("FALLBACK_USED", ""),
        "fallback_reason": outcome_meta.get("FALLBACK_REASON", ""),
        "trust_class": outcome_meta.get("TRUST_CLASS", ""),
        "intent_family": outcome_meta.get("MANIFEST_INTENT_FAMILY", "") or outcome_meta.get("INTENT_FAMILY", ""),
        "evidence_mode": evidence_mode,
        "evidence_mode_reason": evidence_mode_reason,
        "evidence_mode_selection": evidence_mode_selection_label(evidence_mode, evidence_mode_reason),
        "augmented_allowed": outcome_meta.get("AUGMENTED_ALLOWED", ""),
        "augmented_provider": outcome_meta.get("AUGMENTED_PROVIDER", ""),
        "augmented_provider_selected": outcome_meta.get("AUGMENTED_PROVIDER_SELECTED", ""),
        "augmented_provider_used": outcome_meta.get("AUGMENTED_PROVIDER_USED", ""),
        "augmented_provider_usage_class": outcome_meta.get("AUGMENTED_PROVIDER_USAGE_CLASS", ""),
        "augmented_provider_call_reason": outcome_meta.get("AUGMENTED_PROVIDER_CALL_REASON", ""),
        "augmented_provider_status": outcome_meta.get("AUGMENTED_PROVIDER_STATUS", ""),
        "augmented_provider_error_reason": outcome_meta.get("AUGMENTED_PROVIDER_ERROR_REASON", ""),
        "augmented_provider_selection_reason": outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_REASON", ""),
        "augmented_provider_selection_query": outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_QUERY", ""),
        "augmented_provider_selection_rule": outcome_meta.get("AUGMENTED_PROVIDER_SELECTION_RULE", ""),
        "augmented_provider_cost_notice": outcome_meta.get("AUGMENTED_PROVIDER_COST_NOTICE", ""),
        "augmented_paid_provider_invoked": outcome_meta.get("AUGMENTED_PAID_PROVIDER_INVOKED", ""),
        "augmentation_policy": outcome_meta.get("AUGMENTATION_POLICY", ""),
        "augmented_direct_request": outcome_meta.get("AUGMENTED_DIRECT_REQUEST", "") or augmented_direct_request,
        "unverified_context_used": outcome_meta.get("UNVERIFIED_CONTEXT_USED", ""),
        "unverified_context_class": outcome_meta.get("UNVERIFIED_CONTEXT_CLASS", ""),
        "unverified_context_title": outcome_meta.get("UNVERIFIED_CONTEXT_TITLE", ""),
        "unverified_context_url": outcome_meta.get("UNVERIFIED_CONTEXT_URL", ""),
        "primary_outcome_code": outcome_meta.get("PRIMARY_OUTCOME_CODE", ""),
        "primary_trust_class": outcome_meta.get("PRIMARY_TRUST_CLASS", ""),
        "recovery_attempted": outcome_meta.get("RECOVERY_ATTEMPTED", ""),
        "recovery_used": outcome_meta.get("RECOVERY_USED", ""),
        "recovery_eligible": outcome_meta.get("RECOVERY_ELIGIBLE", ""),
        "recovery_lane": outcome_meta.get("RECOVERY_LANE", ""),
        "augmented_behavior_shape": outcome_meta.get("AUGMENTED_BEHAVIOR_SHAPE", ""),
        "augmented_clarification_required": outcome_meta.get("AUGMENTED_CLARIFICATION_REQUIRED", ""),
        "augmented_answer_contract": build_augmented_answer_contract(
            outcome_meta,
            answer_class,
            response_text,
            request_text=request_text,
            history_file=history_file,
        ),
        "self_review_request": outcome_meta.get("SELF_REVIEW_REQUEST", ""),
        "self_review_mode": outcome_meta.get("SELF_REVIEW_MODE", ""),
        "self_review_targets": outcome_meta.get("SELF_REVIEW_TARGETS", ""),
        "self_review_target_count": outcome_meta.get("SELF_REVIEW_TARGET_COUNT", ""),
        "evidence_created": outcome_meta.get("EVIDENCE_CREATED", ""),
        "outcome_code": outcome_meta.get("OUTCOME_CODE", ""),
        "rc": returncode if returncode is not None else parse_int(outcome_meta.get("RC")),
        "utc": outcome_meta.get("UTC", ""),
    }


def build_route_payload(
    route_meta: dict[str, str],
    outcome_meta: dict[str, str],
    *,
    request_text: str,
) -> dict[str, Any]:
    evidence_mode = outcome_meta.get("MANIFEST_EVIDENCE_MODE", "")
    evidence_mode_reason = outcome_meta.get("MANIFEST_EVIDENCE_MODE_REASON", "")
    selected_route = (
        outcome_meta.get("MANIFEST_SELECTED_ROUTE", "")
        or outcome_meta.get("ROUTE_MODE", "")
        or route_meta.get("MODE", "")
        or outcome_meta.get("FINAL_MODE", "")
    )
    route_mode = route_meta.get("MODE", "") or outcome_meta.get("ROUTE_MODE", "") or selected_route
    return {
        "mode": route_mode,
        "selected_route": selected_route,
        "requested_mode": outcome_meta.get("REQUESTED_MODE", ""),
        "final_mode": outcome_meta.get("FINAL_MODE", ""),
        "intent_class": outcome_meta.get("GOVERNOR_INTENT", "") or outcome_meta.get("CLASSIFIER_INTENT", ""),
        "intent_family": outcome_meta.get("MANIFEST_INTENT_FAMILY", "") or outcome_meta.get("INTENT_FAMILY", ""),
        "evidence_mode": evidence_mode,
        "evidence_mode_reason": evidence_mode_reason,
        "evidence_mode_selection": evidence_mode_selection_label(evidence_mode, evidence_mode_reason),
        "authority_basis": outcome_meta.get("MANIFEST_AUTHORITY_BASIS", ""),
        "winning_signal": outcome_meta.get("WINNING_SIGNAL", ""),
        "query": route_meta.get("QUERY", "") or outcome_meta.get("QUERY", "") or request_text,
        "reason": route_meta.get("ROUTE_REASON", "") or outcome_meta.get("ROUTE_REASON", ""),
        "session_id": route_meta.get("SESSION_ID", "") or outcome_meta.get("SESSION_ID", ""),
        "utc": route_meta.get("UTC", "") or outcome_meta.get("UTC", ""),
    }


def build_rejected_payload(error: str) -> dict[str, Any]:
    return build_failed_payload(
        request_text="",
        error=error,
        status="rejected",
        accepted=False,
    )


def build_failed_payload(
    *,
    request_text: str,
    error: str,
    status: str,
    accepted: bool,
    request_id: str | None = None,
    control_state: dict[str, Any] | None = None,
    response_text: str = "",
    route_meta: dict[str, str] | None = None,
    outcome_meta: dict[str, str] | None = None,
    returncode: int | None = None,
    augmented_direct_request: str = "",
) -> dict[str, Any]:
    route_meta = route_meta or {}
    outcome_meta = outcome_meta or {}
    return {
        "accepted": accepted,
        "authority": build_authority_payload(),
        "completed_at": iso_now(),
        "control_state": {
            "mode": (control_state or {}).get("mode", ""),
            "memory": (control_state or {}).get("memory", ""),
            "evidence": (control_state or {}).get("evidence", ""),
            "voice": (control_state or {}).get("voice", ""),
            "augmentation_policy": (control_state or {}).get("augmentation_policy", ""),
            "augmented_provider": (control_state or {}).get("augmented_provider", ""),
            "model": (control_state or {}).get("model", ""),
            "profile": (control_state or {}).get("profile", ""),
        },
        "error": error,
        "outcome": build_outcome_payload(
            outcome_meta,
            response_text=response_text,
            request_text=request_text,
            augmented_direct_request=augmented_direct_request,
            returncode=returncode,
        ),
        "request_id": request_id or make_request_id(),
        "request_text": request_text,
        "response_text": response_text,
        "route": build_route_payload(route_meta, outcome_meta, request_text=request_text),
        "status": status,
    }


def persist_payload(result_file: Path, payload: dict[str, Any]) -> None:
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with locked_state_file(result_file):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=result_file.parent,
            delete=False,
            prefix=".last_request_result.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, result_file)
    persist_route_snapshot(payload)
    append_history_entry(resolve_history_file(), payload)


def persist_route_snapshot(payload: dict[str, Any]) -> None:
    route = payload.get("route")
    if not isinstance(route, dict):
        return
    selected_route = _stringify(route.get("selected_route") or route.get("mode") or route.get("final_mode"))
    if not selected_route:
        return

    snapshot_path = resolve_ui_state_dir() / "last_route.json"
    snapshot = build_route_snapshot_payload(payload)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    with locked_state_file(snapshot_path):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=snapshot_path.parent,
            delete=False,
            prefix=".last_route.",
            suffix=".tmp",
        ) as handle:
            json.dump(snapshot, handle, indent=2, sort_keys=True)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, snapshot_path)


def build_route_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else build_authority_payload()
    current_route = _stringify(route.get("selected_route") or route.get("mode") or route.get("final_mode") or route.get("requested_mode"))
    provider_used = _stringify(
        outcome.get("augmented_provider_used")
        or outcome.get("augmented_provider")
        or outcome.get("augmented_provider_selected")
    )
    source_type = determine_route_source_type(current_route=current_route, provider_used=provider_used, trust_class=_stringify(outcome.get("trust_class")))
    return {
        "current_route": current_route,
        "final_mode": _stringify(route.get("final_mode")),
        "intent_family": _stringify(route.get("intent_family")),
        "mode": _stringify(route.get("mode")),
        "outcome_code": _stringify(outcome.get("outcome_code")),
        "provider_used": provider_used or "none",
        "request_id": _stringify(payload.get("request_id")),
        "route": current_route,
        "route_reason": _stringify(route.get("reason")),
        "selected_route": _stringify(route.get("selected_route")),
        "source": source_type,
        "source_type": source_type,
        "status": _stringify(payload.get("status")),
        "answer_class": _stringify(outcome.get("answer_class")),
        "provider_authorization": _stringify(outcome.get("provider_authorization")),
        "operator_trust_label": _stringify(outcome.get("operator_trust_label")),
        "operator_answer_path": _stringify(outcome.get("operator_answer_path")),
        "trust_class": _stringify(outcome.get("trust_class")),
        "updated_at": _stringify(payload.get("completed_at")) or iso_now(),
        "authority": authority if isinstance(authority, dict) else {},
    }


def determine_route_source_type(*, current_route: str, provider_used: str, trust_class: str) -> str:
    route_label = current_route.strip().upper()
    provider_label = provider_used.strip().lower()
    trust_label = trust_class.strip().lower()
    if provider_label in {"openai", "grok", "wikipedia"}:
        return provider_label
    if route_label == "LOCAL":
        return "local"
    if route_label == "EVIDENCE":
        return "evidence"
    if route_label == "SELF_REVIEW":
        return "self_review"
    if trust_label:
        return trust_label
    return "unknown"


def append_history_entry(history_file: Path, payload: dict[str, Any]) -> None:
    entry = build_history_entry(payload)
    request_id = str(entry.get("request_id", "")).strip()
    if not request_id:
        return

    history_file.parent.mkdir(parents=True, exist_ok=True)
    with locked_state_file(history_file):
        if _history_contains_request_id(history_file, request_id):
            return
        with history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True))
            handle.write("\n")
        rotate_history_if_needed(history_file, max_entries=resolve_history_max_entries())


def build_history_entry(payload: dict[str, Any]) -> dict[str, Any]:
    control_state = payload.get("control_state")
    return {
        "authority": payload.get("authority", {}) if isinstance(payload.get("authority"), dict) else {},
        "completed_at": payload.get("completed_at", ""),
        "control_state": control_state if isinstance(control_state, dict) else {},
        "error": payload.get("error", ""),
        "outcome": payload.get("outcome", {}) if isinstance(payload.get("outcome"), dict) else {},
        "request_id": payload.get("request_id", ""),
        "request_text": payload.get("request_text", ""),
        "response_text": payload.get("response_text", ""),
        "route": payload.get("route", {}) if isinstance(payload.get("route"), dict) else {},
        "status": payload.get("status", ""),
    }


def _history_contains_request_id(history_file: Path, request_id: str) -> bool:
    for path in _history_scan_paths(history_file):
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict) and str(parsed.get("request_id", "")).strip() == request_id:
                    return True
        except OSError:
            continue
    return False


def rotate_history_if_needed(history_file: Path, *, max_entries: int) -> None:
    lines = _read_history_lines(history_file)
    if len(lines) <= max_entries:
        return

    archive_lines = lines[:-max_entries]
    active_lines = lines[-max_entries:]
    archive_file = _next_archive_path(history_file)

    _write_lines_atomic(archive_file, archive_lines, prefix=".request_history_archive.")
    _write_lines_atomic(history_file, active_lines, prefix=".request_history_active.")


def _read_history_lines(history_file: Path) -> list[str]:
    if not history_file.exists():
        return []
    try:
        return [line for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        raise RuntimeRequestError(f"unable to read history file {history_file}: {exc}") from exc


def _write_lines_atomic(path: Path, lines: list[str], *, prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        prefix=prefix,
        suffix=".tmp",
    ) as handle:
        for line in lines:
            handle.write(line.rstrip("\n"))
            handle.write("\n")
        tmp_path = Path(handle.name)
        os.replace(tmp_path, path)


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _history_scan_paths(history_file: Path) -> list[Path]:
    archive_pattern = f"{history_file.stem}.*{history_file.suffix}"
    archive_paths = sorted(history_file.parent.glob(archive_pattern))
    paths: list[Path] = []
    if history_file.exists():
        paths.append(history_file)
    paths.extend(path for path in archive_paths if path.is_file())
    return paths


def _next_archive_path(history_file: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    candidate = history_file.with_name(f"{history_file.stem}.{timestamp}{history_file.suffix}")
    if not candidate.exists():
        return candidate

    suffix = 1
    while True:
        candidate = history_file.with_name(
            f"{history_file.stem}.{timestamp}-{suffix}{history_file.suffix}"
        )
        if not candidate.exists():
            return candidate
        suffix += 1


if __name__ == "__main__":
    sys.exit(main())
