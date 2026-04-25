#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
ALLOW="${ROOT}/config/evidence_keys_allowlist.txt"
KMAP="${ROOT}/config/evidence_keymap_v1.tsv"
QMAP="${ROOT}/config/query_to_keys_v1.tsv"
MED_ALLOW="${ROOT}/config/trust/generated/medical_runtime.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

need_keys="medical_hypertension_1 medical_hypertension_2"
for key in ${need_keys}; do
  grep -Fxq "${key}" "${ALLOW}" || die "missing ${key} in allowlist"
done
ok "medical hypertension keys present in allowlist"

for key in ${need_keys}; do
  awk -F'\t' -v k="${key}" '$1==k {found=1} END{exit(found?0:1)}' "${KMAP}" || die "missing ${key} in keymap"
done
ok "medical hypertension keys present in keymap"

while IFS=$'\t' read -r key url domain; do
  [[ "${key}" =~ ^medical_hypertension_ ]] || continue
  grep -Fxiq "${domain}" "${MED_ALLOW}" || die "domain ${domain} for ${key} is not medical-allowlisted"
done < "${KMAP}"
ok "medical hypertension key domains are medical-allowlisted"

grep -Pq "^medication for high blood pressure\tEVIDENCE\tmedical_hypertension_1 medical_hypertension_2$" "${QMAP}" \
  || die "query map missing blood pressure medication evidence mapping"
grep -Pq "^what is the correct medication for high blood pressure\tEVIDENCE\tmedical_hypertension_1 medical_hypertension_2$" "${QMAP}" \
  || die "query map missing full hypertension medication question mapping"
ok "query map includes hypertension medication coverage"

echo "PASS: test_medical_hypertension_key_coverage"
