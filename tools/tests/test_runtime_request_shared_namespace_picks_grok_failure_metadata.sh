#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
REQUEST_TOOL="${ROOT}/tools/runtime_request.py"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${REQUEST_TOOL}" ]] || die "missing request tool: ${REQUEST_TOOL}"
[[ -f "${CONTROL_TOOL}" ]] || die "missing control tool: ${CONTROL_TOOL}"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
STATE_FILE="${TMPD}/current_state.json"
RESULT_FILE="${TMPD}/last_request_result.json"
HISTORY_FILE="${TMPD}/request_history.jsonl"
MOCK_ROOT="${TMPD}/mock_root"
NAMESPACE="ns-live-smoke"
mkdir -p "${MOCK_ROOT}/state/namespaces/${NAMESPACE}"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
q="${1:-}"
ns="${LUCY_SHARED_STATE_NAMESPACE:-}"
state_dir="${LUCY_ROOT}/state"
if [[ -n "${ns}" ]]; then
  state_dir="${state_dir}/namespaces/${ns}"
fi
mkdir -p "${state_dir}"
cat > "${state_dir}/last_route.env" <<EOF
UTC=2026-03-24T17:10:00Z
MODE=LOCAL
ROUTE_REASON=mock_route
SESSION_ID=
QUERY=${q}
EOF
cat > "${state_dir}/last_outcome.env" <<EOF
UTC=2026-03-24T17:10:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_route
SESSION_ID=
EVIDENCE_CREATED=false
OUTCOME_CODE=execution_error
ACTION_HINT=Grok provider is selected but missing configuration.
RC=0
QUERY=${q}
REQUESTED_MODE=AUGMENTED
FINAL_MODE=AUGMENTED
FALLBACK_USED=false
FALLBACK_REASON=direct_grok_provider_unavailable
TRUST_CLASS=unverified
AUGMENTED_PROVIDER=grok
AUGMENTATION_POLICY=direct_allowed
AUGMENTED_DIRECT_REQUEST=true
UNVERIFIED_CONTEXT_USED=false
UNVERIFIED_CONTEXT_CLASS=none
EOF
printf 'BEGIN_VALIDATED\nGrok provider is selected but missing configuration.\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmentation --value direct_allowed >/dev/null

if LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_SHARED_STATE_NAMESPACE="${NAMESPACE}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "augmented: namespace grok check" >/dev/null; then
  die "execution_error outcome should return failed status"
fi

python3 - <<'PY' "${RESULT_FILE}"
import json
import sys
from pathlib import Path

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert payload["status"] == "failed"
assert payload["error"] == "Grok provider is selected but missing configuration."
assert payload["outcome"]["outcome_code"] == "execution_error"
assert payload["outcome"]["augmented_provider"] == "grok"
assert payload["outcome"]["requested_mode"] == "AUGMENTED"
assert payload["outcome"]["final_mode"] == "AUGMENTED"
assert payload["outcome"]["trust_class"] == "unverified"
PY

ok "runtime_request picks fresh namespaced outcome and preserves grok-specific failure metadata"
echo "PASS: test_runtime_request_shared_namespace_picks_grok_failure_metadata"
