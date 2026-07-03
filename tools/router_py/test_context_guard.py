"""Tests for the context relevance guard."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from context_guard import (
    filter_memory_context,
    is_evidence_relevant,
    score_evidence_relevance,
    score_memory_relevance,
)


@pytest.fixture(autouse=True)
def _force_keyword_fallback(monkeypatch):
    """Keep tests fast/deterministic; semantic paths are covered explicitly."""
    import context_guard

    context_guard._ce_model = None
    context_guard._bi_model = None
    monkeypatch.setattr(context_guard, "_load_ce_model", lambda: None)
    monkeypatch.setattr(context_guard, "_load_bi_model", lambda: None)


# ---------------------------------------------------------------------------
# Evidence relevance
# ---------------------------------------------------------------------------


def test_japan_tourism_rejects_china_evidence():
    evidence = {
        "title": "Tourism in China",
        "context": "Tourism in China is a growing industry...",
        "provider": "wikipedia",
    }
    score = score_evidence_relevance("What are the main tourist attractions in Japan?", evidence)
    assert score == 0.0
    assert (
        is_evidence_relevant("What are the main tourist attractions in Japan?", evidence) is False
    )


def test_japan_tourism_accepts_japan_evidence():
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry and contributor to the Japanese economy.",
        "provider": "wikipedia",
    }
    score = score_evidence_relevance("What are the main tourist attractions in Japan?", evidence)
    assert score >= 0.6
    assert is_evidence_relevant("What are the main tourist attractions in Japan?", evidence) is True


def test_query_without_place_uses_keyword_overlap():
    evidence = {
        "title": "Quantum computing",
        "context": "Quantum computing uses qubits which can exist in superposition.",
        "provider": "wikipedia",
    }
    assert is_evidence_relevant("What is quantum computing?", evidence) is True


def test_empty_evidence_is_irrelevant():
    assert score_evidence_relevance("What is Python?", {}) == 0.0
    assert is_evidence_relevant("What is Python?", {}) is False


def test_evidence_semantic_scorer_rejects_wrong_entity():
    """Cross-encoder path: Japan question vs China article."""
    fake_model = MagicMock()
    fake_model.predict.return_value = [-7.5]
    evidence = {
        "title": "Tourism in China",
        "context": "Tourism in China is a growing industry...",
    }
    with patch("context_guard._load_ce_model", return_value=fake_model):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score < 0.01
    assert (
        is_evidence_relevant("What are the main tourist attractions in Japan?", evidence) is False
    )


def test_evidence_semantic_scorer_accepts_relevant_doc():
    """Cross-encoder path: Japan question vs Japan article."""
    fake_model = MagicMock()
    fake_model.predict.return_value = [3.4]
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry...",
    }
    with patch("context_guard._load_ce_model", return_value=fake_model):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score >= 0.95
    assert is_evidence_relevant("What are the main tourist attractions in Japan?", evidence) is True


# ---------------------------------------------------------------------------
# Memory relevance
# ---------------------------------------------------------------------------


def test_memory_filter_drops_stale_china_turn():
    memory = (
        "User: What are the main tourist attractions in Japan?\n\n"
        "Assistant: Tourism in China is a growing industry..."
    )
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts,
        {
            "What are interesting towns in Tokyo?": [1.0, 0.0],
            "Japan": [1.0, 0.0],
            "China": [0.0, 1.0],
        },
    )
    with patch("context_guard._load_bi_model", return_value=fake_model):
        filtered = filter_memory_context("What are interesting towns in Tokyo?", memory)
    assert "Tourism in China" not in filtered
    assert "User: What are the main tourist attractions in Japan?" in filtered


def test_memory_filter_keeps_relevant_turn():
    memory = (
        "User: What are the main tourist attractions in Japan?\n\n"
        "Assistant: Tourism in Japan is a major industry..."
    )
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts,
        {
            "What about Tokyo specifically?": [1.0, 0.0],
            "Japan": [1.0, 0.0],
        },
    )
    with patch("context_guard._load_bi_model", return_value=fake_model):
        filtered = filter_memory_context("What about Tokyo specifically?", memory)
    assert "Tourism in Japan" in filtered


def test_memory_relevance_uses_place_tail():
    turn = "User: What are the main tourist attractions in Japan?"
    assert score_memory_relevance("Tell me more about Japan", turn) >= 0.8


def test_filter_memory_returns_empty_when_nothing_relevant():
    memory = "User: What is the weather in London?\n\nAssistant: It is rainy in London today."
    filtered = filter_memory_context("Explain quantum computing", memory)
    assert filtered == ""


def test_memory_semantic_scorer_keeps_pronoun_reference():
    """Bi-encoder path: 'How does it work?' keeps the quantum computing turn."""
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts, {"How does it work?": [1.0, 0.0], "quantum": [0.9, 0.1]}
    )
    turn = "User: What is quantum computing?\nAssistant: Quantum computing uses qubits..."
    with patch("context_guard._load_bi_model", return_value=fake_model):
        score = score_memory_relevance("How does it work?", turn)
    assert score >= 0.8


def test_memory_semantic_scorer_drops_unrelated_topic():
    """Bi-encoder path: unrelated topic gets a low cosine score."""
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts,
        {
            "Explain quantum computing": [1.0, 0.0],
            "London weather": [-0.5, 0.5],
        },
    )
    turn = "User: What is the weather in London?\nAssistant: It is rainy in London today."
    with patch("context_guard._load_bi_model", return_value=fake_model):
        score = score_memory_relevance("Explain quantum computing", turn)
    assert score < 0.2


def _fake_embeddings(texts, vectors):
    import numpy as np

    out = []
    for t in texts:
        key = next((k for k in vectors if k.lower() in t.lower()), None)
        out.append(vectors.get(key, [0.0, 1.0]))
    return np.array(out, dtype=float)


# ---------------------------------------------------------------------------
# Fallback paths
# ---------------------------------------------------------------------------


def test_evidence_fallback_to_keyword_when_model_missing():
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry...",
    }
    with patch("context_guard._load_ce_model", return_value=None):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score >= 0.6


def test_memory_fallback_to_keyword_when_model_missing():
    turn = "User: What are the main tourist attractions in Japan?"
    with patch("context_guard._load_bi_model", return_value=None):
        score = score_memory_relevance("Tell me more about Japan", turn)
    assert score >= 0.8
