#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
KEYMAP="${ROOT}/config/evidence_keymap_v1.tsv"
QUERYMAP="${ROOT}/config/query_to_keys_v1.tsv"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${KEYMAP}" ]] || die "missing keymap"
[[ -f "${QUERYMAP}" ]] || die "missing query-to-keys map"

world5_row="$(awk -F'\t' '$1=="news_world_5"{print $0; exit}' "${KEYMAP}")"
[[ -n "${world5_row}" ]] || die "missing news_world_5 mapping"

world5_url="$(printf '%s\n' "${world5_row}" | awk -F'\t' '{print $2}')"
world5_domain="$(printf '%s\n' "${world5_row}" | awk -F'\t' '{print $3}')"

[[ "${world5_url}" == "https://apnews.com/" ]] || die "expected news_world_5 url to point to apnews.com (got ${world5_url})"
[[ "${world5_domain}" == "apnews.com" ]] || die "expected news_world_5 domain label apnews.com (got ${world5_domain})"
ok "news_world_5 maps to AP"

world_row="$(awk -F'\t' '$1=="latest world news" && $2=="NEWS"{print $3; exit}' "${QUERYMAP}")"
[[ -n "${world_row}" ]] || die "missing latest world news NEWS mapping"
printf '%s\n' "${world_row}" | grep -Fq 'news_world_5' || die "latest world news mapping should still include news_world_5"
ok "latest world news continues to select news_world_5"

if awk -F'\t' '$1 ~ /^news_world_/ && ($2 ~ /washingtonpost/ || $3 ~ /washingtonpost/){found=1} END{exit(found ? 0 : 1)}' "${KEYMAP}"; then
  die "world-news keymap still contains washingtonpost"
fi
ok "world-news keymap no longer references washingtonpost"

echo "PASS: test_world_news_keymap_avoids_washingtonpost"
