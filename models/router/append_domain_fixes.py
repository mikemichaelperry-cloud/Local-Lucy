#!/usr/bin/env python3
"""
Append training examples to fix domain-specific misclassifications.

Fixes:
  - Astronomy queries with temperature words → LOCAL (not WEATHER)
  - Geography / capital city queries → LOCAL (not TIME)

Usage:
    python append_domain_fixes.py --dry-run     # Preview only
    python append_domain_fixes.py --apply       # Append + rebuild
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
# New examples — domain correction batch
# ---------------------------------------------------------------------------

NEW_EXAMPLES: list[dict] = [
    # ================================================================
    # 1. Astronomy / Space Science (LOCAL)
    # Temperature words + celestial bodies must not route to WEATHER
    # ================================================================
    {
        "query": "How hot is the sun?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the temperature of the sun?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How cold is space?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the surface temperature of Venus?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How hot is a supernova?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the hottest planet in our solar system?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How cold is the dark side of the moon?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the core temperature of the Earth?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How hot are stars?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the boiling point on Mars?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "Why is the sun so hot?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How cold is Pluto?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the temperature of Jupiter's atmosphere?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How hot is Mercury?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the temperature in the center of the Earth?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How far away is Mars?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What are stars made of?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "Tell me about black holes",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the largest planet in our solar system?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How many moons does Jupiter have?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is a nebula?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "Explain the life cycle of a star",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What is the Milky Way?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "How old is the universe?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    {
        "query": "What causes a solar eclipse?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "astronomy"},
    },
    # ================================================================
    # 2. Geography / Capital Cities (LOCAL)
    # City/country names must not route to TIME
    # ================================================================
    {
        "query": "Capital of Japan",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of France?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital city of Germany",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Italy?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Tell me the capital of Spain",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital of Brazil",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of India?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital city of Australia",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Canada?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital of the United Kingdom",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of China?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital of Russia",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Mexico?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital city of South Africa",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Egypt?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Argentina?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital of Turkey",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Sweden?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital city of Norway",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Greece?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Portugal?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital of Thailand",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of South Korea?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "Capital city of the Netherlands",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
    {
        "query": "What is the capital of Poland?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "domain_correction", "category": "geography"},
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_existing_queries() -> set[str]:
    """Load existing queries from the canonical JSON (case-insensitive)."""
    existing = set()
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
            examples = json.load(f)
        for ex in examples:
            try:
                existing.add(ex["query"].lower().strip())
            except (KeyError, AttributeError):
                continue
    return existing


def backup_files():
    """Create timestamped backups."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(exist_ok=True)
    for src in (EXAMPLES_PATH, EMBEDDINGS_PATH):
        if src.exists():
            dst = BACKUP_DIR / f"{src.stem}_{timestamp}{src.suffix}"
            shutil.copy2(src, dst)
            print(f"  Backup: {dst.name}")


def append_to_examples(new_examples: list[dict]):
    """Append new examples to the canonical JSON file."""
    examples = []
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Append domain correction examples to embedding index"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not modify files")
    parser.add_argument(
        "--apply", action="store_true", help="Append examples and rebuild embeddings"
    )
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
        print("\n✅ All examples already exist in the index. Nothing to add.")
        return

    # Stats
    by_route = Counter(ex["labels"]["route"] for ex in new_examples)
    by_category = Counter(ex["metadata"]["category"] for ex in new_examples)

    print(f"\nNew examples to add: {len(new_examples)}")
    print("By route:")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count:2d}")
    print("By category:")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:15s} {count:2d}")

    if args.dry_run or not args.apply:
        print("\n💡 Use --apply to append and rebuild")
        return

    # Apply
    print("\n⚠️  Applying changes in 3 seconds... (Ctrl+C to cancel)")
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
