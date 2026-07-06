#!/usr/bin/env python3
"""Run a focused question barrage through Local Lucy and capture outcomes.

Usage:
    cd ~/lucy-v10
    source .env
    python3 tools/router_py/run_barrage.py --output /tmp/lucy_barrage.jsonl

The script bypasses the HMI and calls execute_plan_python directly for speed.
It records: question, route, provider, model, response text, latency, metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.main import execute_plan_python


# Focused pilot barrage covering the main route/intent categories.
# Keep each question short enough for stable routing but representative.
PILOT_BARRAGE: list[dict] = [
    {"id": "stable_fact", "category": "general", "question": "What is the capital of France?"},
    {"id": "current_news", "category": "news", "question": "What is the latest Israeli news?"},
    {"id": "weather", "category": "weather", "question": "What is the weather in Tel Aviv?"},
    {"id": "time", "category": "time", "question": "What time is it in New York?"},
    {
        "id": "finance_stock",
        "category": "finance",
        "question": "What is the current price of Apple stock?",
    },
    {
        "id": "finance_fx",
        "category": "finance",
        "question": "What is the EUR to USD exchange rate?",
    },
    {"id": "medical", "category": "medical", "question": "What are the symptoms of dehydration?"},
    {
        "id": "coding",
        "category": "coding",
        "question": "Write a Python function that reverses a string.",
    },
    {
        "id": "reasoning",
        "category": "reasoning",
        "question": "If it takes 5 machines 5 minutes to make 5 widgets, how long does it take 100 machines to make 100 widgets?",
    },
    {
        "id": "creative",
        "category": "creative",
        "question": "Write a short poem about a rainy evening.",
    },
    {"id": "meta_capabilities", "category": "meta", "question": "What can you do?"},
    {"id": "meta_identity", "category": "meta", "question": "Who are you?"},
]


def run_one(question: str, timeout: int = 130) -> dict:
    """Run a single query and return a compact outcome dict."""
    start = time.monotonic()
    outcome = execute_plan_python(
        question=question,
        policy="fallback_only",
        timeout=timeout,
        surface="barrage",
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "status": outcome.status,
        "route": outcome.route,
        "provider": outcome.provider,
        "provider_usage_class": outcome.provider_usage_class,
        "intent_family": outcome.intent_family,
        "confidence": outcome.confidence,
        "execution_time_ms": elapsed_ms,
        "outcome_code": outcome.outcome_code,
        "error_message": outcome.error_message,
        "response_text": outcome.response_text,
        "metadata": outcome.metadata or {},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Local Lucy barrage pilot")
    parser.add_argument("--output", type=Path, default=Path("/tmp/lucy_barrage_pilot.jsonl"))
    parser.add_argument("--timeout", type=int, default=130)
    args = parser.parse_args()

    results: list[dict] = []
    for item in PILOT_BARRAGE:
        print(f"[{item['id']}] {item['question']}", flush=True)
        try:
            outcome = run_one(item["question"], timeout=args.timeout)
        except Exception as e:
            outcome = {"status": "exception", "error_message": str(e)}
        record = {
            "id": item["id"],
            "category": item["category"],
            "question": item["question"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "outcome": outcome,
        }
        results.append(record)
        with open(args.output, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"  -> {outcome.get('route', 'N/A')} | {outcome.get('status', 'N/A')} | {outcome.get('execution_time_ms', 'N/A')} ms",
            flush=True,
        )

    print(f"\nBarrage complete. {len(results)} questions. Output: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
