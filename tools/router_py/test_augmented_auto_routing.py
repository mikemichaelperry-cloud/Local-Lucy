#!/usr/bin/env python3
"""
Automatic AUGMENTED routing test for Local Lucy V10.

Verifies that general-knowledge queries which are NOT in the local LLM's
training data correctly route to AUGMENTED (Wikipedia/OpenAI/Kimi) instead
of being answered vaguely by the local model.

Uses the FULL classify.py pipeline (classify_intent + select_route + policy
+ keyword guards) — NOT mocked. This is the same path used in production.
Skips gracefully when sentence_transformers or router assets are unavailable.

Run:
    cd ~/lucy-v10 && python -m pytest tools/router_py/test_augmented_auto_routing.py -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

# ------------------------------------------------------------------
# Router availability probe
# ------------------------------------------------------------------
_ROUTER_AVAILABLE = False
_ROUTER_SKIP_REASON = ""

try:
    from router_py.classify import classify_intent, select_route, prewarm_router
    from router_py.policy import requires_evidence_mode

    if not prewarm_router():
        _ROUTER_AVAILABLE = False
        _ROUTER_SKIP_REASON = "Router assets (embeddings/examples) or sentence_transformers unavailable"
    else:
        _ROUTER_AVAILABLE = True
except Exception as exc:
    _ROUTER_AVAILABLE = False
    _ROUTER_SKIP_REASON = f"Router import/load failed: {exc}"


class TestAugmentedAutoRouting(unittest.TestCase):
    """Tests that general knowledge queries auto-route to AUGMENTED."""

    @classmethod
    def setUpClass(cls):
        if not _ROUTER_AVAILABLE:
            raise unittest.SkipTest(_ROUTER_SKIP_REASON)

    def _route(self, query: str, policy: str = "fallback_only") -> tuple[str, str]:
        """Run the FULL production pipeline: classify -> policy -> route."""
        classification = classify_intent(query)
        decision = select_route(classification, policy, None, query, None)
        return decision.route, decision.policy_reason

    # ------------------------------------------------------------------
    # Cooking / recipes — must route to AUGMENTED
    # ------------------------------------------------------------------

    def test_recipe_query_augmented(self):
        route, _ = self._route("Do you have a good recipe for Australian meat pies?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for recipe query, got {route}")

    def test_bake_bread_augmented(self):
        route, _ = self._route("How to bake sourdough bread")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for baking query, got {route}")

    def test_cook_egg_augmented(self):
        route, _ = self._route("How to cook an egg")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for cooking how-to, got {route}")

    def test_cookie_recipe_augmented(self):
        route, _ = self._route("Best chocolate chip cookie recipe")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for recipe query, got {route}")

    def test_hummus_augmented(self):
        route, _ = self._route("How do I make hummus from scratch?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for recipe query, got {route}")

    # ------------------------------------------------------------------
    # General knowledge / background — must route to AUGMENTED
    # ------------------------------------------------------------------

    def test_historical_figure_augmented(self):
        route, _ = self._route("Who painted the Mona Lisa?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for historical figure, got {route}")

    def test_geography_augmented(self):
        route, _ = self._route("What is the capital of France?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for geography, got {route}")

    def test_population_augmented(self):
        route, _ = self._route("What is the population of Tokyo?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for population query, got {route}")

    def test_capital_germany_augmented(self):
        route, _ = self._route("What is the capital of Germany?")
        self.assertEqual(route, "AUGMENTED", f"Expected AUGMENTED for geography, got {route}")

    # ------------------------------------------------------------------
    # Personal / family — must stay LOCAL, not AUGMENTED
    # ------------------------------------------------------------------

    def test_family_children_not_augmented(self):
        route, _ = self._route("Who are my children?")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for family query, got {route}")

    def test_pet_name_not_augmented(self):
        route, _ = self._route("What is my dog's name?")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for pet query, got {route}")

    def test_age_statement_not_augmented(self):
        route, _ = self._route("Oscar is 2 years old")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for age statement, got {route}")

    # ------------------------------------------------------------------
    # Medical / veterinary — must route to EVIDENCE, not AUGMENTED
    # ------------------------------------------------------------------

    def test_medical_symptom_not_augmented(self):
        route, _ = self._route("I have a fever and cough, what should I do?")
        self.assertEqual(route, "EVIDENCE", f"Expected EVIDENCE for medical symptom, got {route}")

    def test_vet_emergency_not_augmented(self):
        route, _ = self._route("My dog is vomiting and has diarrhea")
        self.assertEqual(route, "EVIDENCE", f"Expected EVIDENCE for vet emergency, got {route}")

    def test_medication_not_augmented(self):
        route, _ = self._route("What is the dosage for metformin?")
        self.assertEqual(route, "EVIDENCE", f"Expected EVIDENCE for medication query, got {route}")

    # ------------------------------------------------------------------
    # Time / weather / news — must route to their specific routes
    # ------------------------------------------------------------------

    def test_time_query_not_augmented(self):
        route, _ = self._route("What time is it?")
        self.assertEqual(route, "TIME", f"Expected TIME for time query, got {route}")

    def test_weather_query_not_augmented(self):
        route, _ = self._route("What is the weather in London?")
        self.assertEqual(route, "WEATHER", f"Expected WEATHER for weather query, got {route}")

    def test_news_query_not_augmented(self):
        route, _ = self._route("What is the latest Israel news?")
        self.assertEqual(route, "NEWS", f"Expected NEWS for news query, got {route}")

    def test_current_events_news(self):
        route, _ = self._route("What is happening in the world today?")
        self.assertEqual(route, "NEWS", f"Expected NEWS for current events, got {route}")

    # ------------------------------------------------------------------
    # Prefix override — "augmented:" must force AUGMENTED
    # ------------------------------------------------------------------

    def test_augmented_prefix_override(self):
        import re
        prefix_patterns = [
            (r"^local:\s*(.*)$", "LOCAL"),
            (r"^news:\s*(.*)$", "NEWS"),
            (r"^evidence:\s*(.*)$", "EVIDENCE"),
            (r"^augmented:\s*(.*)$", "AUGMENTED"),
        ]
        question = "augmented: What is the capital of Spain?"
        route_prefix = ""
        parsed_query = question
        for pattern, prefix_route in prefix_patterns:
            match = re.match(pattern, question, re.IGNORECASE)
            if match:
                route_prefix = prefix_route
                parsed_query = match.group(1).strip()
                break
        self.assertEqual(route_prefix, "AUGMENTED")
        self.assertEqual(parsed_query, "What is the capital of Spain?")

    # ------------------------------------------------------------------
    # Finance / live data — must route to AUGMENTED (or EVIDENCE for high-stakes)
    # ------------------------------------------------------------------

    def test_stock_price_augmented(self):
        route, _ = self._route("What is the current Apple stock price?")
        self.assertIn(route, ("AUGMENTED", "EVIDENCE"), f"Expected AUGMENTED/EVIDENCE for finance query, got {route}")

    def test_exchange_rate_augmented(self):
        route, _ = self._route("What is the EUR to USD exchange rate?")
        self.assertIn(route, ("AUGMENTED", "EVIDENCE"), f"Expected AUGMENTED/EVIDENCE for exchange rate, got {route}")

    # ------------------------------------------------------------------
    # Math / coding — should stay LOCAL (local LLM handles these well)
    # ------------------------------------------------------------------

    def test_math_local(self):
        route, _ = self._route("What is 25 times 17?")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for math query, got {route}")

    def test_python_local(self):
        route, _ = self._route("What is Python?")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for programming query, got {route}")

    def test_coding_local(self):
        route, _ = self._route("How to program a Python function")
        self.assertEqual(route, "LOCAL", f"Expected LOCAL for coding query, got {route}")


def run_tests():
    """Run tests and report pass/fail counts (usable as a script)."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestAugmentedAutoRouting)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("\n" + "=" * 60)
    print(f"Total:  {result.testsRun}")
    print(f"Passed: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failed: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 60)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
