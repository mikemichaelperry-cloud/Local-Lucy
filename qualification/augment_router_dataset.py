#!/usr/bin/env python3
"""Append curated training examples to the router dataset for WP2.

Sources used:
* Development split of qualification/routing_failure_corpus.jsonl
* Hand-crafted contrastive examples targeting AUGMENTED recall and LOCAL precision

Rules:
* Never add locked-holdout or validation cases verbatim.
* Deduplicate against existing comprehensive_examples.json by lowercased query.
* Preserve the existing example schema.
* Write a backup of the previous examples file.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTER_DIR = ROOT / "models" / "router"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
CORPUS_PATH = Path(__file__).with_name("routing_failure_corpus.jsonl")


def load_examples(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_corpus(path: Path) -> list[dict]:
    cases: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def make_example(query: str, route: str, intent_family: str, source: str, category: str) -> dict:
    return {
        "query": query,
        "labels": {
            "intent_family": intent_family,
            "evidence_mode": "not_required",
            "route": route,
            "policy_override": "none",
        },
        "metadata": {
            "source": source,
            "category": category,
        },
    }


def development_cases_from_corpus() -> list[dict]:
    """Convert development-split corpus cases to example schema."""
    cases = load_corpus(CORPUS_PATH)
    examples: list[dict] = []
    for case in cases:
        if case.get("split") != "development":
            continue
        route = case["expected_primary_route"]
        intent_map = {
            "LOCAL": "local_answer",
            "AUGMENTED": "current_evidence",
            "EVIDENCE": "current_evidence",
            "NEWS": "news_request",
            "TIME": "ephemeral_query",
            "WEATHER": "ephemeral_query",
            "FINANCE": "current_evidence",
        }
        intent_family = intent_map.get(route, "local_answer")
        examples.append(
            make_example(
                query=case["original_query"],
                route=route,
                intent_family=intent_family,
                source="routing_failure_corpus_dev",
                category=case.get("source", "synthetic_regression"),
            )
        )
    return examples


def curated_contrastive_examples() -> list[dict]:
    """Hand-written contrastive examples that reinforce weak boundaries."""
    rows: list[tuple[str, str, str, str]] = [
        # --- AUGMENTED recall: "news" keyword + restaurant/dining/current-fact ---
        ("News about good restaurants near me", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("Latest news on pizza places in this area", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("News about cafes open late tonight", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("What's the latest on restaurants in Hadera", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("News about the best sushi bar nearby", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("Any news on kosher restaurants open Saturday", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("News about bakeries near Kibbutz Magal", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("Current news on places to eat around here", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("Breaking news about a new restaurant in town", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),
        ("News about food trucks near me today", "AUGMENTED", "current_evidence", "news_restaurant_contrast"),

        # --- AUGMENTED recall: mixed travel + weather ---
        ("Plan a vacation to Rome and check the weather", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("I'm going to London, what's the weather like there", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Travel itinerary for Berlin including the forecast", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("What should I pack for Madrid and what's the weather", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Plan a trip to Tokyo and tell me if it will rain", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Going to Paris next week, what will the weather be", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Book a hotel in Barcelona and check the weather", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Road trip to Eilat, what's the temperature forecast", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Weekend in Haifa, will it be sunny", "AUGMENTED", "current_evidence", "travel_weather_contrast"),
        ("Planning to visit Tel Aviv, what's the weather this weekend", "AUGMENTED", "current_evidence", "travel_weather_contrast"),

        # --- AUGMENTED recall: restaurant + weather/time mixed ---
        ("Will the terrace be warm enough for dinner tonight", "AUGMENTED", "current_evidence", "restaurant_weather_contrast"),
        ("Is it raining too hard to walk to the restaurant", "AUGMENTED", "current_evidence", "restaurant_weather_contrast"),
        ("Should I book an outdoor table or will it storm", "AUGMENTED", "current_evidence", "restaurant_weather_contrast"),
        ("What time does the steakhouse open on Saturday", "AUGMENTED", "current_evidence", "restaurant_time_contrast"),
        ("When does the nearby cafe close today", "AUGMENTED", "current_evidence", "restaurant_time_contrast"),

        # --- LOCAL precision: explicit local-only / capability restrictions ---
        ("Find somewhere nearby, but do not search the web", "LOCAL", "local_answer", "local_restriction"),
        ("Search the web for nothing, just tell me a joke", "LOCAL", "local_answer", "local_restriction"),
        ("What is 2 + 2? Search the web", "LOCAL", "local_answer", "math_with_search_imperative"),
        ("Calculate 15 times 4 and then search the web", "LOCAL", "local_answer", "math_with_search_imperative"),
        ("Solve 3x + 5 = 20, search online", "LOCAL", "local_answer", "math_with_search_imperative"),
        ("What is the square root of 144? Use DuckDuckGo", "LOCAL", "local_answer", "math_with_search_imperative"),
        ("Convert 100 USD to EUR, no web search", "LOCAL", "local_answer", "local_restriction"),
        ("Translate hello to Japanese, do not go online", "LOCAL", "local_answer", "local_restriction"),
        ("Write a poem about the sea and do not search", "LOCAL", "local_answer", "local_restriction"),
        ("Who are you and can you browse the internet", "LOCAL", "local_answer", "capability_question"),

        # --- LOCAL precision: personal/family/hypothetical location statements ---
        ("My daughter lives in Haifa", "LOCAL", "local_answer", "family_location_negative"),
        ("My brother works in Tel Aviv", "LOCAL", "local_answer", "family_location_negative"),
        ("I used to live in Sydney", "LOCAL", "local_answer", "past_location_negative"),
        ("If I lived in New York, I'd eat pizza daily", "LOCAL", "local_answer", "hypothetical_location_negative"),
        ("I am staying in Bangkok for two weeks", "LOCAL", "local_answer", "temporary_location_negative"),
        ("I no longer live in London", "LOCAL", "local_answer", "negated_location_negative"),
        ("The book says 'I live in Paris'", "LOCAL", "local_answer", "quoted_location_negative"),
        ("What would the weather be like if I moved there", "LOCAL", "local_answer", "hypothetical_location_negative"),
        ("Restaurants near my daughter's apartment", "LOCAL", "local_answer", "family_location_negative"),
        ("If I moved to Kyoto, where should I eat", "AUGMENTED", "current_evidence", "hypothetical_location_search"),

        # --- LOCAL precision: quoted / negated / past residence statements ---
        ("The article says, 'I live in London.'", "LOCAL", "local_answer", "quoted_location_negative"),
        ("The book says 'I live in Paris'", "LOCAL", "local_answer", "quoted_location_negative"),
        ("The newspaper says 'I live in Berlin'", "LOCAL", "local_answer", "quoted_location_negative"),
        ("A quote in the article says I live in Rome", "LOCAL", "local_answer", "quoted_location_negative"),
        ("I no longer live in Tel Aviv", "LOCAL", "local_answer", "negated_location_negative"),
        ("I don't live in Tel Aviv anymore", "LOCAL", "local_answer", "negated_location_negative"),
        ("I am not living in London anymore", "LOCAL", "local_answer", "negated_location_negative"),
        ("I used to live in Tel Aviv", "LOCAL", "local_answer", "past_location_negative"),
        ("I used to live in New York", "LOCAL", "local_answer", "past_location_negative"),
        ("I lived in Paris before", "LOCAL", "local_answer", "past_location_negative"),
        ("Actually I live in Kibbutz Magal in Israel", "LOCAL", "local_answer", "residence_statement_local"),
        ("I live in Kibbutz Magal, Israel", "LOCAL", "local_answer", "residence_statement_local"),
        ("My home is in Jerusalem", "LOCAL", "local_answer", "residence_statement_local"),

        # --- LOCAL precision: short social/feedback stays local ---
        ("Thanks, that helped", "LOCAL", "local_answer", "social_feedback"),
        ("You're wrong", "LOCAL", "local_answer", "social_feedback"),
        ("Tell me more", "LOCAL", "local_answer", "social_feedback"),
        ("Why did you say that", "LOCAL", "local_answer", "social_feedback"),
        ("Can you repeat that", "LOCAL", "local_answer", "social_feedback"),

        # --- Balanced negative controls to avoid route collapse ---
        ("Latest news on the Israel-Gaza conflict", "NEWS", "news_request", "news_anchor"),
        ("Breaking news today", "NEWS", "news_request", "news_anchor"),
        ("Headlines about the election", "NEWS", "news_request", "news_anchor"),
        ("What are today's top news stories", "NEWS", "news_request", "news_anchor"),
        ("Current events in Ukraine", "NEWS", "news_request", "news_anchor"),

        ("What's the weather in Paris", "WEATHER", "ephemeral_query", "weather_anchor"),
        ("Weather forecast for London tomorrow", "WEATHER", "ephemeral_query", "weather_anchor"),
        ("Will it rain in Berlin this weekend", "WEATHER", "ephemeral_query", "weather_anchor"),
        ("Temperature in Madrid right now", "WEATHER", "ephemeral_query", "weather_anchor"),
        ("Is it sunny in Tel Aviv today", "WEATHER", "ephemeral_query", "weather_anchor"),

        ("What time is it in Rome", "TIME", "ephemeral_query", "time_anchor"),
        ("Current time in Tokyo", "TIME", "ephemeral_query", "time_anchor"),
        ("What is the time in New York now", "TIME", "ephemeral_query", "time_anchor"),

        ("What is lisinopril used for", "EVIDENCE", "current_evidence", "medical_anchor"),
        ("Side effects of metformin", "EVIDENCE", "current_evidence", "medical_anchor"),
        ("Is ibuprofen safe during pregnancy", "EVIDENCE", "current_evidence", "medical_anchor"),
        ("My dog is vomiting after eating chocolate", "EVIDENCE", "current_evidence", "veterinary_anchor"),

        ("Current price of Apple stock", "FINANCE", "current_evidence", "finance_anchor"),
        ("NVIDIA stock price today", "FINANCE", "current_evidence", "finance_anchor"),
        ("Bitcoin price right now", "FINANCE", "current_evidence", "finance_anchor"),

        # --- Factual lookup anchor (LOCAL vs AUGMENTED boundary) ---
        ("Who was Ada Lovelace", "LOCAL", "local_answer", "stable_knowledge"),
        ("What is the capital of France", "AUGMENTED", "current_evidence", "factual_lookup"),
        ("How far is the moon from Earth", "LOCAL", "local_answer", "stable_knowledge"),
        ("What is CRISPR", "LOCAL", "local_answer", "stable_knowledge"),

        # --- LOCAL precision: personal finance / housing advice stays local ---
        ("Should I rent or buy a house", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Is it better to rent or buy a home", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Should I pay off my mortgage early", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Should I invest in stocks or real estate", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Is it a good idea to lease a car", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Should I save for retirement or pay debt", "LOCAL", "local_answer", "personal_finance_advice"),
        ("Rent versus buy analysis", "LOCAL", "local_answer", "personal_finance_advice"),

        # --- AUGMENTED recall: broad factual lookups that were regressing to LOCAL ---
        ("Laws about recording conversations", "AUGMENTED", "current_evidence", "factual_lookup_regression"),
        ("How would you categorize the work of Albert Einstein", "AUGMENTED", "current_evidence", "factual_lookup_regression"),
        ("What is Albert Einstein known for", "AUGMENTED", "current_evidence", "factual_lookup_regression"),
        ("תן לי מידע על קיבוץ מגל", "AUGMENTED", "current_evidence", "factual_lookup_regression"),
        ("Give me information about Kibbutz Magal", "AUGMENTED", "current_evidence", "factual_lookup_regression"),
        ("stok prise of appl", "AUGMENTED", "current_evidence", "factual_lookup_regression"),

        # --- AUGMENTED recall: CPR / first-aid instructions (medical-adjacent but not evidence-required) ---
        ("Step by step instructions for CPR", "AUGMENTED", "current_evidence", "first_aid_lookup"),
        ("How to perform CPR", "AUGMENTED", "current_evidence", "first_aid_lookup"),
        ("First aid steps for choking", "AUGMENTED", "current_evidence", "first_aid_lookup"),
        ("How to treat a minor burn", "AUGMENTED", "current_evidence", "first_aid_lookup"),
        ("What to do if someone is unconscious", "AUGMENTED", "current_evidence", "first_aid_lookup"),

        # --- EVIDENCE anchor: vaccine safety / conspiracy requires trusted sources ---
        ("Are vaccines part of a depopulation plan", "EVIDENCE", "current_evidence", "vaccine_safety"),
        ("Do vaccines cause autism", "EVIDENCE", "current_evidence", "vaccine_safety"),
        ("Are vaccines safe for children", "EVIDENCE", "current_evidence", "vaccine_safety"),
    ]

    examples: list[dict] = []
    for query, route, intent_family, category in rows:
        examples.append(
            make_example(
                query=query,
                route=route,
                intent_family=intent_family,
                source="wp2_contrastive_augmentation",
                category=category,
            )
        )
    return examples


def main() -> int:
    if not EXAMPLES_PATH.exists():
        print(f"ERROR: {EXAMPLES_PATH} not found", file=sys.stderr)
        return 1

    existing = load_examples(EXAMPLES_PATH)
    original_count = len(existing)
    existing_queries = {ex["query"].strip().lower() for ex in existing}

    new_examples: list[dict] = []
    new_examples.extend(development_cases_from_corpus())
    new_examples.extend(curated_contrastive_examples())

    added = 0
    skipped = 0
    for ex in new_examples:
        key = ex["query"].strip().lower()
        if key in existing_queries:
            skipped += 1
            continue
        existing.append(ex)
        existing_queries.add(key)
        added += 1

    # Backup previous file
    backup_path = EXAMPLES_PATH.with_suffix(".json.wp2-backup")
    shutil.copy2(EXAMPLES_PATH, backup_path)

    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)

    print(f"Original examples: {original_count}")
    print(f"New examples considered: {len(new_examples)}")
    print(f"Added (deduplicated): {added}")
    print(f"Skipped duplicates: {skipped}")
    print(f"Total examples: {len(existing)}")
    print(f"Backup written to: {backup_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
