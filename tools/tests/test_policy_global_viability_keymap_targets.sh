#!/usr/bin/env bash
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
KEYMAP="${ROOT}/config/evidence_keymap_v1.tsv"

die() {
  echo "FAIL: $*" >&2
  exit 1
}

grep -Eq '^policy_ai_gov_1[[:space:]]+https://www\.bbc\.com/news/technology[[:space:]]+bbc\.com$' "${KEYMAP}" \
  || die "policy_ai_gov_1 should target BBC technology"

grep -Eq '^policy_regulation_1[[:space:]]+https://ec\.europa\.eu/commission/presscorner/api/rss\?language=en[[:space:]]+ec\.europa\.eu$' "${KEYMAP}" \
  || die "policy_regulation_1 should target European Commission RSS"

echo "PASS: policy_global viability key targets are set"
