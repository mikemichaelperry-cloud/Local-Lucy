#!/usr/bin/env python3
"""Short demo test for the new v11 pipeline features.

Run with:
    python -m pytest tools/router_py/test_new_features_demo.py -v
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


def _make_outcome(
    route="LOCAL",
    response_text="Test response.",
    outcome_code="answered",
    metadata=None,
) -> MagicMock:
    return MagicMock(
        status="completed",
        outcome_code=outcome_code,
        route=route,
        provider="local" if route == "LOCAL" else "news",
        provider_usage_class="local" if route == "LOCAL" else "news",
        intent_family="local_knowledge",
        confidence=0.9,
        response_text=response_text,
        error_message="",
        execution_time_ms=50,
        metadata=metadata or {},
        evidence_reason="",
        policy_reason="",
    )


def _run_process(question: str, classification=None, decision=None):
    from router_py.request_pipeline import process

    return process(question, surface="cli", timeout=10, classification=classification, decision=decision)


class TestNewFeaturesDemo:
    """Demonstrate source attribution, escalation suggestion, web fetch, and critical guard."""

    @pytest.fixture(autouse=True)
    def _enable_flags(self, monkeypatch):
        monkeypatch.setenv("LUCY_SOURCE_ATTRIBUTION", "1")
        monkeypatch.setenv("LUCY_SUGGEST_WEB_ESCALATION", "1")
        monkeypatch.setenv("LUCY_AUTO_WEB_GENERAL_KNOWLEDGE", "1")
        monkeypatch.setenv("LUCY_TRUSTED_SOURCES_ONLY_CRITICAL", "1")

    def test_source_attribution_attached(self):
        with patch("router_py.request_pipeline.execute.execute_request") as mock_exec:
            mock_exec.return_value = _make_outcome(
                route="LOCAL",
                response_text="The capital of France is Paris.",
            )
            outcome, _, _ = _run_process("What is the capital of France?")

        assert isinstance(outcome, RouterOutcome)
        assert outcome.source_attribution is not None
        assert outcome.source_attribution.basis == "local"
        print(f"\n[source_attribution] basis={outcome.source_attribution.basis!r} "
              f"confidence={outcome.source_attribution.confidence!r} "
              f"trust_label={outcome.trust_label!r}")

    def test_escalation_suggestion_for_thin_local_question(self):
        classification = ClassificationResult(
            intent="general",
            intent_family="local_knowledge",
            intent_class="local_knowledge",
            confidence=0.4,
            category="general",
        )
        decision = RoutingDecision(
            route="LOCAL",
            mode="AUTO",
            intent_family="local_knowledge",
            confidence=0.4,
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
        )
        thin_attribution = SourceAttribution(basis="none", sources=[], confidence="unknown")
        with patch("router_py.request_pipeline.execute.execute_request") as mock_exec, \
             patch("router_py.request_pipeline.outcome.build_source_attribution", return_value=thin_attribution), \
             patch("router_py.request_pipeline.fetcher.fetch_general_knowledge") as mock_fetch:
            mock_exec.return_value = _make_outcome(
                route="LOCAL",
                response_text="I am not sure.",
            )
            mock_fetch.return_value = FetchResult(url="", title="", snippet="", source_type="web_untrusted")
            outcome, _, _ = _run_process(
                "What is the rarest chemical element in the universe?",
                classification=classification,
                decision=decision,
            )

        assert outcome.escalation_suggestion
        assert "web" in outcome.escalation_suggestion.lower()
        print(f"\n[escalation_suggestion] {outcome.escalation_suggestion!r}")

    def test_general_knowledge_web_fetch(self):
        classification = ClassificationResult(
            intent="general",
            intent_family="local_knowledge",
            intent_class="local_knowledge",
            confidence=0.4,
            category="general",
        )
        decision = RoutingDecision(
            route="LOCAL",
            mode="AUTO",
            intent_family="local_knowledge",
            confidence=0.4,
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
        )
        thin_attribution = SourceAttribution(basis="none", sources=[], confidence="unknown")
        with patch("router_py.request_pipeline.execute.execute_request") as mock_exec, \
             patch("router_py.request_pipeline.outcome.build_source_attribution", return_value=thin_attribution), \
             patch("router_py.request_pipeline.fetcher.fetch_general_knowledge") as mock_fetch:
            mock_exec.return_value = _make_outcome(
                route="LOCAL",
                response_text="I am not sure.",
            )
            mock_fetch.return_value = MagicMock(
                url="https://example.com/rarest-element",
                title="Rarest Element",
                snippet="Astatine is one of the rarest naturally occurring elements.",
                source_type="web_untrusted",
            )
            outcome, _, _ = _run_process(
                "What is the rarest chemical element in the universe?",
                classification=classification,
                decision=decision,
            )

        mock_fetch.assert_called_once()
        assert "[untrusted source title redacted]" in outcome.escalation_suggestion
        assert "example.com" in outcome.escalation_suggestion
        assert "rarest-element" not in outcome.escalation_suggestion
        print(f"\n[web_fetch] suggestion={outcome.escalation_suggestion!r}")

    def test_critical_category_blocked_from_web(self):
        classification = ClassificationResult(
            intent="MEDICAL_INFO",
            intent_family="medical_info",
            intent_class="evidence_check",
            confidence=0.95,
            category="medical",
        )
        decision = RoutingDecision(
            route="NEWS",
            mode="AUTO",
            intent_family="current_fact",
            confidence=0.95,
            provider="news",
            provider_usage_class="news",
            evidence_mode="",
        )
        with patch("router_py.request_pipeline.execute.execute_request") as mock_exec, \
             patch("router_py.request_pipeline.fetcher.fetch_general_knowledge") as mock_fetch:
            outcome, _, _ = _run_process(
                "What are the side effects of ibuprofen?",
                classification=classification,
                decision=decision,
            )

        mock_fetch.assert_not_called()
        mock_exec.assert_not_called()
        assert outcome.outcome_code == "operator_blocked"
        print(f"\n[critical_guard] route={outcome.route!r} outcome_code={outcome.outcome_code!r} "
              f"response_text={outcome.response_text!r}")
