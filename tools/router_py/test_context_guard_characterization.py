"""Characterization tests for the context_guard split.

These tests assert the public API surface and deterministic keyword fallback
behavior. They never load sentence-transformers or Ollama models.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

# Make the repository tools tree importable so both `router_py.context_guard`
# and the legacy top-level `context_guard` package resolve.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "router_py"))

pytestmark = [pytest.mark.static]


@pytest.fixture(autouse=True)
def _force_keyword_fallback(monkeypatch):
    """Keep characterization tests deterministic and model-free."""
    import context_guard

    context_guard._ce_model = None
    context_guard._bi_model = None
    monkeypatch.setattr(context_guard, "_load_ce_model", lambda: None)
    monkeypatch.setattr(context_guard, "_load_bi_model", lambda: None)


def test_public_symbols_importable_from_router_py_context_guard():
    """The split package must expose the same public functions as the monolith."""
    from router_py.context_guard import (
        filter_memory_context,
        is_evidence_relevant,
        score_evidence_relevance,
        score_memory_relevance,
    )

    assert callable(score_evidence_relevance)
    assert callable(is_evidence_relevant)
    assert callable(score_memory_relevance)
    assert callable(filter_memory_context)


def test_default_thresholds_match_config():
    """Default thresholds must stay in sync with context_guard/config.py."""
    from router_py.context_guard import (
        filter_memory_context,
        is_evidence_relevant,
    )
    from router_py.context_guard import config

    evidence_sig = inspect.signature(is_evidence_relevant)
    assert evidence_sig.parameters["threshold"].default == config.EVIDENCE_THRESHOLD

    memory_sig = inspect.signature(filter_memory_context)
    assert memory_sig.parameters["threshold"].default == config.MEMORY_THRESHOLD


def test_keyword_fallback_scoring_is_deterministic_without_models():
    """Keyword fallback must be deterministic and must not load models."""
    from context_guard import _load_ce_model, _load_bi_model
    from router_py.context_guard import (
        score_evidence_relevance,
        score_memory_relevance,
    )

    # Guard against accidental model loads.
    assert _load_ce_model() is None
    assert _load_bi_model() is None

    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry.",
        "provider": "wikipedia",
    }
    score1 = score_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    )
    score2 = score_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    )
    assert score1 == score2
    assert 0.0 <= score1 <= 1.0

    memory_turn = "User: What are the main tourist attractions in Japan?"
    mem1 = score_memory_relevance("Tell me more about Japan", memory_turn)
    mem2 = score_memory_relevance("Tell me more about Japan", memory_turn)
    assert mem1 == mem2
    assert 0.0 <= mem1 <= 1.0


def test_is_evidence_relevant_simple_cases():
    """Sanity-check boolean relevance decisions on simple evidence items."""
    from router_py.context_guard import is_evidence_relevant

    japan_evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry.",
        "provider": "wikipedia",
    }
    china_evidence = {
        "title": "Tourism in China",
        "context": "Tourism in China is a growing industry.",
        "provider": "wikipedia",
    }

    assert (
        is_evidence_relevant(
            "What are the main tourist attractions in Japan?", japan_evidence
        )
        is True
    )
    assert (
        is_evidence_relevant(
            "What are the main tourist attractions in Japan?", china_evidence
        )
        is False
    )
    assert is_evidence_relevant("What is Python?", {}) is False
