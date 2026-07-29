#!/usr/bin/env python3
"""Plan construction helpers for the plan-to-pipeline CLI.

This module holds the plan-building logic that used to live inline in
``plan_to_pipeline_cli.py``:

* Extracting the legacy plan from a classified plan
* Patching a plan to match an effective plan
* Building a classification-derived plan patch
* Applying semantic-interpretation upgrades
* Building the route-prefix-derived ``effective_plan``
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, List

# Ensure tools package is importable when this module is loaded directly.
TOOLS_DIR = Path(__file__).resolve().parent.parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.intent_classifier import _legacy_plan_from_classification
from router_py.core.routing_signals import should_use_israel_news_region


def _legacy_plan(plan: Dict[str, object]) -> Dict[str, object]:
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


def _news_region_filter_for_question(question: str) -> str:
    if should_use_israel_news_region(question or ""):
        return "IL"
    return ""


def _patch_classification_for_effective_plan(
    plan: Dict[str, object], effective_plan: Dict[str, object]
) -> Dict[str, object]:
    patched = dict(plan)
    patched["legacy_plan"] = dict(effective_plan)
    patched["intent"] = effective_plan.get("intent")
    patched["category"] = effective_plan.get("category")
    patched["needs_web"] = effective_plan.get("needs_web")
    patched["needs_citations"] = effective_plan.get("needs_citations")
    patched["min_sources"] = effective_plan.get("min_sources")
    patched["output_mode"] = effective_plan.get("output_mode")
    patched["prefer_domains"] = effective_plan.get("prefer_domains")
    patched["allow_domains_file"] = effective_plan.get("allow_domains_file")
    patched["region_filter"] = effective_plan.get("region_filter")
    patched["one_clarifying_question"] = effective_plan.get("one_clarifying_question")
    patched["confidence_policy"] = effective_plan.get("confidence_policy")
    if effective_plan.get("intent") == "LOCAL_KNOWLEDGE":
        patched["intent_class"] = "local_knowledge"
        patched["needs_current_info"] = False
        patched["needs_clarification"] = False
        patched["clarification_question"] = None
        patched["mixed_intent"] = False
        routing_signals = dict(patched.get("routing_signals") or {})
        for signal_name in (
            "temporal",
            "news",
            "source_request",
            "url",
            "current_product_recommendation",
            "ambiguity_followup",
        ):
            routing_signals[signal_name] = False
        patched["routing_signals"] = routing_signals
    if effective_plan.get("intent") == "MEDICAL_INFO":
        patched["intent_class"] = "evidence_check"
        patched["needs_clarification"] = False
        patched["clarification_question"] = None
        patched["mixed_intent"] = False
        patched["needs_current_info"] = bool(patched.get("needs_current_info"))
        patched["confidence"] = max(float(patched.get("confidence") or 0.0), 0.9)
    return patched


def _json_array(values: List[str]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _semantic_trace(question: str) -> Dict[str, object]:
    return {
        "original_query": question,
        "resolved_execution_query": question,
        "interpreter_fired": False,
        "inferred_domain": "unknown",
        "inferred_intent_family": "unknown",
        "normalized_candidates": [],
        "retrieval_candidates": [],
        "ambiguity_flag": False,
        "confidence": 0.0,
        "provenance_notes": [],
        "use_reason": "not_invoked",
        "used_for_routing": False,
        "forward_candidates": False,
        "selected_normalized_query": question,
        "selected_retrieval_query": "",
    }


def _medical_detector_trace(question: str) -> Dict[str, object]:
    return {
        "detector_fired": False,
        "original_query": question,
        "resolved_execution_query": question,
        "normalized_query": "",
        "detection_source": "not_detected",
        "pattern_family": "",
        "candidate_medication": "",
        "normalized_candidate": "",
        "confidence": "none",
        "confidence_score": 0.0,
        "provenance_notes": [],
    }


def _patch_plan_with_classification(
    plan: Dict[str, object],
    intent_class: str,
    subcategory: str,
    confidence: float,
    candidate_routes: List[str],
    *,
    needs_current_info: bool = False,
    needs_clarification: bool = False,
    clarification_question: str = "",
    style_mode: str = "informational",
    mixed_intent: bool = False,
    region_filter: str = "",
) -> Dict[str, object]:
    classification = {
        "intent_class": intent_class,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "needs_current_info": bool(needs_current_info),
        "needs_personal_context": False,
        "style_mode": style_mode,
        "mixed_intent": mixed_intent,
        "candidate_routes": candidate_routes,
        "needs_clarification": needs_clarification,
        "clarification_question": clarification_question or None,
        "subcategory": subcategory,
        "identity_variant": "",
    }
    if region_filter:
        classification["region_filter"] = region_filter
    patched = dict(plan)
    patched.update(classification)
    legacy_plan = _legacy_plan_from_classification(classification, patched)
    patched["legacy_plan"] = legacy_plan
    patched.update(legacy_plan)
    return patched


def _semantic_use_allowed(plan: Dict[str, object], semantic_trace: Dict[str, object]) -> bool:
    if not semantic_trace.get("interpreter_fired"):
        return False
    if (
        semantic_trace.get("ambiguity_flag")
        and float(semantic_trace.get("confidence") or 0.0) < 0.7
    ):
        return False
    try:
        semantic_confidence = float(semantic_trace.get("confidence") or 0.0)
    except (TypeError, ValueError):
        semantic_confidence = 0.0
    if semantic_confidence < 0.78:
        return False
    intent_class = str(plan.get("intent_class") or "").strip().lower()
    subcategory = str(plan.get("subcategory") or "").strip().lower()
    if intent_class == "technical_explanation" and float(plan.get("confidence") or 0.0) >= 0.86:
        return False
    if intent_class == "evidence_check" and subcategory in {
        "medical",
        "url_reference",
        "primary_doc",
    }:
        return False
    if intent_class == "current_fact" and subcategory.startswith("news"):
        return False
    return True


def _apply_semantic_interpretation(
    plan: Dict[str, object],
    question: str,
    semantic_trace: Dict[str, object],
) -> Dict[str, object]:
    if not _semantic_use_allowed(plan, semantic_trace):
        return plan

    intent_class = str(plan.get("intent_class") or "").strip().lower()
    inferred_domain = str(semantic_trace.get("inferred_domain") or "unknown").strip().lower()
    inferred_intent_family = (
        str(semantic_trace.get("inferred_intent_family") or "unknown").strip().lower()
    )
    confidence = max(
        float(plan.get("confidence") or 0.0), float(semantic_trace.get("confidence") or 0.0)
    )
    question_lower = (question or "").strip().lower()

    if inferred_intent_family == "url_reference":
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "upgrade_to_url_reference"
        return _patch_plan_with_classification(
            plan,
            "evidence_check",
            "url_reference",
            confidence,
            ["EVIDENCE"],
        )

    if inferred_domain == "medical" or (
        inferred_intent_family == "evidence_check"
        and re.search(r"\b(medical|medication|drug|blood pressure|hypertension)\b", question_lower)
    ):
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "upgrade_to_medical_evidence"
        return _patch_plan_with_classification(
            plan,
            "evidence_check",
            "medical",
            max(confidence, 0.9),
            ["EVIDENCE"],
        )

    if inferred_domain == "travel":
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "upgrade_to_travel_evidence"
        return _patch_plan_with_classification(
            plan,
            "evidence_check",
            "travel_advisory",
            confidence,
            ["EVIDENCE"],
            needs_current_info=True,
        )

    if inferred_domain == "news" or inferred_intent_family == "current_fact":
        region_filter = _news_region_filter_for_question(question_lower)
        subcategory = "news_israel" if region_filter == "IL" else "news_world"
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "upgrade_to_news"
        return _patch_plan_with_classification(
            plan,
            "current_fact",
            subcategory,
            max(confidence, 0.86),
            ["NEWS", "EVIDENCE"],
            needs_current_info=True,
            style_mode="brief",
            region_filter=region_filter,
        )

    if inferred_intent_family == "technical_explanation":
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "upgrade_to_technical_local"
        return _patch_plan_with_classification(
            plan,
            "technical_explanation",
            "technical_explanation",
            max(confidence, 0.82),
            ["LOCAL"],
            style_mode="technical",
        )

    if inferred_intent_family == "clarify" or (
        semantic_trace.get("ambiguity_flag")
        and float(semantic_trace.get("confidence") or 0.0) < 0.82
        and intent_class in {"mixed", "local_knowledge"}
    ):
        semantic_trace["used_for_routing"] = True
        semantic_trace["use_reason"] = "prefer_clarify_over_speculation"
        return _patch_plan_with_classification(
            plan,
            "mixed",
            "ambiguous_interpretation",
            min(float(semantic_trace.get("confidence") or 0.0), 0.6),
            ["CLARIFY", "EVIDENCE", "LOCAL"],
            needs_clarification=True,
            clarification_question="What specific topic do you want me to continue with?",
            mixed_intent=True,
        )

    return plan


def build_effective_plan(plan: Dict[str, object], route_prefix: str) -> Dict[str, object]:
    """Build the effective legacy plan, applying route-prefix overrides.

    Args:
        plan: The fully classified plan (possibly after semantic interpretation).
        route_prefix: Normalized lower-case route prefix (e.g. ``"news"``, ``"local"``).

    Returns:
        The effective plan dict used for downstream routing and contract building.
    """
    base_plan = _legacy_plan(plan)
    effective_plan = dict(base_plan)
    if route_prefix == "news":
        effective_plan["intent"] = "WEB_NEWS"
        effective_plan["needs_web"] = True
        effective_plan["min_sources"] = max(1, int(base_plan.get("min_sources", 2) or 2))
        effective_plan["output_mode"] = "LIGHT_EVIDENCE"
    elif route_prefix == "local" and str(base_plan.get("intent") or "") != "MEDICAL_INFO":
        effective_plan["intent"] = "LOCAL_KNOWLEDGE"
        effective_plan["needs_web"] = False
        effective_plan["min_sources"] = 1
        effective_plan["output_mode"] = "CHAT"
    return effective_plan
