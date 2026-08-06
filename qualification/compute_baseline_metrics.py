#!/usr/bin/env python3
"""Compute baseline per-route precision/recall from the validation corpus."""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

# Make project tools importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from router_py.pipeline import classify, route  # noqa: E402
from router_py.request_types import RouterOutcome  # noqa: E402


def load_corpus(path: Path) -> list[dict]:
    cases: list[dict] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def evaluate_case(case: dict) -> tuple[str, str, bool]:
    """Return (expected_route, predicted_route, correct)."""
    query = case["original_query"]
    expected = case["expected_primary_route"]
    acceptable = set(case.get("acceptable_alternative_routes", []))
    forbidden = set(case.get("forbidden_routes", []))

    classify_result, route_prefix, bypass_decision = classify.classify_question(
        query, surface="cli", model=None, route_prefix="", context={}
    )
    if isinstance(classify_result, RouterOutcome):
        return expected, classify_result.route, False
    decision_or_outcome = route.select_route_for_question(
        classify_result, query, policy="fallback_only", context={}
    )

    # select_route_for_question may return a RouterOutcome on routing error.
    if hasattr(decision_or_outcome, "route"):
        predicted = decision_or_outcome.route
    else:
        predicted = decision_or_outcome.route

    correct = predicted == expected or predicted in acceptable
    if predicted in forbidden:
        correct = False

    return expected, predicted, correct


def _compute_metrics(cases: list[dict]) -> dict:
    per_route: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    correct_count = 0
    results: list[dict] = []

    for case in cases:
        expected, predicted, correct = evaluate_case(case)
        correct_count += int(correct)
        per_route[expected]["tp"] += int(correct and predicted == expected)
        per_route[expected]["fn"] += int(not correct or predicted != expected)

        # False positives for the predicted route when it was wrong.
        if predicted != expected and not correct:
            per_route[predicted]["fp"] += 1

        results.append(
            {
                "case_id": case["case_id"],
                "source": case.get("source"),
                "split": case.get("split"),
                "query": case["original_query"],
                "expected": expected,
                "predicted": predicted,
                "correct": correct,
                "risk_level": case.get("risk_level"),
            }
        )

    total = len(cases)
    overall_accuracy = correct_count / total if total else 0.0

    per_route_metrics: dict[str, dict[str, float]] = {}
    for route_name, counts in sorted(per_route.items()):
        tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        per_route_metrics[route_name] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    return {
        "overall_accuracy": overall_accuracy,
        "total_cases": total,
        "correct": correct_count,
        "per_route": per_route_metrics,
        "results": results,
    }


def main() -> int:
    os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
    os.environ.setdefault("LUCY_ENABLE_INTERNET", "1")
    corpus_path = Path(__file__).with_name("routing_failure_corpus.jsonl")
    all_cases = load_corpus(corpus_path)
    val_cases = [c for c in all_cases if c.get("split") == "validation"]
    holdout_cases = [c for c in all_cases if c.get("split") == "locked_holdout"]

    val_metrics = _compute_metrics(val_cases)
    holdout_metrics = _compute_metrics(holdout_cases)
    combined_metrics = _compute_metrics(val_cases + holdout_cases)

    output = {
        "note": "Baseline metrics measure classify+route only; anaphora/context resolution in main.py is excluded.",
        "validation": val_metrics,
        "locked_holdout": holdout_metrics,
        "combined": combined_metrics,
    }

    output_path = Path(__file__).with_name("results") / "baseline_metrics.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, default=str)

    for split_name, metrics in [
        ("validation", val_metrics),
        ("locked_holdout", holdout_metrics),
        ("combined", combined_metrics),
    ]:
        print(
            f"\n{split_name}: {metrics['correct']}/{metrics['total_cases']} = {metrics['overall_accuracy']:.3f}"
        )
        for route_name, m in metrics["per_route"].items():
            print(
                f"  {route_name:12s}  precision={m['precision']:.3f}  recall={m['recall']:.3f}  "
                f"f1={m['f1']:.3f}  (tp={m['tp']} fp={m['fp']} fn={m['fn']})"
            )

    print(f"\nDetailed results written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
