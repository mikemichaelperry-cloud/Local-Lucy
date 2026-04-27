#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
CONTEXTUAL="${ROOT}/tools/router/core/contextual_policy.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier"
[[ -f "${CONTEXTUAL}" ]] || die "missing contextual policy"

field() {
  local query="$1" key="$2"
  local plan_json
  plan_json="$("${CLASSIFIER}" "${query}")"
  PLAN_JSON="${plan_json}" python3 - "$key" <<'PY'
import json, os, sys
print(json.loads(os.environ["PLAN_JSON"]).get(sys.argv[1], ""))
PY
}

query1="Can you predict the outcome of the current military action between Israel and Iran?"
[[ "$(field "${query1}" intent)" == "WEB_NEWS" ]] || die "query1 should route as WEB_NEWS"
[[ "$(field "${query1}" region_filter)" == "IL" ]] || die "query1 should carry region_filter=IL"
ok "current military action prompt routes as Israel news"

query2="How do you predict the current war between Israel and the United states agains Iran?"
[[ "$(field "${query2}" intent)" == "WEB_NEWS" ]] || die "query2 should route as WEB_NEWS"
[[ "$(field "${query2}" region_filter)" == "IL" ]] || die "query2 should carry region_filter=IL"
ok "current war prediction prompt avoids technical-explanation misroute"

query3="What are the current tensions in the South China Sea?"
[[ "$(field "${query3}" intent)" == "WEB_NEWS" ]] || die "query3 should route as WEB_NEWS"
ok "current tensions prompt routes as news"

query4="Is there currently a ceasefire in Gaza?"
[[ "$(field "${query4}" intent)" == "WEB_NEWS" ]] || die "query4 should route as WEB_NEWS"
[[ "$(field "${query4}" region_filter)" == "IL" ]] || die "query4 should carry region_filter=IL"
ok "currently ceasefire prompt routes as Israel news"

query5="what happening south china sea rn"
[[ "$(field "${query5}" intent)" == "WEB_NEWS" ]] || die "query5 should route as WEB_NEWS"
ok "messy rn prompt routes as news"

query6="History of the Gaza conflict."
[[ "$(field "${query6}" intent)" == "LOCAL_KNOWLEDGE" ]] || die "query6 should stay LOCAL_KNOWLEDGE"
[[ "$(field "${query6}" region_filter)" != "IL" ]] || die "query6 should not force Israel region filtering"
ok "conceptual Gaza history prompt stays local"

query7="What is Hamas?"
[[ "$(field "${query7}" intent)" == "LOCAL_KNOWLEDGE" ]] || die "query7 should stay LOCAL_KNOWLEDGE"
[[ "$(field "${query7}" region_filter)" != "IL" ]] || die "query7 should not force Israel region filtering"
ok "conceptual Hamas prompt stays local"

memf="$(mktemp)"
trap 'rm -f "${memf}"' EXIT
cat > "${memf}" <<'EOF'
User: Can you predict the outcome of the current military action between Israel and Iran?
Assistant: I need current reporting for that.
EOF

resolved="$(LUCY_CHAT_MEMORY_FILE="${memf}" python3 - "${CONTEXTUAL}" <<'PY'
import importlib.util
import os
import sys
from pathlib import Path

path = sys.argv[1]
sys.path.insert(0, str(Path(path).resolve().parents[1]))
spec = importlib.util.spec_from_file_location("contextual_policy", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
out = mod.resolve_contextual_followup("And what about Lebanon?", "/home/mike/lucy-v8")
print("" if out is None else out.get("contextual_followup_kind", ""))
PY
)"
[[ "${resolved}" == "news" ]] || die "current-conflict followup should stay on news track"
ok "current conflict followup remains news-aware"

echo "PASS: test_router_current_conflict_news_routing"
