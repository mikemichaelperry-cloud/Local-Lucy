#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${CONTROL_TOOL}" ]] || die "missing control tool: ${CONTROL_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
STATE_FILE="${TMPD}/current_state.json"
STATE_FILE_ENV="${TMPD}/current_state_env.json"
CLI_STATE_FILE="${TMPD}/current_state_cli.json"
NAMESPACE_ROOT="${TMPD}/runtime_namespace"
LAST_REQUEST_RESULT_FILE="${NAMESPACE_ROOT}/state/last_request_result.json"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

python3 - <<'PY' "${STATE_FILE}"
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert state["mode"] == "auto"
assert state["conversation"] == "off"
assert state["memory"] == "on"
assert state["evidence"] == "on"
assert state["voice"] == "on"
assert state["voice_tts_chunk_pause_ms"] == 56
assert state["augmentation_policy"] == "fallback_only"
assert state["augmented_provider"] == "wikipedia"
PY

set_mode_json="$(python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-mode --value online)"
set_mode_noop_json="$(python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-mode --value online)"
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-conversation --value on >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-memory --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-evidence --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-voice --value off >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-voice-tts-pause --value 112 >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmentation --value direct_allowed >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmented-provider --value openai >/dev/null
env_out="$(python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" print-env)"

python3 - <<'PY' "${STATE_FILE}" "${set_mode_json}" "${set_mode_noop_json}"
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1])
set_mode_payload = json.loads(sys.argv[2])
set_mode_noop_payload = json.loads(sys.argv[3])
state = json.loads(state_path.read_text(encoding="utf-8"))

assert state["mode"] == "online"
assert state["conversation"] == "on"
assert state["memory"] == "off"
assert state["evidence"] == "off"
assert state["voice"] == "off"
assert state["voice_tts_chunk_pause_ms"] == 112
assert state["augmentation_policy"] == "direct_allowed"
assert state["augmented_provider"] == "openai"
assert state["status"] == "ready"
assert state["last_updated"]

assert set_mode_payload["ok"] is True
assert set_mode_payload["field"] == "mode"
assert set_mode_payload["value"] == "online"
assert set_mode_payload["changed"] is True

assert set_mode_noop_payload["ok"] is True
assert set_mode_noop_payload["field"] == "mode"
assert set_mode_noop_payload["value"] == "online"
assert set_mode_noop_payload["changed"] is False
PY

printf '%s\n' "${env_out}" | grep -qx 'LUCY_ROUTE_CONTROL_MODE=FORCED_ONLINE' || die "print-env did not expose forced online route mode"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_CONVERSATION_MODE_FORCE=1' || die "print-env did not expose conversation on"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_SESSION_MEMORY=0' || die "print-env did not expose memory off"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_EVIDENCE_ENABLED=0' || die "print-env did not expose evidence off"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_VOICE_ENABLED=0' || die "print-env did not expose voice off"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_VOICE_TTS_CHUNK_PAUSE_MS=112' || die "print-env did not expose voice tts pause"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_AUGMENTATION_POLICY=direct_allowed' || die "print-env did not expose augmentation policy"
printf '%s\n' "${env_out}" | grep -qx 'LUCY_AUGMENTED_PROVIDER=openai' || die "print-env did not expose augmented provider"

if python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-memory --value maybe >/dev/null 2>"${TMPD}/invalid.err"; then
  die "invalid toggle value should fail"
fi
grep -qi 'invalid choice' "${TMPD}/invalid.err" || die "invalid toggle error should mention invalid choice"

if python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmented-provider --value invalid >/dev/null 2>"${TMPD}/invalid_provider.err"; then
  die "invalid augmented provider value should fail"
fi
grep -qi 'invalid choice' "${TMPD}/invalid_provider.err" || die "invalid provider error should mention invalid choice"

LUCY_RUNTIME_STATE_FILE="${STATE_FILE_ENV}" python3 "${CONTROL_TOOL}" ensure-state >/dev/null
python3 - <<'PY' "${STATE_FILE_ENV}"
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert state["profile"] == "opt-experimental-v7-dev"
assert state["mode"] == "auto"
PY

LUCY_RUNTIME_NAMESPACE_ROOT="${NAMESPACE_ROOT}" python3 "${CONTROL_TOOL}" ensure-state >/dev/null
python3 - <<'PY' "${NAMESPACE_ROOT}"
import json
import sys
from pathlib import Path

state_path = Path(sys.argv[1]) / "state" / "current_state.json"
state = json.loads(state_path.read_text(encoding="utf-8"))
assert state_path.exists()
assert state["profile"] == "opt-experimental-v7-dev"
assert state["mode"] == "auto"
PY

mkdir -p "${NAMESPACE_ROOT}/state"
cat > "${LAST_REQUEST_RESULT_FILE}" <<'EOF'
{
  "outcome": {
    "augmented_provider": "openai",
    "augmented_provider_used": "openai",
    "augmented_provider_status": "external_unavailable",
    "augmented_provider_error_reason": "openai_network_error"
  }
}
EOF
self_check_json="$(LUCY_RUNTIME_NAMESPACE_ROOT="${NAMESPACE_ROOT}" python3 "${CONTROL_TOOL}" self-check)"
python3 - <<'PY' "${self_check_json}" "${NAMESPACE_ROOT}"
import json
import sys
from pathlib import Path

payload = json.loads(sys.argv[1])
namespace_root = Path(sys.argv[2])

assert payload["status"] == "warning"
assert payload["resolution_source"] == "env_namespace_root"
assert Path(payload["runtime_namespace_root"]) == namespace_root
assert payload["control_state"]["augmented_provider"] == "wikipedia"
assert payload["control_state"]["voice_tts_chunk_pause_ms"] == 56
assert payload["augmented_availability"]["provider"] == "openai"
assert payload["augmented_availability"]["status"] == "external_unavailable"
assert payload["augmented_availability"]["error_reason"] == "openai_network_error"
assert "augmented_provider_external_unavailable" in payload["warning_codes"]
PY

LUCY_RUNTIME_STATE_FILE="${STATE_FILE_ENV}" python3 "${CONTROL_TOOL}" --state-file "${CLI_STATE_FILE}" ensure-state >/dev/null
python3 - <<'PY' "${STATE_FILE_ENV}" "${CLI_STATE_FILE}"
import json
import sys
from pathlib import Path

env_state = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
cli_state = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
assert env_state["mode"] == "auto"
assert cli_state["mode"] == "auto"
assert Path(sys.argv[1]) != Path(sys.argv[2])
PY

ok "runtime_control persists bounded state transitions and exports launcher env values"
echo "PASS: test_runtime_control_endpoints"
