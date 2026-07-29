#!/usr/bin/env python3
"""Tests for the general-knowledge web fetcher."""

from __future__ import annotations

import sys
import urllib.error
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.escalation.critical_guard import is_critical_category
from router_py.escalation.fetcher import FetchResult, fetch_general_knowledge
from router_py.pipeline.config import CapabilityFlags
from router_py.request_pipeline import process
from router_py.request_types import (
    ClassificationResult,
    ExecutionResult,
    RouterOutcome,
    RoutingDecision,
    SourceAttribution,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sample_ddg_html() -> str:
    return """<!DOCTYPE html>
<html>
<body>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fone">First Result</a></h2>
  <a class="result__snippet">This is the first snippet.</a>
  <div class="result__extras__url"><a class="result__url" href="https://example.com/one">example.com</a></div>
</div>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="https://wikipedia.org/wiki/Second">Second Result</a></h2>
  <a class="result__snippet">This is the second snippet.</a>
  <div class="result__extras__url"><a class="result__url" href="https://wikipedia.org/wiki/Second">wikipedia.org</a></div>
</div>
</body>
</html>"""


def _empty_ddg_html() -> str:
    return "<!DOCTYPE html><html><body><p>No results</p></body></html>"


def _mock_urlopen(html: str, status: int = 200):
    """Return a callable that yields a mock response containing *html*."""

    def _opener(*args, **kwargs):
        response = MagicMock()
        response.status = status
        response.read.return_value = html.encode("utf-8")
        response.__enter__ = MagicMock(return_value=response)
        response.__exit__ = MagicMock(return_value=False)
        return response

    return _opener


# ---------------------------------------------------------------------------
# Critical guard
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "category",
    [
        "medical",
        "medical_veterinary",
        "financial",
        "personal_finance",
        "legal",
        "regulatory",
        "safety",
        "identity",
        "personal identity",
        "travel_advisory",
        "market",
        "economic",
    ],
)
def test_is_critical_category_returns_true_for_critical(category: str):
    classification = ClassificationResult(
        intent="general", intent_family="factual", category=category
    )
    assert is_critical_category(classification) is True


@pytest.mark.parametrize(
    "category",
    ["factual", "general", "history", "science", "entertainment", ""],
)
def test_is_critical_category_returns_false_for_non_critical(category: str):
    classification = ClassificationResult(
        intent="general", intent_family="factual", category=category
    )
    assert is_critical_category(classification) is False


# ---------------------------------------------------------------------------
# FetchResult dataclass
# ---------------------------------------------------------------------------


def test_fetch_result_defaults_to_web_untrusted():
    result = FetchResult(url="https://example.com", title="Example", snippet="snip")
    assert result.source_type == "web_untrusted"


def test_fetch_result_can_be_frozen_and_replaced():
    result = FetchResult(url="https://example.com", title="Example", snippet="snip")
    updated = replace(result, title="Updated")
    assert updated.title == "Updated"
    assert updated.source_type == "web_untrusted"


# ---------------------------------------------------------------------------
# DuckDuckGo fetcher
# ---------------------------------------------------------------------------


def test_fetch_general_knowledge_parses_first_result():
    with patch("urllib.request.urlopen", _mock_urlopen(_sample_ddg_html())):
        result = fetch_general_knowledge("capital of france")

    assert isinstance(result, FetchResult)
    assert result.source_type == "web_untrusted"
    assert result.title == "First Result"
    assert "example.com/one" in result.url
    assert "first snippet" in result.snippet.lower()


def test_fetch_general_knowledge_refuses_critical_classification():
    classification = ClassificationResult(
        intent="general", intent_family="factual", category="medical"
    )
    with patch("urllib.request.urlopen", _mock_urlopen(_sample_ddg_html())):
        result = fetch_general_knowledge(
            "capital of france", classification=classification
        )

    assert result.url == ""
    assert result.title == "No web sources found"


def test_fetch_general_knowledge_filters_by_allowed_domains():
    with patch("urllib.request.urlopen", _mock_urlopen(_sample_ddg_html())):
        result = fetch_general_knowledge(
            "capital of france", allowed_domains=["wikipedia.org"]
        )

    assert result.title == "Second Result"
    assert "wikipedia.org" in result.url


def test_fetch_general_knowledge_returns_empty_when_no_allowed_matches():
    with patch("urllib.request.urlopen", _mock_urlopen(_sample_ddg_html())):
        result = fetch_general_knowledge(
            "capital of france", allowed_domains=["nonexistent.example"]
        )

    assert result.title == "No web sources found"
    assert result.url == ""


def test_fetch_general_knowledge_handles_empty_results():
    with patch("urllib.request.urlopen", _mock_urlopen(_empty_ddg_html())):
        result = fetch_general_knowledge("xyzabc123")

    assert result.title == "No web sources found"
    assert result.url == ""


def test_fetch_general_knowledge_handles_http_errors():
    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("network down"),
    ):
        result = fetch_general_knowledge("capital of france")

    assert isinstance(result, FetchResult)
    assert result.source_type == "web_untrusted"
    assert result.title == "No web sources found"
    assert result.url == ""


