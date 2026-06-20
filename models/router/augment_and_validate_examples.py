#!/usr/bin/env python3
"""Safely augment comprehensive_examples.json with validated synthetic examples.

1. Loads the current production examples.
2. Generates deterministic synthetic candidates for under-represented routes
   and edge cases (short queries, multilingual, medical/vet evidence, etc.).
3. Validates every candidate against the current HybridRouterV2 prediction.
4. Keeps only candidates where the router's predicted route matches the
   intended label (guarding against accidentally adding mislabeled examples).
5. Backs up the original file and writes the merged, deduplicated dataset.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

# Import the synthetic generators from the existing script.  It is safe to
# import because generate_synthetic_examples.py only runs its main() under
# __name__ == "__main__".
sys.path.insert(0, str(Path(__file__).parent))
from generate_synthetic_examples import (
    _generate_evidence_examples,
    _generate_news_examples,
    _generate_time_examples,
    _generate_weather_examples,
)

from hybrid_router_v2 import HybridRouterV2


ROOT = Path(__file__).parent.resolve()
EXAMPLES_PATH = ROOT / "comprehensive_examples.json"
BACKUP_PATH = ROOT / "comprehensive_examples.json.bak"


def _make_example(query: str, route: str, intent_family: str = "", evidence_mode: str = "") -> dict:
    if not intent_family:
        intent_family = {
            "LOCAL": "local_answer",
            "AUGMENTED": "synthesis_explanation",
            "EVIDENCE": "evidence_request",
            "NEWS": "current_evidence",
            "TIME": "time_query",
            "WEATHER": "ephemeral_query",
            "EPHEMERAL": "ephemeral_query",
        }.get(route, "local_answer")

    if not evidence_mode:
        evidence_mode = "required" if route == "EVIDENCE" else "not_required"

    return {
        "query": query,
        "labels": {
            "intent_family": intent_family,
            "evidence_mode": evidence_mode,
            "route": route,
            "policy_override": "none",
        },
        "metadata": {
            "source": "synthetic_augmentation_v2",
            "feedback_type": "router_validated",
        },
    }


def _generate_short_query_variants(examples: list[dict], target: int = 80) -> list[dict]:
    """Create very short, stripped-down versions of existing examples."""
    short_variants = []
    for ex in examples:
        q = ex["query"]
        route = ex["labels"]["route"]
        if len(q.split()) <= 3:
            continue
        words = q.split()
        # Drop stop-word fluff to create terse variants.
        for start in ("What is ", "What are ", "How is ", "How are ", "Tell me about ", "Explain "):
            if q.startswith(start):
                short = q[len(start) :].rstrip("?")
                short_variants.append(_make_example(short + "?", route))
                break
        # First few words variant.
        if len(words) >= 4:
            short_variants.append(_make_example(" ".join(words[:4]).rstrip("?") + "?", route))
        if len(short_variants) >= target:
            break
    return short_variants[:target]


def _generate_local_augmented_boundary(target: int = 60) -> list[dict]:
    """Examples that sit on the LOCAL / AUGMENTED boundary."""
    local_templates = [
        "Explain how photosynthesis works",
        "What is the theory of relativity",
        "How does a combustion engine work",
        "Describe the water cycle",
        "What causes earthquakes",
        "How do vaccines work",
        "Explain the difference between DNA and RNA",
        "What is machine learning",
        "How does encryption work",
        "What is blockchain",
    ]
    augmented_templates = [
        "What is the latest research on photosynthesis",
        "Recent discoveries about black holes",
        "Current understanding of quantum computing",
        "Latest findings on climate change",
        "What do recent studies say about sleep",
        "New developments in fusion energy",
        "Latest trends in artificial intelligence",
        "Recent advances in battery technology",
        "What did the latest Mars rover discover",
        "Current state of the James Webb Space Telescope",
    ]
    examples = []
    for q in local_templates:
        examples.append(_make_example(q + "?", "LOCAL"))
    for q in augmented_templates:
        examples.append(_make_example(q + "?", "AUGMENTED"))
    return examples[:target]


def _generate_multilingual_edge(target: int = 40) -> list[dict]:
    """Non-English examples for routes with clear keywords."""
    examples = [
        # Weather
        _make_example("Wie ist das Wetter heute?", "WEATHER"),
        _make_example("Quel temps fait-il aujourd'hui?", "WEATHER"),
        _make_example("¿Cómo está el clima hoy?", "WEATHER"),
        _make_example("Che tempo fa oggi?", "WEATHER"),
        _make_example("今日の天気はどうですか", "WEATHER"),
        # Time
        _make_example("Wie spät ist es?", "TIME"),
        _make_example("Quelle heure est-il?", "TIME"),
        _make_example("¿Qué hora es?", "TIME"),
        _make_example("Che ore sono?", "TIME"),
        _make_example("今何時ですか", "TIME"),
        # News
        _make_example("Quelles sont les dernières nouvelles?", "NEWS"),
        _make_example("¿Cuáles son las últimas noticias?", "NEWS"),
        _make_example("Was gibt es Neues?", "NEWS"),
        # Local simple
        _make_example("Wie alt ist die Erde?", "LOCAL"),
        _make_example("Qu'est-ce que la photosynthèse?", "LOCAL"),
        _make_example("¿Qué es la gravedad?", "LOCAL"),
    ]
    return examples[:target]


def _generate_veterinary_evidence(target: int = 30) -> list[dict]:
    """Vet-specific EVIDENCE examples (often under-represented)."""
    templates = [
        "My dog is limping, what could be wrong",
        "Cat vomiting after eating, possible causes",
        "What are the symptoms of parvovirus in puppies",
        "How is feline leukemia diagnosed",
        "What vaccinations does my puppy need",
        "My rabbit stopped eating, what should I do",
        "Signs of bloat in dogs",
        "What is the treatment for kennel cough",
        "How do I know if my cat has a urinary blockage",
        "My horse has a cough, possible diagnoses",
        "What are common toxins for dogs",
        "How is heartworm prevented in dogs",
    ]
    return [_make_example(q + "?", "EVIDENCE") for q in templates[:target]]


def _generate_finance_evidence(target: int = 30) -> list[dict]:
    """Finance-specific EVIDENCE examples."""
    templates = [
        "What is the current Federal Reserve interest rate",
        "What are the SEC reporting requirements for public companies",
        "What is the difference between a Roth IRA and a traditional IRA",
        "What are the tax implications of capital gains",
        "What is the current inflation rate",
        "What are the reserve requirements for banks",
        "What is the legal retirement age for full Social Security benefits",
        "What are the Basel III capital requirements",
        "What is the current unemployment rate",
        "How is GDP calculated",
    ]
    return [_make_example(q + "?", "EVIDENCE") for q in templates[:target]]


def _validate_candidates(
    router: HybridRouterV2,
    candidates: list[dict],
    existing_queries: set[str],
) -> tuple[list[dict], dict[str, int]]:
    """Return only candidates whose predicted route matches the intended route."""
    accepted: list[dict] = []
    stats: dict[str, int] = {"accepted": 0, "rejected": 0, "duplicate": 0}

    for ex in candidates:
        q = ex["query"].strip()
        q_lower = q.lower()
        if q_lower in existing_queries:
            stats["duplicate"] += 1
            continue

        try:
            pred = router.predict(q)
        except Exception:
            stats["rejected"] += 1
            continue

        if pred.get("route") == ex["labels"]["route"]:
            accepted.append(ex)
            existing_queries.add(q_lower)
            stats["accepted"] += 1
        else:
            stats["rejected"] += 1

    return accepted, stats


def main() -> int:
    random.seed(42)

    print(f"Loading {EXAMPLES_PATH}...")
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        existing = json.load(f)
    print(f"  Existing examples: {len(existing)}")

    existing_queries = {ex["query"].strip().lower() for ex in existing}
    before = Counter(ex["labels"]["route"] for ex in existing)

    print("\nGenerating synthetic candidates...")
    candidates: list[dict] = []
    # Use the existing template generators with slightly higher targets.
    candidates.extend(_generate_evidence_examples(80))
    candidates.extend(_generate_weather_examples(60))
    candidates.extend(_generate_time_examples(80))
    candidates.extend(_generate_news_examples(80))
    # Add our focused augmentations.
    candidates.extend(_generate_veterinary_evidence(30))
    candidates.extend(_generate_finance_evidence(30))
    candidates.extend(_generate_local_augmented_boundary(60))
    candidates.extend(_generate_multilingual_edge(40))
    candidates.extend(_generate_short_query_variants(existing, 80))
    print(f"  Candidates generated: {len(candidates)}")

    print("\nLoading router for validation...")
    router = HybridRouterV2()

    print("Validating candidates...")
    accepted, stats = _validate_candidates(router, candidates, existing_queries)
    print(f"  Accepted: {stats['accepted']}")
    print(f"  Rejected (router mismatch): {stats['rejected']}")
    print(f"  Duplicates skipped: {stats['duplicate']}")

    merged = existing + accepted
    after = Counter(ex["labels"]["route"] for ex in merged)

    print("\n--- BEFORE vs AFTER ---")
    print(f"{'Route':<15} {'Before':>8} {'After':>8} {'+/-':>8}")
    print("-" * 42)
    for route in sorted(set(before) | set(after)):
        b = before.get(route, 0)
        a = after.get(route, 0)
        print(f"{route:<15} {b:>8} {a:>8} {a-b:>+8}")
    print(f"\nTotal: {len(existing)} -> {len(merged)} (+{len(accepted)})")

    # Backup and write.
    print(f"\nBacking up original to {BACKUP_PATH}...")
    shutil.copy2(EXAMPLES_PATH, BACKUP_PATH)

    print(f"Writing merged dataset to {EXAMPLES_PATH}...")
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("\nDone. Rebuild embeddings next:")
    print("  python models/router/rebuild_embeddings.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
