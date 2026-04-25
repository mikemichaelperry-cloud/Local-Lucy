#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"
[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"

run_case() {
  local plan_json="$1"
  local route_prefix="${2:-}"
  local route_mode="${3:-AUTO}"
  local question="${4:-}"
  python3 "${MAPPER}" --plan-json "${plan_json}" --route-prefix "${route_prefix}" --route-control-mode "${route_mode}" --question "${question}"
}

run_case_with_memory() {
  local memory_context="$1"
  local plan_json="$2"
  local question="${3:-}"
  LUCY_SESSION_MEMORY_CONTEXT="${memory_context}" python3 "${MAPPER}" --plan-json "${plan_json}" --route-control-mode "AUTO" --question "${question}"
}

run_classified_case() {
  local question="$1"
  local plan_json
  plan_json="$("${CLASSIFIER}" "${question}")"
  python3 "${MAPPER}" --plan-json "${plan_json}" --route-control-mode "AUTO" --question "${question}"
}

assert_json_field() {
  local json="$1"
  local key="$2"
  local expected="$3"
  local got
  got="$(python3 - "$json" "$key" <<'PY'
import json, sys
o=json.loads(sys.argv[1])
cur=o
for part in sys.argv[2].split("."):
    if not isinstance(cur, dict) or part not in cur:
        cur=None
        break
    cur=cur.get(part)
v=cur
if isinstance(v, bool):
    print("true" if v else "false")
else:
    print("" if v is None else str(v))
PY
)"
  [[ "${got}" == "${expected}" ]] || die "expected ${key}=${expected}, got ${got}"
}

assert_manifest_compat_aliases() {
  local json="$1"
  python3 - "$json" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
manifest = payload.get("route_manifest") or {}
selected_route = str(manifest.get("selected_route") or "")
if not selected_route:
    raise SystemExit("missing route_manifest.selected_route")
expected_policy_route = selected_route.lower()
checks = {
    "force_mode": selected_route,
    "route_mode": selected_route,
    "policy_recommended_route": expected_policy_route,
    "policy_actual_route": expected_policy_route,
    "policy_base_recommended_route": expected_policy_route,
}
for field, expected in checks.items():
    got = payload.get(field)
    if got != expected:
        raise SystemExit(f"{field} drifted from manifest: {got} != {expected}")
if payload.get("needs_clarification") != manifest.get("clarify_required"):
    raise SystemExit("needs_clarification drifted from route_manifest.clarify_required")
PY
}

# Intent -> pipeline mapping
j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}')"
assert_json_field "${j}" force_mode "LOCAL"
assert_json_field "${j}" offline_action "allow"
assert_json_field "${j}" effective_plan.intent "LOCAL_KNOWLEDGE"
assert_json_field "${j}" route_decision.route_mode "LOCAL"
assert_json_field "${j}" route_manifest.selected_route "LOCAL"
assert_json_field "${j}" route_manifest.manifest_version "v1"
assert_json_field "${j}" execution_contract.route "LOCAL"
assert_json_field "${j}" execution_contract.fallback_policy "local_safe"
assert_manifest_compat_aliases "${j}"
ok "LOCAL_KNOWLEDGE maps to LOCAL"

j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' '' 'AUTO' 'What is ChatGPT?')"
assert_json_field "${j}" execution_contract.local_response_id "definition_chatgpt"
assert_json_field "${j}" execution_contract.local_response_text ""
assert_json_field "${j}" execution_contract.resolved_question ""
ok "LOCAL_KNOWLEDGE software definition gets local response directive"

j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' '' 'AUTO' 'How reliable or biased is Fox News?')"
assert_json_field "${j}" execution_contract.local_response_id "media_reliability_fox_news"
ok "media reliability local prompt gets deterministic local response directive"

