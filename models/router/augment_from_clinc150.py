#!/usr/bin/env python3
"""
Extract useful, high-quality examples from CLINC150 and merge into training data.

Only extracts:
- weather (intent 5) → WEATHER
- time (intent 4) → TIME
- timezone (intent 66) → TIME
- date (intent 95) → TIME
- oos (intent 42) → LOCAL (out-of-scope / fringe rejection)

Filters for quality: no injection patterns, reasonable length, no duplicates.
"""

import json
import re
from collections import Counter
from pathlib import Path
from datasets import load_dataset

ROOT = Path(__file__).parent.resolve()
INPUT_PATH = ROOT / "comprehensive_examples_augmented.json"
OUTPUT_PATH = ROOT / "comprehensive_examples_merged.json"

# Intent IDs from CLINC150 that map to our routes
CLINC_INTENT_MAP = {
    4: ("time", "TIME"),
    5: ("weather", "WEATHER"),
    66: ("timezone", "TIME"),
    95: ("date", "TIME"),
    42: ("oos", "LOCAL"),  # out-of-scope → fringe/conspiracy rejection
}

# Routes we want to boost specifically
TARGET_ROUTES = {"TIME", "WEATHER", "LOCAL"}

_INJECTION_PATTERNS = [
    re.compile(r"<script", re.IGNORECASE),
    re.compile(r"javascript:", re.IGNORECASE),
    re.compile(r"on\w+\s*=", re.IGNORECASE),
    re.compile(r"[<>{}]\s*\w+\s*[=;]"),
]


def _is_clean(query: str) -> bool:
    """Basic quality filter for CLINC examples."""
    q = query.strip()
    if len(q) < 10 or len(q) > 200:
        return False
    for pat in _INJECTION_PATTERNS:
        if pat.search(q):
            return False
    # Skip very repetitive
    words = q.lower().split()
    if len(words) > 5 and len(set(words)) == 1:
        return False
    return True


def _load_clinc_examples() -> list[dict]:
    """Load and filter CLINC150 examples."""
    print("Loading CLINC150...")
    clinc = load_dataset("clinc/clinc_oos", "plus")
    intent_names = clinc["train"].features["intent"].names

    extracted = []
    for split in ["train", "validation", "test"]:
        data = clinc[split]
        for i in range(len(data)):
            intent_id = data[i]["intent"]
            if intent_id not in CLINC_INTENT_MAP:
                continue
            text = data[i]["text"].strip()
            if not _is_clean(text):
                continue

            clinc_name, our_route = CLINC_INTENT_MAP[intent_id]
            extracted.append(
                {
                    "query": text,
                    "labels": {
                        "intent_family": "local_answer" if our_route == "LOCAL" else "local_answer",
                        "evidence_mode": "not_required",
                        "route": our_route,
                        "policy_override": "none",
                    },
                    "metadata": {
                        "source": "clinc150",
                        "clinc_intent": clinc_name,
                        "clinc_intent_id": intent_id,
                    },
                }
            )

    print(f"  Extracted {len(extracted)} raw examples from CLINC150")

    # Deduplicate
    seen = set()
    deduped = []
    for ex in extracted:
        q = ex["query"].lower()
        if q not in seen:
            seen.add(q)
            deduped.append(ex)

    print(f"  After dedup: {len(deduped)}")
    return deduped


def _filter_existing(examples: list[dict], existing_queries: set[str]) -> list[dict]:
    """Remove examples that duplicate our existing data."""
    filtered = []
    for ex in examples:
        q = ex["query"].strip().lower()
        if q not in existing_queries:
            filtered.append(ex)
    return filtered


def main() -> None:
    # Load our augmented data
    print(f"Loading {INPUT_PATH}...")
    with open(INPUT_PATH) as f:
        existing = json.load(f)
    print(f"  Existing examples: {len(existing)}")

    existing_queries = {ex["query"].strip().lower() for ex in existing}
    old_routes = Counter(ex["labels"]["route"] for ex in existing)

    # Load CLINC
    clinc_examples = _load_clinc_examples()
    clinc_examples = _filter_existing(clinc_examples, existing_queries)

    # We only want to add up to certain limits per route
    route_limits = {
        "TIME": 300,  # generous — time zones are important
        "WEATHER": 100,  # CLINC has good weather variety
        "LOCAL": 100,  # OOS examples for fringe rejection
    }

    # Sort by quality heuristic (prefer longer, more diverse)
    clinc_examples.sort(key=lambda ex: len(ex["query"]), reverse=True)

    selected = []
    route_counts = Counter()
    for ex in clinc_examples:
        route = ex["labels"]["route"]
        limit = route_limits.get(route, 0)
        current = old_routes.get(route, 0) + route_counts[route]
        if current < limit:
            selected.append(ex)
            route_counts[route] += 1

    print(f"\nSelected {len(selected)} CLINC examples:")
    for route, count in sorted(route_counts.items()):
        print(f"  {route}: {count}")

    # Merge
    merged = existing + selected
    new_routes = Counter(ex["labels"]["route"] for ex in merged)

    print("\n--- BEFORE vs AFTER ---")
    print(f"{'Route':<15} {'Before':>8} {'After':>8} {'Change':>8}")
    print("-" * 45)
    for route in ["LOCAL", "AUGMENTED", "EVIDENCE", "NEWS", "TIME", "WEATHER", "EPHEMERAL"]:
        before = old_routes.get(route, 0)
        after = new_routes.get(route, 0)
        change = after - before
        print(f"{route:<15} {before:>8} {after:>8} {change:>+8}")

    print(f"\nTotal: {len(existing)} → {len(merged)} (+{len(merged) - len(existing)})")

    # Write
    with open(OUTPUT_PATH, "w") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    print(f"\nWrote: {OUTPUT_PATH}")

    # Save a sample for review
    sample_path = ROOT / "clinc150_samples_for_review.json"
    with open(sample_path, "w") as f:
        json.dump(selected[:30], f, indent=2, ensure_ascii=False)
    print(f"Review sample: {sample_path}")


if __name__ == "__main__":
    main()
