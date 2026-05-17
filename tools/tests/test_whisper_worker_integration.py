#!/usr/bin/env python3
"""Integration test: verify runtime_voice.py uses whisper worker fast-path.

Run with: cd ~/lucy-v9/tools && python tests/test_whisper_worker_integration.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime_voice import transcribe_with_whisper, resolve_whisper_model_path, bundled_whisper_binary, resolve_root
from voice.whisper_worker import stop_whisper_worker

ROOT = Path(__file__).resolve().parents[2]
TEST_WAV = ROOT / "tools" / "tests" / "fixtures" / "test_hello.wav"
WHISPER_BIN = str(bundled_whisper_binary(resolve_root()))


def test_worker_fast_path() -> None:
    """Verify transcribe_with_whisper uses the worker when available."""
    if not TEST_WAV.exists():
        print(f"⚠ SKIP: test wav not found at {TEST_WAV}")
        return

    # Ensure clean state
    stop_whisper_worker()

    model_path = resolve_whisper_model_path()
    if not model_path.exists():
        print(f"⚠ SKIP: model not found at {model_path}")
        return

    result = transcribe_with_whisper("whisper", TEST_WAV)
    assert result.backend == "gpu", f"expected gpu backend, got {result.backend}"
    assert result.fallback_used is False, "expected no fallback on first attempt"
    print(f"✓ Worker fast-path returned: {repr(result.text)} (backend={result.backend})")

    stop_whisper_worker()


def test_fallback_to_whisper_cli() -> None:
    """Verify whisper-cli fallback still works when worker is disabled."""
    import os

    if not TEST_WAV.exists():
        print("⚠ SKIP: test wav not found")
        return

    model_path = resolve_whisper_model_path()
    if not model_path.exists():
        print(f"⚠ SKIP: model not found at {model_path}")
        return

    # Disable worker
    old_disable = os.environ.get("LUCY_WHISPER_SERVER_DISABLE")
    os.environ["LUCY_WHISPER_SERVER_DISABLE"] = "1"
    try:
        result = transcribe_with_whisper(WHISPER_BIN, TEST_WAV)
        assert result.backend in ("gpu", "cpu"), f"unexpected backend: {result.backend}"
        print(f"✓ Fallback whisper-cli returned: {repr(result.text)} (backend={result.backend})")
    finally:
        if old_disable is None:
            os.environ.pop("LUCY_WHISPER_SERVER_DISABLE", None)
        else:
            os.environ["LUCY_WHISPER_SERVER_DISABLE"] = old_disable


if __name__ == "__main__":
    print("=== test_whisper_worker_integration ===")
    test_worker_fast_path()
    test_fallback_to_whisper_cli()
    print("\nAll integration tests passed.")
