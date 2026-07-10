#!/usr/bin/env python3
"""
Local Lucy v8 — Comprehensive Stress & End-to-End Validation Test

Tests all routing paths, monitors resources, validates correctness.
Run: cd ~/lucy-v10/ui-v10 && python3 comprehensive_stress_test.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "app"))
sys.path.insert(0, str(Path.home() / "lucy-v10" / "models" / "router"))

os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v10"))
os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")
os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
os.environ.setdefault("LUCY_SESSION_MEMORY", "1")

from app.backend import execute_plan_python


@dataclass
class TestResult:
    query: str
    route: str
    status: str
    response: str
    latency_ms: float
    ephemeral: bool = False
    error: str = ""
    correct: bool = False


@dataclass
class ResourceSnapshot:
    timestamp: float
    gpu_mem_used_mb: int | None
    gpu_mem_total_mb: int | None
    system_ram_used_mb: int
    system_ram_total_mb: int


def get_gpu_memory() -> tuple[int, int] | tuple[None, None]:
    """Returns (used_mb, total_mb) or (None, None) if no GPU."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            used, total = out.stdout.strip().split(",")
            return int(used.strip()), int(total.strip())
    except Exception:
        pass
    return None, None


def get_system_memory() -> tuple[int, int]:
    """Returns (used_mb, total_mb)."""
    with open("/proc/meminfo") as f:
        lines = f.readlines()
    mem_total = 0
    mem_available = 0
    for line in lines:
        if line.startswith("MemTotal:"):
            mem_total = int(line.split()[1]) // 1024
        elif line.startswith("MemAvailable:"):
            mem_available = int(line.split()[1]) // 1024
    return mem_total - mem_available, mem_total


def snapshot(label: str = "") -> ResourceSnapshot:
    gpu_used, gpu_total = get_gpu_memory()
    ram_used, ram_total = get_system_memory()
    snap = ResourceSnapshot(
        timestamp=time.time(),
        gpu_mem_used_mb=gpu_used,
        gpu_mem_total_mb=gpu_total,
        system_ram_used_mb=ram_used,
        system_ram_total_mb=ram_total,
    )
    if label:
        print(
            f"  [{label}] GPU: {gpu_used or '?'} / {gpu_total or '?'} MB | RAM: {ram_used} / {ram_total} MB"
        )
    return snap


def run_query(
    query: str, expected_route: str | None = None, expected_contains: str | None = None
) -> TestResult:
    """Execute a single query and return results."""
    t0 = time.time()
    try:
        result = execute_plan_python(query)
        latency = (time.time() - t0) * 1000
        response = result.response_text or ""
        correct = True
        if expected_route and result.route != expected_route:
            correct = False
        if expected_contains and expected_contains.lower() not in response.lower():
            correct = False
        return TestResult(
            query=query,
            route=result.route,
            status=result.status,
            response=response[:300],
            latency_ms=latency,
            ephemeral=getattr(result, "ephemeral", False),
            error=result.error_message or "",
            correct=correct,
        )
    except Exception as e:
        return TestResult(
            query=query,
            route="ERROR",
            status="failed",
            response="",
            latency_ms=(time.time() - t0) * 1000,
            error=str(e),
            correct=False,
        )


def print_result(r: TestResult) -> None:
    status = "✅" if r.correct and r.status == "completed" else "❌"
    eph = "[E]" if r.ephemeral else "   "
    print(f"  {status} [{r.route:8s}] {eph} {r.latency_ms:6.0f}ms | {r.query[:55]}")
    if r.error:
        print(f"      ERROR: {r.error[:80]}")
    if not r.correct and r.status == "completed":
        print(f"      RESPONSE: {r.response[:80]}...")


