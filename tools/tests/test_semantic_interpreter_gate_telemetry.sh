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

url_out="$(run_mapper "https://reuters.com/")"
[[ "$(json_field "${url_out}" semantic_interpreter_fired)" == "false" ]] || die "expected URL prompt to skip semantic interpreter"
[[ "$(json_field "${url_out}" semantic_interpreter_gate_reason)" == "strong_high_stakes_deterministic" ]] || die "expected URL gate reason"
[[ "$(json_field "${url_out}" semantic_interpreter_invocation_attempted)" == "false" ]] || die "expected no semantic invocation for URL prompt"
[[ "$(json_field "${url_out}" semantic_interpreter_result_status)" == "skipped" ]] || die "expected skipped semantic status for URL prompt"
ok "URL prompt exposes deterministic semantic skip telemetry"

news_out="$(run_mapper "What are the latest world headlines?")"
[[ "$(json_field "${news_out}" semantic_interpreter_fired)" == "false" ]] || die "expected strong news prompt to skip semantic interpreter"
[[ "$(json_field "${news_out}" semantic_interpreter_gate_reason)" == "strong_news_deterministic" ]] || die "expected news gate reason"
[[ "$(json_field "${news_out}" semantic_interpreter_result_status)" == "skipped" ]] || die "expected skipped semantic status for strong news prompt"
ok "strong news prompt exposes deterministic semantic skip telemetry"

fx_out="$(run_mapper "What is the current USD to ILS exchange rate?")"
[[ "$(json_field "${fx_out}" semantic_interpreter_fired)" == "false" ]] || die "expected strong current-fact prompt to skip semantic interpreter"
[[ "$(json_field "${fx_out}" semantic_interpreter_gate_reason)" == "strong_current_fact_deterministic" ]] || die "expected current-fact gate reason"
[[ "$(json_field "${fx_out}" semantic_interpreter_invocation_attempted)" == "false" ]] || die "expected no semantic invocation for current-fact prompt"
[[ "$(json_field "${fx_out}" semantic_interpreter_result_status)" == "skipped" ]] || die "expected skipped semantic status for current-fact prompt"
ok "strong non-news current-fact prompt exposes deterministic semantic skip telemetry"

bearing_out="$(run_mapper "Explain what a bearing is")"
[[ "$(json_field "${bearing_out}" semantic_interpreter_fired)" == "false" ]] || die "expected short local explanation prompt to skip semantic interpreter"
[[ "$(json_field "${bearing_out}" semantic_interpreter_gate_reason)" == "deterministic_sufficient" ]] || die "expected deterministic_sufficient gate reason"
[[ "$(json_field "${bearing_out}" semantic_interpreter_invocation_attempted)" == "false" ]] || die "expected no semantic invocation for short local explanation"
[[ "$(json_field "${bearing_out}" semantic_interpreter_result_status)" == "skipped" ]] || die "expected skipped semantic status for short local explanation"
ok "short local explanation prompt avoids semantic interpreter overhead"

fixture='{"inferred_domain":"general","inferred_intent_family":"local_knowledge","normalized_candidates":["Antikythera mechanism purpose"],"retrieval_candidates":["What was the purpose of the Antikythera mechanism?"],"ambiguity_flag":false,"confidence":0.91,"provenance_notes":["obscure factual phrasing"]}'
fixture_out="$(
  LUCY_SEMANTIC_INTERPRETER_INLINE_JSON="${fixture}" \
  run_mapper "What was the purpose of the Antikythera mechanism?"
)"
[[ "$(json_field "${fixture_out}" semantic_interpreter_fired)" == "true" ]] || die "expected fixture-backed semantic invocation"
[[ "$(json_field "${fixture_out}" semantic_interpreter_gate_reason)" == "weak_general_local" ]] || die "expected weak_general_local gate reason"
[[ "$(json_field "${fixture_out}" semantic_interpreter_invocation_attempted)" == "false" ]] || die "expected fixture path to avoid model call"
[[ "$(json_field "${fixture_out}" semantic_interpreter_result_status)" == "fixture_payload" ]] || die "expected fixture_payload semantic status"
ok "weak general local prompt exposes semantic gate-open telemetry"

state_root="$(mktemp -d)"
trap 'rm -rf "${state_root}"' EXIT
recorded_at="$(python3 - <<'PY'
import time
print(f"{time.time():.3f}")
PY
)"
mkdir -p "${state_root}/state"
cat > "${state_root}/state/semantic_interpreter_backend.json" <<EOF
{"status":"unavailable","recorded_at":${recorded_at},"url":"http://127.0.0.1:11434/api/generate","model":"local-lucy"}
EOF
cached_out="$(
  LUCY_ROOT="${state_root}" \
  LUCY_SEMANTIC_INTERPRETER_FAILURE_TTL_S=300 \
  run_mapper "What was the purpose of the Antikythera mechanism?"
)"
[[ "$(json_field "${cached_out}" semantic_interpreter_fired)" == "false" ]] || die "expected cached backend outage to skip semantic interpreter output"
[[ "$(json_field "${cached_out}" semantic_interpreter_gate_reason)" == "weak_general_local" ]] || die "expected weak_general_local gate reason for cached outage case"
[[ "$(json_field "${cached_out}" semantic_interpreter_invocation_attempted)" == "false" ]] || die "expected cached backend outage to suppress invocation"
[[ "$(json_field "${cached_out}" semantic_interpreter_result_status)" == "backend_unavailable_cached" ]] || die "expected cached backend outage status"
[[ "$(json_field "${cached_out}" semantic_interpreter_use_reason)" == "backend_unavailable_cached" ]] || die "expected cached backend outage use reason"
ok "cached backend outage suppresses repeated semantic model attempts"

echo "PASS: test_semantic_interpreter_gate_telemetry"
