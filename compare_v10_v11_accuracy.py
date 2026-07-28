#!/usr/bin/env python3
"""V10 vs V11 accuracy/intuition comparison suite.

Runs the curated cases in data/evaluation/v10_v11_accuracy_suite.jsonl through
both V10 and V11 routing pipelines and reports agreement, V11 accuracy against
the expected route, and deltas.

Usage:
    cd /home/mike/lucy-v11
    source ui-v10/.venv/bin/activate
    python compare_v10_v11_accuracy.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

V10_ROOT = Path("/home/mike/lucy-v10")
V11_ROOT = Path("/home/mike/lucy-v11")
V10_VENV = V10_ROOT / "ui-v10" / ".venv" / "bin" / "python"
V11_VENV = V11_ROOT / "ui-v10" / ".venv" / "bin" / "python"
SUITE_PATH = V11_ROOT / "data" / "evaluation" / "v10_v11_accuracy_suite.jsonl"


def load_cases() -> list[dict[str, Any]]:
    cases = []
    with SUITE_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _run_subprocess(
    cwd: Path,
    python: Path,
    code: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """Run a Python snippet in the target project venv and return parsed JSON."""
    env = {
        "PYTHONPATH": "tools:models/router",
        "LUCY_EXEC_PY": "1",
        "LUCY_SESSION_MEMORY": "0",
    }
    cmd = [str(python), "-c", code]
    result = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Subprocess failed: {result.stderr[:500]}")
    # Some modules print progress to stdout before JSON; take last JSON object.
    lines = [ln for ln in result.stdout.splitlines() if ln.strip()]
    for ln in reversed(lines):
        try:
            return json.loads(ln)
        except json.JSONDecodeError:
            continue
    raise RuntimeError(f"No JSON found in output:\n{result.stdout[:500]}")


def v10_classify(query: str, surface: str = "cli") -> str:
    code = (
        "import sys; "
        "sys.path.insert(0, 'tools'); "
        "sys.path.insert(0, 'tools/router_py'); "
        "from router_py.classify import classify_intent, select_route; "
        f"c = classify_intent({query!r}, surface={surface!r}); "
        f"d = select_route(c, query={query!r}, policy='fallback_only'); "
        "import json; "
        "print(json.dumps({'route': d.route, 'policy_reason': d.policy_reason}))"
    )
    data = _run_subprocess(V10_ROOT, V10_VENV, code)
    return data["route"]


def v10_pipeline(query: str, surface: str = "cli") -> str:
    code = (
        "import sys; "
        "sys.path.insert(0, 'tools'); "
        "sys.path.insert(0, 'tools/router_py'); "
        "from router_py.main import execute_plan_python; "
        f"o = execute_plan_python({query!r}, surface={surface!r}, timeout=30); "
        "import json; "
        "print(json.dumps({'route': o.route, 'policy_reason': o.policy_reason, 'status': o.status}))"
    )
    data = _run_subprocess(V10_ROOT, V10_VENV, code)
    return data["route"]


def v11_classify(query: str, surface: str = "cli") -> str:
    code = (
        "import sys; "
        "sys.path.insert(0, 'tools'); "
        "sys.path.insert(0, 'tools/router_py'); "
        "from router_py.classify import classify_intent, select_route; "
        f"c = classify_intent({query!r}, surface={surface!r}); "
        f"d = select_route(c, query={query!r}, policy='fallback_only'); "
        "import json; "
        "print(json.dumps({'route': d.route, 'policy_reason': d.policy_reason}))"
    )
    data = _run_subprocess(V11_ROOT, V11_VENV, code)
    return data["route"]


def v11_pipeline(query: str, surface: str = "cli") -> str:
    code = (
        "import sys; "
        "sys.path.insert(0, 'tools'); "
        "sys.path.insert(0, 'tools/router_py'); "
        "from router_py.main import execute_plan_python; "
        f"o = execute_plan_python({query!r}, surface={surface!r}, timeout=30); "
        "import json; "
        "print(json.dumps({'route': o.route, 'policy_reason': o.policy_reason, 'status': o.status}))"
    )
    data = _run_subprocess(V11_ROOT, V11_VENV, code)
    return data["route"]


def evaluate_case(case: dict[str, Any]) -> dict[str, Any]:
    query = case["query"]
    surface = case.get("surface", "cli")
    use_pipeline = case.get("use_pipeline", False)

    if use_pipeline:
        v10_route = v10_pipeline(query, surface)
        v11_route = v11_pipeline(query, surface)
    else:
        v10_route = v10_classify(query, surface)
        v11_route = v11_classify(query, surface)

    expected = case["expected_v11"]
    return {
        "id": case["id"],
        "category": case["category"],
        "query": query,
        "surface": surface,
        "use_pipeline": use_pipeline,
        "v10_route": v10_route,
        "v11_route": v11_route,
        "expected_v11": expected,
        "v10_matches_v11": v10_route == v11_route,
        "v11_correct": v11_route == expected,
    }


def main() -> int:
    if not SUITE_PATH.exists():
        print(f"Suite not found: {SUITE_PATH}", file=sys.stderr)
        return 1

    cases = load_cases()
    print(f"Loaded {len(cases)} cases from {SUITE_PATH}\n")

    results = []
    for case in cases:
        try:
            result = evaluate_case(case)
        except Exception as exc:
            result = {
                "id": case["id"],
                "category": case["category"],
                "query": case["query"],
                "surface": case.get("surface", "cli"),
                "use_pipeline": case.get("use_pipeline", False),
                "v10_route": f"ERROR: {exc}",
                "v11_route": f"ERROR: {exc}",
                "expected_v11": case["expected_v11"],
                "v10_matches_v11": False,
                "v11_correct": False,
            }
        results.append(result)

    # Per-category stats
    stats = defaultdict(lambda: {"total": 0, "agree": 0, "v11_correct": 0})
    total_agree = 0
    total_v11_correct = 0
    deltas = []

    print(
        f"{'ID':<30} {'CATEGORY':<22} {'V10':<10} {'V11':<10} {'EXPECTED':<10} {'AGREE':<5} {'V11_OK':<6}"
    )
    print("=" * 105)
    for r in results:
        cat = r["category"]
        stats[cat]["total"] += 1
        if r["v10_matches_v11"]:
            stats[cat]["agree"] += 1
            total_agree += 1
        if r["v11_correct"]:
            stats[cat]["v11_correct"] += 1
            total_v11_correct += 1
        else:
            deltas.append(r)
        if not r["v10_matches_v11"] or not r["v11_correct"]:
            deltas.append(r)

        agree = "YES" if r["v10_matches_v11"] else "NO"
        ok = "YES" if r["v11_correct"] else "NO"
        print(
            f"{r['id']:<30} {r['category']:<22} {r['v10_route']:<10} "
            f"{r['v11_route']:<10} {r['expected_v11']:<10} {agree:<5} {ok:<6}"
        )

    print("\n" + "=" * 105)
    print("Per-category summary")
    print("-" * 105)
    print(f"{'CATEGORY':<22} {'CASES':>6} {'AGREE':>6} {'V11_CORRECT':>12}")
    for cat in sorted(stats):
        s = stats[cat]
        print(f"{cat:<22} {s['total']:>6} {s['agree']:>6} {s['v11_correct']:>12}")
    print("-" * 105)
    print(f"{'TOTAL':<22} {len(results):>6} {total_agree:>6} {total_v11_correct:>12}")

    print(
        f"\nOverall agreement: {total_agree}/{len(results)} ({100 * total_agree / len(results):.1f}%)"
    )
    print(
        f"V11 accuracy vs expected: {total_v11_correct}/{len(results)} ({100 * total_v11_correct / len(results):.1f}%)"
    )

    if deltas:
        print("\nDeltas / failures:")
        seen = set()
        for r in deltas:
            key = (r["id"], r["v10_route"], r["v11_route"])
            if key in seen:
                continue
            seen.add(key)
            print(
                f"  - {r['id']} ({r['category']}): V10={r['v10_route']} V11={r['v11_route']} expected={r['expected_v11']}"
            )
            print(f"    Query: {r['query']}")

    # Write machine-readable report
    report_path = V11_ROOT / "lucy-v11-prep" / "reports" / "phase12_v10_v11_accuracy_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", encoding="utf-8") as fh:
        json.dump(
            {
                "suite_path": str(SUITE_PATH),
                "total_cases": len(results),
                "agreement": {"count": total_agree, "pct": 100 * total_agree / len(results)},
                "v11_accuracy": {
                    "count": total_v11_correct,
                    "pct": 100 * total_v11_correct / len(results),
                },
                "per_category": {k: dict(v) for k, v in stats.items()},
                "results": results,
            },
            fh,
            indent=2,
        )
    print(f"\nDetailed results written to: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
