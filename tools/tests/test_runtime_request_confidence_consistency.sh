#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
REQUEST_TOOL="${ROOT}/tools/runtime_request.py"
CONTROL_TOOL="${ROOT}/tools/runtime_control.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

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
counter_file="${LUCY_ROOT}/state/repeat_counter.txt"

{
  echo "UTC=2026-04-05T19:15:00Z"
  echo "MODE=AUGMENTED"
  echo "ROUTE_REASON=mock_consistency"
  echo "SESSION_ID=consistency-session"
  echo "QUERY=${q}"
} > "${LUCY_ROOT}/state/last_route.env"

cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-04-05T19:15:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_consistency
SESSION_ID=consistency-session
EVIDENCE_CREATED=false
OUTCOME_CODE=augmented_fallback_answer
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=AUGMENTED
FALLBACK_USED=true
FALLBACK_REASON=validated_insufficient
TRUST_CLASS=unverified
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=default_light
MANIFEST_AUTHORITY_BASIS=live_current_prompt
WINNING_SIGNAL=policy_global
AUGMENTED_PROVIDER=openai
AUGMENTED_PROVIDER_USED=openai
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTED_PROVIDER_SELECTION_REASON=synthesis/explanation task
AUGMENTED_PROVIDER_SELECTION_QUERY=${q}
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF

case "${q}" in
  "stable repeat")
    printf 'BEGIN_VALIDATED\nOpenAI notes that entropy measures how many plausible arrangements remain before additional information narrows the state.\nEND_VALIDATED\n'
    ;;
  "volatile repeat")
    count=0
    if [[ -f "${counter_file}" ]]; then
      count="$(cat "${counter_file}")"
    fi
    count="$((count + 1))"
    printf '%s' "${count}" > "${counter_file}"
    if [[ "${count}" -eq 1 ]]; then
      printf 'BEGIN_VALIDATED\nOpenAI says entropy is about uncertainty and spread across plausible states.\nEND_VALIDATED\n'
    else
      printf 'BEGIN_VALIDATED\nOpenAI says entropy is mostly about heat loss and machine friction in practical engines.\nEND_VALIDATED\n'
    fi
    ;;
  *)
    printf 'BEGIN_VALIDATED\nmock: %s\nEND_VALIDATED\n' "${q}"
    ;;
esac
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null

run_submit() {
  local prompt="$1"
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "${prompt}"
}

stable_one="$(run_submit "stable repeat")"
stable_two="$(run_submit "stable repeat")"
volatile_one="$(run_submit "volatile repeat")"
volatile_two="$(run_submit "volatile repeat")"

python3 - <<'PY' "${stable_one}" "${stable_two}" "${volatile_one}" "${volatile_two}"
import json
import sys

stable_one = json.loads(sys.argv[1])["outcome"]["augmented_answer_contract"]
stable_two = json.loads(sys.argv[2])["outcome"]["augmented_answer_contract"]
volatile_one = json.loads(sys.argv[3])["outcome"]["augmented_answer_contract"]
volatile_two = json.loads(sys.argv[4])["outcome"]["augmented_answer_contract"]

assert stable_one["estimated_confidence_pct"] == 34
assert stable_two["estimated_confidence_pct"] == 38
assert stable_one["consistency_signal"] == "first_seen"
assert stable_two["consistency_signal"] == "stable_repeat"

assert volatile_one["estimated_confidence_pct"] == 34
assert volatile_two["estimated_confidence_pct"] == 28
assert volatile_one["consistency_signal"] == "first_seen"
assert volatile_two["consistency_signal"] == "divergent_repeat"
PY

ok "runtime_request confidence adds a small boost for stable repeats and lowers divergent repeats"
echo "PASS: test_runtime_request_confidence_consistency"
