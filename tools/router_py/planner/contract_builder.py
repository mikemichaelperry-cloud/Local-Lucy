#!/usr/bin/env python3
"""Execution contract building and JSON-ready output assembly.

This module holds the contract-building and output-assembly logic that used to
live inline in ``plan_to_pipeline_cli.py``. It calls the runtime governor and
produces the exact dict that the CLI serializes to JSON.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict

# Ensure tools package is importable when this module is loaded directly.
TOOLS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.runtime_governor import build_execution_contract
from router_py.planner.plan_builder import _json_array


def build_contract(
    plan: Dict[str, object],
    effective_plan: Dict[str, object],
    route_decision: Dict[str, object],
    route_manifest: Dict[str, object],
    question: str,
    resolved_question: str,
    local_response_text: str | None,
    route_control_mode: str,
    route_prefix: str,
    surface: str,
    *,
    base_plan: Dict[str, object],
    original_question: str,
    route_reason_override: str,
    knowledge_path: str,
    outcome_code_override: str,
    contextual_followup_applied: bool,
    contextual_followup_kind: str,
    semantic_trace: Dict[str, object],
    medical_detector: Dict[str, object],
) -> Dict[str, object]:
    """Build the execution contract and the full CLI output dictionary."""
    compatibility_route = str(route_manifest.get("selected_route") or "").strip().upper()
    compatibility_policy_route = compatibility_route.lower()

    execution_contract = build_execution_contract(
        plan=plan,
        effective_plan=effective_plan,
        route_decision=route_decision,
        route_manifest=route_manifest,
        question=question,
        resolved_question=resolved_question,
        local_response_text=local_response_text,
        route_control_mode=route_control_mode,
        route_prefix=route_prefix,
        surface=surface,
    )

    return {
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
        "surface": route_decision.get("surface") or surface,
        "mixed_intent": route_decision.get("mixed_intent"),
        "manifest_version": route_manifest.get("manifest_version"),
        "manifest_selected_route": route_manifest.get("selected_route"),
        "manifest_winning_signal": route_manifest.get("winning_signal"),
        "manifest_authority_basis": route_manifest.get("authority_basis"),
        "resolved_question": resolved_question,
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
