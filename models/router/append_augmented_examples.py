#!/usr/bin/env python3
"""
Append 70 carefully curated examples to the embedding router index.

These examples fill known gaps in the router:
  - DIY / how-to queries misrouting to AUGMENTED
  - Ambiguous boundary queries (weather-like but not weather)
  - Pronoun-heavy follow-ups without memory context
  - Keyword guard bypasses (medical/financial words in creative contexts)
  - Typos and noisy input
  - Compound / mixed intent queries
  - Cultural / regional phrasing variations

Usage:
    python append_augmented_examples.py --dry-run     # Preview only
    python append_augmented_examples.py --apply       # Append + rebuild

Safety:
    - Deduplicates against existing 395 examples
    - Backs up comprehensive_examples.json and comprehensive_embeddings.npy
    - Only appends genuinely new queries
    - Rebuilds embeddings atomically
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROUTER_DIR = Path(__file__).parent.resolve()
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"

BACKUP_DIR = ROUTER_DIR / "checkpoints"


# ---------------------------------------------------------------------------
# The 70 new examples — organized by gap category
# ---------------------------------------------------------------------------

NEW_EXAMPLES: list[dict] = [
    # ================================================================
    # 1. DIY / How-To Gap (AUGMENTED → LOCAL misroutes)
    # ================================================================
    {
        "query": "How do I change a tire?",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How do I change a car tire step by step",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How to jump start a car",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How do I patch a hole in drywall",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How to unclog a sink drain",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How do I tie a tie for a wedding",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How to bake sourdough bread from scratch",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How do I build a bookshelf",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "How to replace a broken phone screen",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },
    {
        "query": "Step by step instructions for CPR",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "diy"},
    },

    # ================================================================
    # 2. Ambiguous Boundary Queries (Route confusion stress tests)
    # ================================================================
    {
        "query": "What is the weather like on Mars?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "What was the weather like during D-Day?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "What time is it in a black hole?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "What's the news from ancient Rome?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "Current price of a gallon of milk",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "Bitcoin price in 2010",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "How much does a Tesla cost?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "Tell me about the news industry",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "What is the forecast for my retirement?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },
    {
        "query": "Latest trends in interior design",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "ambiguous"},
    },

    # ================================================================
    # 3. Pronoun / Context Queries (Without Memory Gate)
    # ================================================================
    {
        "query": "What about it?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "Tell me more",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "Why is that?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "Should I keep it?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "How does it work?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "What do you think about them?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "Is that true?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "Can you explain it better?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "What happened next?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },
    {
        "query": "And then?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "pronoun"},
    },

    # ================================================================
    # 4. Keyword Guard Bypasses (guard words in non-triggering contexts)
    # ================================================================
    {
        "query": "Write a story about a doctor",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Write a poem about financial ruin",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Tell me a joke about lawyers",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "How to draw a heart",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "The economy of Middle Earth",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Stock characters in Shakespeare",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Weather the storm in business",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Time travel stories for kids",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Current events in the Marvel Universe",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },
    {
        "query": "Breaking news about my lunch",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "guard_bypass"},
    },

    # ================================================================
    # 5. Typos / Noisy Input Stress Tests
    # ================================================================
    {
        "query": "wats teh wether in tokio",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "wats teh l8est newz",
        "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "whut tiem iz it nao",
        "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "how 2 chnge a tirr",
        "labels": {"intent_family": "how_to", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "wat abot that",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "tell me mor",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "wht did i say",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "rmd me wat mi nme is",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "whats teh wether 4cast",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },
    {
        "query": "stok prise of appl",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "typos"},
    },

    # ================================================================
    # 6. Mixed / Compound Intent Queries
    # ================================================================
    {
        "query": "Weather forecast and news headlines",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "What time is it and what's the weather?",
        "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "How do I cook pasta and what's the news?",
        "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "Tell me a story about the stock market crash of 1929",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "Current trends in AI and machine learning",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "What is the best time to plant tomatoes?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "Price comparison of electric cars",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "How to invest in renewable energy",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "Latest research on climate change",
        "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },
    {
        "query": "What is the current status of my application?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "compound"},
    },

    # ================================================================
    # 7. Cultural / Regional Variations
    # ================================================================
    {
        "query": "What's the weather like today, mate?",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "How's the weather looking, yeah?",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Cheers, what's the time?",
        "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Give us the news, will ya?",
        "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "What's the craic?",
        "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Wie spät ist es?",
        "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Quel temps fait-il?",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Wie ist das Wetter?",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "Dame el pronóstico",
        "labels": {"intent_family": "ephemeral_query", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
    {
        "query": "מה השעה?",
        "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
        "metadata": {"source": "manual_augment_2026_05_10", "category": "cultural"},
    },
]


def load_existing_queries() -> set[str]:
    """Load existing queries for deduplication from canonical JSON."""
    existing: set[str] = set()

    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            try:
                examples = json.load(f)
                for ex in examples:
                    existing.add(ex.get("query", "").lower().strip())
            except (json.JSONDecodeError, TypeError):
                pass

    return existing


def backup_files():
    """Create timestamped backups of canonical examples and embeddings."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    if EXAMPLES_PATH.exists():
        shutil.copy2(EXAMPLES_PATH, BACKUP_DIR / f"comprehensive_examples_{ts}.json")
    if EMBEDDINGS_PATH.exists():
        shutil.copy2(EMBEDDINGS_PATH, BACKUP_DIR / f"comprehensive_embeddings_{ts}.npy")

    print(f"Backups created in {BACKUP_DIR}/")
    return ts


