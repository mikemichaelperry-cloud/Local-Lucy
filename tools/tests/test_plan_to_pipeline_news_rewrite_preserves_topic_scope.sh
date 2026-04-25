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

query="What are the most significant developments in AI this past month?"
plan_json="$(python3 "${CLASSIFIER}" "${query}")"
mapped_json="$(python3 "${MAPPER}" --plan-json "${plan_json}" --question "${query}" --surface cli --route-control-mode AUTO)"

resolved_exec_q="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("resolved_execution_query") or "").strip())
PY
)"
selected_route="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("selected_route") or "").strip())
PY
)"

[[ "${selected_route}" == "EVIDENCE" ]] || die "expected AI recency query to avoid NEWS drift, got route: ${selected_route}"
printf '%s\n' "${resolved_exec_q}" | grep -Eqi '^what are the most significant developments in ai this past month\?$' \
  || die "unexpected resolved execution query: ${resolved_exec_q}"
printf '%s\n' "${resolved_exec_q}" | grep -Eqi '^what are the latest news and developments about what are ' \
  && die "query drifted into wrapped generic news form: ${resolved_exec_q}"
ok "AI recency query stays topic-scoped and avoids generic news rewrite drift"

echo "PASS: test_plan_to_pipeline_news_rewrite_preserves_topic_scope"
