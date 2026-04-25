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
    with tempfile.TemporaryDirectory(prefix="tts_fallback_") as tmp_dir:
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
                handle.writeframes(struct.pack("<hhh", 300, 200, 100))
            """,
        )

        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env["PYTHONPATH"] = str(REPO_ROOT / "tools")
        env["LUCY_VOICE_PIPER_BIN"] = str(bin_dir / "piper")
        env["HOME"] = str(root / "home")

        payload = run_adapter(
            dict(env, LUCY_VOICE_KOKORO_VOICE="custom.pt"),
            "synthesize",
            "--engine", "kokoro",
            "--fallback-engine", "piper",
            "--output-dir",
            str(out_dir),
            "--text",
            "fallback test",
        )
        assert_ok(payload["ok"] is True, f"fallback should succeed: {payload}")
        assert_ok(payload["requested_engine"] == "kokoro", f"requested_engine should preserve original request: {payload}")
        assert_ok(payload["engine"] == "piper", f"unexpected fallback engine: {payload}")
        assert_ok(payload["fallback_used"] is True, f"fallback flag missing: {payload}")

        failure = run_adapter(
            dict(env, LUCY_VOICE_KOKORO_BIN=str(root / "missing-kokoro")),
            "synthesize",
            "--engine",
            "kokoro",
            "--fallback-engine",
            "none",
            "--output-dir",
            str(out_dir),
            "--text",
            "kokoro should fail explicitly",
        )
        assert_ok(failure["ok"] is False, f"kokoro failure contract expected: {failure}")
        assert_ok(failure["requested_engine"] == "kokoro", f"failure should preserve requested_engine: {failure}")
        assert_ok(failure["engine"] == "kokoro", f"failure should preserve attempted engine: {failure}")
        assert_ok("kokoro" in str(failure["error"]).lower(), f"expected kokoro error detail: {failure}")
    print("PASS: test_tts_fallback")
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


def write_executable(path: Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
