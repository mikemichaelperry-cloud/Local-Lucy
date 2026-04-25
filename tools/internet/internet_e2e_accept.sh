#!/usr/bin/env bash
set -euo pipefail

OUT="/tmp/internet-e2e"
mkdir -p "$OUT"
LOG="$OUT/log.txt"
: > "$LOG"

log(){ echo "[$(date -Is)] $*" >> "$LOG"; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
ROUTER="$LUCY_ROOT/tools/internet/tool_router.sh"

PASS=1
fail(){ log "FAIL: $*"; PASS=0; }

# --- 0) Preflight ---
[[ -x "$ROUTER" ]] || { echo "Internet E2E: FAIL (router missing: $ROUTER)"; exit 1; }

# --- 1) SearXNG local sanity ---
html_code="$(timeout 6s curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8080/" || echo 000)"
json_code="$(timeout 6s curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8080/search?q=test&format=json" || echo 000)"
log "SearXNG html=$html_code json=$json_code"
[[ "$html_code" == "200" ]] || fail "SearXNG / not 200 (got $html_code)"
[[ "$json_code" == "200" ]] || fail "SearXNG /search?format=json not 200 (got $json_code)"

# --- 2) search_web (JSON mode) ---
SEARCH_JSON='{"query":"Test Wikipedia","max_results":3,"domains":["wikipedia.org"]}'
if timeout 15s "$ROUTER" search_web "$SEARCH_JSON" > "$OUT/search.json" 2>>"$LOG"; then
  log "search_web bytes=$(wc -c < "$OUT/search.json")"
else
  fail "search_web tool call failed"
fi

# Extract first URL
URL="$(python3 - "$OUT/search.json" <<'PY' 2>>"$LOG"
import json,sys
o=json.load(open(sys.argv[1],encoding="utf-8",errors="replace"))
r=o.get("results") or []
print((r[0].get("url","") if r else "").strip())
PY
)"
log "search_top_url=$URL"
[[ -n "$URL" ]] || fail "search_web returned no URLs"

# --- 3) fetch_url_v1 (JSON mode) ---
FETCH_JSON="$(python3 - <<PY
import json
print(json.dumps({"url": "$URL"}, ensure_ascii=False))
PY
)"

if timeout 20s "$ROUTER" fetch_url_v1 "$FETCH_JSON" > "$OUT/fetch_v1.json" 2>>"$LOG"; then
  log "fetch_v1 bytes=$(wc -c < "$OUT/fetch_v1.json")"
else
  fail "fetch_url_v1 tool call failed"
fi

# Validate envelope
if python3 - "$OUT/fetch_v1.json" <<'PY' 2>>"$LOG"; then
import json,sys
o=json.load(open(sys.argv[1],encoding="utf-8",errors="replace"))
assert o.get("trust_level") == "external_unverified"
assert o.get("ok") is True
m=o.get("meta") or {}
assert m.get("tool_version")==1
h=m.get("output_sha256","")
assert isinstance(h,str) and len(h)==64
b=m.get("bytes",0)
assert isinstance(b,int) and b>0
content=(o.get("data") or {}).get("content","")
assert isinstance(content,str) and len(content) > 120
PY
  log "fetch_url_v1 envelope OK"
else
  fail "fetch_url_v1 envelope/meta validation failed"
fi

# --- 4) SSRF blocks (localhost + metadata) ---
block_test() {
  local u="$1"
  local js
  js="$(python3 - <<PY
import json
print(json.dumps({"url":"$u"}, ensure_ascii=False))
PY
)"
  timeout 8s bash -lc 'exec </dev/null; "'"$ROUTER"'" fetch_url_v1 "$1" >/dev/null 2>&1' _ "$js"
}

if block_test "http://127.0.0.1:8080/"; then
  fail "localhost fetch was allowed (should be blocked)"
else
  log "localhost blocked OK"
fi

if block_test "http://169.254.169.254/latest/meta-data/"; then
  fail "metadata fetch was allowed (should be blocked)"
else
  log "metadata blocked OK"
fi

# --- Summary ---
if [[ "$PASS" == "1" ]]; then
  echo "Internet E2E: PASS"
  log "RESULT=PASS"
  exit 0
else
  echo "Internet E2E: FAIL (see $LOG)"
  log "RESULT=FAIL"
  exit 1
fi
