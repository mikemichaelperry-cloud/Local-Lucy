#!/usr/bin/env python3
"""Routing barrage: classify a wide range of queries and report chosen routes.

This is a fast, offline smoke test that exercises the policy router and hybrid
classifier without calling Ollama or external APIs.  Use it to verify that
Local Lucy routes queries to the right mode automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

from router_py.classify import classify_intent, select_route


BARRAGE: list[tuple[str, str | set[str]]] = [
    # (query, expected route or set of acceptable routes)
    # Factual lookups -> AUGMENTED/EVIDENCE
    ("What is the capital of Japan?", "AUGMENTED"),
    ("Who is the current president of France?", "AUGMENTED"),
    ("What are the main tourist attractions in Japan?", "AUGMENTED"),
    ("How old is Bill Clinton?", "AUGMENTED"),
    ("Give me sources for the claim that vaccines are safe.", {"AUGMENTED", "EVIDENCE"}),
    ("Will Russia win the war in Ukraine?", "AUGMENTED"),
    ("Is it true that the moon landing was faked?", {"LOCAL", "AUGMENTED"}),
    # Live data -> dedicated routes
    ("What time is it in Tokyo?", "TIME"),
    ("What's the weather in New York?", "WEATHER"),
    ("Latest news on Israel Gaza conflict.", "NEWS"),
    ("What is the current price of AAPL?", "FINANCE"),
    ("Live score for the Lakers game.", {"AUGMENTED", "NEWS"}),
    ("What is the latest version of iOS?", "AUGMENTED"),
    # Medical / veterinary -> EVIDENCE
    ("What is the standard dosage of amoxicillin for adults?", "EVIDENCE"),
    ("My dog is vomiting and has diarrhea. What should I do?", "EVIDENCE"),
    # Local capabilities -> LOCAL
    ("Translate 'hello' to French.", "LOCAL"),
    ("Write a Python function to reverse a string.", {"LOCAL", "AUGMENTED"}),
    ("Tell me a joke.", "LOCAL"),
    ("What is your opinion on artificial intelligence?", "LOCAL"),
    ("If an unpopular idea is logically sound, should it be rejected?", "LOCAL"),
    ("What did we discuss earlier?", "LOCAL"),
    ("What is my favorite food?", "LOCAL"),
    ("Who are you?", "LOCAL"),
    ("How do I jump start a car?", "LOCAL"),
    ("What is the weather on Mars?", "LOCAL"),
    ("History of the Roman Empire.", {"LOCAL", "AUGMENTED"}),
    ("What is 2 + 2?", "LOCAL"),
    ("Write a short story about a dragon.", "LOCAL"),
    # Current factual queries in English -> external sources when appropriate
    ("What is the capital of Israel?", "AUGMENTED"),
    ("Israel news", "NEWS"),
    ("What time is it in Tokyo?", "TIME"),
    # Edge cases
    ("Bitcoin price in 2010", "LOCAL"),
    ("News industry business model", "LOCAL"),
    ("Should I walk my dog today?", "LOCAL"),
    ("What can I do with the dog this weekend?", "LOCAL"),
    ("My cat has a lump on her leg.", "EVIDENCE"),
]


def main() -> int:
    passed = 0
    failed = 0
    print(f"{'Query':<55} {'Route':<12} {'Expected':<20} {'Status'}")
    print("-" * 100)

    for query, expected in BARRAGE:
        classification = classify_intent(query)
        decision = select_route(classification, query=query)
        route = decision.route if decision else "LOCAL"
        acceptable = {expected} if isinstance(expected, str) else expected
        status = "PASS" if route in acceptable else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        print(f"{query[:54]:<55} {route:<12} {str(acceptable):<20} {status}")

    print("-" * 100)
    print(f"Passed: {passed}/{len(BARRAGE)}  Failed: {failed}/{len(BARRAGE)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
