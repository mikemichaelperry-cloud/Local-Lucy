#!/usr/bin/env python3
"""
End-to-end latency benchmark for all routing modes.

Tests the unified pipeline (main.run()) across:
  LOCAL, WEATHER, TIME, NEWS, AUGMENTED

Measures:
  - Wall-clock time (total user-perceived latency)
  - Per-stage breakdown when LUCY_LATENCY_PROFILE=1:
    classify_ms, route_ms, provider_resolve_ms, context_build_ms, execute_ms, overhead_ms
  - Cold vs warm comparison (LOCAL only, 3 runs)

Usage:
    cd /home/mike/lucy-v10
    source ui-v10/.venv/bin/activate
    LUCY_LATENCY_PROFILE=1 python tools/router_py/benchmark_e2e_latency.py

Requirements:
    Ollama running with local-lucy loaded
    Internet connectivity for WEATHER/TIME/NEWS/AUGMENTED
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure project paths
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(PROJECT_ROOT))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(PROJECT_ROOT))
os.environ.setdefault("LUCY_UI_ROOT", str(PROJECT_ROOT / "ui-v10"))
os.environ.setdefault("LUCY_LATENCY_PROFILE", "1")
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")
os.environ.setdefault("LUCY_SESSION_MEMORY", "0")  # Disable memory for pure benchmark

from router_py.main import run


# ---------------------------------------------------------------------------
# Test cases by expected route
# ---------------------------------------------------------------------------

BENCHMARK_CASES: list[dict[str, Any]] = [
    # LOCAL — knowledge questions (3 runs for warm/cold analysis)
    {
        "query": "What is Ohm's law?",
        "expected_route": "LOCAL",
        "runs": 3,
        "category": "local_knowledge",
    },
    {
        "query": "Explain entropy in simple terms.",
        "expected_route": "LOCAL",
        "runs": 3,
        "category": "local_knowledge",
    },
    # WEATHER — live data
    {
        "query": "What is the weather in London?",
        "expected_route": "WEATHER",
        "runs": 2,
        "category": "live_weather",
    },
    # TIME — live data
    {
        "query": "What time is it in Tokyo?",
        "expected_route": "TIME",
        "runs": 2,
        "category": "live_time",
    },
    # NEWS — live data
    {
        "query": "Latest news about technology",
        "expected_route": "NEWS",
        "runs": 1,
        "category": "live_news",
    },
    # AUGMENTED — Wikipedia evidence + local
    {
        "query": "What is photosynthesis?",
        "expected_route": "AUGMENTED",
        "runs": 2,
        "category": "augmented_wikipedia",
    },
]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RunResult:
    wall_ms: int
    reported_ms: int
    classify_ms: int | None
    route_ms: int | None
    provider_resolve_ms: int | None
    context_build_ms: int | None
    execute_ms: int | None
    overhead_ms: int | None
    actual_route: str
    status: str
    success: bool


@dataclass
class CaseResult:
    query: str
    expected_route: str
    category: str
    runs: list[RunResult] = field(default_factory=list)

    def median_wall_ms(self) -> float | None:
        times = [r.wall_ms for r in self.runs if r.success]
        return statistics.median(times) if times else None

    def median_execute_ms(self) -> float | None:
        times = [r.execute_ms for r in self.runs if r.success and r.execute_ms is not None]
        return statistics.median(times) if times else None

    def median_overhead_ms(self) -> float | None:
        times = [r.overhead_ms for r in self.runs if r.success and r.overhead_ms is not None]
        return statistics.median(times) if times else None

    def cold_wall_ms(self) -> int | None:
        first = [r for r in self.runs if r.success]
        return first[0].wall_ms if first else None

    def warm_wall_ms(self) -> float | None:
        times = [r.wall_ms for r in self.runs if r.success]
        return statistics.median(times[1:]) if len(times) > 1 else None


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------

def _extract_profile(outcome) -> dict[str, int]:
    """Extract latency profile from outcome metadata."""
    meta = getattr(outcome, "metadata", {}) or {}
    return meta.get("latency_profile", {})


def _run_case(case: dict[str, Any]) -> CaseResult:
    """Run a single benchmark case (may include multiple iterations)."""
    result = CaseResult(
        query=case["query"],
        expected_route=case["expected_route"],
        category=case["category"],
    )

    for i in range(case["runs"]):
        run_label = "cold" if i == 0 else f"warm-{i}"
        print(f"    [{run_label}] ", end="", flush=True)

        t0 = time.perf_counter()
        try:
            outcome = run(
                question=case["query"],
                policy="fallback_only",
                timeout=130,
                surface="cli",
            )
        except Exception as exc:
            print(f"ERROR: {exc}")
            result.runs.append(RunResult(
                wall_ms=0, reported_ms=0,
                classify_ms=None, route_ms=None,
                provider_resolve_ms=None, context_build_ms=None,
                execute_ms=None, overhead_ms=None,
                actual_route="ERROR", status="exception", success=False,
            ))
            continue

        wall_ms = int((time.perf_counter() - t0) * 1000)
        profile = _extract_profile(outcome)

        run_result = RunResult(
            wall_ms=wall_ms,
            reported_ms=outcome.execution_time_ms or 0,
            classify_ms=profile.get("classify_ms"),
            route_ms=profile.get("route_ms"),
            provider_resolve_ms=profile.get("provider_resolve_ms"),
            context_build_ms=profile.get("context_build_ms"),
            execute_ms=profile.get("execute_ms"),
            overhead_ms=profile.get("overhead_ms"),
            actual_route=outcome.route,
            status=outcome.status,
            success=outcome.status == "completed",
        )
        result.runs.append(run_result)

        status_icon = "✓" if run_result.success else "✗"
        route_ok = "✓" if outcome.route == case["expected_route"] else f"!{outcome.route}"
        print(f"{status_icon} wall={wall_ms}ms reported={run_result.reported_ms}ms route={route_ok}")

        # Brief pause between runs
        if i < case["runs"] - 1:
            time.sleep(1.5)

    return result


def _print_summary(results: list[CaseResult]) -> None:
    """Print formatted summary table."""
    print("\n" + "=" * 90)
    print("SUMMARY — Per-Route Latency")
    print("=" * 90)
    print(f"{'Category':<22} {'Query':<30} {'Cold':>8} {'Warm':>8} {'Execute':>8} {'Overhead':>8}")
    print("-" * 90)

    for case in results:
        cold = case.cold_wall_ms()
        warm = case.warm_wall_ms()
        execute = case.median_execute_ms()
        overhead = case.median_overhead_ms()

        cold_str = f"{cold}ms" if cold is not None else "n/a"
        warm_str = f"{int(warm)}ms" if warm is not None else cold_str
        execute_str = f"{int(execute)}ms" if execute is not None else "n/a"
        overhead_str = f"{int(overhead)}ms" if overhead is not None else "n/a"

        print(
            f"{case.category:<22} {case.query[:28]:<30} "
            f"{cold_str:>8} {warm_str:>8} {execute_str:>8} {overhead_str:>8}"
        )

    # Bottleneck analysis
    print("\n" + "=" * 90)
    print("BOTTLENECK ANALYSIS")
    print("=" * 90)

    all_profiles: list[dict[str, int]] = []
    for case in results:
        for run in case.runs:
            if run.success and run.execute_ms is not None:
                all_profiles.append({
                    "classify": run.classify_ms or 0,
                    "route": run.route_ms or 0,
                    "provider_resolve": run.provider_resolve_ms or 0,
                    "context_build": run.context_build_ms or 0,
                    "execute": run.execute_ms or 0,
                    "overhead": run.overhead_ms or 0,
                })

    if all_profiles:
        stages = ["classify", "route", "provider_resolve", "context_build", "execute", "overhead"]
        print(f"{'Stage':<20} {'Median':>10} {'Max':>10} {'% of total':>12}")
        print("-" * 55)

        totals = [sum(p[s] for s in stages) for p in all_profiles]
        median_total = statistics.median(totals) if totals else 1

        for stage in stages:
            vals = [p[stage] for p in all_profiles]
            med = statistics.median(vals)
            max_v = max(vals)
            pct = (med / median_total * 100) if median_total else 0
            print(f"{stage:<20} {med:>8}ms {max_v:>8}ms {pct:>10.1f}%")

    # Route comparison
    print("\n" + "=" * 90)
    print("ROUTE COMPARISON (median wall time)")
    print("=" * 90)
    route_times: dict[str, list[int]] = {}
    for case in results:
        for run in case.runs:
            if run.success:
                route_times.setdefault(case.expected_route, []).append(run.wall_ms)

    for route, times in sorted(route_times.items(), key=lambda x: statistics.median(x[1])):
        med = statistics.median(times)
        min_t = min(times)
        max_t = max(times)
        print(f"  {route:<12} {med:>8}ms  (range: {min_t}–{max_t}ms, n={len(times)})")


def main() -> int:
    print("=" * 90)
    print("LOCAL LUCY v8 — End-to-End Latency Benchmark")
    print("=" * 90)
    print(f"Profiling: {'ON' if os.environ.get('LUCY_LATENCY_PROFILE') == '1' else 'OFF'}")
    print(f"Project root: {PROJECT_ROOT}")
    print("")

    # Warm-up: force router model load before timing
    print("Warming up embedding router...")
    try:
        run("What is 2+2?", policy="fallback_only", timeout=30, surface="cli")
        print("  ✓ Router warm")
    except Exception as exc:
        print(f"  ✗ Warm-up failed: {exc}")
        return 1

    print("")

    results: list[CaseResult] = []
    for case in BENCHMARK_CASES:
        print(f"[{case['category']}] {case['query']!r} → {case['expected_route']}")
        results.append(_run_case(case))
        print("")

    _print_summary(results)

    # Save JSON report
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "profiling_enabled": os.environ.get("LUCY_LATENCY_PROFILE") == "1",
        "cases": [
            {
                "query": c.query,
                "expected_route": c.expected_route,
                "category": c.category,
                "runs": [
                    {
                        "wall_ms": r.wall_ms,
                        "reported_ms": r.reported_ms,
                        "classify_ms": r.classify_ms,
                        "route_ms": r.route_ms,
                        "provider_resolve_ms": r.provider_resolve_ms,
                        "context_build_ms": r.context_build_ms,
                        "execute_ms": r.execute_ms,
                        "overhead_ms": r.overhead_ms,
                        "actual_route": r.actual_route,
                        "status": r.status,
                        "success": r.success,
                    }
                    for r in c.runs
                ],
            }
            for c in results
        ],
    }

    report_path = PROJECT_ROOT / "logs" / "e2e_latency_benchmark.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nFull report saved to: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
