#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
GATE="${ROOT}/tools/internet/run_fetch_with_gate.sh"
MEDICAL_ALLOWLIST="${ROOT}/config/trust/generated/medical_runtime.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"
[[ -x "${GATE}" ]] || die "missing gate: ${GATE}"
[[ -s "${MEDICAL_ALLOWLIST}" ]] || die "missing allowlist: ${MEDICAL_ALLOWLIST}"

plan="$("${CLASSIFIER}" "Does tadalafil cause arrhythmia?")"
intent="$(python3 - "${plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
needs_web="$(python3 - "${plan}" <<'PY'
import json, sys
v=json.loads(sys.argv[1]).get("needs_web")
print("true" if v else "false")
PY
)"
output_mode="$(python3 - "${plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
allow_file="$(python3 - "${plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"

[[ "${intent}" == "MEDICAL_INFO" ]] || die "expected MEDICAL_INFO, got ${intent}"
[[ "${needs_web}" == "true" ]] || die "expected needs_web=true, got ${needs_web}"
[[ "${output_mode}" == "VALIDATED" ]] || die "expected output_mode=VALIDATED, got ${output_mode}"
[[ "${allow_file}" == "config/trust/generated/medical_runtime.txt" ]] || die "unexpected allow_domains_file: ${allow_file}"
ok "medical query routes to MEDICAL_INFO + VALIDATED + medical runtime allowlist"

bp_plan="$("${CLASSIFIER}" "What is the correct medication for high blood pressure?")"
bp_intent="$(python3 - "${bp_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
bp_output_mode="$(python3 - "${bp_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
bp_allow_file="$(python3 - "${bp_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${bp_intent}" == "MEDICAL_INFO" ]] || die "expected high blood pressure medication query MEDICAL_INFO, got ${bp_intent}"
[[ "${bp_output_mode}" == "VALIDATED" ]] || die "expected high blood pressure medication output_mode=VALIDATED, got ${bp_output_mode}"
[[ "${bp_allow_file}" == "config/trust/generated/medical_runtime.txt" ]] || die "unexpected high blood pressure medication allow_domains_file: ${bp_allow_file}"
ok "blood pressure medication query routes to MEDICAL_INFO + VALIDATED + medical runtime allowlist"

pet_plan="$("${CLASSIFIER}" "Is it safe to feed tuna to my dog Oscar?")"
pet_intent="$(python3 - "${pet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
pet_output_mode="$(python3 - "${pet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
pet_allow_file="$(python3 - "${pet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${pet_intent}" == "PET_FOOD" ]] || die "expected pet safety query PET_FOOD, got ${pet_intent}"
[[ "${pet_output_mode}" == "CHAT" ]] || die "expected pet safety output_mode=CHAT, got ${pet_output_mode}"
[[ -z "${pet_allow_file}" ]] || die "expected empty pet safety allow_domains_file, got ${pet_allow_file}"
ok "pet food safety query routes to PET_FOOD + CHAT knowledge path"

pet_health_plan="$("${CLASSIFIER}" "Is tinned tuna healthy for my dog Oscar?")"
pet_health_intent="$(python3 - "${pet_health_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
pet_health_output_mode="$(python3 - "${pet_health_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
pet_health_allow_file="$(python3 - "${pet_health_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${pet_health_intent}" == "PET_FOOD" ]] || die "expected pet health query PET_FOOD, got ${pet_health_intent}"
[[ "${pet_health_output_mode}" == "CHAT" ]] || die "expected pet health output_mode=CHAT, got ${pet_health_output_mode}"
[[ -z "${pet_health_allow_file}" ]] || die "expected empty pet health allow_domains_file, got ${pet_health_allow_file}"
ok "pet health wording routes to PET_FOOD + CHAT knowledge path"

pet_burger_plan="$("${CLASSIFIER}" "Can my dog eat a double cheeseburger?")"
pet_burger_intent="$(python3 - "${pet_burger_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
pet_burger_output_mode="$(python3 - "${pet_burger_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
[[ "${pet_burger_intent}" == "PET_FOOD" ]] || die "expected burger query PET_FOOD, got ${pet_burger_intent}"
[[ "${pet_burger_output_mode}" == "CHAT" ]] || die "expected burger query output_mode=CHAT, got ${pet_burger_output_mode}"
ok "general pet-food classifier routes cheeseburger prompt to PET_FOOD"

pet_olive_plan="$("${CLASSIFIER}" "Is tuna in olive oil okay for my dog Oscar?")"
pet_olive_intent="$(python3 - "${pet_olive_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
pet_olive_output_mode="$(python3 - "${pet_olive_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
[[ "${pet_olive_intent}" == "PET_FOOD" ]] || die "expected olive-oil tuna query PET_FOOD, got ${pet_olive_intent}"
[[ "${pet_olive_output_mode}" == "CHAT" ]] || die "expected olive-oil tuna query output_mode=CHAT, got ${pet_olive_output_mode}"
ok "olive-oil tuna phrasing routes to PET_FOOD knowledge path"

btc_plan="$("${CLASSIFIER}" "what is the latest BTC price?")"
btc_intent="$(python3 - "${btc_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
btc_cq="$(python3 - "${btc_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("one_clarifying_question","") or "")
PY
)"
[[ "${btc_intent}" == "WEB_FACT" ]] || die "expected BTC price query WEB_FACT, got ${btc_intent}"
[[ -z "${btc_cq}" ]] || die "did not expect BTC price clarifying question, got: ${btc_cq}"
ok "BTC price query avoids shopping-local clarification misroute"

vet_plan="$("${CLASSIFIER}" "My dog is vomiting and lethargic. What should I do?")"
vet_intent="$(python3 - "${vet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("intent",""))
PY
)"
vet_output_mode="$(python3 - "${vet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("output_mode",""))
PY
)"
vet_allow_file="$(python3 - "${vet_plan}" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("allow_domains_file","") or "")
PY
)"
[[ "${vet_intent}" == "MEDICAL_INFO" ]] || die "expected general vet query MEDICAL_INFO, got ${vet_intent}"
[[ "${vet_output_mode}" == "VALIDATED" ]] || die "expected general vet output_mode=VALIDATED, got ${vet_output_mode}"
[[ "${vet_allow_file}" == "config/trust/generated/vet_runtime.txt" ]] || die "unexpected general vet allow_domains_file: ${vet_allow_file}"
ok "general vet query routes to MEDICAL_INFO + VALIDATED + vet runtime allowlist"

if ! grep -Eq '^medical_cialis_2[[:space:]]+https://cochranelibrary.com/search\?text=tadalafil[[:space:]]+cochranelibrary\.com$' "${ROOT}/config/evidence_keymap_v1.tsv"; then
  die "expected tadalafil secondary key to map to cochranelibrary.com"
fi
ok "tadalafil secondary evidence key maps to cochranelibrary.com"

TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT
FAKEBIN="${TMPD}/bin"
mkdir -p "${FAKEBIN}"
REAL_PYTHON3="$(command -v python3)"

cat > "${FAKEBIN}/python3" <<SH
#!/usr/bin/env bash
set -euo pipefail
REAL_PYTHON3="${REAL_PYTHON3}"
if [[ "\${1:-}" == "${ROOT}/tools/internet/url_safety.py" && "\${2:-}" == "validate-url" ]]; then
  u="\${3:-}"
  case "\$u" in
    https://*) echo "OK url=\$u host=test port=443"; exit 0 ;;
    *) echo "ERR reason=https only"; exit 1 ;;
  esac
fi
exec "\$REAL_PYTHON3" "\$@"
SH
chmod +x "${FAKEBIN}/python3"

assert_gate_not_blocked() {
  local url="$1"
  local out rc
  set +e
  out="$(
    PATH="${FAKEBIN}:$PATH" \
    LUCY_FETCH_ALLOWLIST_FILTER_FILE="${MEDICAL_ALLOWLIST}" \
    "${GATE}" "${url}" 2>&1
  )"
  rc=$?
  set -e
  if printf '%s\n' "${out}" | grep -q 'FAIL_NOT_ALLOWLISTED'; then
    die "unexpected FAIL_NOT_ALLOWLISTED for ${url}: ${out}"
  fi
  if ! printf '%s\n' "${out}" | grep -q 'FETCH_META'; then
    die "missing FETCH_META for ${url}: ${out}"
  fi
  if [[ "${rc}" == "40" ]]; then
    die "unexpected allowlist block rc=40 for ${url}: ${out}"
  fi
  ok "medical filter does not block ${url}"
}

assert_gate_not_blocked "https://pubmed.ncbi.nlm.nih.gov/"
assert_gate_not_blocked "https://jamanetwork.com/"
assert_gate_not_blocked "https://cochranelibrary.com/"
assert_gate_not_blocked "https://dailymed.nlm.nih.gov/"
assert_gate_not_blocked "https://medlineplus.gov/"

echo "PASS: test_medical_allowlist_plumbing"
