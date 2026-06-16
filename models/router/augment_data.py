#!/usr/bin/env python3
"""Data augmentation using qwen3 to paraphrase and expand training examples.

Generates diverse, natural-sounding queries by asking qwen3 to rephrase
template-based synthetic examples into realistic user queries.
"""

import json
import random
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode

API_URL = "http://127.0.0.1:11434/api/generate"
MODEL = "local-lucy"


def generate_variations(template_query: str, intent: str, n: int = 3) -> list[str]:
    """Ask qwen3 to generate natural variations of a query."""
    prompt = f"""Generate {n} different ways a real person might ask this question.
Keep the same meaning but use different words, phrasing, or context.
Output ONLY the variations, one per line, no numbering.

Original: {template_query}
"""
    try:
        resp = requests.post(
            API_URL,
            json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.8, "num_predict": 200},
            },
            timeout=20,
        )
        resp.raise_for_status()
        content = resp.json().get("response", "").strip()

        # Split into lines and clean
        lines = [line.strip("-•* \t") for line in content.split("\n") if line.strip()]
        # Filter out lines that look like headers or explanations
        lines = [
            line
            for line in lines
            if len(line) > 10 and not line.lower().startswith(("here", "sure", "below", "the"))
        ]
        return lines[:n]
    except Exception as e:
        print(f"  Error generating variations: {e}")
        return []


def create_augmented_dataset(
    output_path: str = "augmented_training.jsonl", target_total: int = 1000
):
    """Create augmented dataset by generating diverse examples."""

    # Seed examples covering all intent families and domains
    seed_examples = [
        # local_answer
        ("What is 2+2?", "local_answer", "LOCAL"),
        ("How do you say hello in Japanese?", "local_answer", "LOCAL"),
        ("Debug this Python error: IndexError", "local_answer", "LOCAL"),
        ("Should I learn Python or JavaScript?", "local_answer", "LOCAL"),
        ("Help me write an email to my boss", "local_answer", "LOCAL"),
        ("What is the capital of France?", "local_answer", "LOCAL"),
        ("Tell me a joke", "local_answer", "LOCAL"),
        ("Calculate 15% of 240", "local_answer", "LOCAL"),
        # background_overview
        ("Who was Ada Lovelace?", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("What is quantum computing?", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("Explain the theory of relativity", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("What caused World War II?", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("How does photosynthesis work?", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("What is blockchain technology?", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("Tell me about the Roman Empire", "background_overview", "LOCAL_WITH_FALLBACK"),
        ("What is dark matter?", "background_overview", "LOCAL_WITH_FALLBACK"),
        # technical_explanation
        (
            "How does a transformer neural network work?",
            "technical_explanation",
            "LOCAL_WITH_FALLBACK",
        ),
        ("Explain TCP congestion control", "technical_explanation", "LOCAL_WITH_FALLBACK"),
        ("What is the algorithm behind Bitcoin?", "technical_explanation", "LOCAL_WITH_FALLBACK"),
        (
            "How does garbage collection work in Java?",
            "technical_explanation",
            "LOCAL_WITH_FALLBACK",
        ),
        (
            "Explain the math behind Fourier transforms",
            "technical_explanation",
            "LOCAL_WITH_FALLBACK",
        ),
        # current_evidence
        ("What are the symptoms of flu?", "current_evidence", "AUGMENTED"),
        ("Is metformin safe for diabetes?", "current_evidence", "AUGMENTED"),
        ("What does the latest research say about sleep?", "current_evidence", "AUGMENTED"),
        ("Clinical trial results for mRNA vaccines", "current_evidence", "AUGMENTED"),
        ("Peer-reviewed studies on climate change", "current_evidence", "AUGMENTED"),
        ("Current bitcoin price", "current_evidence", "AUGMENTED"),
        ("Stock price of Apple", "current_evidence", "AUGMENTED"),
        ("Is it legal to record conversations?", "current_evidence", "AUGMENTED"),
        # news_request
        ("Latest news on Israel", "news_request", "NEWS"),
        ("Breaking news about earthquake", "news_request", "NEWS"),
        ("What happened in Ukraine today?", "news_request", "NEWS"),
        ("Headlines about AI regulation", "news_request", "NEWS"),
        ("Sports news about Manchester United", "news_request", "NEWS"),
        # time_query
        ("What time is it in Tokyo?", "time_query", "TIME"),
        ("Current time in London", "time_query", "TIME"),
        ("How many days until Christmas?", "time_query", "TIME"),
        # creative_writing
        ("Write a story about a robot", "creative_writing", "LOCAL"),
        ("Create a poem about the ocean", "creative_writing", "LOCAL"),
        ("Imagine a world where gravity reverses", "creative_writing", "LOCAL"),
        ("Write a dialogue between Einstein and Newton", "creative_writing", "LOCAL"),
        # clarification
        ("What?", "clarification", "CLARIFY"),
        ("Explain", "clarification", "CLARIFY"),
        ("I don't understand", "clarification", "CLARIFY"),
        ("Tell me more", "clarification", "CLARIFY"),
    ]

    print(f"Generating augmented dataset targeting {target_total} examples...")
    print(f"Seed examples: {len(seed_examples)}")

    all_examples = []

    for query, intent, route in seed_examples:
        # Add original
        requires, reason = requires_evidence_mode(query)
        evidence = "required" if requires else "not_required"

        all_examples.append(
            {
                "query": query,
                "labels": {
                    "intent_family": intent,
                    "evidence_mode": evidence,
                    "route": route,
                    "policy_override": "none",
                },
                "metadata": {"source": "seed", "original": query},
            }
        )

        # Generate variations
        variations = generate_variations(query, intent, n=3)
        for var in variations:
            if var and var != query:
                requires, reason = requires_evidence_mode(var)
                evidence = "required" if requires else "not_required"
                all_examples.append(
                    {
                        "query": var,
                        "labels": {
                            "intent_family": intent,
                            "evidence_mode": evidence,
                            "route": route,
                            "policy_override": "none",
                        },
                        "metadata": {"source": "augmented", "original": query},
                    }
                )

        print(f"  {intent:25s}: {query[:40]:40s} -> {len(variations)} variations")
        time.sleep(0.5)  # Rate limit

    # If we don't have enough, duplicate with random selection
    while len(all_examples) < target_total:
        ex = random.choice(all_examples)
        all_examples.append(
            {
                "query": ex["query"],
                "labels": ex["labels"].copy(),
                "metadata": {
                    "source": "duplicated",
                    "original": ex["metadata"].get("original", ex["query"]),
                },
            }
        )

    random.shuffle(all_examples)
    all_examples = all_examples[:target_total]

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in all_examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nSaved {len(all_examples)} examples to {output_path}")

    # Print distribution
    from collections import Counter

    intent_dist = Counter(ex["labels"]["intent_family"] for ex in all_examples)
    print("\nIntent distribution:")
    for intent, count in sorted(intent_dist.items()):
        print(f"  {intent:25s}: {count}")

    return all_examples


if __name__ == "__main__":
    create_augmented_dataset()
