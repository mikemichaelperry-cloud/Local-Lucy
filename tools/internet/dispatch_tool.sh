#!/usr/bin/env bash
set -euo pipefail

# Self-locate project root if not already provided by caller
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LUCY_ROOT="${LUCY_ROOT:-$(cd -- "$SCRIPT_DIR/../.." && pwd)}"

TOOL="${1:?tool name}"
PAYLOAD_JSON="${2:?json payload}"

case "$TOOL" in
  search_web)
    q=$(python3 - <<'PY' "$PAYLOAD_JSON"
import json,sys
d=json.loads(sys.argv[1])
print(d.get("query",""))
PY
)
    n=$(python3 - <<'PY' "$PAYLOAD_JSON"
import json,sys
d=json.loads(sys.argv[1])
print(int(d.get("max_results",5)))
PY
)
    exec "$LUCY_ROOT/tools/internet/run_search_with_gate.sh" "$q" "$n"
    ;;
  fetch_url)
    u=$(python3 - <<'PY' "$PAYLOAD_JSON"
import json,sys
d=json.loads(sys.argv[1])
print(d.get("url",""))
PY
)
    b=$(python3 - <<'PY' "$PAYLOAD_JSON"
import json,sys
d=json.loads(sys.argv[1])
print(int(d.get("max_bytes",400000)))
PY
)
    exec "$LUCY_ROOT/tools/internet/run_fetch_with_gate.sh" "$u" "$b"
    ;;

  *)
    echo "{\"error\":\"unknown_tool\",\"detail\":\"$TOOL\"}"
    exit 2
    ;;
esac
