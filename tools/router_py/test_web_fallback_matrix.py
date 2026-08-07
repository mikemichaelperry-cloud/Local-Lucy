#!/usr/bin/env python3
"""Broad permutation tests for the general-web fallback path.

These tests verify that ordinary AUGMENTED factual queries across many fields
can fall back to an explicitly-labelled untrusted web source when primary
evidence providers fail, while critical routes (medical, veterinary, legal,
financial high-stakes, EVIDENCE) and explicit no-network requests do not.

The tests do not hard-code expected prose answers and do not invoke Ollama.
They mock the classifier, provider resolver, evidence providers, and local
model so the matrix stays fast and deterministic.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router_py.escalation.fetcher import FetchResult
from router_py.request_constraints import RequestConstraints
from router_py.request_pipeline import process
from router_py.request_types import ClassificationResult, RoutingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classification(intent_family: str = "factual", evidence_reason: str = "factual_lookup") -> ClassificationResult:
    return ClassificationResult(
        intent="question",
        intent_family=intent_family,
        intent_class="factual",
        category="general",
        confidence=0.7,
        evidence_mode="required" if evidence_reason else "",
        evidence_reason=evidence_reason,
    )


def _decision(route: str, evidence_reason: str = "factual_lookup", provider: str = "local") -> RoutingDecision:
    return RoutingDecision(
        route=route,
        mode="AUTO",
        intent_family="factual",
        confidence=0.7,
        provider=provider,
        provider_usage_class="local" if provider == "local" else "free",
        evidence_mode="required" if evidence_reason else "",
        evidence_reason=evidence_reason,
        requires_evidence=route in ("AUGMENTED", "EVIDENCE", "FULL"),
    )


@pytest.fixture(autouse=True)
def _enable_features(monkeypatch):
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("LUCY_ENABLE_INTERNET", "1")
    monkeypatch.setenv("LUCY_SOURCE_ATTRIBUTION", "1")


@pytest.fixture
def _mock_engine(monkeypatch):
    """Patch ExecutionEngine so no Ollama/network/provider-resolution runs."""
    from router_py import execution_engine as ee_mod
    from router_py import provider_resolver as resolver_mod
    from router_py.execution_engine import ExecutionEngine

    async def _fake_local(self, prompt, context, session_memory, route_mode=None):
        return "Answer synthesized from available context.", {}

    async def _fake_parallel(self, question, route, chain):
        return {
            "_parallel_success": False,
            "attempted": chain,
            "last_error": "mocked primary failure",
        }

    async def _fake_trusted(self, question, route):
        return None

    async def _fake_weather(self, question):
        return {"ok": True, "formatted": "Sunny, 22 C", "location": "Test City"}

    async def _fake_time(self, question):
        return {"ok": True, "formatted": "12:00 UTC", "time": "12:00"}

    async def _fake_finance(self, question):
        return {"ok": True, "formatted": "$123.45", "symbol": "TEST"}

    async def _fake_news(self, question, for_voice=False):
        return {"ok": True, "formatted": "Test headline", "headlines": []}

    def _fake_fetch(query, allowed_domains=None, classification=None):
        return FetchResult(
            url=f"https://example.com/search?q={query.replace(' ', '+')}",
            title="Mock web result",
            snippet=f"Mock snippet for: {query}",
            source_type="web_untrusted",
        )

    def _noop_apply_provider(decision, classification, context=None, prefer_paid=False):
        return decision

    monkeypatch.setattr(ExecutionEngine, "_call_local_model_async", _fake_local)
    monkeypatch.setattr(ExecutionEngine, "_fetch_evidence_parallel", _fake_parallel)
    monkeypatch.setattr(ExecutionEngine, "_fetch_trusted_evidence", _fake_trusted)
    monkeypatch.setattr(ExecutionEngine, "_fetch_weather_evidence", _fake_weather)
    monkeypatch.setattr(ExecutionEngine, "_fetch_time_evidence", _fake_time)
    monkeypatch.setattr(ExecutionEngine, "_fetch_finance_evidence", _fake_finance)
    monkeypatch.setattr(ExecutionEngine, "_fetch_news_evidence", _fake_news)
    monkeypatch.setattr(ee_mod, "fetch_general_knowledge", _fake_fetch)
    monkeypatch.setattr(resolver_mod, "apply_provider", _noop_apply_provider)


def _run(question: str, decision: RoutingDecision, context: dict[str, Any] | None = None):
    classification = _classification(evidence_reason=decision.evidence_reason)
    outcome, _, _ = process(
        question,
        surface="cli",
        timeout=10,
        classification=classification,
        decision=decision,
        context=context,
    )
    return outcome


# ---------------------------------------------------------------------------
# A. Ordinary factual queries across many fields should use web fallback
# ---------------------------------------------------------------------------


ORDINARY_FACTUAL_QUERIES = [
    "Who was Marie Curie?",
    "What caused the fall of the Roman Empire?",
    "Where is Mount Everest located?",
    "Explain photosynthesis in simple terms.",
    "What is the capital of Mongolia?",
    "How does a blockchain work?",
    "Who painted the Mona Lisa?",
    "What is the theory of relativity?",
    "How do electric cars work?",
    "What is the longest river in South America?",
    "When did the Berlin Wall fall?",
    "What language is spoken in Brazil?",
    "Who wrote One Hundred Years of Solitude?",
    "What is quantum entanglement?",
    "How does a vaccine work?",
]


@pytest.mark.parametrize("question", ORDINARY_FACTUAL_QUERIES)
def test_ordinary_factual_query_uses_web_fallback(question, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run(question, _decision("AUGMENTED", "factual_lookup"))

    assert outcome.route == "AUGMENTED"
    assert outcome.provider == "web_untrusted"
    assert outcome.trust_label == "untrusted"
    assert "untrusted web" in outcome.response_text.lower()
    assert "Live sources are unavailable" not in outcome.response_text
    assert outcome.outcome_code == "answered"


# ---------------------------------------------------------------------------
# B. Critical/stakes categories must NOT use the untrusted web fallback
# ---------------------------------------------------------------------------


CRITICAL_EVIDENCE_REASONS = [
    ("AUGMENTED", "medical_context"),
    ("AUGMENTED", "medical_safety"),
    ("AUGMENTED", "veterinary_context"),
    ("AUGMENTED", "legal_context"),
    ("AUGMENTED", "financial_high_stakes"),
]


@pytest.mark.parametrize("route,evidence_reason", CRITICAL_EVIDENCE_REASONS)
def test_critical_queries_reject_untrusted_web_fallback(route, evidence_reason, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    question = f"Test {evidence_reason} question placeholder"
    outcome = _run(question, _decision(route, evidence_reason))

    assert outcome.provider != "web_untrusted"
    assert "untrusted web" not in outcome.response_text.lower()
    assert "Mock web result" not in outcome.response_text


def test_evidence_route_returns_clarification_not_web(_mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run("What does metformin do?", _decision("EVIDENCE", "medical_context"))

    assert outcome.route == "EVIDENCE"
    assert outcome.provider != "web_untrusted"
    assert outcome.outcome_code == "clarification_requested"
    assert "untrusted web" not in outcome.response_text.lower()


# ---------------------------------------------------------------------------
# C. Explicit capability restrictions keep the request local
# ---------------------------------------------------------------------------


def test_no_network_request_constraint_blocks_web_fallback(_mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    question = "What is the current population of Tokyo?"
    constraints = RequestConstraints(network=False)
    outcome = _run(question, _decision("AUGMENTED", "factual_lookup"), context={"request_constraints": constraints})

    assert outcome.route == "LOCAL"
    assert outcome.provider == "local"
    assert outcome.provider != "web_untrusted"
    assert "untrusted web" not in outcome.response_text.lower()


# ---------------------------------------------------------------------------
# D. Direct external routes are not replaced by the web fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "route,provider",
    [
        ("NEWS", "news"),
        ("WEATHER", "weather"),
        ("TIME", "timeapi"),
        ("FINANCE", "finance"),
    ],
)
def test_direct_external_routes_unchanged(route, provider, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run("Test direct route", _decision(route, "", provider=provider))

    assert outcome.route == route
    assert outcome.provider == provider
    assert outcome.provider != "web_untrusted"


# ---------------------------------------------------------------------------
# E. Adversarial typos and noisy input still get labelled web answers
# ---------------------------------------------------------------------------


ADVERSARIAL_TYPO_QUERIES = [
    "Whu wuz Marie Curie?",
    "What caused th fall of th Roman Empir?",
    "Explane fotosynthesis",
    "Ho does a blokchain work?",
    "Wher is Mount Everst locatd?",
    "What is the capitl of Monglia?",
    "Who paintd the Mona Lisa?",
]


@pytest.mark.parametrize("question", ADVERSARIAL_TYPO_QUERIES)
def test_adversarial_typos_use_web_fallback(question, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run(question, _decision("AUGMENTED", "factual_lookup"))

    assert outcome.route == "AUGMENTED"
    assert outcome.provider == "web_untrusted"
    assert outcome.trust_label == "untrusted"
    assert "untrusted web" in outcome.response_text.lower()
    assert "Live sources are unavailable" not in outcome.response_text


# ---------------------------------------------------------------------------
# F. Current-event vs stable-knowledge boundary
# ---------------------------------------------------------------------------


STABLE_KNOWLEDGE_QUERIES = [
    "Who was Marie Curie?",
    "What caused the fall of the Roman Empire?",
    "Explain photosynthesis in simple terms.",
    "What is the theory of relativity?",
]


@pytest.mark.parametrize("question", STABLE_KNOWLEDGE_QUERIES)
def test_stable_knowledge_can_use_web_fallback(question, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run(question, _decision("AUGMENTED", "factual_lookup"))

    assert outcome.provider == "web_untrusted"
    assert outcome.trust_label == "untrusted"


CURRENT_EVENT_EVIDENCE_REASONS = [
    "current_information",
    "conflict_live",
    "news_synthesis",
    "financial_data",
]


@pytest.mark.parametrize("evidence_reason", CURRENT_EVENT_EVIDENCE_REASONS)
def test_current_event_reasons_reject_untrusted_web_fallback(evidence_reason, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    question = f"Test {evidence_reason} current event question placeholder"
    outcome = _run(question, _decision("AUGMENTED", evidence_reason))

    assert outcome.provider != "web_untrusted"
    assert "untrusted web" not in outcome.response_text.lower()
    assert "Mock web result" not in outcome.response_text


# ---------------------------------------------------------------------------
# G. Domain-specific safety: conspiracy/hoax topics must not use untrusted web
# ---------------------------------------------------------------------------


CONSPIRACY_PRONE_QUERIES = [
    "Is the earth flat?",
    "Was the moon landing faked?",
    "9/11 inside job evidence",
    "Do vaccines contain microchips?",
    "What are chemtrails?",
    "Who are the lizard people?",
    "Is climate change a hoax?",
]


@pytest.mark.parametrize("question", CONSPIRACY_PRONE_QUERIES)
def test_conspiracy_prone_queries_reject_untrusted_web_fallback(question, _mock_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    outcome = _run(question, _decision("AUGMENTED", "factual_lookup"))

    assert outcome.provider != "web_untrusted"
    assert "untrusted web" not in outcome.response_text.lower()
    assert "Mock web result" not in outcome.response_text
