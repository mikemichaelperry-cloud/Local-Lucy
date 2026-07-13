#!/usr/bin/env python3
"""Latency benchmark for Local Lucy routing + local model generation.

Run this before and after changes to quantify latency impact. It reports:
- Routing latency (classify + policy router)
- Local model first-token / total latency per model
"""

from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

from router_py.classify import classify_intent, select_route
from router_py.local_answer import LocalAnswer, LocalAnswerConfig

QUERIES = [
    "What is the capital of Japan?",
    "What time is it in Tokyo?",
    "What's the weather in New York?",
    "Latest news on Israel Gaza conflict.",
    "What is the current price of AAPL?",
    "What is the standard dosage of amoxicillin for adults?",
    "Translate 'hello' to French.",
    "Write a Python function to reverse a string.",
    "Tell me a joke.",
    "What did we discuss earlier?",
]

MODELS = [
    "local-lucy-llama31",
    "gemma4:12b-it-qat",
]


def bench_routing() -> dict[str, float]:
    times: list[float] = []
    for query in QUERIES:
        t0 = time.perf_counter()
        classification = classify_intent(query)
        select_route(classification, query=query)
        times.append((time.perf_counter() - t0) * 1000)
    return {
        "mean_ms": statistics.mean(times),
        "min_ms": min(times),
        "max_ms": max(times),
    }


async def bench_model(model: str) -> dict[str, float | str]:
    config = LocalAnswerConfig.from_env()
    config.model = model
    config.cache_enabled = False
    config.temperature = 0.0
    config.seed = 7

    total_times: list[float] = []
    errors = 0
    async with LocalAnswer(config) as answer:
        for query in QUERIES[:3]:  # 3 queries per model to keep runtime sane
            t0 = time.perf_counter()
            try:
                result = await answer.generate_answer(query=query, route_mode="LOCAL")
                if not result.text:
                    errors += 1
            except Exception:
                errors += 1
            total_times.append((time.perf_counter() - t0) * 1000)

    return {
        "model": model,
        "mean_total_ms": statistics.mean(total_times) if total_times else 0,
        "min_total_ms": min(total_times) if total_times else 0,
        "max_total_ms": max(total_times) if total_times else 0,
        "errors": errors,
    }


async def main() -> int:
    print("Local Lucy Latency Benchmark")
    print("=" * 60)

    # Trigger the same startup warmups the execution engine uses, so the
    # measured routing latency reflects steady-state performance rather than
    # the one-time MiniLM import/load cost.
    LocalAnswer.warmup_ollama()
    # Force-load the semantic classifier here so routing measurements are in
    # steady state (in production this happens in the background while the
    # user types).
    try:
        from router_py.policy import _get_semantic_model

        _get_semantic_model()
    except Exception:
        pass

    routing = bench_routing()
    print("\nRouting (classify + policy router):")
    print(
        f"  mean={routing['mean_ms']:.1f}ms  min={routing['min_ms']:.1f}ms  max={routing['max_ms']:.1f}ms"
    )

    print("\nLocal model generation (3 queries each):")
    print(f"{'Model':<30} {'Mean':>10} {'Min':>10} {'Max':>10} {'Errors':>8}")
    for model in MODELS:
        result = await bench_model(model)
        print(
            f"{result['model']:<30} "
            f"{result['mean_total_ms']:>10.1f} "
            f"{result['min_total_ms']:>10.1f} "
            f"{result['max_total_ms']:>10.1f} "
            f"{result['errors']:>8}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
