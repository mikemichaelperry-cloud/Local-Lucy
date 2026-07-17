#!/usr/bin/env python3
"""
Tests for NEWS vs AUGMENTED routing for news-related queries.

Pure news requests ("latest news about X") should route to NEWS (raw headlines).
Synthesis requests route according to the V2 embedding classifier without
keyword-guard overrides.
"""

import pytest
from router_py.classify import classify_intent, select_route


class TestNewsSynthesisRouting:
    """Verify news queries route correctly based on classifier decision."""

    @pytest.mark.parametrize(
        "query",
        [
            "Latest Israeli news",
            "Latest news about Israel",
            "What is happening in Gaza today",
            "Show me headlines from Iran",
            "Current events in Ukraine",
        ],
    )
    def test_pure_news_requests_route_to_news(self, query):
        """Pure news/headline requests should get raw NEWS route."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "NEWS", f"{query!r} should route to NEWS, got {decision.route}"
        assert decision.provider == "news"

    @pytest.mark.parametrize(
        "query,expected_route",
        [
            ("Probability of Israel-Iran war", "AUGMENTED"),
            ("Will Russia win in Ukraine", "AUGMENTED"),
        ],
    )
    def test_analysis_requests_route_to_augmented(self, query, expected_route):
        """Analysis/prediction requests route to AUGMENTED per classifier."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == expected_route, (
            f"{query!r} should route to {expected_route}, got {decision.route}"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "Cold war history",
            "What caused World War 2",
        ],
    )
    def test_historical_war_queries(self, query):
        """Historical war queries route to LOCAL (stable knowledge, not live news)."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "LOCAL", f"{query!r} should route to LOCAL, got {decision.route}"

    @pytest.mark.parametrize(
        "query",
        [
            "What's the latest world news?",
            "What is the latest world news?",
            "world news",
            "news today",
            "breaking news",
        ],
    )
    def test_news_keyword_guard_routes_news(self, query):
        """Unambiguous news phrasing should route to NEWS via keyword guard."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "NEWS", f"{query!r} should route to NEWS, got {decision.route}"
        assert decision.policy_reason == "router_news_guard"
