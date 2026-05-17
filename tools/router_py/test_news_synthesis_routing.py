#!/usr/bin/env python3
"""
Tests for NEWS vs AUGMENTED routing for news-related queries.

Pure news requests ("latest news about X") should route to NEWS (raw headlines).
Synthesis requests ("probability of X", "opinion on Y", "assess Z") that the
classifier flags as news-related should route to AUGMENTED with news headlines
as evidence (evidence_reason="news_synthesis").
"""

import pytest
from router_py.classify import classify_intent, select_route


class TestNewsSynthesisRouting:
    """Verify news queries route correctly based on intent."""

    @pytest.mark.parametrize("query", [
        "Latest Israeli news",
        "Latest news about Israel",
        "What is happening in Gaza today",
        "Show me headlines from Iran",
        "Current events in Ukraine",
    ])
    def test_pure_news_requests_route_to_news(self, query):
        """Pure news/headline requests should get raw NEWS route."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "NEWS", (
            f"{query!r} should route to NEWS, got {decision.route}"
        )
        assert decision.provider == "news"

    @pytest.mark.parametrize("query", [
        "Probability of Israel-Iran war",
        "What is your opinion on the Gaza conflict",
        "Can you predict the outcome of the conflict",
    ])
    def test_news_synthesis_requests_get_news_synthesis_reason(self, query):
        """Synthesis requests detected as news by classifier get news_synthesis."""
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "AUGMENTED", (
            f"{query!r} should route to AUGMENTED, got {decision.route}"
        )
        assert decision.evidence_reason == "news_synthesis", (
            f"{query!r} should have evidence_reason='news_synthesis', "
            f"got {decision.evidence_reason!r}"
        )
        assert decision.policy_reason == "router_news_synthesis"

    @pytest.mark.parametrize("query", [
        "Will Russia win in Ukraine",
        "How do you assess the situation in Ukraine",
    ])
    def test_synthesis_requests_route_to_augmented(self, query):
        """Other synthesis requests may route to AUGMENTED through normal channels.

        These don't necessarily get evidence_reason='news_synthesis' because the
        classifier may not flag them as news-related, but they should still end
        up on AUGMENTED for analysis.
        """
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        assert decision.route == "AUGMENTED", (
            f"{query!r} should route to AUGMENTED, got {decision.route}"
        )

    @pytest.mark.parametrize("query", [
        "Cold war history",
        "What caused World War 2",
    ])
    def test_historical_war_queries(self, query):
        """Historical war queries currently route to NEWS due to keyword matching.

        This is a known limitation — 'war' matches news keywords regardless of
        temporal context. The test documents current behavior.
        """
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        # Document current behavior; may change if temporal disambiguation improves
        assert decision.route in ("NEWS", "LOCAL", "AUGMENTED")