def test_fetch_general_knowledge_decodes_duckduckgo_redirect_url():
    html = """<!DOCTYPE html>
<html><body>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FParis">Paris - Wikipedia</a></h2>
  <a class="result__snippet">Paris is the capital of France.</a>
</div>
</body></html>"""
    with patch("urllib.request.urlopen", _mock_urlopen(html)):
        result = fetch_general_knowledge("capital of france")

    assert result.url == "https://en.wikipedia.org/wiki/Paris"
    assert result.title == "Paris - Wikipedia"


def test_fetch_general_knowledge_respects_allowed_domains_with_redirect():
    html = """<!DOCTYPE html>
<html><body>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fbad">Bad</a></h2>
  <a class="result__snippet">Bad snippet.</a>
</div>
<div class="result">
  <h2 class="result__title"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FGood">Good</a></h2>
  <a class="result__snippet">Good snippet.</a>
</div>
</body></html>"""
    with patch("urllib.request.urlopen", _mock_urlopen(html)):
        result = fetch_general_knowledge(
            "query", allowed_domains=["en.wikipedia.org"]
        )

    assert result.title == "Good"
    assert result.url == "https://en.wikipedia.org/wiki/Good"


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def _fake_local_outcome() -> RouterOutcome:
    return RouterOutcome(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="local answer",
        source_attribution=SourceAttribution(basis="none", confidence="unknown"),
        trust_label="unknown",
        escalation_suggestion="",
    )


def test_process_attaches_web_suggestion_when_flag_enabled():
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )
    fetched = FetchResult(
        url="https://example.com/found",
        title="Found It",
        snippet="snippet",
        source_type="web_untrusted",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            suggest_web_escalation=False,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=_fake_local_outcome(),
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
                return_value=fetched,
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )

    mock_fetch.assert_called_once_with(
        "what is the capital of france",
        allowed_domains=[],
        classification=classification,
    )
    assert "Found It" in outcome.escalation_suggestion
    assert "example.com/found" in outcome.escalation_suggestion
    assert "untrusted" in outcome.escalation_suggestion.lower()


def test_process_skips_web_fetch_for_critical_category():
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="medical",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=_fake_local_outcome(),
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
                return_value=FetchResult(url="", title="No web sources found", snippet=""),
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what are symptoms of flu",
                    classification=classification,
                    decision=decision,
                )
                mock_fetch.assert_called_once_with(
                    "what are symptoms of flu",
                    allowed_domains=[],
                    classification=classification,
                )

    assert outcome.escalation_suggestion == ""


def test_process_skips_web_fetch_when_flag_disabled():
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            auto_web_general_knowledge=False,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=_fake_local_outcome(),
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )
                mock_fetch.assert_not_called()

    assert outcome.escalation_suggestion == ""


def test_process_skips_web_fetch_when_attribution_is_strong():
    strong_outcome = replace(
        _fake_local_outcome(),
        source_attribution=SourceAttribution(basis="local", confidence="high"),
        trust_label="local_only",
    )
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.9,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.9,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=strong_outcome,
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )
                mock_fetch.assert_not_called()

    assert outcome.escalation_suggestion == ""


def test_process_fetches_when_source_attribution_flag_disabled():
    """auto_web_general_knowledge must work even when source_attribution is off."""
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )
    fetched = FetchResult(
        url="https://example.com/found",
        title="Found It",
        snippet="snippet",
        source_type="web_untrusted",
    )
    no_attribution_outcome = replace(
        _fake_local_outcome(), source_attribution=None, trust_label=""
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=False,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=no_attribution_outcome,
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
                return_value=fetched,
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )

    mock_fetch.assert_called_once_with(
        "what is the capital of france",
        allowed_domains=[],
        classification=classification,
    )
    assert "Found It" in outcome.escalation_suggestion
    assert "example.com/found" in outcome.escalation_suggestion


def test_process_skips_fetch_when_attribution_basis_is_low():
    """basis='low' is not a real production basis; it must not trigger a fetch."""
    low_basis_outcome = replace(
        _fake_local_outcome(),
        source_attribution=SourceAttribution(basis="low", confidence="unknown"),
        trust_label="unknown",
    )
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=low_basis_outcome,
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )
                mock_fetch.assert_not_called()

    assert outcome.escalation_suggestion == ""


def test_process_skips_fetch_when_only_confidence_is_low():
    """Low confidence alone must not trigger fetch; basis must be checked."""
    local_low_confidence_outcome = replace(
        _fake_local_outcome(),
        source_attribution=SourceAttribution(basis="local", confidence="low"),
        trust_label="local_only",
    )
    classification = ClassificationResult(
        intent="general",
        intent_family="factual",
        category="general",
        confidence=0.5,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="factual",
        confidence=0.5,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    with patch(
        "router_py.request_pipeline.load_capability_flags",
        return_value=CapabilityFlags(
            source_attribution=True,
            auto_web_general_knowledge=True,
        ),
    ):
        with patch(
            "router_py.request_pipeline.outcome.build_outcome",
            return_value=local_low_confidence_outcome,
        ):
            with patch(
                "router_py.request_pipeline.fetcher.fetch_general_knowledge",
            ) as mock_fetch:
                outcome, _, _ = process(
                    "what is the capital of france",
                    classification=classification,
                    decision=decision,
                )
                mock_fetch.assert_not_called()

    assert outcome.escalation_suggestion == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
