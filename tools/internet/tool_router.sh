#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

TOOL="${1:-}"; shift || true
ARGS_JSON="${1:-}"

# Helper: extract a field from a JSON string (no jq dependency)
json_get() {
  local key="$1"
  local js="${2:-}"
  python3 - "$key" "$js" <<'PY'
import json,sys
k=sys.argv[1]
raw=sys.argv[2]
try:
  o=json.loads(raw) if raw.strip() else {}
except Exception:
  o={}
v=o.get(k,"")
if isinstance(v,(dict,list)):
  print(json.dumps(v,ensure_ascii=False))
else:
  print(v)
PY
}

# If second argument looks like JSON, extract parameters. Otherwise treat remaining args as positional.
is_json=0
if [[ "$ARGS_JSON" =~ ^\{.*\}$ ]]; then is_json=1; fi

case "$TOOL" in
  search_web|search_web_v0)
    if [[ "$is_json" == "1" ]]; then
      # JSON-mode: call search_web.py directly (it expects JSON on stdin)
      echo "$ARGS_JSON" | exec python3 "$LUCY_ROOT/tools/internet/search_web.py"
    else
      exec "$LUCY_ROOT/tools/internet/run_search_with_gate.sh" "$@"
    fi
    ;;

  fetch_url|fetch_url_v0)
    if [[ "$is_json" == "1" ]]; then
      url="$(json_get url "$ARGS_JSON")"
      exec "$LUCY_ROOT/tools/internet/run_fetch_with_gate.sh" "$url"
    else
      exec "$LUCY_ROOT/tools/internet/run_fetch_with_gate.sh" "$@"
    fi
    ;;

  fetch_url_v1)
    if [[ "$is_json" == "1" ]]; then
      url="$(json_get url "$ARGS_JSON")"
      exec "$LUCY_ROOT/tools/internet/run_fetch_with_gate_v1.sh" "$url"
    else
      exec "$LUCY_ROOT/tools/internet/run_fetch_with_gate_v1.sh" "$@"
    fi
    ;;

  *)
    echo "{\"error\":\"unknown_tool\",\"tool\":\"$TOOL\"}"
    exit 2
    ;;
esac
