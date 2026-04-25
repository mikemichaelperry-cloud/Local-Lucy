#!/usr/bin/env bash
set -euo pipefail

OUT="/tmp/internet-v0-accept"
mkdir -p "$OUT"
: > "$OUT/summary.txt"
: > "$OUT/STEP.txt"

step() { echo "step=$1" > "$OUT/STEP.txt"; }

# --- Baselines: SearXNG must respond (html+json) ---
step "searx_health"
# wait briefly for SearXNG to become ready (handles fresh restarts)
for _ in 1 2 3 4 5; do
  html_code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:8080/" || true)"
  json_code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 6 "http://127.0.0.1:8080/search?q=test&format=json" || true)"
  [[ "$html_code" == "200" && "$json_code" == "200" ]] && break
  sleep 1
done
html_code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 3 "http://127.0.0.1:8080/" || true)"
json_code="$(curl -sS -o /dev/null -w "%{http_code}" --max-time 6 "http://127.0.0.1:8080/search?q=test&format=json" || true)"

# --- Gate search: must return a URL and rc=0 ---
step "gate_search"
set +e
timeout 15s bash "$HOME/lucy/tools/internet/run_search_with_gate.sh" "internet v0 acceptance" >"$OUT/search.out" 2>"$OUT/search.err"
gate_search_rc=$?
set -e

has_url=0
grep -qE '"url"\s*:\s*"https?://|https?://[^ ]' "$OUT/search.out" && has_url=1 || true

# --- SSRF blocks must hold ---
step "fetch_local"
set +e
timeout 8s bash "$HOME/lucy/tools/internet/run_fetch_with_gate.sh" "http://127.0.0.1:8080/" >"$OUT/fetch_local.out" 2>"$OUT/fetch_local.err"
rc_local=$?
set -e
deny_local=0; [[ "$rc_local" == "41" ]] && deny_local=1 || true

step "fetch_meta"
set +e
timeout 8s bash "$HOME/lucy/tools/internet/run_fetch_with_gate.sh" "http://169.254.169.254/latest/meta-data/" >"$OUT/fetch_meta.out" 2>"$OUT/fetch_meta.err"
rc_meta=$?
set -e
deny_meta=0; [[ "$rc_meta" == "41" ]] && deny_meta=1 || true

# --- Decision ---
step "done"
status="REJECTED"
if [[ "$html_code" == "200" && "$json_code" == "200" && "$gate_search_rc" == "0" && "$has_url" == "1" && "$deny_local" == "1" && "$deny_meta" == "1" ]]; then
  status="ACCEPTED"
fi

printf 'SearX(html=%s json=%s) gate_search_rc=%s has_url=%s deny_local=%s deny_meta=%s => %s\n' \
  "$html_code" "$json_code" "$gate_search_rc" "$has_url" "$deny_local" "$deny_meta" "$status" \
  > "$OUT/summary.txt"
