#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"
UI_ROOT_ENV = "LUCY_UI_ROOT"
RUNTIME_NAMESPACE_ENV = "LUCY_RUNTIME_NAMESPACE_ROOT"
CONTRACT_REQUIRED_ENV = "LUCY_RUNTIME_CONTRACT_REQUIRED"
LEGACY_ROOT_ENV = "LUCY_ROOT"
SCRIPT_PATH = Path(__file__).resolve()
SNAPSHOT_ROOT = SCRIPT_PATH.parents[2]
LUCY_ROOT = SNAPSHOT_ROOT.parents[1]
USER_HOME = LUCY_ROOT.parent
TOOLS_DIR = SNAPSHOT_ROOT / "tools"
LAUNCHER_PATH = TOOLS_DIR / "start_local_lucy_opt_experimental_v7_dev.sh"
DESKTOP_MANIFEST_PATH = SNAPSHOT_ROOT / "config" / "launcher" / "desktop_launchers.tsv"
UI_RUNTIME_BRIDGE_PATH = LUCY_ROOT / "ui-v7" / "app" / "services" / "runtime_bridge.py"
RUNTIME_REQUEST_PATH = TOOLS_DIR / "runtime_request.py"
ROUTER_EXECUTE_PLAN_PATH = TOOLS_DIR / "router" / "execute_plan.sh"
PLAN_TO_PIPELINE_PATH = TOOLS_DIR / "router" / "plan_to_pipeline.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Print the active Local Lucy v7 authority chain.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    payload = build_payload()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    ordered_keys = (
        "snapshot_root",
        "active_root",
        "authority_override_env",
        "authority_override_root",
        "authority_root_source",
        "ambient_lucy_root",
        "ambient_lucy_root_ignored",
        "launcher",
        "desktop_manifest",
        "desktop_current_entry",
        "desktop_current_exec_target",
        "desktop_current_status",
        "runtime_bridge",
        "runtime_bridge_classification",
        "runtime_bridge_request_tool",
        "runtime_bridge_status",
        "runtime_request",
        "runtime_request_root",
        "ui_root",
        "ui_root_source",
        "runtime_namespace_root",
        "runtime_namespace_root_source",
        "authority_contract_required",
        "authority_contract_status",
        "legacy_runtime_namespace_root",
        "legacy_runtime_namespace_present",
        "legacy_runtime_namespace_status",
        "lucy_chat",
        "execute_plan",
        "plan_to_pipeline",
        "manifest_source",
    )
    for key in ordered_keys:
        print(f"{key}={payload[key]}")
    return 0


def build_payload() -> dict[str, str]:
    runtime_request_root = resolve_authority_root()
    runtime_request_path = runtime_request_root / "tools" / "runtime_request.py"
    runtime_namespace_root = resolve_runtime_namespace_root()
    ui_root = resolve_ui_root()
    legacy_runtime_namespace_root = resolve_legacy_runtime_namespace_root()
    runtime_bridge_paths = parse_runtime_bridge_paths(UI_RUNTIME_BRIDGE_PATH)
    desktop_entry_path, desktop_exec_target = read_current_desktop_entry(DESKTOP_MANIFEST_PATH)
    ambient_lucy_root = normalize_env_path(LEGACY_ROOT_ENV)
    authority_override_root = normalize_env_path(AUTHORITY_ROOT_ENV)
    bridge_request_tool = runtime_bridge_paths.get("request_tool_path", "")
    if authority_override_root and runtime_bridge_supports_authority_override(UI_RUNTIME_BRIDGE_PATH):
        bridge_request_tool = str(Path(authority_override_root) / "tools" / "runtime_request.py")
    manifest_source = runtime_request_root / "tools" / "router" / "core" / "route_manifest.py"

    return {
        "snapshot_root": str(SNAPSHOT_ROOT),
        "active_root": str(runtime_request_root),
        "authority_override_env": AUTHORITY_ROOT_ENV,
        "authority_override_root": authority_override_root,
        "authority_root_source": "env" if authority_override_root else "snapshot_default",
        "ambient_lucy_root": ambient_lucy_root,
        "ambient_lucy_root_ignored": bool_text(
            bool(ambient_lucy_root) and Path(ambient_lucy_root) != runtime_request_root
        ),
        "launcher": str(LAUNCHER_PATH),
        "desktop_manifest": str(DESKTOP_MANIFEST_PATH),
        "desktop_current_entry": desktop_entry_path,
        "desktop_current_exec_target": desktop_exec_target,
        "desktop_current_status": alignment_status(desktop_exec_target, LAUNCHER_PATH),
        "runtime_bridge": str(UI_RUNTIME_BRIDGE_PATH),
        "runtime_bridge_classification": "permitted_global_control_plane_exception",
        "runtime_bridge_request_tool": bridge_request_tool,
        "runtime_bridge_status": alignment_status(bridge_request_tool, runtime_request_path),
        "runtime_request": str(runtime_request_path),
        "runtime_request_root": str(runtime_request_root),
        "ui_root": str(ui_root),
        "ui_root_source": "env" if os.environ.get(UI_ROOT_ENV, "").strip() else "default_ui_v7",
        "runtime_namespace_root": str(runtime_namespace_root),
        "runtime_namespace_root_source": (
            "env" if os.environ.get(RUNTIME_NAMESPACE_ENV, "").strip() else "home_fallback"
        ),
        "authority_contract_required": bool_text(contract_required()),
        "authority_contract_status": contract_status(runtime_request_root, ui_root, runtime_namespace_root),
        "legacy_runtime_namespace_root": str(legacy_runtime_namespace_root),
        "legacy_runtime_namespace_present": bool_text(legacy_runtime_namespace_root.exists()),
        "legacy_runtime_namespace_status": classify_legacy_runtime_namespace(
            runtime_namespace_root, legacy_runtime_namespace_root
        ),
        "lucy_chat": str(runtime_request_root / "lucy_chat.sh"),
        "execute_plan": str(runtime_request_root / "tools" / "router" / "execute_plan.sh"),
        "plan_to_pipeline": str(runtime_request_root / "tools" / "router" / "plan_to_pipeline.py"),
        "manifest_source": str(manifest_source),
    }


