#!/usr/bin/env python3
"""Characterization tests for request_pipeline.process().

These tests capture the routing/classification behaviour of the current
``process()`` implementation for a fixed set of representative inputs. They
are intentionally written *before* the pipeline split refactor so that the
same outputs can be verified again after the code is moved into
``pipeline/classify.py`` and ``pipeline/route.py``.

ExecutionEngine is stubbed to avoid network/model calls; the tests focus on
the route, provider, outcome_code, status, and related classification/routing
metadata produced by the pipeline choke point.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from router_py.request_pipeline import process
from router_py.request_constraints import RequestConstraints
from router_py.request_types import ExecutionResult


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: Any, tmp_path: Path) -> None:
    """Provide a deterministic, isolated environment for every test."""
    monkeypatch.delenv("LUCY_ROUTER_BYPASS", raising=False)
    monkeypatch.delenv("LUCY_CHAT_FORCE_MODE", raising=False)
    monkeypatch.delenv("LUCY_GEMMA4_SMART_ROUTING", raising=False)
    monkeypatch.delenv("LUCY_AUGMENTED_PROVIDER", raising=False)
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("LUCY_MODEL", "local-lucy-llama31")
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    # Ensure no leftover state file is read.
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_dir.joinpath("current_state.json").write_text(
        '{"self_analysis_mode": "off"}', encoding="utf-8"
    )


@pytest.fixture(autouse=True)
def _stub_execution_engine(monkeypatch: Any) -> None:
    """Replace ExecutionEngine with a deterministic stub."""

    class FakeExecutionEngine:
        def __init__(self, config: dict[str, Any]) -> None:
            pass

        def execute(self, classification, decision, context):
            return ExecutionResult(
                status="completed",
                outcome_code="answered",
                route=decision.route,
                provider=decision.provider,
                provider_usage_class=decision.provider_usage_class,
                response_text="fake answer",
                error_message="",
                execution_time_ms=1,
            )

    monkeypatch.setattr(
        "router_py.request_pipeline.ExecutionEngine", FakeExecutionEngine
    )


def _run_case(question: str, **kwargs: Any):
    """Call process() and return the outcome, classification, and decision."""
    return process(question, **kwargs)


def test_simple_local_question():
    """A simple factual query routes LOCAL."""
    outcome, classification, decision = _run_case("what is 2+2")
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "LOCAL"
    assert outcome.provider == "local"
    assert outcome.intent_family == "local_answer"
    assert decision.route == "LOCAL"
    assert decision.mode == "AUTO"
    assert decision.provider == "local"
    assert classification.intent_family == "local_answer"
    assert classification.needs_web is False


def test_news_query():
    """A news query routes NEWS."""
    outcome, classification, decision = _run_case("latest news about Israel")
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "NEWS"
    assert outcome.provider == "kimi"
    assert outcome.intent_family == "current_evidence"
    assert decision.route == "NEWS"
    assert decision.mode == "AUTO"
    assert decision.provider == "kimi"
    assert classification.intent_family == "current_evidence"
    assert classification.needs_web is True


def test_evidence_query():
    """A source/evidence query routes AUGMENTED."""
    outcome, classification, decision = _run_case("evidence for climate change")
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "AUGMENTED"
    assert outcome.provider == "wikipedia"
    assert outcome.intent_family == "current_evidence"
    assert decision.route == "AUGMENTED"
    assert decision.mode == "AUTO"
    assert decision.provider == "wikipedia"
    assert classification.intent_family == "current_evidence"
    assert classification.needs_web is True


def test_medical_query():
    """A medication query routes EVIDENCE with trusted provider."""
    outcome, classification, decision = _run_case("What is lisinopril?")
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "EVIDENCE"
    assert outcome.provider == "trusted"
    assert outcome.intent_family == "current_evidence"
    assert outcome.evidence_reason == "medical_context"
    assert decision.route == "EVIDENCE"
    assert decision.provider == "trusted"
    assert classification.intent_family == "current_evidence"
    assert classification.needs_web is True


def test_route_prefix_news():
    """An explicit route_prefix overrides the classifier selection."""
    outcome, classification, decision = _run_case(
        "tell me something", route_prefix="NEWS"
    )
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "NEWS"
    assert outcome.provider == "kimi"
    assert decision.route == "NEWS"
    assert decision.mode == "FORCED"
    assert decision.policy_reason == "prefix_override_news"
    # Classification is still produced but overridden by the prefix.
    assert classification.intent_family == "local_answer"


def test_augmented_direct_once():
    """augmented_direct_once forces a LOCAL decision to AUGMENTED."""
    outcome, classification, decision = _run_case(
        "who was ada lovelace", augmented_direct_once=True
    )
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "AUGMENTED"
    assert outcome.intent_family == "local_answer"
    assert decision.route == "AUGMENTED"
    assert decision.mode == "AUTO"
    assert decision.policy_reason == "augmented_direct_once"
    assert classification.intent_family == "local_answer"


def test_env_bypass_network_constraint_fallback(monkeypatch: Any) -> None:
    """Env bypass NEWS with network constraint falls back to LOCAL."""
    monkeypatch.setenv("LUCY_ROUTER_BYPASS", "1")
    monkeypatch.setenv("LUCY_CHAT_FORCE_MODE", "NEWS")
    outcome, classification, decision = _run_case(
        "latest news",
        context={"request_constraints": RequestConstraints(network=False)},
    )
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "LOCAL"
    assert outcome.provider == "local"
    assert decision.route == "LOCAL"
    assert decision.policy_reason == "request_constraint_network_denied"


def test_env_bypass_augmented_direct_once(monkeypatch: Any) -> None:
    """Env bypass LOCAL with augmented_direct_once upgrades to AUGMENTED."""
    monkeypatch.setenv("LUCY_ROUTER_BYPASS", "1")
    monkeypatch.setenv("LUCY_CHAT_FORCE_MODE", "LOCAL")
    outcome, classification, decision = _run_case(
        "who was ada lovelace",
        augmented_direct_once=True,
    )
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "AUGMENTED"
    assert decision.route == "AUGMENTED"
    assert decision.policy_reason == "augmented_direct_once"


def test_gemma4_bypass_augmented_direct_once(monkeypatch: Any) -> None:
    """Gemma 4 smart-routing bypass with augmented_direct_once upgrades to AUGMENTED."""
    monkeypatch.setenv("LUCY_GEMMA4_SMART_ROUTING", "1")
    monkeypatch.setenv("LUCY_MODEL", "gemma4")
    outcome, classification, decision = _run_case(
        "what is 2+2",
        augmented_direct_once=True,
    )
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "AUGMENTED"
    assert decision.route == "AUGMENTED"
    assert decision.policy_reason == "augmented_direct_once"
    assert classification.intent_family == "general"


def test_env_bypass_news_provider_resolution(monkeypatch: Any) -> None:
    """Forced NEWS bypass receives resolved provider, not the raw 'news' placeholder."""
    monkeypatch.setenv("LUCY_ROUTER_BYPASS", "1")
    monkeypatch.setenv("LUCY_CHAT_FORCE_MODE", "NEWS")
    outcome, classification, decision = _run_case("latest news")
    assert outcome.status == "completed"
    assert outcome.outcome_code == "answered"
    assert outcome.route == "NEWS"
    assert outcome.provider != "news"
    assert outcome.provider in {"kimi", "wikipedia", "openai"}
    assert decision.provider != "news"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
