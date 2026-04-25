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
  echo "UTC=2026-03-23T20:10:00Z"
  echo "MODE=EVIDENCE"
  echo "ROUTE_REASON=mock_service"
  echo "SESSION_ID=svc-session"
  echo "QUERY=${q}"
} > "${LUCY_ROOT}/state/last_route.env"

case "${q}" in
  "svc evidence")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=EVIDENCE
ROUTE_REASON=mock_service
SESSION_ID=svc-session
EVIDENCE_CREATED=true
OUTCOME_CODE=answered
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=EVIDENCE
FALLBACK_USED=false
FALLBACK_REASON=none
TRUST_CLASS=evidence_backed
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
    ;;
  "svc fallback")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_service
SESSION_ID=svc-session
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
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=default_light
MANIFEST_AUTHORITY_BASIS=live_current_prompt
WINNING_SIGNAL=policy_global
GOVERNOR_INTENT=WEB_FACT
AUGMENTED_PROVIDER=wikipedia
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTED_PROVIDER_SELECTION_REASON=stable factual overview
AUGMENTED_PROVIDER_SELECTION_QUERY=who was alan turing?
AUGMENTED_PROVIDER_SELECTION_RULE=background_overview
UNVERIFIED_CONTEXT_TITLE=Alan Turing
UNVERIFIED_CONTEXT_URL=https://en.wikipedia.org/wiki/Alan_Turing
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "svc grok")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_service
SESSION_ID=svc-session
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
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=default_light
MANIFEST_AUTHORITY_BASIS=live_current_prompt
WINNING_SIGNAL=policy_global
GOVERNOR_INTENT=WEB_FACT
AUGMENTED_PROVIDER=grok
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTED_PROVIDER_SELECTION_REASON=explicit provider selection
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "svc openai")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_service
SESSION_ID=svc-session
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
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=FULL
MANIFEST_EVIDENCE_MODE_REASON=default_light
MANIFEST_AUTHORITY_BASIS=live_current_prompt
WINNING_SIGNAL=policy_global
GOVERNOR_INTENT=WEB_FACT
AUGMENTED_PROVIDER=openai
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTED_PROVIDER_SELECTION_REASON=synthesis/explanation task
AUGMENTED_PROVIDER_SELECTION_QUERY=explain entropy in plain english with engineering intuition
AUGMENTED_PROVIDER_SELECTION_RULE=plain_explanation
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  "Explain entropy in plain language")
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=LOCAL
ROUTE_REASON=mock_service
SESSION_ID=svc-session
EVIDENCE_CREATED=true
OUTCOME_CODE=best_effort_recovery_answer
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=EVIDENCE
FINAL_MODE=LOCAL
FALLBACK_USED=true
FALLBACK_REASON=validated_insufficient
TRUST_CLASS=best_effort_unverified
PRIMARY_OUTCOME_CODE=validated_insufficient
PRIMARY_TRUST_CLASS=evidence_backed
RECOVERY_ATTEMPTED=true
RECOVERY_USED=true
RECOVERY_ELIGIBLE=true
RECOVERY_LANE=local_best_effort
MANIFEST_SELECTED_ROUTE=EVIDENCE
MANIFEST_EVIDENCE_MODE=LIGHT
MANIFEST_EVIDENCE_MODE_REASON=default_light
MANIFEST_AUTHORITY_BASIS=live_current_prompt
WINNING_SIGNAL=policy_global
GOVERNOR_INTENT=WEB_FACT
AUGMENTED_PROVIDER=none
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=0
EOF
    ;;
  *)
    cat > "${LUCY_ROOT}/state/last_outcome.env" <<EOF
UTC=2026-03-23T20:10:01Z
MODE=AUGMENTED
ROUTE_REASON=mock_service
SESSION_ID=svc-session
EVIDENCE_CREATED=false
OUTCOME_CODE=augmented_answer
ACTION_HINT=
RC=0
QUERY=${q}
REQUESTED_MODE=AUGMENTED
FINAL_MODE=AUGMENTED
FALLBACK_USED=false
FALLBACK_REASON=direct_request
TRUST_CLASS=unverified
MANIFEST_SELECTED_ROUTE=LOCAL
MANIFEST_EVIDENCE_MODE=
MANIFEST_AUTHORITY_BASIS=conceptual_local_prompt
WINNING_SIGNAL=conceptual_local
GOVERNOR_INTENT=LOCAL_KNOWLEDGE
AUGMENTED_PROVIDER=wikipedia
AUGMENTED_PROVIDER_STATUS=available
AUGMENTED_PROVIDER_ERROR_REASON=none
AUGMENTED_PROVIDER_SELECTION_REASON=explicit provider selection
AUGMENTATION_POLICY=${LUCY_AUGMENTATION_POLICY:-disabled}
AUGMENTED_DIRECT_REQUEST=1
EOF
    ;;
