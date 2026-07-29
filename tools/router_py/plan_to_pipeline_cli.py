#!/usr/bin/env python3
"""Frozen router/governor baseline.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and semantic-interpreter routing
authority must not be expanded casually.

This module is now a thin facade: plan construction, policy resolution, and
news-query rewriting live in ``router_py.planner`` submodules.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict

MODULE_IMPORT_START = time.perf_counter()

THIS_DIR = Path(__file__).resolve().parent
AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"
TOOLS_DIR = THIS_DIR.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.intent_classifier import classify_question
from router_py.core.medical_query_heuristics import detect_human_medication_query
from router_py.core.policy_router import route_intent
from router_py.core.route_manifest import build_route_manifest
from router_py.core.runtime_governor import build_execution_contract
from router_py.core.semantic_interpreter import maybe_interpret_question

from router_py.planner.news_rewriter import rewrite_news_query
from router_py.planner.plan_builder import (
    _apply_semantic_interpretation,
    _json_array,
    _legacy_plan,
    _semantic_trace,
    build_effective_plan,
)
from router_py.planner.policy_resolver import (
    apply_contextual_policies,
    resolve_contextual_followup_for_question,
)


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


def _root_dir() -> str:
    override = (os.environ.get(AUTHORITY_ROOT_ENV) or "").strip()
    if override:
        return str(Path(override).expanduser().resolve())
    return str(THIS_DIR.parent.parent)


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
    _append_latency(
        "resolve_root_dir", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )
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
        followup = resolve_contextual_followup_for_question(original_question, root_dir)
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
    _append_latency(
        "contextual_followup", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )

    stage_start = time.perf_counter()
    semantic_trace = maybe_interpret_question(question_for_execution or original_question, plan)
    semantic_trace["original_query"] = original_question
    semantic_trace["resolved_execution_query"] = question_for_execution or original_question
    _append_latency(
        "semantic_interpreter", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )

    stage_start = time.perf_counter()
    medical_detector = detect_human_medication_query(question_for_execution or original_question)
    medical_detector["original_query"] = original_question
    medical_detector["resolved_execution_query"] = question_for_execution or original_question
    _append_latency(
        "medical_detector", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )

    stage_start = time.perf_counter()
    plan = _apply_semantic_interpretation(
        plan, question_for_execution or original_question, semantic_trace
    )
    _append_latency(
        "semantic_plan_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )

    base_plan = _legacy_plan(plan)

    stage_start = time.perf_counter()
    effective_plan = build_effective_plan(plan, route_prefix)
    _append_latency(
        "route_prefix_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )

    stage_start = time.perf_counter()
    (
        plan,
        effective_plan,
        route_reason_override,
        outcome_code_override,
        local_response_text,
        local_response_operator_override,
        knowledge_path,
        local_response_id_hint,
        proven_local_capability,
    ) = apply_contextual_policies(
        plan=plan,
        effective_plan=effective_plan,
        original_question=original_question,
        question_for_execution=question_for_execution,
        root_dir=root_dir,
        contextual_followup_kind=contextual_followup_kind,
        route_reason_override=route_reason_override,
        outcome_code_override=outcome_code_override,
    )
    _append_latency(
        "contextual_plan_patch", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )
    _append_latency(
        "local_context_resolution", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )
    _append_latency(
        "pet_food_policy", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )
    _append_latency(
        "local_response_match", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
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
        and (
            semantic_trace.get("normalized_candidates")
            or semantic_trace.get("retrieval_candidates")
        )
    )
    semantic_trace["forward_candidates"] = semantic_forward_candidates
    if str(route_decision.get("route_mode") or "").upper() == "NEWS":
        rewritten_news_question = rewrite_news_query(question_for_execution)
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
    manifest_selected_route = str(
        route_decision.get("force_mode") or route_decision.get("route_mode") or ""
    )
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
            route_decision.get("policy_base_recommended_route")
            or route_decision.get("policy_recommended_route")
            or manifest_selected_route
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
    _append_latency(
        "route_manifest", max(1, int(round((time.perf_counter() - stage_start) * 1000)))
    )
    governor_start = time.perf_counter()
    execution_contract = build_execution_contract(
        plan=plan,
        effective_plan=effective_plan,
        route_decision=route_decision,
        route_manifest=route_manifest,
        question=question_for_execution,
        resolved_question=question_for_execution
        if question_for_execution != original_question
        else "",
        local_response_text=local_response_text,
        route_control_mode=route_control_mode,
        route_prefix=route_prefix,
        surface=args.surface,
    )
    governor_ms = max(1, int(round((time.perf_counter() - governor_start) * 1000)))
    _append_latency("runtime_governor", governor_ms)
    _append_latency(
        "module_import_and_init", max(1, int(round((main_start - MODULE_IMPORT_START) * 1000)))
    )
    _append_latency(
        "main_body_total", max(1, int(round((time.perf_counter() - main_start) * 1000)))
    )
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
        "resolved_question": question_for_execution
        if question_for_execution != original_question
        else "",
        "contextual_followup_applied": contextual_followup_applied,
        "contextual_followup_kind": contextual_followup_kind,
        "route_reason_override": route_reason_override,
        "knowledge_path": knowledge_path,
        "outcome_code_override": outcome_code_override,
        "semantic_interpreter": semantic_trace,
        "semantic_interpreter_fired": semantic_trace.get("interpreter_fired"),
        "semantic_interpreter_original_query": semantic_trace.get("original_query"),
        "semantic_interpreter_resolved_execution_query": semantic_trace.get(
            "resolved_execution_query"
        ),
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
        "semantic_interpreter_selected_normalized_query": semantic_trace.get(
            "selected_normalized_query"
        ),
        "semantic_interpreter_selected_retrieval_query": semantic_trace.get(
            "selected_retrieval_query"
        ),
        "semantic_interpreter_normalized_candidates_csv": ",".join(
            semantic_trace.get("normalized_candidates") or []
        ),
        "semantic_interpreter_retrieval_candidates_csv": ",".join(
            semantic_trace.get("retrieval_candidates") or []
        ),
        "semantic_interpreter_normalized_candidates_json": _json_array(
            semantic_trace.get("normalized_candidates") or []
        ),
        "semantic_interpreter_retrieval_candidates_json": _json_array(
            semantic_trace.get("retrieval_candidates") or []
        ),
        "medical_detector": medical_detector,
        "medical_detector_fired": medical_detector.get("detector_fired"),
        "medical_detector_original_query": medical_detector.get("original_query"),
        "medical_detector_resolved_execution_query": medical_detector.get(
            "resolved_execution_query"
        ),
        "medical_detector_detection_source": medical_detector.get("detection_source"),
        "medical_detector_pattern_family": medical_detector.get("pattern_family"),
        "medical_detector_candidate_medication": medical_detector.get("candidate_medication"),
        "medical_detector_normalized_candidate": medical_detector.get("normalized_candidate"),
        "medical_detector_normalized_query": medical_detector.get("normalized_query"),
        "medical_detector_confidence": medical_detector.get("confidence"),
        "medical_detector_confidence_score": medical_detector.get("confidence_score"),
        "medical_detector_provenance_notes_json": _json_array(
            medical_detector.get("provenance_notes") or []
        ),
    }
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
