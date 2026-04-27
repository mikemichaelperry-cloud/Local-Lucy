#!/usr/bin/env python3
"""Benchmark whisper GPU vs CPU: latency, memory, utilization."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WHISPER_BIN = ROOT / "runtime" / "voice" / "bin" / "whisper"
MODEL_PATH = ROOT / "runtime" / "voice" / "models" / f"ggml-{os.environ.get('LUCY_VOICE_MODEL', 'large-v3-turbo').strip()}.bin"


def generate_test_wav(path: Path, duration_sec: float = 5.0) -> None:
    """Generate a silent WAV file for benchmarking."""
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * (num_samples * 2))


def get_gpu_snapshot() -> dict:
    """Query GPU memory and utilization via nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode != 0:
            return {}
        parts = [p.strip() for p in result.stdout.strip().split(",")]
        if len(parts) >= 4:
            return {
                "name": parts[0],
                "memory_used_mb": int(parts[1]),
                "memory_total_mb": int(parts[2]),
                "utilization_pct": int(parts[3]),
            }
    except Exception:
        pass
    return {}


def run_whisper(wav_path: Path, use_gpu: bool = True) -> tuple[int, str, str, float]:
    cmd = [str(WHISPER_BIN), "-m", str(MODEL_PATH), "-f", str(wav_path), "-otxt", "-of", "-"]
    if not use_gpu:
        cmd.append("--no-gpu")

    env = dict(subprocess.os.environ)
    lib_dirs = [
        str(ROOT / "runtime" / "voice" / "whisper.cpp" / "build" / "src"),
        str(ROOT / "runtime" / "voice" / "whisper.cpp" / "build" / "ggml" / "src"),
    ]
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))

    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)
    elapsed = time.time() - start
    return proc.returncode, proc.stdout, proc.stderr, elapsed


def benchmark_backend(wav_path: Path, use_gpu: bool, iterations: int = 3) -> dict:
    label = "gpu" if use_gpu else "cpu"
    print(f"\nBenchmarking {label.upper()} ({iterations} iterations)...")

    times = []
    gpu_memory_deltas = []
    gpu_utils = []

    for i in range(iterations):
        baseline = get_gpu_snapshot() if use_gpu else {}
        rc, out, err, t = run_whisper(wav_path, use_gpu=use_gpu)
        peak = get_gpu_snapshot() if use_gpu else {}

        if rc != 0:
            print(f"  Iteration {i+1}: FAILED ({err[:200]})")
            continue

        times.append(t)
        print(f"  Iteration {i+1}: {t:.2f}s")

        if baseline and peak:
            mem_delta = peak.get("memory_used_mb", 0) - baseline.get("memory_used_mb", 0)
            gpu_util = peak.get("utilization_pct", 0)
            gpu_memory_deltas.append(mem_delta)
            gpu_utils.append(gpu_util)
            print(f"    GPU mem delta: {mem_delta} MB, util: {gpu_util}%")

    result = {
        "backend": label,
        "iterations": len(times),
        "transcription_time_ms": int(sum(times) / len(times) * 1000) if times else 0,
        "transcription_time_min_ms": int(min(times) * 1000) if times else 0,
        "transcription_time_max_ms": int(max(times) * 1000) if times else 0,
    }

    if gpu_memory_deltas:
        result["gpu_memory_delta_mb"] = int(sum(gpu_memory_deltas) / len(gpu_memory_deltas))
        result["gpu_memory_delta_max_mb"] = max(gpu_memory_deltas)
    if gpu_utils:
        result["gpu_utilization_peak_pct"] = max(gpu_utils)
        result["gpu_utilization_avg_pct"] = int(sum(gpu_utils) / len(gpu_utils))

    return result


def main() -> int:
    if not WHISPER_BIN.exists():
        print(f"ERROR: whisper binary not found at {WHISPER_BIN}")
        return 1
    if not MODEL_PATH.exists():
        print(f"ERROR: model not found at {MODEL_PATH}")
        return 1

    with tempfile.TemporaryDirectory(prefix="whisper_bench_") as tmp:
        wav_path = Path(tmp) / "test.wav"
        generate_test_wav(wav_path, duration_sec=5.0)

        print("=" * 60)
        print("Whisper GPU/CPU Benchmark")
        print(f"Binary: {WHISPER_BIN}")
        print(f"Model:  {MODEL_PATH}")
        print("=" * 60)

        results = {
            "gpu": benchmark_backend(wav_path, use_gpu=True, iterations=3),
            "cpu": benchmark_backend(wav_path, use_gpu=False, iterations=3),
        }

        print("\n" + "=" * 60)
        print("Summary")
        print("=" * 60)
        for key, res in results.items():
            print(f"\n{key.upper()}:")
            for k, v in res.items():
                if k == "backend":
                    continue
                print(f"  {k}: {v}")

        report_path = Path(tmp) / "whisper_benchmark_report.json"
        report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nFull report saved to: {report_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
