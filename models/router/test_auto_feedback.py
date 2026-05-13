#!/usr/bin/env python3
"""Tests for auto_feedback.py — confidence capping, threshold separation."""

import json
import os
from pathlib import Path

import pytest

import auto_feedback
from auto_feedback import (
    analyze_answer_quality,
    log_auto_feedback,
    load_auto_feedback,
    clear_auto_feedback,
    AUTO_FEEDBACK_PATH,
    _MAX_AUTO_FEEDBACK_CONFIDENCE,
)


class TestAnalyzeAnswerQuality:
    """Detection heuristics."""

    def test_augmented_i_dont_know(self):
        result = analyze_answer_quality(
            "What is the stock price?",
            "AUGMENTED",
            "I don't have access to real-time stock prices.",
        )
        assert result is not None
        assert result["suggested_route"] == "LOCAL"
        assert result["reason"] == "augmented_answer_incomplete"

    def test_local_medical_disclaimer(self):
        result = analyze_answer_quality(
            "My chest feels tight",
            "LOCAL",
            "I'm not a medical professional. Please consult a doctor.",
        )
        assert result is not None
        assert result["suggested_route"] == "AUGMENTED"
        assert result["reason"] == "local_had_medical_disclaimer"

    def test_good_answer_returns_none(self):
        result = analyze_answer_quality(
            "What is 2+2?",
            "LOCAL",
            "The answer is 4.",
        )
        assert result is None


class TestLogAutoFeedback:
    """Writing and confidence capping."""

    @pytest.fixture(autouse=True)
    def clean_auto_feedback(self, tmp_path, monkeypatch):
        """Use a temp file for auto-feedback."""
        test_path = tmp_path / "auto_feedback.jsonl"
        monkeypatch.setattr("auto_feedback.AUTO_FEEDBACK_PATH", test_path)
        yield
        if test_path.exists():
            test_path.unlink()

    def test_confidence_capped_at_max(self):
        """High-confidence suggestions are capped to the auto-feedback trust tier."""
        suggestion = {
            "query": "test query",
            "suggested_route": "LOCAL",
            "reason": "augmented_provider_error",
            "confidence": 0.95,  # raw confidence is high
            "details": "",
        }
        log_auto_feedback(suggestion)
        entries = load_auto_feedback(min_confidence=0.0)
        assert len(entries) == 1
        assert entries[0]["confidence"] <= _MAX_AUTO_FEEDBACK_CONFIDENCE
        assert entries[0]["confidence"] == min(0.95, _MAX_AUTO_FEEDBACK_CONFIDENCE)

    def test_low_confidence_preserved(self):
        """Suggestions already below the cap are not modified."""
        suggestion = {
            "query": "test query",
            "suggested_route": "LOCAL",
            "reason": "local_answer_too_short_factual",
            "confidence": 0.4,  # below cap
            "details": "",
        }
        log_auto_feedback(suggestion)
        entries = load_auto_feedback(min_confidence=0.0)
        assert len(entries) == 1
        assert entries[0]["confidence"] == 0.4

    def test_clear_auto_feedback_moves_file(self):
        """clear_auto_feedback() renames to .processed suffix."""
        suggestion = {
            "query": "test",
            "suggested_route": "LOCAL",
            "reason": "test",
            "confidence": 0.5,
            "details": "",
        }
        log_auto_feedback(suggestion)
        assert auto_feedback.AUTO_FEEDBACK_PATH.exists()
        clear_auto_feedback()
        assert not auto_feedback.AUTO_FEEDBACK_PATH.exists()
        assert auto_feedback.AUTO_FEEDBACK_PATH.with_suffix(".processed").exists()

    def test_load_filters_by_min_confidence(self):
        """load_auto_feedback respects min_confidence."""
        for conf in [0.3, 0.5, 0.7]:
            log_auto_feedback({
                "query": f"test {conf}",
                "suggested_route": "LOCAL",
                "reason": "test",
                "confidence": conf,
                "details": "",
            })
        # With cap at 0.5, 0.7 is capped to 0.5.
        # So stored confidences are [0.3, 0.5, 0.5].
        # With min_confidence=0.4, only the two 0.5 entries qualify.
        entries = load_auto_feedback(min_confidence=0.4)
        assert len(entries) == 2
        # With min_confidence=0.6, nothing qualifies.
        entries_high = load_auto_feedback(min_confidence=0.6)
        assert len(entries_high) == 0


class TestAutoFeedbackEnv:
    """Environment variable overrides."""

    def test_custom_max_confidence(self, tmp_path, monkeypatch):
        """LUCY_AUTO_FEEDBACK_MAX_CONFIDENCE env var is respected."""
        monkeypatch.setenv("LUCY_AUTO_FEEDBACK_MAX_CONFIDENCE", "0.3")
        # Re-import to pick up the new env value
        import importlib
        import auto_feedback
        importlib.reload(auto_feedback)

        test_path = tmp_path / "auto_feedback.jsonl"
        monkeypatch.setattr("auto_feedback.AUTO_FEEDBACK_PATH", test_path)

        suggestion = {
            "query": "test",
            "suggested_route": "LOCAL",
            "reason": "test",
            "confidence": 0.9,
            "details": "",
        }
        auto_feedback.log_auto_feedback(suggestion)
        entries = auto_feedback.load_auto_feedback(min_confidence=0.0)
        assert len(entries) == 1
        assert entries[0]["confidence"] == 0.3
