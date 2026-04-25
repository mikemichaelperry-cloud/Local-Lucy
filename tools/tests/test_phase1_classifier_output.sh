#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing executable: ${CLASSIFIER}"

json_field(){
  python3 - "$1" "$2" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
value = obj
for part in sys.argv[2].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
elif isinstance(value, list):
    print(",".join(str(x) for x in value))
else:
    print(str(value))
PY
}

run_case(){
  local label="$1"
  local prompt="$2"
  local field="$3"
  local expected="$4"
  local out got
  out="$("${CLASSIFIER}" "${prompt}")"
  got="$(json_field "${out}" "${field}")"
  [[ "${got}" == "${expected}" ]] || die "${label}: expected ${field}=${expected}, got ${got}"
  ok "${label}: ${field}=${got}"
}

run_case "identity_personal" "who is oscar" "intent_class" "identity_personal"
run_case "identity_local_route" "who is oscar" "candidate_routes" "LOCAL"
run_case "identity_legacy" "who is oscar" "intent" "IDENTITY_RELATIONSHIP"

run_case "technical_explanation" "explain ohm's law" "intent_class" "technical_explanation"
run_case "technical_local_route" "explain ohm's law" "candidate_routes" "LOCAL"

run_case "current_fact_news" "latest world news" "intent_class" "current_fact"
run_case "current_fact_news_route" "latest world news" "candidate_routes" "NEWS,EVIDENCE"
run_case "current_fact_news_legacy" "latest world news" "intent" "WEB_NEWS"
run_case "current_president_current_fact" "Who is the current President of the United States?" "intent_class" "current_fact"
run_case "current_president_route" "Who is the current President of the United States?" "candidate_routes" "EVIDENCE,NEWS"
run_case "current_president_legacy" "Who is the current President of the United States?" "intent" "WEB_FACT"
run_case "current_tensions_news" "What are the current tensions in the South China Sea?" "intent" "WEB_NEWS"
run_case "currently_ceasefire_news" "Is there currently a ceasefire in Gaza?" "intent" "WEB_NEWS"
run_case "tax_deadline_current_fact" "Has the filing deadline for US taxes changed this year?" "intent_class" "current_fact"
run_case "tax_deadline_route" "Has the filing deadline for US taxes changed this year?" "candidate_routes" "EVIDENCE,NEWS"
run_case "fx_current_fact" "What is the current USD to ILS exchange rate?" "intent_class" "current_fact"
run_case "fx_current_fact_legacy_intent" "What is the current USD to ILS exchange rate?" "intent" "WEB_FACT"
run_case "current_component_production_fact" "MJ4502 + MJ802 power darlington transistors. Are they in current production?" "intent_class" "current_fact"
run_case "current_component_production_route" "MJ4502 + MJ802 power darlington transistors. Are they in current production?" "candidate_routes" "EVIDENCE,NEWS"
run_case "current_component_production_legacy" "MJ4502 + MJ802 power darlington transistors. Are they in current production?" "intent" "WEB_FACT"
run_case "ai_policy_updates_not_forced_news" "What are the latest developments in AI policy regulation worldwide?" "intent" "WEB_FACT"
run_case "messy_rn_news" "what happening south china sea rn" "intent" "WEB_NEWS"
run_case "ambiguous_tell_me_more" "Tell me more about it." "needs_clarification" "true"
run_case "ambiguous_is_it_safe" "Is it safe?" "intent_class" "mixed"
run_case "ambiguous_how_about_now" "How about now?" "candidate_routes" "CLARIFY"
run_case "ambiguous_can_you_continue" "Can you continue?" "candidate_routes" "CLARIFY"
run_case "inflation_concept_local" "What is inflation?" "intent_class" "local_knowledge"
run_case "inflation_concept_route" "What is inflation?" "candidate_routes" "LOCAL"
run_case "latest_url_reference_intent_class" "Latest updates from https://example.com/report" "intent_class" "evidence_check"
run_case "latest_url_reference_legacy_intent" "Latest updates from https://example.com/report" "intent" "WEB_DOC"
run_case "latest_url_reference_route" "Latest updates from https://example.com/report" "candidate_routes" "EVIDENCE"
run_case "current_laptop_mixed" "Tell me what RAM is and recommend a current laptop." "intent_class" "mixed"
run_case "current_laptop_route" "Tell me what RAM is and recommend a current laptop." "candidate_routes" "EVIDENCE,NEWS"
run_case "hezbollah_ideology_local" "Explain Hezbollah ideology." "intent_class" "local_knowledge"
run_case "hezbollah_latest_news" "Latest Hezbollah news." "intent" "WEB_NEWS"
run_case "aspirin_blood_pressure_medical" "What about Aspirin for blood pressure?" "intent_class" "evidence_check"
run_case "aspirin_blood_pressure_route" "What about Aspirin for blood pressure?" "candidate_routes" "EVIDENCE"
run_case "aspirin_blood_pressure_legacy" "What about Aspirin for blood pressure?" "intent" "MEDICAL_INFO"
run_case "ibuprofen_blood_pressure_medical" "What about ibuprofen for blood pressure?" "intent_class" "evidence_check"
run_case "what_is_aspirin_medical" "What is aspirin?" "intent" "MEDICAL_INFO"

run_case "travel_advisory" "is bali safe right now" "intent_class" "evidence_check"
run_case "travel_advisory_route" "is bali safe right now" "candidate_routes" "EVIDENCE"
run_case "travel_advisory_category" "is bali safe right now" "category" "travel_advisory"
run_case "travel_info_clarify" "travel information." "intent_class" "mixed"
run_case "travel_info_clarify_flag" "travel information." "needs_clarification" "true"
run_case "travel_info_clarify_route" "travel information." "candidate_routes" "CLARIFY,EVIDENCE,LOCAL"

run_case "mixed_bali" "tell me about bali" "intent_class" "mixed"
run_case "mixed_bali_clarify" "tell me about bali" "needs_clarification" "true"

run_case "command_online" "/mode online" "intent_class" "command_control"
run_case "command_offline" "/mode offline" "intent_class" "command_control"
run_case "dismissal_conversation" "Not necessary." "intent_class" "conversational"
run_case "dismissal_route" "Not necessary." "candidate_routes" "LOCAL"
run_case "dismissal_legacy" "Not necessary." "intent" "LOCAL_CHAT"

echo "PASS: test_phase1_classifier_output"
