#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing executable: ${CLASSIFIER}"
[[ -f "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"

json_field(){
  python3 - "$1" "$2" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
value = obj.get(sys.argv[2])
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(str(value))
PY
}

route_case(){
  local label="$1"
  local prompt="$2"
  local expected_mode="$3"
  local expected_force="$4"
  local plan out got_mode got_force
  plan="$("${CLASSIFIER}" "${prompt}")"
  out="$(python3 "${MAPPER}" --plan-json "${plan}" --question "${prompt}" --route-prefix "" --surface "cli" --route-control-mode "AUTO")"
  got_mode="$(json_field "${out}" "route_mode")"
  got_force="$(json_field "${out}" "force_mode")"
  [[ "${got_mode}" == "${expected_mode}" ]] || die "${label}: expected route_mode=${expected_mode}, got ${got_mode}"
  [[ "${got_force}" == "${expected_force}" ]] || die "${label}: expected force_mode=${expected_force}, got ${got_force}"
  ok "${label}: route_mode=${got_mode} force_mode=${got_force}"
}

route_case "identity_local" "who is oscar" "LOCAL" "LOCAL"
route_case "technical_local" "explain ohm's law" "LOCAL" "LOCAL"
route_case "latest_news" "latest world news" "NEWS" "NEWS"
route_case "bali_safe" "is bali safe right now" "EVIDENCE" "EVIDENCE"
route_case "bali_mixed" "tell me about bali" "CLARIFY" "CLARIFY"

echo "PASS: test_phase1_routing_output"

