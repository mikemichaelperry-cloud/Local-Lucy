#!/usr/bin/env python3
"""
Model Comparison Benchmark v2 — Clean Slate

Unloads Ollama completely before each model test to ensure fair cold-start
comparison. Measures both cold-start (first query after load) and warm
performance.

Models tested:
  - local-lucy-llama31 (llama3.1 8B, default)
  - gemma4:12b-it-qat  (gemma4 12B reasoning/multimodal)
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Runtime setting controlled by --smart-routing CLI flag.
_SMART_ROUTING = "off"

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
    / f"lucy_v10_model_benchmark_clean_{datetime.now().strftime('%Y-%m-%dT%H-%M-%S')}.json"
)

MODELS = [
    ("auto", "automatic selector (Llama/Gemma per query)"),
    ("local-lucy-llama31", "llama3.1 8B default"),
    ("gemma4:12b-it-qat", "gemma4 12B reasoning/multimodal"),
]

PROMPTS = [
    "What is Ohm's law?",
    "Explain entropy in simple terms.",
    "What does a 6205 bearing number mean?",
    "What is the difference between AC and DC?",
    "Give me a short chicken soup tip.",
]

RUNS_PER_PROMPT = 2
UNLOAD_WAIT_S = 5  # Time for Ollama to fully unload from VRAM

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
            [
                "curl",
                "-s",
                "-X",
                "POST",
                "http://127.0.0.1:11434/api/generate",
                "-d",
                '{"model":"__unload__","prompt":"","keep_alive":0,"stream":false}',
            ],
            capture_output=True,
            timeout=10,
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
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
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
    if model == "auto":
        env["LUCY_MODEL"] = "auto"
        env["LUCY_LOCAL_MODEL"] = "local-lucy-llama31"
    else:
        env["LUCY_MODEL"] = model
        env["LUCY_LOCAL_MODEL"] = model
    env["LUCY_LOCAL_REPEAT_CACHE"] = "false"
    env["LUCY_GEMMA4_SMART_ROUTING"] = "1" if _SMART_ROUTING in ("on", "true", "1") else "0"

    start = time.time()
    try:
        r = subprocess.run(
            [sys.executable, str(REQUEST_TOOL), "submit", "--text", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(SNAPSHOT_ROOT),
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


def _set_state_model(model_alias: str, smart_routing: str) -> None:
    """Align the authoritative state file with the benchmark target config.

    runtime_request.py / main.py read current_state.json, so env vars alone are
    not enough to guarantee the intended model is actually loaded.
    """
    control_tool = SNAPSHOT_ROOT / "tools" / "runtime_control.py"
    model_value = "auto" if model_alias == "auto" else model_alias
    env = os.environ.copy()
    env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(SNAPSHOT_ROOT)
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(RUNTIME_NS)
    try:
        subprocess.run(
            [sys.executable, str(control_tool), "set-model", "--value", model_value],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(SNAPSHOT_ROOT),
            check=False,
        )
        subprocess.run(
            [
                sys.executable,
                str(control_tool),
                "set-gemma4-smart-routing",
                "--value",
                "on" if smart_routing in ("on", "true", "1") else "off",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
            cwd=str(SNAPSHOT_ROOT),
            check=False,
        )
    except Exception as exc:
        log(f"Warning: failed to set state model/routing: {exc}")


def benchmark_one(model_alias, model_label, smart_routing: str = "off"):
    log(f"{'=' * 60}")
    log(f"MODEL: {model_alias} ({model_label})  [smart_routing={smart_routing}]")
    log(f"{'=' * 60}")

    # STEP 0: Make sure the authoritative state matches the benchmark target
    _set_state_model(model_alias, smart_routing)

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
        "mode": "auto" if model_alias == "auto" else "direct",
        "gemma4_smart_routing": smart_routing,
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


def write_markdown_summary(report: dict, json_path: Path) -> Path:
    """Write a human-readable Markdown summary next to the JSON report."""
    md_path = json_path.with_suffix(".md")
    lines = [
        "# Local Lucy V10 — Model Comparison Benchmark Summary",
        "",
        f"**Timestamp:** {report['timestamp']}",
        f"**Modes tested:** {', '.join(report['models'])}",
        f"**Prompts:** {len(report['prompts'])}",
        f"**Runs per prompt:** {report['runs_per_prompt']}",
        "**Cache:** disabled",
        f"**Unload wait between modes:** {report['unload_wait_s']}s",
        "",
        "## Overall Results",
        "",
        "| Mode | Alias | Smart Routing | Cold-start (s) | Median (s) | Mean (s) | Min (s) | Max (s) | VRAM (MB) | Failed |",
        "|------|-------|---------------|----------------|------------|----------|---------|---------|-----------|--------|",
    ]
    for r in report["results"]:
        lines.append(
            f"| {r['mode']} | {r['model_alias']} | {r.get('gemma4_smart_routing', 'off')} | {r['cold_start_ttc']} | "
            f"{r['overall_median'] or 'N/A'} | {r['overall_mean'] or 'N/A'} | "
            f"{r['overall_min'] or 'N/A'} | {r['overall_max'] or 'N/A'} | "
            f"{r.get('vram_during_mb') or 'N/A'} | {r['failed']}/{r['total_queries']} |"
        )
    lines.extend(
        [
            "",
            "## Per-prompt Breakdown",
            "",
        ]
    )
    for r in report["results"]:
        lines.extend(
            [
                f"### {r['model_alias']} ({r['model_label']})",
                "",
                "| Prompt | Median (s) | Mean (s) | Min (s) | Max (s) |",
                "|--------|------------|----------|---------|---------|",
            ]
        )
        for prompt, stats in r["per_prompt"].items():
            lines.append(
                f"| {prompt} | {stats['median']} | {stats['mean']} | {stats['min']} | {stats['max']} |"
            )
        lines.append("")
    lines.extend(
        [
            "## Raw Data",
            "",
            f"Full JSON report: `{json_path}`",
            "",
        ]
    )
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main():
    parser = argparse.ArgumentParser(
        description="Clean-slate benchmark for Local Lucy selectable modes."
    )
    parser.add_argument(
        "--model",
        choices=[m[0] for m in MODELS],
        help="Benchmark only this model instead of the full list.",
    )
    parser.add_argument(
        "--smart-routing",
        choices=["on", "off"],
        default="off",
        help="Set gemma4_smart_routing state for this run (default: off).",
    )
    parser.add_argument(
        "--append-to",
        type=Path,
        help="Load an existing JSON report, append this run's result, and rewrite the summary.",
    )
    args = parser.parse_args()

    global _SMART_ROUTING
    _SMART_ROUTING = args.smart_routing

    models = [next((m for m in MODELS if m[0] == args.model), None)] if args.model else MODELS
    models = [m for m in models if m is not None]

    log("=" * 60)
    log("LOCAL LUCY V10 — CLEAN SLATE MODEL COMPARISON")
    log("=" * 60)
    log(f"Models: {', '.join(m[0] for m in models)}")
    log(f"Smart routing: {args.smart_routing}")
    log(f"Prompts: {len(PROMPTS)} x {RUNS_PER_PROMPT} runs")
    log("Cache: DISABLED")
    log(f"Unload wait: {UNLOAD_WAIT_S}s between models")
    log("=" * 60)

    results = []
    for alias, label in models:
        r = benchmark_one(alias, label, smart_routing=args.smart_routing)
        results.append(r)
        log(
            f"Summary for {alias}: median={r['overall_median']}s, mean={r['overall_mean']}s, failed={r['failed']}/{r['total_queries']}"
        )

    # Determine report file and merge behavior
    if args.append_to:
        report_path = args.append_to
        try:
            with open(report_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {"results": []}
        existing_results = existing.get("results", [])
        # Replace any prior result for the same alias + smart_routing state
        existing_results = [
            er
            for er in existing_results
            if not (
                er.get("model_alias") == results[0]["model_alias"]
                and er.get("gemma4_smart_routing") == results[0]["gemma4_smart_routing"]
            )
        ]
        existing_results.extend(results)
        report = {
            "timestamp": datetime.now().isoformat(),
            "models": sorted({er.get("model_alias") for er in existing_results}),
            "prompts": PROMPTS,
            "runs_per_prompt": RUNS_PER_PROMPT,
            "unload_wait_s": UNLOAD_WAIT_S,
            "results": existing_results,
        }
    else:
        report_path = REPORT_FILE
        report = {
            "timestamp": datetime.now().isoformat(),
            "models": [m[0] for m in MODELS],
            "prompts": PROMPTS,
            "runs_per_prompt": RUNS_PER_PROMPT,
            "unload_wait_s": UNLOAD_WAIT_S,
            "results": results,
        }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    md_file = write_markdown_summary(report, report_path)
    log(f"Markdown summary: {md_file}")

    log("=" * 60)
    log("FINAL COMPARISON (clean slate — cold start + warm runs)")
    log("=" * 60)
    log(
        f"{'Model':<30} {'Smart':<8} {'Cold':<8} {'Median':<8} {'Mean':<8} {'Min':<8} {'Max':<8} {'VRAM':<8}"
    )
    log("-" * 90)
    for r in report["results"]:
        log(
            f"{r['model_alias']:<30} {r.get('gemma4_smart_routing', 'off'):<8} "
            f"{r['cold_start_ttc']:<8} {r['overall_median'] or 'N/A':<8} "
            f"{r['overall_mean'] or 'N/A':<8} {r['overall_min'] or 'N/A':<8} "
            f"{r['overall_max'] or 'N/A':<8} {r.get('vram_during_mb') or 'N/A':<8}"
        )

    log(f"\nFull report: {report_path}")


if __name__ == "__main__":
    main()
