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

map_route(){
  local query="$1" plan
  plan="$(python3 "${CLASSIFIER}" "${query}")"
  python3 "${MAPPER}" --plan-json "${plan}" --question "${query}"
}

read_json_field(){
  local json="$1" field="$2"
  python3 - "${json}" "${field}" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
print((payload.get(sys.argv[2]) or "").strip())
PY
}

assert_evidence_route(){
  local label="$1" query="$2" mapped route
  mapped="$(map_route "${query}")"
  route="$(read_json_field "${mapped}" "route_mode")"
  [[ "${route}" == "EVIDENCE" ]] || die "${label} expected EVIDENCE route, got ${route}: ${mapped}"
  ok "${label} prefers EVIDENCE on the routed shared backend path"
}

assert_evidence_route "compound policy query" \
  "Tell me, with evidence, what the most significant developments in global climate policy and AI safety have been in the past week; cite at least two authoritative news sources, describe how those developments interact, and explain the implications for technology regulation going forward."

assert_evidence_route "single-domain AI policy query" \
  "What are the latest AI safety regulatory developments this week?"

assert_evidence_route "single-domain climate policy query" \
  "What are the most important global climate policy developments this week?"

assert_evidence_route "over-broad cross-domain policy query" \
  "Summarize all major global policy developments across climate, AI, and financial regulation this week, explain how they interact, and predict the regulatory direction."

echo "PASS: test_policy_global_route_prefers_evidence"
