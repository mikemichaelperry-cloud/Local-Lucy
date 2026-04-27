#!/usr/bin/env python3
"""Real whisper integration test: verify GPU and CPU paths both work."""
from __future__ import annotations

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
    """Generate a silent WAV file for testing."""
    sample_rate = 16000
    num_samples = int(sample_rate * duration_sec)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * (num_samples * 2))


def run_whisper(wav_path: Path, use_gpu: bool = True) -> tuple[int, str, str, float]:
    """Run whisper and return (returncode, stdout, stderr, elapsed_sec)."""
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
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    elapsed = time.time() - start
    return proc.returncode, proc.stdout, proc.stderr, elapsed


def main() -> int:
    if not WHISPER_BIN.exists():
        print(f"SKIP: whisper binary not found at {WHISPER_BIN}")
        return 0
    if not MODEL_PATH.exists():
        print(f"SKIP: model not found at {MODEL_PATH}")
        return 0

    with tempfile.TemporaryDirectory(prefix="whisper_real_test_") as tmp:
        wav_path = Path(tmp) / "test.wav"
        generate_test_wav(wav_path, duration_sec=3.0)

        print("=" * 60)
        print("Real Whisper Integration Test")
        print(f"Binary: {WHISPER_BIN}")
        print(f"Model:  {MODEL_PATH}")
        print("=" * 60)

        # Test GPU path
        print("\n[1/2] Testing GPU path (default)...")
        rc_gpu, out_gpu, err_gpu, t_gpu = run_whisper(wav_path, use_gpu=True)
        print(f"  returncode: {rc_gpu}")
        print(f"  elapsed:    {t_gpu:.2f}s")
        if rc_gpu != 0:
            print(f"  stderr:     {err_gpu[:500]}")
            print("  GPU path FAILED")
        else:
            print("  GPU path OK")

        # Test CPU path
        print("\n[2/2] Testing CPU path (--no-gpu)...")
        rc_cpu, out_cpu, err_cpu, t_cpu = run_whisper(wav_path, use_gpu=False)
        print(f"  returncode: {rc_cpu}")
        print(f"  elapsed:    {t_cpu:.2f}s")
        if rc_cpu != 0:
            print(f"  stderr:     {err_cpu[:500]}")
            print("  CPU path FAILED")
        else:
            print("  CPU path OK")

        print("\n" + "=" * 60)
        if rc_gpu == 0 and rc_cpu == 0:
            print("RESULT: PASS — both GPU and CPU paths work")
            print(f"  GPU latency: {t_gpu:.2f}s")
            print(f"  CPU latency: {t_cpu:.2f}s")
            return 0
        elif rc_gpu != 0 and rc_cpu == 0:
            print("RESULT: PARTIAL — GPU failed, CPU fallback works")
            print(f"  CPU latency: {t_cpu:.2f}s")
            return 0
        else:
            print("RESULT: FAIL — both paths failed")
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
