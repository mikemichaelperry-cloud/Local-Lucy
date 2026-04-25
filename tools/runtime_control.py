#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import fcntl


MODE_TO_ROUTE_CONTROL = {
    "auto": "AUTO",
    "online": "FORCED_ONLINE",
    "offline": "FORCED_OFFLINE",
}

AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"
UI_ROOT_ENV = "LUCY_UI_ROOT"
RUNTIME_NAMESPACE_ENV = "LUCY_RUNTIME_NAMESPACE_ROOT"
CONTRACT_REQUIRED_ENV = "LUCY_RUNTIME_CONTRACT_REQUIRED"

KNOWN_FIELDS = {
    "schema_version",
    "profile",
    "mode",
    "conversation",
    "memory",
    "evidence",
    "voice",
    "augmentation_policy",
    "augmented_provider",
    "model",
    "approval_required",
    "status",
    "last_updated",
}


class RuntimeControlError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateResult:
    field: str
    value: Any
    changed: bool
    state: dict[str, Any]


@dataclass(frozen=True)
class ResolvedRuntimePaths:
    state_file: Path
    namespace_root: Path
    resolution_source: str
    warning_codes: tuple[str, ...]
    warnings: tuple[str, ...]


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_authority_contract(expected_authority_root=Path(__file__).resolve().parents[1])
        resolved_paths = resolve_runtime_paths(args.state_file)
        state_file = resolved_paths.state_file
        if args.command == "show-state":
            state = load_or_create_state(state_file, refresh_timestamp=False)
            print(json.dumps(state, indent=2, sort_keys=True))
            return 0
        if args.command == "self-check":
            payload = build_self_check_payload(resolved_paths)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "print-env":
            state = load_or_create_state(state_file, refresh_timestamp=False)
            print(render_env(state))
            return 0
        if args.command == "ensure-state":
            state = load_or_create_state(state_file, refresh_timestamp=False)
            print_success("ensure-state", None, None, False, state_file, state)
            return 0

        if args.command == "set-mode":
            result = update_state_field(state_file, "mode", args.value)
        elif args.command == "set-conversation":
            result = update_state_field(state_file, "conversation", args.value)
        elif args.command == "set-memory":
            result = update_state_field(state_file, "memory", args.value)
        elif args.command == "set-evidence":
            result = update_state_field(state_file, "evidence", args.value)
        elif args.command == "set-voice":
            result = update_state_field(state_file, "voice", args.value)
        elif args.command == "set-augmentation":
            result = update_state_field(state_file, "augmentation_policy", args.value)
        elif args.command == "set-augmented-provider":
            result = update_state_field(state_file, "augmented_provider", args.value)
        else:
            raise RuntimeControlError(f"unsupported command: {args.command}")

        print_success(args.command, result.field, result.value, result.changed, state_file, result.state)
        return 0
    except RuntimeControlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authoritative Local Lucy runtime control endpoints.",
    )
    parser.add_argument(
        "--state-file",
        help=f"Override the authoritative state file path. Defaults to {DEFAULT_STATE_FILE} or $LUCY_RUNTIME_STATE_FILE.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("show-state")
    subparsers.add_parser("self-check")
    subparsers.add_parser("print-env")
    subparsers.add_parser("ensure-state")

    mode_parser = subparsers.add_parser("set-mode")
    mode_parser.add_argument("--value", required=True, choices=sorted(MODE_TO_ROUTE_CONTROL))

    for name in ("set-conversation", "set-memory", "set-evidence", "set-voice"):
        toggle_parser = subparsers.add_parser(name)
        toggle_parser.add_argument("--value", required=True, choices=("on", "off"))
    augmentation_parser = subparsers.add_parser("set-augmentation")
    augmentation_parser.add_argument(
        "--value",
        required=True,
        choices=("disabled", "fallback_only", "direct_allowed"),
    )
    provider_parser = subparsers.add_parser("set-augmented-provider")
    provider_parser.add_argument(
        "--value",
        required=True,
        choices=("wikipedia", "grok", "openai"),
    )

    return parser


def resolve_state_file(explicit_path: str | None) -> Path:
    return resolve_runtime_paths(explicit_path).state_file


def resolve_runtime_paths(explicit_path: str | None) -> ResolvedRuntimePaths:
    if contract_required():
        namespace_raw = os.environ.get(RUNTIME_NAMESPACE_ENV, "").strip()
        if not namespace_raw and not explicit_path and not os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip():
            raise RuntimeControlError(
                f"missing required {RUNTIME_NAMESPACE_ENV} while {CONTRACT_REQUIRED_ENV}=1"
            )
    if explicit_path:
        state_file = Path(explicit_path).expanduser()
        return ResolvedRuntimePaths(
            state_file=state_file,
            namespace_root=infer_runtime_namespace_root_from_state_file(state_file),
            resolution_source="cli_state_file",
            warning_codes=(),
            warnings=(),
        )

    raw_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE")
    if raw_state_file:
        state_file = Path(raw_state_file).expanduser()
        return ResolvedRuntimePaths(
            state_file=state_file,
            namespace_root=infer_runtime_namespace_root_from_state_file(state_file),
            resolution_source="env_state_file",
            warning_codes=(),
            warnings=(),
        )

    explicit_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    if explicit_root:
        namespace_root = Path(explicit_root).expanduser()
        return ResolvedRuntimePaths(
            state_file=namespace_root / "state" / "current_state.json",
            namespace_root=namespace_root,
            resolution_source="env_namespace_root",
            warning_codes=(),
            warnings=(),
        )

    namespace_root = home_fallback_runtime_namespace_root()
    return ResolvedRuntimePaths(
        state_file=namespace_root / "state" / "current_state.json",
        namespace_root=namespace_root,
        resolution_source="home_fallback",
        warning_codes=("runtime_namespace_home_fallback",),
        warnings=(
            "Runtime namespace is resolved from HOME fallback only; set LUCY_RUNTIME_NAMESPACE_ROOT or --state-file to pin the authoritative runtime namespace.",
        ),
    )


def default_runtime_namespace_root() -> Path:
    explicit_root = os.environ.get(RUNTIME_NAMESPACE_ENV)
    if explicit_root:
        return Path(explicit_root).expanduser()
    return home_fallback_runtime_namespace_root()


def home_fallback_runtime_namespace_root() -> Path:
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


def contract_required() -> bool:
    raw = os.environ.get(CONTRACT_REQUIRED_ENV, "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def enforce_authority_contract(*, expected_authority_root: Path | None = None) -> None:
    if not contract_required():
        return

    missing = []
    authority_raw = os.environ.get(AUTHORITY_ROOT_ENV, "").strip()
    ui_root_raw = os.environ.get(UI_ROOT_ENV, "").strip()
    runtime_ns_raw = os.environ.get(RUNTIME_NAMESPACE_ENV, "").strip()
    if not authority_raw:
        missing.append(AUTHORITY_ROOT_ENV)
    if not ui_root_raw:
        missing.append(UI_ROOT_ENV)
    if not runtime_ns_raw:
        missing.append(RUNTIME_NAMESPACE_ENV)
    if missing:
        raise RuntimeControlError(f"missing required authority contract env(s): {', '.join(missing)}")

    authority_root = Path(authority_raw).expanduser().resolve()
    ui_root = Path(ui_root_raw).expanduser().resolve()
    runtime_ns_root = Path(runtime_ns_raw).expanduser().resolve()

    if expected_authority_root is not None and authority_root != expected_authority_root.resolve():
        raise RuntimeControlError(
            f"authority root mismatch: env={authority_root} expected={expected_authority_root.resolve()}"
        )
    if not ui_root.exists() or not ui_root.is_dir():
        raise RuntimeControlError(f"invalid UI root in contract: {ui_root}")
    if ui_root.name != "ui-v8":
        raise RuntimeControlError(
            f"V8 ISOLATION VIOLATION: invalid UI root in contract (expected ui-v8): {ui_root}. "
            f"V8 cannot use V7 (ui-v7) components."
        )
    if not runtime_ns_root.is_absolute():
        raise RuntimeControlError(f"invalid runtime namespace root in contract: {runtime_ns_root}")

    raw_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip()
    if raw_state_file:
        state_file = Path(raw_state_file).expanduser().resolve()
        if not _is_relative_to(state_file, runtime_ns_root):
            raise RuntimeControlError(
                f"LUCY_RUNTIME_STATE_FILE is outside {RUNTIME_NAMESPACE_ENV}: {state_file} vs {runtime_ns_root}"
            )


def infer_runtime_namespace_root_from_state_file(state_file: Path) -> Path:
    if state_file.name == "current_state.json" and state_file.parent.name == "state":
        return state_file.parent.parent
    return state_file.parent


DEFAULT_STATE_FILE = str(default_runtime_namespace_root() / "state" / "current_state.json")


def default_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile": os.environ.get("LUCY_RUNTIME_PROFILE")
        or os.environ.get("LUCY_LAUNCHER_LABEL")
        or "opt-experimental-v8-dev",
        "mode": "auto",
        "conversation": coerce_toggle(os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "0")),
        "memory": "on",
        "evidence": "on",
        "voice": "on",
        "augmentation_policy": clean_text(os.environ.get("LUCY_AUGMENTATION_POLICY")) or "fallback_only",
        "augmented_provider": "wikipedia",
        "model": os.environ.get("LUCY_RUNTIME_MODEL") or os.environ.get("LUCY_LOCAL_MODEL") or "local-lucy",
        "approval_required": False,
        "status": "ready",
        "last_updated": iso_now(),
    }


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_or_create_state(state_file: Path, *, refresh_timestamp: bool) -> dict[str, Any]:
    with locked_state_file(state_file):
        current_state = read_state_file(state_file)
        normalized = normalize_state(current_state)
        if refresh_timestamp and current_state is None:
            normalized["last_updated"] = iso_now()
        if current_state != normalized:
            write_state_file(state_file, normalized)
        return normalized


