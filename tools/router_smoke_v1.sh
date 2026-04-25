#!/usr/bin/env bash
set -euo pipefail

R="$HOME/lucy/lucy_chat.sh"

ok(){ echo "OK: $*"; }
die(){ echo "ERR: $*" >&2; exit 1; }

need(){ [ -x "$1" ] || die "missing: $1"; }

need "$R"

check_wrap(){
  local out begins ends
  out="$1"
  begins="$(grep -c '^BEGIN_VALIDATED$' "$out" || true)"
  ends="$(grep -c '^END_VALIDATED$' "$out" || true)"
  [ "$begins" -eq 1 ] || die "bad BEGIN count: $begins"
  [ "$ends" -eq 1 ] || die "bad END count: $ends"
}

t="$(mktemp)"

"$R" "how do I cook mashed potatoes" > "$t" 2>&1 || true
check_wrap "$t"; ok "LOCAL wrap"

"$R" "price of eggs in China today" > "$t" 2>&1 || true
check_wrap "$t"; ok "EVIDENCE wrap"

LUCY_NEWS_MIN_SOURCES=1 "$R" "latest Israeli news" > "$t" 2>&1 || true
check_wrap "$t"; ok "NEWS wrap"

rm -f "$t"
ok "router_smoke_v1 complete"
