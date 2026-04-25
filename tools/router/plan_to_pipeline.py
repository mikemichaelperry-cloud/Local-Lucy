#!/usr/bin/env python3
"""Frozen router/governor baseline.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and semantic-interpreter routing
authority must not be expanded casually.
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List

MODULE_IMPORT_START = time.perf_counter()

THIS_DIR = Path(__file__).resolve().parent
AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"
CORE_DIR = THIS_DIR / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))
if str(THIS_DIR) not in sys.path:
    sys.path.insert(0, str(THIS_DIR))

from contextual_policy import resolve_contextual_followup
from intent_classifier import _legacy_plan_from_classification, classify_question
from local_context_policy import resolve_local_context_response
from local_policy import match_local_response_id
from medical_query_heuristics import detect_human_medication_query
from pet_food_policy import resolve_pet_food_policy
from policy_router import route_intent
from route_manifest import build_route_manifest
from runtime_governor import build_execution_contract
from routing_signals import should_use_israel_news_region
from semantic_interpreter import maybe_interpret_question


def _append_latency(stage: str, ms: int, component: str = "plan_to_pipeline") -> None:
    if (os.environ.get("LUCY_LATENCY_PROFILE_ACTIVE") or "0") != "1":
        return
    path = (os.environ.get("LUCY_LATENCY_PROFILE_FILE") or "").strip()
    run_id = (os.environ.get("LUCY_LATENCY_RUN_ID") or "").strip()
    if not path or not run_id:
        return
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"run={run_id}\tcomponent={component}\tstage={stage}\tms={int(ms)}\n")
    except OSError:
        return


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


def _root_dir() -> str:
    override = (os.environ.get(AUTHORITY_ROOT_ENV) or "").strip()
    if override:
        return str(Path(override).expanduser().resolve())
    return str(THIS_DIR.parent.parent)


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text or "", flags=re.IGNORECASE) is not None


def _rewrite_news_query(question: str) -> str:
    rewritten = (question or "").strip()
    if not rewritten or _has_re(rewritten, r"\b(news|headline|headlines|breaking)\b"):
        return rewritten
    if _has_re(rewritten, r"\bwhat happened in\b"):
        rewritten = re.sub(
            r"(?i)\bwhat happened in\b",
            "What are the latest news and developments in",
            rewritten,
            count=1,
        )
    elif _has_re(rewritten, r"\blatest developments?\b"):
        rewritten = re.sub(r"(?i)\blatest developments?\b", "latest news and developments", rewritten, count=1)
    elif _has_re(rewritten, r"\b(most significant|major|key)\s+developments?\b"):
        rewritten = re.sub(
            r"(?i)\b(most significant|major|key)\s+developments?\b",
            "latest news and developments",
            rewritten,
            count=1,
        )
    elif _has_re(rewritten, r"\blatest on\b"):
        rewritten = re.sub(r"(?i)\blatest on\b", "the latest news and developments on", rewritten, count=1)
    elif _has_re(rewritten, r"\b(today|latest|recent|right now|now)\b"):
        rewritten = rewritten.rstrip("?.! ")
        rewritten = f"{rewritten}. Focus on the latest news and developments."
    else:
        topic = rewritten.rstrip("?.! ")
        topic = re.sub(r"(?i)^\s*what\s+(?:are|is)\s+", "", topic).strip()
        topic = re.sub(r"(?i)^\s*(?:tell me|give me|summarize|update me on)\s+", "", topic).strip()
        if not topic:
            topic = rewritten.rstrip("?.! ")
        rewritten = f"What are the latest news and developments about {topic}?"
    if _has_re(rewritten, r"^what\b") and not rewritten.endswith("?"):
        rewritten = f"{rewritten}?"
    return rewritten


def _news_region_filter_for_question(question: str) -> str:
    if should_use_israel_news_region(question or ""):
        return "IL"
    return ""


def _pet_food_medical_plan() -> Dict[str, object]:
    return {
        "intent": "MEDICAL_INFO",
        "category": "medical",
        "needs_web": True,
        "needs_citations": True,
        "min_sources": 2,
        "output_mode": "VALIDATED",
        "prefer_domains": [],
        "allow_domains_file": "config/trust/generated/vet_runtime.txt",
        "region_filter": None,
        "one_clarifying_question": None,
        "confidence_policy": "high_stakes",
    }


def _media_reliability_local_plan() -> Dict[str, object]:
    return {
        "intent": "LOCAL_KNOWLEDGE",
        "category": "general",
        "needs_web": False,
        "needs_citations": False,
        "min_sources": 1,
        "output_mode": "CHAT",
        "prefer_domains": [],
        "allow_domains_file": None,
        "region_filter": None,
        "one_clarifying_question": None,
        "confidence_policy": "normal",
    }


def _patch_classification_for_effective_plan(plan: Dict[str, object], effective_plan: Dict[str, object]) -> Dict[str, object]:
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
        for signal_name in ("temporal", "news", "source_request", "url", "current_product_recommendation", "ambiguity_followup"):
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
    if semantic_trace.get("ambiguity_flag") and float(semantic_trace.get("confidence") or 0.0) < 0.7:
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
    if intent_class == "evidence_check" and subcategory in {"medical", "url_reference", "primary_doc"}:
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
    inferred_intent_family = str(semantic_trace.get("inferred_intent_family") or "unknown").strip().lower()
    confidence = max(float(plan.get("confidence") or 0.0), float(semantic_trace.get("confidence") or 0.0))
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
        inferred_intent_family == "evidence_check" and re.search(r"\b(medical|medication|drug|blood pressure|hypertension)\b", question_lower)
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
        semantic_trace.get("ambiguity_flag") and float(semantic_trace.get("confidence") or 0.0) < 0.82 and intent_class in {"mixed", "local_knowledge"}
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


def main() -> int:
    main_start = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--question", default="")
    parser.add_argument("--route-prefix", default="")
    parser.add_argument("--route-control-mode", default="AUTO")
    parser.add_argument("--surface", default=os.environ.get("LUCY_SURFACE", "cli"))
    args = parser.parse_args()

    try:
        plan = json.loads(args.plan_json or "{}")
    except Exception as exc:
        print(f"ERR invalid plan json: {exc}", file=sys.stderr)
        return 2

    route_control_mode = (args.route_control_mode or "AUTO").strip()
    if route_control_mode not in {"AUTO", "FORCED_OFFLINE", "FORCED_ONLINE"}:
        print(f"ERR invalid route_control_mode: {route_control_mode}", file=sys.stderr)
        return 2

    try:
        confidence_threshold = float(os.environ.get("POLICY_CONFIDENCE_THRESHOLD", "0.60"))
    except ValueError:
        confidence_threshold = 0.60

    route_prefix = (args.route_prefix or "").strip().lower()
    stage_start = time.perf_counter()
    root_dir = _root_dir()
    _append_latency("resolve_root_dir", max(1, int(round((time.perf_counter() - stage_start) * 1000))))
    original_question = args.question or ""
    question_for_execution = original_question
    route_reason_override = ""
    contextual_followup_applied = False
    contextual_followup_kind = ""
    knowledge_path = ""
    outcome_code_override = ""
    local_response_text = None
    local_response_operator_override = ""
    semantic_trace = _semantic_trace(original_question)

    stage_start = time.perf_counter()
    if not route_prefix:
        followup = resolve_contextual_followup(original_question, root_dir)
        if followup:
            question_for_execution = str(followup.get("resolved_question") or original_question)
            route_reason_override = str(followup.get("route_reason_override") or "")
            contextual_followup_applied = True
            contextual_followup_kind = str(followup.get("contextual_followup_kind") or "")
            classify_start = time.perf_counter()
            plan = classify_question(question_for_execution, surface=args.surface)
            _append_latency(
                "reclassify_followup_question",
                max(1, int(round((time.perf_counter() - classify_start) * 1000))),
            )
    _append_latency("contextual_followup", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    semantic_trace = maybe_interpret_question(question_for_execution or original_question, plan)
    semantic_trace["original_query"] = original_question
    semantic_trace["resolved_execution_query"] = question_for_execution or original_question
    _append_latency("semantic_interpreter", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    medical_detector = detect_human_medication_query(question_for_execution or original_question)
    medical_detector["original_query"] = original_question
    medical_detector["resolved_execution_query"] = question_for_execution or original_question
    _append_latency("medical_detector", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    plan = _apply_semantic_interpretation(plan, question_for_execution or original_question, semantic_trace)
    _append_latency("semantic_plan_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    base_plan = _legacy_plan(plan)
    effective_plan = dict(base_plan)
    stage_start = time.perf_counter()
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
    _append_latency("route_prefix_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    if contextual_followup_kind == "media_reliability":
        effective_plan = _media_reliability_local_plan()
        plan = _patch_classification_for_effective_plan(plan, effective_plan)
    _append_latency("contextual_plan_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    if original_question and not local_response_text:
        local_context_resolution = resolve_local_context_response(original_question, root_dir)
        if local_context_resolution:
            route_reason_override = str(local_context_resolution.get("route_reason_override") or route_reason_override)
            outcome_code_override = str(local_context_resolution.get("outcome_code_override") or outcome_code_override)
            local_response_text = str(local_context_resolution.get("local_response_text") or "")
            local_response_operator_override = str(
                local_context_resolution.get("operator_override") or "governor_local_context_response"
            )
    _append_latency("local_context_resolution", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    if original_question and str(effective_plan.get("intent") or "") == "PET_FOOD":
        pet_food_resolution = resolve_pet_food_policy(root_dir, question_for_execution)
        if pet_food_resolution:
            knowledge_path = str(pet_food_resolution.get("knowledge_path") or "")
            route_reason_override = str(pet_food_resolution.get("route_reason_override") or route_reason_override)
            outcome_code_override = str(pet_food_resolution.get("outcome_code_override") or "")
            if pet_food_resolution.get("matched"):
                local_response_text = str(pet_food_resolution.get("local_response_text") or "")
                local_response_operator_override = "governor_pet_food_knowledge"
            else:
                effective_plan = _pet_food_medical_plan()
                plan = _patch_classification_for_effective_plan(plan, effective_plan)
    _append_latency("pet_food_policy", max(1, int(round((time.perf_counter() - stage_start) * 1000))))

    stage_start = time.perf_counter()
    local_response_id_hint = match_local_response_id(
        question_for_execution or original_question,
        str(effective_plan.get("intent") or plan.get("intent") or ""),
    )
    _append_latency("local_response_match", max(1, int(round((time.perf_counter() - stage_start) * 1000))))
    proven_local_capability = bool(
        local_response_text
        or local_response_id_hint
        or str(plan.get("intent_class") or "").strip().lower() in {"conversational", "identity_personal"}
    )

    router_input = dict(plan)
    router_input["legacy_plan"] = dict(effective_plan)
    router_input["local_response_id_hint"] = local_response_id_hint or ""
    router_input["has_proven_local_capability"] = proven_local_capability

    router_start = time.perf_counter()
    routing = route_intent(
        plan=router_input,
        question=question_for_execution,
        route_prefix=route_prefix,
        route_control_mode=route_control_mode,
        confidence_threshold=confidence_threshold,
        surface=args.surface,
    )
    router_ms = max(1, int(round((time.perf_counter() - router_start) * 1000)))
    _append_latency("policy_engine", router_ms)

    route_decision = dict(routing)
    semantic_forward_candidates = bool(
        semantic_trace.get("interpreter_fired")
        and not semantic_trace.get("ambiguity_flag")
        and float(semantic_trace.get("confidence") or 0.0) >= 0.78
        and route_decision.get("route_mode") in {"NEWS", "EVIDENCE"}
        and (semantic_trace.get("normalized_candidates") or semantic_trace.get("retrieval_candidates"))
    )
    semantic_trace["forward_candidates"] = semantic_forward_candidates
    if str(route_decision.get("route_mode") or "").upper() == "NEWS":
        rewritten_news_question = _rewrite_news_query(question_for_execution)
        if rewritten_news_question and rewritten_news_question != question_for_execution:
            question_for_execution = rewritten_news_question
            route_reason_override = route_reason_override or "governor_news_query_rewrite"
    if local_response_text:
        route_decision.update(
            {
                "route_mode": "LOCAL",
                "force_mode": "LOCAL",
                "offline_action": "allow",
                "needs_clarification": False,
                "clarification_question": None,
                "policy_recommended_route": "local",
                "policy_actual_route": "local",
                "policy_base_recommended_route": "local",
                "intent_family": "local_answer",
                "augmented_family": "",
                "operator_override": local_response_operator_override or "governor_local_response",
            }
        )
    stage_start = time.perf_counter()
    manifest_selected_route = str(route_decision.get("force_mode") or route_decision.get("route_mode") or "")
    offline_action = str(route_decision.get("offline_action") or "").strip().lower()
    if (
        offline_action
        and offline_action != "allow"
        and not (
            route_prefix == "local"
            and str(manifest_selected_route).strip().upper() == "LOCAL"
            and not bool(effective_plan.get("needs_web"))
        )
    ):
        manifest_selected_route = str(
            route_decision.get("policy_base_recommended_route") or route_decision.get("policy_recommended_route") or manifest_selected_route
        )
    route_manifest = build_route_manifest(
        original_query=original_question,
        resolved_execution_query=question_for_execution or original_question,
        selected_route=manifest_selected_route,
        candidate_routes=plan.get("candidate_routes") or [],
        winning_signal=str(route_decision.get("winning_signal") or ""),
        precedence_version=str(route_decision.get("precedence_version") or ""),
        clarify_required=bool(route_decision.get("needs_clarification")),
        signal_flags=route_decision.get("signal_flags") or {},
        context_resolution_used=contextual_followup_applied,
        contextual_followup_kind=contextual_followup_kind,
        intent_family=str(route_decision.get("intent_family") or ""),
        route_prefix=route_prefix,
        local_response_selected=bool(local_response_text),
    )
    _append_latency("route_manifest", max(1, int(round((time.perf_counter() - stage_start) * 1000))))
    governor_start = time.perf_counter()
    execution_contract = build_execution_contract(
        plan=plan,
        effective_plan=effective_plan,
        route_decision=route_decision,
        route_manifest=route_manifest,
        question=question_for_execution,
        resolved_question=question_for_execution if question_for_execution != original_question else "",
        local_response_text=local_response_text,
        route_control_mode=route_control_mode,
        route_prefix=route_prefix,
        surface=args.surface,
    )
    governor_ms = max(1, int(round((time.perf_counter() - governor_start) * 1000)))
    _append_latency("runtime_governor", governor_ms)
    _append_latency("module_import_and_init", max(1, int(round((main_start - MODULE_IMPORT_START) * 1000))))
    _append_latency("main_body_total", max(1, int(round((time.perf_counter() - main_start) * 1000))))
    compatibility_route = str(route_manifest.get("selected_route") or "").strip().upper()
    compatibility_policy_route = compatibility_route.lower()

    output = {
        "router_intent": effective_plan.get("intent") or base_plan.get("intent"),
        "effective_plan": effective_plan,
        "route_decision": route_decision,
        "route_manifest": route_manifest,
        "execution_contract": execution_contract,
        "effective_intent": effective_plan.get("intent"),
        "effective_needs_web": effective_plan.get("needs_web"),
        "effective_min_sources": effective_plan.get("min_sources"),
        "effective_plan_output_mode": effective_plan.get("output_mode"),
        "prefix_requires_evidence": route_prefix in {"news", "evidence"},
        "force_mode": compatibility_route,
        "route_mode": compatibility_route,
        "offline_action": route_decision.get("offline_action"),
        "one_clarifying_question": effective_plan.get("one_clarifying_question"),
        "needs_clarification": route_manifest.get("clarify_required"),
        "clarification_question": route_decision.get("clarification_question"),
        "route_prefix": route_prefix,
        "route_control_mode": route_control_mode,
        "policy_recommended_route": compatibility_policy_route,
        "policy_actual_route": compatibility_policy_route,
        "policy_base_recommended_route": compatibility_policy_route,
        "policy_confidence": route_decision.get("policy_confidence"),
        "policy_confidence_threshold": route_decision.get("policy_confidence_threshold"),
        "confidence_band": route_decision.get("confidence_band"),
        "freshness_requirement": route_decision.get("freshness_requirement"),
        "risk_level": route_decision.get("risk_level"),
        "source_criticality": route_decision.get("source_criticality"),
        "operator_override": route_decision.get("operator_override"),
        "reason_codes": route_decision.get("reason_codes") or [],
        "reason_codes_csv": route_decision.get("reason_codes_csv"),
        "surface": route_decision.get("surface") or args.surface,
        "mixed_intent": route_decision.get("mixed_intent"),
        "manifest_version": route_manifest.get("manifest_version"),
        "manifest_selected_route": route_manifest.get("selected_route"),
        "manifest_winning_signal": route_manifest.get("winning_signal"),
        "manifest_authority_basis": route_manifest.get("authority_basis"),
        "resolved_question": question_for_execution if question_for_execution != original_question else "",
        "contextual_followup_applied": contextual_followup_applied,
        "contextual_followup_kind": contextual_followup_kind,
        "route_reason_override": route_reason_override,
        "knowledge_path": knowledge_path,
        "outcome_code_override": outcome_code_override,
        "semantic_interpreter": semantic_trace,
        "semantic_interpreter_fired": semantic_trace.get("interpreter_fired"),
        "semantic_interpreter_original_query": semantic_trace.get("original_query"),
        "semantic_interpreter_resolved_execution_query": semantic_trace.get("resolved_execution_query"),
        "semantic_interpreter_inferred_domain": semantic_trace.get("inferred_domain"),
        "semantic_interpreter_inferred_intent_family": semantic_trace.get("inferred_intent_family"),
        "semantic_interpreter_confidence": semantic_trace.get("confidence"),
        "semantic_interpreter_ambiguity_flag": semantic_trace.get("ambiguity_flag"),
        "semantic_interpreter_gate_reason": semantic_trace.get("gate_reason"),
        "semantic_interpreter_invocation_attempted": semantic_trace.get("invocation_attempted"),
        "semantic_interpreter_result_status": semantic_trace.get("result_status"),
        "semantic_interpreter_use_reason": semantic_trace.get("use_reason"),
        "semantic_interpreter_used_for_routing": semantic_trace.get("used_for_routing"),
        "semantic_interpreter_forward_candidates": semantic_trace.get("forward_candidates"),
        "semantic_interpreter_selected_normalized_query": semantic_trace.get("selected_normalized_query"),
        "semantic_interpreter_selected_retrieval_query": semantic_trace.get("selected_retrieval_query"),
        "semantic_interpreter_normalized_candidates_csv": ",".join(semantic_trace.get("normalized_candidates") or []),
        "semantic_interpreter_retrieval_candidates_csv": ",".join(semantic_trace.get("retrieval_candidates") or []),
        "semantic_interpreter_normalized_candidates_json": _json_array(semantic_trace.get("normalized_candidates") or []),
        "semantic_interpreter_retrieval_candidates_json": _json_array(semantic_trace.get("retrieval_candidates") or []),
        "medical_detector": medical_detector,
        "medical_detector_fired": medical_detector.get("detector_fired"),
        "medical_detector_original_query": medical_detector.get("original_query"),
        "medical_detector_resolved_execution_query": medical_detector.get("resolved_execution_query"),
        "medical_detector_detection_source": medical_detector.get("detection_source"),
        "medical_detector_pattern_family": medical_detector.get("pattern_family"),
        "medical_detector_candidate_medication": medical_detector.get("candidate_medication"),
        "medical_detector_normalized_candidate": medical_detector.get("normalized_candidate"),
        "medical_detector_normalized_query": medical_detector.get("normalized_query"),
        "medical_detector_confidence": medical_detector.get("confidence"),
        "medical_detector_confidence_score": medical_detector.get("confidence_score"),
        "medical_detector_provenance_notes_json": _json_array(medical_detector.get("provenance_notes") or []),
    }
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
