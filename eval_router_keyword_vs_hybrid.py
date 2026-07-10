#!/usr/bin/env python3
"""
Router Evaluation: Keyword-Only vs Hybrid (Embedding + Keyword Guards)

Runs the full synthetic adversarial suite (403 cases) through both routing
strategies and reports comparative accuracy.

Usage:
    cd /home/mike/lucy-v10
    source ui-v10/.venv/bin/activate
    PYTHONPATH=tools:models/router python eval_router_keyword_vs_hybrid.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Ensure paths
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent / "models" / "router"))

CASES_PATH = Path(__file__).resolve().parent / "tests" / "synthetic_adversarial_cases.jsonl"


@dataclass
class EvalResult:
    case_id: str
    family: str
    prompt: str
    expected_route: str | None
    forbidden_routes: list[str]
    hybrid_route: str
    hybrid_provider: str
    keyword_route: str
    keyword_provider: str
    hybrid_correct: bool
    keyword_correct: bool
    hybrid_error: str | None
    keyword_error: str | None


def load_cases() -> list[dict[str, Any]]:
    cases = []
    with CASES_PATH.open("r", encoding="utf-8") as fh:
        for raw in fh:
            raw = raw.strip()
            if raw:
                cases.append(json.loads(raw))
    return cases


def evaluate_hybrid(cases: list[dict[str, Any]]) -> list[EvalResult]:
    """Evaluate using current hybrid router (embedding + keyword guards)."""
    from router_py.classify import classify_intent, select_route

    results = []
    for case in cases:
        prompt = case["prompt"]
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])

        try:
            classification = classify_intent(prompt)
            decision = select_route(
                classification,
                query=prompt,
                policy="fallback_only",
            )
            hybrid_route = decision.route
            hybrid_provider = decision.provider
        except Exception:
            hybrid_route = "ERROR"
            hybrid_provider = "ERROR"

        hybrid_err = None
        if expected is not None and hybrid_route != expected:
            hybrid_err = f"expected {expected}, got {hybrid_route}"
        if hybrid_route in forbidden:
            hybrid_err = (hybrid_err or "") + f"; FORBIDDEN route {hybrid_route}"

        results.append(
            {
                "route": hybrid_route,
                "provider": hybrid_provider,
                "error": hybrid_err,
            }
        )
    return results


def evaluate_keyword_only(cases: list[dict[str, Any]]) -> list[EvalResult]:
    """Evaluate with embedding router disabled (keyword guards only)."""
    # Monkey-patch _get_router to return None, forcing skip of embedding path
    import router_py.classify as classify_mod
    from router_py.classify import classify_intent, select_route

    original_get_router = getattr(classify_mod, "_get_router", None)

    def _noop_router():
        return None

    classify_mod._get_router = _noop_router

    results = []
    for case in cases:
        prompt = case["prompt"]
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])

        try:
            classification = classify_intent(prompt)
            decision = select_route(
                classification,
                query=prompt,
                policy="fallback_only",
            )
            keyword_route = decision.route
            keyword_provider = decision.provider
        except Exception:
            keyword_route = "ERROR"
            keyword_provider = "ERROR"

        keyword_err = None
        if expected is not None and keyword_route != expected:
            keyword_err = f"expected {expected}, got {keyword_route}"
        if keyword_route in forbidden:
            keyword_err = (keyword_err or "") + f"; FORBIDDEN route {keyword_route}"

        results.append(
            {
                "route": keyword_route,
                "provider": keyword_provider,
                "error": keyword_err,
            }
        )

    # Restore
    if original_get_router:
        classify_mod._get_router = original_get_router

    return results


def main():
    print("=" * 70)
    print("ROUTER EVALUATION: Keyword-Only vs Hybrid")
    print("=" * 70)

    cases = load_cases()
    print(f"Loaded {len(cases)} synthetic adversarial cases\n")

    print("Running HYBRID (embedding + keyword guards)...")
    hybrid_results = evaluate_hybrid(cases)
    print("  Done.")

    print("Running KEYWORD-ONLY (keyword guards, no embedding)...")
    keyword_results = evaluate_keyword_only(cases)
    print("  Done.\n")

    # Build per-family stats
    family_stats = defaultdict(
        lambda: {
            "total": 0,
            "hybrid_correct": 0,
            "keyword_correct": 0,
            "both_correct": 0,
            "both_wrong": 0,
            "hybrid_only": 0,
            "keyword_only": 0,
            "hybrid_errors": [],
            "keyword_errors": [],
        }
    )

    total_correct_hybrid = 0
    total_correct_keyword = 0
    total_with_expected = 0

    diffs = []

    for case, hy, kw in zip(cases, hybrid_results, keyword_results):
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])
        family = case["family"]
        prompt = case["prompt"]
        cid = case["id"]

        # A case is "correct" if:
        # - expected_route matches actual route, AND
        # - actual route is NOT in forbidden_routes
        hy_ok = True
        if expected is not None and hy["route"] != expected:
            hy_ok = False
        if hy["route"] in forbidden:
            hy_ok = False

        kw_ok = True
        if expected is not None and kw["route"] != expected:
            kw_ok = False
        if kw["route"] in forbidden:
            kw_ok = False

        stats = family_stats[family]
        stats["total"] += 1
        if hy_ok:
            stats["hybrid_correct"] += 1
        if kw_ok:
            stats["keyword_correct"] += 1
        if hy_ok and kw_ok:
            stats["both_correct"] += 1
        elif not hy_ok and not kw_ok:
            stats["both_wrong"] += 1
        elif hy_ok and not kw_ok:
            stats["hybrid_only"] += 1
        elif not hy_ok and kw_ok:
            stats["keyword_only"] += 1

        if expected is not None:
            total_with_expected += 1
            if hy_ok:
                total_correct_hybrid += 1
            if kw_ok:
                total_correct_keyword += 1

        if hy["route"] != kw["route"]:
            diffs.append(
                {
                    "id": cid,
                    "family": family,
                    "prompt": prompt[:60],
                    "hybrid": hy["route"],
                    "keyword": kw["route"],
                    "expected": expected,
                }
            )

        if not hy_ok and hy["error"]:
            stats["hybrid_errors"].append(
                f"[{cid}] {prompt[:50]}... -> {hy['route']} ({hy['error']})"
            )
        if not kw_ok and kw["error"]:
            stats["keyword_errors"].append(
                f"[{cid}] {prompt[:50]}... -> {kw['route']} ({kw['error']})"
            )

    # Summary
    print("-" * 70)
    print("OVERALL RESULTS")
    print("-" * 70)
    print(f"  Total cases evaluated:              {len(cases)}")
    print(f"  Cases with expected_route:          {total_with_expected}")
    print(
        f"  Hybrid correct (incl. forbidden):   {total_correct_hybrid} / {len(cases)} ({100*total_correct_hybrid/len(cases):.1f}%)"
    )
    print(
        f"  Keyword correct (incl. forbidden):  {total_correct_keyword} / {len(cases)} ({100*total_correct_keyword/len(cases):.1f}%)"
    )
    print(f"  Routes that differed:               {len(diffs)}")
    print()

    print("-" * 70)
    print("PER-FAMILY BREAKDOWN")
    print("-" * 70)
    print(
        f"{'Family':<30} {'Total':>6} {'Hybrid':>7} {'Keyword':>8} {'BothOK':>7} {'BothBad':>8} {'HyOnly':>7} {'KwOnly':>7}"
    )
    print("-" * 70)
    for family in sorted(family_stats.keys()):
        s = family_stats[family]
        print(
            f"{family:<30} {s['total']:>6} "
            f"{s['hybrid_correct']:>7} {s['keyword_correct']:>8} "
            f"{s['both_correct']:>7} {s['both_wrong']:>8} "
            f"{s['hybrid_only']:>7} {s['keyword_only']:>7}"
        )
    print()

    # Cases where keyword wins (hybrid is wrong, keyword is right)
    print("-" * 70)
    print("CASES WHERE KEYWORD-ONLY WINS (hybrid wrong, keyword right)")
    print("-" * 70)
    keyword_wins = [
        d
        for d in diffs
        if any(
            d["id"] == case["id"]
            and (
                case.get("expected_route") == d["keyword"]
                or (
                    d["keyword"] not in case.get("forbidden_routes", [])
                    and d["hybrid"] in case.get("forbidden_routes", [])
                )
            )
            for case in cases
        )
    ]
    # Better approach: recompute
    keyword_wins = []
    for case, hy, kw in zip(cases, hybrid_results, keyword_results):
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])
        hy_ok = (expected is None or hy["route"] == expected) and hy["route"] not in forbidden
        kw_ok = (expected is None or kw["route"] == expected) and kw["route"] not in forbidden
        if not hy_ok and kw_ok:
            keyword_wins.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "prompt": case["prompt"],
                    "expected": expected,
                    "hybrid": hy["route"],
                    "keyword": kw["route"],
                }
            )

    print(f"  Count: {len(keyword_wins)}")
    for w in keyword_wins[:20]:
        print(f"    [{w['id']}] {w['prompt'][:55]}...")
        print(f"      expected={w['expected']}, hybrid={w['hybrid']}, keyword={w['keyword']}")
    if len(keyword_wins) > 20:
        print(f"    ... and {len(keyword_wins) - 20} more")
    print()

    # Cases where hybrid wins
    print("-" * 70)
    print("CASES WHERE HYBRID WINS (keyword wrong, hybrid right)")
    print("-" * 70)
    hybrid_wins = []
    for case, hy, kw in zip(cases, hybrid_results, keyword_results):
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])
        hy_ok = (expected is None or hy["route"] == expected) and hy["route"] not in forbidden
        kw_ok = (expected is None or kw["route"] == expected) and kw["route"] not in forbidden
        if hy_ok and not kw_ok:
            hybrid_wins.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "prompt": case["prompt"],
                    "expected": expected,
                    "hybrid": hy["route"],
                    "keyword": kw["route"],
                }
            )

    print(f"  Count: {len(hybrid_wins)}")
    for w in hybrid_wins[:20]:
        print(f"    [{w['id']}] {w['prompt'][:55]}...")
        print(f"      expected={w['expected']}, hybrid={w['hybrid']}, keyword={w['keyword']}")
    if len(hybrid_wins) > 20:
        print(f"    ... and {len(hybrid_wins) - 20} more")
    print()

    # Cases where both are wrong
    print("-" * 70)
    print("CASES WHERE BOTH ARE WRONG")
    print("-" * 70)
    both_wrong = []
    for case, hy, kw in zip(cases, hybrid_results, keyword_results):
        expected = case.get("expected_route")
        forbidden = case.get("forbidden_routes", [])
        hy_ok = (expected is None or hy["route"] == expected) and hy["route"] not in forbidden
        kw_ok = (expected is None or kw["route"] == expected) and kw["route"] not in forbidden
        if not hy_ok and not kw_ok:
            both_wrong.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "prompt": case["prompt"],
                    "expected": expected,
                    "hybrid": hy["route"],
                    "keyword": kw["route"],
                    "forbidden": forbidden,
                }
            )

    print(f"  Count: {len(both_wrong)}")
    for w in both_wrong[:15]:
        print(f"    [{w['id']}] {w['prompt'][:55]}...")
        print(
            f"      expected={w['expected']}, hybrid={w['hybrid']}, keyword={w['keyword']}, forbidden={w['forbidden']}"
        )
    if len(both_wrong) > 15:
        print(f"    ... and {len(both_wrong) - 15} more")
    print()

    # Final recommendation
    print("=" * 70)
    print("RECOMMENDATION")
    print("=" * 70)
    hy_acc = total_correct_hybrid / len(cases) * 100
    kw_acc = total_correct_keyword / len(cases) * 100
    diff = hy_acc - kw_acc
    print(f"  Hybrid accuracy:  {hy_acc:.1f}%")
    print(f"  Keyword accuracy: {kw_acc:.1f}%")
    print(f"  Difference:       {diff:+.1f} percentage points")
    print()
    if diff > 2.0:
        print("  VERDICT: Keep the hybrid router. It provides a measurable accuracy")
        print("           improvement over keyword-only. Consider fine-tuning or")
        print("           contrastive learning to fix the semantic blindness.")
    elif diff < -2.0:
        print("  VERDICT: Demote the embedding router. Keyword-only is more accurate.")
        print("           The embedding router is introducing net-negative value.")
    else:
        print("  VERDICT: Statistically tied. The embedding router adds no meaningful")
        print("           accuracy benefit. Demote to tie-breaker-only to reduce")
        print("           hallucination risk and simplify the pipeline.")
    print()


if __name__ == "__main__":
    main()
