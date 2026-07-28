#!/usr/bin/env python3
"""Deterministic behavior-parity tests using scenario invariants.

These tests bypass the LLM-based intent classifier and feed synthetic
ClassificationResult objects into select_route. This keeps the suite fast and
independent of Ollama while still verifying that the routing logic in the split
modules behaves consistently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.deterministic]

SCENARIO_PATH = Path(__file__).resolve().parent / "fixtures" / "split_parity_scenarios.yaml"


def _load_scenarios():
    with open(SCENARIO_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["scenarios"]


SCENARIOS = _load_scenarios()


def _make_classification(scenario_classification: dict) -> object:
    """Build a ClassificationResult from scenario data."""
    from router_py.request_types import ClassificationResult

    fields = {
        "intent": scenario_classification["intent"],
        "intent_family": scenario_classification["intent_family"],
        "intent_class": scenario_classification.get("intent_class", ""),
        "category": scenario_classification.get("category", ""),
        "confidence": scenario_classification.get("confidence", 0.0),
        "needs_web": scenario_classification.get("needs_web", False),
        "needs_memory": scenario_classification.get("needs_memory", False),
        "needs_synthesis": scenario_classification.get("needs_synthesis", False),
        "clarify_required": scenario_classification.get("clarify_required", False),
        "evidence_mode": scenario_classification.get("evidence_mode", ""),
        "evidence_reason": scenario_classification.get("evidence_reason", ""),
        "augmentation_recommended": scenario_classification.get(
            "augmentation_recommended", False
        ),
        "force_local": scenario_classification.get("force_local", False),
        "manifest_version": scenario_classification.get("manifest_version", ""),
        "selected_route": scenario_classification.get("selected_route", ""),
        "allowed_routes": scenario_classification.get("allowed_routes", []),
        "forbidden_routes": scenario_classification.get("forbidden_routes", []),
        "surface": scenario_classification.get("surface", "cli"),
        "raw_plan": scenario_classification.get("raw_plan", {}),
    }
    return ClassificationResult(**fields)


@pytest.fixture(autouse=True)
def _disable_ollama_arbiter(monkeypatch):
    """Keep tests deterministic by preventing any Ollama arbiter call."""
    import router_py.classify_core.select as select

    monkeypatch.setattr(select, "_call_llm_arbiter", lambda query: None)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s["id"])
def test_routing_scenario(scenario: dict):
    """A scenario must produce the expected route and side-effect invariants."""
    from router_py.classify import select_route

    classification = _make_classification(scenario["classification"])
    query = scenario["query"]
    forced_mode = scenario.get("forced_mode")

    decision = select_route(
        classification,
        query=query,
        forced_mode=forced_mode,
    )

    if "expected_route" in scenario:
        assert decision.route == scenario["expected_route"], (
            f"{scenario['id']}: expected {scenario['expected_route']}, got {decision.route}"
        )

    if "expected_route_pattern" in scenario:
        assert re.fullmatch(scenario["expected_route_pattern"], decision.route), (
            f"{scenario['id']}: route {decision.route} does not match pattern"
        )

    if "forbidden_route" in scenario:
        assert decision.route != scenario["forbidden_route"], (
            f"{scenario['id']}: route {decision.route} is forbidden"
        )

    if "required_evidence_mode" in scenario:
        assert decision.evidence_mode == scenario["required_evidence_mode"], (
            f"{scenario['id']}: evidence mode {decision.evidence_mode} != "
            f"{scenario['required_evidence_mode']}"
        )
