#!/usr/bin/env python3
"""Tests for critical-category trusted-source enforcement."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.escalation.critical_guard import is_critical_category
from router_py.pipeline.route import apply_critical_source_policy
from router_py.pipeline.config import CapabilityFlags
from router_py.request_pipeline import process
from router_py.request_types import ClassificationResult, RouterOutcome, RoutingDecision


def _classification(category: str, evidence_reason: str = "") -> ClassificationResult:
    return ClassificationResult(
        intent="general",
        intent_family="factual",
        intent_class="general",
        category=category,
        confidence=0.8,
        evidence_reason=evidence_reason,
    )


def _decision(
    route: str = "LOCAL",
    provider: str = "local",
    evidence_mode: str = "",
    evidence_reason: str = "",
) -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider=provider,
        provider_usage_class="local" if provider == "local" else "free",
        evidence_mode=evidence_mode,
        evidence_reason=evidence_reason,
    )


def _trusted_flags() -> CapabilityFlags:
    return CapabilityFlags(trusted_sources_only_critical=True)


@pytest.mark.parametrize(
    "category",
    [
        "medical",
        "financial",
        "finance",
        "legal",
        "regulatory",
        "safety",
        "identity",
        "identity_personal",
        "travel_advisory",
        "market",
        "economic",
    ],
)
def test_is_critical_category_matches(category: str):
    assert is_critical_category(_classification(category)) is True


def test_is_critical_category_non_critical():
    assert is_critical_category(_classification("factual")) is False
    assert is_critical_category(_classification("news_israel")) is False


def test_non_critical_query_unchanged():
    flags = _trusted_flags()
    decision = _decision("AUGMENTED", provider="wikipedia")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("factual"))
    assert isinstance(result, RoutingDecision)
    assert result.route == "AUGMENTED"
    assert result.provider == "wikipedia"


def test_critical_query_unchanged_when_flag_disabled():
    flags = CapabilityFlags(trusted_sources_only_critical=False)
    decision = _decision("AUGMENTED", provider="wikipedia")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("medical"))
    assert isinstance(result, RoutingDecision)
    assert result.provider == "wikipedia"


def test_medical_news_converted_to_evidence_with_trusted_provider():
    flags = _trusted_flags()
    decision = _decision("NEWS", provider="news", evidence_reason="news_query")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("medical"))
    assert isinstance(result, RoutingDecision)
    assert result.route == "EVIDENCE"
    assert result.provider == "trusted"
    assert result.evidence_mode == "required"
    assert result.requires_evidence is True
    assert "critical_trusted_sources_only" in result.policy_reason


def test_financial_augmented_restricted_to_trusted():
    flags = _trusted_flags()
    decision = _decision("AUGMENTED", provider="wikipedia")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(
            decision, _classification("financial", evidence_reason="financial_data")
        )
    assert isinstance(result, RoutingDecision)
    assert result.route == "AUGMENTED"
    assert result.provider == "trusted"
    assert result.evidence_mode == "required"
    assert result.requires_evidence is True


def test_medical_evidence_kept_with_trusted_provider():
    flags = _trusted_flags()
    decision = _decision(
        "EVIDENCE", provider="kimi", evidence_mode="required", evidence_reason="medical_context"
    )
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("medical"))
    assert isinstance(result, RoutingDecision)
    assert result.route == "EVIDENCE"
    assert result.provider == "trusted"


def test_safety_without_trusted_source_blocked():
    flags = _trusted_flags()
    decision = _decision("AUGMENTED", provider="wikipedia")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("safety"))
    assert isinstance(result, RouterOutcome)
    assert result.outcome_code == "operator_blocked"
    assert result.status == "completed"


def test_identity_without_trusted_source_blocked():
    flags = _trusted_flags()
    decision = _decision("EVIDENCE", provider="kimi", evidence_mode="required")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("identity_personal"))
    assert isinstance(result, RouterOutcome)
    assert result.outcome_code == "operator_blocked"


def test_context_allow_domains_file_set_for_medical():
    flags = _trusted_flags()
    decision = _decision("EVIDENCE", provider="kimi", evidence_mode="required")
    context: dict[str, object] = {}
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(
            decision, _classification("medical", evidence_reason="medical_context"), context
        )
    assert isinstance(result, RoutingDecision)
    assert context.get("allow_domains_file").endswith("medical_runtime.txt")


def test_context_allow_domains_file_set_for_finance():
    flags = _trusted_flags()
    decision = _decision("AUGMENTED", provider="wikipedia")
    context: dict[str, object] = {}
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(
            decision,
            _classification("financial", evidence_reason="financial_data"),
            context,
        )
    assert isinstance(result, RoutingDecision)
    assert context.get("allow_domains_file").endswith("finance_runtime.txt")


def test_pre_trusted_evidence_sets_default_allow_domains_file():
    """Critical EVIDENCE with provider='trusted' but no category allowlist still gets a trusted file."""
    flags = _trusted_flags()
    decision = _decision(
        "EVIDENCE", provider="trusted", evidence_mode="required"
    )
    context: dict[str, object] = {}
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(
            decision, _classification("identity_personal"), context
        )
    assert isinstance(result, RoutingDecision)
    assert context.get("allow_domains_file").endswith("allowlist_tier1.txt")


def test_local_critical_route_unchanged():
    """LOCAL routes for critical categories should not be blocked or altered."""
    flags = _trusted_flags()
    decision = _decision("LOCAL", provider="local")
    with patch(
        "router_py.pipeline.route.load_capability_flags",
        return_value=flags,
    ):
        result = apply_critical_source_policy(decision, _classification("medical"))
    assert isinstance(result, RoutingDecision)
    assert result.route == "LOCAL"
    assert result.provider == "local"


def test_pipeline_blocks_critical_safety_augmented_query():
    """Full pipeline returns operator_blocked for safety with no trusted source."""
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        intent_class="general",
        category="safety",
        confidence=0.8,
    )
    decision = RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider="wikipedia",
        provider_usage_class="free",
        evidence_mode="",
    )
    outcome, _, _ = process(
        "safety recall for baby stroller",
        classification=classification,
        decision=decision,
    )
    assert outcome.outcome_code == "operator_blocked"
    assert "trusted" in outcome.policy_reason or "trusted" in outcome.response_text.lower()


def test_pipeline_restricts_critical_medical_to_trusted():
    """Full pipeline restricts a critical medical AUGMENTED query to trusted provider."""
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        intent_class="general",
        category="medical",
        confidence=0.8,
        evidence_reason="medical_context",
    )
    decision = RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider="wikipedia",
        provider_usage_class="free",
        evidence_mode="",
    )
    with patch.dict("os.environ", {"LUCY_EVIDENCE_ENABLED": "1"}):
        with patch("router_py.request_pipeline.execute.execute_request") as mock_execute:
            from router_py.request_types import ExecutionResult

            mock_execute.return_value = ExecutionResult(
                status="completed",
                outcome_code="augmented_answer",
                route="AUGMENTED",
                provider="trusted",
                provider_usage_class="free",
                response_text="trusted answer",
            )
            outcome, _, final_decision = process(
                "what is lisinopril",
                classification=classification,
                decision=decision,
            )
    assert final_decision is not None
    assert final_decision.provider == "trusted"
    assert final_decision.route == "AUGMENTED"
    assert outcome.provider == "trusted"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
