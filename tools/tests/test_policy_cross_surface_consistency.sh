#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier"
[[ -f "${MAPPER}" ]] || die "missing mapper"

map_force_mode(){
  local surface="$1" prompt="$2" plan out
  plan="$("${CLASSIFIER}" "${prompt}")"
  out="$(python3 "${MAPPER}" --plan-json "${plan}" --question "${prompt}" --route-prefix "" --surface "${surface}" --route-control-mode "AUTO")"
  python3 - "${out}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("force_mode",""))
PY
}

check_prompt(){
  local prompt="$1" cli conv voice
  cli="$(map_force_mode cli "${prompt}")"
  conv="$(map_force_mode conversation "${prompt}")"
  voice="$(map_force_mode voice "${prompt}")"
  [[ -n "${cli}" ]] || die "empty cli route for: ${prompt}"
  [[ "${cli}" == "${conv}" ]] || die "conversation mismatch for '${prompt}': cli=${cli} conversation=${conv}"
  [[ "${cli}" == "${voice}" ]] || die "voice mismatch for '${prompt}': cli=${cli} voice=${voice}"
  ok "consistent route (${cli}) :: ${prompt}"
}

check_prompt "What is ohm's law?"
check_prompt "What are the latest world headlines?"
check_prompt "Would you suggest travelling to Iran at the moment?"
check_prompt "What is the weather tomorrow in New York City?"
check_prompt "Who are you?"

echo "PASS: test_policy_cross_surface_consistency"
