#!/usr/bin/env python3
"""Evaluate old vs new router on the frozen independent holdout set.

Usage:
    python evaluate_holdout.py [--policy]

Outputs:
    holdout_eval_results.json
    holdout_eval_report.txt
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

# Allow importing the router and the policy layer.
ROUTER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = ROUTER_DIR.parent.parent
sys.path.insert(0, str(ROUTER_DIR))
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

from hybrid_router_v2 import HybridRouterV2
from policy_router import PolicyRouter
from request_types import ClassificationResult
from policy import requires_evidence_mode

HOLDOUT_PATH = ROUTER_DIR / "holdout_eval_set.jsonl"
OLD_INDEX_PATH = ROUTER_DIR / "checkpoints" / "comprehensive_index_20260531_181416.jsonl"
OLD_EMBEDDINGS_PATH = ROUTER_DIR / "checkpoints" / "comprehensive_embeddings_20260531_181416.npy"
RESULTS_PATH = ROUTER_DIR / "holdout_eval_results.json"
REPORT_PATH = ROUTER_DIR / "holdout_eval_report.txt"


def _load_holdout(path: Path) -> list[dict]:
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def _build_old_examples_json() -> Path:
    """Convert the old JSONL checkpoint to a JSON array for HybridRouterV2."""
    examples = []
    with open(OLD_INDEX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
    json.dump(examples, tmp, ensure_ascii=False)
    tmp.close()
    return Path(tmp.name)


def _make_classification(query: str) -> ClassificationResult:
    """Build a minimal classification with the evidence reason policy gates need."""
    _, evidence_reason = requires_evidence_mode(query, context={})
    return ClassificationResult(
        intent="ask",
        intent_family="factual",
        evidence_reason=evidence_reason,
    )


def _predict(
    router: HybridRouterV2,
    policy: PolicyRouter | None,
    query: str,
) -> tuple[str, str]:
    """Return (effective_route, source).

    Source is one of: policy, classifier, knn.
    """
    classification = _make_classification(query)
    if policy is not None:
        decision = policy.apply(query, classification, context={})
        if decision is not None:
            return decision.route, "policy"

    result = router.predict(query)
    return result["route"], result.get("routing_source", "knn")


def _evaluate(name: str, router: HybridRouterV2, policy: PolicyRouter | None, holdout: list[dict]):
    correct = 0
    per_route: dict[str, dict[str, int]] = {}
    per_category: dict[str, dict[str, int]] = {}
    rows = []

    for item in holdout:
        expected = item["expected_route"]
        predicted, source = _predict(router, policy, item["query"])
        is_correct = predicted == expected
        if is_correct:
            correct += 1

        per_route.setdefault(expected, {"total": 0, "correct": 0})
        per_route[expected]["total"] += 1
        if is_correct:
            per_route[expected]["correct"] += 1

        cat = item.get("category", "unknown")
        per_category.setdefault(cat, {"total": 0, "correct": 0})
        per_category[cat]["total"] += 1
        if is_correct:
            per_category[cat]["correct"] += 1

        rows.append(
            {
                "query": item["query"],
                "expected": expected,
                "predicted": predicted,
                "correct": is_correct,
                "source": source,
                "category": cat,
            }
        )

    total = len(holdout)
    accuracy = correct / total if total else 0.0
    return {
        "name": name,
        "total": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "per_route": per_route,
        "per_category": per_category,
        "rows": rows,
    }


def _render_report(results: dict) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("Independent Holdout Evaluation Report")
    lines.append("=" * 60)
    lines.append("")
    lines.append(f"Holdout set: {HOLDOUT_PATH}")
    lines.append(f"Old router index: {OLD_INDEX_PATH}")
    lines.append(f"Total holdout examples: {results['holdout_size']}")
    lines.append("")

    for run in results["runs"]:
        lines.append(f"--- {run['name']} ---")
        lines.append(f"Accuracy: {run['correct']}/{run['total']} ({run['accuracy']:.1%})")
        lines.append("Per-route:")
        for route, stats in sorted(run["per_route"].items()):
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
            lines.append(f"  {route:12s} {stats['correct']:2d}/{stats['total']:2d} ({pct:5.1f}%)")
        lines.append("")

    # Build confusion matrix for the full-policy runs.
    full_runs = [r for r in results["runs"] if "+policy" in r["name"]]
    if len(full_runs) == 2:
        old_rows = {r["query"]: r for r in full_runs[0]["rows"]}
        new_rows = {r["query"]: r for r in full_runs[1]["rows"]}
        improved = []
        regressed = []
        for query, old_row in old_rows.items():
            new_row = new_rows[query]
            expected = old_row["expected"]
            if old_row["predicted"] != expected and new_row["predicted"] == expected:
                improved.append((query, old_row["predicted"], new_row["predicted"]))
            elif old_row["predicted"] == expected and new_row["predicted"] != expected:
                regressed.append((query, old_row["predicted"], new_row["predicted"]))
        lines.append("--- New vs Old (with policy) ---")
        lines.append(f"Fixed by new router:   {len(improved)}")
        for q, old_r, new_r in improved[:10]:
            lines.append(f"  + {q[:60]:60s}  {old_r:8s} -> {new_r}")
        if len(improved) > 10:
            lines.append(f"  ... and {len(improved) - 10} more")
        lines.append(f"Broken by new router:  {len(regressed)}")
        for q, old_r, new_r in regressed:
            lines.append(f"  - {q[:60]:60s}  {old_r:8s} -> {new_r}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate old vs new router on holdout set.")
    parser.add_argument("--policy", action="store_true", help="Also apply deterministic policy gates.")
    args = parser.parse_args()

    holdout = _load_holdout(HOLDOUT_PATH)
    if not holdout:
        print("Holdout set is empty.", file=sys.stderr)
        sys.exit(1)

    print(f"Loaded {len(holdout)} holdout examples")
    print("Loading new router (current examples + classifier head)...")
    new_router = HybridRouterV2()

    print("Loading old router (May 31 checkpoint, k-NN only)...")
    old_examples_json = _build_old_examples_json()
    old_router = HybridRouterV2(
        examples_path=str(old_examples_json),
        embeddings_path=str(OLD_EMBEDDINGS_PATH),
    )
    # Force the old router to behave as the k-NN-only baseline it was at the time.
    old_router.classifier_head = None
    old_router.classifier_threshold = 1.0

    policy = PolicyRouter() if args.policy else None

    runs = []
    runs.append(_evaluate("old_embedding_only", old_router, None, holdout))
    runs.append(_evaluate("new_embedding_only", new_router, None, holdout))
    if policy is not None:
        runs.append(_evaluate("old_embedding+policy", old_router, policy, holdout))
        runs.append(_evaluate("new_embedding+policy", new_router, policy, holdout))

    results = {
        "holdout_size": len(holdout),
        "holdout_path": str(HOLDOUT_PATH),
        "old_index_path": str(OLD_INDEX_PATH),
        "policy_enabled": args.policy,
        "runs": runs,
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    report = _render_report(results)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nSaved results to {RESULTS_PATH}")
    print(f"Saved report to {REPORT_PATH}")


if __name__ == "__main__":
    main()
