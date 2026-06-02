#!/usr/bin/env python3
"""
Audit script for router training data quality.

Detects exact duplicates, near-duplicates, class imbalance, and anomalies
in the comprehensive training dataset.

Run: python tools/audit_router_training_data.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DATA_PATH = Path("models/router/comprehensive_examples.json")
EMBEDDINGS_PATH = Path("models/router/comprehensive_embeddings.npy")
NEAR_DUPLICATE_THRESHOLD = 0.97  # cosine similarity
CLASS_BALANCE_RATIO_WARN = 3.0  # max/min ratio before warning
CLASS_BALANCE_RATIO_CRITICAL = 6.0


def load_data() -> tuple[list[dict], np.ndarray]:
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        examples = json.load(f)
    embeddings = np.load(EMBEDDINGS_PATH)
    return examples, embeddings


def exact_duplicate_audit(examples: list[dict]) -> dict:
    """Find exact duplicate queries."""
    seen: dict[str, list[int]] = {}
    for i, ex in enumerate(examples):
        q = ex["query"].strip().lower()
        seen.setdefault(q, []).append(i)

    duplicates = {q: idxs for q, idxs in seen.items() if len(idxs) > 1}
    return {
        "duplicate_groups": len(duplicates),
        "duplicate_examples": sum(len(idxs) - 1 for idxs in duplicates.values()),
        "details": sorted(
            ((q, idxs) for q, idxs in duplicates.items()),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:20],
    }


def near_duplicate_audit(examples: list[dict], embeddings: np.ndarray) -> dict:
    """Find near-duplicate queries via embedding cosine similarity."""
    # Normalize embeddings
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / np.where(norms == 0, 1, norms)

    # Compute pairwise similarities (upper triangle only)
    sim_matrix = np.dot(normed, normed.T)

    # Extract pairs above threshold, excluding self-similarity
    pairs = []
    n = len(examples)
    for i in range(n):
        # Only check j > i to avoid duplicates and self
        row = sim_matrix[i, i + 1 :]
        hits = np.where(row >= NEAR_DUPLICATE_THRESHOLD)[0]
        for h in hits:
            j = i + 1 + int(h)
            pairs.append((i, j, float(sim_matrix[i, j])))

    # Group into clusters for reporting
    clusters: list[set[int]] = []
    for i, j, sim in pairs:
        added = False
        for c in clusters:
            if i in c or j in c:
                c.add(i)
                c.add(j)
                added = True
                break
        if not added:
            clusters.append({i, j})

    # Count redundant examples (each pair beyond the first in a cluster)
    redundant = sum(len(c) - 1 for c in clusters)

    return {
        "pairs_found": len(pairs),
        "clusters_found": len(clusters),
        "redundant_examples": redundant,
        "top_pairs": sorted(pairs, key=lambda x: x[2], reverse=True)[:15],
    }


def class_balance_audit(examples: list[dict]) -> dict:
    """Analyze route class distribution."""
    routes = [ex["labels"]["route"] for ex in examples]
    counts = Counter(routes)
    total = len(examples)

    # Check for intent_family distribution too
    intent_families = [ex["labels"]["intent_family"] for ex in examples]
    intent_counts = Counter(intent_families)

    max_count = max(counts.values())
    min_count = min(counts.values())
    ratio = max_count / min_count if min_count > 0 else float("inf")

    return {
        "route_counts": dict(sorted(counts.items(), key=lambda x: x[1], reverse=True)),
        "route_pcts": {
            k: f"{v / total * 100:.1f}%" for k, v in sorted(counts.items(), key=lambda x: x[1], reverse=True)
        },
        "intent_counts": dict(sorted(intent_counts.items(), key=lambda x: x[1], reverse=True)),
        "max_class": max_count,
        "min_class": min_count,
        "balance_ratio": round(ratio, 2),
        "balance_status": (
            "CRITICAL" if ratio > CLASS_BALANCE_RATIO_CRITICAL
            else "WARN" if ratio > CLASS_BALANCE_RATIO_WARN
            else "OK"
        ),
    }


def source_audit(examples: list[dict]) -> dict:
    """Analyze source and feedback_type distribution."""
    sources = []
    feedback_types = []
    for ex in examples:
        meta = ex.get("metadata", {})
        sources.append(meta.get("source", "unknown"))
        feedback_types.append(meta.get("feedback_type", "unknown"))

    return {
        "source_counts": dict(Counter(sources).most_common()),
        "feedback_type_counts": dict(Counter(feedback_types).most_common()),
    }


def length_audit(examples: list[dict]) -> dict:
    """Analyze query length distribution."""
    lengths = [len(ex["query"]) for ex in examples]
    words = [len(ex["query"].split()) for ex in examples]

    return {
        "char_min": min(lengths),
        "char_max": max(lengths),
        "char_mean": round(sum(lengths) / len(lengths), 1),
        "char_median": round(sorted(lengths)[len(lengths) // 2], 1),
        "word_min": min(words),
        "word_max": max(words),
        "word_mean": round(sum(words) / len(words), 1),
        "very_short_queries": sum(1 for w in words if w <= 3),
        "very_long_queries": sum(1 for w in words if w >= 30),
    }


def cross_route_near_duplicates(examples: list[dict], embeddings: np.ndarray) -> dict:
    """Find near-duplicates across DIFFERENT routes (most dangerous)."""
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    normed = embeddings / np.where(norms == 0, 1, norms)
    sim_matrix = np.dot(normed, normed.T)

    cross_route_pairs = []
    n = len(examples)
    for i in range(n):
        row = sim_matrix[i, i + 1 :]
        hits = np.where(row >= NEAR_DUPLICATE_THRESHOLD)[0]
        for h in hits:
            j = i + 1 + int(h)
            route_i = examples[i]["labels"]["route"]
            route_j = examples[j]["labels"]["route"]
            if route_i != route_j:
                cross_route_pairs.append((
                    i, j, float(sim_matrix[i, j]),
                    route_i, route_j,
                    examples[i]["query"][:60],
                    examples[j]["query"][:60],
                ))

    return {
        "count": len(cross_route_pairs),
        "details": sorted(cross_route_pairs, key=lambda x: x[2], reverse=True)[:10],
    }


def main() -> int:
    print("=" * 70)
    print("ROUTER TRAINING DATA AUDIT")
    print("=" * 70)
    print()

    examples, embeddings = load_data()
    print(f"Dataset: {DATA_PATH}")
    print(f"Embeddings: {EMBEDDINGS_PATH}  ({embeddings.shape[0]} × {embeddings.shape[1]})")
    print()

    # --- Exact duplicates ---
    print("-" * 70)
    print("EXACT DUPLICATE QUERIES")
    print("-" * 70)
    dup = exact_duplicate_audit(examples)
    print(f"Duplicate groups: {dup['duplicate_groups']}")
    print(f"Redundant examples: {dup['duplicate_examples']}")
    if dup["details"]:
        print("\nTop duplicate groups:")
        for q, idxs in dup["details"][:10]:
            print(f"  [{len(idxs)}×] {q[:80]}")
    print()

    # --- Near duplicates ---
    print("-" * 70)
    print(f"NEAR-DUPLICATE QUERIES (cosine ≥ {NEAR_DUPLICATE_THRESHOLD})")
    print("-" * 70)
    near = near_duplicate_audit(examples, embeddings)
    print(f"Near-duplicate pairs: {near['pairs_found']}")
    print(f"Clusters: {near['clusters_found']}")
    print(f"Redundant examples: {near['redundant_examples']}")
    if near["top_pairs"]:
        print("\nTop near-duplicate pairs:")
        for i, j, sim in near["top_pairs"][:10]:
            print(f"  sim={sim:.4f}")
            print(f"    [{examples[i]['labels']['route']}] {examples[i]['query'][:70]}")
            print(f"    [{examples[j]['labels']['route']}] {examples[j]['query'][:70]}")
    print()

    # --- Cross-route near duplicates (dangerous!) ---
    print("-" * 70)
    print("CROSS-ROUTE NEAR-DUPLICATES (most dangerous)")
    print("-" * 70)
    cross = cross_route_near_duplicates(examples, embeddings)
    print(f"Cross-route near-duplicate pairs: {cross['count']}")
    if cross["details"]:
        print("\nTop cross-route near-duplicates:")
        for i, j, sim, ri, rj, qi, qj in cross["details"]:
            print(f"  sim={sim:.4f}  {ri} ↔ {rj}")
            print(f"    A: {qi}")
            print(f"    B: {qj}")
    else:
        print("  None found — good.")
    print()

    # --- Class balance ---
    print("-" * 70)
    print("CLASS BALANCE")
    print("-" * 70)
    bal = class_balance_audit(examples)
    print(f"Route distribution:")
    for route, count in bal["route_counts"].items():
        pct = bal["route_pcts"][route]
        print(f"  {route:12s} {count:4d}  ({pct})")
    print(f"\nBalance ratio (max/min): {bal['balance_ratio']}")
    print(f"Status: {bal['balance_status']}")
    print()

    # --- Sources ---
    print("-" * 70)
    print("SOURCE DISTRIBUTION")
    print("-" * 70)
    src = source_audit(examples)
    print("Sources:")
    for s, c in src["source_counts"].items():
        print(f"  {s:40s} {c:4d}")
    print("\nFeedback types:")
    for ft, c in src["feedback_type_counts"].items():
        print(f"  {ft:40s} {c:4d}")
    print()

    # --- Length distribution ---
    print("-" * 70)
    print("QUERY LENGTH DISTRIBUTION")
    print("-" * 70)
    ln = length_audit(examples)
    print(f"Characters: min={ln['char_min']}, max={ln['char_max']}, mean={ln['char_mean']}, median={ln['char_median']}")
    print(f"Words:      min={ln['word_min']}, max={ln['word_max']}, mean={ln['word_mean']}")
    print(f"Very short (≤3 words): {ln['very_short_queries']}")
    print(f"Very long (≥30 words): {ln['very_long_queries']}")
    print()

    # --- Summary ---
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    issues = []
    if dup["duplicate_groups"] > 0:
        issues.append(f"{dup['duplicate_groups']} exact duplicate groups ({dup['duplicate_examples']} redundant)")
    if near["redundant_examples"] > 0:
        issues.append(f"{near['redundant_examples']} near-duplicate redundant examples")
    if cross["count"] > 0:
        issues.append(f"{cross['count']} CROSS-ROUTE near-duplicates (critical)")
    if bal["balance_status"] != "OK":
        issues.append(f"Class imbalance: ratio={bal['balance_ratio']} ({bal['balance_status']})")
    if ln["very_short_queries"] > 20:
        issues.append(f"{ln['very_short_queries']} very short queries (≤3 words)")

    if issues:
        print("Issues found:")
        for issue in issues:
            print(f"  ⚠️  {issue}")
    else:
        print("✅ No significant issues found.")
    print()

    return 1 if cross["count"] > 0 or bal["balance_status"] == "CRITICAL" else 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
