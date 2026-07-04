#!/usr/bin/env python3
"""Tests for automatic LOCAL -> AUGMENTED/EVIDENCE escalation fallback."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from execution_engine import ExecutionEngine
from router_py.request_types import ClassificationResult, ExecutionResult, RoutingDecision


class TestEscalationTrigger(unittest.TestCase):
    """Unit tests for _is_local_response_sufficient and _try_escalation_fallback."""

    def setUp(self):
        """Create an ExecutionEngine with state management mocked out."""
        self._state_manager_patcher = patch(
            "execution_engine.get_state_manager", return_value=MagicMock()
        )
        self._state_writer_patcher = patch("execution_engine.StateWriter", return_value=MagicMock())
        self._state_manager_patcher.start()
        self._state_writer_patcher.start()

        self.engine = ExecutionEngine(
            config={"state_dir": str(Path(__file__).parent / "test_state")}
        )

    def tearDown(self):
        self._state_manager_patcher.stop()
        self._state_writer_patcher.stop()

    def _make_route(self, route: str = "LOCAL") -> RoutingDecision:
        return RoutingDecision(
            route=route,
            mode="AUTO",
            intent_family="factual",
            confidence=0.8,
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
        )

    def _make_intent(self) -> ClassificationResult:
        return ClassificationResult(
            intent="ask",
            intent_family="factual",
            selected_route="LOCAL",
        )

    def test_admission_phrases_trigger_escalation(self):
        """Common 'I don't know' phrasing must be treated as insufficient."""
        admissions = [
            "I don't know.",
            "I do not know the answer.",
            "I have no information about that.",
            "No facts about a person named Bill Clinton.",
            "The provided persistent fact only mentions Mike's age.",
            "I'm not sure.",
            "I cannot provide that information.",
            "That is outside my knowledge.",
        ]
        for text in admissions:
            with self.subTest(text=text):
                self.assertFalse(
                    self.engine._is_local_response_sufficient(text),
                    f"Expected admission to trigger escalation: {text!r}",
                )

    def test_confident_answers_do_not_trigger_escalation(self):
        """Normal factual answers must be treated as sufficient."""
        answers = [
            "Bill Clinton is 79 years old.",
            "The capital of France is Paris.",
            "Sure, here's how to bake sourdough bread.",
        ]
        for text in answers:
            with self.subTest(text=text):
                self.assertTrue(
                    self.engine._is_local_response_sufficient(text),
                    f"Expected answer to be sufficient: {text!r}",
                )

    def test_general_query_escalates_to_augmented(self):
        """A non-medical insufficient LOCAL result escalates to AUGMENTED."""
        question = "How old is Bill Clinton?"
        local_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="I don't know.",
        )
        augmented_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            response_text="Bill Clinton is 79 years old.",
        )

        with patch.object(
            self.engine, "_call_augmented_provider", return_value=augmented_result
        ) as mock_call:
            result = self.engine._try_escalation_fallback(
                question,
                self._make_intent(),
                self._make_route("LOCAL"),
                {"question": question},
                local_result,
                "local_insufficient",
            )

        self.assertEqual(result.route, "AUGMENTED")
        self.assertEqual(result.outcome_code, "augmented_fallback")
        self.assertIn("Bill Clinton is 79 years old", result.response_text)
        mock_call.assert_called_once()
        passed_route = mock_call.call_args[0][2]
        self.assertEqual(passed_route.route, "LOCAL")

    def test_medical_query_escalates_to_evidence(self):
        """An insufficient LOCAL medical result escalates to EVIDENCE (trusted sources only)."""
        question = "What is the standard dosage of amoxicillin for adults?"
        local_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="I don't have that information.",
        )
        evidence_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="EVIDENCE",
            provider="trusted",
            provider_usage_class="trusted",
            response_text="Typical adult dosage is 500 mg every 8 hours.",
        )

        with patch.object(
            self.engine, "_call_augmented_provider", return_value=evidence_result
        ) as mock_call:
            with patch(
                "execution_engine.requires_evidence_mode",
                return_value=(True, "medical_context"),
            ):
                result = self.engine._try_escalation_fallback(
                    question,
                    self._make_intent(),
                    self._make_route("LOCAL"),
                    {"question": question},
                    local_result,
                    "local_insufficient",
                )

        self.assertEqual(result.route, "EVIDENCE")
        self.assertEqual(result.outcome_code, "evidence_fallback")
        self.assertIn("Typical adult dosage", result.response_text)
        mock_call.assert_called_once()
        passed_route = mock_call.call_args[0][2]
        self.assertEqual(passed_route.route, "EVIDENCE")
        self.assertEqual(passed_route.provider, "trusted")

    def test_escalation_failure_returns_local_result(self):
        """If the augmented/evidence call fails, the original LOCAL result is returned."""
        question = "What is the capital of Burkina Faso?"
        local_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="I don't know.",
        )
        failed_result = ExecutionResult(
            status="failed",
            outcome_code="provider_error",
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            response_text="",
            error_message="Provider unreachable",
        )

        with patch.object(self.engine, "_call_augmented_provider", return_value=failed_result):
            result = self.engine._try_escalation_fallback(
                question,
                self._make_intent(),
                self._make_route("LOCAL"),
                {"question": question},
                local_result,
                "local_insufficient",
            )

        self.assertEqual(result.route, "LOCAL")
        self.assertEqual(result.outcome_code, "local_fallback")
        self.assertEqual(result.response_text, "I don't know.")


if __name__ == "__main__":
    unittest.main()
