#!/usr/bin/env python3
"""Frozen routing policy baseline.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries and routing precedence must not be weakened or widened.

AUTO includes a narrow AUGMENTED band for low-risk conceptual prompts where
augmentation is useful but EVIDENCE/NEWS is not required. This is intentionally
limited to explicit background and synthesis/explanation prompt classes.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

THIS_DIR = Path(__file__).resolve().parent
CORE_DIR = THIS_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from local_policy import is_local_policy_query
from routing_signals import (
    ROUTING_PRECEDENCE_LADDER,
    ROUTING_PRECEDENCE_VERSION,
    build_common_signal_flags,
    has_temporal_signal,
    is_probable_culinary_source_misrecognition,
)

LOCAL_INTENTS = {
    "LOCAL_KNOWLEDGE",
    "LOCAL_CHAT",
    "PET_FOOD",
    "IDENTITY_SELF",
    "IDENTITY_USER",
    "IDENTITY_RELATIONSHIP",
}
NEWS_INTENTS = {"WEB_NEWS", "STATUS_UPDATE"}
EVIDENCE_INTENTS = {"WEB_FACT", "WEB_DOC", "PRIMARY_DOC", "SHOPPING_LOCAL", "MEDICAL_INFO"}
AUTO_INTENT_FAMILIES = {"", "self_review", "current_evidence", "background_overview", "synthesis_explanation", "local_answer"}


def _s(v) -> str:
    if v is None:
        return ""
    return str(v)


def _b(v) -> bool:
    if isinstance(v, bool):
        return v
    return _s(v).strip().lower() in {"1", "true", "yes", "on"}


def _bool_map(values) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    if not isinstance(values, dict):
        return out
    for key, value in values.items():
        out[str(key)] = _b(value)
    return out


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _has_temporal_freshness_marker(qn: str) -> bool:
    return has_temporal_signal(qn)


def _is_conceptual_travel_advisory_query(qn: str) -> bool:
    return _has_re(qn, r"\b(explain|what is|what's|whats|define|meaning of|tell me about)\b") and _has_re(
        qn, r"\btravel advisory\b"
    ) and not _has_temporal_freshness_marker(qn)


def _is_augmented_background_query(qn: str) -> bool:
    # Stable factual/background prompts should prefer AUGMENTED over LOCAL when
    # the query is low-risk and does not require live evidence.
    if _has_re(qn, r"^\s*who was\b"):
        return True
    if _has_re(qn, r"\b(overview of|history of|tell me about)\b"):
        return True
    return False


def _is_augmented_synthesis_query(qn: str) -> bool:
    # Explanation/rewrite/comparison prompts benefit from stronger articulation
    # while remaining outside the evidence-required path.
    if _has_re(qn, r"\b(rewrite|rephrase|paraphrase|reword|edit|improve|clarify|compare|contrast|tradeoff|tradeoffs)\b"):
        return True
    if _has_re(qn, r"\b(explain)\b") and _has_re(
        qn,
        r"\b(plain english|plain language|simple terms|engineering intuition|with intuition|with an analogy|with analogy|real world analogy|broader conceptual articulation)\b",
    ):
        return True
    if _has_re(
        qn,
        r"\b(plain english|plain language|simple terms|engineering intuition|with intuition|with an analogy|with analogy|real world analogy|broader conceptual articulation)\b",
    ):
        return True
    return False


def _is_conditional_component_spec_query(qn: str) -> bool:
    if not _has_re(
        qn,
        r"\b(axial load|radial load|thrust load|dynamic load|static load|load rating|allowable load|maximum load|max load|capacity|rating|can it take|can it handle)\b",
    ):
        return False
    if not _has_re(
        qn,
        r"\b(bearing|capacitor|resistor|relay|fuse|connector|transistor|mosfet|igbt|diode|tube|valve|motor|gearbox|pump|seal|spring)\b",
    ):
        return False
    if not (_has_re(qn, r"\b\d{3,5}[a-z]?\b") or _has_re(qn, r"\b(series|spec|specification)\b")):
        return False
    return True


def _is_conditional_technical_capability_query(qn: str) -> bool:
    if not _has_re(
        qn,
        r"\b(capable of|can produce|can deliver|would you consider|suitable for|realistic|practical|enough for)\b",
    ):
        return False
    if not _has_re(
        qn,
        r"\b(tube|valve|amplifier|output stage|audio|class a|class ab|class ab1|class ab2|plate|screen|bias|load line|impedance|transformer)\b",
    ):
        return False
    if not _has_re(
        qn,
        r"\b(watt|watts|rms|power|output|plate dissipation|dissipation|voltage|current|load|impedance)\b",
    ):
        return False
    return True


def _is_augmented_technical_query(qn: str) -> bool:
    if not _has_re(
        qn,
        r"\b(ohm|voltage|current|resistor|circuit|transistor|diode|op-amp|op amp|lm317|electronics|transformer|tube|valve|amplifier|output stage|operating point|plate|screen|anode|cathode|grid|bias|feedback|compensation|stability|phase margin|gain stage|class a|class ab1|load line|impedance)\b",
    ):
        return False
    if not _has_re(
        qn,
        r"\b(recommend|recommended|consider|best|optimum|optimal|why not|tradeoff|tradeoffs|reasonable|choose|use|set)\b",
    ):
        return False
    if not _has_re(qn, r"\b(plate|screen|anode|cathode|grid|bias|class a|class ab1|operating point|load line|impedance|quiescent|feedback|compensation|stability|phase margin)\b"):
        return False
    if _has_re(qn, r"\b(datasheet|manual|pdf|source|sources|citation|citations|cite|url|link)\b"):
        return False
    return True


def _build_auto_intent_profile(
    *,
    plan: Dict,
    qn: str,
    intent: str,
    category: str,
    intent_class: str,
    needs_web: bool,
    risk_level: str,
    source_criticality: str,
    signal_flags: Dict[str, bool],
    route_control_mode: str,
    proven_local_capability: bool,
) -> Dict[str, bool]:
    requires_current_evidence = (
        _is_policy_global_signal(plan, intent, category, signal_flags)
        or _is_explicit_doc_source_signal(intent, category, signal_flags)
        or _is_medical_high_stakes_signal(intent, category, signal_flags)
        or _is_temporal_live_signal(intent, category, signal_flags)
        or _is_current_product_signal(category, signal_flags)
    )
    local_safe_window = (
        route_control_mode == "AUTO"
        and _s(os.environ.get("LUCY_AUGMENTATION_POLICY")).strip().lower() != "disabled"
        and intent in LOCAL_INTENTS
        and not needs_web
        and risk_level == "low"
        and source_criticality == "low"
        and not signal_flags.get("temporal")
        and not signal_flags.get("news")
        and not signal_flags.get("source_request")
        and not signal_flags.get("url")
        and not signal_flags.get("medical_context")
        and not signal_flags.get("current_product_recommendation")
    )
    is_synthesis_request = local_safe_window and intent_class in {"local_knowledge", "technical_explanation"} and (
        _is_augmented_synthesis_query(qn)
        or _is_conditional_component_spec_query(qn)
        or _is_conditional_technical_capability_query(qn)
    )
    is_background_request = local_safe_window and intent_class == "local_knowledge" and _is_augmented_background_query(qn)
    is_local_answer_request = local_safe_window and intent_class == "local_knowledge" and not is_background_request and not is_synthesis_request
    is_unproven_specialized_request = (
        route_control_mode == "AUTO"
        and _s(os.environ.get("LUCY_AUGMENTATION_POLICY")).strip().lower() != "disabled"
        and not proven_local_capability
        and intent in LOCAL_INTENTS
        and not needs_web
        and risk_level == "low"
        and source_criticality == "low"
        and (intent_class == "technical_explanation" or _is_augmented_technical_query(qn))
    )
    return {
        "requires_current_evidence": requires_current_evidence,
        "local_safe_window": local_safe_window,
        "proven_local_capability": proven_local_capability,
        "background_overview": is_background_request,
        "synthesis_explanation": is_synthesis_request,
        "local_answer": is_local_answer_request,
        "unproven_specialized_local": is_unproven_specialized_request,
    }


def _should_prefer_augmented_for_unproven_local(
    *,
    qn: str,
    intent: str,
    intent_class: str,
    needs_web: bool,
    risk_level: str,
    source_criticality: str,
    route_control_mode: str,
    proven_local_capability: bool,
) -> bool:
    profile = _build_auto_intent_profile(
        plan={},
        qn=qn,
        intent=intent,
        category="",
        intent_class=intent_class,
        needs_web=needs_web,
        risk_level=risk_level,
        source_criticality=source_criticality,
        signal_flags={},
        route_control_mode=route_control_mode,
        proven_local_capability=proven_local_capability,
    )
    return bool(profile.get("unproven_specialized_local"))


def _auto_intent_family(
    *,
    plan: Dict,
    qn: str,
    intent: str,
    category: str,
    intent_class: str,
    needs_web: bool,
    risk_level: str,
    source_criticality: str,
    signal_flags: Dict[str, bool],
    route_control_mode: str,
    proven_local_capability: bool,
) -> str:
    profile = _build_auto_intent_profile(
        plan=plan,
        qn=qn,
        intent=intent,
        category=category,
        intent_class=intent_class,
        needs_web=needs_web,
        risk_level=risk_level,
        source_criticality=source_criticality,
        signal_flags=signal_flags,
        route_control_mode=route_control_mode,
        proven_local_capability=proven_local_capability,
    )
    if profile.get("requires_current_evidence"):
        return "current_evidence"
    if not profile.get("local_safe_window"):
        return ""
    if profile.get("proven_local_capability"):
        return "local_answer"
    if route_control_mode == "AUTO" and intent_class == "technical_explanation":
        return "synthesis_explanation"
    if profile.get("synthesis_explanation"):
        return "synthesis_explanation"
    if profile.get("background_overview"):
        return "background_overview"
    if profile.get("local_answer"):
        return "local_answer"
    return ""


def _augmented_family_alias(intent_family: str) -> str:
    if intent_family == "background_overview":
        return "background"
    if intent_family == "synthesis_explanation":
        return "synthesis"
    return ""


def _confidence_from_policy_label(label: str) -> float:
    key = _s(label).strip().lower()
    if key in {"high", "strict"}:
        return 0.85
    if key in {"low", "uncertain"}:
        return 0.45
    return 0.75


def _infer_freshness_requirement(qn: str, intent: str) -> str:
    if intent in NEWS_INTENTS:
        return "high"
    if _has_temporal_freshness_marker(qn):
        return "high"
    if _has_re(qn, r"\b(tomorrow|next week|forecast|schedule)\b"):
        return "medium"
    return "low"


def _infer_risk_level(qn: str, intent: str, category: str) -> str:
    if intent == "MEDICAL_INFO":
        return "high"
    if _is_conceptual_travel_advisory_query(qn):
        return "low"
    if _has_re(qn, r"\b(travel|travelling|traveling|trip|visit)\b") and _has_re(
        qn,
        r"\b(safe|safety|advisory|warning|risk|dangerous|at the moment|right now|currently|today|iran|ukraine|russia|lebanon|syria|gaza|tehran|middle east|bali)\b",
    ):
        return "high"
    if _has_re(qn, r"\b(legal|lawsuit|regulation|tax|investment|buy or sell|mortgage|loan|debt)\b"):
        return "high"
    if category in {"travel_advisory"}:
        return "high"
    if _has_re(qn, r"\b(symptom|diagnosis|treatment|dose|dosage|side effect|contraindication)\b"):
        return "high"
    return "low"


def _infer_source_criticality(qn: str, needs_web: bool, needs_citations: bool, output_mode: str, intent: str) -> str:
    if intent == "MEDICAL_INFO":
        return "high"
    if needs_citations or needs_web:
        return "high"
    if output_mode in {"LIGHT_EVIDENCE", "VALIDATED"}:
        return "high"
    if _has_re(qn, r"\b(source|sources|citation|citations|cite|verify|proof|evidence|wikipedia|wiki|url|link|http)\b") and not is_probable_culinary_source_misrecognition(qn):
        return "high"
    return "low"


def _recommended_route(intent: str, needs_web: bool, freshness: str, risk: str, source_criticality: str) -> str:
    if intent in NEWS_INTENTS:
        return "news"
    if intent in EVIDENCE_INTENTS:
        return "evidence"
    if needs_web:
        return "evidence"
    if freshness != "low" or risk == "high" or source_criticality == "high":
        return "evidence"
    if intent in LOCAL_INTENTS:
        return "local"
    return "evidence"


def _is_explicit_doc_source_signal(intent: str, category: str, signal_flags: Dict[str, bool]) -> bool:
    if signal_flags.get("url") or signal_flags.get("source_request"):
        return True
    if intent in {"WEB_DOC", "PRIMARY_DOC"}:
        return True
    return category in {"reference", "url_reference", "primary_doc"}


def _is_medical_high_stakes_signal(intent: str, category: str, signal_flags: Dict[str, bool]) -> bool:
    return intent == "MEDICAL_INFO" or category == "medical" or bool(signal_flags.get("medical_context"))


def _is_temporal_live_signal(intent: str, category: str, signal_flags: Dict[str, bool]) -> bool:
    if intent in NEWS_INTENTS:
        return True
    if category in {"current_fact", "travel_advisory", "shopping_local"}:
        return True
    if signal_flags.get("news") or signal_flags.get("temporal"):
        return True
    return False


def _is_current_product_signal(category: str, signal_flags: Dict[str, bool]) -> bool:
    return category == "current_product_recommendation" or bool(signal_flags.get("current_product_recommendation"))


def _is_policy_global_signal(plan: Dict, intent: str, category: str, signal_flags: Dict[str, bool]) -> bool:
    allow_domains_file = _s(plan.get("allow_domains_file")).strip().lower()
    if not allow_domains_file.endswith("policy_global_runtime.txt"):
        return False
    if intent in EVIDENCE_INTENTS:
        return True
    if intent in NEWS_INTENTS:
        return True
    if category in {"news_world", "news_israel", "reference"}:
        return True
    return bool(signal_flags.get("source_request"))


def _resolve_signal_precedence(
    *,
    plan: Dict,
    qn: str,
    intent: str,
    category: str,
    signal_flags: Dict[str, bool],
    needs_web: bool,
    risk_level: str,
    source_criticality: str,
    legacy_recommended_route: str,
    route_control_mode: str,
) -> Tuple[str, str, str]:
    if _is_policy_global_signal(plan, intent, category, signal_flags):
        return "evidence", "policy_global", "current_evidence"
    intent_class = _s(plan.get("intent_class")).strip().lower()
    proven_local_capability = _b(plan.get("has_proven_local_capability"))
    intent_family = _auto_intent_family(
        plan=plan,
        qn=qn,
        intent=intent,
        category=category,
        intent_class=intent_class,
        needs_web=needs_web,
        risk_level=risk_level,
        source_criticality=source_criticality,
        signal_flags=signal_flags,
        route_control_mode=route_control_mode,
        proven_local_capability=proven_local_capability,
    )
    if intent_family == "current_evidence":
        if _is_explicit_doc_source_signal(intent, category, signal_flags):
            return "evidence", "doc_source", intent_family
        if _is_medical_high_stakes_signal(intent, category, signal_flags):
            return "evidence", "medical_high_stakes", intent_family
        if _is_temporal_live_signal(intent, category, signal_flags):
            return ("news" if intent in NEWS_INTENTS or signal_flags.get("news") else "evidence"), "temporal_live", intent_family
        if _is_current_product_signal(category, signal_flags):
            return "evidence", "current_product", intent_family
    if not intent_family and _should_prefer_augmented_for_unproven_local(
        qn=qn,
        intent=intent,
        intent_class=intent_class,
        needs_web=needs_web,
        risk_level=risk_level,
        source_criticality=source_criticality,
        route_control_mode=route_control_mode,
        proven_local_capability=proven_local_capability,
    ):
        return "augmented", "unproven_local_capability", ""
    if intent_family in {"background_overview", "synthesis_explanation"}:
        return "augmented", "conceptual_augmented", intent_family
    for signal_name in ROUTING_PRECEDENCE_LADDER:
        if signal_name == "ambiguity":
            continue
        if signal_name == "doc_source" and _is_explicit_doc_source_signal(intent, category, signal_flags):
            return "evidence", signal_name, intent_family if intent_family == "current_evidence" else ""
        if signal_name == "medical_high_stakes" and _is_medical_high_stakes_signal(intent, category, signal_flags):
            return "evidence", signal_name, intent_family if intent_family == "current_evidence" else ""
        if signal_name == "temporal_live" and _is_temporal_live_signal(intent, category, signal_flags):
            return ("news" if intent in NEWS_INTENTS or signal_flags.get("news") else "evidence"), signal_name, intent_family if intent_family == "current_evidence" else ""
        if signal_name == "current_product" and _is_current_product_signal(category, signal_flags):
            return "evidence", signal_name, intent_family if intent_family == "current_evidence" else ""
        if signal_name == "conceptual_local" and intent_family == "local_answer" and intent in LOCAL_INTENTS and not needs_web and risk_level == "low" and source_criticality == "low":
            return "local", signal_name, intent_family
    return legacy_recommended_route, "legacy_policy", intent_family


def _is_travel_advisory_query(qn: str, category: str) -> bool:
    if _is_conceptual_travel_advisory_query(qn):
        return False
    if category == "travel_advisory":
        return True
    if _has_re(qn, r"\b(travel|travelling|traveling|trip|visit)\b") and _has_re(
        qn,
        r"\b(safe|safety|advisory|warning|risk|dangerous|at the moment|right now|currently|today|iran|ukraine|russia|lebanon|syria|gaza|tehran|middle east|bali)\b",
    ):
        return True
    # Destination safety prompts that omit explicit travel verbs still require evidence routing.
    if _has_re(qn, r"\b(safe|safety|advisory|warning|dangerous|risk)\b") and _has_re(
        qn, r"\b(iran|israel|ukraine|russia|lebanon|syria|gaza|tehran|middle east|bali|jordan)\b"
    ):
        return True
    return False


def _apply_confidence_fail_open(recommended_route: str, confidence: float, threshold: float) -> str:
    if confidence < threshold and recommended_route == "local":
        return "evidence"
    return recommended_route

def _resolve_override_route(
    recommended_route: str,
    route_control_mode: str,
    route_prefix: str,
    intent: str,
    qn: str,
) -> Tuple[str, str, List[str]]:
    reasons: List[str] = []
    operator_override = "none"

    if route_prefix in {"local", "news", "evidence"}:
        operator_override = f"query_prefix_{route_prefix}"
        reasons.append(operator_override)
        return route_prefix, operator_override, reasons

    if route_control_mode == "FORCED_OFFLINE":
        operator_override = "operator_forced_offline"
        reasons.append(operator_override)
        return "local", operator_override, reasons

    if route_control_mode == "FORCED_ONLINE":
        operator_override = "operator_forced_online"
        reasons.append(operator_override)
        # Governor-owned local identity/software directives stay local under forced-online.
        if is_local_policy_query(qn, intent) or recommended_route == "local":
            return "local", operator_override, reasons
        if intent in NEWS_INTENTS or _has_re(qn, r"\b(news|headline|headlines|breaking)\b"):
            return "news", operator_override, reasons
        return "evidence", operator_override, reasons

    return recommended_route, operator_override, reasons


def evaluate_policy(
    plan: Dict,
    question: str,
    route_prefix: str,
    route_control_mode: str,
    confidence_threshold: float,
    surface: str,
) -> Dict:
    route_prefix = _s(route_prefix).strip().lower()
    route_control_mode = _s(route_control_mode).strip()
    intent = _s(plan.get("intent"))
    needs_web = _b(plan.get("needs_web"))
    needs_citations = _b(plan.get("needs_citations"))
    output_mode = _s(plan.get("output_mode"))
    category = _s(plan.get("category"))
    qn = _norm_text(question)
    signal_flags = build_common_signal_flags(qn)
    signal_flags.update(_bool_map(plan.get("routing_signals")))

    freshness_requirement = _infer_freshness_requirement(qn, intent)
    risk_level = _infer_risk_level(qn, intent, category)
    source_criticality = _infer_source_criticality(qn, needs_web, needs_citations, output_mode, intent)
    signal_flags["medical_context"] = intent == "MEDICAL_INFO"
    signal_flags["travel_risk"] = _is_travel_advisory_query(qn, category)
    signal_flags["legal_finance"] = _has_re(qn, r"\b(legal|lawsuit|regulation|tax|investment|mortgage|loan|debt|stock|market)\b")
    signal_flags["policy_global"] = _is_policy_global_signal(plan, intent, category, signal_flags)

    policy_confidence = _confidence_from_policy_label(_s(plan.get("confidence_policy")))
    intent_class = _s(plan.get("intent_class")).strip().lower()
    proven_local_capability = _b(plan.get("has_proven_local_capability"))
    if intent in LOCAL_INTENTS and freshness_requirement == "low" and risk_level == "low" and source_criticality == "low":
        policy_confidence = min(0.95, policy_confidence + 0.08)
    if freshness_requirement == "high" and intent in LOCAL_INTENTS:
        policy_confidence = max(0.25, policy_confidence - 0.28)

    base_recommended_route = _recommended_route(intent, needs_web, freshness_requirement, risk_level, source_criticality)
    if _is_travel_advisory_query(qn, category):
        base_recommended_route = "evidence"
    precedence_route, winning_signal, intent_family = _resolve_signal_precedence(
        plan=plan,
        qn=qn,
        intent=intent,
        category=category,
        signal_flags=signal_flags,
        needs_web=needs_web,
        risk_level=risk_level,
        source_criticality=source_criticality,
        legacy_recommended_route=base_recommended_route,
        route_control_mode=route_control_mode,
    )
    recommended_route = _apply_confidence_fail_open(precedence_route, policy_confidence, confidence_threshold)

    reason_codes: List[str] = []
    reason_codes.append(f"intent:{intent or 'unknown'}")
    reason_codes.append(f"freshness:{freshness_requirement}")
    reason_codes.append(f"risk:{risk_level}")
    reason_codes.append(f"source_criticality:{source_criticality}")
    reason_codes.append(f"local_capability:{'proven' if proven_local_capability else 'unproven'}")
    if intent_family:
        reason_codes.append(f"intent_family:{intent_family}")
    reason_codes.append(f"winning_signal:{winning_signal}")
    augmented_family = _augmented_family_alias(intent_family)
    if augmented_family:
        reason_codes.append(f"augmented_family:{augmented_family}")
    for signal_name in ("temporal", "news", "conflict", "geopolitics", "medical_context", "source_request", "url", "travel_risk", "policy_global"):
        if signal_flags.get(signal_name):
            reason_codes.append(f"signal:{signal_name}")
    if policy_confidence < confidence_threshold:
        reason_codes.append("confidence_below_threshold")
    if recommended_route != base_recommended_route:
        reason_codes.append("uncertainty_escalation_to_evidence")

    actual_route, operator_override, override_reasons = _resolve_override_route(
        recommended_route, route_control_mode, route_prefix, intent, qn
    )
    reason_codes.extend(override_reasons)

    if route_control_mode == "FORCED_OFFLINE":
        if intent == "MEDICAL_INFO":
            offline_action = "validated_insufficient"
        elif recommended_route in {"evidence", "news"} or needs_web:
            offline_action = "requires_evidence"
        else:
            offline_action = "allow"
    else:
        offline_action = "allow"

    return {
        "route": actual_route,
        "policy_recommended_route": recommended_route,
        "base_recommended_route": base_recommended_route,
        "offline_action": offline_action,
        "operator_override": operator_override,
        "reason_codes": reason_codes,
        "reason_codes_csv": ",".join(reason_codes),
        "policy_confidence": round(policy_confidence, 3),
        "policy_confidence_threshold": round(confidence_threshold, 3),
        "freshness_requirement": freshness_requirement,
        "risk_level": risk_level,
        "source_criticality": source_criticality,
        "winning_signal": winning_signal,
        "intent_family": intent_family,
        "augmented_family": augmented_family,
        "precedence_version": ROUTING_PRECEDENCE_VERSION,
        "signal_flags": signal_flags,
        "surface": _s(surface).strip().lower() or "cli",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan-json", required=True)
    ap.add_argument("--question", default="")
    ap.add_argument("--route-prefix", default="")
    ap.add_argument("--route-control-mode", default="AUTO")
    ap.add_argument("--confidence-threshold", type=float, default=0.60)
    ap.add_argument("--surface", default="cli")
    args = ap.parse_args()

    try:
        plan = json.loads(args.plan_json or "{}")
    except Exception as e:
        print(f"ERR invalid plan json: {e}", file=sys.stderr)
        return 2

    if args.route_control_mode not in {"AUTO", "FORCED_OFFLINE", "FORCED_ONLINE"}:
        print(f"ERR invalid route_control_mode: {args.route_control_mode}", file=sys.stderr)
        return 2

    out = evaluate_policy(
        plan=plan,
        question=args.question,
        route_prefix=args.route_prefix,
        route_control_mode=args.route_control_mode,
        confidence_threshold=args.confidence_threshold,
        surface=args.surface,
    )
    print(json.dumps(out, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