esac
printf 'BEGIN_VALIDATED\nmock: %s\nEND_VALIDATED\n' "${q}"
SH
chmod +x "${MOCK_ROOT}/lucy_chat.sh"

python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" ensure-state >/dev/null
python3 "${CONTROL_TOOL}" --state-file "${STATE_FILE}" set-augmentation --value direct_allowed >/dev/null

payload_evidence="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "svc evidence"
)"

payload_fallback="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "svc fallback"
)"

payload_direct="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "svc direct"
)"

payload_grok="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "svc grok"
)"

payload_openai="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "svc openai"
)"

payload_best_effort="$(
  LUCY_RUNTIME_AUTHORITY_ROOT="${MOCK_ROOT}" \
  LUCY_RUNTIME_STATE_FILE="${STATE_FILE}" \
  LUCY_RUNTIME_REQUEST_RESULT_FILE="${RESULT_FILE}" \
  LUCY_RUNTIME_REQUEST_HISTORY_FILE="${HISTORY_FILE}" \
  python3 "${REQUEST_TOOL}" submit --text "Explain entropy in plain language"
)"

python3 - <<'PY' "${payload_evidence}" "${payload_fallback}" "${payload_direct}" "${payload_grok}" "${payload_openai}" "${payload_best_effort}"
import json, sys
e = json.loads(sys.argv[1])
f = json.loads(sys.argv[2])
d = json.loads(sys.argv[3])
g = json.loads(sys.argv[4])
o = json.loads(sys.argv[5])
b = json.loads(sys.argv[6])

assert e["control_state"]["augmentation_policy"] == "direct_allowed"
assert e["outcome"]["outcome_code"] == "answered"
assert e["outcome"]["requested_mode"] == "EVIDENCE"
assert e["outcome"]["final_mode"] == "EVIDENCE"
assert e["outcome"]["fallback_used"] == "false"
assert e["outcome"]["trust_class"] == "evidence_backed"
assert e["outcome"]["answer_class"] == "evidence_backed_answer"
assert e["outcome"]["provider_authorization"] == "not_applicable"
assert e["outcome"]["operator_trust_label"] == "evidence-backed"
assert e["outcome"]["operator_answer_path"] == "Evidence-backed answer"
assert e["outcome"]["evidence_mode"] == "FULL"
assert e["outcome"]["evidence_mode_reason"] == "explicit_source_request"
assert e["outcome"]["evidence_mode_selection"] == "explicit-user-triggered"
assert e["outcome"]["augmented_provider"] == "none"
assert e["route"]["selected_route"] == "EVIDENCE"
assert e["route"]["intent_class"] == "WEB_FACT"
assert e["route"]["evidence_mode"] == "FULL"
assert e["route"]["evidence_mode_reason"] == "explicit_source_request"
assert e["route"]["evidence_mode_selection"] == "explicit-user-triggered"
assert e["route"]["authority_basis"] == "doc_source_prompt"
assert e["route"]["winning_signal"] == "policy_global"

