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
cat > "${LUCY_ROOT}/state/last_route.env" <<EOF
UTC=2026-03-23T21:00:00Z
MODE=EVIDENCE
ROUTE_REASON=mock_additive
SESSION_ID=compat-session
QUERY=${q}
EOF
cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T21:00:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_additive
SESSION_ID=compat-session
EVIDENCE_CREATED=true
OUTCOME_CODE=augmented_fallback_answer
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=AUGMENTED
FALLBACK_USED=true
FALLBACK_REASON=validated_insufficient
TRUST_CLASS=unverified
MANIFEST_EVIDENCE_MODE=LIGHT
MANIFEST_EVIDENCE_MODE_REASON=default_light
AUGMENTATION_POLICY=direct_allowed
AUGMENTED_DIRECT_REQUEST=0
EOF
printf 'BEGIN_VALIDATED\ncompat reply\nEND_VALIDATED\n'
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmentation --value direct_allowed >/dev/null

payload="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "compat test"
)"

python3 - <<'PY' "${payload}"
import json
import sys

payload = json.loads(sys.argv[1])

# Legacy required fields remain available.
assert payload["status"] == "completed"
assert payload["accepted"] is True
assert payload["response_text"] == "compat reply"
assert payload["route"]["mode"] == "EVIDENCE"
assert payload["outcome"]["outcome_code"] == "augmented_fallback_answer"

# Additive fields are present.
assert payload["outcome"]["requested_mode"] == "EVIDENCE"
assert payload["outcome"]["final_mode"] == "AUGMENTED"
assert payload["outcome"]["fallback_used"] == "true"
assert payload["outcome"]["trust_class"] == "unverified"
assert payload["outcome"]["evidence_mode"] == "LIGHT"
assert payload["outcome"]["evidence_mode_reason"] == "default_light"
assert payload["outcome"]["evidence_mode_selection"] == "default-light"
assert payload["control_state"]["augmentation_policy"] == "direct_allowed"

# Simulated downstream legacy consumer: reads only old keys, ignores extras.
def legacy_consumer(obj):
    return {
        "status": obj["status"],
        "route_mode": obj["route"]["mode"],
        "outcome_code": obj["outcome"]["outcome_code"],
        "response_text": obj["response_text"],
    }

legacy = legacy_consumer(payload)
assert legacy == {
    "status": "completed",
    "route_mode": "EVIDENCE",
    "outcome_code": "augmented_fallback_answer",
    "response_text": "compat reply",
}
PY

ok "runtime_request payload stays backward-compatible for legacy consumers while allowing additive fields"
echo "PASS: test_runtime_request_schema_additive_compat"
