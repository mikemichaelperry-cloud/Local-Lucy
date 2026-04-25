#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing classifier"
[[ -f "${MAPPER}" ]] || die "missing mapper"

json_field(){
  python3 - "$1" "$2" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
value = obj
for part in sys.argv[2].split("."):
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print("")
else:
    print(str(value))
PY
}

run_mapper(){
  local prompt="$1" plan
  plan="$("${CLASSIFIER}" "${prompt}")"
  python3 "${MAPPER}" --plan-json "${plan}" --question "${prompt}" --route-prefix "" --surface "cli" --route-control-mode "AUTO"
}

state_root="$(mktemp -d)"
trap 'rm -rf "${state_root}"' EXIT
recorded_at="$(python3 - <<'PY'
import time
print(f"{time.time():.3f}")
PY
)"
mkdir -p "${state_root}/state/namespaces/alpha"
cat > "${state_root}/state/namespaces/alpha/semantic_interpreter_backend.json" <<EOF
{"status":"unavailable","recorded_at":${recorded_at},"url":"http://127.0.0.1:9/api/generate","model":"local-lucy"}
EOF

prompt="What was the purpose of the Antikythera mechanism?"
alpha_out="$(
  LUCY_ROOT="${state_root}" \
  LUCY_SHARED_STATE_NAMESPACE="alpha" \
  LUCY_SEMANTIC_INTERPRETER_FAILURE_TTL_S=300 \
  LUCY_OLLAMA_API_URL="http://127.0.0.1:9/api/generate" \
  run_mapper "${prompt}"
)"
[[ "$(json_field "${alpha_out}" semantic_interpreter_result_status)" == "backend_unavailable_cached" ]] || die "expected alpha namespace to reuse cached outage"
[[ "$(json_field "${alpha_out}" semantic_interpreter_use_reason)" == "backend_unavailable_cached" ]] || die "expected alpha namespace cached outage use reason"
ok "semantic backend outage cache is honored inside the same namespace"

beta_out="$(
  LUCY_ROOT="${state_root}" \
  LUCY_SHARED_STATE_NAMESPACE="beta" \
  LUCY_SEMANTIC_INTERPRETER_FAILURE_TTL_S=300 \
  LUCY_OLLAMA_API_URL="http://127.0.0.1:9/api/generate" \
  run_mapper "${prompt}"
)"
[[ "$(json_field "${beta_out}" semantic_interpreter_result_status)" == "model_unavailable" ]] || die "expected beta namespace to attempt the backend independently"
[[ "$(json_field "${beta_out}" semantic_interpreter_invocation_attempted)" == "true" ]] || die "expected beta namespace invocation attempt"
[[ -f "${state_root}/state/namespaces/beta/semantic_interpreter_backend.json" ]] || die "expected beta namespace to write its own outage cache"
[[ -f "${state_root}/state/namespaces/alpha/semantic_interpreter_backend.json" ]] || die "expected alpha namespace outage cache to remain intact"
ok "semantic backend outage cache does not leak across namespaces"

echo "PASS: test_semantic_interpreter_backend_cache_scope"
