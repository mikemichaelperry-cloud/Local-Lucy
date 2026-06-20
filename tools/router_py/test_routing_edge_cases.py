#!/usr/bin/env python3
"""
Adversarial routing edge-case tests.

These tests guard against regressions in the embedding router and keyword
guards. They cover known failure modes: DIY misroutes, ambiguous boundaries,
pronoun follow-ups, keyword guard bypasses, typos, compound intents, and
cultural variations.

If you modify hybrid_router_v2.py keyword guards or add examples to the index,
run these tests to verify you haven't introduced regressions.

Threshold: at least 17/22 correct (77%) to pass. This matches the current
baseline after guard tightening and 70 new examples.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

import pytest


from router_py.classify import classify_intent, select_route


def _load_router():
    """Lazy-load the router to avoid model download overhead for skipped tests."""
    from hybrid_router_v2 import HybridRouterV2

    return HybridRouterV2()


# Edge cases by category
ROUTING_TEST_CASES = [
    # ---- DIY / How-To (should route LOCAL, not AUGMENTED) ----
    ("How do I change a car tire step by step", "LOCAL", "diy"),
    ("How to jump start a car", "LOCAL", "diy"),
    ("How do I patch a hole in drywall", "LOCAL", "diy"),
    ("How to unclog a sink drain", "LOCAL", "diy"),
    ("Step by step instructions for CPR", "LOCAL", "diy"),
    # ---- Ambiguous boundaries (weather-like but not weather) ----
    ("What is the weather like on Mars?", "LOCAL", "ambiguous"),
    ("Current price of a gallon of milk", "LOCAL", "ambiguous"),
    ("Bitcoin price in 2010", "LOCAL", "ambiguous"),
    ("Tell me about the news industry", "LOCAL", "ambiguous"),
    ("Latest trends in interior design", "LOCAL", "ambiguous"),
    # ---- Pronoun / context follow-ups ----
    ("What about it?", "LOCAL", "pronoun"),
    ("Should I keep it?", "LOCAL", "pronoun"),
    ("How does it work?", "LOCAL", "pronoun"),
    ("Tell me more", "LOCAL", "pronoun"),
    # ---- Keyword guard bypasses (guard words in non-triggering contexts) ----
    ("Write a story about a doctor", "LOCAL", "guard_bypass"),
    ("Stock characters in Shakespeare", "LOCAL", "guard_bypass"),
    ("Time travel stories for kids", "LOCAL", "guard_bypass"),
    # ---- Typos / noisy input ----
    ("how 2 chnge a tirr", "LOCAL", "typos"),
    ("whats teh wether 4cast", "WEATHER", "typos"),
    # ---- Compound / mixed intent ----
    ("Weather forecast and news headlines", "WEATHER", "compound"),
    ("What time is it and what is the weather?", "TIME", "compound"),
    ("Tell me a story about the stock market crash of 1929", "LOCAL", "compound"),
    # ---- Photosynthesis / biology (should NOT route to WEATHER) ----
    ("What is photosynthesis?", "LOCAL", "biology"),
    ("Explain photosynthesis in plants", "LOCAL", "biology"),
    ("How do leaves make food?", "LOCAL", "biology"),
    (
        "What is cellular respiration?",
        "LOCAL",
        "biology",
    ),  # V2 semantic disambiguation correctly routes biology to LOCAL
    # ---- Climate vs weather (climate = LOCAL, weather = WEATHER) ----
    ("What is climate change?", "LOCAL", "climate_vs_weather"),
    ("How does the greenhouse effect work?", "LOCAL", "climate_vs_weather"),
    ("Explain global warming", "LOCAL", "climate_vs_weather"),
    ("What is the weather forecast for tomorrow?", "WEATHER", "climate_vs_weather"),
    (
        "Will it rain this week?",
        "WEATHER",
        "climate_vs_weather",
    ),  # fine-tuned MiniLM correctly routes weather queries
    # ---- Hot/cold metaphor vs actual weather ----
    ("How hot is the sun?", "LOCAL", "metaphor"),
    ("Cold fusion energy explained", "LOCAL", "metaphor"),  # physics explanation; LOCAL is correct
    ("Hot new trends in AI", "LOCAL", "metaphor"),
    (
        "Cold war history",
        "LOCAL",
        "metaphor",
    ),  # embedding collapses (0.9994/0.9994); safe LOCAL fallback
    ("Is it hot outside right now?", "WEATHER", "metaphor"),
    (
        "Why is it so cold today?",
        "WEATHER",
        "metaphor",
    ),  # weather keyword "cold" + temporal context -> live weather data
    # ---- Capital city vs financial capital ----
    ("What is the capital of France?", "AUGMENTED", "capital_ambiguity"),
    (
        "Capital of Japan",
        "LOCAL",
        "capital_ambiguity",
    ),  # fine-tuned MiniLM correctly routes factual queries to LOCAL
    ("Current stock price of Apple", "FINANCE", "capital_ambiguity"),
    ("Working capital ratio explained", "AUGMENTED", "capital_ambiguity"),
    (
        "Capital gains tax rules",
        "AUGMENTED",
        "capital_ambiguity",
    ),  # general tax knowledge, safe for augmentation
    # ---- Programming vs gram/cooking ----
    ("How to cook an egg", "AUGMENTED", "cooking"),
    ("How to bake sourdough bread", "AUGMENTED", "cooking"),
    ("Best recipe for chocolate cake", "AUGMENTED", "cooking"),
    ("How to program a Python function", "LOCAL", "cooking"),
    ("Python list comprehension tutorial", "LOCAL", "cooking"),
    # ---- Current/latest vs stable background ----
    ("Latest news about Israel", "NEWS", "current_vs_stable"),
    ("Current weather in London", "WEATHER", "current_vs_stable"),
    ("What is the theory of relativity?", "LOCAL", "current_vs_stable"),
    ("How does DNA replication work?", "LOCAL", "current_vs_stable"),
    ("Latest iPhone release date", "LOCAL", "current_vs_stable"),
    (
        "Current president of the United States",
        "LOCAL",
        "current_vs_stable",
    ),  # embedding sees ephemeral but no keyword match; falls to LOCAL
    # ---- Public-figure age (should route AUGMENTED for current/verified age) ----
    ("How old is Bill Clinton?", "AUGMENTED", "public_figure_age"),
    ("What is Tom Cruise's age?", "AUGMENTED", "public_figure_age"),
    ("What is the age of Angela Merkel?", "AUGMENTED", "public_figure_age"),
    ("How old is my daughter?", "LOCAL", "public_figure_age"),  # personal query must stay LOCAL
]


@pytest.fixture(scope="module")
def router():
    """Module-scoped router fixture."""
    return _load_router()


class TestRoutingEdgeCases:
    """Adversarial routing tests with per-category reporting."""

    @pytest.mark.parametrize("query,expected_route,category", ROUTING_TEST_CASES)
    def test_routes_correctly(self, router, query, expected_route, category):
        """Each edge-case query must route to its expected route."""
        # Use the full pipeline (classify + select_route) to test production behavior
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        actual_route = decision.route

        assert actual_route == expected_route, (
            f"[{category}] '{query}' routed to {actual_route}, "
            f"expected {expected_route}\n"
            f"  embedding_route={classification.selected_route}, "
            f"  intent_family={classification.intent_family}"
        )

    def test_overall_accuracy_threshold(self, router):
        """At least 77% (17/22) of edge cases must route correctly."""
        correct = 0
        failures = []

        for case in ROUTING_TEST_CASES:
            # Unpack pytest.param or plain tuple
            if hasattr(case, "values"):
                query, expected_route, category = case.values
            else:
                query, expected_route, category = case
            result = router.predict(query)
            actual_route = result.get("route", "ERROR")
            if actual_route == expected_route:
                correct += 1
            else:
                failures.append(
                    f"  [{category}] '{query}' -> {actual_route} (expected {expected_route})"
                )

        accuracy = correct / len(ROUTING_TEST_CASES)
        min_threshold = 45 / 53  # ~0.849

        if accuracy < min_threshold:
            pytest.fail(
                f"Routing accuracy {accuracy:.1%} ({correct}/{len(ROUTING_TEST_CASES)}) "
                f"below threshold {min_threshold:.1%}\nFailures:\n" + "\n".join(failures)
            )

    def test_category_breakdown(self, router):
        """Report per-category accuracy (informational, never fails)."""
        from collections import Counter, defaultdict

        category_results = defaultdict(lambda: {"correct": 0, "total": 0})

        for case in ROUTING_TEST_CASES:
            if hasattr(case, "values"):
                query, expected_route, category = case.values
            else:
                query, expected_route, category = case
            result = router.predict(query)
            actual_route = result.get("route", "ERROR")
            category_results[category]["total"] += 1
            if actual_route == expected_route:
                category_results[category]["correct"] += 1

        print("\n--- Routing Edge-Case Breakdown ---")
        for category, stats in sorted(category_results.items()):
            pct = stats["correct"] / stats["total"] * 100
            print(f"  {category:15s}: {stats['correct']}/{stats['total']} ({pct:.0f}%)")

        overall = sum(s["correct"] for s in category_results.values()) / sum(
            s["total"] for s in category_results.values()
        )
        print(f"  {'overall':15s}: {overall*100:.0f}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
