#!/usr/bin/env python3
"""Tests for conservative escalation suggestion logic."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.escalation.suggestion import suggest_escalation
from router_py.pipeline.config import CapabilityFlags
from router_py.request_types import ClassificationResult, RoutingDecision, SourceAttribution


def _classification(
    *,
    category: str = "factual",
    needs_web: bool = False,
    confidence: float = 0.8,
) -> ClassificationResult:
    return ClassificationResult(
        intent="general",
        intent_family="factual",
        intent_class="general",
        category=category,
        confidence=confidence,
        needs_web=needs_web,
    )


def _decision(route: str = "LOCAL") -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )


def _attribution(basis: str = "local", confidence: str = "medium") -> SourceAttribution:
    return SourceAttribution(basis=basis, confidence=confidence)


@pytest.mark.parametrize("enabled", [False, None])
def test_suggestion_disabled_when_flag_off_or_missing(enabled: bool | None):
    flags = CapabilityFlags(suggest_web_escalation=False) if enabled is False else None
    classification = _classification()
    decision = _decision("LOCAL")
    attribution = _attribution("none", "unknown")
    assert suggest_escalation(classification, decision, attribution, flags) == ""


def test_non_local_route_never_suggests():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(needs_web=True)
    for route in ("AUGMENTED", "EVIDENCE", "NEWS", "MEMORY_RECALL"):
        decision = _decision(route)
        assert suggest_escalation(classification, decision, _attribution("none"), flags) == ""


@pytest.mark.parametrize(
    "category",
    [
        "medical",
        "financial",
        "legal",
        "safety",
        "identity",
        "medical_veterinary",
        "travel_advisory",
        "identity_personal",
        "regulatory",
        "market",
        "economics_concept",
    ],
)
def test_critical_categories_never_suggest(category: str):
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(category=category, needs_web=True)
    decision = _decision("LOCAL")
    attribution = _attribution("none", "unknown")
    assert suggest_escalation(classification, decision, attribution, flags) == ""


def test_local_basis_none_suggests_general_knowledge():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification()
    decision = _decision("LOCAL")
    attribution = _attribution("none", "unknown")
    suggestion = suggest_escalation(classification, decision, attribution, flags)
    assert suggestion != ""
    assert "web" in suggestion.lower()


def test_local_confidence_low_suggests_general_knowledge():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification()
    decision = _decision("LOCAL")
    attribution = _attribution("local", "low")
    suggestion = suggest_escalation(classification, decision, attribution, flags)
    assert suggestion != ""
    assert "web" in suggestion.lower()


def test_local_needs_web_suggests_current_info():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(needs_web=True)
    decision = _decision("LOCAL")
    attribution = _attribution("local", "medium")
    suggestion = suggest_escalation(classification, decision, attribution, flags)
    assert suggestion != ""
    assert "web" in suggestion.lower()


def test_local_good_attribution_does_not_suggest():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(needs_web=False)
    decision = _decision("LOCAL")
    attribution = _attribution("local", "medium")
    assert suggest_escalation(classification, decision, attribution, flags) == ""


def test_local_no_attribution_but_needs_web_suggests():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(needs_web=True)
    decision = _decision("LOCAL")
    assert suggest_escalation(classification, decision, None, flags) != ""


def test_local_no_attribution_and_no_needs_web_does_not_suggest():
    flags = CapabilityFlags(suggest_web_escalation=True)
    classification = _classification(needs_web=False)
    decision = _decision("LOCAL")
    assert suggest_escalation(classification, decision, None, flags) == ""


def test_build_outcome_populates_escalation_suggestion_when_flag_enabled():
    """Integration check that build_outcome wires suggestion into RouterOutcome."""
    from router_py.pipeline.outcome import build_outcome
    from router_py.request_types import ExecutionResult

    classification = _classification(needs_web=True)
    decision = _decision("LOCAL")
    result = ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="answer",
        metadata={},
    )
    flags = CapabilityFlags(source_attribution=True, suggest_web_escalation=True)
    outcome = build_outcome(result, classification, decision, 0.0, None, flags=flags)
    assert outcome.escalation_suggestion != ""
    assert "web" in outcome.escalation_suggestion.lower()


def test_build_outcome_leaves_escalation_suggestion_empty_when_flag_disabled():
    """Default behaviour keeps escalation_suggestion empty."""
    from router_py.pipeline.outcome import build_outcome
    from router_py.request_types import ExecutionResult

    classification = _classification(needs_web=True)
    decision = _decision("LOCAL")
    result = ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="answer",
        metadata={},
    )
    flags = CapabilityFlags(source_attribution=True, suggest_web_escalation=False)
    outcome = build_outcome(result, classification, decision, 0.0, None, flags=flags)
    assert outcome.escalation_suggestion == ""
