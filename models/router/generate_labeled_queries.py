#!/usr/bin/env python3
"""Generate diverse labeled queries using qwen3 for embedding router training.

Uses the local qwen3 model to generate realistic user queries for each
routing category, then labels them with the fixed legacy router.
"""

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from classify import ClassificationResult, select_route
from policy import requires_evidence_mode

API_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "local-lucy"


# Prompt templates for generating queries per category
CATEGORY_PROMPTS = {
    "local_answer": """Generate 10 realistic user queries that someone would ask an AI assistant like Siri, Alexa, or ChatGPT. These should be simple questions the AI can answer directly WITHOUT needing internet search.

Examples: math problems, translations, definitions, coding help, advice, opinions.

Requirements:
- Each query must be 5-20 words
- Be diverse: mix of math, coding, advice, definitions, translations
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "background_overview": """Generate 10 realistic user queries asking for factual knowledge or explanations about topics. These might benefit from web search but the AI may know the answer from training data.

Examples: historical figures, science concepts, geography, biography.

Requirements:
- Each query must be 5-20 words
- Be diverse: history, science, geography, culture, technology
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "technical_explanation": """Generate 10 realistic user queries asking for technical how-to instructions or deep technical explanations.

Examples: programming tutorials, system administration, debugging, algorithms.

Requirements:
- Each query must be 5-25 words
- Be diverse: different programming languages, tools, protocols
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "current_evidence": """Generate 10 realistic user queries that require verified, up-to-date information or evidence. These NEED web search or fact-checking.

Examples: medical advice, legal questions, current research, financial data, fact verification.

Requirements:
- Each query must be 5-25 words
- Be diverse: medical, legal, financial, scientific claims
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "news_request": """Generate 10 realistic user queries asking for current news or events.

Examples: breaking news, politics, sports, weather, world events.

Requirements:
- Each query must be 3-15 words
- Be diverse: world news, local news, sports, politics, tech
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "time_query": """Generate 10 realistic user queries about time, dates, or timezones.

Examples: current time in cities, timezone differences, date calculations.

Requirements:
- Each query must be 3-15 words
- Mention different cities/countries
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "creative_writing": """Generate 10 realistic user queries asking the AI to create creative content.

Examples: stories, poems, dialogues, fictional scenarios, imaginative content.

Requirements:
- Each query must be 5-20 words
- Be diverse: different genres, topics, formats
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
    "clarification": """Generate 10 realistic vague or ambiguous user queries that would need clarification.

Examples: single words, incomplete questions, follow-ups without context.

Requirements:
- Each query must be 1-10 words
- Be very brief and ambiguous
- Write EXACTLY one query per line
- No numbering, no explanations, just the queries

Generate 10 queries:""",
}


def generate_queries(category: str, count: int = 10) -> list[str]:
    """Use qwen3 to generate realistic queries for a category."""
    prompt = CATEGORY_PROMPTS.get(category, CATEGORY_PROMPTS["local_answer"])

    try:
        resp = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 300},
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json().get("response", "").strip()

        # Parse lines
        lines = [line.strip("-•* \t\"'") for line in content.split("\n") if line.strip()]
        lines = [
            line
            for line in lines
            if len(line) > 3
            and not line.lower().startswith(("here", "sure", "below", "the", "generate"))
        ]

        return lines[:count]
    except Exception as e:
        print(f"  Error generating {category}: {e}")
        return []


def label_with_legacy(query: str) -> dict:
    """Label a query using the fixed legacy router."""
    requires_evidence, evidence_reason = requires_evidence_mode(query)
    q_lower = query.lower()

    if any(k in q_lower for k in ["story", "poem", "novel", "compose a", "write a"]):
        family = "local_answer"
        needs_web = False
        cat = "creative"
    elif any(k in q_lower for k in ["news", "headlines", "latest news", "breaking"]):
        family = "current_evidence"
        needs_web = True
        cat = "news_world"
    elif any(k in q_lower for k in ["time is it", "current time", "what day is it", "timezone"]):
        family = "current_evidence"
        needs_web = True
        cat = "time_query"
    elif any(
        k in q_lower
        for k in ["symptom", "treatment", "medication", "dosage", "side effects", "is it safe"]
    ):
        family = "current_evidence"
        needs_web = True
        cat = "medical"
    elif any(
        k in q_lower
        for k in ["stock price", "bitcoin", "exchange rate", "interest rate", "market cap"]
    ):
        family = "current_evidence"
        needs_web = True
        cat = "financial"
    elif any(
        k in q_lower
        for k in ["legal to", "court ruling", "supreme court", "tenant rights", "statute"]
    ):
        family = "current_evidence"
        needs_web = True
        cat = "legal"
    elif any(k in q_lower for k in ["how to", "how do i", "install", "debug", "what is python"]):
        family = "local_answer"
        needs_web = False
        cat = "procedural"
    elif any(
        k in q_lower
        for k in [
            "who was",
            "who is",
            "what is the capital",
            "what is the speed",
            "when did",
            "what caused",
        ]
    ):
        family = "background_overview"
        needs_web = True
        cat = "informational"
    elif any(
        k in q_lower
        for k in ["hello", "who are you", "good morning", "how are you", "what is your name"]
    ):
        family = "local_answer"
        needs_web = False
        cat = "greeting"
    elif any(k in q_lower for k in ["what is 2+2", "what is 5+5", "calculate", "translate"]):
        family = "local_answer"
        needs_web = False
        cat = "math"
    else:
        family = "local_answer"
        needs_web = False
        cat = "general"

    classification = ClassificationResult(
        intent=family,
        intent_family=family,
        intent_class=family,
        category=cat,
        confidence=0.85,
        needs_web=needs_web,
        evidence_mode="required" if requires_evidence else "",
        evidence_reason=evidence_reason,
        augmentation_recommended=needs_web and not requires,
        force_local="story" in q_lower or "poem" in q_lower,
    )

    decision = select_route(classification, policy="fallback_only")

    return {
        "query": query,
        "labels": {
            "intent_family": family,
            "evidence_mode": "required" if requires_evidence else "not_required",
            "route": decision.route,
            "policy_override": "none",
        },
        "metadata": {"source": "qwen3_generated", "category": cat},
    }


def main():
    print("=" * 70)
    print("Generating Labeled Queries with Qwen3")
    print("=" * 70)

    all_examples = []
    categories = list(CATEGORY_PROMPTS.keys())

    for category in categories:
        print(f"\nGenerating {category}...")
        queries = generate_queries(category, count=10)
        print(f"  Got {len(queries)} queries")

        for q in queries:
            labeled = label_with_legacy(q)
            all_examples.append(labeled)
            print(f"  [{labeled['labels']['route']:15s}] {q[:60]}")

        time.sleep(1)  # Rate limit

    # Stats
    from collections import Counter

    intent_counts = Counter(ex["labels"]["intent_family"] for ex in all_examples)
    route_counts = Counter(ex["labels"]["route"] for ex in all_examples)

    print(f"\n{'=' * 70}")
    print(f"Generated {len(all_examples)} examples")
    print("\nIntent distribution:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")
    print("\nRoute distribution:")
    for route, count in sorted(route_counts.items()):
        print(f"  {route:20s}: {count}")

    # Save
    output_path = Path("generated_queries.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