assert f["outcome"]["outcome_code"] == "augmented_fallback_answer"
assert f["outcome"]["requested_mode"] == "EVIDENCE"
assert f["outcome"]["final_mode"] == "AUGMENTED"
assert f["outcome"]["fallback_used"] == "true"
assert f["outcome"]["fallback_reason"] == "validated_insufficient"
assert f["outcome"]["trust_class"] == "unverified"
assert f["outcome"]["answer_class"] == "augmented_unverified_fallback"
assert f["outcome"]["provider_authorization"] == "authorized_by_runtime_state"
assert f["outcome"]["operator_trust_label"] == "unverified"
assert f["outcome"]["operator_answer_path"] == "Evidence insufficient -> WIKIPEDIA fallback"
assert f["outcome"]["evidence_mode"] == "FULL"
assert f["outcome"]["evidence_mode_reason"] == "default_light"
assert f["outcome"]["evidence_mode_selection"] == "default-light"
assert f["outcome"]["augmented_provider"] == "wikipedia"
assert f["outcome"]["augmented_provider_selection_reason"] == "stable factual overview"
assert f["outcome"]["augmented_provider_selection_query"] == "who was alan turing?"
assert f["outcome"]["augmented_provider_selection_rule"] == "background_overview"
assert f["outcome"]["unverified_context_title"] == "Alan Turing"
assert f["outcome"]["unverified_context_url"] == "https://en.wikipedia.org/wiki/Alan_Turing"
assert f["outcome"]["augmented_answer_contract"]["answer"] == "mock: svc fallback"
assert f["outcome"]["augmented_answer_contract"]["verification_status"] == "unverified"
assert f["outcome"]["augmented_answer_contract"]["estimated_confidence_pct"] == 50
assert f["outcome"]["augmented_answer_contract"]["estimated_confidence_band"] == "Moderate"
assert f["outcome"]["augmented_answer_contract"]["estimated_confidence_label"] == "50% (Moderate, estimated)"
assert f["outcome"]["augmented_answer_contract"]["source_basis"] == ["augmented_provider_wikipedia", "local_model_background"]
assert f["outcome"]["augmented_answer_contract"]["provider_status"] == "available"
assert f["outcome"]["augmented_answer_contract"]["consistency_signal"] == "first_seen"
assert f["outcome"]["augmented_answer_contract"]["notes"] == "No allowlisted evidence confirmed this directly."
assert f["route"]["selected_route"] == "EVIDENCE"
assert f["route"]["intent_class"] == "WEB_FACT"
assert f["route"]["evidence_mode_reason"] == "default_light"
assert f["route"]["evidence_mode_selection"] == "default-light"

assert d["outcome"]["outcome_code"] == "augmented_answer"
assert d["outcome"]["requested_mode"] == "AUGMENTED"
assert d["outcome"]["final_mode"] == "AUGMENTED"
assert d["outcome"]["answer_class"] == "augmented_unverified_answer"
assert d["outcome"]["provider_authorization"] == "explicit_provider_selection"
assert d["outcome"]["operator_trust_label"] == "unverified"
assert d["outcome"]["fallback_used"] == "false"
assert d["outcome"]["fallback_reason"] == "direct_request"
assert d["outcome"]["trust_class"] == "unverified"
assert d["outcome"]["augmented_direct_request"] == "1"
assert d["outcome"]["augmented_provider"] == "wikipedia"
assert d["outcome"]["augmented_provider_selection_reason"] == "explicit provider selection"
assert d["outcome"]["augmented_answer_contract"]["answer"] == "mock: svc direct"
assert d["outcome"]["augmented_answer_contract"]["verification_status"] == "unverified"
assert d["outcome"]["augmented_answer_contract"]["estimated_confidence_pct"] == 44
assert d["outcome"]["augmented_answer_contract"]["estimated_confidence_band"] == "Moderate"
assert d["outcome"]["augmented_answer_contract"]["estimated_confidence_label"] == "44% (Moderate, estimated)"
assert d["outcome"]["augmented_answer_contract"]["source_basis"] == ["augmented_provider_wikipedia", "local_model_background"]
assert d["outcome"]["augmented_answer_contract"]["provider_status"] == "available"
assert d["outcome"]["augmented_answer_contract"]["consistency_signal"] == "first_seen"
assert d["route"]["selected_route"] == "LOCAL"
assert d["route"]["intent_class"] == "LOCAL_KNOWLEDGE"

assert g["outcome"]["outcome_code"] == "augmented_fallback_answer"
assert g["outcome"]["trust_class"] == "unverified"
assert g["outcome"]["augmented_provider"] == "grok"
assert g["outcome"]["provider_authorization"] == "explicit_provider_selection"
assert g["outcome"]["augmented_provider_selection_reason"] == "explicit provider selection"
assert g["outcome"]["augmented_answer_contract"]["answer"] == "mock: svc grok"
assert g["outcome"]["augmented_answer_contract"]["verification_status"] == "unverified"
assert g["outcome"]["augmented_answer_contract"]["estimated_confidence_pct"] == 34
assert g["outcome"]["augmented_answer_contract"]["estimated_confidence_band"] == "Low"
assert g["outcome"]["augmented_answer_contract"]["estimated_confidence_label"] == "34% (Low, estimated)"
assert g["outcome"]["augmented_answer_contract"]["source_basis"] == ["augmented_provider_grok", "local_model_background"]
assert g["outcome"]["augmented_answer_contract"]["provider_status"] == "available"
assert g["outcome"]["augmented_answer_contract"]["consistency_signal"] == "first_seen"
assert g["route"]["selected_route"] == "EVIDENCE"

