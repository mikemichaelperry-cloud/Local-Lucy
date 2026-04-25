#!/usr/bin/env bash
# Local Lucy - Dev/Evidence+Tools - Full Verification Sweep (SAFE)
# Design goals:
# - Never store large outputs in shell variables
# - Stream to files, grep files
# - Keep terminal output small; detailed output goes to a log
# - Avoid scanning snapshots by default (they can be huge)

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)}"
TOOLS="$ROOT/tools"
LOGDIR="$ROOT/tmp/logs"
TS="$(date -Is | tr ':' '_')"
LOG="$LOGDIR/verify_all_dev_evidence_tools_v1.$TS.log"

ROUTER="$TOOLS/router/lucy_router.sh"
ROUTER_REG="$TOOLS/router/router_regression_v1.sh"
FULL_REG="$TOOLS/full_regression_v2.sh"

find_exec(){
  local base="$1"
  local p=""

  # Prefer canonical tools dir.
  if [[ -x "${TOOLS}/${base}" ]]; then
    printf "%s
" "${TOOLS}/${base}"
    return 0
  fi

  # Common subdir: tools/internet
  if [[ -x "${TOOLS}/internet/${base}" ]]; then
    printf "%s
" "${TOOLS}/internet/${base}"
    return 0
  fi

  # Prefer stable snapshots if any exist.
  p="$(find "${ROOT}/snapshots" -maxdepth 6 -type f -name "${base}" -perm -u+x 2>/dev/null | grep -E "/stable-" | sort | tail -n 1 || true)"
  if [[ -n "${p}" ]]; then
    printf "%s
" "${p}"
    return 0
  fi

  # Fallback: any snapshot.
  p="$(find "${ROOT}/snapshots" -maxdepth 6 -type f -name "${base}" -perm -u+x 2>/dev/null | sort | tail -n 1 || true)"
  [[ -n "${p}" ]] || return 1
  printf "%s
" "${p}"
}

FETCHER="$(find_exec "fetch_url_allowlisted.sh" || true)"

EVID_ONLY="$TOOLS/run_evidence_only.sh"

mkdir -p "$LOGDIR"

die(){ echo "FAIL: $*" | tee -a "$LOG" >&2; exit 1; }
ok(){  echo "OK: $*" | tee -a "$LOG" >&2; }
info(){ echo "$*" | tee -a "$LOG" >&2; }

need_file(){ [[ -f "$1" ]] || die "missing file: $1"; }
need_exec(){ [[ -x "$1" ]] || die "not executable: $1"; }

run_to_files(){
  # run_to_files "label" cmd...
  local label="$1"; shift
  local out="$LOGDIR/$label.$TS.out"
  local err="$LOGDIR/$label.$TS.err"
  set +e
  "$@" >"$out" 2>"$err"
  local rc="$?"
  set -e
  echo "$rc" >"$LOGDIR/$label.$TS.rc"
  # record small tails into main log
  {
    echo "== $label =="
    echo "rc=$rc"
    echo "-- stderr tail --"
    tail -n 40 "$err" || true
    echo "-- stdout tail --"
    tail -n 40 "$out" || true
    echo
  } >>"$LOG"
  return "$rc"
}

grep_file(){
  # grep_file file pattern description
  local f="$1"
  local pat="$2"
  local what="$3"
  grep -Eq "$pat" "$f" || die "$what (missing pattern: $pat) in $f"
}

info "== Local Lucy Verification Sweep (SAFE) =="
info "time: $(date -Is)"
info "root: $ROOT"
info "log:  $LOG"
info ""

# --- core dirs ---
for d in "$ROOT" "$TOOLS" "$ROOT/tmp" "$ROOT/snapshots"; do
  [[ -d "$d" ]] || die "missing dir: $d"
done
ok "core dirs present"

# --- key scripts exist + exec ---
need_file "$FULL_REG"; need_exec "$FULL_REG"
need_file "$ROUTER";   need_exec "$ROUTER"
need_file "$ROUTER_REG"; need_exec "$ROUTER_REG"
need_file "$EVID_ONLY"; need_exec "$EVID_ONLY"
need_file "$FETCHER";  need_exec "$FETCHER"
ok "core scripts present + executable"

# --- bash syntax on key scripts ---
bash -n "$FULL_REG"   || die "syntax: full_regression_v2.sh"
bash -n "$ROUTER"     || die "syntax: lucy_router.sh"
bash -n "$ROUTER_REG" || die "syntax: router_regression_v1.sh"
bash -n "$EVID_ONLY"  || die "syntax: run_evidence_only.sh"
bash -n "$FETCHER"    || die "syntax: fetch_url_allowlisted.sh"
ok "bash syntax OK"

# --- non-ascii scan (bounded, no snapshots) ---
info "== non-ascii scan (tools + config, bounded) =="

# Only scan these dirs; explicitly skip snapshots and tmp/logs.
# Also only scan text-like files.
NONASCII_HITS="$LOGDIR/nonascii_hits.$TS.txt"
: >"$NONASCII_HITS"

set +e
find "$ROOT/tools" "$ROOT/config" -type f \
  ! -path "$ROOT/tools/.git/*" \
  -size -2M \
  2>/dev/null \