def main() -> int:
    print("=" * 80)
    print("LOCAL LUCY V8 — COMPREHENSIVE STRESS & E2E VALIDATION")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 80)

    # Baseline resources
    print("\n📊 BASELINE RESOURCES")
    baseline = snapshot("baseline")

    # Warm-up: first query loads ModernBERT
    print("\n🔥 WARM-UP (loading router)...")
    run_query("What is 2+2?")
    time.sleep(1)
    snapshot("post-warmup")

    results: list[TestResult] = []

    # ================================================================
    # BATCH 1: LOCAL ROUTE (math, identity, general knowledge)
    # ================================================================
    print("\n🧪 BATCH 1: LOCAL ROUTE (15 queries)")
    local_tests = [
        ("What is 2+2?", "LOCAL", "4"),
        ("What is 15 times 23?", "LOCAL", "345"),
        ("Who are you?", "LOCAL", "Lucy"),
        ("Tell me a joke", "LOCAL", None),
        ("Explain quantum computing", "LOCAL", None),
        ("How do I bake sourdough bread?", "LOCAL", "flour"),
        ("What is the capital of France?", "LOCAL", "Paris"),
        ("Write a haiku about rain", "LOCAL", None),
        ("Translate hello to Japanese", "LOCAL", "konnichiwa"),
        ("What is CRISPR?", "LOCAL", "gene"),
        ("How do I make pancakes?", "LOCAL", "pancake"),
        ("What is the Pythagorean theorem?", "LOCAL", "a²"),
        ("Who invented the telephone?", "LOCAL", "Bell"),
        ("What is the speed of light?", "LOCAL", "299"),
        ("Explain recursion", "LOCAL", "itself"),
    ]
    for q, expected, contains in local_tests:
        r = run_query(q, expected, contains)
        results.append(r)
        print_result(r)

    # ================================================================
    # BATCH 2: TIME ROUTE
    # ================================================================
    print("\n🧪 BATCH 2: TIME ROUTE (5 queries)")
    time_tests = [
        ("What time is it?", "TIME", None),
        ("What time is it in Tokyo?", "TIME", "Tokyo"),
        ("Current time in London", "TIME", "London"),
        ("What time is it in New York?", "TIME", "York"),
        ("Time in Sydney Australia", "TIME", "Sydney"),
    ]
    for q, expected, contains in time_tests:
        r = run_query(q, expected, contains)
        results.append(r)
        print_result(r)

    # ================================================================
    # BATCH 3: WEATHER ROUTE
    # ================================================================
    print("\n🧪 BATCH 3: WEATHER ROUTE (8 queries)")
    weather_tests = [
        ("What is the weather in London?", "WEATHER", "London"),
        ("Whats the current weather in Hadera Israel?", "WEATHER", "Israel"),
        ("Will it rain in Paris tomorrow?", "WEATHER", "Paris"),
        ("Temperature in Tokyo", "WEATHER", "Tokyo"),
        ("Do I need an umbrella in Seattle?", "WEATHER", "Seattle"),
        ("Should I bring a jacket today?", "WEATHER", None),
        ("Weather forecast for New York", "WEATHER", "York"),
        ("Is it sunny in Barcelona?", "WEATHER", "Barcelona"),
    ]
    for q, expected, contains in weather_tests:
        r = run_query(q, expected, contains)
        results.append(r)
        print_result(r)

    # ================================================================
    # BATCH 4: NEWS ROUTE
    # ================================================================
    print("\n🧪 BATCH 4: NEWS ROUTE (5 queries)")
    news_tests = [
        ("What are todays headlines?", "NEWS", None),
        ("Latest news on technology", "NEWS", None),
        ("Breaking news", "NEWS", None),
        ("What happened today?", "NEWS", None),
        ("Current events", "NEWS", None),
    ]
    for q, expected, contains in news_tests:
        r = run_query(q, expected, contains)
        results.append(r)
        print_result(r)

    # ================================================================
    # BATCH 5: AUGMENTED ROUTE (evidence required)
    # ================================================================
    print("\n🧪 BATCH 5: AUGMENTED ROUTE (8 queries)")
    aug_tests = [
        ("What are symptoms of diabetes?", "AUGMENTED", "diabetes"),
        ("Search Wikipedia for Python programming language", "AUGMENTED", "Python"),
        ("What is the treatment for flu?", "AUGMENTED", "flu"),
        ("Tesla stock price", "AUGMENTED", None),
        ("Current NVIDIA stock price", "AUGMENTED", None),
        ("How much is Bitcoin worth?", "AUGMENTED", None),
        ("Latest Supreme Court ruling", "AUGMENTED", None),
        ("What are the side effects of aspirin?", "AUGMENTED", "aspirin"),
    ]
    for q, expected, contains in aug_tests:
        r = run_query(q, expected, contains)
        results.append(r)
        print_result(r)

    # ================================================================
    # BATCH 6: MEMORY PIPELINE
    # ================================================================
    print("\n🧪 BATCH 6: MEMORY PIPELINE (4 queries)")
    # Store
    r1 = run_query("My favorite color is blue", None, None)
    results.append(r1)
    print(f"  {'✅' if r1.status == 'completed' else '❌'} STORE: {r1.query}")
    time.sleep(0.5)
    # Recall
    r2 = run_query("What is my favorite color?", None, None)
    results.append(r2)
    print(f"  {'✅' if r2.status == 'completed' else '❌'} RECALL: {r2.query}")
    print(f"      Response: {r2.response[:80]}...")

    # Store another fact
    r3 = run_query("My dogs name is Max", None, None)
    results.append(r3)
    time.sleep(0.5)
    r4 = run_query("What is my dogs name?", None, None)
    results.append(r4)
    print(f"  {'✅' if r4.status == 'completed' else '❌'} RECALL: {r4.query}")
    print(f"      Response: {r4.response[:80]}...")

    # ================================================================
    # BATCH 7: RAPID-FIRE STRESS (10 queries in quick succession)
    # ================================================================
    print("\n🧪 BATCH 7: RAPID-FIRE STRESS (10 queries, back-to-back)")
    rapid = [
        "What is 5+5?",
        "What time is it?",
        "Weather in London",
        "Who won the World Cup?",
        "Tesla stock",
        "What is gravity?",
        "Tell me a joke",
        "Latest news",
        "Do I need an umbrella?",
        "What is AI?",
    ]
    rapid_results = []
    for q in rapid:
        r = run_query(q)
        rapid_results.append(r)
        status = "✅" if r.status == "completed" else "❌"
        print(f"  {status} [{r.route:8s}] {r.latency_ms:6.0f}ms | {q}")
    results.extend(rapid_results)

    # ================================================================
    # BATCH 8: CACHE VALIDATION (repeat same query 3x)
    # ================================================================
    print("\n🧪 BATCH 8: RESPONSE CACHE (3 identical queries)")
    cache_q = "What is the square root of 144?"
    cache_times = []
    for i in range(3):
        t0 = time.time()
        r = run_query(cache_q, "LOCAL", "12")
        latency = (time.time() - t0) * 1000
        cache_times.append(latency)
        results.append(r)
        print(f"  Run {i+1}: {latency:.0f}ms | route={r.route} | response={r.response[:40]}...")
    if cache_times[2] < cache_times[0] * 0.5:
        print("  ⚡ Cache likely active (3rd query significantly faster)")

    # ================================================================
    # FINAL RESOURCES
    # ================================================================
    print("\n📊 FINAL RESOURCES")
    final = snapshot("final")

    # ================================================================
    # SUMMARY
    # ================================================================
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    completed = [r for r in results if r.status == "completed"]
    failed = [r for r in results if r.status != "completed"]
    correct = [r for r in results if r.correct]
    incorrect = [r for r in results if not r.correct and r.status == "completed"]

    total_latency = sum(r.latency_ms for r in results)
    avg_latency = total_latency / len(results) if results else 0
    min_latency = min(r.latency_ms for r in results) if results else 0
    max_latency = max(r.latency_ms for r in results) if results else 0

    routes = {}
    for r in results:
        routes[r.route] = routes.get(r.route, 0) + 1

    print(f"\nTotal queries:        {len(results)}")
    print(f"Completed:            {len(completed)} ({len(completed)*100//len(results)}%)")
    print(f"Failed:               {len(failed)} ({len(failed)*100//len(results)}%)")
    print(f"Correct (validated):  {len(correct)} ({len(correct)*100//len(results)}%)")
    print(f"Incorrect content:    {len(incorrect)}")
    print("\nLatency:")
    print(f"  Average: {avg_latency:.0f}ms")
    print(f"  Min:     {min_latency:.0f}ms")
    print(f"  Max:     {max_latency:.0f}ms")
    print("\nRoute distribution:")
    for route, count in sorted(routes.items(), key=lambda x: -x[1]):
        print(f"  {route:12s}: {count}")

    # Resource delta
    if baseline.gpu_mem_used_mb is not None and final.gpu_mem_used_mb is not None:
        gpu_delta = final.gpu_mem_used_mb - baseline.gpu_mem_used_mb
        print(
            f"\nGPU memory delta:     {gpu_delta:+d} MB ({baseline.gpu_mem_used_mb} → {final.gpu_mem_used_mb})"
        )
    ram_delta = final.system_ram_used_mb - baseline.system_ram_used_mb
    print(
        f"System RAM delta:     {ram_delta:+d} MB ({baseline.system_ram_used_mb} → {final.system_ram_used_mb})"
    )

    # Failures detail
    if failed:
        print("\n❌ FAILED QUERIES:")
        for r in failed:
            print(f"  [{r.route}] {r.query}")
            print(f"    Error: {r.error[:100]}")

    if incorrect:
        print("\n⚠️  INCORRECT CONTENT:")
        for r in incorrect:
            print(f"  [{r.route}] {r.query}")
            print(f"    Response: {r.response[:100]}...")

    # Overall verdict
    success_rate = len(correct) / len(results) * 100 if results else 0
    print(
        f"\n{'✅' if success_rate >= 90 else '⚠️' if success_rate >= 70 else '❌'} OVERALL: {success_rate:.0f}% success rate"
    )

    # Save report
    report_path = (
        Path.home()
        / ".codex-api-home"
        / "lucy"
        / "runtime-v10"
        / "logs"
        / f"stress_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(
            {
                "timestamp": datetime.now().isoformat(),
                "total_queries": len(results),
                "completed": len(completed),
                "failed": len(failed),
                "correct": len(correct),
                "incorrect": len(incorrect),
                "avg_latency_ms": avg_latency,
                "max_latency_ms": max_latency,
                "routes": routes,
                "gpu_delta_mb": gpu_delta if baseline.gpu_mem_used_mb else None,
                "ram_delta_mb": ram_delta,
                "baseline": vars(baseline),
                "final": vars(final),
                "results": [vars(r) for r in results],
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\n📄 Full report saved to: {report_path}")

    return 0 if success_rate >= 90 else 1


if __name__ == "__main__":
    sys.exit(main())
