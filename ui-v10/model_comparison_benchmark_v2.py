#!/usr/bin/env python3
"""
Model Comparison Benchmark v2 — Clean Slate

Unloads Ollama completely before each model test to ensure fair cold-start
comparison. Measures both cold-start (first query after load) and warm
performance.

Models tested:
  - local-lucy-llama31 (llama3.1 8B, default)
  - local-lucy        (qwen3:14b, standard)
  - local-lucy-fast   (qwen3:14b, optimized)
  - local-lucy-mistral (mistral-nemo 12B)
"""
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SNAPSHOT_ROOT = Path("/home/mike/lucy-v10")
RUNTIME_NS = Path("/home/mike/.codex-api-home/lucy/runtime-v10")
REQUEST_TOOL = SNAPSHOT_ROOT / "tools/runtime_request.py"
REPORT_FILE = Path.home() / "Desktop" / f"lucy_v10_model_benchmark_clean_{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.json"

MODELS = [
    ("local-lucy-llama31", "llama3.1 8B default"),
    ("local-lucy",         "qwen3:14b standard"),
    ("local-lucy-fast",    "qwen3:14b optimized"),
    ("local-lucy-mistral", "mistral-nemo 12B"),
]

PROMPTS = [
    "What is Ohm's law?",
    "Explain entropy in simple terms.",
    "What does a 6205 bearing number mean?",
    "What is the difference between AC and DC?",
    "Give me a short chicken soup tip.",
]

RUNS_PER_PROMPT = 3
UNLOAD_WAIT_S = 15  # Time for Ollama to fully unload from VRAM

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def unload_ollama_all():
    """Force Ollama to unload ALL models from GPU memory."""
    try:
        # unload by requesting a non-existent model with keep_alive=0
        subprocess.run(
            ["curl", "-s", "-X", "POST", "http://127.0.0.1:11434/api/generate",
             "-d", '{"model":"__unload__","prompt":"","keep_alive":0,"stream":false}'],
            capture_output=True, timeout=10
        )
    except Exception:
        pass
    # Also kill any whisper-server to free VRAM
    try:
        subprocess.run(["pkill", "-f", "whisper-server"], capture_output=True, timeout=5)
    except Exception:
        pass


def get_vram():
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=False
        )
        return int(r.stdout.strip().split("\n")[0])
    except Exception:
        return None


def run_query(prompt, model, timeout=130):
    env = os.environ.copy()
    env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(SNAPSHOT_ROOT)
    env["LUCY_UI_ROOT"] = str(SNAPSHOT_ROOT / "ui-v10")
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(RUNTIME_NS)
    env["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
    env["LUCY_MODEL"] = model
    env["LUCY_LOCAL_MODEL"] = model
    env["LUCY_LOCAL_REPEAT_CACHE"] = "false"

    start = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(REQUEST_TOOL), "submit", "--text", prompt],
            capture_output=True, text=True, timeout=timeout, env=env,
            cwd=str(SNAPSHOT_ROOT)
        )
        elapsed = time.time() - start
        if r.stdout:
            try:
                d = json.loads(r.stdout)
                return elapsed, d.get("accepted", False), d.get("error", "")
            except json.JSONDecodeError:
                return elapsed, False, "json_parse"
        return elapsed, False, "empty"
    except subprocess.TimeoutExpired:
        return timeout, False, "timeout"
    except Exception as e:
        return 0.0, False, str(e)


