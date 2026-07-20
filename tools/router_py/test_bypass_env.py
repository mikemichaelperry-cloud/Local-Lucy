#!/usr/bin/env python3
"""Tests for LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE env-var support.

These replace obsolete shell-mock e2e tests that relied on the removed
shell execution pipeline.  They verify the Python-native router honors the
 documented bypass/force-mode interface without invoking external services.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from router_py import request_pipeline
from router_py.request_types import ClassificationResult, RoutingDecision


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch: Any) -> None:
    """Make sure bypass env vars are clean for every test."""
    for key in ("LUCY_ROUTER_BYPASS", "LUCY_CHAT_FORCE_MODE"):
        monkeypatch.delenv(key, raising=False)


def test_no_bypass_when_env_unset() -> None:
    assert request_pipeline._forced_route_from_env("latest news") is None
    assert request_pipeline._forced_route_from_env("What is aspirin?") is None


def test_bypass_forces_news() -> None:
    os.environ["LUCY_ROUTER_BYPASS"] = "1"
    os.environ["LUCY_CHAT_FORCE_MODE"] = "NEWS"
    assert request_pipeline._forced_route_from_env("anything") == "NEWS"


def test_bypass_forces_evidence() -> None:
    os.environ["LUCY_ROUTER_BYPASS"] = "1"
    os.environ["LUCY_CHAT_FORCE_MODE"] = "EVIDENCE"
    assert request_pipeline._forced_route_from_env("anything") == "EVIDENCE"


def test_bypass_infers_news_from_query() -> None:
    os.environ["LUCY_ROUTER_BYPASS"] = "1"
    assert request_pipeline._forced_route_from_env("Whats the latest Australian news?") == "NEWS"
    assert request_pipeline._forced_route_from_env("breaking news headlines") == "NEWS"


def test_bypass_decision_medical_evidence() -> None:
    classification, decision = request_pipeline._bypass_classification_decision(
        "What is lisinopril?", "EVIDENCE"
    )
    assert classification.intent_family == "evidence_check"
    assert classification.evidence_reason == "medical_context"
    assert decision.route == "EVIDENCE"
    assert decision.provider == "trusted"
    assert decision.policy_reason == "env_bypass"


def test_bypass_decision_news() -> None:
    classification, decision = request_pipeline._bypass_classification_decision(
        "latest Israel news", "NEWS"
    )
    assert classification.intent_family == "current_fact"
    assert decision.route == "NEWS"
    assert decision.provider == "news"


def test_bypass_decision_local() -> None:
    classification, decision = request_pipeline._bypass_classification_decision(
        "hello", "LOCAL"
    )
    assert classification.intent_family == "local_knowledge"
    assert decision.route == "LOCAL"
    assert decision.provider == "local"
    assert not decision.requires_evidence


def test_evidence_disabled_gate_blocks_news(tmp_path: Path, monkeypatch: Any) -> None:
    """When evidence is disabled, forced NEWS must return the operator message."""
    monkeypatch.setenv("LUCY_ROUTER_BYPASS", "1")
    monkeypatch.setenv("LUCY_CHAT_FORCE_MODE", "NEWS")
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "0")
    # Prevent the router from loading a real state file.
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))

    outcome, classification, decision = request_pipeline.process("latest world news")
    assert outcome.outcome_code == "operator_blocked"
    assert "Evidence disabled by operator control" in outcome.response_text
    assert decision is not None
    assert decision.route == "NEWS"


def test_evidence_disabled_gate_blocks_evidence(tmp_path: Path, monkeypatch: Any) -> None:
    """When evidence is disabled, forced EVIDENCE must return the operator message."""
    monkeypatch.setenv("LUCY_ROUTER_BYPASS", "1")
    monkeypatch.setenv("LUCY_CHAT_FORCE_MODE", "EVIDENCE")
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "0")
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))

    outcome, _classification, decision = request_pipeline.process("What is aspirin?")
    assert outcome.outcome_code == "operator_blocked"
    assert decision is not None
    assert decision.route == "EVIDENCE"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
