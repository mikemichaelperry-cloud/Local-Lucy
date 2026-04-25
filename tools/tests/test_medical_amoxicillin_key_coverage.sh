#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

ALLOW="${ROOT}/config/evidence_keys_allowlist.txt"
KEYMAP="${ROOT}/config/evidence_keymap_v1.tsv"
QMAP="${ROOT}/config/query_to_keys_v1.tsv"
MED_RUNTIME="${ROOT}/config/trust/generated/medical_runtime.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

for f in "${ALLOW}" "${KEYMAP}" "${QMAP}" "${MED_RUNTIME}"; do
  [[ -f "${f}" ]] || die "missing file: ${f}"
done

need_keys="medical_amoxicillin_1 medical_amoxicillin_2"

for k in ${need_keys}; do
  grep -Fxq "${k}" "${ALLOW}" || die "allowlist missing key: ${k}"
done
ok "medical amoxicillin keys present in allowlist"

for k in ${need_keys}; do
  grep -Pq "^${k}\t" "${KEYMAP}" || die "keymap missing key: ${k}"
done
ok "medical amoxicillin keys present in keymap"

while IFS=$'\t' read -r key url domain; do
  [[ -n "${key}" ]] || continue
  [[ "${key}" =~ ^medical_amoxicillin_ ]] || continue
  grep -Fqx "${domain}" "${MED_RUNTIME}" || grep -Fqx "www.${domain}" "${MED_RUNTIME}" \
    || die "domain for ${key} not in medical runtime allowlist: ${domain}"
done < "${KEYMAP}"
ok "medical amoxicillin key domains are medical-allowlisted"

grep -Pq "^amoxicillin\tEVIDENCE\tmedical_amoxicillin_1 medical_amoxicillin_2$" "${QMAP}" \
  || die "query map missing amoxicillin evidence mapping"
grep -Pq "^amoxycilin\tEVIDENCE\tmedical_amoxicillin_1 medical_amoxicillin_2$" "${QMAP}" \
  || die "query map missing amoxycilin evidence mapping"
ok "query map includes amoxicillin misspelling coverage"

echo "PASS: test_medical_amoxicillin_key_coverage"