| head -n 5000 \
| while IFS= read -r f; do
    # If grep finds non-ascii, record filename and first hit line.
    LC_ALL=C grep -n --binary-files=without-match -m 1 $'[^\x00-\x7F]' "$f" >/dev/null 2>&1
    if [[ "$?" -eq 0 ]]; then
      echo "$f" >>"$NONASCII_HITS"
    fi
  done
set -e

if [[ -s "$NONASCII_HITS" ]]; then
  {
    echo "Non-ascii files (first 50):"
    head -n 50 "$NONASCII_HITS"
  } | tee -a "$LOG" >&2
  die "non-ascii found (see $NONASCII_HITS)"
fi
ok "ASCII-only in tools + config (bounded)"

# --- evidence expansion behavior (positive + negative) ---
info "== router evidence expansion tests =="

EVID="$ROOT/tmp/router_test_evidence.txt"
cat > "$EVID" <<'EOT'
Header
Data:
one
two
three
EOT

export LUCY_EVIDENCE_FILE="$EVID"
run_to_files "router_evidence_ok" "$ROUTER" "summarize: @EVIDENCE" || die "router evidence OK rc!=0"
OUTF="$LOGDIR/router_evidence_ok.$TS.out"
grep_file "$OUTF" '^<OUT>$' "evidence: <OUT>"
grep_file "$OUTF" 'Header'  "evidence: Header"
grep_file "$OUTF" '^</OUT>$' "evidence: </OUT>"
ok "evidence expansion OK"
export LUCY_EVIDENCE_FILE="\$ROOT/tmp/does_not_exist.txt"
run_to_files "router_evidence_missing" "$ROUTER" "summarize: @EVIDENCE" || true
RC_FILE="$LOGDIR/router_evidence_missing.$TS.rc"
RC="$(cat "$RC_FILE" 2>/dev/null | tr -d "\r\n" || true)"
if ! [[ "$RC" =~ ^[0-9]+$ ]]; then die "evidence missing rc not numeric: '$RC' (file: $RC_FILE)"; fi
[[ "$RC" -ne 0 ]] || die "evidence missing file must be non-zero"
ok "evidence missing file non-zero"

export LUCY_EVIDENCE_FILE="$EVID"

# --- tool route basic ---
info "== router tool route test =="
run_to_files "router_tool_sha256" "$ROUTER" "tool: sha256 hello" || die "tool sha256 rc!=0"
OUTF="$LOGDIR/router_tool_sha256.$TS.out"
grep -q '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824' "$OUTF" \
  || die "tool sha256 mismatch"
ok "tool route OK (sha256 hello)"

# --- fetch allowlist quick check (boi) ---
info "== router fetch allowlist test =="
if ! run_to_files "router_fetch_boi" "$ROUTER" "https://boi.org.il/"; then
  OUTF="$LOGDIR/router_fetch_boi.$TS.out"
  ERRF="$LOGDIR/router_fetch_boi.$TS.err"
  if grep -Eqi 'FAIL_DNS|http_status=000|fetch failed or empty response|Temporary failure in name resolution|timed out|timeout' "$OUTF" "$ERRF" 2>/dev/null; then
    info "WARN: fetch allowlist skipped due transient network failure"
  else
    die "fetch allowlist rc!=0"
  fi
else
  OUTF="$LOGDIR/router_fetch_boi.$TS.out"
  grep_file "$OUTF" '^<OUT>$' "fetch: <OUT>"
  grep_file "$OUTF" '^url: https://boi\.org\.il/' "fetch: url"
  grep_file "$OUTF" '^bytes: ' "fetch: bytes"
  grep_file "$OUTF" '^</OUT>$' "fetch: </OUT>"
  ok "fetch allowlisted OK"
fi

# --- truncation contract check (no big variable capture) ---
info "== truncation contract test =="
export LUCY_MAX_FINAL_BYTES=1024
BIGF="$ROOT/tmp/router_big.txt"
printf "%*s" 200000 "" | tr " " "A" >"$BIGF"
run_to_files "router_trunc" "$ROUTER" "tool: readfile $BIGF" || die "truncation rc!=0"
unset LUCY_MAX_FINAL_BYTES
OUTF="$LOGDIR/router_trunc.$TS.out"
grep_file "$OUTF" '^\[TRUNCATED\]$' "truncation: marker"
tail -n 1 "$OUTF" | grep -Eq '^</OUT>$' || die "truncation: missing final </OUT>"
ok "truncation contract OK"

# --- run canonical regressions ---
info "== router_regression_v1 =="
run_to_files "router_regression_v1" "$ROUTER_REG" || die "router_regression_v1 FAIL"
ok "router_regression_v1 PASS"

info "== full_regression_v2 =="
if [[ -n "${LUCY_SKIP_FULL_REG_IN_SWEEP:-}" ]]; then
  ok "full_regression_v2 SKIPPED (LUCY_SKIP_FULL_REG_IN_SWEEP set)"
else
  run_to_files "full_regression_v2" env LUCY_SKIP_VERIFY_SWEEP=1 bash "$FULL_REG" || die "full_regression_v2 FAIL"
  ok "full_regression_v2 PASS"
fi

info ""
info "== ALL CHECKS PASS =="
