#!/usr/bin/env python3
"""Create a frozen stratified validation corpus from the labeled examples.

Usage:
    python models/router/create_validation_corpus.py

The script:
  1. Loads models/router/comprehensive_examples.json.
  2. Holds out a deterministic 15% stratified split by route.
  3. Writes data/evaluation/routing_validation_corpus.jsonl.
  4. Overwrites models/router/comprehensive_examples.json with the training split.
  5. Runs scripts/rebuild_embeddings.py to rebuild the embedding index.
  6. Writes a metadata file with seed / split statistics.

The validation split is deterministic because it uses a fixed random seed (42).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

from sklearn.model_selection import train_test_split


ROUTER_DIR = Path(__file__).resolve().parent
ROOT_DIR = ROUTER_DIR.parent.parent
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"
VALIDATION_PATH = ROOT_DIR / "data" / "evaluation" / "routing_validation_corpus.jsonl"
METADATA_PATH = ROOT_DIR / "data" / "evaluation" / "validation_split_metadata.json"
BACKUP_PATH = ROUTER_DIR / "comprehensive_examples.json.phase4.bak"
REBUILD_SCRIPT = ROOT_DIR / "scripts" / "rebuild_embeddings.py"

SEED = 42
VAL_SIZE = 0.15


def normalize_query(q: str) -> str:
    return q.lower().strip()


def build_record(ex: dict) -> dict:
    labels = ex.get("labels", {})
    metadata = ex.get("metadata", {})
    return {
        "query": ex["query"],
        "route": labels.get("route", "UNKNOWN"),
        "intent_family": labels.get("intent_family", "unknown"),
        "source": metadata.get("source", "unknown"),
    }


def main() -> int:
    if not EXAMPLES_PATH.exists():
        print(f"ERROR: examples file not found: {EXAMPLES_PATH}", file=sys.stderr)
        return 1

    with open(EXAMPLES_PATH, "r", encoding="utf-8") as f:
        examples = json.load(f)

    print(f"Loaded {len(examples)} examples from {EXAMPLES_PATH}")

    routes = [ex["labels"]["route"] for ex in examples if ex.get("labels", {}).get("route")]
    if len(routes) != len(examples):
        print("ERROR: some examples are missing route labels", file=sys.stderr)
        return 1

    # Stratified holdout
    indices = list(range(len(examples)))
    train_idx, val_idx = train_test_split(
        indices,
        test_size=VAL_SIZE,
        random_state=SEED,
        stratify=routes,
    )
    train_idx = set(train_idx)

    train_examples = [examples[i] for i in range(len(examples)) if i in train_idx]
    val_records = [build_record(examples[i]) for i in range(len(examples)) if i not in train_idx]

    print(f"Training examples: {len(train_examples)}")
    print(f"Validation examples: {len(val_records)}")

    # Route distribution
    def _dist(items, key):
        return dict(sorted(Counter(key(item) for item in items).items()))

    print("Training route distribution:", _dist(train_examples, lambda e: e["labels"]["route"]))
    print("Validation route distribution:", _dist(val_records, lambda r: r["route"]))

    # Backup original examples
    shutil.copy2(EXAMPLES_PATH, BACKUP_PATH)
    print(f"Backed up original examples to {BACKUP_PATH}")

    # Write training examples back to canonical path
    VALIDATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(train_examples, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote training examples to {EXAMPLES_PATH}")

    # Write validation corpus JSONL
    with open(VALIDATION_PATH, "w", encoding="utf-8") as f:
        for rec in val_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Wrote validation corpus to {VALIDATION_PATH}")

    # Rebuild embeddings from the training split
    print("\nRebuilding embeddings from training split...")
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

    # Save split metadata
    metadata = {
        "seed": SEED,
        "val_size": VAL_SIZE,
        "total_examples": len(examples),
        "train_examples": len(train_examples),
        "validation_examples": len(val_records),
        "train_route_distribution": _dist(train_examples, lambda e: e["labels"]["route"]),
        "validation_route_distribution": _dist(val_records, lambda r: r["route"]),
        "validation_path": str(VALIDATION_PATH.relative_to(ROOT_DIR)),
        "backup_path": str(BACKUP_PATH.relative_to(ROOT_DIR)),
    }
    with open(METADATA_PATH, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"Wrote split metadata to {METADATA_PATH}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
