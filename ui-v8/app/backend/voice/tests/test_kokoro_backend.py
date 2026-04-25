#!/usr/bin/env python3
from __future__ import annotations

import struct
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from voice.backends import kokoro_backend


class FakeResult:
    def __init__(self, audio: np.ndarray) -> None:
        self.audio = audio


class FakeSoundFile:
    @staticmethod
    def write(path: str, data: np.ndarray, sample_rate: int, subtype: str | None = None) -> None:
        del subtype
        clipped = np.clip(np.asarray(data, dtype=np.float32), -1.0, 1.0)
        frames = b"".join(struct.pack("<h", int(round(float(sample) * 32767))) for sample in clipped)
        with wave.open(path, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(frames)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="kokoro_backend_") as tmp_dir:
        root = Path(tmp_dir)
        fake_bin = root / "kokoro-runtime"
        fake_bin.write_text("stub\n", encoding="utf-8")
        output_path = root / "kokoro.wav"
        calls: dict[str, object] = {}

        class FakePipeline:
            def __init__(self, lang_code: str, repo_id: str | None = None, device: str | None = None, **_: object) -> None:
                calls["init"] = (lang_code, repo_id, device)

            def __call__(self, text: str, voice: str | None = None, speed: float = 1.0, split_pattern: str | None = None, **_: object):
                calls["call"] = (text, voice, speed, split_pattern)
                yield FakeResult(np.array([0.25, -0.25], dtype=np.float32))
                yield FakeResult(np.array([0.0, 0.1], dtype=np.float32))

        original_loader = kokoro_backend.load_runtime_dependencies
        original_cuda_available = kokoro_backend.cuda_available
        original_cache = dict(kokoro_backend._PIPELINE_CACHE)
        try:
            kokoro_backend._PIPELINE_CACHE.clear()
            kokoro_backend.load_runtime_dependencies = lambda: (FakePipeline, np, FakeSoundFile)
            kokoro_backend.cuda_available = lambda: True
            voice = kokoro_backend.synthesize(
                root=root,
                text="hello kokoro",
                output_path=output_path,
                voice="af_heart",
                env={"LUCY_VOICE_KOKORO_BIN": str(fake_bin)},
            )
            assert_ok(voice == "af_heart", f"unexpected voice: {voice}")
            assert_ok(output_path.exists(), "expected synthesized wav output")
            with wave.open(str(output_path), "rb") as handle:
                assert_ok(handle.getframerate() == 24000, f"unexpected sample rate: {handle.getframerate()}")
                assert_ok(handle.getnframes() == 4, f"unexpected frame count: {handle.getnframes()}")
            assert_ok(calls.get("init") == ("a", "hexgrad/Kokoro-82M", "cuda"), f"unexpected init call: {calls}")
            assert_ok(calls.get("call") == ("hello kokoro", "af_heart", 1.0, r"\n+"), f"unexpected synth call: {calls}")

            kokoro_backend._PIPELINE_CACHE.clear()

            def fail_loader():
                raise kokoro_backend.KokoroBackendError("unable to import kokoro runtime: boom")

            kokoro_backend.load_runtime_dependencies = fail_loader
            try:
                kokoro_backend.synthesize(
                    root=root,
                    text="should fail",
                    output_path=root / "failure.wav",
                    voice="af_heart",
                    env={"LUCY_VOICE_KOKORO_BIN": str(fake_bin)},
                )
            except kokoro_backend.KokoroBackendError as exc:
                assert_ok("unable to import kokoro runtime" in str(exc), f"unexpected error: {exc}")
            else:
                raise AssertionError("expected kokoro import/init failure")
        finally:
            kokoro_backend.load_runtime_dependencies = original_loader
            kokoro_backend.cuda_available = original_cuda_available
            kokoro_backend._PIPELINE_CACHE.clear()
            kokoro_backend._PIPELINE_CACHE.update(original_cache)
    print("PASS: test_kokoro_backend")
    return 0


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