j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' '' 'AUTO' 'Is water wet? Give facts, assumptions, and external dependencies.')"
assert_json_field "${j}" execution_contract.local_response_id "water_wet_structured"
ok "structured conceptual prompt gets deterministic local response directive"

j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' '' 'AUTO' 'How much output can a pair of 807s in push-pull class AB1 make at 400V?')"
assert_json_field "${j}" execution_contract.local_response_id "tube_807_pp_ab1_output_400v"
ok "807 pair output prompt gets deterministic local response directive"

j="$(run_case_with_memory $'User: My dog'\''s name is Oscar.\nAssistant: Got it. Your dog'\''s name is Oscar.' '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' 'Who is my dog?')"
assert_json_field "${j}" execution_contract.route "LOCAL"
assert_json_field "${j}" execution_contract.local_response_text "Your dog's name is Oscar."
ok "dog recall prompt gets deterministic local response text from session context"

j="$(run_case_with_memory $'User: How do I cook schnitzel?\nAssistant: Use thin cutlets and breadcrumbs.' '{"intent":"LOCAL_CHAT","needs_web":false,"min_sources":0,"output_mode":"CONVERSATION"}' 'quantities')"
assert_json_field "${j}" execution_contract.route "LOCAL"
assert_json_field "${j}" execution_contract.local_response_text "Schnitzel quantities (about 4 servings): 4 thin cutlets, 1 cup flour, 2 eggs, 1.5 cups breadcrumbs, 1 teaspoon salt, 0.5 teaspoon black pepper, and enough oil for shallow frying."
ok "schnitzel quantity follow-up gets deterministic local response text from session context"

j="$(run_case '{"intent":"PET_FOOD","needs_web":false,"min_sources":0,"output_mode":"CHAT"}')"
assert_json_field "${j}" force_mode "LOCAL"
assert_json_field "${j}" offline_action "allow"
ok "PET_FOOD maps to LOCAL"

j="$(run_case '{"intent":"WEB_FACT","needs_web":true,"min_sources":2,"output_mode":"CHAT"}')"
assert_json_field "${j}" force_mode "EVIDENCE"
assert_json_field "${j}" route_manifest.selected_route "EVIDENCE"
assert_manifest_compat_aliases "${j}"
ok "WEB_FACT maps to EVIDENCE"

j="$(run_classified_case 'Latest updates from https://example.com/report')"
assert_json_field "${j}" effective_intent "WEB_DOC"
assert_json_field "${j}" router_intent "WEB_DOC"
assert_json_field "${j}" force_mode "EVIDENCE"
assert_json_field "${j}" route_decision.winning_signal "doc_source"
assert_json_field "${j}" route_manifest.selected_route "EVIDENCE"
assert_json_field "${j}" route_manifest.authority_basis "doc_source_prompt"
assert_json_field "${j}" route_manifest.signals.url "true"
assert_manifest_compat_aliases "${j}"
ok "explicit URL prompt keeps doc-style intent through mapper"

j="$(run_classified_case 'Have you got a good recipe for chicken breasts in a tomato based source? Please provide a full recipe for 2.5kg of chicken. Make it a different recipe than the previous.')"
assert_json_field "${j}" effective_intent "LOCAL_KNOWLEDGE"
assert_json_field "${j}" router_intent "LOCAL_KNOWLEDGE"
assert_json_field "${j}" force_mode "LOCAL"
assert_json_field "${j}" route_manifest.selected_route "LOCAL"
assert_json_field "${j}" route_manifest.signals.source_request "false"
assert_manifest_compat_aliases "${j}"
ok "culinary source typo does not misroute recipe prompt into evidence"

j="$(run_classified_case 'MJ4502 + MJ802 power darlington transistors. Are they in current production?')"
assert_json_field "${j}" effective_intent "WEB_FACT"
assert_json_field "${j}" router_intent "WEB_FACT"
assert_json_field "${j}" route_decision.route_mode "EVIDENCE"
assert_json_field "${j}" route_decision.winning_signal "temporal_live"
assert_json_field "${j}" route_manifest.selected_route "EVIDENCE"
assert_json_field "${j}" route_manifest.authority_basis "policy_selected_route"
assert_manifest_compat_aliases "${j}"
ok "current component production query maps to EVIDENCE"

