#!/usr/bin/env bash
set -euo pipefail

# Local Lucy full-stack health battery
# - Fail-fast by default
# - Produces one report directory with a single summary file
# - Designed to be snapshot-friendly and reproducible

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TS="$(date +%Y%m%dT%H%M%S%z)"
OUT_BASE="${ROOT}/tmp/test_reports/health_battery"
OUT_DIR="${OUT_BASE}/${TS}"
SUMMARY="${OUT_DIR}/summary.txt"
LOG="${OUT_DIR}/run.log"

mkdir -p "${OUT_DIR}"

log(){ printf '%s\n' "$*" | tee -a "${LOG}" >/dev/null; }
kv(){ printf '%s: %s\n' "$1" "$2" | tee -a "${SUMMARY}" >/dev/null; }

die(){
  log "FAIL: $*"
  kv "status" "FAIL"
  kv "fail_reason" "$*"
  exit 1
}

run_step(){
  # Usage: run_step "name" "command ..."
  local name="$1"; shift
  local start end rc
  start="$(date -Is)"

  log
  log "== STEP: ${name} =="
  log "start: ${start}"
  log "cmd: $*"

  set +e
  "$@" >>"${LOG}" 2>&1
  rc="$?"
  set -e

  end="$(date -Is)"
  log "end: ${end}"
  log "rc: ${rc}"

  if [ "${rc}" -ne 0 ]; then
    kv "step_${name}" "FAIL"
    kv "step_${name}_rc" "${rc}"
    die "step failed: ${name}"
  fi

  kv "step_${name}" "OK"
}

usage(){
  cat <<'USAGE'
Usage:
  tools/health_battery.sh [options]

Options:
  --skip-internet           Skip internet regression step
  --skip-full               Skip full_regression_v2 step
  --skip-router             Skip router_regression step
  --skip-golden             Skip golden_eval step
  --keep-going              Do not fail-fast; record failures and continue
  --out-dir PATH            Override output dir (default: tmp/test_reports/health_battery/<timestamp>)
  --help                    Show this help

Notes:
  - Default behavior is fail-fast.
  - This script assumes it is run from within a snapshot root containing:
      tools/sha_manifest.sh
      tools/router_regression.sh
      tools/full_regression_v2.sh
      tools/golden_eval.sh
      tools/internet/all_systems_regression.sh
USAGE
}

SKIP_INTERNET=0
SKIP_FULL=0
SKIP_ROUTER=0
SKIP_GOLDEN=0
KEEP_GOING=0

# Parse args (minimal, robust)
while [ "${#}" -gt 0 ]; do
  case "$1" in
    --skip-internet) SKIP_INTERNET=1; shift ;;
    --skip-full)     SKIP_FULL=1; shift ;;
    --skip-router)   SKIP_ROUTER=1; shift ;;
    --skip-golden)   SKIP_GOLDEN=1; shift ;;
    --keep-going)    KEEP_GOING=1; shift ;;
    --out-dir)
      [ "${#}" -ge 2 ] || die "--out-dir requires a value"
      OUT_DIR="$2"
      SUMMARY="${OUT_DIR}/summary.txt"
      LOG="${OUT_DIR}/run.log"
      mkdir -p "${OUT_DIR}"
      shift 2
      ;;
    --help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

# Keep-going mode: do not die on step failure; record and continue
run_step_maybe(){
  local name="$1"; shift
  if [ "${KEEP_GOING}" -eq 0 ]; then
    run_step "${name}" "$@"
    return 0
  fi

  local start end rc
  start="$(date -Is)"
  log
  log "== STEP: ${name} =="
  log "start: ${start}"
  log "cmd: $*"

  set +e
  "$@" >>"${LOG}" 2>&1
  rc="$?"
  set -e

  end="$(date -Is)"
  log "end: ${end}"
  log "rc: ${rc}"

  if [ "${rc}" -ne 0 ]; then
    kv "step_${name}" "FAIL"
    kv "step_${name}_rc" "${rc}"
    return "${rc}"
  fi

  kv "step_${name}" "OK"
  return 0
}

# Header
: >"${SUMMARY}"
: >"${LOG}"

kv "time" "$(date -Is)"
kv "root" "${ROOT}"
kv "out_dir" "${OUT_DIR}"
kv "status" "RUNNING"

# Capture manifest hash if present (useful for "known-good stamp")
MANIFEST_SHA="NA"
if [ -f "${ROOT}/SHA256SUMS.clean" ]; then
  # sha256 of the manifest file itself
  MANIFEST_SHA="$(sha256sum "${ROOT}/SHA256SUMS.clean" | awk '{print $1}')"
fi
kv "manifest_sha256" "${MANIFEST_SHA}"

# Environment notes (optional, but useful)
kv "user" "$(id -un 2>/dev/null || echo unknown)"
kv "host" "$(hostname 2>/dev/null || echo unknown)"
kv "shell" "${SHELL:-unknown}"

# Steps
FAILS=0

run_step_maybe "integrity" "${ROOT}/tools/sha_manifest.sh" check || FAILS=$((FAILS+1))

if [ "${SKIP_ROUTER}" -eq 1 ]; then
  kv "step_router" "SKIPPED"
else
  run_step_maybe "router" "${ROOT}/tools/router_regression.sh" || FAILS=$((FAILS+1))
fi

if [ "${SKIP_FULL}" -eq 1 ]; then
  kv "step_full_regression_v2" "SKIPPED"
else
  run_step_maybe "full_regression_v2" "${ROOT}/tools/full_regression_v2.sh" || FAILS=$((FAILS+1))
fi

if [ "${SKIP_GOLDEN}" -eq 1 ]; then
  kv "step_golden_eval" "SKIPPED"
else
  # Full-stack health must fail if golden's system checks fail.
  run_step_maybe "golden_eval" "${ROOT}/tools/golden_eval.sh" --hard-fail-system || FAILS=$((FAILS+1))
fi

if [ "${SKIP_INTERNET}" -eq 1 ]; then
  kv "step_internet_all_systems" "SKIPPED"
else
  run_step_maybe "internet_all_systems" "${ROOT}/tools/internet/all_systems_regression.sh" || FAILS=$((FAILS+1))
fi

# Final status
if [ "${FAILS}" -eq 0 ]; then
  kv "status" "PASS"
  kv "fails" "0"
  log
  log "PASS: full-stack health battery complete"
  exit 0
fi

kv "status" "FAIL"
kv "fails" "${FAILS}"
log
log "FAIL: ${FAILS} step(s) failed (keep-going mode)"
exit 1
