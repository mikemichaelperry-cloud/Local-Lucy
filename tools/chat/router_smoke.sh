#!/usr/bin/env bash
set -euo pipefail

ROOT="${LUCY_ROOT:-$HOME/lucy}"
CHAT="$ROOT/lucy_chat.sh"

die(){ echo "ERR: $*" >&2; exit 1; }
ok(){ echo "OK: $*"; }

needx(){ [ -x "$1" ] || die "missing executable: $1"; }

assert_one_block(){
  local b e
  b="$(grep -c '^[[:space:]]*BEGIN_VALIDATED[[:space:]]*$' "$1" || true)"
  e="$(grep -c '^[[:space:]]*END_VALIDATED[[:space:]]*$' "$1" || true)"
  [ "$b" = "1" ] || die "expected 1 BEGIN_VALIDATED, got $b"
  [ "$e" = "1" ] || die "expected 1 END_VALIDATED, got $e"
}

assert_no_block(){
  local b e
  b="$(grep -c '^[[:space:]]*BEGIN_VALIDATED[[:space:]]*$' "$1" || true)"
  e="$(grep -c '^[[:space:]]*END_VALIDATED[[:space:]]*$' "$1" || true)"
  [ "$b" = "0" ] || die "expected 0 BEGIN_VALIDATED, got $b"
  [ "$e" = "0" ] || die "expected 0 END_VALIDATED, got $e"
}

assert_has(){
  local pat="$1" f="$2"
  grep -Eq -- "$pat" "$f" || die "missing pattern: $pat"
}

assert_no_leaks(){
  grep -qi 'Not in memory:' "$1" && die "leaked: Not in memory"
  grep -qi 'Not provided in this session' "$1" && die "leaked: evidence placeholder"
  return 0
}

main(){
  needx "$CHAT"

  out="$(mktemp)"
  trap 'rm -f "$out"' EXIT

  "$CHAT" "how do I cook mashed potatoes" >"$out" 2>&1 || true
  assert_no_block "$out"
  assert_no_leaks "$out"
  ok "LOCAL ok"

  "$CHAT" "price of eggs in China today" >"$out" 2>&1 || true
  assert_no_block "$out"
  test -s "$out" || die "EVIDENCE smoke output empty"
  ok "EVIDENCE ok"

  "$CHAT" "usd to ils exchange rate" >"$out" 2>&1 || true
  assert_no_block "$out"
  assert_has 'This requires evidence mode\.' "$out"
  ok "FX ok"

  LUCY_NEWS_MIN_SOURCES=2 "$CHAT" "latest Israeli news" >"$out" 2>&1 || true
  assert_no_block "$out"
  assert_has '^Sources:' "$out"
  ok "NEWS ok"

  ok "router smoke complete"
}

main "$@"
