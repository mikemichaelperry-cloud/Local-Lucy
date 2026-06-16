#!/usr/bin/env python3
"""Append NEWS training examples to fix misrouted news queries."""

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
    {
        "query": "Show me today's top stories",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Show me news about climate change",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Latest world news",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "What is the current status of the Israel-Gaza conflict?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Top headlines today",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "News about the Middle East",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "What are the headlines from Europe?",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Show me breaking news",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Latest updates on the war",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "News from Asia today",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "What is happening in Ukraine?",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Current events in the Middle East",
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Latest political news",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Show me sports headlines",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
    {
        "query": "Technology news today",
        "labels": {
            "intent_family": "news_request",
            "evidence_mode": "not_required",
            "route": "NEWS",
            "policy_override": "none",
        },
        "metadata": {"source": "synthetic_fix", "category": "news"},
    },
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
    print(f"\nNew examples to add: {len(new_examples)}")
    for route, count in sorted(by_route.items()):
        print(f"  {route:12s} {count:2d}")

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
