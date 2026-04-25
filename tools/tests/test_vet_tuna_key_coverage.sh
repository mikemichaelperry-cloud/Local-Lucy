#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"

ALLOW="${ROOT}/config/evidence_keys_allowlist.txt"
KEYMAP="${ROOT}/config/evidence_keymap_v1.tsv"
QMAP="${ROOT}/config/query_to_keys_v1.tsv"
VET_RUNTIME="${ROOT}/config/trust/generated/vet_runtime.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

for f in "${ALLOW}" "${KEYMAP}" "${QMAP}" "${VET_RUNTIME}"; do
  [[ -f "${f}" ]] || die "missing file: ${f}"
done

need_keys="vet_tuna_1 vet_tuna_2 vet_tuna_3 vet_tuna_4"

for k in ${need_keys}; do
  grep -Fxq "${k}" "${ALLOW}" || die "allowlist missing key: ${k}"
done
ok "vet tuna keys present in allowlist"

for k in ${need_keys}; do
  grep -Pq "^${k}\t" "${KEYMAP}" || die "keymap missing key: ${k}"
done
ok "vet tuna keys present in keymap"

need_general_keys="vet_general_1 vet_general_2 vet_general_3 vet_general_4 vet_general_5 vet_general_6 vet_general_7 vet_general_8"

for k in ${need_general_keys}; do
  grep -Fxq "${k}" "${ALLOW}" || die "allowlist missing key: ${k}"
done
ok "vet general keys present in allowlist"

for k in ${need_general_keys}; do
  grep -Pq "^${k}\t" "${KEYMAP}" || die "keymap missing key: ${k}"
done
ok "vet general keys present in keymap"

while IFS=$'\t' read -r key url domain; do
  [[ -n "${key}" ]] || continue
  [[ "${key}" =~ ^vet_tuna_ || "${key}" =~ ^vet_general_ ]] || continue
  grep -Fqx "${domain}" "${VET_RUNTIME}" || grep -Fqx "www.${domain}" "${VET_RUNTIME}" \
    || die "domain for ${key} not in vet runtime allowlist: ${domain}"
done < "${KEYMAP}"
ok "vet tuna/general key domains are vet-allowlisted"

grep -Pq "^safe to feed tuna\tEVIDENCE\tvet_tuna_1 vet_tuna_2 vet_tuna_3 vet_tuna_4$" "${QMAP}" \
  || die "query map missing safe-to-feed tuna evidence mapping"
grep -Pq "^tinned tuna\tEVIDENCE\tvet_tuna_1 vet_tuna_2 vet_tuna_3 vet_tuna_4$" "${QMAP}" \
  || die "query map missing tinned tuna evidence mapping"
grep -Pq "^tuna in olive oil\tEVIDENCE\tvet_tuna_1 vet_tuna_2 vet_tuna_3 vet_tuna_4$" "${QMAP}" \
  || die "query map missing tuna in olive oil evidence mapping"
ok "query map includes vet tuna evidence mappings"

grep -Pq "^dog symptoms\tEVIDENCE\tvet_general_1 vet_general_2 vet_general_5 vet_general_7$" "${QMAP}" \
  || die "query map missing dog symptoms evidence mapping"
grep -Pq "^dog ate chocolate\tEVIDENCE\tvet_general_3 vet_general_1 vet_general_2 vet_general_8$" "${QMAP}" \
  || die "query map missing dog ate chocolate evidence mapping"
grep -Pq "^can i give my dog ibuprofen\tEVIDENCE\tvet_general_1 vet_general_2 vet_general_7 vet_general_8$" "${QMAP}" \
  || die "query map missing dog ibuprofen evidence mapping"
ok "query map includes vet general evidence mappings"

echo "PASS: test_vet_tuna_key_coverage"
