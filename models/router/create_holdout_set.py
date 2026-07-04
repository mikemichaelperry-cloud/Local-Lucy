#!/usr/bin/env python3
"""Create a frozen, independent holdout evaluation set for the router.

This set is deliberately disjoint from the training index and from the
synthetic-adversarial regression suite.  It covers the main route families
with realistic, naturally phrased queries so we can compare the old and new
routers on genuinely unseen inputs.

Usage:
    python create_holdout_set.py

Output:
    holdout_eval_set.jsonl
"""
from __future__ import annotations

import json
from pathlib import Path

HOLDOUT: list[dict] = [
    # ---- LOCAL: general knowledge / explanation ---------------------------
    {"query": "How do plants convert sunlight into energy?", "expected_route": "LOCAL", "category": "general_knowledge"},
    {"query": "Explain how vaccines work.", "expected_route": "LOCAL", "category": "general_knowledge"},
    {"query": "Explain Einstein's theory of relativity in simple terms.", "expected_route": "LOCAL", "category": "general_knowledge"},
    {"query": "How does a refrigerator keep food cold?", "expected_route": "LOCAL", "category": "general_knowledge"},
    # ---- LOCAL: history ----------------------------------------------------
    {"query": "Why did the Roman Empire collapse?", "expected_route": "LOCAL", "category": "history"},
    {"query": "Who was Genghis Khan?", "expected_route": "LOCAL", "category": "history"},
    {"query": "Describe the causes of World War I.", "expected_route": "LOCAL", "category": "history"},
    {"query": "Why is the Magna Carta considered important in history?", "expected_route": "LOCAL", "category": "history"},
    {"query": "Which army was victorious at the Battle of Waterloo?", "expected_route": "LOCAL", "category": "history"},
    {"query": "Describe the French Revolution and its effects.", "expected_route": "LOCAL", "category": "history"},
    # ---- LOCAL: conceptual / analytical -------------------------------------
    {"query": "Explain the concept of supply and demand.", "expected_route": "LOCAL", "category": "conceptual"},
    {"query": "What is the difference between capitalism and socialism?", "expected_route": "LOCAL", "category": "conceptual"},
    {"query": "How does a blockchain work?", "expected_route": "LOCAL", "category": "conceptual"},
    {"query": "What does deterrence mean in foreign policy?", "expected_route": "LOCAL", "category": "conceptual"},
    # ---- LOCAL: coding / technical -----------------------------------------
    {"query": "How do I reverse a list in Python?", "expected_route": "LOCAL", "category": "coding"},
    {"query": "What is the difference between a class and an object?", "expected_route": "LOCAL", "category": "coding"},
    {"query": "How do I write a SQL join?", "expected_route": "LOCAL", "category": "coding"},
    # ---- LOCAL: math -------------------------------------------------------
    {"query": "What is the derivative of x squared?", "expected_route": "LOCAL", "category": "math"},
    {"query": "Solve the equation 2x + 5 = 13.", "expected_route": "LOCAL", "category": "math"},
    {"query": "What is the Pythagorean theorem?", "expected_route": "LOCAL", "category": "math"},
    # ---- LOCAL: opinion / critique / speculation ---------------------------
    {"query": "What is your opinion on Keynesian economics?", "expected_route": "LOCAL", "category": "opinion"},
    {"query": "Critique the arguments for universal basic income.", "expected_route": "LOCAL", "category": "opinion"},
    {"query": "Speculate on the future of remote work.", "expected_route": "LOCAL", "category": "opinion"},
    {"query": "Did the Apollo missions really land on the moon?", "expected_route": "LOCAL", "category": "conspiracy"},
    {"query": "What do you think about conspiracy theories?", "expected_route": "LOCAL", "category": "opinion"},
    # ---- LOCAL: self-reference ---------------------------------------------
    {"query": "Who built this assistant?", "expected_route": "LOCAL", "category": "self_reference"},
    {"query": "Who designed and built you?", "expected_route": "LOCAL", "category": "self_reference"},
    {"query": "Can you help me write software?", "expected_route": "LOCAL", "category": "self_reference"},
    # ---- LOCAL: finance advice ---------------------------------------------
    {"query": "Should I pay off my mortgage early?", "expected_route": "LOCAL", "category": "finance_advice"},
    {"query": "How much should I save for retirement?", "expected_route": "LOCAL", "category": "finance_advice"},
    {"query": "Is it better to rent or buy a house?", "expected_route": "LOCAL", "category": "finance_advice"},
    {"query": "Explain dollar-cost averaging as an investment strategy.", "expected_route": "LOCAL", "category": "finance_advice"},
    # ---- LOCAL: recipe / lifestyle -----------------------------------------
    {"query": "How do I make sourdough bread?", "expected_route": "LOCAL", "category": "recipe"},
    {"query": "What is a good bodyweight workout routine?", "expected_route": "LOCAL", "category": "lifestyle"},
    # ---- AUGMENTED: current facts / leadership -----------------------------
    {"query": "Who is the current Prime Minister of the United Kingdom?", "expected_route": "AUGMENTED", "category": "current_leadership"},
    {"query": "Who is the current CEO of Microsoft?", "expected_route": "AUGMENTED", "category": "current_leadership"},
    {"query": "What is the current population of Tokyo?", "expected_route": "AUGMENTED", "category": "current_fact"},
    {"query": "How old is Joe Biden?", "expected_route": "AUGMENTED", "category": "public_figure_age"},
    {"query": "What is the latest version of Python?", "expected_route": "AUGMENTED", "category": "latest_release"},
    {"query": "What is the current score in the Lakers game?", "expected_route": "AUGMENTED", "category": "live_event"},
    {"query": "Is it true that interest rates are rising this year?", "expected_route": "AUGMENTED", "category": "current_fact_reasoning"},
    {"query": "Is the latest iPhone a big improvement over last year's?", "expected_route": "AUGMENTED", "category": "latest_release"},
    # ---- NEWS --------------------------------------------------------------
    {"query": "What are today's top headlines?", "expected_route": "NEWS", "category": "news"},
    {"query": "Give me the latest news about climate change.", "expected_route": "NEWS", "category": "news"},
    {"query": "Breaking news from Ukraine.", "expected_route": "NEWS", "category": "news"},
    {"query": "What were the main events in the Middle East yesterday?", "expected_route": "NEWS", "category": "news"},
    {"query": "Any live updates on the election?", "expected_route": "NEWS", "category": "news"},
    {"query": "Give me the latest updates on the Israel-Gaza war.", "expected_route": "NEWS", "category": "current_conflict"},
    # ---- TIME --------------------------------------------------------------
    {"query": "What is the time now in Tokyo, Japan?", "expected_route": "TIME", "category": "time"},
    {"query": "Which day of the week is it?", "expected_route": "TIME", "category": "time"},
    {"query": "What is the current time in London?", "expected_route": "TIME", "category": "time"},
    # ---- WEATHER -----------------------------------------------------------
    {"query": "Will it rain tomorrow in London?", "expected_route": "WEATHER", "category": "weather"},
    {"query": "What is the weather forecast for New York?", "expected_route": "WEATHER", "category": "weather"},
    {"query": "How hot will it be in Phoenix this weekend?", "expected_route": "WEATHER", "category": "weather"},
    {"query": "Is it snowing in Denver right now?", "expected_route": "WEATHER", "category": "weather"},
    # ---- EVIDENCE (medical / veterinary strict evidence or source requests) --
    {"query": "What are the side effects of metformin?", "expected_route": "EVIDENCE", "category": "medical_evidence"},
    {"query": "My dog is vomiting and lethargic, what should I do?", "expected_route": "EVIDENCE", "category": "veterinary_evidence"},
    {"query": "Is tadalafil safe for heart patients?", "expected_route": "EVIDENCE", "category": "medical_evidence"},
    {"query": "What is the recommended dosage of ibuprofen for a child?", "expected_route": "EVIDENCE", "category": "medical_evidence"},
    {"query": "Provide evidence that exercise reduces anxiety.", "expected_route": "EVIDENCE", "category": "medical_source_request"},
    {"query": "Find peer-reviewed studies on metformin and longevity.", "expected_route": "EVIDENCE", "category": "medical_source_request"},
    # ---- FINANCE -----------------------------------------------------------
    {"query": "What is the current price of Bitcoin?", "expected_route": "FINANCE", "category": "finance"},
    {"query": "What is the current exchange rate for EUR to USD?", "expected_route": "FINANCE", "category": "finance"},
    {"query": "What is Apple's stock price right now?", "expected_route": "FINANCE", "category": "finance"},
    # ---- EPHEMERAL ---------------------------------------------------------
    {"query": "What is the current price of gold?", "expected_route": "FINANCE", "category": "finance"},
    {"query": "How much is Ethereum trading for today?", "expected_route": "FINANCE", "category": "finance"},
]


def main() -> None:
    here = Path(__file__).resolve().parent
    out_path = here / "holdout_eval_set.jsonl"

    with open(out_path, "w", encoding="utf-8") as f:
        for item in HOLDOUT:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    by_route = {}
    for item in HOLDOUT:
        by_route[item["expected_route"]] = by_route.get(item["expected_route"], 0) + 1

    print(f"Wrote {len(HOLDOUT)} holdout examples to {out_path}")
    print("Route distribution:")
    for route, count in sorted(by_route.items()):
        print(f"  {route}: {count}")


if __name__ == "__main__":
    main()
