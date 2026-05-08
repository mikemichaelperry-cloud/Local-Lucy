#!/usr/bin/env python3
"""Tests for auto_feedback.py answer quality heuristics."""

import pytest
from auto_feedback import analyze_answer_quality, log_auto_feedback, load_auto_feedback, clear_auto_feedback


class TestAugmentedFailures:
    """AUGMENTED route failures should suggest LOCAL fallback."""

    def test_augmented_provider_error(self):
        result = analyze_answer_quality(
            "What is the weather?",
            "AUGMENTED",
            "",
            "Connection refused: timeout",
        )
        assert result is not None
        assert result["suggested_route"] == "LOCAL"
        assert result["reason"] == "augmented_provider_error"

    def test_augmented_i_dont_know(self):
        result = analyze_answer_quality(
            "What is the stock price of Apple?",
            "AUGMENTED",
            "I don't have access to real-time stock prices.",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "LOCAL"
        assert result["reason"] == "augmented_answer_incomplete"

    def test_augmented_empty_response(self):
        result = analyze_answer_quality(
            "What is the news today?",
            "AUGMENTED",
            "   ",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "LOCAL"
        assert result["reason"] == "augmented_answer_empty"

    def test_augmented_good_answer(self):
        result = analyze_answer_quality(
            "What is the capital of France?",
            "AUGMENTED",
            "Paris is the capital of France.",
            "",
        )
        assert result is None


class TestLocalDisclaimers:
    """LOCAL route with disclaimers on specialized queries should suggest AUGMENTED."""

    def test_local_medical_disclaimer(self):
        result = analyze_answer_quality(
            "My chest feels tight",
            "LOCAL",
            "I'm not a medical professional. Please consult a doctor.",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "AUGMENTED"
        assert result["reason"] == "local_had_medical_disclaimer"

    def test_local_financial_disclaimer(self):
        result = analyze_answer_quality(
            "Should I invest in bitcoin?",
            "LOCAL",
            "I'm not a financial advisor. This is not financial advice.",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "AUGMENTED"
        assert result["reason"] == "local_had_financial_disclaimer"

    def test_local_legal_disclaimer(self):
        result = analyze_answer_quality(
            "Is it legal to download movies?",
            "LOCAL",
            "I'm not a lawyer. This is not legal advice.",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "AUGMENTED"
        assert result["reason"] == "local_had_legal_disclaimer"

    def test_local_medical_no_disclaimer(self):
        # Local model gives actual info, no disclaimer
        result = analyze_answer_quality(
            "What causes headaches?",
            "LOCAL",
            "Headaches can be caused by stress, dehydration, or eye strain.",
            "",
        )
        assert result is None


class TestLocalIgnorance:
    """LOCAL route admitting ignorance on factual queries should suggest AUGMENTED."""

    def test_local_i_dont_know_factual(self):
        result = analyze_answer_quality(
            "What is the current price of gold?",
            "LOCAL",
            "I don't have access to real-time price data.",
            "",
        )
        assert result is not None
        assert result["suggested_route"] == "AUGMENTED"
        assert result["reason"] == "local_admitted_ignorance_factual"

    def test_local_i_dont_know_creative(self):
        # Creative queries don't need augmented
        result = analyze_answer_quality(
            "Write me a poem about the moon",
            "LOCAL",
            "I don't have access to real-time price data.",
            "",
        )
        assert result is None  # Not a factual query

    def test_local_short_but_correct(self):
        # Short correct answers should not be flagged
        result = analyze_answer_quality(
            "What is 2+2?",
            "LOCAL",
            "The answer is 4.",
            "",
        )
        assert result is None


class TestNoMisroute:
    """Correct routes should return None."""

    def test_local_creative_query(self):
        result = analyze_answer_quality(
            "Write a short story about a robot",
            "LOCAL",
            "Once upon a time, there was a robot named Unit-7...",
            "",
        )
        assert result is None

    def test_local_general_knowledge(self):
        result = analyze_answer_quality(
            "What is the capital of France?",
            "LOCAL",
            "Paris is the capital of France.",
            "",
        )
        assert result is None

    def test_augmented_current_events(self):
        result = analyze_answer_quality(
            "What are today's headlines?",
            "AUGMENTED",
            "Today's top headlines include...",
            "",
        )
        assert result is None

    def test_empty_query(self):
        result = analyze_answer_quality(
            "",
            "LOCAL",
            "Some response",
            "",
        )
        assert result is None


class TestLogAndLoad:
    """Test feedback logging and loading."""

    def test_log_and_load_roundtrip(self, tmp_path, monkeypatch):
        from auto_feedback import AUTO_FEEDBACK_PATH
        monkeypatch.setattr(
            "auto_feedback.AUTO_FEEDBACK_PATH",
            tmp_path / "auto_feedback.jsonl"
        )
        suggestion = {
            "query": "test query",
            "suggested_route": "AUGMENTED",
            "reason": "test_reason",
            "confidence": 0.8,
            "details": "test details",
        }
        log_auto_feedback(suggestion)
        entries = load_auto_feedback(min_confidence=0.6)
        assert len(entries) == 1
        assert entries[0]["query"] == "test query"
        assert entries[0]["correct_route"] == "AUGMENTED"

    def test_load_respects_min_confidence(self, tmp_path, monkeypatch):
        from auto_feedback import AUTO_FEEDBACK_PATH
        monkeypatch.setattr(
            "auto_feedback.AUTO_FEEDBACK_PATH",
            tmp_path / "auto_feedback.jsonl"
        )
        log_auto_feedback({
            "query": "low confidence",
            "suggested_route": "LOCAL",
            "reason": "test",
            "confidence": 0.3,
            "details": "",
        })
        entries = load_auto_feedback(min_confidence=0.6)
        assert len(entries) == 0
