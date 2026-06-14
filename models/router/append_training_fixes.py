#!/usr/bin/env python3
"""
Append targeted training examples to fix remaining synthetic test failures.

Categories:
  - Finance live data -> AUGMENTED
  - Historical queries -> LOCAL
  - News synthesis -> AUGMENTED

Usage:
    python append_training_fixes.py --apply
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROUTER_DIR = Path(__file__).parent.resolve()
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
BACKUP_DIR = ROUTER_DIR / "checkpoints"

NEW_EXAMPLES: list[dict] = [
    # ================================================================
    # Finance live data -> AUGMENTED
    # ================================================================
    {"query": "Current oil price per barrel", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Nikkei index current value", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Tesla shares now", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Tesla market value", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Apple stock price today", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Bitcoin price right now", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Gold price per ounce today", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "EUR to USD exchange rate", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "S&P 500 current value", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},
    {"query": "Dow Jones today", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "finance"}},

    # ================================================================
    # Historical queries -> LOCAL
    # ================================================================
    {"query": "What was the impact of the 1918 flu pandemic?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "How did the Black Death change Europe?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "What caused the fall of the Roman Empire?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "Effects of the Great Depression", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "How did World War 2 end?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "What was the Treaty of Versailles?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "Causes of the American Civil War", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "What happened during the Renaissance?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "History of the Ottoman Empire", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},
    {"query": "The rise and fall of the Mongol Empire", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "history"}},

    # ================================================================
    # News synthesis -> AUGMENTED
    # ================================================================
    {"query": "Interpret the recent political developments in Turkey", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What is your take on the US-China trade war?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Probability of Israel-Iran war", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Assess the economic impact of Brexit", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What are the implications of the new EU regulations?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Analyze the consequences of the latest Fed rate hike", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "How will the election results affect foreign policy?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Evaluate the effectiveness of recent sanctions", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What does the latest trade agreement mean for consumers?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Interpret the significance of the peace talks", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What is the outlook for the global economy?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "How likely is a recession next year?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What are the risks of escalating tensions in the region?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Summarize the debate around climate policy", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What is the consensus on vaccine efficacy?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Compare the candidates' foreign policy positions", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What are the geopolitical stakes in the South China Sea?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "How should we understand the latest intelligence reports?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "What do the polling numbers really tell us?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
    {"query": "Evaluate the claims made in the State of the Union address", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "synthetic_fix", "category": "synthesis"}},
]


def load_existing_queries() -> set[str]:
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
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    BACKUP_DIR.mkdir(exist_ok=True)
    for src in (EXAMPLES_PATH, EMBEDDINGS_PATH):
        if src.exists():
            dst = BACKUP_DIR / f"{src.stem}_{timestamp}{src.suffix}"
            shutil.copy2(src, dst)
            print(f"  Backup: {dst.name}")


def append_to_examples(new_examples: list[dict]):
    examples = []
    if EXAMPLES_PATH.exists():
        with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
            examples = json.load(f)
    examples.extend(new_examples)
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(examples, f, indent=2, ensure_ascii=False)
    print(f"Appended {len(new_examples)} examples to {EXAMPLES_PATH} (total {len(examples)})")


def rebuild_embeddings():
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    existing = load_existing_queries()
    print(f"Existing examples: {len(existing)}")

    new_examples = []
    for ex in NEW_EXAMPLES:
        norm = ex["query"].lower().strip()
        if norm not in existing:
            new_examples.append(ex)
        else:
            print(f"  SKIP (duplicate): {ex['query'][:60]}")

    if not new_examples:
        print("\n✅ All examples already exist. Nothing to add.")
        return

    by_route = Counter(ex["labels"]["route"] for ex in new_examples)
    by_category = Counter(ex["metadata"]["category"] for ex in new_examples)
    print(f"\nNew examples to add: {len(new_examples)}")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count:2d}")
    for cat, count in sorted(by_category.items()):
        print(f"  {cat:15s} {count:2d}")

    if args.dry_run or not args.apply:
        print(f"\n💡 Use --apply to append and rebuild")
        return

    print(f"\n⚠️  Applying changes in 3 seconds...")
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
