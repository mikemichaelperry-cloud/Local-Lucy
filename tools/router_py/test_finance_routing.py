#!/usr/bin/env python3
"""
FINANCE route tests for Local Lucy v10.

Validates that:
1. Live-market queries route to FINANCE
2. Non-finance queries do NOT route to FINANCE
3. Finance provider helpers correctly parse query types
4. ExecutionEngine handles FINANCE route with source labeling
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.classify import classify_intent, select_route, _is_financial_ephemeral
from router_py.providers.evidence import (
    _match_exchange_rate,
    _extract_stock_symbol,
    _extract_net_worth_person,
)
from router_py.execution_engine import ExecutionEngine
from router_py.request_types import ExecutionResult


class TestFinanceRouteDetection(unittest.TestCase):
    """Finance queries must route to FINANCE."""

    def _route(self, query: str):
        classification = classify_intent(query)
        return select_route(classification, "fallback_only", None, query, None)

    def test_stock_price_routes_to_finance(self):
        decision = self._route("What is Tesla stock price?")
        self.assertEqual(decision.route, "FINANCE")
        self.assertEqual(decision.provider, "finance")

    def test_exchange_rate_routes_to_finance(self):
        decision = self._route("EUR to USD")
        self.assertEqual(decision.route, "FINANCE")

    def test_net_worth_routes_to_finance(self):
        decision = self._route("How much is Elon Musk worth today?")
        self.assertEqual(decision.route, "FINANCE")

    def test_crypto_price_routes_to_finance(self):
        decision = self._route("Bitcoin price today")
        self.assertEqual(decision.route, "FINANCE")

    def test_index_routes_to_finance(self):
        decision = self._route("S&P 500 current value")
        self.assertEqual(decision.route, "FINANCE")

    def test_trillionaire_routes_to_finance(self):
        decision = self._route("Is Elon Musk a trillionaire?")
        self.assertEqual(decision.route, "FINANCE")

    def test_cooking_stays_local(self):
        decision = self._route("How to bake sourdough bread")
        self.assertNotEqual(decision.route, "FINANCE")

    def test_medical_stays_evidence(self):
        decision = self._route("What are the side effects of metformin")
        self.assertEqual(decision.route, "EVIDENCE")


class TestFinanceEphemeralDetector(unittest.TestCase):
    """Direct tests for the _is_financial_ephemeral helper."""

    def test_detects_live_stock(self):
        self.assertTrue(_is_financial_ephemeral("Apple stock price now"))

    def test_detects_fx(self):
        self.assertTrue(_is_financial_ephemeral("Euro to dollar rate"))

    def test_detects_net_worth(self):
        self.assertTrue(_is_financial_ephemeral("How much is Jeff Bezos worth?"))

    def test_detects_trillionaire(self):
        self.assertTrue(_is_financial_ephemeral("Is he a trillionaire today?"))

    def test_rejects_cooking(self):
        self.assertFalse(_is_financial_ephemeral("Best chocolate chip cookie recipe"))

    def test_rejects_medical(self):
        self.assertFalse(_is_financial_ephemeral("My dog is vomiting"))


class TestFinanceProviderHelpers(unittest.TestCase):
    """Unit tests for finance provider query parsing."""

    def test_match_exchange_rate_eur_usd(self):
        result = _match_exchange_rate("What is EUR to USD?")
        self.assertEqual(result, {"base": "EUR", "target": "USD"})

    def test_match_exchange_rate_euro_dollar(self):
        result = _match_exchange_rate("Euro to dollar")
        self.assertEqual(result, {"base": "EUR", "target": "USD"})

    def test_extract_stock_symbol_ticker(self):
        self.assertEqual(_extract_stock_symbol("TSLA stock price"), "TSLA")

    def test_extract_stock_symbol_company_name(self):
        self.assertEqual(_extract_stock_symbol("Microsoft stock price"), "MSFT")

    def test_extract_net_worth_person(self):
        self.assertEqual(_extract_net_worth_person("How much is Elon Musk worth?"), "Elon Musk")

    def test_extract_net_worth_rejects_pronouns(self):
        self.assertIsNone(_extract_net_worth_person("How much is he worth?"))

    def test_extract_net_worth_from_phrase(self):
        self.assertEqual(_extract_net_worth_person("Elon Musk net worth"), "Elon Musk")

    def test_extract_net_worth_possessive(self):
        self.assertEqual(_extract_net_worth_person("What is Jeff Bezos's net worth?"), "Jeff Bezos")

    def test_extract_crypto_symbol_from_name(self):
        self.assertEqual(_extract_stock_symbol("Bitcoin price"), "BITCOIN")

    def test_extract_crypto_symbol_from_ticker(self):
        self.assertEqual(_extract_stock_symbol("ETH price"), "ETH")


class TestFinanceExecutionLabeling(unittest.TestCase):
    """EVIDENCE fallback labeling must not apply to FINANCE route."""

    def setUp(self):
        self.engine = ExecutionEngine(config={"timeout": 30})
        self.base_result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="FINANCE",
            provider="finance",
            provider_usage_class="free",
            response_text="TSLA is at $250.",
            error_message="",
            metadata={},
        )

    def test_finance_route_not_labeled_as_evidence_fallback(self):
        evidence = {
            "fallback_used": True,
            "successful_backend": "wikipedia",
        }
        result = self.engine._label_evidence_fallback(self.base_result, evidence)
        self.assertEqual(result.response_text, "TSLA is at $250.")
        self.assertNotEqual(result.metadata.get("trust_class"), "trusted_fallback")
        self.assertNotIn("evidence_fallback_label_applied", result.metadata)


if __name__ == "__main__":
    unittest.main()
