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
{
  echo "UTC=2026-03-28T22:00:00Z"
  echo "MODE=LOCAL"
  echo "ROUTE_REASON=mock_contract"
  echo "SESSION_ID=contract-session"
  echo "QUERY=${q}"
} > "${LUCY_ROOT}/state/last_route.env"

case "${q}" in
  "repeat same")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-28T22:00:01Z
MODE=LOCAL
ROUTE_REASON=mock_contract
SESSION_ID=contract-session
EVIDENCE_CREATED=false
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=LOCAL
FINAL_MODE=LOCAL
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=
MANIFEST_SELECTED_ROUTE=LOCAL
MANIFEST_AUTHORITY_BASIS=conceptual_local_prompt
WINNING_SIGNAL=legacy_policy
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "What is OpenAI doing now?")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-28T22:00:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_contract
SESSION_ID=contract-session
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
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "Compare Microsoft historically and what it is doing now.")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-28T22:00:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_contract
SESSION_ID=contract-session
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
AUGMENTED_PROVIDER=wikipedia
AUGMENTED_PROVIDER_USED=wikipedia
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "What did OpenAI build?")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-28T22:00:01Z
MODE=LOCAL
ROUTE_REASON=mock_contract
SESSION_ID=contract-session
EVIDENCE_CREATED=false
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=LOCAL
FINAL_MODE=LOCAL
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=
MANIFEST_SELECTED_ROUTE=LOCAL
MANIFEST_AUTHORITY_BASIS=conceptual_local_prompt
WINNING_SIGNAL=legacy_policy
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  *)
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-28T22:00:01Z
MODE=CLARIFY
ROUTE_REASON=mock_contract
SESSION_ID=contract-session
EVIDENCE_CREATED=false
OUTCOME_CODE=clarification_requested
ACTION_HINT=ask one narrower question
RC=0
QUERY=${q}
REQUESTED_MODE=CLARIFY
FINAL_MODE=CLARIFY
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=
MANIFEST_SELECTED_ROUTE=CLARIFY
MANIFEST_AUTHORITY_BASIS=underspecified_prompt
WINNING_SIGNAL=clarify_required
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-fallback_only}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
esac
printf 'BEGIN_VALIDATED\nmock: %s\nEND_VALIDATED\n' "${q}"
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

repeat_one="$(run_submit "repeat same")"
repeat_two="$(run_submit "repeat same")"
current_one="$(run_submit "What is OpenAI doing now?")"
mixed_one="$(run_submit "Compare Microsoft historically and what it is doing now.")"
historical_one="$(run_submit "What did OpenAI build?")"
clarify_one="$(run_submit "What about him?")"

python3 - <<'PY' "${repeat_one}" "${repeat_two}" "${current_one}" "${mixed_one}" "${historical_one}" "${clarify_one}"
import json
import sys

repeat_one = json.loads(sys.argv[1])
repeat_two = json.loads(sys.argv[2])
current_one = json.loads(sys.argv[3])
mixed_one = json.loads(sys.argv[4])
historical_one = json.loads(sys.argv[5])
clarify_one = json.loads(sys.argv[6])

triplet_one = (
    repeat_one["outcome"]["answer_class"],
    repeat_one["outcome"]["provider_authorization"],
    repeat_one["outcome"]["operator_trust_label"],
)
triplet_two = (
    repeat_two["outcome"]["answer_class"],
    repeat_two["outcome"]["provider_authorization"],
    repeat_two["outcome"]["operator_trust_label"],
)
assert triplet_one == ("local_answer", "not_applicable", "local")
assert triplet_two == triplet_one

assert current_one["outcome"]["answer_class"] == "augmented_unverified_fallback"
assert current_one["outcome"]["operator_trust_label"] == "unverified"
assert current_one["outcome"]["operator_answer_path"] == "Evidence insufficient -> OPENAI fallback"
current_contract = current_one["outcome"]["augmented_answer_contract"]
assert current_contract["answer"]
assert current_contract["verification_status"] == "unverified"
assert current_contract["estimated_confidence_pct"] == 34
assert current_contract["estimated_confidence_band"] == "Low"
assert current_contract["estimated_confidence_label"] == "34% (Low, estimated)"
assert current_contract["source_basis"] == ["augmented_provider_openai", "local_model_background"]
assert current_contract["provider_status"] == "available"

assert mixed_one["outcome"]["answer_class"] == "augmented_unverified_fallback"
assert mixed_one["outcome"]["operator_trust_label"] == "unverified"
assert mixed_one["outcome"]["operator_answer_path"] == "Evidence insufficient -> WIKIPEDIA fallback"
mixed_contract = mixed_one["outcome"]["augmented_answer_contract"]
assert mixed_contract["answer"]
assert mixed_contract["verification_status"] == "unverified"
assert mixed_contract["estimated_confidence_pct"] == 44
assert mixed_contract["estimated_confidence_band"] == "Moderate"
assert mixed_contract["estimated_confidence_label"] == "44% (Moderate, estimated)"
assert mixed_contract["source_basis"] == ["augmented_provider_wikipedia", "local_model_background"]
assert mixed_contract["provider_status"] == "available"

assert historical_one["outcome"]["answer_class"] == "local_answer"
assert historical_one["outcome"]["operator_trust_label"] == "local"
assert historical_one["outcome"]["augmented_answer_contract"] == {}

assert clarify_one["outcome"]["answer_class"] == "clarification_required"
assert clarify_one["outcome"]["provider_authorization"] == "not_applicable"
assert clarify_one["outcome"]["operator_trust_label"] == "clarify-first"
assert clarify_one["outcome"]["operator_answer_path"] == "Clarification requested"
PY

ok "runtime_request answer contract stays stable for repeat inputs and separates current, mixed, historical, and clarify classes"
echo "PASS: test_runtime_request_answer_contract_invariants"
