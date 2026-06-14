#!/usr/bin/env python3
"""Rebuild embedding index from comprehensive_examples.json.

This script reads the canonical comprehensive_examples.json (git-tracked),
rebuilds the embedding matrix, and writes:
  - comprehensive_embeddings.npy
  - comprehensive_examples.json (re-validated)
  - comprehensive_index.jsonl (derived, for backward compatibility)
"""
import json
import sys
from pathlib import Path

ROUTER_DIR = Path(__file__).resolve().parent.parent / "models" / "router"
sys.path.insert(0, str(ROUTER_DIR))

from hybrid_router_v2 import HybridRouterV2


def main():
    examples_path = ROUTER_DIR / "comprehensive_examples.json"
    print(f"Reading examples from {examples_path}")

    with open(examples_path, "r", encoding="utf-8") as f:
        examples = json.load(f)

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
    router = HybridRouterV2()
    router.fit(examples)

    # Save
    embeddings_path = ROUTER_DIR / "comprehensive_embeddings.npy"
    examples_path_out = ROUTER_DIR / "comprehensive_examples.json"
    index_path = ROUTER_DIR / "comprehensive_index.jsonl"

    import numpy as np
    np.save(embeddings_path, router.embeddings)
    with open(examples_path_out, "w", encoding="utf-8") as f:
        json.dump(router.examples, f, indent=2, ensure_ascii=False)

    # Derive JSONL for backward compatibility
    with open(index_path, "w", encoding="utf-8") as f:
        for ex in router.examples:
            f.write(json.dumps(ex, ensure_ascii=False) + "\n")

    print(f"\nSaved:")
    print(f"  Embeddings: {embeddings_path} ({router.embeddings.shape})")
    print(f"  Examples:   {examples_path_out} ({len(router.examples)} entries)")
    print(f"  Index:      {index_path} (derived)")


if __name__ == "__main__":
    main()
