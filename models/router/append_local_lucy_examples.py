#!/usr/bin/env python3
"""Append Local Lucy-specific training examples to the router dataset.

These examples reflect actual user queries and use cases for Mike's
installation of Local Lucy V10.
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
    # --- Personal / Family (LOCAL) ---
    {"query": "Who are my children", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "How many kids do I have", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "Do I have any grandchildren", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "Tell me about my dog Oscar", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "What is my wife's name", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "Who is Rachel", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "How old is Tom", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},
    {"query": "Tell me about my family", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "personal_family"}},

    # --- Dog / Veterinary (EVIDENCE) ---
    {"query": "My dog is vomiting what should I do", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "What are the symptoms of parvo in dogs", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "Can dogs eat chocolate", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "My dog has diarrhea", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "Dog ear infection treatment", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "How much should I feed my dog", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "Best food for dogs with allergies", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},
    {"query": "Dog vaccination schedule", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "EVIDENCE", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "veterinary_dog"}},

    # --- Electronics / Tube Database (LOCAL) ---
    {"query": "What is a 12AX7 tube", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "electronics"}},
    {"query": "Compare 6L6 and EL34 tubes", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "electronics"}},
    {"query": "What is the pinout of a 5U4G rectifier", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "electronics"}},
    {"query": "How does a capacitor work", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "electronics"}},
    {"query": "Difference between ceramic and electrolytic capacitors", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "electronics"}},

    # --- Coding / Programming (LOCAL) ---
    {"query": "How to write a Python function", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "Python list comprehension tutorial", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "How do I sort a dictionary in Python", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "Explain asyncio in Python", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "What is the difference between a list and a tuple", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "How to use git rebase", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},
    {"query": "Bash script to find large files", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "programming"}},

    # --- Creative Writing (LOCAL) ---
    {"query": "Write a poem about electricity", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "creative_writing"}},
    {"query": "Tell me a story about a resistor", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "creative_writing"}},
    {"query": "Write a short story about a dog who becomes an engineer", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "creative_writing"}},

    # --- General Knowledge (LOCAL) ---
    {"query": "Explain Ohm's law", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "What is the speed of light", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "How does a transistor work", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "What is quantum mechanics", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "History of the transistor", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "What is entropy in physics", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},
    {"query": "How does an LED work", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "general_knowledge"}},

    # --- Translation / Language (LOCAL) ---
    {"query": "Translate hello to Hebrew", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "translation"}},
    {"query": "How do you say good morning in Arabic", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "translation"}},
    {"query": "Translate this sentence to Spanish", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "translation"}},

    # --- Finance (AUGMENTED) ---
    {"query": "What is the current gold price", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},
    {"query": "Bitcoin price today", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},
    {"query": "S&P 500 current value", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},
    {"query": "EUR to USD exchange rate", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},
    {"query": "Tesla stock price now", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},
    {"query": "Current inflation rate in the US", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "finance"}},

    # --- News (NEWS) ---
    {"query": "What is happening in the world today", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Latest news about Israel", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Show me today's headlines", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Any news from Australia", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Breaking news Middle East", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Latest developments in Ukraine", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "What is the current situation in Gaza", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "News about climate change", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},
    {"query": "Technology news today", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "news"}},

    # --- Weather (WEATHER) ---
    {"query": "What is the weather like", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "weather"}},
    {"query": "Is it going to rain today", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "weather"}},
    {"query": "Temperature outside right now", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "weather"}},
    {"query": "Weather forecast for tomorrow", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "WEATHER", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "weather"}},

    # --- Time (TIME) ---
    {"query": "What time is it now", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "time"}},
    {"query": "Current time in Sydney", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "time"}},
    {"query": "What is the time in London", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "time"}},
    {"query": "Time in Tokyo right now", "labels": {"intent_family": "current_evidence", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}, "metadata": {"source": "local_lucy_use_case", "category": "time"}},
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
    print("\nBy category:")
    for cat, count in sorted(by_category.items(), key=lambda x: -x[1]):
        print(f"  {cat:20s} {count:2d}")

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
