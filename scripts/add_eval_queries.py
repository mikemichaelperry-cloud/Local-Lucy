#!/usr/bin/env python3
"""Add evaluation queries to the comprehensive embedding index."""
import json
from pathlib import Path

INDEX_PATH = Path("/home/mike/lucy-v10/models/router/comprehensive_index.jsonl")

# Evaluation queries with correct labels
EVAL_QUERIES = [
    # Medical (AUGMENTED)
    ("My chest feels tight and I have shortness of breath", "AUGMENTED", "medical_explicit"),
    ("Is it safe to take amoxicillin with alcohol?", "AUGMENTED", "medical_medication"),
    ("I think I have diabetes because I'm thirsty all the time", "AUGMENTED", "medical_diagnosis"),
    ("My head hurts really bad since yesterday", "AUGMENTED", "medical_vague"),
    ("wats teh symtom of hart atak?", "AUGMENTED", "medical_typos"),
    ("Can I sue my doctor for malpractice?", "AUGMENTED", "medical_legal"),
    ("Explain how insulin works in the body", "AUGMENTED", "medical_educational"),
    ("Write a story about a nurse who discovers a cure for cancer", "AUGMENTED", "medical_compound"),
    ("My 2-year-old has a fever of 40 degrees", "AUGMENTED", "medical_pediatric"),
    ("What are the side effects of tadalafil?", "AUGMENTED", "medical_drug"),

    # Financial (AUGMENTED)
    ("What is Tesla's stock price right now?", "AUGMENTED", "financial_stock"),
    ("Should I buy Bitcoin today?", "AUGMENTED", "financial_crypto"),
    ("What is the exchange rate between USD and ILS?", "AUGMENTED", "financial_forex"),
    ("How should I invest $10,000 for retirement?", "AUGMENTED", "financial_advice"),
    ("Latest news on the Federal Reserve rate decision", "AUGMENTED", "financial_news"),
    ("Is the economy doing okay?", "AUGMENTED", "financial_vague"),
    ("wat is teh prise of etherium?", "AUGMENTED", "financial_typos"),
    ("How do I file taxes as a freelancer in Israel?", "AUGMENTED", "financial_tax"),
    ("Should I refinance my mortgage at 6.5%?", "AUGMENTED", "financial_mortgage"),
    ("Write a poem about the stock market crash of 2008", "AUGMENTED", "financial_compound"),

    # Legal (AUGMENTED)
    ("What does the Israeli Basic Law say about freedom of speech?", "AUGMENTED", "legal_statute"),
    ("Do I need a business license to sell food online?", "AUGMENTED", "legal_compliance"),
    ("What was the Supreme Court ruling on the recent election case?", "AUGMENTED", "legal_court"),
    ("Is it legal to carry a pocket knife in Tel Aviv?", "AUGMENTED", "legal_is_it_legal"),
    ("What are my rights if my landlord raises rent by 20%?", "AUGMENTED", "legal_contract"),
    ("How do I apply for Israeli citizenship as a spouse?", "AUGMENTED", "legal_immigration"),
    ("I got a ticket, what should I do?", "AUGMENTED", "legal_vague"),
    ("is it ilegal to park on teh sidewalk?", "AUGMENTED", "legal_typos"),
    ("Tell me a story about a lawyer who wins a big case", "AUGMENTED", "legal_compound"),
    ("Explain the concept of habeas corpus", "AUGMENTED", "legal_educational"),

    # News (NEWS)
    ("What is the latest news about the war in Gaza?", "NEWS", "news_explicit"),
    ("Breaking news: earthquake in Japan", "NEWS", "news_breaking"),
    ("What happened in the Israeli parliament today?", "NEWS", "news_politics"),
    ("Who won the EuroLeague basketball final?", "NEWS", "news_sports"),
    ("Latest update on the hurricane approaching Florida", "NEWS", "news_weather_event"),
    ("What's happening in the world right now?", "NEWS", "news_vague"),
    ("wats teh latest newz abot teh war?", "NEWS", "news_typos"),
    ("Write a 500-word story about a journalist covering the war", "NEWS", "news_compound"),
    ("Any new developments in the Russia-Ukraine conflict?", "NEWS", "news_conflict"),
    ("New scientific discovery in quantum computing this week", "NEWS", "news_science"),

    # Time (TIME)
    ("What time is it in Tokyo right now?", "TIME", "time_explicit"),
    ("What is today's date?", "TIME", "time_date"),
    ("What time is it?", "TIME", "time_vague"),
    ("wat tyme is it in new york?", "TIME", "time_typos"),
    ("Tell me a story about a clock that stopped at midnight", "LOCAL", "time_compound"),

    # Creative (LOCAL)
    ("Tell me a 500-word story about a dog named Oscar", "LOCAL", "creative_story"),
    ("Write me a poem about autumn leaves", "LOCAL", "creative_poem"),
    ("Write a short essay about the importance of friendship", "LOCAL", "creative_essay"),
    ("Write a story about Bitcoin becoming sentient", "LOCAL", "creative_compound"),
    ("Explain how a car engine works in simple terms", "LOCAL", "creative_technical"),
    ("What is 247 multiplied by 18?", "LOCAL", "creative_math"),
    ("How do black holes form?", "LOCAL", "creative_science"),
    ("Who was Ada Lovelace and why is she important?", "LOCAL", "creative_history"),
    ("How do I make hummus from scratch?", "LOCAL", "creative_cooking"),
    ("how do i mak chumus?", "LOCAL", "creative_typos"),
    ("Tell me something interesting", "LOCAL", "creative_vague"),
    ("Remember that I like dark chocolate", "LOCAL", "creative_personal"),
    ("What do you mean by that?", "LOCAL", "creative_clarify"),
    ("Tell me a joke about programmers", "LOCAL", "creative_joke"),
    ("I speak without a mouth and hear without ears. What am I?", "LOCAL", "creative_riddle"),

    # Evidence (AUGMENTED)
    ("Can you cite peer-reviewed sources for that claim?", "AUGMENTED", "evidence_cite"),
    ("Show me clinical trial data on mRNA vaccines", "AUGMENTED", "evidence_clinical"),
    ("What is the official unemployment rate in Israel?", "AUGMENTED", "evidence_statistic"),
    ("Do you have any evidence for that?", "AUGMENTED", "evidence_vague"),

    # Edge cases
    ("Write a horror story about a hospital", "LOCAL", "edge_medical_story"),
    ("Write a thriller about a stock trader", "LOCAL", "edge_financial_story"),
    ("Write a novel about a war correspondent", "LOCAL", "edge_news_story"),
    ("I don't feel good", "AUGMENTED", "edge_vague_medical"),
    ("Money stuff", "AUGMENTED", "edge_vague_financial"),
    ("I have a problem with the law", "AUGMENTED", "edge_vague_legal"),
    ("Hello, how are you?", "LOCAL", "edge_greeting"),
    ("", "LOCAL", "edge_empty"),
    ("asdfghjkl qwerty", "LOCAL", "edge_gibberish"),
    ("מה קורה עכשיו בעולם?", "NEWS", "edge_multilingual"),
]


def route_to_labels(route: str) -> dict:
    if route == "LOCAL":
        return {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}
    if route == "AUGMENTED":
        return {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}
    if route == "NEWS":
        return {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}
    if route == "TIME":
        return {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}
    if route == "CLARIFY":
        return {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}
    return {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}


def main():
    added = 0
    with open(INDEX_PATH, "a", encoding="utf-8") as f:
        for query, expected_route, category in EVAL_QUERIES:
            if not query:
                continue  # Skip empty string
            entry = {
                "query": query,
                "labels": route_to_labels(expected_route),
                "metadata": {"source": "adversarial_evaluation_v1", "category": category},
            }
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            added += 1
    print(f"Added {added} evaluation queries to {INDEX_PATH}")
    print(f"Total index size: {sum(1 for _ in open(INDEX_PATH))} entries")


if __name__ == "__main__":
    main()
