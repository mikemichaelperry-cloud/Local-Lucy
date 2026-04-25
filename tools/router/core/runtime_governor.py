#!/usr/bin/env python3
"""Frozen governor execution contract.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and semantic-interpreter authority
must not be expanded through contract fallback.

AUGMENTED is a governed route in the live AUTO path. It remains distinct from
EVIDENCE/NEWS and is limited to unverified-context execution tools.
"""

from typing import Any, Dict, List, Optional

from local_policy import match_local_response_id


CONTRACT_VERSION = "v1"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).strip().lower() in {"1", "true", "yes", "on"}


def _float(value: Any) -> float:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return 0.0


def _first_defined(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _legacy_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    legacy = plan.get("legacy_plan")
    if isinstance(legacy, dict):
        return dict(legacy)
    return {
        "intent": plan.get("intent"),
        "category": plan.get("category"),
        "needs_web": plan.get("needs_web"),
        "needs_citations": plan.get("needs_citations"),
        "min_sources": plan.get("min_sources"),
        "output_mode": plan.get("output_mode"),
        "prefer_domains": plan.get("prefer_domains"),
        "allow_domains_file": plan.get("allow_domains_file"),
        "region_filter": plan.get("region_filter"),
        "one_clarifying_question": plan.get("one_clarifying_question"),
        "confidence_policy": plan.get("confidence_policy"),
    }


def _normalize_route(value: Any) -> str:
    route = _text(value).strip().upper()
    if route in {"LOCAL", "NEWS", "EVIDENCE", "AUGMENTED", "CLARIFY"}:
        return route
    route_lower = route.lower()
    if route_lower in {"local", "news", "evidence", "augmented", "clarify"}:
        return route_lower.upper()
    return ""


def _manifest_route(manifest: Dict[str, Any]) -> str:
    route = _normalize_route(manifest.get("selected_route"))
    if not route:
        raise ValueError("route_manifest.selected_route is required")
    return route


def _intent_name(plan: Dict[str, Any], effective_plan: Dict[str, Any]) -> str:
    intent_class = _text(plan.get("intent_class")).strip()
    if intent_class:
        return intent_class
    legacy_intent = _text(_legacy_plan(plan).get("intent")).strip()
    if legacy_intent:
        return legacy_intent
    effective_intent = _text(effective_plan.get("intent")).strip()
    if effective_intent:
        return effective_intent
    return "unknown"


def _subcategory(plan: Dict[str, Any], effective_plan: Dict[str, Any]) -> str:
    return (
        _text(plan.get("subcategory")).strip().lower()
        or _text(effective_plan.get("category")).strip().lower()
        or _text(_legacy_plan(plan).get("category")).strip().lower()
    )


def _fallback_policy(
    intent: str,
    route: str,
    subcategory: str,
    requires_sources: bool,
    requires_clarification: bool,
) -> str:
    intent_lower = intent.strip().lower()
    if requires_clarification or route == "CLARIFY":
        return "none"
    if subcategory == "travel_advisory":
        return "risk_first"
    if route in {"NEWS", "EVIDENCE"} or requires_sources:
        return "evidence_required"
    if intent_lower in {"identity_personal", "conversational", "local_knowledge", "technical_explanation"}:
        return "local_safe"
    if intent_lower.startswith("identity_"):
        return "local_safe"
    if route == "AUGMENTED":
        return "augmented_selected"
    return "local_safe"


def _allowed_tools(route: str, requires_clarification: bool, requires_sources: bool) -> List[str]:
    if requires_clarification or route == "CLARIFY":
        return []
    if route == "LOCAL":
        tools = ["local_answer"]
        if not requires_sources:
            tools.insert(0, "local_worker")
        return tools
    if route == "AUGMENTED":
        # AUGMENTED stays explicitly bounded to background-context tooling.
        return ["unverified_context_provider", "local_worker", "local_answer"]
    if route == "NEWS":
        return ["news_fetch", "validated_extract"]
    if route == "EVIDENCE":
        return ["web_fetch", "validated_extract"]
    return []


def _audit_tags(
    intent: str,
    route: str,
    route_control_mode: str,
    route_prefix: str,
    surface: str,
    route_decision: Dict[str, Any],
    requires_sources: bool,
    requires_clarification: bool,
) -> List[str]:
    tags = [
        f"contract:{CONTRACT_VERSION}",
        f"intent:{intent.strip().lower() or 'unknown'}",
        f"route:{route.strip().lower() or 'unknown'}",
    ]
    mode = _text(route_control_mode).strip().lower()
    if mode:
        tags.append(f"mode:{mode}")
    prefix = _text(route_prefix).strip().lower()
    if prefix:
        tags.append(f"prefix:{prefix}")
    surface_value = _text(surface).strip().lower()
    if surface_value:
        tags.append(f"surface:{surface_value}")
    confidence_band = _text(route_decision.get("confidence_band")).strip().lower()
    if confidence_band:
        tags.append(f"confidence_band:{confidence_band}")
    freshness_requirement = _text(route_decision.get("freshness_requirement")).strip().lower()
    if freshness_requirement:
        tags.append(f"freshness:{freshness_requirement}")
    risk_level = _text(route_decision.get("risk_level")).strip().lower()
    if risk_level:
        tags.append(f"risk:{risk_level}")
    source_criticality = _text(route_decision.get("source_criticality")).strip().lower()
    if source_criticality:
        tags.append(f"source_criticality:{source_criticality}")
    offline_action = _text(route_decision.get("offline_action")).strip().lower()
    if offline_action and offline_action != "allow":
        tags.append(f"offline_action:{offline_action}")
    if requires_sources:
        tags.append("requires_sources")
    if requires_clarification:
        tags.append("requires_clarification")
    return tags


def _local_response_id(question: str, intent: str, route: str, requires_sources: bool) -> Optional[str]:
    if route != "LOCAL" or requires_sources:
        return None
    return match_local_response_id(question, intent)


def build_execution_contract(
    plan: Dict[str, Any],
    effective_plan: Dict[str, Any],
    route_decision: Dict[str, Any],
    route_manifest: Optional[Dict[str, Any]] = None,
    question: str = "",
    resolved_question: str = "",
    local_response_text: Optional[str] = None,
    route_control_mode: str = "AUTO",
    route_prefix: str = "",
    surface: str = "cli",
) -> Dict[str, Any]:
    legacy_plan = _legacy_plan(plan)
    plan_requires_sources = _bool(_first_defined(effective_plan.get("needs_web"), legacy_plan.get("needs_web")))
    manifest = route_manifest if isinstance(route_manifest, dict) else {}
    route = _manifest_route(manifest)

    requires_clarification = _bool(manifest.get("clarify_required")) or route == "CLARIFY"
    clarification_question = (
        _text(route_decision.get("clarification_question")).strip()
        or _text(plan.get("clarification_question")).strip()
        or _text(effective_plan.get("one_clarifying_question")).strip()
        or _text(legacy_plan.get("one_clarifying_question")).strip()
    )
    intent = _intent_name(plan, effective_plan)
    confidence = _float(plan.get("confidence"))
    if confidence <= 0.0:
        confidence = _float(route_decision.get("policy_confidence"))
    requires_sources = plan_requires_sources
    if requires_clarification or route == "CLARIFY":
        requires_sources = False
    elif route in {"NEWS", "EVIDENCE"}:
        requires_sources = True
    subcategory = _subcategory(plan, effective_plan)
    fallback_policy = _fallback_policy(
        intent=intent,
        route=route,
        subcategory=subcategory,
        requires_sources=requires_sources,
        requires_clarification=requires_clarification,
    )
    local_response_id = _local_response_id(
        question=question,
        intent=intent,
        route=route,
        requires_sources=requires_sources,
    )
    audit_tags = _audit_tags(
        intent=intent,
        route=route,
        route_control_mode=route_control_mode,
        route_prefix=route_prefix,
        surface=surface,
        route_decision=route_decision,
        requires_sources=requires_sources,
        requires_clarification=requires_clarification,
    )
    if local_response_id:
        audit_tags.append(f"local_response:{local_response_id}")

    contract = {
        "intent": intent,
        "confidence": confidence,
        "route": route,
        "allowed_tools": _allowed_tools(route, requires_clarification, requires_sources),
        "requires_sources": requires_sources,
        "requires_clarification": requires_clarification,
        "clarification_question": clarification_question or None,
        "fallback_policy": fallback_policy,
        "audit_tags": audit_tags,
        "contract_version": CONTRACT_VERSION,
        "local_response_id": local_response_id,
        "local_response_text": local_response_text,
        "resolved_question": resolved_question or None,
    }
    return contract
