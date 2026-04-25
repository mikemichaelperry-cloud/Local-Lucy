#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"
[[ -x "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"

classify_query(){
  local query="$1"
  LUCY_AUGMENTATION_POLICY=direct_allowed python3 "${CLASSIFIER}" "${query}"
}

map_query(){
  local query="$1" plan
  plan="$(classify_query "${query}")"
  LUCY_AUGMENTATION_POLICY=direct_allowed python3 "${MAPPER}" --plan-json "${plan}" --question "${query}"
}

read_json_field(){
  local json="$1" field="$2"
  python3 - "${json}" "${field}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
value = payload
for part in sys.argv[2].split("."):
    if not isinstance(value, dict):
        value = ""
        break
    value = value.get(part, "")
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(str(value))
PY
}

technical_query="What would you consider the optimum voltage for an 807 tube amplifier to have on the 807 plate? Answer my question, in class A. Why not?"
technical_plan="$(classify_query "${technical_query}")"
technical_mapped="$(map_query "${technical_query}")"

[[ "$(read_json_field "${technical_plan}" "intent_class")" == "technical_explanation" ]] || die "niche technical query should classify as technical_explanation"
[[ "$(read_json_field "${technical_mapped}" "route_mode")" == "AUGMENTED" ]] || die "niche technical query should route to AUGMENTED: ${technical_mapped}"
[[ "$(read_json_field "${technical_mapped}" "policy_actual_route")" == "augmented" ]] || die "niche technical query policy route should be augmented: ${technical_mapped}"
[[ "$(read_json_field "${technical_mapped}" "manifest_selected_route")" == "AUGMENTED" ]] || die "niche technical query manifest route should be AUGMENTED: ${technical_mapped}"
[[ -z "$(read_json_field "${technical_mapped}" "execution_contract.local_response_id")" ]] || die "niche technical query should not take a canned local response path: ${technical_mapped}"
ok "niche technical operating-point query prefers AUGMENTED"

for related_query in \
  "What screen voltage is reasonable for an 807 in class A?" \
  "What bias would you use for an 807 at 400V plate in class A?" \
  "What load impedance would you choose for a single-ended 807 in class A?" \
  "How would you choose the operating point for an 807 output stage?"; do
  related_mapped="$(map_query "${related_query}")"
  [[ "$(read_json_field "${related_mapped}" "route_mode")" == "AUGMENTED" ]] || die "related niche technical query should route to AUGMENTED: ${related_query} :: ${related_mapped}"
  [[ -z "$(read_json_field "${related_mapped}" "execution_contract.local_response_id")" ]] || die "related niche technical query should not take a canned local response path: ${related_query} :: ${related_mapped}"
done
ok "related niche technical operating-point queries prefer AUGMENTED"

for broader_query in \
  "What plate dissipation does an 807 have?" \
  "How would you choose resistor values for a transistor bias network?" \
  "How would you choose compensation for a transistor amplifier?"; do
  broader_mapped="$(map_query "${broader_query}")"
  [[ "$(read_json_field "${broader_mapped}" "route_mode")" == "AUGMENTED" ]] || die "broader technical query should route to AUGMENTED: ${broader_query} :: ${broader_mapped}"
  [[ -z "$(read_json_field "${broader_mapped}" "execution_contract.local_response_id")" ]] || die "broader technical query should not take a canned local response path: ${broader_query} :: ${broader_mapped}"
done
ok "broader technical queries without proven local handlers prefer AUGMENTED"

tube_capability_query="Would you consider a pair of 809 tubes run in class AB2 Audio capable of producing 100 watts RMS?"
tube_capability_mapped="$(map_query "${tube_capability_query}")"
[[ "$(read_json_field "${tube_capability_mapped}" "route_mode")" == "AUGMENTED" ]] || die "conditional tube capability query should route to AUGMENTED: ${tube_capability_mapped}"
[[ "$(read_json_field "${tube_capability_mapped}" "policy_actual_route")" == "augmented" ]] || die "conditional tube capability policy route should be augmented: ${tube_capability_mapped}"
[[ -z "$(read_json_field "${tube_capability_mapped}" "execution_contract.local_response_id")" ]] || die "conditional tube capability query should not take a canned local response path: ${tube_capability_mapped}"
ok "conditional tube capability query prefers AUGMENTED"

identity_query="What about the 807 power tube?"
identity_mapped="$(map_query "${identity_query}")"
[[ "$(read_json_field "${identity_mapped}" "route_mode")" == "LOCAL" ]] || die "simple 807 identity query should stay LOCAL: ${identity_mapped}"
[[ "$(read_json_field "${identity_mapped}" "execution_contract.local_response_id")" == "tube_807_identity" ]] || die "simple 807 identity query should keep deterministic local identity response: ${identity_mapped}"
ok "simple 807 identity query stays LOCAL"

ohms_query="Explain Ohm's law."
ohms_mapped="$(map_query "${ohms_query}")"
[[ "$(read_json_field "${ohms_mapped}" "route_mode")" == "LOCAL" ]] || die "deterministic technical local query should stay LOCAL: ${ohms_mapped}"
[[ "$(read_json_field "${ohms_mapped}" "execution_contract.local_response_id")" == "technical_ohms_law" ]] || die "deterministic technical local query should keep local response directive: ${ohms_mapped}"
ok "deterministic technical local query stays LOCAL"

part_query="what is 74HC14?"
part_mapped="$(map_query "${part_query}")"
[[ "$(read_json_field "${part_mapped}" "route_mode")" == "LOCAL" ]] || die "timeless part lookup should stay LOCAL: ${part_mapped}"
ok "timeless part lookup stays LOCAL"

food_query="How do I cook mashed potatoes?"
food_mapped="$(map_query "${food_query}")"
[[ "$(read_json_field "${food_mapped}" "route_mode")" == "LOCAL" ]] || die "everyday local knowledge should stay LOCAL: ${food_mapped}"
ok "everyday local knowledge stays LOCAL"

echo "PASS: test_niche_technical_queries_prefer_augmented"
