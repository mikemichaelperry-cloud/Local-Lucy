#!/usr/bin/env bash
set -euo pipefail

ROOT="${LUCY_ROOT:-/home/mike/lucy/snapshots/opt-experimental-v7-dev}"
KEYMAP="${ROOT}/config/evidence_keymap_v1.tsv"
ALLOW_FETCH="${ROOT}/config/trust/generated/allowlist_fetch.txt"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${KEYMAP}" ]] || die "missing keymap: ${KEYMAP}"
[[ -f "${ALLOW_FETCH}" ]] || die "missing allowlist: ${ALLOW_FETCH}"

cpi1="$(awk -F'\t' '$1=="cpi_us_1"{print $2"\t"$3; exit}' "${KEYMAP}")"
cpi2="$(awk -F'\t' '$1=="cpi_us_2"{print $2"\t"$3; exit}' "${KEYMAP}")"

[[ "${cpi1}" == $'https://www.bls.gov/news.release/cpi.nr0.htm\tbls.gov' ]] \
  || die "cpi_us_1 must bind to BLS CPI release page"
[[ "${cpi2}" == $'https://apnews.com/hub/inflation\tapnews.com' ]] \
  || die "cpi_us_2 must bind to AP inflation hub"

grep -Fxq "bls.gov" "${ALLOW_FETCH}" || die "allowlist_fetch missing bls.gov"
grep -Fxq "www.bls.gov" "${ALLOW_FETCH}" || die "allowlist_fetch missing www.bls.gov"

ok "cpi_us_* key bindings target CPI-relevant sources and include BLS in fetch allowlist"
echo "PASS: test_cpi_us_keymap_binds_release_sources"
