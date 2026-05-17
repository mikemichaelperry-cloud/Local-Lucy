#!/usr/bin/env python3
"""Unit tests for the persistent whisper-server worker.

Run with: cd ~/lucy-v9/tools && python tests/test_whisper_worker_direct.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.whisper_worker import (
    ensure_whisper_worker,
    stop_whisper_worker,
    transcribe_with_worker,
    WhisperWorkerError,
    resolve_whisper_worker_port,
)

ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "runtime" / "voice" / "models" / "ggml-large-v3-turbo.bin"
TEST_WAV = ROOT / "tools" / "tests" / "fixtures" / "test_hello.wav"


def test_resolve_port_default() -> None:
    port = resolve_whisper_worker_port()
    assert port == 18181, f"expected 18181, got {port}"
    print("✓ resolve_whisper_worker_port default")


def test_resolve_port_env() -> None:
    old = os.environ.get("LUCY_WHISPER_SERVER_PORT")
    os.environ["LUCY_WHISPER_SERVER_PORT"] = "19999"
    try:
        port = resolve_whisper_worker_port()
        assert port == 19999, f"expected 19999, got {port}"
        print("✓ resolve_whisper_worker_port env override")
    finally:
        if old is None:
            os.environ.pop("LUCY_WHISPER_SERVER_PORT", None)
        else:
            os.environ["LUCY_WHISPER_SERVER_PORT"] = old


def test_start_and_transcribe() -> None:
    if not MODEL_PATH.exists():
        print(f"⚠ SKIP: model not found at {MODEL_PATH}")
        return
    if not TEST_WAV.exists():
        print(f"⚠ SKIP: test wav not found at {TEST_WAV}")
        return

    # Ensure clean state
    stop_whisper_worker()

    port = ensure_whisper_worker(MODEL_PATH, use_gpu=True)
    assert port is not None, "ensure_whisper_worker returned None"
    print(f"✓ Worker started on port {port}")

    result = transcribe_with_worker(TEST_WAV, port, timeout=30.0)
    assert "text" in result, f"missing 'text' in result: {result}"
    print(f"✓ Transcription result: {repr(result['text'])}")

    # Health re-check: calling ensure again should return same port instantly
    port2 = ensure_whisper_worker(MODEL_PATH, use_gpu=True)
    assert port2 == port, f"expected same port {port}, got {port2}"
    print("✓ Re-use existing worker")

    stop_whisper_worker()

    # After stop, worker should be gone
    port3 = ensure_whisper_worker(MODEL_PATH, use_gpu=True)
    assert port3 == port, f"expected same port {port}, got {port3}"
    print("✓ Worker restarted after stop")

    stop_whisper_worker()
    print("✓ Worker stopped cleanly")


def test_fallback_on_missing_wav() -> None:
    if not MODEL_PATH.exists():
        print("⚠ SKIP: model not found")
        return

    stop_whisper_worker()
    port = ensure_whisper_worker(MODEL_PATH, use_gpu=True)
    assert port is not None

    try:
        transcribe_with_worker("/nonexistent/path.wav", port, timeout=5.0)
        assert False, "expected WhisperWorkerError"
    except WhisperWorkerError:
        print("✓ WhisperWorkerError raised for missing file")

    stop_whisper_worker()


if __name__ == "__main__":
    print("=== test_whisper_worker_direct ===")
    test_resolve_port_default()
    test_resolve_port_env()
    test_start_and_transcribe()
    test_fallback_on_missing_wav()
    print("\nAll whisper worker direct tests passed.")
