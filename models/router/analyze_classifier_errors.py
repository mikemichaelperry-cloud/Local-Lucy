#!/usr/bin/env python3
"""Evaluate the router on the frozen validation corpus and categorize errors.

Usage:
    python models/router/analyze_classifier_errors.py [--output path]

Outputs:
    data/evaluation/classifier_error_report.json with:
      - overall accuracy
      - per-route precision / recall / f1
      - confusion matrix
      - error counts by category
      - full list of misrouted examples
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path


# Make router_py and hybrid_router_v2 importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "models" / "router"))

from router_py.classify import classify_intent, prewarm_router, select_route


ROUTER_DIR = Path(__file__).resolve().parent
ROOT_DIR = ROUTER_DIR.parent.parent
DEFAULT_CORPUS = ROOT_DIR / "data" / "evaluation" / "routing_validation_corpus.jsonl"
DEFAULT_REPORT = ROOT_DIR / "data" / "evaluation" / "classifier_error_report.json"

# Error categories we track
CATEGORIES = {
    "augmented_vs_local": "AUGMENTED vs LOCAL confusion",
    "news_vs_local": "NEWS vs LOCAL confusion",
    "evidence_false_negatives": "EVIDENCE false negatives",
    "ephemeral_misclassification": "EPHEMERAL misclassification",
}


def load_corpus(path: Path) -> list[dict]:
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def categorize_error(expected: str, predicted: str) -> list[str]:
    cats = []
    if {expected, predicted} == {"AUGMENTED", "LOCAL"}:
        cats.append("augmented_vs_local")
    if {expected, predicted} == {"NEWS", "LOCAL"}:
        cats.append("news_vs_local")
    if expected == "EVIDENCE" and predicted != "EVIDENCE":
        cats.append("evidence_false_negatives")
    if expected == "EPHEMERAL" and predicted != "EPHEMERAL":
        cats.append("ephemeral_misclassification")
    return cats


def compute_metrics(expected: list[str], predicted: list[str], routes: list[str]) -> dict:
    # Confusion matrix
    cm = {r: {c: 0 for c in routes} for r in routes}
    for e, p in zip(expected, predicted):
        if e in cm and p in cm[e]:
            cm[e][p] += 1

    per_route = {}
    for route in routes:
        tp = cm[route][route]
        fp = sum(cm[r][route] for r in routes if r != route)
        fn = sum(cm[route][r] for r in routes if r != route)
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        per_route[route] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": tp + fn,
        }

    accuracy = sum(1 for e, p in zip(expected, predicted) if e == p) / len(expected)
    return {
        "accuracy": round(accuracy, 4),
        "confusion_matrix": cm,
        "per_route": per_route,
    }


def evaluate(corpus: list[dict]) -> dict:
    print("Prewarming router...")
    prewarm_router()

    expected = []
    predicted = []
    errors = []
    category_counts = Counter()

    for rec in corpus:
        query = rec["query"]
        exp_route = rec["route"]
        try:
            classification = classify_intent(query)
            decision = select_route(classification, query=query)
            pred_route = decision.route
        except Exception as exc:
            pred_route = "LOCAL"
            print(f"  WARNING: routing failed for '{query[:60]}': {exc}")

        expected.append(exp_route)
        predicted.append(pred_route)

        if exp_route != pred_route:
            cats = categorize_error(exp_route, pred_route)
            for c in cats:
                category_counts[c] += 1
            err = {
                "query": query,
                "expected": exp_route,
                "predicted": pred_route,
                "intent_family": rec.get("intent_family", ""),
                "source": rec.get("source", ""),
                "categories": cats,
            }
            errors.append(err)

    routes = sorted(set(expected) | set(predicted))
    metrics = compute_metrics(expected, predicted, routes)

    report = {
        "metadata": {
            "corpus_path": str(DEFAULT_CORPUS.relative_to(ROOT_DIR)),
            "total": len(corpus),
            "errors": len(errors),
            "accuracy": metrics["accuracy"],
        },
        "metrics": metrics,
        "error_categories": {
            key: {
                "description": desc,
                "count": category_counts.get(key, 0),
            }
            for key, desc in CATEGORIES.items()
        },
        "errors": errors,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze classifier errors on validation corpus")
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS, help="Validation corpus")
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT, help="Report output path")
    args = parser.parse_args()

    os.environ.setdefault("LUCY_SESSION_MEMORY", "0")

    if not args.corpus.exists():
        print(f"ERROR: corpus not found: {args.corpus}", file=sys.stderr)
        return 1

    corpus = load_corpus(args.corpus)
    print(f"Loaded {len(corpus)} validation records")

    report = evaluate(corpus)

    print(f"\nAccuracy: {report['metrics']['accuracy']:.4f}")
    print(f"Errors: {report['metadata']['errors']}/{report['metadata']['total']}")
    print("\nPer-route metrics:")
    for route, m in sorted(report["metrics"]["per_route"].items()):
        print(
            f"  {route:12s} P={m['precision']:.3f} R={m['recall']:.3f} F1={m['f1']:.3f}  n={m['support']}"
        )
    print("\nError categories:")
    for key, info in report["error_categories"].items():
        if info["count"]:
            print(f"  {key}: {info['count']}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote report to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