def append_to_examples(new_examples: list[dict]):
    """Append new examples to the canonical JSON file."""
    examples = []
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, encoding="utf-8") as f:
            examples = json.load(f)
    examples.extend(new_examples)
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"Appended {len(new_examples)} examples to {EXAMPLES_PATH} (total {len(examples)})")


def rebuild_embeddings():
    """Trigger embedding rebuild."""
    rebuild_script = Path(__file__).parent.parent.parent / "scripts" / "rebuild_embeddings.py"
    if rebuild_script.exists():
        import subprocess
        result = subprocess.run(
            [sys.executable, str(rebuild_script)],
            capture_output=True,
            text=True,
        )
        print(result.stdout)
        if result.returncode != 0:
            print(f"WARNING: rebuild failed:\n{result.stderr}")
            return False
        return True
    else:
        print(f"WARNING: rebuild_embeddings.py not found at {rebuild_script}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Append 70 curated examples to embedding index")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not modify files")
    parser.add_argument("--apply", action="store_true", help="Append examples and rebuild embeddings")
    args = parser.parse_args()

    existing = load_existing_queries()
    print(f"Existing examples: {len(existing)}")

    # Filter out duplicates
    new_examples = []
    for ex in NEW_EXAMPLES:
        norm = ex["query"].lower().strip()
        if norm not in existing:
            new_examples.append(ex)
        else:
            print(f"  SKIP (duplicate): {ex['query'][:60]}")

    if not new_examples:
        print("\n✅ All 70 examples already exist in the index. Nothing to add.")
        return

    # Stats
    by_route = Counter(ex["labels"]["route"] for ex in new_examples)
    by_category = Counter(ex["metadata"]["category"] for ex in new_examples)

    print(f"\nNew examples to add: {len(new_examples)}")
    print(f"By route:")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count:2d}")
    print(f"By category:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:15s} {count:2d}")

    if args.dry_run or not args.apply:
        print(f"\n💡 Use --apply to append and rebuild")
        return

    # Apply
    print(f"\n⚠️  Applying changes in 3 seconds... (Ctrl+C to cancel)")
    import time
    try:
        time.sleep(3)
    except KeyboardInterrupt:
        print("\nCancelled.")
        return

    backup_files()
    append_to_examples(new_examples)
    rebuild_embeddings()

    print(f"\n✅ Done! Index now has {len(existing) + len(new_examples)} examples")


if __name__ == "__main__":
    main()
