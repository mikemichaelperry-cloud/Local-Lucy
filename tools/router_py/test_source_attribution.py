#!/usr/bin/env python3
"""Tests for pipeline source attribution rules."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.pipeline.attribution import (
    build_source_attribution,
    build_trust_label,
)
from router_py.pipeline.config import CapabilityFlags
from router_py.request_types import ExecutionResult, RoutingDecision, SourceAttribution


def _decision(route: str, evidence_reason: str = "") -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
        evidence_reason=evidence_reason,
    )


def _result(route: str, metadata: dict | None = None) -> ExecutionResult:
    return ExecutionResult(
        status="completed",
        outcome_code="answered",
        route=route,
        provider="local",
        provider_usage_class="local",
        response_text="answer",
        metadata=metadata or {},
    )


def test_disabled_flag_returns_none():
    flags = CapabilityFlags(source_attribution=False)
    decision = _decision("LOCAL")
    result = _result("LOCAL")
    assert build_source_attribution(decision, result, flags=flags) is None


def test_local_no_evidence_is_local_medium():
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("LOCAL")
    result = _result("LOCAL", metadata={"trust_class": "local"})
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution == SourceAttribution(basis="local", sources=[], confidence="medium")


def test_local_with_evidence_is_still_local():
    """LOCAL route should be reported as local even if evidence metadata exists."""
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("LOCAL")
    result = _result("LOCAL", metadata={"evidence_fetched": True, "trust_class": "unverified"})
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution.basis == "local"
    assert attribution.confidence == "medium"


def test_augmented_is_augmented_medium():
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("AUGMENTED")
    result = _result("AUGMENTED", metadata={"evidence_fetched": True, "trust_class": "unverified"})
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution == SourceAttribution(basis="augmented", sources=[], confidence="medium")


def test_evidence_trusted_is_evidence_high():
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("EVIDENCE", evidence_reason="medical")
    result = _result(
        "EVIDENCE",
        metadata={
            "evidence_fetched": True,
            "trust_class": "trusted",
            "sources": ["medlineplus.gov", "pubmed.ncbi.nlm.nih.gov"],
        },
    )
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution.basis == "evidence"
    assert attribution.confidence == "high"
    assert attribution.sources == ["medlineplus.gov", "pubmed.ncbi.nlm.nih.gov"]


def test_evidence_untrusted_is_none_unknown():
    """EVIDENCE without trusted-domain metadata falls through to unknown."""
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("EVIDENCE")
    result = _result(
        "EVIDENCE",
        metadata={"evidence_fetched": True, "trust_class": "unverified"},
    )
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution == SourceAttribution(basis="none", sources=[], confidence="unknown")


def test_news_is_evidence_medium():
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("NEWS")
    result = _result(
        "NEWS",
        metadata={"evidence_fetched": True, "sources": ["rss-source.example"]},
    )
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution.basis == "evidence"
    assert attribution.confidence == "medium"
    assert attribution.sources == ["rss-source.example"]


def test_unrecognized_route_with_no_metadata_is_none_unknown():
    flags = CapabilityFlags(source_attribution=True)
    decision = _decision("MEMORY_RECALL")
    result = _result("MEMORY_RECALL", metadata={})
    attribution = build_source_attribution(decision, result, flags=flags)
    assert attribution == SourceAttribution(basis="none", sources=[], confidence="unknown")


def test_build_trust_label_verified_for_high_confidence_evidence():
    attribution = SourceAttribution(basis="evidence", confidence="high")
    assert build_trust_label(attribution) == "verified"


def test_build_trust_label_local_only():
    attribution = SourceAttribution(basis="local", confidence="medium")
    assert build_trust_label(attribution) == "local_only"


def test_build_trust_label_augmented():
    attribution = SourceAttribution(basis="augmented", confidence="medium")
    assert build_trust_label(attribution) == "augmented"


def test_build_trust_label_partially_verified_for_medium_evidence():
    attribution = SourceAttribution(basis="evidence", confidence="medium")
    assert build_trust_label(attribution) == "partially_verified"


def test_build_trust_label_unknown_for_none_basis():
    attribution = SourceAttribution(basis="none", confidence="unknown")
    assert build_trust_label(attribution) == "unknown"


def test_build_trust_label_untrusted_for_untrusted_basis():
    attribution = SourceAttribution(basis="web_untrusted", confidence="low")
    assert build_trust_label(attribution) == "untrusted"
