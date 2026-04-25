#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REAL_ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
WIKI_TOOL="${REAL_ROOT}/tools/unverified_context_wikipedia.py"
TMPD="$(mktemp -d)"
trap 'rm -rf "${TMPD}"' EXIT

ok(){ echo "OK: $*"; }
die(){ echo "ERR: $*" >&2; exit 1; }

[[ -f "${WIKI_TOOL}" ]] || die "missing wikipedia tool"

cache_root="${TMPD}/fake_root"
mkdir -p "${cache_root}/state"

first_json="$(
  LUCY_ROOT="${cache_root}" \
  LUCY_UNVERIFIED_CONTEXT_MOCK_TEXT="Cached wikipedia summary." \
  python3 "${WIKI_TOOL}" "Who was Alan Turing?"
)"

printf '%s\n' "${first_json}" | grep -Fq '"ok": true' || die "expected mock-backed success payload"

second_json="$(
  LUCY_ROOT="${cache_root}" \
  LUCY_UNVERIFIED_CONTEXT_WIKIPEDIA_CACHE_TTL="900" \
  python3 "${WIKI_TOOL}" "Who was Alan Turing?"
)"

printf '%s\n' "${second_json}" | grep -Fq '"ok": true' || die "expected cached success payload"
printf '%s\n' "${second_json}" | grep -Fq 'Cached wikipedia summary.' || die "expected cached payload text"
printf '%s\n' "${second_json}" | grep -Fq '"provider": "wikipedia"' || die "expected wikipedia provider in cached payload"

ok "wikipedia provider cache can satisfy a repeat query without a live fetch"
echo "PASS: test_unverified_context_wikipedia_cache"
