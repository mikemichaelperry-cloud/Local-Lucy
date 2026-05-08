#!/usr/bin/env python3
"""Rebuild embedding index from comprehensive_index.jsonl."""
import json
import sys
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parent / "models" / "router"
sys.path.insert(0, str(ROUTER_DIR))

from embedding_router import EmbeddingRouter


def main():
    index_path = ROUTER_DIR / "comprehensive_index.jsonl"
    print(f"Reading index from {index_path}")

    examples = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))

    print(f"Loaded {len(examples)} examples")

    # Show distribution
    from collections import Counter
    intent_counts = Counter(ex["labels"]["intent_family"] for ex in examples)
    route_counts = Counter(ex["labels"]["route"] for ex in examples)

    print("\nIntent distribution:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")

    print("\nRoute distribution:")
    for route, count in sorted(route_counts.items()):
        print(f"  {route:20s}: {count}")

    # Build embeddings
    print("\nBuilding embeddings...")
    router = EmbeddingRouter()
    router.fit(examples)

    # Save
    embeddings_path = ROUTER_DIR / "comprehensive_embeddings.npy"
    examples_path = ROUTER_DIR / "comprehensive_examples.json"

    import numpy as np
    np.save(embeddings_path, router.embeddings)
    with open(examples_path, "w", encoding="utf-8") as f:
        json.dump(router.examples, f, indent=2, ensure_ascii=False)

    print(f"\nSaved:")
    print(f"  Embeddings: {embeddings_path}")
    print(f"  Examples:   {examples_path}")


if __name__ == "__main__":
    main()
