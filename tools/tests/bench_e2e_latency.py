#!/usr/bin/env python3
"""
End-to-End Latency Benchmark for Local Lucy V8

Profiles per-stage latency across all routing modes with reliable queries.
Measures wall-clock time vs pipeline-reported execution time.
Detects warm (cache hit) vs cold (model load/inference) runs.

Usage:
    cd /home/mike/lucy-v8
    source ui-v8/.venv/bin/activate
    LUCY_LATENCY_PROFILE=1 python3 tools/tests/bench_e2e_latency.py

Environment:
    LUCY_LATENCY_PROFILE=1  — enables per-stage profiling in request_pipeline.py
"""

import os
import sys
import time
import json
import statistics
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Any

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from router_py.main import run

# ---------------------------------------------------------------------------
#  Benchmark configuration — queries chosen for ~100% routing accuracy
# ---------------------------------------------------------------------------

BENCHMARK_QUERIES: list[tuple[str, str, str]] = [
    # (category, query, expected_route)
    ("LOCAL",     "What is the capital of France?",           "LOCAL"),
    ("AUGMENTED", "What is diabetes?",                        "AUGMENTED"),
    ("WEATHER",   "Weather in Paris",                         "WEATHER"),
    ("TIME",      "Time in New York",                         "TIME"),
    ("NEWS",      "Latest news on Israel",                    "NEWS"),
]

RUNS_PER_QUERY = 3
TIMEOUT_SECONDS = 30

REPORT_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
REPORT_PATH = REPORT_DIR / "e2e_latency_benchmark.json"


@dataclass
class QueryResult:
    category: str
    query: str
    expected_route: str
    actual_routes: list[str] = field(default_factory=list)
    wall_times_ms: list[float] = field(default_factory=list)
    execution_times_ms: list[float | None] = field(default_factory=list)
    stage_profiles: list[dict[str, Any]] = field(default_factory=list)

    @property
    def route_accuracy(self) -> float:
        hits = sum(1 for r in self.actual_routes if r == self.expected_route)
        return hits / len(self.actual_routes) if self.actual_routes else 0.0

    @property
    def median_wall_ms(self) -> float | None:
        if not self.wall_times_ms:
            return None
        return statistics.median(self.wall_times_ms)

    @property
    def min_wall_ms(self) -> float | None:
        return min(self.wall_times_ms) if self.wall_times_ms else None

    @property
    def max_wall_ms(self) -> float | None:
        return max(self.wall_times_ms) if self.wall_times_ms else None

    @property
    def is_warm(self) -> bool:
        """Heuristic: if max wall time < 200ms, likely all cache hits."""
        if self.max_wall_ms is None:
            return False
        return self.max_wall_ms < 200

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "query": self.query,
            "expected_route": self.expected_route,
            "actual_routes": self.actual_routes,
            "route_accuracy": self.route_accuracy,
            "wall_times_ms": self.wall_times_ms,
            "median_wall_ms": self.median_wall_ms,
            "min_wall_ms": self.min_wall_ms,
            "max_wall_ms": self.max_wall_ms,
            "execution_times_ms": self.execution_times_ms,
            "is_warm": self.is_warm,
            "stage_profiles": self.stage_profiles,
        }


def benchmark_query(category: str, query: str, expected_route: str) -> QueryResult:
    result = QueryResult(category=category, query=query, expected_route=expected_route)

    for i in range(RUNS_PER_QUERY):
        t0 = time.time()
        try:
            outcome = run(query, policy="fallback_only", timeout=TIMEOUT_SECONDS, surface="cli")
        except Exception as e:
            print(f"  ERROR: {e}")
            outcome = None

        wall_ms = (time.time() - t0) * 1000
        actual_route = outcome.route if outcome else "ERROR"
        exec_ms = getattr(outcome, "execution_time_ms", None)
        profile = outcome.metadata.get("latency_profile", {}) if outcome else {}

        result.actual_routes.append(actual_route)
        result.wall_times_ms.append(round(wall_ms, 2))
        result.execution_times_ms.append(exec_ms)
        result.stage_profiles.append(profile)

    return result


