#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -f "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"

json_field() {
  local json="$1"
  local key="$2"
  python3 - "$json" "$key" <<'PY'
import json, sys

payload = json.loads(sys.argv[1])
cur = payload
for part in sys.argv[2].split("."):
    if not isinstance(cur, dict) or part not in cur:
        cur = None
        break
    cur = cur.get(part)
value = cur
if isinstance(value, bool):
    print("true" if value else "false")
elif isinstance(value, list):
    print(",".join(str(item) for item in value))
else:
    print("" if value is None else str(value))
PY
}

run_plan() {
  local plan="$1"
  local question="$2"
  python3 "${MAPPER}" --plan-json "${plan}" --question "${question}"
}

assert_manifest_state() {
  local json="$1"
  local expected_route="$2"
  local expected_mode="$3"
  local expected_reason="$4"
  [[ "$(json_field "${json}" "route_manifest.selected_route")" == "${expected_route}" ]] || die "expected manifest route ${expected_route}"
  [[ "$(json_field "${json}" "route_manifest.evidence_mode")" == "${expected_mode}" ]] || die "expected evidence_mode=${expected_mode}"
  [[ "$(json_field "${json}" "route_manifest.evidence_mode_reason")" == "${expected_reason}" ]] || die "expected evidence_mode_reason=${expected_reason}"
}

assert_manifest_mode_only() {
  local json="$1"
  local expected_mode="$2"
  local expected_reason="$3"
  [[ "$(json_field "${json}" "route_manifest.evidence_mode")" == "${expected_mode}" ]] || die "expected evidence_mode=${expected_mode}"
  [[ "$(json_field "${json}" "route_manifest.evidence_mode_reason")" == "${expected_reason}" ]] || die "expected evidence_mode_reason=${expected_reason}"
}

plan_light='{
  "intent": "WEB_FACT",
  "category": "current_fact",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["EVIDENCE", "NEWS"],
  "routing_signals": {}
}'

plan_source='{
  "intent": "WEB_FACT",
  "category": "current_fact",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["EVIDENCE"],
  "routing_signals": {"source_request": true}
}'

plan_geo='{
  "intent": "WEB_NEWS",
  "category": "news_world",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["NEWS", "EVIDENCE"],
  "routing_signals": {"geopolitics": true, "news": true}
}'

plan_news_light='{
  "intent": "WEB_NEWS",
  "category": "news_world",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["NEWS", "EVIDENCE"],
  "routing_signals": {"news": true, "temporal": true}
}'

plan_medical='{
  "intent": "MEDICAL_INFO",
  "category": "medical",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "VALIDATED",
  "confidence": 0.92,
  "confidence_policy": "high_stakes",
  "candidate_routes": ["EVIDENCE"],
  "routing_signals": {"medical_context": true}
}'

plan_conflict_history='{
  "intent": "WEB_FACT",
  "category": "current_fact",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["EVIDENCE"],
  "routing_signals": {"conflict": true}
}'

plan_conflict_live='{
  "intent": "WEB_NEWS",
  "category": "news_world",
  "needs_web": true,
  "needs_citations": true,
  "min_sources": 2,
  "output_mode": "LIGHT_EVIDENCE",
  "confidence": 0.85,
  "confidence_policy": "normal",
  "candidate_routes": ["EVIDENCE", "NEWS"],
  "routing_signals": {"conflict": true, "temporal": true}
}'

plan_local='{
  "intent": "LOCAL_KNOWLEDGE",
  "category": "general",
  "needs_web": false,
  "needs_citations": false,
  "min_sources": 1,
  "output_mode": "CHAT",
  "confidence": 0.75,
  "confidence_policy": "normal",
  "candidate_routes": ["LOCAL"],
  "routing_signals": {}
}'

general_json="$(run_plan "${plan_light}" "General current info?")"
assert_manifest_state "${general_json}" "EVIDENCE" "LIGHT" "default_light"
ok "default evidence route selects LIGHT evidence_mode"

source_json="$(run_plan "${plan_source}" "Compare the sources and cite them.")"
assert_manifest_state "${source_json}" "EVIDENCE" "FULL" "explicit_source_request"
ok "explicit source request upgrades to FULL evidence_mode"

news_light_json="$(run_plan "${plan_news_light}" "What are the latest space headlines?")"
assert_manifest_state "${news_light_json}" "NEWS" "LIGHT" "default_light"
ok "ordinary NEWS prompt stays on LIGHT evidence_mode"

geo_json="$(run_plan "${plan_geo}" "Is there a new Iran-Israel development?")"
assert_manifest_state "${geo_json}" "NEWS" "FULL" "policy_geopolitics_high_risk"
ok "geopolitical live prompt sets FULL evidence_mode"

medical_json="$(run_plan "${plan_medical}" "Is Lipitor safe with grapefruit?")"
assert_manifest_state "${medical_json}" "EVIDENCE" "FULL" "policy_medical_high_risk"
ok "high-risk medical prompt sets FULL evidence_mode"

conflict_history_json="$(run_plan "${plan_conflict_history}" "Give a brief history of the conflict.")"
assert_manifest_state "${conflict_history_json}" "EVIDENCE" "LIGHT" "default_light"
ok "bare conflict signal no longer escalates to FULL evidence_mode"

conflict_live_json="$(run_plan "${plan_conflict_live}" "What are the latest ceasefire developments?")"
assert_manifest_state "${conflict_live_json}" "NEWS" "FULL" "policy_conflict_live"
ok "live conflict prompt sets FULL evidence_mode"

local_json="$(run_plan "${plan_local}" "Tell me about vacuum tubes.")"
assert_manifest_mode_only "${local_json}" "" "not_evidence_route"
ok "non-evidence routes store empty evidence_mode"

echo "PASS: test_router_evidence_mode_selection"
