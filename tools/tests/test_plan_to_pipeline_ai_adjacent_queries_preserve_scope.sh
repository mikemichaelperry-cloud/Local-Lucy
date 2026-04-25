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

assert_ai_query_stays_evidence(){
  local query="$1" mapped_json selected_route resolved_exec_q
  mapped_json="$(python3 "${MAPPER}" --plan-json "$(python3 "${CLASSIFIER}" "${query}")" --question "${query}" --surface cli --route-control-mode AUTO)"
  selected_route="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("selected_route") or "").strip())
PY
)"
  resolved_exec_q="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("resolved_execution_query") or "").strip())
PY
)"
  [[ "${selected_route}" == "EVIDENCE" ]] || die "expected EVIDENCE route for query: ${query}; got: ${selected_route}"
  if printf '%s\n' "${resolved_exec_q}" | grep -Eqi '^what are the latest news and developments about '; then
    die "AI query drifted into wrapped news form: ${resolved_exec_q}"
  fi
  if printf '%s\n' "${resolved_exec_q}" | grep -Eqi '^what are the latest news and developments in '; then
    die "AI query drifted into generic news rewrite: ${resolved_exec_q}"
  fi
}

assert_non_ai_query_stays_news(){
  local query="$1" mapped_json selected_route resolved_exec_q
  mapped_json="$(python3 "${MAPPER}" --plan-json "$(python3 "${CLASSIFIER}" "${query}")" --question "${query}" --surface cli --route-control-mode AUTO)"
  selected_route="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("selected_route") or "").strip())
PY
)"
  resolved_exec_q="$(python3 - "${mapped_json}" <<'PY'
import json, sys
payload=json.loads(sys.argv[1])
print(((payload.get("route_manifest") or {}).get("resolved_execution_query") or "").strip())
PY
)"
  [[ "${selected_route}" == "NEWS" ]] || die "expected NEWS route for non-AI developments query: ${query}; got: ${selected_route}"
  printf '%s\n' "${resolved_exec_q}" | grep -Eqi 'latest news and developments' \
    || die "expected NEWS rewrite for non-AI query; got: ${resolved_exec_q}"
}

assert_ai_query_stays_evidence "What are the latest genai developments this past month?"
assert_ai_query_stays_evidence "What are the latest llm developments this past month?"
assert_ai_query_stays_evidence "What are the latest foundation model developments this past month?"
assert_ai_query_stays_evidence "What are the latest ai policy updates this past month?"

assert_non_ai_query_stays_news "What are the latest developments in agriculture this past month?"
assert_non_ai_query_stays_news "What are the latest developments in Yemen this past month?"
ok "adjacent AI recency prompts stay EVIDENCE and non-AI developments prompts remain NEWS"

echo "PASS: test_plan_to_pipeline_ai_adjacent_queries_preserve_scope"
