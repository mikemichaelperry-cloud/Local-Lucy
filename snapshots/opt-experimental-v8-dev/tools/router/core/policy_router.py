#!/usr/bin/env python3
from typing import Dict

from policy_engine import evaluate_policy
from routing_signals import ROUTING_PRECEDENCE_VERSION


def _s(value) -> str:
    if value is None:
        return ""
    return str(value)


def _legacy_plan(plan: Dict) -> Dict:
    legacy = plan.get("legacy_plan")
    if isinstance(legacy, dict):
        merged = dict(legacy)
        if "routing_signals" not in merged:
            merged["routing_signals"] = plan.get("routing_signals")
        merged["intent_class"] = plan.get("intent_class")
        merged["classifier_confidence"] = plan.get("confidence")
        merged["has_proven_local_capability"] = plan.get("has_proven_local_capability")
        merged["local_response_id_hint"] = plan.get("local_response_id_hint")
        return merged
    return {
        "intent": plan.get("intent"),
        "category": plan.get("category"),
        "needs_web": plan.get("needs_web"),
        "needs_citations": plan.get("needs_citations"),
        "min_sources": plan.get("min_sources"),
        "output_mode": plan.get("output_mode"),
        "one_clarifying_question": plan.get("one_clarifying_question"),
        "routing_signals": plan.get("routing_signals"),
        "intent_class": plan.get("intent_class"),
        "classifier_confidence": plan.get("confidence"),
        "has_proven_local_capability": plan.get("has_proven_local_capability"),
        "local_response_id_hint": plan.get("local_response_id_hint"),
    }


def route_intent(
    plan: Dict,
    question: str,
    route_prefix: str,
    route_control_mode: str,
    confidence_threshold: float,
    surface: str,
) -> Dict:
    intent_class = _s(plan.get("intent_class")).strip().lower()
    confidence = float(plan.get("confidence") or 0.0)
    needs_clarification = bool(plan.get("needs_clarification"))
    clarification_question = _s(plan.get("clarification_question")).strip()
    mixed_intent = bool(plan.get("mixed_intent"))
    signal_flags = dict(plan.get("routing_signals") or {})

    if route_prefix not in {"local", "news", "evidence"}:
        if needs_clarification or (intent_class == "mixed" and confidence < max(confidence_threshold, 0.7)):
            if not clarification_question:
                clarification_question = "Do you want general information, current news, or travel safety information?"
            return {
                "route_mode": "CLARIFY",
                "force_mode": "CLARIFY",
                "offline_action": "allow",
                "needs_clarification": True,
                "clarification_question": clarification_question,
                "policy_recommended_route": "clarify",
                "policy_actual_route": "clarify",
                "policy_base_recommended_route": "clarify",
                "policy_confidence": round(confidence, 3),
                "policy_confidence_threshold": round(confidence_threshold, 3),
                "confidence_band": "low" if confidence < confidence_threshold else "medium",
                "freshness_requirement": "high" if plan.get("needs_current_info") else "low",
                "risk_level": "high" if intent_class in {"evidence_check", "current_fact"} else "low",
                "source_criticality": "high" if intent_class in {"evidence_check", "current_fact"} else "low",
                "operator_override": "none",
                "reason_codes": ["needs_clarification", f"intent_class:{intent_class or 'unknown'}"],
                "reason_codes_csv": f"needs_clarification,intent_class:{intent_class or 'unknown'}",
                "surface": _s(surface).strip().lower() or "cli",
                "mixed_intent": mixed_intent,
                "winning_signal": "ambiguity",
                "precedence_version": ROUTING_PRECEDENCE_VERSION,
                "signal_flags": signal_flags,
            }

    policy = evaluate_policy(
        plan=_legacy_plan(plan),
        question=question,
        route_prefix=route_prefix,
        route_control_mode=route_control_mode,
        confidence_threshold=confidence_threshold,
        surface=surface,
    )
    signal_flags.update(policy.get("signal_flags") or {})
    route_mode = _s(policy.get("route")).strip().upper()
    confidence_band = "high"
    if float(policy.get("policy_confidence") or 0.0) < confidence_threshold:
        confidence_band = "low"
    elif float(policy.get("policy_confidence") or 0.0) < 0.82:
        confidence_band = "medium"

    return {
        "route_mode": route_mode,
        "force_mode": route_mode,
        "offline_action": _s(policy.get("offline_action") or "allow"),
        "needs_clarification": False,
        "clarification_question": clarification_question or None,
        "policy_recommended_route": _s(policy.get("policy_recommended_route")),
        "policy_actual_route": _s(policy.get("route")),
        "policy_base_recommended_route": _s(policy.get("base_recommended_route")),
        "policy_confidence": policy.get("policy_confidence"),
        "policy_confidence_threshold": policy.get("policy_confidence_threshold"),
        "confidence_band": confidence_band,
        "freshness_requirement": _s(policy.get("freshness_requirement")),
        "risk_level": _s(policy.get("risk_level")),
        "source_criticality": _s(policy.get("source_criticality")),
        "intent_family": _s(policy.get("intent_family")),
        "augmented_family": _s(policy.get("augmented_family")),
        "operator_override": _s(policy.get("operator_override")),
        "reason_codes": policy.get("reason_codes") or [],
        "reason_codes_csv": _s(policy.get("reason_codes_csv")),
        "surface": _s(policy.get("surface") or surface),
        "mixed_intent": mixed_intent,
        "winning_signal": _s(policy.get("winning_signal")),
        "precedence_version": _s(policy.get("precedence_version")),
        "signal_flags": signal_flags,
    }
