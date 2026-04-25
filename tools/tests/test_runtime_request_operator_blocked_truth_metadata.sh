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
mkdir -p "${MOCK_ROOT}/state"

cat > "${MOCK_ROOT}/lucy_chat.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
q="${1:-}"
mkdir -p "${LUCY_ROOT}/state"
{
  echo "UTC=2026-04-05T14:19:20Z"
  echo "MODE=EVIDENCE"
  echo "ROUTE_REASON=mock_service"
  echo "SESSION_ID="
  echo "QUERY=${q}"
  echo "QUERY_SHA256=$(printf '%s' "${q}" | sha256sum | awk '{print $1}')"
} > "${LUCY_ROOT}/state/last_route.env"

cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-04-05T14:19:20Z
MODE=EVIDENCE
ROUTE_REASON=mock_service
SESSION_ID=
EVIDENCE_CREATED=false
OUTCOME_CODE=validation_failed
ACTION_HINT=enable evidence
RC=0
QUERY=${q}
QUERY_SHA256=$(printf '%s' "${q}" | sha256sum | awk '{print $1}')
REQUESTED_MODE=EVIDENCE
FINAL_MODE=EVIDENCE
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=unknown
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=explicit_source_request
MANIFEST_AUTHORITY_BASIS=doc_source_prompt
WINNING_SIGNAL=policy_global
GOVERNOR_INTENT=WEB_FACT
AUGMENTED_PROVIDER=none
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=0
EOF
printf 'BEGIN_VALIDATED\nEvidence disabled by operator control.\nEnable evidence to allow evidence routes.\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-evidence --value off >/dev/null

payload="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "latest world news"
)"

python3 - <<'PY' "${payload}"
import json
import sys

payload = json.loads(sys.argv[1])

assert payload["status"] == "completed"
assert payload["control_state"]["evidence"] == "off"
assert payload["response_text"] == "Evidence disabled by operator control.\nEnable evidence to allow evidence routes."
assert payload["outcome"]["outcome_code"] == "validation_failed"
assert payload["outcome"]["requested_mode"] == "EVIDENCE"
assert payload["outcome"]["final_mode"] == "EVIDENCE"
assert payload["outcome"]["trust_class"] == "unknown"
assert payload["outcome"]["answer_class"] == "operator_blocked"
assert payload["outcome"]["provider_authorization"] == "not_applicable"
assert payload["outcome"]["operator_trust_label"] == "blocked"
assert payload["outcome"]["operator_answer_path"] == "Evidence route blocked"
assert payload["outcome"]["operator_note"] == "Evidence is disabled by operator control."
assert payload["outcome"]["action_hint"] == "enable evidence"
assert payload["route"]["selected_route"] == "EVIDENCE"
assert payload["route"]["final_mode"] == "EVIDENCE"
assert payload["route"]["authority_basis"] == "doc_source_prompt"
assert payload["route"]["winning_signal"] == "policy_global"
PY

ok "runtime_request preserves operator-blocked evidence truth without mislabeling it evidence-backed"
echo "PASS: test_runtime_request_operator_blocked_truth_metadata"
