#!/usr/bin/env python3
"""Tests for global travel routing and trusted-source handling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.classify import select_route
from router_py.core.intent_classifier import classify_question
from router_py.escalation.critical_guard import get_trusted_domains_file
from router_py.pipeline.config import CapabilityFlags
from router_py.pipeline.route import apply_critical_source_policy
from router_py.request_types import ClassificationResult, RoutingDecision


def _classification(category: str, evidence_reason: str = "") -> ClassificationResult:
    return ClassificationResult(
        intent="general",
        intent_family="factual",
        intent_class="evidence_check",
        category=category,
        confidence=0.92,
        evidence_reason=evidence_reason,
    )


def _decision(route: str = "LOCAL", provider: str = "local") -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.92,
        provider=provider,
        provider_usage_class="local" if provider == "local" else "free",
        evidence_mode="",
        evidence_reason="",
    )


def _trusted_flags() -> CapabilityFlags:
    return CapabilityFlags(trusted_sources_only_critical=True)


@pytest.mark.parametrize(
    "query",
    [
        "Best places to visit in France",
        "What should I see in Japan?",
        "Travel guide to Italy",
        "Where should I go in Thailand?",
        "interesting places to visit in Israel",
        "Is it safe to travel to Turkey?",
    ],
)
def test_classifier_recognises_travel_advisory(query: str):
    result = classify_question(query)
    assert result["category"] == "travel_advisory"
    assert result["subcategory"] == "travel_advisory"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("What is the capital of Italy?", "general"),
        ("Weather in Tokyo", "current_fact"),
        ("News from Paris", "news_world"),
        ("War in Ukraine", "general"),
    ],
)
def test_classifier_does_not_misroute_non_travel(query: str, expected: str):
    result = classify_question(query)
    assert result["category"] != "travel_advisory"
    assert result["category"] == expected


def test_router_routes_travel_to_augmented_then_policy_forces_evidence():
    classification = _classification("travel_advisory")
    decision = select_route(classification, policy="fallback_only", query="Where should I go in Thailand?")
    assert decision.route == "AUGMENTED"

    flags = _trusted_flags()
    final = apply_critical_source_policy(decision, classification, flags=flags)
    assert isinstance(final, RoutingDecision)
    assert final.route == "EVIDENCE"
    assert final.provider == "trusted"


def test_critical_source_policy_blocks_untrusted_travel():
    flags = _trusted_flags()
    decision = _decision("AUGMENTED", provider="kimi")
    classification = _classification("travel_advisory")
    result = apply_critical_source_policy(decision, classification, flags=flags)
    assert isinstance(result, RoutingDecision)
    assert result.route == "EVIDENCE"
    assert result.provider == "trusted"
    assert result.policy_reason == "critical_trusted_sources_only"


def test_travel_allowlist_exists():
    classification = _classification("travel_advisory")
    path = get_trusted_domains_file(classification)
    assert path is not None
    assert path.exists()


def test_travel_destination_extraction():
    from unverified_context_trusted import _extract_travel_destination

    assert _extract_travel_destination("What should I see in Japan?") == "Japan"
    assert _extract_travel_destination("Best places to visit in France") == "France"
    assert _extract_travel_destination("Travel guide to Italy") == "Italy"
    assert _extract_travel_destination("Where should I go in Thailand?") == "Thailand"
    assert _extract_travel_destination("Weather in Paris") is None
    assert _extract_travel_destination("News from Japan") is None


def test_travel_provider_returns_wikivoyage_content(monkeypatch):
    from router_py.providers.evidence import fetch_trusted_evidence

    monkeypatch.setattr(
        "unverified_context_trusted._fetch_json",
        lambda url, timeout: {"extract": "France travel guide", "title": "France"},
    )

    route = RoutingDecision(
        route="EVIDENCE",
        mode="AUTO",
        intent_family="factual",
        confidence=0.92,
        provider="trusted",
        provider_usage_class="free",
        evidence_mode="required",
        evidence_reason="travel_advisory",
        requires_evidence=True,
    )

    async def _run():
        return await fetch_trusted_evidence("Best places to visit in France", route)

    import asyncio

    evidence = asyncio.run(_run())
    assert evidence is not None
    assert evidence["provider"] == "trusted"
    assert "France" in evidence.get("context", "")
    assert "wikivoyage.org" in evidence.get("context", "").lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
