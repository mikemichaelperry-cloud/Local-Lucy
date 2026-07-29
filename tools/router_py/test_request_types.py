"""
Tests for the shared request pipeline dataclasses.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))


def test_router_outcome_source_attribution():
    from router_py.request_types import RouterOutcome, SourceAttribution

    outcome = RouterOutcome(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        intent_family="local_knowledge",
        confidence=0.9,
        response_text="hello",
        source_attribution=SourceAttribution(basis="local", sources=[], confidence="high"),
    )
    assert outcome.source_attribution.basis == "local"


def test_router_outcome_optional_attribution_defaults():
    """Existing callers that do not pass attribution metadata must remain unaffected."""
    from router_py.request_types import RouterOutcome

    outcome = RouterOutcome(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
    )
    assert outcome.source_attribution is None
    assert outcome.trust_label == ""
    assert outcome.escalation_suggestion == ""


def test_source_attribution_defaults():
    from router_py.request_types import SourceAttribution

    attribution = SourceAttribution()
    assert attribution.basis == "none"
    assert attribution.sources == []
    assert attribution.confidence == "unknown"