def update_state_field(state_file: Path, field: str, requested_value: str) -> UpdateResult:
    with locked_state_file(state_file):
        current_state = read_state_file(state_file)
        state = normalize_state(current_state)
        prior_value = state[field]
        state[field] = requested_value
        state["last_updated"] = iso_now()
        if field in {"mode", "conversation", "memory", "evidence", "voice", "augmentation_policy", "augmented_provider"}:
            state["status"] = "ready"
        changed = prior_value != requested_value
        write_state_file(state_file, state)
        return UpdateResult(field=field, value=requested_value, changed=changed, state=state)


@contextmanager
def locked_state_file(state_file: Path) -> Iterator[None]:
    lock_file = state_file.with_suffix(state_file.suffix + ".lock")
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_state_file(state_file: Path) -> dict[str, Any] | None:
    if not state_file.exists():
        return None
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeControlError(f"unable to read state file {state_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeControlError(f"state file must contain a JSON object: {state_file}")
    return payload


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeControlError(f"unable to read json file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeControlError(f"json file must contain a JSON object: {path}")
    return payload


def normalize_state(payload: dict[str, Any] | None) -> dict[str, Any]:
    state = default_state()
    extras: dict[str, Any] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in KNOWN_FIELDS:
                state[key] = value
            else:
                extras[key] = value

    state["schema_version"] = 1
    state["profile"] = clean_text(state.get("profile")) or default_state()["profile"]
    state["mode"] = coerce_mode(state.get("mode"))
    state["conversation"] = coerce_toggle(state.get("conversation"))
    state["memory"] = coerce_toggle(state.get("memory"))
    state["evidence"] = coerce_toggle(state.get("evidence"))
    state["voice"] = coerce_toggle(state.get("voice"))
    state["augmentation_policy"] = coerce_augmentation_policy(state.get("augmentation_policy"))
    state["augmented_provider"] = coerce_augmented_provider(state.get("augmented_provider"))
    state["model"] = clean_text(state.get("model")) or default_state()["model"]
    state["approval_required"] = bool(state.get("approval_required", False))
    state["status"] = clean_text(state.get("status")) or "ready"
    state["last_updated"] = clean_text(state.get("last_updated")) or iso_now()
    state.update(extras)
    return state


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def coerce_mode(value: Any) -> str:
    raw = clean_text(value).lower()
    if raw in MODE_TO_ROUTE_CONTROL:
        return raw
    if raw in {"forced_online", "online"}:
        return "online"
    if raw in {"forced_offline", "offline"}:
        return "offline"
    if raw in {"auto", "automatic"}:
        return "auto"
    return "auto"


def coerce_toggle(value: Any) -> str:
    if isinstance(value, bool):
        return "on" if value else "off"
    raw = clean_text(value).lower()
    if raw in {"1", "true", "yes", "on"}:
        return "on"
    if raw in {"0", "false", "no", "off"}:
        return "off"
    return "on"


def coerce_augmentation_policy(value: Any) -> str:
    raw = clean_text(value).lower()
    if raw in {"disabled", "off", "none", "0", "false", "no"}:
        return "disabled"
    if raw in {"fallback_only", "fallback", "1", "true", "yes", "on"}:
        return "fallback_only"
    if raw in {"direct_allowed", "direct", "2"}:
        return "direct_allowed"
    return "disabled"


def coerce_augmented_provider(value: Any) -> str:
    raw = clean_text(value).lower()
    if raw in {"wikipedia", "grok", "openai"}:
        return raw
    return "wikipedia"


def write_state_file(state_file: Path, state: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=state_file.parent,
            delete=False,
            prefix=".current_state.",
            suffix=".tmp",
        ) as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, state_file)
    except OSError as exc:
        raise RuntimeControlError(f"unable to write state file {state_file}: {exc}") from exc


def build_self_check_payload(resolved_paths: ResolvedRuntimePaths) -> dict[str, Any]:
    state = load_or_create_state(resolved_paths.state_file, refresh_timestamp=False)
    result_file = resolve_last_request_result_file(resolved_paths.namespace_root)
    last_result = read_json_object(result_file)
    outcome = last_result.get("outcome") if isinstance(last_result, dict) else None
    if not isinstance(outcome, dict):
        outcome = {}

    availability_provider = (
        clean_text(outcome.get("augmented_provider_used"))
        or clean_text(outcome.get("augmented_provider"))
        or clean_text(state.get("augmented_provider"))
    )
    if not availability_provider or availability_provider.lower() == "none":
        availability_provider = clean_text(state.get("augmented_provider"))

    availability_status = clean_text(outcome.get("augmented_provider_status")).lower()
    if not availability_status:
        if clean_text(state.get("augmentation_policy")).lower() == "disabled":
            availability_status = "disabled"
        elif clean_text(availability_provider).lower() in {"", "none"}:
            availability_status = "not_used"
        else:
            availability_status = "unknown"

    availability_reason = clean_text(outcome.get("augmented_provider_error_reason")) or "none"
    warning_codes = list(resolved_paths.warning_codes)
    warnings = list(resolved_paths.warnings)

    availability_warning_map = {
        "external_unavailable": (
            "augmented_provider_external_unavailable",
            "Structured outcome metadata reports the configured augmented provider as externally unavailable.",
        ),
        "misconfigured": (
            "augmented_provider_misconfigured",
            "Structured outcome metadata reports the configured augmented provider as misconfigured.",
        ),
        "provider_error": (
            "augmented_provider_provider_error",
            "Structured outcome metadata reports a provider-side augmented error.",
        ),
    }
    availability_warning = availability_warning_map.get(availability_status)
    if availability_warning is not None:
        warning_codes.append(availability_warning[0])
        warnings.append(availability_warning[1])

    return {
        "ok": True,
        "action": "self-check",
        "status": "warning" if warning_codes else "ok",
        "resolution_source": resolved_paths.resolution_source,
        "runtime_namespace_root": str(resolved_paths.namespace_root),
        "state_file": str(resolved_paths.state_file),
        "last_request_result_file": str(result_file),
        "warning_codes": warning_codes,
        "warnings": warnings,
        "control_state": {
            "mode": state.get("mode", ""),
            "conversation": state.get("conversation", ""),
            "memory": state.get("memory", ""),
            "evidence": state.get("evidence", ""),
            "voice": state.get("voice", ""),
            "augmentation_policy": state.get("augmentation_policy", ""),
            "augmented_provider": state.get("augmented_provider", ""),
            "profile": state.get("profile", ""),
            "model": state.get("model", ""),
        },
        "augmented_availability": {
            "provider": availability_provider,
            "status": availability_status,
            "error_reason": availability_reason,
            "source": "last_request_result" if outcome else "control_state_only",
        },
    }


def resolve_last_request_result_file(namespace_root: Path) -> Path:
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_RESULT_FILE")
    if raw:
        return Path(raw).expanduser()
    return namespace_root / "state" / "last_request_result.json"


def render_env(state: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"mode={state['mode']}",
            f"conversation={state['conversation']}",
            f"memory={state['memory']}",
            f"evidence={state['evidence']}",
            f"voice={state['voice']}",
            f"augmentation_policy={state['augmentation_policy']}",
            f"augmented_provider={state['augmented_provider']}",
            f"status={state['status']}",
            f"profile={state['profile']}",
            f"model={state['model']}",
            f"LUCY_ROUTE_CONTROL_MODE={MODE_TO_ROUTE_CONTROL[state['mode']]}",
            f"LUCY_CONVERSATION_MODE_FORCE={toggle_to_flag(state['conversation'])}",
            f"LUCY_SESSION_MEMORY={toggle_to_flag(state['memory'])}",
            f"LUCY_EVIDENCE_ENABLED={toggle_to_flag(state['evidence'])}",
            f"LUCY_ENABLE_INTERNET={toggle_to_flag(state['evidence'])}",
            f"LUCY_VOICE_ENABLED={toggle_to_flag(state['voice'])}",
            f"LUCY_AUGMENTATION_POLICY={state['augmentation_policy']}",
            f"LUCY_AUGMENTED_PROVIDER={state['augmented_provider']}",
        ]
    )


def toggle_to_flag(value: str) -> str:
    return "1" if value == "on" else "0"


def print_success(
    action: str,
    field: str | None,
    value: str | None,
    changed: bool,
    state_file: Path,
    state: dict[str, Any],
) -> None:
    payload = {
        "ok": True,
        "action": action,
        "field": field,
        "value": value,
        "changed": changed,
        "state_file": str(state_file),
        "state": state,
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
