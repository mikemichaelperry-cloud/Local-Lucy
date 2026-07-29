#!/usr/bin/env python3
"""Argparse and JSON output wrapper for the plan-to-pipeline CLI.

This module holds the argparse handling, orchestration, latency profiling, and
JSON printing that used to live inline in ``plan_to_pipeline_cli.py``. It
delegates execution-contract and output-dict assembly to
``router_py.planner.contract_builder``.
"""

from __future__ import annotations

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
TOOLS_DIR = THIS_DIR.parent.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.intent_classifier import classify_question
from router_py.core.medical_query_heuristics import detect_human_medication_query
from router_py.core.policy_router import route_intent
from router_py.core.route_manifest import build_route_manifest
from router_py.core.semantic_interpreter import maybe_interpret_question

from router_py.planner.contract_builder import build_contract
from router_py.planner.news_rewriter import rewrite_news_query
from router_py.planner.plan_builder import (
    _apply_semantic_interpretation,
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
    return str(THIS_DIR.parent.parent.parent)


def run_cli(argv=None) -> int:
    main_start = time.perf_counter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", required=True)
    parser.add_argument("--question", default="")
    parser.add_argument("--route-prefix", default="")
    parser.add_argument("--route-control-mode", default="AUTO")
    parser.add_argument("--surface", default=os.environ.get("LUCY_SURFACE", "cli"))
    args = parser.parse_args(argv)

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
        _policy_timings,
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
    _append_latency("contextual_plan_patch", _policy_timings.get("contextual_plan_patch", 1))
    _append_latency(
        "local_context_resolution", _policy_timings.get("local_context_resolution", 1)
    )
    _append_latency("pet_food_policy", _policy_timings.get("pet_food_policy", 1))
    _append_latency("local_response_match", _policy_timings.get("local_response_match", 1))

    router_input: Dict[str, object] = dict(plan)
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

    resolved_question = (
        question_for_execution if question_for_execution != original_question else ""
    )

    governor_start = time.perf_counter()
    output = build_contract(
        plan=plan,
        effective_plan=effective_plan,
        route_decision=route_decision,
        route_manifest=route_manifest,
        question=question_for_execution,
        resolved_question=resolved_question,
        local_response_text=local_response_text,
        route_control_mode=route_control_mode,
        route_prefix=route_prefix,
        surface=args.surface,
        base_plan=base_plan,
        original_question=original_question,
        route_reason_override=route_reason_override,
        knowledge_path=knowledge_path,
        outcome_code_override=outcome_code_override,
        contextual_followup_applied=contextual_followup_applied,
        contextual_followup_kind=contextual_followup_kind,
        semantic_trace=semantic_trace,
        medical_detector=medical_detector,
    )
    governor_ms = max(1, int(round((time.perf_counter() - governor_start) * 1000)))
    _append_latency("runtime_governor", governor_ms)
    _append_latency(
        "module_import_and_init", max(1, int(round((main_start - MODULE_IMPORT_START) * 1000)))
    )
    _append_latency(
        "main_body_total", max(1, int(round((time.perf_counter() - main_start) * 1000)))
    )

    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0