def print_summary(results: list[QueryResult]) -> None:
    print("\n" + "=" * 80)
    print("  END-TO-END LATENCY BENCHMARK SUMMARY")
    print("=" * 80)
    print(f"  {'Mode':<12} {'Median':>8} {'Min':>8} {'Max':>8} {'Acc':>5} {'Warm?':>6}  Query")
    print("-" * 80)

    for r in results:
        acc = f"{r.route_accuracy:.0%}" if r.route_accuracy == 1.0 else f"{r.route_accuracy:.0%}!"
        warm = "YES" if r.is_warm else "NO"
        print(
            f"  {r.category:<12} {r.median_wall_ms:>7.1f}ms {r.min_wall_ms:>7.1f}ms "
            f"{r.max_wall_ms:>7.1f}ms {acc:>5} {warm:>6}  {r.query[:40]}"
        )

    print("-" * 80)

    # -----------------------------------------------------------------
    #  Stage profile stats — split cold (model-load) vs warm (cached)
    # -----------------------------------------------------------------
    def _is_model_load(prof: dict) -> bool:
        """Heuristic: route_ms > 500 indicates embedding model loading."""
        return prof.get("route_ms", 0) > 500

    warm_profiles: list[dict] = []
    cold_profiles: list[dict] = []
    warm_walls: list[float] = []
    cold_walls: list[float] = []

    for r in results:
        if r.route_accuracy < 1.0:
            continue
        for i, prof in enumerate(r.stage_profiles):
            if _is_model_load(prof):
                cold_profiles.append(prof)
                cold_walls.append(r.wall_times_ms[i])
            else:
                warm_profiles.append(prof)
                warm_walls.append(r.wall_times_ms[i])

    # -----------------------------------------------------------------
    #  Per-mode breakdown (cached modes vs live-data modes)
    # -----------------------------------------------------------------
    print("\n  PER-MODE BREAKDOWN:")
    print("  ─────────────────────────────────────────────────────────────────────")
    for r in results:
        if r.route_accuracy < 1.0:
            continue
        warm_walls = [r.wall_times_ms[i] for i, p in enumerate(r.stage_profiles) if not _is_model_load(p)]
        cold_walls = [r.wall_times_ms[i] for i, p in enumerate(r.stage_profiles) if _is_model_load(p)]
        tag = "cached" if r.category in ("LOCAL", "AUGMENTED") else "live API"
        line = f"  {r.category:<12} {tag:<9}  wall={statistics.median(warm_walls):>7.1f}ms"
        if cold_walls:
            line += f"  (cold={statistics.median(cold_walls):.0f}ms)"
        print(line)
        # Show stage medians for this mode
        warm_profs = [p for p in r.stage_profiles if not _is_model_load(p)]
        if warm_profs:
            for sk in ["classify_ms", "route_ms", "provider_resolve_ms", "context_build_ms", "execute_ms"]:
                vals = [p.get(sk, 0) for p in warm_profs]
                med = statistics.median(vals)
                if med > 0:
                    print(f"                 └─ {sk[:-3]:<15} {med:>6.1f}ms")

    # -----------------------------------------------------------------
    #  Optimization priorities
    # -----------------------------------------------------------------
    print("\n  OPTIMIZATION PRIORITIES:")
    print("  ─────────────────────────────────────────────────────────────────────")

    has_cold = len(cold_profiles) > 0
    priority = 1

    if has_cold:
        cold_route_med = statistics.median([p.get("route_ms", 0) for p in cold_profiles])
        print(f"  {priority}. PRE-LOAD EMBEDDING MODEL")
        print(f"     → route_ms={cold_route_med:.0f} on first call (ModernBERT load)")
        print("     → Initialize router at startup so first user query isn't penalized")
        priority += 1

    # Live API modes with high latency
    ext_slow: list[tuple[str, float]] = []
    for r in results:
        if r.category in ("WEATHER", "TIME", "NEWS") and r.route_accuracy == 1.0:
            warm_walls = [r.wall_times_ms[i] for i, p in enumerate(r.stage_profiles) if not _is_model_load(p)]
            if warm_walls:
                ext_slow.append((r.category, statistics.median(warm_walls)))
    ext_slow.sort(key=lambda x: x[1], reverse=True)

    for cat, med in ext_slow:
        print(f"  {priority}. ADD SHORT-TTL CACHE FOR {cat}")
        print(f"     → median={med:.0f}ms dominated by external API latency")
        print(f"     → Cache identical queries for 30–60s; pipeline overhead is only ~30ms")
        priority += 1

    # Pipeline health check
    pipe_overhead = []
    for r in results:
        for p in r.stage_profiles:
            if not _is_model_load(p):
                oh = sum(p.get(sk, 0) for sk in ["classify_ms", "route_ms", "provider_resolve_ms", "context_build_ms"])
                pipe_overhead.append(oh)
    if pipe_overhead:
        pipe_med = statistics.median(pipe_overhead)
        if pipe_med <= 50:
            print(f"  {priority}. PIPELINE IS LEAN")
            print(f"     → Routing overhead median={pipe_med:.0f}ms — no optimization needed")
        else:
            print(f"  {priority}. INVESTIGATE PIPELINE OVERHEAD")
            print(f"     → Routing overhead median={pipe_med:.0f}ms — higher than expected")

    print("=" * 80)


def main() -> None:
    print("Local Lucy V8 — End-to-End Latency Benchmark")
    print(f"Runs per query: {RUNS_PER_QUERY} | Timeout: {TIMEOUT_SECONDS}s")
    print("-" * 80)

    results: list[QueryResult] = []

    for category, query, expected in BENCHMARK_QUERIES:
        print(f"Benchmarking [{category}]: {query!r}")
        result = benchmark_query(category, query, expected)
        results.append(result)
        print(f"  Routes: {result.actual_routes} | Median: {result.median_wall_ms:.1f}ms")

    print_summary(results)

    # Save JSON report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "runs_per_query": RUNS_PER_QUERY,
        "timeout_seconds": TIMEOUT_SECONDS,
        "results": [r.to_dict() for r in results],
    }
    with open(REPORT_PATH, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {REPORT_PATH}")


if __name__ == "__main__":
    main()
