#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
TOOLS_DIR="${ROOT}/tools"
UI_ROOT="/home/mike/lucy-v8/ui-v8"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -d "${TOOLS_DIR}" ]] || die "missing tools dir: ${TOOLS_DIR}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
USER_HOME="${TMPD}/user_home"
SANDBOX_HOME="${USER_HOME}/.codex-api-home"
PLUS_HOME="${USER_HOME}/.codex-plus-home"
mkdir -p "${SANDBOX_HOME}" "${PLUS_HOME}"

check_resolution() {
  local home_value="$1"
  local expected_root="$2"
  HOME="${home_value}" python3 - <<'PY' "${TOOLS_DIR}" "${UI_ROOT}" "${expected_root}" "${home_value}"
import os
import sys
from pathlib import Path

tools_dir = Path(sys.argv[1]).resolve()
ui_root = Path(sys.argv[2]).resolve()
expected_root = Path(sys.argv[3]).resolve()
home_value = Path(sys.argv[4]).resolve()

for key in list(os.environ):
    if key.startswith("LUCY_RUNTIME_") or key.startswith("LUCY_UI_") or key == "LUCY_VOICE_RUNTIME_FILE" or key == "LUCY_VOICE_CAPTURE_DIR":
        os.environ.pop(key, None)

sys.path.insert(0, str(tools_dir))
import runtime_control
import runtime_lifecycle
import runtime_request
import runtime_voice

sys.path.insert(0, str(ui_root))
from app.services import state_store

assert runtime_control.resolve_state_file(None) == expected_root / "state" / "current_state.json"
assert Path(runtime_control.DEFAULT_STATE_FILE) == expected_root / "state" / "current_state.json"

assert runtime_request.resolve_result_file() == expected_root / "state" / "last_request_result.json"
assert runtime_request.resolve_history_file() == expected_root / "state" / "request_history.jsonl"
assert Path(runtime_request.DEFAULT_RESULT_FILE) == expected_root / "state" / "last_request_result.json"
assert Path(runtime_request.DEFAULT_HISTORY_FILE) == expected_root / "state" / "request_history.jsonl"

assert runtime_lifecycle.resolve_lifecycle_file(None) == expected_root / "state" / "runtime_lifecycle.json"
assert runtime_lifecycle.resolve_log_file(None) == expected_root / "logs" / "runtime_lifecycle.log"
assert Path(runtime_lifecycle.DEFAULT_LIFECYCLE_FILE) == expected_root / "state" / "runtime_lifecycle.json"
assert Path(runtime_lifecycle.DEFAULT_LOG_FILE) == expected_root / "logs" / "runtime_lifecycle.log"

assert runtime_voice.resolve_voice_runtime_file(None) == expected_root / "state" / "voice_runtime.json"
assert runtime_voice.resolve_capture_directory(None) == expected_root / "voice" / "ui_ptt"
assert Path(runtime_voice.DEFAULT_VOICE_RUNTIME_FILE) == expected_root / "state" / "voice_runtime.json"
assert Path(runtime_voice.DEFAULT_CAPTURE_DIR) == expected_root / "voice" / "ui_ptt"

authority = runtime_request.build_authority_payload()
assert Path(authority["runtime_namespace_root"]) == expected_root
assert Path(state_store.RUNTIME_NAMESPACE_ROOT) == expected_root
assert Path(state_store.STATE_DIRECTORY) == expected_root / "state"
workspace_home = home_value.parent if home_value.name in {".codex-api-home", ".codex-plus-home"} else home_value
assert Path(state_store.LEGACY_RUNTIME_NAMESPACE_ROOT) == workspace_home / "lucy" / "runtime-v8"
PY
}

check_namespace_override() {
  local home_value="$1"
  local namespace_root="$2"
  HOME="${home_value}" LUCY_RUNTIME_NAMESPACE_ROOT="${namespace_root}" python3 - <<'PY' "${TOOLS_DIR}" "${UI_ROOT}" "${namespace_root}"
import os
import sys
from pathlib import Path

tools_dir = Path(sys.argv[1]).resolve()
ui_root = Path(sys.argv[2]).resolve()
namespace_root = Path(sys.argv[3]).resolve()

for key in list(os.environ):
    if key.startswith("LUCY_RUNTIME_") and key != "LUCY_RUNTIME_NAMESPACE_ROOT":
        os.environ.pop(key, None)
    if key.startswith("LUCY_UI_") or key == "LUCY_VOICE_RUNTIME_FILE" or key == "LUCY_VOICE_CAPTURE_DIR":
        os.environ.pop(key, None)

sys.path.insert(0, str(tools_dir))
import runtime_control
import runtime_lifecycle
import runtime_request
import runtime_voice

sys.path.insert(0, str(ui_root))
from app.services import state_store

assert runtime_control.resolve_state_file(None) == namespace_root / "state" / "current_state.json"
assert Path(runtime_control.DEFAULT_STATE_FILE) == namespace_root / "state" / "current_state.json"
assert runtime_request.resolve_result_file() == namespace_root / "state" / "last_request_result.json"
assert runtime_request.resolve_history_file() == namespace_root / "state" / "request_history.jsonl"
assert runtime_lifecycle.resolve_lifecycle_file(None) == namespace_root / "state" / "runtime_lifecycle.json"
assert runtime_lifecycle.resolve_log_file(None) == namespace_root / "logs" / "runtime_lifecycle.log"
assert runtime_voice.resolve_voice_runtime_file(None) == namespace_root / "state" / "voice_runtime.json"
assert runtime_voice.resolve_capture_directory(None) == namespace_root / "voice" / "ui_ptt"
assert Path(state_store.RUNTIME_NAMESPACE_ROOT) == namespace_root
assert Path(state_store.STATE_DIRECTORY) == namespace_root / "state"
PY
}

EXPECTED_ROOT="${USER_HOME}/.codex-api-home/lucy/runtime-v8"
check_resolution "${USER_HOME}" "${EXPECTED_ROOT}"
check_resolution "${SANDBOX_HOME}" "${EXPECTED_ROOT}"
check_resolution "${PLUS_HOME}" "${EXPECTED_ROOT}"
check_namespace_override "/home/mike/.codex-plus-home" "/home/mike/.codex-api-home/lucy/runtime-v8"

ok "default runtime namespace resolution stays stable for normal and Codex sandbox HOME values"
echo "PASS: test_runtime_namespace_default_resolution"
