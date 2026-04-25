#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/../.." && pwd)"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"

ok(){ echo "OK: $*"; }
die(){ echo "FAIL: $*" >&2; exit 1; }

[[ -x "${CLASSIFIER}" ]] || die "missing executable: ${CLASSIFIER}"
[[ -f "${MAPPER}" ]] || die "missing mapper: ${MAPPER}"

run_case() {
  local prompt="$1"
  local plan
  plan="$("${CLASSIFIER}" "${prompt}")"
  python3 "${MAPPER}" --plan-json "${plan}" --question "${prompt}"
}

assert_contract_schema() {
  local label="$1"
  local json="$2"
  python3 - "$label" "$json" <<'PY'
import json
import sys

label = sys.argv[1]
payload = json.loads(sys.argv[2])

expected_effective_plan_keys = [
    "allow_domains_file",
    "category",
    "confidence_policy",
    "intent",
    "min_sources",
    "needs_citations",
    "needs_web",
    "one_clarifying_question",
    "output_mode",
    "prefer_domains",
    "region_filter",
]
expected_route_decision_keys = [
    "clarification_question",
    "confidence_band",
    "force_mode",
    "freshness_requirement",
    "mixed_intent",
    "needs_clarification",
    "offline_action",
    "operator_override",
    "policy_actual_route",
    "policy_base_recommended_route",
    "policy_confidence",
    "policy_confidence_threshold",
    "policy_recommended_route",
    "precedence_version",
    "reason_codes",
    "reason_codes_csv",
    "risk_level",
    "route_mode",
    "signal_flags",
    "source_criticality",
    "surface",
    "winning_signal",
]
expected_route_manifest_keys = [
    "allowed_routes",
    "authority_basis",
    "clarify_required",
    "context_referent_confidence",
    "context_resolution_used",
    "evidence_mode",
    "evidence_mode_reason",
    "forbidden_routes",
    "manifest_version",
    "original_query",
    "precedence_version",
    "resolved_execution_query",
    "selected_route",
    "signals",
    "winning_signal",
]
expected_execution_contract_keys = [
    "allowed_tools",
    "audit_tags",
    "clarification_question",
    "confidence",
    "contract_version",
    "fallback_policy",
    "intent",
    "local_response_id",
    "local_response_text",
    "requires_clarification",
    "requires_sources",
    "resolved_question",
    "route",
]

effective_plan = payload.get("effective_plan")
route_decision = payload.get("route_decision")
route_manifest = payload.get("route_manifest")
execution_contract = payload.get("execution_contract")

if not isinstance(effective_plan, dict):
    raise SystemExit(f"{label}: effective_plan is not an object")
if not isinstance(route_decision, dict):
    raise SystemExit(f"{label}: route_decision is not an object")
if not isinstance(route_manifest, dict):
    raise SystemExit(f"{label}: route_manifest is not an object")
if not isinstance(execution_contract, dict):
    raise SystemExit(f"{label}: execution_contract is not an object")

effective_plan_keys = sorted(effective_plan.keys())
route_decision_keys = sorted(route_decision.keys())
route_manifest_keys = sorted(route_manifest.keys())
execution_contract_keys = sorted(execution_contract.keys())

if effective_plan_keys != expected_effective_plan_keys:
    raise SystemExit(
        f"{label}: effective_plan keys drifted: {effective_plan_keys} != {expected_effective_plan_keys}"
    )
if route_decision_keys != expected_route_decision_keys:
    raise SystemExit(
        f"{label}: route_decision keys drifted: {route_decision_keys} != {expected_route_decision_keys}"
    )
if route_manifest_keys != expected_route_manifest_keys:
    raise SystemExit(
        f"{label}: route_manifest keys drifted: {route_manifest_keys} != {expected_route_manifest_keys}"
    )
if execution_contract_keys != expected_execution_contract_keys:
    raise SystemExit(
        f"{label}: execution_contract keys drifted: {execution_contract_keys} != {expected_execution_contract_keys}"
    )

type_checks = [
    (effective_plan.get("intent"), str, "effective_plan.intent"),
    (effective_plan.get("category"), str, "effective_plan.category"),
    (effective_plan.get("needs_web"), bool, "effective_plan.needs_web"),
    (effective_plan.get("needs_citations"), bool, "effective_plan.needs_citations"),
    (effective_plan.get("min_sources"), int, "effective_plan.min_sources"),
    (effective_plan.get("output_mode"), str, "effective_plan.output_mode"),
    (effective_plan.get("prefer_domains"), list, "effective_plan.prefer_domains"),
    (effective_plan.get("confidence_policy"), str, "effective_plan.confidence_policy"),
    (route_decision.get("route_mode"), str, "route_decision.route_mode"),
    (route_decision.get("force_mode"), str, "route_decision.force_mode"),
    (route_decision.get("offline_action"), str, "route_decision.offline_action"),
    (route_decision.get("needs_clarification"), bool, "route_decision.needs_clarification"),
    (route_decision.get("mixed_intent"), bool, "route_decision.mixed_intent"),
    (route_decision.get("reason_codes"), list, "route_decision.reason_codes"),
    (route_decision.get("reason_codes_csv"), str, "route_decision.reason_codes_csv"),
    (route_decision.get("signal_flags"), dict, "route_decision.signal_flags"),
    (route_decision.get("surface"), str, "route_decision.surface"),
    (route_decision.get("precedence_version"), str, "route_decision.precedence_version"),
    (route_decision.get("winning_signal"), str, "route_decision.winning_signal"),
    (route_manifest.get("manifest_version"), str, "route_manifest.manifest_version"),
    (route_manifest.get("precedence_version"), str, "route_manifest.precedence_version"),
    (route_manifest.get("original_query"), str, "route_manifest.original_query"),
    (route_manifest.get("resolved_execution_query"), str, "route_manifest.resolved_execution_query"),
    (route_manifest.get("selected_route"), str, "route_manifest.selected_route"),
    (route_manifest.get("allowed_routes"), list, "route_manifest.allowed_routes"),
    (route_manifest.get("forbidden_routes"), list, "route_manifest.forbidden_routes"),
    (route_manifest.get("winning_signal"), str, "route_manifest.winning_signal"),
    (route_manifest.get("clarify_required"), bool, "route_manifest.clarify_required"),
    (route_manifest.get("authority_basis"), str, "route_manifest.authority_basis"),
    (route_manifest.get("signals"), dict, "route_manifest.signals"),
    (route_manifest.get("context_resolution_used"), bool, "route_manifest.context_resolution_used"),
    (route_manifest.get("context_referent_confidence"), str, "route_manifest.context_referent_confidence"),
    (route_manifest.get("evidence_mode"), str, "route_manifest.evidence_mode"),
    (route_manifest.get("evidence_mode_reason"), str, "route_manifest.evidence_mode_reason"),
    (execution_contract.get("intent"), str, "execution_contract.intent"),
    (execution_contract.get("confidence"), (int, float), "execution_contract.confidence"),
    (execution_contract.get("route"), str, "execution_contract.route"),
    (execution_contract.get("allowed_tools"), list, "execution_contract.allowed_tools"),
    (execution_contract.get("requires_sources"), bool, "execution_contract.requires_sources"),
    (execution_contract.get("requires_clarification"), bool, "execution_contract.requires_clarification"),
    (execution_contract.get("fallback_policy"), str, "execution_contract.fallback_policy"),
    (execution_contract.get("audit_tags"), list, "execution_contract.audit_tags"),
    (execution_contract.get("contract_version"), str, "execution_contract.contract_version"),
]

for value, expected_type, field in type_checks:
    if not isinstance(value, expected_type):
        type_name = getattr(expected_type, "__name__", str(expected_type))
        raise SystemExit(f"{label}: {field} type drifted: {type(value).__name__} != {type_name}")

nullable_fields = [
    (effective_plan.get("allow_domains_file"), "effective_plan.allow_domains_file"),
    (effective_plan.get("region_filter"), "effective_plan.region_filter"),
    (effective_plan.get("one_clarifying_question"), "effective_plan.one_clarifying_question"),
    (route_decision.get("clarification_question"), "route_decision.clarification_question"),
    (execution_contract.get("clarification_question"), "execution_contract.clarification_question"),
    (execution_contract.get("local_response_id"), "execution_contract.local_response_id"),
    (execution_contract.get("local_response_text"), "execution_contract.local_response_text"),
    (execution_contract.get("resolved_question"), "execution_contract.resolved_question"),
]
for value, field in nullable_fields:
    if value is not None and not isinstance(value, str):
        raise SystemExit(f"{label}: {field} type drifted: {type(value).__name__} != str|null")

numeric_fields = [
    (route_decision.get("policy_confidence"), "route_decision.policy_confidence"),
    (route_decision.get("policy_confidence_threshold"), "route_decision.policy_confidence_threshold"),
]
for value, field in numeric_fields:
    if not isinstance(value, (int, float)):
        raise SystemExit(f"{label}: {field} type drifted: {type(value).__name__} != number")

if route_manifest.get("selected_route") != execution_contract.get("route"):
    raise SystemExit(f"{label}: route_manifest.selected_route must match execution_contract.route")
if route_manifest.get("selected_route") not in route_manifest.get("allowed_routes", []):
    raise SystemExit(f"{label}: selected route missing from allowed_routes")
if route_manifest.get("selected_route") in route_manifest.get("forbidden_routes", []):
    raise SystemExit(f"{label}: selected route unexpectedly forbidden")

signals = route_manifest.get("signals") or {}
for field in (
    "temporal",
    "news",
    "conflict",
    "geopolitics",
    "israel_region_live",
    "source_request",
    "url",
    "ambiguity_followup",
    "medical_context",
    "current_product",
):
    if not isinstance(signals.get(field), bool):
        raise SystemExit(f"{label}: route_manifest.signals.{field} must be a bool")
PY
}

local_json="$(run_case "explain ohm's law")"
assert_contract_schema "technical_local" "${local_json}"
ok "technical_local nested contract schema matches exact structure"

clarify_json="$(run_case "tell me about bali")"
assert_contract_schema "mixed_clarify" "${clarify_json}"
ok "mixed_clarify nested contract schema matches exact structure"

echo "PASS: test_router_contract_schema"
