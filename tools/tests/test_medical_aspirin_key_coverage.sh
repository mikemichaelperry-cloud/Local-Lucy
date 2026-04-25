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

need_keys="medical_aspirin_1 medical_aspirin_2"

for k in ${need_keys}; do
  grep -Fxq "${k}" "${ALLOW}" || die "allowlist missing key: ${k}"
done
ok "medical aspirin keys present in allowlist"

for k in ${need_keys}; do
  grep -Pq "^${k}\t" "${KEYMAP}" || die "keymap missing key: ${k}"
done
ok "medical aspirin keys present in keymap"

while IFS=$'\t' read -r key url domain; do
  [[ -n "${key}" ]] || continue
  [[ "${key}" =~ ^medical_aspirin_ ]] || continue
  grep -Fqx "${domain}" "${MED_RUNTIME}" || grep -Fqx "www.${domain}" "${MED_RUNTIME}" \
    || die "domain for ${key} not in medical runtime allowlist: ${domain}"
done < "${KEYMAP}"
ok "medical aspirin key domains are medical-allowlisted"

grep -Pq "^aspirin\tEVIDENCE\tmedical_aspirin_1 medical_aspirin_2$" "${QMAP}" \
  || die "query map missing aspirin evidence mapping"
grep -Pq "^what is aspirin\tEVIDENCE\tmedical_aspirin_1 medical_aspirin_2$" "${QMAP}" \
  || die "query map missing aspirin definition mapping"
grep -Pq "^safe dose of aspirin\tEVIDENCE\tmedical_aspirin_1 medical_aspirin_2$" "${QMAP}" \
  || die "query map missing aspirin dose mapping"
ok "query map includes aspirin coverage"

echo "PASS: test_medical_aspirin_key_coverage"
