#!/usr/bin/env python3
"""
Fast unit tests for deterministic low-confidence routing fallback.

These tests mock the embedding router and LLM arbiter so they do not need
sentence_transformers or a live Ollama instance.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.classify import ClassificationResult, select_route


class TestLowConfidenceFallback(unittest.TestCase):
    """Deterministic fallback when classifier confidence is low."""

    def setUp(self):
        """Disable deterministic policy gates so the embedding/arbiter path is exercised."""
        self._policy_router_patch = patch(
            "router_py.policy_router.PolicyRouter.apply", return_value=None
        )
        self._policy_router_patch.start()

    def tearDown(self):
        self._policy_router_patch.stop()

    def _low_confidence_router_result(self):
        """Return a mock router predicting LOCAL with low confidence."""
        mock_router = MagicMock()
        mock_router.predict.return_value = {
            "route": "LOCAL",
            "confidence": 0.45,
            "confidence_margin": 0.05,
            "intent_family": "factual",
            "evidence_mode": "",
            "evidence_reason": "",
        }
        return mock_router

    def test_low_confidence_fallback_to_augmented_when_needs_web(self):
        """Low confidence + web need falls back to AUGMENTED when arbiter is unavailable."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.45,
            needs_web=True,
            augmentation_recommended=True,
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                decision = select_route(
                    classification, query="What is the current population of Tokyo?"
                )

        self.assertEqual(decision.route, "AUGMENTED")
        self.assertTrue(decision.low_confidence)
        self.assertEqual(decision.policy_reason, "low_confidence_fallback")

    def test_low_confidence_fallback_to_evidence_for_medical(self):
        """Low confidence + medical context falls back to EVIDENCE/trusted."""
        classification = ClassificationResult(
            intent="medical_question",
            intent_family="factual",
            intent_class="medical_question",
            category="informational",
            confidence=0.45,
            evidence_reason="medical_context",
            evidence_mode="required",
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                decision = select_route(
                    classification, query="What are symptoms of appendicitis?"
                )

        self.assertEqual(decision.route, "EVIDENCE")
        self.assertEqual(decision.provider, "trusted")
        self.assertTrue(decision.low_confidence)

    def test_low_confidence_honors_force_local(self):
        """Low confidence does not override force_local."""
        classification = ClassificationResult(
            intent="creative_writing",
            intent_family="creative",
            intent_class="creative_writing",
            category="creative",
            confidence=0.45,
            force_local=True,
        )
        decision = select_route(classification, query="Write a poem about the moon.")

        self.assertEqual(decision.route, "LOCAL")

    def test_low_confidence_weather_fallback_only_when_query_is_weather(self):
        """A low-confidence LOCAL decision only falls back to WEATHER when the query actually looks like weather."""
        classification = ClassificationResult(
            intent="factual",
            intent_family="factual",
            intent_class="factual",
            category="informational",
            confidence=0.45,
            evidence_reason="weather_query",
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                with patch("router_py.classify_core.select._is_weather_query", return_value=True):
                    decision = select_route(classification, query="Will it rain today?")
        self.assertEqual(decision.route, "WEATHER")
        self.assertEqual(decision.policy_reason, "low_confidence_fallback")

    def test_low_confidence_weather_not_fallback_for_non_weather_query(self):
        """A restaurant query with a weather evidence_reason must not be forced to WEATHER."""
        classification = ClassificationResult(
            intent="factual",
            intent_family="factual",
            intent_class="factual",
            category="informational",
            confidence=0.45,
            evidence_reason="weather_query",
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                with patch("router_py.classify_core.select._is_weather_query", return_value=False):
                    decision = select_route(classification, query="restaurants open today near me")
        self.assertEqual(decision.route, "LOCAL")

    def test_low_confidence_time_fallback_only_when_query_is_time(self):
        """A low-confidence LOCAL decision only falls back to TIME when the query actually looks like time."""
        classification = ClassificationResult(
            intent="factual",
            intent_family="factual",
            intent_class="factual",
            category="informational",
            confidence=0.45,
            evidence_reason="time_query",
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                with patch("router_py.classify_core.select._is_time_query", return_value=True):
                    decision = select_route(classification, query="What time is it in Tokyo?")
        self.assertEqual(decision.route, "TIME")
        self.assertEqual(decision.policy_reason, "low_confidence_fallback")

    def test_low_confidence_time_not_fallback_for_non_time_query(self):
        """A non-time query with a time evidence_reason must not be forced to TIME."""
        classification = ClassificationResult(
            intent="factual",
            intent_family="factual",
            intent_class="factual",
            category="informational",
            confidence=0.45,
            evidence_reason="time_query",
        )
        with patch(
            "router_py.classify_core.select._get_router",
            return_value=self._low_confidence_router_result(),
        ):
            with patch("router_py.classify_core.select._call_llm_arbiter", return_value=None):
                with patch("router_py.classify_core.select._is_time_query", return_value=False):
                    decision = select_route(classification, query="restaurants open today near me")
        self.assertEqual(decision.route, "LOCAL")


if __name__ == "__main__":
    unittest.main()