def benchmark_one(model_alias, model_label):
    log(f"{'='*60}")
    log(f"MODEL: {model_alias} ({model_label})")
    log(f"{'='*60}")

    # STEP 1: Unload everything and wait for clean slate
    log("Unloading all models from Ollama...")
    unload_ollama_all()
    log(f"Waiting {UNLOAD_WAIT_S}s for full VRAM release...")
    time.sleep(UNLOAD_WAIT_S)
    vram_before = get_vram()
    log(f"VRAM before load: {vram_before} MB")

    # STEP 2: Cold-start measurement (first query triggers model load)
    log("Cold-start query (triggers model load)...")
    cold_ttc, cold_ok, cold_err = run_query("What is 2+2?", model_alias)
    log(f"  Cold-start TTC={cold_ttc:.2f}s {'✓' if cold_ok else '✗ ' + cold_err}")
    time.sleep(2)

    # STEP 3: Warm-up (not recorded)
    log("Warm-up query...")
    w_ttc, w_ok, w_err = run_query("What is 2+2?", model_alias)
    log(f"  Warm-up TTC={w_ttc:.2f}s {'✓' if w_ok else '✗ ' + w_err}")
    time.sleep(2)

    # STEP 4: Recorded runs
    raw = []
    for prompt in PROMPTS:
        log(f"Prompt: '{prompt}'")
        for run in range(1, RUNS_PER_PROMPT + 1):
            ttc, ok, err = run_query(prompt, model_alias)
            raw.append({"prompt": prompt, "run": run, "ttc": ttc, "accepted": ok, "error": err})
            status = "✓" if ok else f"✗ ({err[:40]})"
            log(f"  Run {run}: TTC={ttc:.2f}s {status}")
            time.sleep(1)

    vram_after = get_vram()
    log(f"VRAM during run: {vram_after} MB")

    # Statistics
    per_prompt = {}
    for p in PROMPTS:
        times = [r["ttc"] for r in raw if r["prompt"] == p and r["accepted"] and r["ttc"] > 0]
        if times:
            per_prompt[p] = {
                "median": round(statistics.median(times), 2),
                "mean": round(statistics.mean(times), 2),
                "min": round(min(times), 2),
                "max": round(max(times), 2),
                "stdev": round(statistics.stdev(times), 2) if len(times) > 1 else 0.0,
            }

    all_times = [r["ttc"] for r in raw if r["accepted"] and r["ttc"] > 0]
    failed = sum(1 for r in raw if not r["accepted"])

    return {
        "model_alias": model_alias,
        "model_label": model_label,
        "cold_start_ttc": round(cold_ttc, 2),
        "cold_start_accepted": cold_ok,
        "vram_before_mb": vram_before,
        "vram_during_mb": vram_after,
        "total_queries": len(raw),
        "successful": len(all_times),
        "failed": failed,
        "overall_median": round(statistics.median(all_times), 2) if all_times else None,
        "overall_mean": round(statistics.mean(all_times), 2) if all_times else None,
        "overall_min": round(min(all_times), 2) if all_times else None,
        "overall_max": round(max(all_times), 2) if all_times else None,
        "per_prompt": per_prompt,
        "raw": raw,
    }


def main():
    log("=" * 60)
    log("LOCAL LUCY V10 — CLEAN SLATE MODEL COMPARISON")
    log("=" * 60)
    log(f"Models: {', '.join(m[0] for m in MODELS)}")
    log(f"Prompts: {len(PROMPTS)} x {RUNS_PER_PROMPT} runs")
    log(f"Cache: DISABLED")
    log(f"Unload wait: {UNLOAD_WAIT_S}s between models")
    log(f"Report: {REPORT_FILE}")
    log("=" * 60)

    results = []
    for alias, label in MODELS:
        r = benchmark_one(alias, label)
        results.append(r)
        log(f"Summary for {alias}: median={r['overall_median']}s, mean={r['overall_mean']}s, failed={r['failed']}/{r['total_queries']}")

    # Report
    report = {
        "timestamp": datetime.now().isoformat(),
        "models": [m[0] for m in MODELS],
        "prompts": PROMPTS,
        "runs_per_prompt": RUNS_PER_PROMPT,
        "unload_wait_s": UNLOAD_WAIT_S,
        "results": results,
    }
    with open(REPORT_FILE, "w") as f:
        json.dump(report, f, indent=2)

    log("=" * 60)
    log("FINAL COMPARISON (clean slate — cold start + warm runs)")
    log("=" * 60)
    log(f"{'Model':<25} {'Cold':<8} {'Median':<8} {'Mean':<8} {'Min':<8} {'Max':<8} {'VRAM':<8}")
    log("-" * 80)
    for r in results:
        log(f"{r['model_alias']:<25} {r['cold_start_ttc']:<8} {r['overall_median'] or 'N/A':<8} {r['overall_mean'] or 'N/A':<8} {r['overall_min'] or 'N/A':<8} {r['overall_max'] or 'N/A':<8} {r.get('vram_during_mb') or 'N/A':<8}")

    log(f"\nFull report: {REPORT_FILE}")


if __name__ == "__main__":
    main()