j="$(run_case '{"intent":"STATUS_UPDATE","needs_web":true,"min_sources":2,"output_mode":"LIGHT_EVIDENCE"}')"
assert_json_field "${j}" force_mode "NEWS"
assert_json_field "${j}" route_manifest.selected_route "NEWS"
assert_json_field "${j}" execution_contract.route "NEWS"
assert_json_field "${j}" execution_contract.requires_sources "true"
assert_manifest_compat_aliases "${j}"
ok "STATUS_UPDATE maps to NEWS"

j="$(run_classified_case 'Tell me about Bali.')"
assert_json_field "${j}" route_manifest.selected_route "CLARIFY"
assert_json_field "${j}" route_manifest.clarify_required "true"
assert_json_field "${j}" execution_contract.route "CLARIFY"
assert_manifest_compat_aliases "${j}"
ok "ambiguous prompt emits CLARIFY route manifest"

# Prefix overrides
j="$(run_case '{"intent":"WEB_FACT","needs_web":true,"min_sources":2,"output_mode":"CHAT"}' 'news')"
assert_json_field "${j}" effective_intent "WEB_NEWS"
assert_json_field "${j}" effective_needs_web "true"
assert_json_field "${j}" effective_plan_output_mode "LIGHT_EVIDENCE"
assert_json_field "${j}" effective_plan.intent "WEB_NEWS"
assert_json_field "${j}" route_decision.route_mode "NEWS"
assert_json_field "${j}" force_mode "NEWS"
ok "news prefix overrides to WEB_NEWS/NEWS"

j="$(run_case '{"intent":"WEB_FACT","needs_web":true,"min_sources":2,"output_mode":"CHAT"}' 'local')"
assert_json_field "${j}" effective_intent "LOCAL_KNOWLEDGE"
assert_json_field "${j}" effective_needs_web "false"
assert_json_field "${j}" effective_min_sources "1"
assert_json_field "${j}" effective_plan_output_mode "CHAT"
assert_json_field "${j}" force_mode "LOCAL"
ok "local prefix forces local for non-medical intent"

j="$(run_case '{"intent":"MEDICAL_INFO","needs_web":true,"min_sources":2,"output_mode":"VALIDATED"}' 'local')"
assert_json_field "${j}" effective_intent "MEDICAL_INFO"
assert_json_field "${j}" force_mode "LOCAL"
ok "local prefix preserves medical plan semantics but still forces LOCAL pipeline (legacy-compatible)"

# Offline actions
j="$(run_case '{"intent":"MEDICAL_INFO","needs_web":true,"min_sources":2,"output_mode":"VALIDATED"}' '' 'FORCED_OFFLINE')"
assert_json_field "${j}" offline_action "validated_insufficient"
assert_json_field "${j}" route_decision.offline_action "validated_insufficient"
ok "medical forced offline returns validated_insufficient action"

j="$(run_case '{"intent":"WEB_DOC","needs_web":true,"min_sources":1,"output_mode":"LIGHT_EVIDENCE"}' '' 'FORCED_OFFLINE')"
assert_json_field "${j}" offline_action "requires_evidence"
assert_json_field "${j}" execution_contract.route "EVIDENCE"
ok "web intent forced offline returns requires_evidence action"

j="$(run_case '{"intent":"LOCAL_KNOWLEDGE","needs_web":false,"min_sources":1,"output_mode":"CHAT"}' '' 'FORCED_OFFLINE')"
assert_json_field "${j}" offline_action "allow"
ok "local intent forced offline remains allowed"

echo "PASS: test_plan_to_pipeline_mapping"
