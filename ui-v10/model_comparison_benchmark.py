#!/usr/bin/env python3
"""
Model Comparison Benchmark: Llama 3.1 vs Gemma 4

Tests LOCAL-route text latency across the allowed model configurations:
  - local-lucy-llama31 (llama3.1 8B, default)
  - local-lucy-gemma4  (gemma4 12B reasoning)

Measures:
  - Time-to-completion (TTC) per prompt
  - Cold-start vs warm-start latency
  - Median/min/max per model
  - VRAM footprint (via nvidia-smi when available)

Usage:
    cd <project-root>/ui-v10
    ../../ui-v10/.venv/bin/python model_comparison_benchmark.py
"""

import json
import os
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_NS = Path(
    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    or (Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
REQUEST_TOOL = SNAPSHOT_ROOT / "tools/runtime_request.py"
REPORT_FILE = (
    Path.home()
    / "Desktop"
    / f"lucy_v10_model_benchmark_{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.json"
)

MODELS = [
    ("auto", "automatic selector (Llama/Gemma per query)"),
    ("local-lucy-llama31", "llama3.1 8B default"),
    ("local-lucy-gemma4", "gemma4 12B reasoning"),
]

PROMPTS = [
    "What is Ohm's law?",
    "Explain entropy in simple terms.",
    "What does a 6205 bearing number mean?",
    "What is the difference between AC and DC?",
    "Give me a short chicken soup tip.",
]

WARMUP_PROMPT = "What is 2+2?"
RUNS_PER_PROMPT = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    prompt: str
    model: str
    run: int
    ttc: float
    accepted: bool
    error: str = ""


def get_vram_usage() -> Optional[float]:
    """Return Ollama VRAM usage in MB, or None if unavailable."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return None
        total_mb = 0.0
        for line in result.stdout.strip().splitlines():
            parts = line.strip().split(",")
            if len(parts) >= 2:
                try:
                    total_mb += float(parts[1].strip())
                except ValueError:
                    pass
        return total_mb
    except Exception:
        return None


def unload_ollama_models() -> None:
    """Ask Ollama to unload all models to get clean cold-start numbers."""
    try:
        # Sending empty prompt with keep_alive=0 unloads the model
        subprocess.run(
            [
                "curl",
                "-s",
                "http://127.0.0.1:11434/api/generate",
                "-d",
                '{"model":"local-lucy","prompt":"","keep_alive":0,"stream":false}',
            ],
            capture_output=True,
            timeout=10,
        )
        time.sleep(2)
    except Exception:
        pass


def run_query(prompt: str, model: str, timeout: int = 130) -> tuple[float, bool, str]:
    """Run a single query through the full Lucy pipeline."""
    env = os.environ.copy()
    env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(SNAPSHOT_ROOT)
    env["LUCY_UI_ROOT"] = str(SNAPSHOT_ROOT / "ui-v10")
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(RUNTIME_NS)
    env["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
    if model == "auto":
        env["LUCY_MODEL"] = "auto"
        env["LUCY_LOCAL_MODEL"] = "local-lucy-llama31"
    else:
        env["LUCY_MODEL"] = model
        env["LUCY_LOCAL_MODEL"] = model
    env["LUCY_LOCAL_REPEAT_CACHE"] = "false"  # Disable cache for fair comparison

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, str(REQUEST_TOOL), "submit", "--text", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(SNAPSHOT_ROOT),
        )
        elapsed = time.time() - start

        if result.stdout:
            try:
                data = json.loads(result.stdout)
                accepted = data.get("accepted", False)
                error = data.get("error", "")
                return elapsed, accepted, error
            except json.JSONDecodeError:
                return elapsed, False, "json_parse_error"
        else:
            return elapsed, False, "empty_response"
    except subprocess.TimeoutExpired:
        return timeout, False, "timeout"
    except Exception as e:
        return 0.0, False, str(e)


def benchmark_model(model_alias: str, model_label: str) -> dict:
    """Run full benchmark for one model."""
    print(f"\n{'=' * 70}")
    print(f"MODEL: {model_alias} ({model_label})")
    print(f"{'=' * 70}")

    results: list[RunResult] = []

    # Warm-up run (not recorded)
    print(f"  Warm-up: '{WARMUP_PROMPT}'")
    ttc, accepted, error = run_query(WARMUP_PROMPT, model_alias)
    status = "✓" if accepted else f"✗ ({error[:40]})"
    print(f"    Warm-up TTC={ttc:.2f}s {status}")
    time.sleep(1)

    # Recorded runs
    for prompt in PROMPTS:
        print(f"\n  Prompt: '{prompt}'")
        for run in range(1, RUNS_PER_PROMPT + 1):
            ttc, accepted, error = run_query(prompt, model_alias)
            results.append(RunResult(prompt, model_alias, run, ttc, accepted, error))
            status = "✓" if accepted else f"✗ ({error[:40]})"
            print(f"    Run {run}: TTC={ttc:.2f}s {status}")
            time.sleep(1)

    # VRAM snapshot
    vram_mb = get_vram_usage()
    if vram_mb:
        print(f"  VRAM: {vram_mb:.0f} MB")

    # Per-prompt statistics
    per_prompt = {}
    for prompt in PROMPTS:
        times = [r.ttc for r in results if r.prompt == prompt and r.accepted and r.ttc > 0]
        if times:
            per_prompt[prompt] = {
                "median": round(statistics.median(times), 2),
                "mean": round(statistics.mean(times), 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2),
                "stdev": round(statistics.stdev(times), 2) if len(times) > 1 else 0.0,
            }

    # Overall statistics
    all_times = [r.ttc for r in results if r.accepted and r.ttc > 0]
    failed = sum(1 for r in results if not r.accepted)

    summary = {
        "model_alias": model_alias,
        "model_label": model_label,
        "total_queries": len(results),
        "successful": len(all_times),
        "failed": failed,
        "vram_mb": vram_mb,
        "overall_median": round(statistics.median(all_times), 2) if all_times else None,
        "overall_mean": round(statistics.mean(all_times), 2) if all_times else None,
        "overall_min": round(min(all_times), 2) if all_times else None,
        "overall_max": round(max(all_times), 2) if all_times else None,
        "per_prompt": per_prompt,
        "raw_results": [
            {
                "prompt": r.prompt,
                "run": r.run,
                "ttc": round(r.ttc, 2),
                "accepted": r.accepted,
                "error": r.error,
            }
            for r in results
        ],
    }

    print(
        f"\n  Summary: median={summary['overall_median']}s, mean={summary['overall_mean']}s, "
        f"failed={failed}/{len(results)}"
    )
    return summary


def main():
    print("=" * 70)
    print("LOCAL LUCY V10 — MODEL COMPARISON BENCHMARK")
    print("=" * 70)
    print(f"Started: {datetime.now().strftime('%H:%M:%S')}")
    print(f"Models: {', '.join(m[0] for m in MODELS)}")
    print(f"Prompts: {len(PROMPTS)}")
    print(f"Runs per prompt: {RUNS_PER_PROMPT}")
    print("Cache: DISABLED for fair comparison")
    print(f"Report: {REPORT_FILE}")
    print("=" * 70)

    # Check Ollama is reachable
    try:
        result = subprocess.run(
            ["curl", "-s", "http://127.0.0.1:11434/api/tags"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            print("ERROR: Ollama not reachable at :11434")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: Cannot reach Ollama: {e}")
        sys.exit(1)

    all_results = []

    for model_alias, model_label in MODELS:
        # Unload previous model to get clean cold-start for first prompt
        print("\n[Unloading previous models...]")
        unload_ollama_models()
        time.sleep(3)

        result = benchmark_model(model_alias, model_label)
        all_results.append(result)

    # Generate report
    report = {
        "timestamp": datetime.now().isoformat(),
        "models_tested": [m[0] for m in MODELS],
        "prompts": PROMPTS,
        "runs_per_prompt": RUNS_PER_PROMPT,
        "cache_enabled": False,
        "results": all_results,
    }

    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    # Print final comparison table
    print("\n" + "=" * 70)
    print("FINAL COMPARISON")
    print("=" * 70)
    print(f"{'Model':<25} {'Median':<10} {'Mean':<10} {'Min':<10} {'Max':<10} {'VRAM MB':<10}")
    print("-" * 70)
    for r in all_results:
        vram = f"{r['vram_mb']:.0f}" if r.get("vram_mb") else "N/A"
        print(
            f"{r['model_alias']:<25} "
            f"{r['overall_median'] or 'N/A':<10} "
            f"{r['overall_mean'] or 'N/A':<10} "
            f"{r['overall_min'] or 'N/A':<10} "
            f"{r['overall_max'] or 'N/A':<10} "
            f"{vram:<10}"
        )

    print(f"\nFull report saved to: {REPORT_FILE}")
    print("=" * 70)


if __name__ == "__main__":
    main()
