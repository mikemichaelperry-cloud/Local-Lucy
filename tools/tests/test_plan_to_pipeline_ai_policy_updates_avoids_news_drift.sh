#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${LUCY_ROOT:-$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)}"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier: ${CLASSIFIER}"
[[ -f "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"

ai_query="What are the latest ai policy updates this past month?"
ai_plan="$(python3 "${CLASSIFIER}" "${ai_query}")"
ai_news_signal="$(python3 - "${ai_plan}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print("1" if bool((payload.get("routing_signals") or {}).get("news")) else "0")
PY
)"
[[ "${ai_news_signal}" == "0" ]] || die "AI policy updates prompt should not set news routing signal"

ai_mapped="$(python3 "${MAPPER}" --plan-json "${ai_plan}" --question "${ai_query}" --surface cli --route-control-mode AUTO)"
ai_route="$(python3 - "${ai_mapped}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("selected_route") or "").strip())
PY
)"
ai_resolved="$(python3 - "${ai_mapped}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("resolved_execution_query") or "").strip())
PY
)"
[[ "${ai_route}" == "EVIDENCE" ]] || die "AI policy updates prompt should route to EVIDENCE, got: ${ai_route}"
if printf '%s\n' "${ai_resolved}" | grep -Eqi 'latest news and developments'; then
  die "AI policy updates prompt drifted into generic news rewrite: ${ai_resolved}"
fi

news_query="What are the latest updates in Yemen this past month?"
news_plan="$(python3 "${CLASSIFIER}" "${news_query}")"
news_signal="$(python3 - "${news_plan}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print("1" if bool((payload.get("routing_signals") or {}).get("news")) else "0")
PY
)"
[[ "${news_signal}" == "1" ]] || die "non-AI updates prompt should keep news routing signal"

news_mapped="$(python3 "${MAPPER}" --plan-json "${news_plan}" --question "${news_query}" --surface cli --route-control-mode AUTO)"
news_route="$(python3 - "${news_mapped}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("selected_route") or "").strip())
PY
)"
[[ "${news_route}" == "NEWS" ]] || die "non-AI updates prompt should route to NEWS, got: ${news_route}"

ok "AI policy updates avoids NEWS drift while non-AI updates keeps NEWS routing"
echo "PASS: test_plan_to_pipeline_ai_policy_updates_avoids_news_drift"