assert o["outcome"]["outcome_code"] == "augmented_fallback_answer"
assert o["outcome"]["trust_class"] == "unverified"
assert o["outcome"]["augmented_provider"] == "openai"
assert o["outcome"]["augmented_provider_status"] == "available"
assert o["outcome"]["augmented_provider_error_reason"] == "none"
assert o["outcome"]["provider_authorization"] == "authorized_by_runtime_state"
assert o["outcome"]["augmented_provider_selection_reason"] == "synthesis/explanation task"
assert o["outcome"]["augmented_provider_selection_query"] == "explain entropy in plain english with engineering intuition"
assert o["outcome"]["augmented_provider_selection_rule"] == "plain_explanation"
assert o["outcome"]["unverified_context_title"] == ""
assert o["outcome"]["unverified_context_url"] == ""
assert o["outcome"]["augmented_answer_contract"]["answer"] == "mock: svc openai"
assert o["outcome"]["augmented_answer_contract"]["verification_status"] == "unverified"
assert o["outcome"]["augmented_answer_contract"]["estimated_confidence_pct"] == 34
assert o["outcome"]["augmented_answer_contract"]["estimated_confidence_band"] == "Low"
assert o["outcome"]["augmented_answer_contract"]["estimated_confidence_label"] == "34% (Low, estimated)"
assert o["outcome"]["augmented_answer_contract"]["source_basis"] == ["augmented_provider_openai", "local_model_background"]
assert o["outcome"]["augmented_answer_contract"]["provider_status"] == "available"
assert o["outcome"]["augmented_answer_contract"]["consistency_signal"] == "first_seen"
assert o["route"]["selected_route"] == "EVIDENCE"

assert b["outcome"]["outcome_code"] == "best_effort_recovery_answer"
assert b["outcome"]["requested_mode"] == "EVIDENCE"
assert b["outcome"]["final_mode"] == "LOCAL"
assert b["outcome"]["fallback_used"] == "true"
assert b["outcome"]["fallback_reason"] == "validated_insufficient"
assert b["outcome"]["trust_class"] == "best_effort_unverified"
assert b["outcome"]["answer_class"] == "best_effort_recovery_answer"
assert b["outcome"]["provider_authorization"] == "not_applicable"
assert b["outcome"]["operator_trust_label"] == "best-effort"
assert b["outcome"]["operator_answer_path"] == "Evidence insufficient -> local best-effort recovery"
assert b["outcome"]["operator_note"] == "Verification was insufficient, so a local best-effort answer was shown."
assert b["outcome"]["primary_outcome_code"] == "validated_insufficient"
assert b["outcome"]["primary_trust_class"] == "evidence_backed"
assert b["outcome"]["recovery_attempted"] == "true"
assert b["outcome"]["recovery_used"] == "true"
assert b["outcome"]["recovery_eligible"] == "true"
assert b["outcome"]["recovery_lane"] == "local_best_effort"
assert b["outcome"]["augmented_answer_contract"]["answer"] == "mock: Explain entropy in plain language"
assert b["outcome"]["augmented_answer_contract"]["verification_status"] == "unverified"
assert b["outcome"]["augmented_answer_contract"]["estimated_confidence_pct"] == 23
assert b["outcome"]["augmented_answer_contract"]["estimated_confidence_band"] == "Low"
assert b["outcome"]["augmented_answer_contract"]["estimated_confidence_label"] == "23% (Low, estimated)"
assert b["outcome"]["augmented_answer_contract"]["source_basis"] == ["local_model_background"]
assert b["outcome"]["augmented_answer_contract"]["consistency_signal"] == "first_seen"
assert b["outcome"]["augmented_answer_contract"]["notes"] == "No allowlisted evidence confirmed this directly."
assert b["route"]["selected_route"] == "EVIDENCE"
PY

ok "runtime_request service payload reflects augmentation truth metadata and refreshes per scenario"
echo "PASS: test_runtime_request_augmented_truth_metadata"
