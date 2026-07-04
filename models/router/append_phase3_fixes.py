#!/usr/bin/env python3
"""
Append targeted hard-negative training examples for Phase 3.

Goals:
  - Keep finance advice, opinion/critique/speculation, conspiracy, history, and
    math questions LOCAL instead of letting them leak to AUGMENTED/WEATHER.
  - Give the classifier more clear NEWS examples for strategic analysis,
    recent developments, and casualty updates.
  - Give the classifier more clear WEATHER examples using "conditions" phrasing.

Usage:
    python append_phase3_fixes.py --apply
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
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
EMBEDDINGS_PATH = ROUTER_DIR / "comprehensive_embeddings.npy"
INDEX_PATH = ROUTER_DIR / "comprehensive_index.jsonl"
BACKUP_DIR = ROUTER_DIR / "checkpoints"

NEW_EXAMPLES: list[dict] = [
    # ================================================================
    # Finance advice -> LOCAL
    # ================================================================
    {
        "query": "How do taxes on capital gains work?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "Should I buy life insurance?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "What is the best way to save for retirement?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "How much emergency cash should I keep?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "Should I rent or buy a house?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "How do I create a monthly budget?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "What is dollar-cost averaging?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "Is it better to pay off debt or invest?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "How do I diversify my investment portfolio?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    {
        "query": "What is a reasonable debt-to-income ratio?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "finance_advice_local"},
    },
    # ================================================================
    # Opinion / critique / speculation -> LOCAL
    # ================================================================
    {
        "query": "What is your opinion on the Israel-Gaza conflict?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "What is your opinion on the government's tax policy?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "Critique the media coverage of the war",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "Evaluate the diplomatic situation between China and Taiwan",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "Speculate on the outcome of the peace negotiations",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "What is your take on the latest election?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "In your opinion, who is the greatest philosopher?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    {
        "query": "Critique this argument about free will",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "opinion_local"},
    },
    # ================================================================
    # Conspiracy / pseudohistory -> LOCAL
    # ================================================================
    {
        "query": "Is the Earth flat?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    {
        "query": "Is the moon landing a hoax?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    {
        "query": "Are lizard people controlling the government?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    {
        "query": "What happened at Area 51?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    {
        "query": "Is the Federal Reserve controlled by aliens?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    {
        "query": "Do vaccines contain microchips?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "conspiracy_local"},
    },
    # ================================================================
    # Historical conflict outcomes -> LOCAL
    # ================================================================
    {
        "query": "What was the outcome of the Yom Kippur War?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    {
        "query": "Who won the Six-Day War?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    {
        "query": "What happened in the 1973 Arab-Israeli war?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    {
        "query": "What was the result of the Vietnam War?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    {
        "query": "How did World War II end?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    {
        "query": "What was the outcome of the Gulf War?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "history_local"},
    },
    # ================================================================
    # Math / arithmetic -> LOCAL
    # ================================================================
    {
        "query": "What is two plus two?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    {
        "query": "What does 2 plus 2 equal?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    {
        "query": "Calculate 15 times 7",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    {
        "query": "Solve 100 divided by 4",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    {
        "query": "What is the square root of 64?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    {
        "query": "What is 8 multiplied by 9?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "math_local"},
    },
    # ================================================================
    # News analysis / recent developments -> NEWS
    # ================================================================
    {
        "query": "What is the strategic significance of the recent military moves?",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "Strategic implications of the latest military operations",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "What do the recent troop movements mean?",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "Recent AI developments",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "Latest breakthroughs in artificial intelligence",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "Recent advances in renewable energy",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "What are the latest developments in the conflict?",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    {
        "query": "Recent news about climate change",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_analysis"},
    },
    # ================================================================
    # Current casualty / death toll -> NEWS
    # ================================================================
    {
        "query": "What is the current death toll in the war?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_casualties"},
    },
    {
        "query": "How many casualties in the conflict so far?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_casualties"},
    },
    {
        "query": "Latest death toll in Gaza",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_casualties"},
    },
    {
        "query": "Current number of casualties in Ukraine",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_casualties"},
    },
    {
        "query": "What is the latest casualty count?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "news_casualties"},
    },
    # ================================================================
    # Weather "conditions" phrasing -> WEATHER
    # ================================================================
    {
        "query": "Current weather conditions in Tel Aviv",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "WEATHER",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "weather_conditions"},
    },
    {
        "query": "What are the current conditions in London?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "WEATHER",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "weather_conditions"},
    },
    {
        "query": "Current conditions in New York",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "WEATHER",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "weather_conditions"},
    },
    {
        "query": "Weather conditions right now in Paris",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "WEATHER",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "weather_conditions"},
    },
    {
        "query": "Current conditions and forecast for Tokyo",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "WEATHER",
            "policy_override": "none",
        },
        "metadata": {"source": "phase3_fix", "category": "weather_conditions"},
    },
]


def load_existing_queries() -> set[str]:
    existing: set[str] = set()
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
    for src in (EXAMPLES_PATH, EMBEDDINGS_PATH, INDEX_PATH):
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
        print(f"  {cat:22s} {count:2d}")

    if args.dry_run or not args.apply:
        print("\n💡 Use --apply to append and rebuild")
        return

    print("\n⚠️  Applying changes in 3 seconds...")
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
