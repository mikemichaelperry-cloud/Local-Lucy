#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
ADAPTER = REPO_ROOT / "tools" / "voice" / "tts_adapter.py"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="tts_adapter_contract_") as tmp_dir:
        root = Path(tmp_dir)
        bin_dir = root / "bin"
        out_dir = root / "out"
        bin_dir.mkdir(parents=True, exist_ok=True)
        out_dir.mkdir(parents=True, exist_ok=True)

        write_executable(
            bin_dir / "piper",
            """
            #!/usr/bin/env python3
            import struct
            import sys
            import wave

            output_path = sys.argv[sys.argv.index("--output_file") + 1]
            with wave.open(output_path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(22050)
                handle.writeframes(struct.pack("<hhhh", 1000, 800, 600, 400))
            """,
        )
        model_path = root / "voice.onnx"
        model_path.write_bytes(b"stub-model")

        env = base_env(bin_dir, root)
        env["LUCY_VOICE_PIPER_MODEL"] = str(model_path)

        payload = run_adapter(
            env,
            "synthesize",
            "--engine",
            "piper",
            "--output-dir",
            str(out_dir),
            "--text",
            "hello adapter",
        )
        assert_ok(payload["ok"] is True, f"expected ok contract: {payload}")
        assert_ok(payload["requested_engine"] == "piper", f"missing requested_engine on success: {payload}")
        assert_ok(payload["engine"] == "piper", f"unexpected engine: {payload}")
        assert_ok(payload["device"] == "cpu", f"unexpected device: {payload}")
        assert_ok(payload["voice"] == "en_GB-cori-high", f"unexpected voice: {payload}")
        assert_ok(Path(payload["wav_path"]).exists(), f"missing wav output: {payload}")
        assert_ok(payload["sample_rate"] == 22050, f"unexpected sample rate: {payload}")
        assert_ok(payload["duration_ms"] >= 0, f"unexpected duration: {payload}")
        assert_ok(payload["fallback_used"] is False, f"unexpected fallback flag: {payload}")
        assert_ok(payload["cache_hit"] is False, f"unexpected cache flag: {payload}")
        assert_ok(payload["error"] == "", f"unexpected error: {payload}")

        failure = run_adapter(
            env,
            "synthesize",
            "--engine",
            "piper",
            "--output-dir",
            str(out_dir),
            "--text",
            "",
        )
        assert_ok(failure["ok"] is False, f"expected failure contract: {failure}")
        assert_ok(failure["requested_engine"] == "piper", f"missing requested_engine on failure: {failure}")
        assert_ok(failure["device"] == "cpu", f"missing device on failure: {failure}")
        assert_ok(isinstance(failure["error"], str) and failure["error"], f"missing error detail: {failure}")
        assert_ok(failure["wav_path"] == "", f"failure contract should not expose wav path: {failure}")
    print("PASS: test_tts_adapter_contract")
    return 0


def run_adapter(env: dict[str, str], *args: str) -> dict[str, object]:
    completed = subprocess.run(
        [sys.executable, str(ADAPTER), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )
    payload = json.loads(completed.stdout)
    assert_ok(isinstance(payload, dict), f"adapter stdout was not JSON object: {completed.stdout!r}")
    return payload


def base_env(bin_dir: Path, root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["PYTHONPATH"] = str(REPO_ROOT / "tools")
    env["LUCY_VOICE_PIPER_BIN"] = str(bin_dir / "piper")
    env.pop("LUCY_VOICE_KOKORO_BIN", None)
    env["HOME"] = str(root / "home")
    return env


def write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
