#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

# Ensure SearXNG is up (fast, bounded)
"$LUCY_ROOT/tools/internet/searxng_ensure_up.sh" "http://127.0.0.1:8080/" || { echo '{"error":"searxng_down"}'; exit 3; }

q="${1:-}"
if [[ -z "${q}" ]]; then
  echo '{"error":"missing_query"}'
  exit 2
fi

payload="$(python3 - "$q" <<'PY'
import json,sys
q=sys.argv[1]
print(json.dumps({"query": q, "max_results": 5}, ensure_ascii=False))
PY
)"

# Finite stdin; internal timeout is OK (belt & suspenders).
printf '%s' "$payload" | timeout 12s python3 "$LUCY_ROOT/tools/internet/search_web.py"
