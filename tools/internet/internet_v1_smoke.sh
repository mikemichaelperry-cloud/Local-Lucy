#!/usr/bin/env bash
set -euo pipefail

OUT="/tmp/internet-v1-smoke"
mkdir -p "$OUT"
: > "$OUT/log.txt"

log(){ echo "$*" >> "$OUT/log.txt"; }
PASS=1

# Must block localhost + metadata
if timeout 6s bash ~/lucy/tools/internet/run_fetch_with_gate_v1.sh "http://127.0.0.1:8080/" >/dev/null 2>&1; then
  log "FAIL: localhost allowed"; PASS=0
fi
if timeout 6s bash ~/lucy/tools/internet/run_fetch_with_gate_v1.sh "http://169.254.169.254/latest/meta-data/" >/dev/null 2>&1; then
  log "FAIL: metadata allowed"; PASS=0
fi

# Must block non-allowlisted
if timeout 6s bash ~/lucy/tools/internet/run_fetch_with_gate_v1.sh "https://example.com" >/dev/null 2>&1; then
  log "FAIL: non-allowlisted allowed"; PASS=0
fi

# Must succeed on allowlisted (wikipedia.org)
if ! timeout 15s bash ~/lucy/tools/internet/run_fetch_with_gate_v1.sh "https://en.wikipedia.org/wiki/Test" >"$OUT/wiki.json" 2>>"$OUT/log.txt"; then
  log "FAIL: allowlisted fetch"; PASS=0
else
  python3 - <<'PY' "$OUT/wiki.json" || { echo "FAIL: missing meta/hash" >> "'"$OUT/log.txt"'"; exit 1; }
import json,sys
o=json.load(open(sys.argv[1],'r',encoding='utf-8',errors='replace'))
m=o.get("meta",{})
assert "output_sha256" in m and len(m["output_sha256"])==64
assert m.get("tool_version")==1
PY
fi

if [[ "$PASS" == "1" ]]; then
  echo "Internet v1 smoke test: PASS"
  exit 0
else
  echo "Internet v1 smoke test: FAIL (see $OUT/log.txt)"
  exit 1
fi
