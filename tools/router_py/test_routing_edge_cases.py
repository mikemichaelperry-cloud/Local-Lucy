#!/usr/bin/env python3
"""
Adversarial routing edge-case tests.

These tests guard against regressions in the embedding router and keyword
guards. They cover known failure modes: DIY misroutes, ambiguous boundaries,
pronoun follow-ups, keyword guard bypasses, typos, compound intents, and
cultural variations.

If you modify hybrid_router.py keyword guards or add examples to the index,
run these tests to verify you haven't introduced regressions.

Threshold: at least 17/22 correct (77%) to pass. This matches the current
baseline after guard tightening and 70 new examples.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

import pytest


def _load_router():
    """Lazy-load the router to avoid model download overhead for skipped tests."""
    from hybrid_router import HybridRouter
    return HybridRouter()


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
    # Known limitation: "news" keyword guard fires despite embedding LOCAL
    pytest.param("Tell me about the news industry", "LOCAL", "ambiguous", marks=pytest.mark.xfail(reason="news_keyword guard overrides embedding LOCAL")),
    ("Latest trends in interior design", "LOCAL", "ambiguous"),

    # ---- Pronoun / context follow-ups ----
    ("What about it?", "LOCAL", "pronoun"),
    ("Should I keep it?", "LOCAL", "pronoun"),
    ("How does it work?", "LOCAL", "pronoun"),
    ("Tell me more", "LOCAL", "pronoun"),

    # ---- Keyword guard bypasses (guard words in non-triggering contexts) ----
    ("Write a story about a doctor", "LOCAL", "guard_bypass"),
    # Known limitation: k=3 neighbors (2 TIME) override self LOCAL match
    pytest.param("Stock characters in Shakespeare", "LOCAL", "guard_bypass", marks=pytest.mark.xfail(reason="k=NN tie-break: 2 TIME neighbors override self LOCAL")),
    ("Time travel stories for kids", "LOCAL", "guard_bypass"),

    # ---- Typos / noisy input ----
    ("how 2 chnge a tirr", "LOCAL", "typos"),
    # Known limitation: heavy typos break embedding match; no typo guard for "wether"
    pytest.param("whats teh wether 4cast", "WEATHER", "typos", marks=pytest.mark.xfail(reason="heavy typos break embedding match for weather")),

    # ---- Compound / mixed intent ----
    ("Weather forecast and news headlines", "WEATHER", "compound"),
    ("What time is it and what is the weather?", "TIME", "compound"),
    ("Tell me a story about the stock market crash of 1929", "LOCAL", "compound"),
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
        result = router.predict(query)
        actual_route = result.get("route", "ERROR")

        assert actual_route == expected_route, (
            f"[{category}] '{query}' routed to {actual_route}, "
            f"expected {expected_route}\n"
            f"  embedding_route={result.get('embedding_route')}, "
            f"  guards_fired={result.get('guards_fired')}, "
            f"  top_k={[(n['route'], n['similarity']) for n in result.get('top_k_neighbours', [])[:2]]}"
        )

    def test_overall_accuracy_threshold(self, router):
        """At least 77% (17/22) of edge cases must route correctly."""
        correct = 0
        failures = []

        for case in ROUTING_TEST_CASES:
            # Unpack pytest.param or plain tuple
            if hasattr(case, 'values'):
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
        min_threshold = 17 / 22  # ~0.773

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
            if hasattr(case, 'values'):
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

        overall = sum(s["correct"] for s in category_results.values()) / sum(s["total"] for s in category_results.values())
        print(f"  {'overall':15s}: {overall*100:.0f}%")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
