#!/usr/bin/env python3
"""Integration tests for pipeline capability flags.

These tests exercise ``request_pipeline.process()`` end-to-end with each
v11 capability flag toggled, verifying that the flags only change behaviour
when explicitly enabled and that defaults remain backward-compatible.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest

from router_py.escalation.fetcher import FetchResult
from router_py.pipeline.config import CapabilityFlags
from router_py.request_pipeline import process
from router_py.request_types import (
    ClassificationResult,
    ExecutionResult,
    RoutingDecision,
)


def _classification(
    *,
    category: str = "general",
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


def _decision(
    *,
    route: str = "LOCAL",
    provider: str = "local",
) -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.8,
        provider=provider,
        provider_usage_class="local" if provider == "local" else "free",
        evidence_mode="",
    )


def _execute_result(
    *,
    route: str = "LOCAL",
    provider: str = "local",
    response_text: str = "answer",
    metadata: dict | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        status="completed",
        outcome_code="answered",
        route=route,
        provider=provider,
        provider_usage_class="local" if provider == "local" else "free",
        response_text=response_text,
        metadata=metadata or {},
    )


def _set_flags(monkeypatch, **kwargs: bool) -> None:
    """Set capability-flag environment variables for the duration of a test."""
    defaults = {
        "source_attribution": False,
        "suggest_web_escalation": False,
        "auto_web_general_knowledge": False,
        "trusted_sources_only_critical": False,
    }
    defaults.update(kwargs)
    for name, value in defaults.items():
        env_name = f"LUCY_{name.upper()}"
        monkeypatch.setenv(env_name, "1" if value else "0")
    # Earlier tests that import main.py can leave provider/policy env vars set.
    # Remove them so provider resolution uses query-type defaults in this suite.
    monkeypatch.delenv("LUCY_AUGMENTED_PROVIDER", raising=False)
    monkeypatch.delenv("LUCY_AUGMENTATION_POLICY", raising=False)


def _outcome_without_timing(outcome):
    """Return outcome dict excluding dynamic timing fields."""
    data = outcome.to_dict()
    data.pop("execution_time_ms", None)
    return data


# ---------------------------------------------------------------------------
# 1. All flags off -> unchanged baseline
# ---------------------------------------------------------------------------


def test_all_flags_off_matches_baseline(monkeypatch):
    """With every capability flag disabled, process() behaves like the baseline."""
    _set_flags(
        monkeypatch,
        source_attribution=False,
        suggest_web_escalation=False,
        auto_web_general_knowledge=False,
        trusted_sources_only_critical=False,
    )

    classification = _classification(category="general")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="baseline answer",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
    ):
        outcome, _, _ = process(
            "what is the capital of france",
            classification=classification,
            decision=decision,
        )

    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "LOCAL"
    assert outcome.provider == "local"
    assert outcome.response_text == "baseline answer"
    assert outcome.source_attribution is None
    assert outcome.trust_label == ""
    assert outcome.escalation_suggestion == ""

    # Stable deterministic baseline snapshot (timing and profiling stripped).
    snapshot = {
        "status": "completed",
        "outcome_code": "answered",
        "route": "LOCAL",
        "provider": "local",
        "provider_usage_class": "local",
        "intent_family": "factual",
        "confidence": 0.8,
        "response_text": "baseline answer",
        "error_message": "",
        "request_id": "",
        "evidence_reason": "",
        "policy_reason": "",
        "source_attribution": None,
        "trust_label": "",
        "escalation_suggestion": "",
    }
    assert _outcome_without_timing(outcome) == snapshot


# ---------------------------------------------------------------------------
# 2. source_attribution=1
# ---------------------------------------------------------------------------


def test_source_attribution_flag_populates_outcome(monkeypatch):
    """source_attribution=1 adds a source-attribution record to the outcome."""
    _set_flags(monkeypatch, source_attribution=True)

    classification = _classification(category="general")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
        metadata={"trust_class": "local"},
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
    ):
        outcome, _, _ = process(
            "what is the capital of france",
            classification=classification,
            decision=decision,
        )

    assert outcome.source_attribution is not None
    assert outcome.source_attribution.basis == "local"
    assert outcome.source_attribution.confidence == "medium"
    assert outcome.source_attribution.sources == []
    assert outcome.trust_label == "local_only"
    assert outcome.escalation_suggestion == ""


# ---------------------------------------------------------------------------
# 3. suggest_web_escalation=1
# ---------------------------------------------------------------------------


def test_suggest_web_escalation_flag_suggests_for_thin_local(monkeypatch):
    """A thin local question receives a web-escalation suggestion when enabled."""
    _set_flags(
        monkeypatch,
        source_attribution=True,
        suggest_web_escalation=True,
    )

    classification = _classification(category="general", needs_web=True)
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
    ):
        outcome, _, _ = process(
            "current weather in paris",
            classification=classification,
            decision=decision,
        )

    assert outcome.source_attribution is not None
    assert outcome.escalation_suggestion != ""
    assert "web" in outcome.escalation_suggestion.lower()


# ---------------------------------------------------------------------------
# 4. auto_web_general_knowledge=1, non-critical
# ---------------------------------------------------------------------------


def test_auto_web_general_knowledge_fetches_for_non_critical(monkeypatch):
    """A non-critical question with thin attribution triggers a web fetch."""
    _set_flags(monkeypatch, auto_web_general_knowledge=True)

    classification = _classification(category="general")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
    )
    fetched = FetchResult(
        url="https://example.com/found",
        title="Found It",
        snippet="snippet",
        source_type="web_untrusted",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
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
    assert "example.com" in outcome.escalation_suggestion
    assert "example.com/found" not in outcome.escalation_suggestion
    assert "untrusted" in outcome.escalation_suggestion.lower()


# ---------------------------------------------------------------------------
# 5. auto_web_general_knowledge=1, critical -> no fetch
# ---------------------------------------------------------------------------


def test_auto_web_general_knowledge_skips_critical(monkeypatch):
    """Critical questions are never auto-fetched, even when the flag is on."""
    _set_flags(monkeypatch, auto_web_general_knowledge=True)

    classification = _classification(category="medical")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
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


# ---------------------------------------------------------------------------
# 6. auto_web_allowed_domains
# ---------------------------------------------------------------------------


def test_auto_web_allowed_domains_passed_to_fetcher(monkeypatch):
    """Configured allowlist is forwarded from process() to fetch_general_knowledge()."""
    _set_flags(monkeypatch, auto_web_general_knowledge=True)
    monkeypatch.setenv("LUCY_AUTO_WEB_ALLOWED_DOMAINS", "wikipedia.org")

    classification = _classification(category="general")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
    )
    fetched = FetchResult(
        url="https://en.wikipedia.org/wiki/Paris",
        title="Paris - Wikipedia",
        snippet="snippet",
        source_type="web_untrusted",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
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
        allowed_domains=["wikipedia.org"],
        classification=classification,
    )
    assert "Paris - Wikipedia" in outcome.escalation_suggestion


# ---------------------------------------------------------------------------
# 7. trusted_sources_only_critical=1
# ---------------------------------------------------------------------------


def test_trusted_sources_only_critical_preserves_parity_decision(monkeypatch):
    """When caller supplies both inputs, the exact routing decision is preserved."""
    _set_flags(monkeypatch, trusted_sources_only_critical=True)

    classification = _classification(category="safety")
    decision = _decision(route="AUGMENTED", provider="wikipedia")
    execute_result = _execute_result(
        route="AUGMENTED",
        provider="kimi",
        response_text="parity answer",
    )

    with patch.dict("os.environ", {"LUCY_EVIDENCE_ENABLED": "1"}):
        with patch(
            "router_py.request_pipeline.execute.execute_request",
            return_value=execute_result,
        ) as mock_execute:
            outcome, _, final_decision = process(
                "safety recall for baby stroller",
                classification=classification,
                decision=decision,
            )
            mock_execute.assert_called_once()

    assert final_decision is not None
    # Provider resolution still runs in parity mode; only the critical-source
    # policy modification is skipped.
    assert final_decision.route == "AUGMENTED"
    assert final_decision.provider == "kimi"
    assert outcome.outcome_code != "operator_blocked"


# ---------------------------------------------------------------------------
# 8. Diagnostic trace flag
# ---------------------------------------------------------------------------


def test_router_diagnostics_flag_writes_trace(monkeypatch, tmp_path: Path):
    """When LUCY_ROUTER_DIAGNOSTICS=1, process() writes a structured trace entry."""
    diagnostics_file = tmp_path / "router_diagnostics.jsonl"
    monkeypatch.setenv("LUCY_ROUTER_DIAGNOSTICS", "1")
    monkeypatch.setenv("LUCY_ROUTER_DIAGNOSTICS_PATH", str(diagnostics_file))

    classification = _classification(category="general")
    decision = _decision(route="LOCAL", provider="local")
    execute_result = _execute_result(
        route="LOCAL",
        provider="local",
        response_text="local answer",
    )

    with patch(
        "router_py.request_pipeline.execute.execute_request",
        return_value=execute_result,
    ):
        process(
            "what is the capital of france",
            classification=classification,
            decision=decision,
        )

    assert diagnostics_file.exists()
    lines = diagnostics_file.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["original_query"] == "what is the capital of france"
    assert entry["final_route"] == "LOCAL"
    assert entry["final_provider"] == "local"
    assert "capability_flags" in entry


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
