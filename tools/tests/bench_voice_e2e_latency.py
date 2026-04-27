#!/usr/bin/env python3
"""End-to-end voice latency benchmark: transcription + response + TTS."""
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
MODEL_PATH = ROOT / "runtime" / "voice" / "models" / "ggml-small.en.bin"


def generate_test_wav(path: Path, duration_sec: float = 3.0) -> None:
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * (num_samples * 2))


def whisper_env() -> dict[str, str]:
    env = dict(os.environ)
    lib_dirs = [
        str(ROOT / "runtime" / "voice" / "whisper.cpp" / "build" / "src"),
        str(ROOT / "runtime" / "voice" / "whisper.cpp" / "build" / "ggml" / "src"),
    ]
    existing = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))
    return env


def benchmark_iteration(wav_path: Path, iteration: int) -> dict:
    print(f"\nIteration {iteration}...")
    env = whisper_env()
    stages = {}

    # Stage 1: Transcription (GPU-first with fallback)
    t0 = time.time()
    cmd = [str(WHISPER_BIN), "-m", str(MODEL_PATH), "-f", str(wav_path), "-otxt", "-of", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=env)

    if proc.returncode != 0 and any(k in proc.stderr.lower() for k in ("cuda", "cublas", "gpu", "oom")):
        cmd_cpu = cmd + ["--no-gpu"]
        proc = subprocess.run(cmd_cpu, capture_output=True, text=True, timeout=120, env=env)
        stages["stt_backend"] = "cpu"
        stages["stt_fallback"] = True
    else:
        stages["stt_backend"] = "gpu"
        stages["stt_fallback"] = False

    t1 = time.time()
    stages["transcription_ms"] = int((t1 - t0) * 1000)
    transcript = proc.stdout.strip() if proc.returncode == 0 else ""
    print(f"  STT ({stages['stt_backend']}): {stages['transcription_ms']}ms")

    # Stage 2: Mock query processing (simulates Lucy router latency)
    t2 = time.time()
    response_text = "This is a mock response for the end-to-end voice latency benchmark."
    time.sleep(0.05)  # Simulate minimal router work
    t3 = time.time()
    stages["query_ms"] = int((t3 - t2) * 1000)
    print(f"  Query: {stages['query_ms']}ms")

    # Stage 3: TTS synthesis (Kokoro if available, else skip)
    t4 = time.time()
    tts_backend = "none"
    tts_latency_ms = 0
    try:
        tts_adapter = ROOT / "tools" / "voice" / "tts_adapter.py"
        if tts_adapter.exists():
            tts_cmd = [
                sys.executable, str(tts_adapter),
                "synthesize", "--text", response_text,
                "--output-dir", str(wav_path.parent),
            ]
            tts_proc = subprocess.run(tts_cmd, capture_output=True, text=True, timeout=60)
            if tts_proc.returncode == 0:
                tts_result = json.loads(tts_proc.stdout)
                tts_backend = tts_result.get("engine", "unknown")
                tts_latency_ms = tts_result.get("synth_latency_ms", 0)
    except Exception as exc:
        print(f"  TTS skipped: {exc}")

    t5 = time.time()
    stages["tts_ms"] = int((t5 - t4) * 1000)
    stages["tts_backend"] = tts_backend
    stages["tts_synth_latency_ms"] = tts_latency_ms
    print(f"  TTS ({tts_backend}): {stages['tts_ms']}ms")

    stages["total_ms"] = stages["transcription_ms"] + stages["query_ms"] + stages["tts_ms"]
    print(f"  Total: {stages['total_ms']}ms")

    return stages


def main() -> int:
    if not WHISPER_BIN.exists():
        print(f"ERROR: whisper binary not found at {WHISPER_BIN}")
        return 1
    if not MODEL_PATH.exists():
        print(f"ERROR: model not found at {MODEL_PATH}")
        return 1

    with tempfile.TemporaryDirectory(prefix="voice_e2e_bench_") as tmp:
        wav_path = Path(tmp) / "test.wav"
        generate_test_wav(wav_path, duration_sec=3.0)

        print("=" * 60)
        print("End-to-End Voice Latency Benchmark")
        print(f"Whisper: {WHISPER_BIN}")
        print(f"Model:   {MODEL_PATH}")
        print("=" * 60)

        iterations = 5
        results = []
        for i in range(1, iterations + 1):
            results.append(benchmark_iteration(wav_path, i))

        # Compute medians
        total_times = sorted(r["total_ms"] for r in results)
        stt_times = sorted(r["transcription_ms"] for r in results)
        tts_times = sorted(r["tts_ms"] for r in results)
        median_idx = iterations // 2

        summary = {
            "iterations": iterations,
            "median_total_ms": total_times[median_idx],
            "median_stt_ms": stt_times[median_idx],
            "median_tts_ms": tts_times[median_idx],
            "min_total_ms": min(total_times),
            "max_total_ms": max(total_times),
            "per_iteration": results,
        }

        print("\n" + "=" * 60)
        print("Summary (median of 5 iterations)")
        print("=" * 60)
        print(f"  Total E2E latency: {summary['median_total_ms']}ms")
        print(f"  STT latency:       {summary['median_stt_ms']}ms")
        print(f"  TTS latency:       {summary['median_tts_ms']}ms")
        print(f"  Total range:       {summary['min_total_ms']}–{summary['max_total_ms']}ms")

        report_path = Path(tmp) / "voice_e2e_benchmark_report.json"
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"\nFull report saved to: {report_path}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
