#!/usr/bin/env python3
"""Contextual and local policy resolution for the plan-to-pipeline CLI.

This module holds the contextual/local policy logic that used to live inline
in ``plan_to_pipeline_cli.py``:

* Contextual followup resolution
* Local context response resolution
* Pet food policy resolution
* Local response ID matching
* Media-reliability contextual followup plan patching
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.core.contextual_policy import resolve_contextual_followup
from router_py.core.local_context_policy import resolve_local_context_response
from router_py.core.local_policy import match_local_response_id
from router_py.core.pet_food_policy import resolve_pet_food_policy

from router_py.planner.plan_builder import _patch_classification_for_effective_plan


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


def resolve_contextual_followup_for_question(
    original_question: str, root_dir: str
) -> Dict[str, object] | None:
    """Resolve a contextual followup for ``original_question``.

    This is a thin wrapper around ``router_py.core.contextual_policy`` so the
    CLI facade imports contextual policy logic from this module.
    """
    return resolve_contextual_followup(original_question, root_dir)


def apply_contextual_policies(
    plan: Dict[str, object],
    effective_plan: Dict[str, object],
    original_question: str,
    question_for_execution: str,
    root_dir: str,
    *,
    contextual_followup_kind: str = "",
    route_reason_override: str = "",
    outcome_code_override: str = "",
) -> Tuple[
    Dict[str, object],
    Dict[str, object],
    str,
    str,
    Optional[str],
    str,
    str,
    str,
    bool,
]:
    """Apply local-context, pet-food, and local-response policies.

    Args:
        plan: The classified plan.
        effective_plan: The effective plan built by ``build_effective_plan``.
        original_question: The user's original query.
        question_for_execution: The query after contextual followup resolution.
        root_dir: Project/runtime root directory.
        contextual_followup_kind: Kind of contextual followup, if any.
        route_reason_override: Existing route reason override.
        outcome_code_override: Existing outcome code override.

    Returns:
        A tuple of
        ``(plan, effective_plan, route_reason_override, outcome_code_override,
           local_response_text, local_response_operator_override, knowledge_path,
           local_response_id_hint, proven_local_capability)``.
    """
    local_response_text = None
    local_response_operator_override = ""
    knowledge_path = ""

    if contextual_followup_kind == "media_reliability":
        effective_plan = _media_reliability_local_plan()
        plan = _patch_classification_for_effective_plan(plan, effective_plan)

    if original_question:
        local_context_resolution = resolve_local_context_response(original_question, root_dir)
        if local_context_resolution:
            route_reason_override = str(
                local_context_resolution.get("route_reason_override") or route_reason_override
            )
            outcome_code_override = str(
                local_context_resolution.get("outcome_code_override") or outcome_code_override
            )
            local_response_text = str(local_context_resolution.get("local_response_text") or "")
            local_response_operator_override = str(
                local_context_resolution.get("operator_override")
                or "governor_local_context_response"
            )

    if original_question and str(effective_plan.get("intent") or "") == "PET_FOOD":
        pet_food_resolution = resolve_pet_food_policy(root_dir, question_for_execution)
        if pet_food_resolution:
            knowledge_path = str(pet_food_resolution.get("knowledge_path") or "")
            route_reason_override = str(
                pet_food_resolution.get("route_reason_override") or route_reason_override
            )
            outcome_code_override = str(pet_food_resolution.get("outcome_code_override") or "")
            if pet_food_resolution.get("matched"):
                local_response_text = str(pet_food_resolution.get("local_response_text") or "")
                local_response_operator_override = "governor_pet_food_knowledge"
            else:
                effective_plan = _pet_food_medical_plan()
                plan = _patch_classification_for_effective_plan(plan, effective_plan)

    local_response_id_hint = match_local_response_id(
        question_for_execution or original_question,
        str(effective_plan.get("intent") or plan.get("intent") or ""),
    )

    proven_local_capability = bool(
        local_response_text
        or local_response_id_hint
        or str(plan.get("intent_class") or "").strip().lower()
        in {"conversational", "identity_personal"}
    )

    return (
        plan,
        effective_plan,
        route_reason_override,
        outcome_code_override,
        local_response_text,
        local_response_operator_override,
        knowledge_path,
        local_response_id_hint or "",
        proven_local_capability,
    )
