#!/usr/bin/env python3
"""Adversarial threshold tests for escalation and auto-web-fetch features.

These tests guard against accuracy regressions where a confident local-only
question would be labelled "thin" and trigger an unwanted web-escalation
suggestion or an automatic web fetch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.escalation.fetcher import FetchResult
from router_py.request_types import ClassificationResult, RouterOutcome, RoutingDecision, SourceAttribution


def _decision(route: str = "LOCAL") -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="local_knowledge",
        confidence=0.5,
        provider="local" if route == "LOCAL" else "news",
        provider_usage_class="local" if route == "LOCAL" else "news",
        evidence_mode="",
    )


def _classification(*, confidence: float = 0.9, needs_web: bool = False) -> ClassificationResult:
    return ClassificationResult(
        intent="general",
        intent_family="local_knowledge",
        intent_class="local_knowledge",
        category="general",
        confidence=confidence,
        needs_web=needs_web,
    )


def _run_process(
    classification: ClassificationResult,
    decision: RoutingDecision,
    attribution: SourceAttribution | None = None,
):
    from router_py.request_pipeline import process

    if attribution is None:
        attribution = SourceAttribution(basis="local", confidence="medium", sources=[])

    exec_result = MagicMock(
        status="completed",
        outcome_code="answered",
        route=decision.route,
        provider=decision.provider,
        provider_usage_class=decision.provider_usage_class,
        response_text="A local answer.",
        error_message="",
        execution_time_ms=10,
        metadata={},
        evidence_reason="",
        policy_reason="",
    )

    with patch("router_py.request_pipeline.execute.execute_request", return_value=exec_result), \
         patch("router_py.request_pipeline.outcome.build_source_attribution", return_value=attribution), \
         patch("router_py.request_pipeline.fetcher.fetch_general_knowledge") as mock_fetch:
        mock_fetch.return_value = FetchResult(url="", title="", snippet="", source_type="web_untrusted")
        outcome, _, _ = process(
            "test question",
            surface="cli",
            timeout=10,
            classification=classification,
            decision=decision,
        )
        return outcome, mock_fetch


class TestEscalationThresholds:
    """High-confidence local answers must not trigger escalation or web fetch."""

    @pytest.fixture(autouse=True)
    def _enable_flags(self, monkeypatch):
        monkeypatch.setenv("LUCY_SOURCE_ATTRIBUTION", "1")
        monkeypatch.setenv("LUCY_SUGGEST_WEB_ESCALATION", "1")
        monkeypatch.setenv("LUCY_AUTO_WEB_GENERAL_KNOWLEDGE", "1")
        monkeypatch.setenv("LUCY_TRUSTED_SOURCES_ONLY_CRITICAL", "1")

    @pytest.mark.parametrize("confidence", [0.9, 0.7, 0.56])
    def test_high_confidence_local_does_not_escalate(self, confidence: float):
        classification = _classification(confidence=confidence)
        decision = _decision("LOCAL")
        outcome, _ = _run_process(classification, decision)
        assert outcome.escalation_suggestion == ""

    @pytest.mark.parametrize("confidence", [0.9, 0.7, 0.56])
    def test_high_confidence_local_does_not_auto_fetch(self, confidence: float):
        classification = _classification(confidence=confidence)
        decision = _decision("LOCAL")
        _, mock_fetch = _run_process(classification, decision)
        assert mock_fetch.call_count == 0

    def test_low_confidence_local_triggers_escalation(self):
        classification = _classification(confidence=0.3)
        decision = _decision("LOCAL")
        outcome, _ = _run_process(classification, decision)
        assert outcome.escalation_suggestion != ""
        assert "web" in outcome.escalation_suggestion.lower()

    def test_low_confidence_local_triggers_auto_fetch(self):
        classification = _classification(confidence=0.3)
        decision = _decision("LOCAL")
        _, mock_fetch = _run_process(classification, decision)
        assert mock_fetch.call_count == 1

    def test_evidence_backed_local_does_not_escalate_despite_low_classifier_confidence(self):
        classification = _classification(confidence=0.3)
        decision = _decision("LOCAL")
        attribution = SourceAttribution(basis="local", confidence="high", sources=[])
        outcome, mock_fetch = _run_process(classification, decision, attribution=attribution)
        assert outcome.escalation_suggestion == ""
        assert mock_fetch.call_count == 0

    def test_basis_none_still_triggers_fetch_for_legacy_or_disabled_attribution(self):
        classification = _classification(confidence=0.9)
        decision = _decision("LOCAL")
        attribution = SourceAttribution(basis="none", confidence="unknown", sources=[])
        _, mock_fetch = _run_process(classification, decision, attribution=attribution)
        assert mock_fetch.call_count == 1

    def test_non_local_route_does_not_auto_fetch(self):
        classification = _classification(confidence=0.3)
        decision = _decision("NEWS")
        outcome, mock_fetch = _run_process(classification, decision)
        assert outcome.escalation_suggestion == ""
        assert mock_fetch.call_count == 0