def resolve_authority_root() -> Path:
    override = os.environ.get(AUTHORITY_ROOT_ENV, "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return SNAPSHOT_ROOT


def resolve_runtime_namespace_root() -> Path:
    explicit = os.environ.get(RUNTIME_NAMESPACE_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    # V8 ISOLATION: Use v8 runtime namespace
    return USER_HOME / ".codex-api-home" / "lucy" / "runtime-v8"


def resolve_ui_root() -> Path:
    explicit = os.environ.get(UI_ROOT_ENV, "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    return LUCY_ROOT / "ui-v7"


def resolve_legacy_runtime_namespace_root() -> Path:
    # V8 ISOLATION: Use v8 legacy runtime namespace
    return LUCY_ROOT / "runtime-v8"


def normalize_env_path(name: str) -> str:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return ""
    return str(resolve_user_path(raw))


def bool_text(value: bool) -> str:
    return "true" if value else "false"


def contract_required() -> bool:
    raw = os.environ.get(CONTRACT_REQUIRED_ENV, "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def contract_status(authority_root: Path, ui_root: Path, runtime_ns_root: Path) -> str:
    if not contract_required():
        return "not_required"
    if not os.environ.get(AUTHORITY_ROOT_ENV, "").strip():
        return f"missing:{AUTHORITY_ROOT_ENV}"
    if not os.environ.get(UI_ROOT_ENV, "").strip():
        return f"missing:{UI_ROOT_ENV}"
    if not os.environ.get(RUNTIME_NAMESPACE_ENV, "").strip():
        return f"missing:{RUNTIME_NAMESPACE_ENV}"
    # V8 ISOLATION: Only accept v8 authority root
    if authority_root.name != "opt-experimental-v8-dev":
        return f"mismatch_authority:{authority_root}"
    # V8 ISOLATION: Only accept v8 UI root
    if ui_root.name != "ui-v8":
        return f"mismatch_ui:{ui_root}"
    if not runtime_ns_root.is_absolute():
        return f"mismatch_namespace:{runtime_ns_root}"
    return "aligned"


def classify_legacy_runtime_namespace(current_root: Path, legacy_root: Path) -> str:
    if current_root == legacy_root:
        return "same"
    if legacy_root.exists():
        return "stale_parallel_tree_present"
    return "absent"


def alignment_status(actual: str, expected: Path) -> str:
    if not actual:
        return "missing"
    try:
        actual_path = Path(actual).expanduser().resolve()
    except OSError:
        return "invalid"
    return "aligned" if actual_path == expected.resolve() else f"mismatch:{actual_path}"


def parse_runtime_bridge_paths(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        r'self\.(?P<name>[a-z_]+_tool_path)\s*=\s*Path\(\s*"(?P<value>[^"]+)"\s*\)\.expanduser\(\)',
        re.MULTILINE,
    )
    values: dict[str, str] = {}
    for match in pattern.finditer(text):
        values[match.group("name")] = str(resolve_user_path(match.group("value")))
    if values:
        return values
    root_match = re.search(
        r'return\s+Path\(\s*"(?P<value>[^"]+)"\s*\)\.expanduser\(\)\.resolve\(\)',
        text,
        re.MULTILINE,
    )
    if not root_match:
        return values
    snapshot_root = resolve_user_path(root_match.group("value"))
    for tool_name in (
        "control_tool_path",
        "profile_tool_path",
        "lifecycle_tool_path",
        "request_tool_path",
        "voice_tool_path",
    ):
        suffix = tool_name.removesuffix("_tool_path")
        values[tool_name] = str(snapshot_root / "tools" / f"runtime_{suffix}.py")
    return values


def runtime_bridge_supports_authority_override(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    return 'self.authority_root_env = "LUCY_RUNTIME_AUTHORITY_ROOT"' in text


def read_current_desktop_entry(manifest_path: Path) -> tuple[str, str]:
    if not manifest_path.exists():
        return "", ""
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        fields = raw_line.split("\t")
        if len(fields) < 5:
            continue
        desktop_path, _name, _comment, exec_target, _style = fields[:5]
        if "Opt Experimental v7 DEV" in desktop_path:
            return desktop_path, exec_target
    return "", ""


def resolve_user_path(raw: str) -> Path:
    if raw.startswith("~/"):
        return (USER_HOME / raw[2:]).resolve()
    return Path(raw).expanduser().resolve()


if __name__ == "__main__":
    raise SystemExit(main())
