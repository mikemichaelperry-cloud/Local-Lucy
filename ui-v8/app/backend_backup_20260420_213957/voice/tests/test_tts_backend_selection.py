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
    with tempfile.TemporaryDirectory(prefix="tts_backend_selection_") as tmp_dir:
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
                handle.writeframes(struct.pack("<hh", 1000, 800))
            """,
        )
        env = base_env(bin_dir, root)

        probe = run_adapter(env, "probe", "--engine", "auto")
        assert_ok(probe["ok"] is True, f"probe failed: {probe}")
        assert_ok(probe["engine"] == "kokoro", f"auto selection should prefer kokoro when available: {probe}")

        auto_payload = run_adapter(
            env,
            "synthesize",
            "--engine",
            "auto",
            "--output-dir",
            str(out_dir),
            "--text",
            "selection test",
        )
        assert_ok(auto_payload["requested_engine"] == "auto", f"auto payload missing requested_engine: {auto_payload}")
        assert_ok(auto_payload["engine"] == "kokoro", f"auto synth should prefer kokoro when available: {auto_payload}")
        assert_ok(auto_payload["fallback_used"] is False, f"auto primary selection should not mark fallback: {auto_payload}")

        env_no_piper = env.copy()
        env_no_piper["LUCY_VOICE_PIPER_BIN"] = str(root / "missing-piper")
        env_no_piper["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
        (bin_dir / "piper").unlink()

        fallback_probe = run_adapter(env_no_piper, "probe", "--engine", "auto")
        assert_ok(fallback_probe["ok"] is True, f"fallback probe failed: {fallback_probe}")
        assert_ok(fallback_probe["engine"] == "kokoro", f"auto selection should still prefer kokoro when piper is unavailable: {fallback_probe}")

        degraded_payload = run_adapter(
            env_no_piper,
            "synthesize",
            "--engine",
            "piper",
            "--fallback-engine",
            "kokoro",
            "--output-dir",
            str(out_dir),
            "--text",
            "degraded direct selection",
        )
        assert_ok(degraded_payload["ok"] is True, f"degraded selection should still synthesize: {degraded_payload}")
        assert_ok(degraded_payload["requested_engine"] == "piper", f"requested_engine should preserve requested backend: {degraded_payload}")
        assert_ok(degraded_payload["engine"] == "kokoro", f"degraded selection should truthfully report actual engine: {degraded_payload}")
        assert_ok(degraded_payload["fallback_used"] is False, f"direct degraded selection must not mark fallback_used: {degraded_payload}")
    print("PASS: test_tts_backend_selection")
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
