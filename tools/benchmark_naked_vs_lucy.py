#!/usr/bin/env python3
"""Benchmark: naked Ollama vs Local Lucy v10/11.

Usage:
    cd ~/lucy-v10
    source .env
    python3 tools/benchmark_naked_vs_lucy.py

Reports total latency and throughput for the heaviest installed model.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from router_py.main import execute_plan_python  # noqa: E402

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
PROMPT = "Explain in one sentence what photosynthesis is."
MAX_TOKENS = 60


def model_exists(name: str) -> bool:
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return any(
                m["name"] == name or m["name"].startswith(name + ":")
                for m in data.get("models", [])
            )
    except Exception as e:
        print(f"Could not list models: {e}")
        return False


def unload_model(name: str) -> None:
    try:
        body = json.dumps({"model": name, "keep_alive": 0}).encode()
        req = urllib.request.Request(OLLAMA_URL, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass


def benchmark_naked(model: str) -> dict:
    unload_model(model)
    time.sleep(1)

    body = json.dumps(
        {
            "model": model,
            "prompt": PROMPT,
            "stream": False,
            "options": {"num_predict": MAX_TOKENS, "temperature": 0.0},
        }
    ).encode()

    start = time.perf_counter()
    req = urllib.request.Request(OLLAMA_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return {"error": str(e)}
    elapsed = time.perf_counter() - start

    tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)
    return {
        "model": model,
        "total_seconds": elapsed,
        "response": data.get("response", "")[:120],
        "prompt_tokens": data.get("prompt_eval_count", 0),
        "generated_tokens": data.get("eval_count", 0),
        "tokens_per_second": tokens / elapsed if elapsed else 0,
    }


def benchmark_lucy(model: str) -> dict:
    unload_model(model)
    time.sleep(1)

    start = time.perf_counter()
    try:
        result = execute_plan_python(
            question=PROMPT,
            policy="fallback_only",
            timeout=300,
            surface="benchmark",
            model=model,
        )
    except Exception as e:
        return {"error": str(e)}
    elapsed = time.perf_counter() - start

    return {
        "model": model,
        "total_seconds": elapsed,
        "route": result.route,
        "provider": result.provider,
        "response": (result.response_text or "")[:120],
    }


def pick_heaviest_model() -> str:
    # Prefer qwen3:30b if installed; otherwise qwen3:14b; otherwise local-lucy-fast
    candidates = ["qwen3:30b", "qwen3:14b", "local-lucy-fast:latest", "local-lucy:latest"]
    for c in candidates:
        if model_exists(c):
            return c
    return "local-lucy:latest"


def main() -> int:
    model = pick_heaviest_model()
    print(f"Benchmarking model: {model}")
    print(f"Prompt: {PROMPT!r}\n")

    print("--- Naked Ollama ---")
    naked = benchmark_naked(model)
    if "error" in naked:
        print(f"FAILED: {naked['error']}")
    else:
        print(f"Total: {naked['total_seconds']:.2f}s")
        print(f"Prompt tokens: {naked['prompt_tokens']}, Generated: {naked['generated_tokens']}")
        print(f"Throughput: {naked['tokens_per_second']:.2f} tok/s")
        print(f"Response: {naked['response']!r}\n")

    print("--- Local Lucy v10/11 ---")
    lucy = benchmark_lucy(model)
    if "error" in lucy:
        print(f"FAILED: {lucy['error']}")
    else:
        print(f"Total: {lucy['total_seconds']:.2f}s")
        print(f"Route: {lucy['route']}, Provider: {lucy['provider']}")
        print(f"Response: {lucy['response']!r}\n")

    if "error" not in naked and "error" not in lucy:
        overhead = lucy["total_seconds"] - naked["total_seconds"]
        ratio = lucy["total_seconds"] / naked["total_seconds"] if naked["total_seconds"] else 0
        print(f"Local Lucy overhead: {overhead:.2f}s ({ratio:.2f}x naked)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
