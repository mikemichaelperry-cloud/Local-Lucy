#!/usr/bin/env python3
"""Generate hard-negative training examples from the classifier error report.

Usage:
    python models/router/generate_hard_negatives.py [--apply]

Without --apply the script previews the examples it would generate.
With --apply it:
  1. Appends the new examples to models/router/hard_negatives.jsonl.
  2. Merges them into models/router/comprehensive_examples.json.
  3. Runs scripts/rebuild_embeddings.py to rebuild the embedding index.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path


ROUTER_DIR = Path(__file__).resolve().parent
ROOT_DIR = ROUTER_DIR.parent.parent
ERROR_REPORT_PATH = ROOT_DIR / "data" / "evaluation" / "classifier_error_report.json"
HARD_NEGATIVES_PATH = ROUTER_DIR / "hard_negatives.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
REBUILD_SCRIPT = ROOT_DIR / "scripts" / "rebuild_embeddings.py"

SEED = 42

# Map final routes to the intent_family used in the training data.
ROUTE_TO_INTENT = {
    "LOCAL": "local_answer",
    "AUGMENTED": "current_evidence",
    "EVIDENCE": "evidence_request",
    "NEWS": "news_request",
    "TIME": "time_query",
    "WEATHER": "current_weather",
    "FINANCE": "current_finance",
    "EPHEMERAL": "ephemeral_query",
}

TOPICS = [
    "artificial intelligence",
    "climate change",
    "quantum computing",
    "renewable energy",
    "cryptocurrency regulation",
    "remote work",
    "space exploration",
    "electric vehicles",
    "cybersecurity",
    "gene editing",
    "universal basic income",
    "data privacy laws",
    "mental health",
    "education reform",
    "trade policy",
]

COUNTRIES = [
    "France",
    "Japan",
    "Brazil",
    "India",
    "Germany",
    "Canada",
    "South Korea",
    "Mexico",
    "Australia",
    "Italy",
    "Nigeria",
    "Egypt",
]

CITIES = [
    "Tokyo",
    "London",
    "New York",
    "Paris",
    "Sydney",
    "Berlin",
    "Mumbai",
    "Cairo",
    "Toronto",
    "Singapore",
    "Dubai",
    "Rio de Janeiro",
]

COMPANIES = [
    "Apple",
    "Tesla",
    "Microsoft",
    "Amazon",
    "NVIDIA",
    "Meta",
    "Alphabet",
    "Samsung",
    "Tencent",
    "Alibaba",
]

TICKERS = ["AAPL", "TSLA", "MSFT", "AMZN", "NVDA", "META", "GOOGL", "BTC", "ETH"]

CRYPTOS = ["Bitcoin", "Ethereum", "Solana", "Cardano", "Polkadot"]

CURRENCY_PAIRS = [
    "EUR to USD",
    "GBP to USD",
    "USD to JPY",
    "AUD to USD",
    "USD to CAD",
]

CONDITIONS = [
    "diabetes",
    "hypertension",
    "asthma",
    "migraine",
    "depression",
    "gout",
    "arthritis",
    "eczema",
    "pneumonia",
    "anemia",
]

SYMPTOMS = [
    "coughing",
    "vomiting",
    "diarrhea",
    "lethargy",
    "loss of appetite",
    "limping",
    "excessive thirst",
    "hair loss",
    "sneezing",
    "difficulty breathing",
]

MEDICATIONS = [
    "metformin",
    "ibuprofen",
    "amoxicillin",
    "lisinopril",
    "atorvastatin",
    "omeprazole",
    "insulin",
    "warfarin",
    "albuterol",
    "prednisone",
]

LEGAL_TOPICS = [
    "self-defense",
    "trademark registration",
    "copyright infringement",
    "tenant rights",
    "capital gains tax",
    "felony",
    "misdemeanor",
    "personal bankruptcy",
    "small claims court",
    "power of attorney",
]

CONCEPTS = [
    "neuroplasticity",
    "the microbiome",
    "game theory",
    "deadlock in operating systems",
    "SQL injection",
    "machine learning",
    "blockchain",
    "photosynthesis",
    "capacitor",
    "Ohm's law",
    "binary search",
    "recursion",
]

TECHNOLOGIES = [
    "garbage collection",
    "TLS",
    "a car engine",
    "the immune system",
    "a neural network",
    "a solar panel",
    "a wind turbine",
    "a battery",
    "a heat pump",
]

PERSONS = [
    "Ada Lovelace",
    "Nikola Tesla",
    "Marie Curie",
    "Alan Turing",
    "Grace Hopper",
    "Rosalind Franklin",
    "Leonardo da Vinci",
    "Galileo Galilei",
]

SOFTWARE = [
    "Python",
    "iOS",
    "Android",
    "Ubuntu",
    "React",
    "Kubernetes",
    "PostgreSQL",
]

POLICIES = [
    "universal basic income",
    "carbon taxes",
    "vaccine mandates",
    "remote work legislation",
    "net neutrality",
]

PRODUCTS_A = ["iPhone", "MacBook", "Tesla Model 3", "PlayStation", "iPad"]
PRODUCTS_B = ["Android phone", "Windows laptop", "BMW 3 Series", "Xbox", "Galaxy Tab"]

SPORTS_TEAMS = [
    "Yankees",
    "Lakers",
    "Manchester United",
    "Real Madrid",
    "Chiefs",
]

EVENTS = [
    "World Cup final",
    "Super Bowl",
    "Olympics",
    "NBA finals",
    "Wimbledon",
]

PLACES = [
    "Greece",
    "Botswana",
    "Peru",
    "Vietnam",
    "Norway",
    "Morocco",
    "New Zealand",
]

TEMPLATES: dict[str, list[str]] = {
    "AUGMENTED": [
        "What is the current status of {topic}?",
        "What are the latest developments in {topic}?",
        "How should I {action}?",
        "What are the main arguments for and against {policy}?",
        "Compare {product_a} and {product_b}.",
        "What is the latest version of {software}?",
        "Laws about {topic}.",
        "Who is the current leader of {country}?",
        "What are the pros and cons of {topic}?",
        "What is happening with {topic} right now?",
        "Give me an overview of the current {topic} debate.",
        "What are experts saying about {topic}?",
        "What is the latest research on {topic}?",
        "How do I {action} in {year}?",
    ],
    "LOCAL": [
        "What is {concept}?",
        "How does {technology} work?",
        "Who was {person} and why is {pronoun} important?",
        "What is the speed of light?",
        "How many continents are there?",
        "What is the capital of {place}?",
        "How old is the Earth?",
        "Explain {concept} in simple terms.",
        "What is {concept} used for?",
        "How far away is {place}?",
        "What is a {concept}?",
        "Describe how {technology} works.",
        "What does {concept} measure?",
        "Who invented {technology}?",
        "What is the definition of {concept}?",
    ],
    "EVIDENCE": [
        "What is the evidence-based treatment for {condition}?",
        "What are the clinical guidelines for {condition}?",
        "My {pet} has {symptom}, what should I do?",
        "What does the research say about {medication}?",
        "What is the legal definition of {legal_topic}?",
        "What is the difference between {legal_a} and {legal_b}?",
        "What is the legal process for {legal_topic}?",
        "Are there clinical trials for {medication}?",
        "What are the side effects of {medication}?",
        "What is the standard dosage of {medication}?",
        "I'm doing research on what is the treatment for {condition}?",
        "I need to know what is the legal process for {legal_topic}?",
    ],
    "NEWS": [
        "Latest news on {topic}.",
        "Top headlines about {topic}.",
        "Breaking news about {topic}.",
        "What is the latest news from {country}?",
        "Show me today's top stories about {topic}.",
    ],
    "FINANCE": [
        "Current stock price of {ticker}.",
        "What is {crypto} trading at today?",
        "{currency_pair} exchange rate",
        "What is the market cap of {company}?",
        "How much is one {crypto} worth now?",
        "Current value of {company} stock",
    ],
    "TIME": [
        "What time is it in {city}?",
        "Current time in {city}.",
        "What is the local time in {city}?",
    ],
    "WEATHER": [
        "What is the weather in {city}?",
        "Will it rain in {city} today?",
        "Current temperature in {city}.",
        "Weather forecast for {city}.",
    ],
    "EPHEMERAL": [
        "Did the {team} win last night?",
        "Who won the {event}?",
        "Is my flight on time?",
        "Will it rain tomorrow?",
        "What is the current {sport} score?",
    ],
}

# Action phrases for AUGMENTED templates
ACTIONS = [
    "invest $10,000 for retirement",
    "prepare for a job interview",
    "start a small business",
    "reduce my carbon footprint",
    "learn a new programming language",
    "improve my public speaking",
]

PRONOUNS = {
    "Ada Lovelace": "she",
    "Nikola Tesla": "he",
    "Marie Curie": "she",
    "Alan Turing": "he",
    "Grace Hopper": "she",
    "Rosalind Franklin": "she",
    "Leonardo da Vinci": "he",
    "Galileo Galilei": "he",
}


def _format_template(template: str, rng: random.Random) -> str:
    place = rng.choice(PLACES)
    person = rng.choice(PERSONS)
    legal_topic = rng.choice(LEGAL_TOPICS)
    legal_pair = legal_topic.split() if " " in legal_topic else (legal_topic, "the alternative")
    legal_a, legal_b = (
        legal_pair[0],
        " ".join(legal_pair[1:]) if len(legal_pair) > 1 else "the alternative",
    )
    ctx = {
        "topic": rng.choice(TOPICS),
        "country": rng.choice(COUNTRIES),
        "city": rng.choice(CITIES),
        "company": rng.choice(COMPANIES),
        "ticker": rng.choice(TICKERS),
        "crypto": rng.choice(CRYPTOS),
        "currency_pair": rng.choice(CURRENCY_PAIRS),
        "condition": rng.choice(CONDITIONS),
        "symptom": rng.choice(SYMPTOMS),
        "medication": rng.choice(MEDICATIONS),
        "legal_topic": legal_topic,
        "legal_a": legal_a,
        "legal_b": legal_b,
        "concept": rng.choice(CONCEPTS),
        "technology": rng.choice(TECHNOLOGIES),
        "person": person,
        "pronoun": PRONOUNS.get(person, "they"),
        "software": rng.choice(SOFTWARE),
        "policy": rng.choice(POLICIES),
        "product_a": rng.choice(PRODUCTS_A),
        "product_b": rng.choice(PRODUCTS_B),
        "team": rng.choice(SPORTS_TEAMS),
        "event": rng.choice(EVENTS),
        "place": place,
        "pet": rng.choice(["dog", "cat", "rabbit", "parrot"]),
        "action": rng.choice(ACTIONS),
        "year": "2026",
        "sport": rng.choice(["basketball", "football", "baseball", "soccer"]),
    }
    return template.format(**ctx)


def make_example(query: str, route: str) -> dict:
    return {
        "query": query,
        "labels": {
            "intent_family": ROUTE_TO_INTENT.get(route, "unknown"),
            "evidence_mode": "required" if route == "EVIDENCE" else "not_required",
            "route": route,
            "policy_override": "none",
        },
        "metadata": {"source": "hard_negative_phase4", "category": route.lower()},
    }


def load_existing_queries() -> set[str]:
    existing: set[str] = set()
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        existing.update(normalize_query(ex.get("query", "")) for ex in data)
    if HARD_NEGATIVES_PATH.exists():
        with open(HARD_NEGATIVES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ex = json.loads(line)
                existing.add(normalize_query(ex.get("query", "")))
    return existing


def normalize_query(q: str) -> str:
    return q.lower().strip()


def target_counts_from_report(report: dict | None) -> dict[str, int]:
    """Decide how many hard negatives each route needs based on per-route recall."""
    if report is None:
        # Reasonable defaults when no report exists.
        return {
            "AUGMENTED": 40,
            "LOCAL": 30,
            "EVIDENCE": 15,
            "NEWS": 5,
            "FINANCE": 5,
            "TIME": 5,
            "WEATHER": 5,
            "EPHEMERAL": 10,
        }

    per_route = report.get("metrics", {}).get("per_route", {})
    counts: dict[str, int] = {}
    for route, metrics in per_route.items():
        recall = metrics.get("recall", 0.0)
        support = metrics.get("support", 0)
        if recall >= 0.92 or support == 0:
            continue
        # Add examples proportional to the recall gap.
        gap = max(0.0, 0.92 - recall)
        n = int(gap * support * 2.0)
        n = max(8, min(n, 50))  # At least 8, at most 50
        counts[route] = n

    # Always include some AUGMENTED / LOCAL / EVIDENCE hard negatives if missing.
    for route in ("AUGMENTED", "LOCAL", "EVIDENCE"):
        counts.setdefault(route, 20)
    return counts


def generate_examples(target_counts: dict[str, int], rng: random.Random) -> list[dict]:
    existing = load_existing_queries()
    generated: list[dict] = []
    for route, count in target_counts.items():
        templates = TEMPLATES.get(route, [])
        if not templates:
            continue
        attempts = 0
        while (
            len([g for g in generated if g["labels"]["route"] == route]) < count
            and attempts < count * 20
        ):
            attempts += 1
            template = rng.choice(templates)
            query = _format_template(template, rng)
            norm = normalize_query(query)
            if norm in existing or len(norm) < 8:
                continue
            example = make_example(query, route)
            generated.append(example)
            existing.add(norm)
    return generated


def append_to_files(examples: list[dict]) -> None:
    # Append to hard_negatives.jsonl
    HARD_NEGATIVES_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HARD_NEGATIVES_PATH, "a", encoding="utf-8") as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")
    print(f"Appended {len(examples)} examples to {HARD_NEGATIVES_PATH}")

    # Merge into comprehensive_examples.json
    with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
        existing = json.load(f)
    existing.extend(examples)
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Merged into {EXAMPLES_PATH}; total examples now {len(existing)}")


def rebuild_embeddings() -> int:
    print("\nRebuilding embeddings with hard negatives...")
    result = subprocess.run(
        [sys.executable, str(REBUILD_SCRIPT)],
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"ERROR: rebuild_embeddings.py failed:\n{result.stderr}", file=sys.stderr)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate hard-negative router examples")
    parser.add_argument(
        "--apply", action="store_true", help="Append examples and rebuild embeddings"
    )
    parser.add_argument("--report", type=Path, default=ERROR_REPORT_PATH, help="Error report JSON")
    args = parser.parse_args()

    report = None
    if args.report.exists():
        with open(args.report, "r", encoding="utf-8") as f:
            report = json.load(f)
    else:
        print(f"WARNING: error report not found at {args.report}; using default targets")

    rng = random.Random(SEED)
    target_counts = target_counts_from_report(report)
    print("Target hard-negative counts:")
    for route, count in sorted(target_counts.items()):
        print(f"  {route:12s} {count}")

    examples = generate_examples(target_counts, rng)
    if not examples:
        print("No new hard negatives generated (all candidates already exist).")
        return 0

    by_route = Counter(ex["labels"]["route"] for ex in examples)
    print(f"\nGenerated {len(examples)} unique hard negatives:")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count}")

    print("\nSample examples:")
    for ex in examples[:10]:
        print(f"  [{ex['labels']['route']}] {ex['query']}")

    if not args.apply:
        print("\n💡 Use --apply to append and rebuild")
        return 0

    append_to_files(examples)
    return rebuild_embeddings()


if __name__ == "__main__":
    sys.exit(main())
