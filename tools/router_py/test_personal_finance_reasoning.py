#!/usr/bin/env python3
"""
Tests for personal-finance reasoning routing.

Personal-finance reasoning (opinion, planning, advice) should stay LOCAL
so the model can reason with its knowledge. Live financial data lookups
(stock prices, rates, etc.) should still route to AUGMENTED/EVIDENCE.
"""

import pytest
from router_py.classify import classify_intent, select_route


class TestPersonalFinanceReasoning:
    """Verify personal-finance queries route correctly based on intent."""

    @pytest.mark.parametrize(
        "query",
        [
            "What would you consider to be a comfortable bank balance taking into consideration an additional 1 million shekels in my retirement fund and the Israeli standard pension?",
            "How should I budget for retirement?",
            "Should I invest in stocks or bonds?",
            "What is your opinion on my pension plan?",
            "What is a comfortable savings amount for a family of four?",
            "How much should I save for retirement?",
            "Is it worth paying off my mortgage early?",
            "What do you think about my investment strategy?",
        ],
    )
    def test_personal_finance_reasoning_routes_local(self, query):
        """Personal-finance reasoning should stay LOCAL."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "LOCAL", f"{query!r} should route to LOCAL, got {decision.route}"
        assert decision.provider == "local"
        # Evidence reason may be the legacy "personal_finance_reasoning" tag or
        # empty when the local-reasoning policy gate intercepts the query first.
        assert decision.evidence_reason in ("personal_finance_reasoning", "")

    @pytest.mark.parametrize(
        "query",
        [
            "What is the current stock price of Apple?",
            "Bitcoin price today",
            "Current inflation rate in Israel",
            "What is the exchange rate USD to ILS?",
            "NASDAQ index right now",
            "Federal Reserve interest rate today",
        ],
    )
    def test_live_financial_data_routes_finance(self, query):
        """Live financial data lookups should route to FINANCE."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert (
            decision.route == "FINANCE"
        ), f"{query!r} should route to FINANCE, got {decision.route}"
