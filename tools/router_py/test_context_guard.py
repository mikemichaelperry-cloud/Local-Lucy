"""Tests for the context relevance guard."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import metrics
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


# ---------------------------------------------------------------------------
# Hardening signals (Phase 1-2)
# ---------------------------------------------------------------------------


def _fake_ce(score: float):
    fake = MagicMock()
    fake.predict.return_value = [score]
    return fake


def test_provenance_boosts_trusted_and_damps_generated():
    query = "climate in Japan"
    base_text = "The climate in Japan is temperate."
    wiki = {"context": base_text, "provenance": "wikipedia"}
    generated = {"context": base_text, "provenance": "generated"}

    with patch("context_guard._load_ce_model", return_value=_fake_ce(0.5)):
        wiki_score = score_evidence_relevance(query, wiki)
        gen_score = score_evidence_relevance(query, generated)

    # Same semantic raw score; provenance should make Wikipedia higher.
    assert wiki_score > gen_score
    assert wiki_score >= 0.6
    assert gen_score < 0.5


def test_temporal_penalty_for_current_query_with_stale_evidence():
    query = "What is the latest climate news?"
    fresh = {"context": "Climate news today.", "date": "2026-07-04"}
    stale = {"context": "Climate news last year.", "date": "2025-01-01"}

    with patch("context_guard._load_ce_model", return_value=_fake_ce(1.0)):
        fresh_score = score_evidence_relevance(query, fresh)
        stale_score = score_evidence_relevance(query, stale)

    assert fresh_score > stale_score
    assert stale_score < 0.55


def test_temporal_penalty_skipped_for_weather_and_time():
    query = "What is the current weather?"
    stale_weather = {
        "context": "Current weather is sunny.",
        "date": "2025-01-01",
        "provenance": "weather",
    }

    with patch("context_guard._load_ce_model", return_value=_fake_ce(2.0)):
        score = score_evidence_relevance(query, stale_weather)

    assert score >= 0.85


def test_entity_collision_reduces_score_for_different_place():
    query = "What is the climate in Japan?"
    wrong_place = {"context": "The climate in China is diverse."}
    right_place = {"context": "The climate in Japan is temperate."}

    with patch("context_guard._load_ce_model", return_value=_fake_ce(1.0)):
        wrong_score = score_evidence_relevance(query, wrong_place)
        right_score = score_evidence_relevance(query, right_place)

    assert right_score > wrong_score
    assert wrong_score < 0.5


def test_answerability_penalty_when_no_content_word_overlap():
    query = "What is the climate in Japan?"
    unrelated = {"context": "Banana farming in Ecuador relies on rainfall."}

    with patch("context_guard._load_ce_model", return_value=_fake_ce(2.0)):
        score = score_evidence_relevance(query, unrelated)

    assert score < 0.2


def test_is_evidence_relevant_records_metric_when_request_id_given(isolated_metrics, monkeypatch):
    request_id = "req-cg-1"
    evidence = {"title": "Tourism in Japan", "context": "Tourism in Japan is major."}
    is_evidence_relevant("What are tourist attractions in Japan?", evidence, request_id=request_id)

    records = [
        json.loads(line)
        for line in metrics._METRICS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    decision_records = [r for r in records if r.get("type") == "context_decision"]
    assert len(decision_records) == 1
    assert decision_records[0]["request_id"] == request_id
    assert decision_records[0]["kind"] == "evidence"
    assert decision_records[0]["accepted"] is True


def test_filter_memory_context_records_usage_metric(isolated_metrics, monkeypatch):
    request_id = "req-cg-2"
    memory = (
        "User: What are tourist attractions in Japan?\n"
        "Assistant: Tourism in Japan is a major industry...\n\n"
        "User: What is quantum computing?\n"
        "Assistant: Quantum computing uses qubits..."
    )
    filtered = filter_memory_context("Tell me more about Japan", memory, request_id=request_id)
    assert "Japan" in filtered
    assert "quantum" not in filtered

    records = [
        json.loads(line)
        for line in metrics._METRICS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    usage_records = [r for r in records if r.get("type") == "context_usage"]
    assert len(usage_records) == 1
    assert usage_records[0]["request_id"] == request_id
    assert usage_records[0]["used"] == 1
    assert usage_records[0]["total"] == 2


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_metrics(tmp_path, monkeypatch):
    path = tmp_path / "context_guard_metrics.jsonl"
    monkeypatch.setattr("metrics._METRICS_FILE", path)
    yield path
