#!/usr/bin/env python3
"""Direct test of whisper GPU→CPU fallback logic in runtime_voice.py."""
from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from runtime_voice import transcribe_with_whisper, _GPU_ERROR_KEYWORDS, TranscriptionResult


def test_gpu_error_detection():
    assert any(k in "CUDA out of memory".lower() for k in _GPU_ERROR_KEYWORDS)
    assert any(k in "cublas init failed".lower() for k in _GPU_ERROR_KEYWORDS)
    assert not any(k in "random text error".lower() for k in _GPU_ERROR_KEYWORDS)
    print("PASS: _is_gpu_error logic")


def test_gpu_fallback():
    """Mock whisper that fails on GPU, succeeds on CPU fallback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        whisper_bin = tmp / "whisper"
        capture = tmp / "capture.wav"
        capture.write_bytes(b"RIFF" + b"\x00" * 100)

        # Mock whisper: fail without --no-gpu, succeed with it
        whisper_bin.write_text("""#!/usr/bin/env python3
import sys
if "--no-gpu" not in sys.argv:
    print("CUDA out of memory", file=sys.stderr)
    raise SystemExit(1)
# Find -of argument and write transcript
idx = sys.argv.index("-of")
prefix = sys.argv[idx + 1]
with open(prefix + ".txt", "w") as f:
    f.write("cpu fallback transcript")
""", encoding="utf-8")
        whisper_bin.chmod(whisper_bin.stat().st_mode | stat.S_IXUSR)

        result = transcribe_with_whisper(str(whisper_bin), capture)
        assert isinstance(result, TranscriptionResult)
        assert result.text == "cpu fallback transcript", f"Expected 'cpu fallback transcript', got {result.text!r}"
        assert result.backend == "cpu"
        assert result.fallback_used is True
        assert "cuda" in result.fallback_reason.lower()
        print("PASS: GPU fail → CPU fallback")


def test_gpu_success():
    """Mock whisper that succeeds on first GPU attempt."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        whisper_bin = tmp / "whisper"
        capture = tmp / "capture.wav"
        capture.write_bytes(b"RIFF" + b"\x00" * 100)

        whisper_bin.write_text("""#!/usr/bin/env python3
import sys
idx = sys.argv.index("-of")
prefix = sys.argv[idx + 1]
with open(prefix + ".txt", "w") as f:
    f.write("gpu success transcript")
""", encoding="utf-8")
        whisper_bin.chmod(whisper_bin.stat().st_mode | stat.S_IXUSR)

        result = transcribe_with_whisper(str(whisper_bin), capture)
        assert isinstance(result, TranscriptionResult)
        assert result.text == "gpu success transcript"
        assert result.backend == "gpu"
        assert result.fallback_used is False
        assert result.fallback_reason == ""
        print("PASS: GPU success on first attempt")


def test_non_gpu_error_no_fallback():
    """Non-GPU errors should not trigger CPU fallback."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        whisper_bin = tmp / "whisper"
        capture = tmp / "capture.wav"
        capture.write_bytes(b"RIFF" + b"\x00" * 100)

        whisper_bin.write_text("""#!/usr/bin/env python3
import sys
print("Model file not found", file=sys.stderr)
raise SystemExit(1)
""", encoding="utf-8")
        whisper_bin.chmod(whisper_bin.stat().st_mode | stat.S_IXUSR)

        try:
            transcribe_with_whisper(str(whisper_bin), capture)
            raise AssertionError("Should have raised RuntimeVoiceExit")
        except Exception as exc:
            assert "Model file not found" in str(exc)
        print("PASS: Non-GPU error does not trigger fallback")


def main() -> int:
    print("=" * 60)
    print("Direct Whisper Fallback Tests")
    print("=" * 60)
    test_gpu_error_detection()
    test_gpu_fallback()
    test_gpu_success()
    test_non_gpu_error_no_fallback()
    print("=" * 60)
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
