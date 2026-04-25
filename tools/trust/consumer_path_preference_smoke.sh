#!/usr/bin/env bash
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
FETCH="$ROOT/tools/fetch_url_allowlisted.sh"
GEN_DIR="$ROOT/config/trust/generated"
P1="$GEN_DIR/allowlist_all_tier12.txt"
P2="$GEN_DIR/allowlist_fetch.txt"
[[ -x "$FETCH" ]] || { echo "ERR: missing fetch_url_allowlisted.sh" >&2; exit 1; }
[[ -s "$P2" || -s "$P1" ]] || { echo "ERR: generated allowlist missing" >&2; exit 1; }
out="$(LUCY_TRUST_DEBUG=1 "$FETCH" https://example.com/ 2>&1 || true)"
printf '%s\n' "$out" | grep -q 'DEBUG_TRUST' || { echo "ERR: no trust debug output" >&2; exit 1; }
printf '%s\n' "$out" | grep -Eq 'config/trust/generated/(allowlist_all_tier12|allowlist_fetch)\.txt' || { echo "ERR: did not prefer generated trust file" >&2; exit 1; }
if [[ -s "$P1" ]]; then
  mv "$P1" "$P1.bak.utl"
  trap '[[ -f "$P1.bak.utl" ]] && mv "$P1.bak.utl" "$P1"' EXIT
  out2="$(LUCY_TRUST_DEBUG=1 "$FETCH" https://example.com/ 2>&1 || true)"
  printf '%s\n' "$out2" | grep -Eq 'DEBUG_TRUST allow_domains_file=' || { echo "ERR: fallback debug missing" >&2; exit 1; }
  if [[ -s "$P2" ]]; then
    printf '%s\n' "$out2" | grep -q 'allowlist_fetch.txt' || { echo "ERR: fallback did not use generated fetch allowlist" >&2; exit 1; }
  fi
  mv "$P1.bak.utl" "$P1"
  trap - EXIT
fi
echo "PASS: consumer_path_preference_smoke"
