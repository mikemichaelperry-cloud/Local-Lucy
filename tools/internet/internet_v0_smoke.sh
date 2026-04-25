#!/usr/bin/env bash
set -euo pipefail

OUT="/tmp/internet-v0-smoke"
mkdir -p "$OUT"
: > "$OUT/log.txt"

log() { echo "$*" >> "$OUT/log.txt"; }

PASS=1

# --- 1) Ensure SearXNG is up ---
log "checking searxng"
if ! ~/lucy/tools/internet/searxng_ensure_up.sh "http://127.0.0.1:8080/"; then
  log "FAIL: searxng not responding"
  PASS=0
fi

# --- 2) Search gate must succeed ---
log "checking search gate"
if ! timeout 12s bash ~/lucy/tools/internet/run_search_with_gate.sh "smoke test" >/dev/null 2>&1; then
  log "FAIL: search gate"
  PASS=0
fi

# --- 3) SSRF localhost must be blocked ---
log "checking localhost block"
if timeout 6s bash ~/lucy/tools/internet/run_fetch_with_gate.sh "http://127.0.0.1:8080/" >/dev/null 2>&1; then
  log "FAIL: localhost fetch allowed"
  PASS=0
fi

# --- 4) Metadata IP must be blocked ---
log "checking metadata block"
if timeout 6s bash ~/lucy/tools/internet/run_fetch_with_gate.sh "http://169.254.169.254/latest/meta-data/" >/dev/null 2>&1; then
  log "FAIL: metadata fetch allowed"
  PASS=0
fi

# --- Result ---
if [[ "$PASS" == "1" ]]; then
  echo "Internet v0 smoke test: PASS"
  exit 0
else
  echo "Internet v0 smoke test: FAIL (see $OUT/log.txt)"
  exit 1
fi
