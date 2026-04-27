#!/usr/bin/env python3
"""Offscreen HMI test: Whisper GPU fails, CPU fallback succeeds."""
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_TOOLS_ROOT = Path("/home/mike/lucy-v8/tools")
AUTHORITY_ROOT = Path("/home/mike/lucy-v8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="whisper_fallback_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])

        sandbox.write_voice_state("on")
        sandbox.write_request_tool(mode="success")
        window = build_window(app, OperatorConsoleWindow)

        window._handle_voice_ptt_pressed()
        wait_for(lambda: not window._voice_action_in_flight, app, 5.0, "voice start")
        assert_ok(
            window._latest_state_snapshot.voice_runtime["status"] == "listening",
            "press should enter listening",
        )

        window._handle_voice_ptt_released()
        wait_for(lambda: not window._voice_action_in_flight, app, 10.0, "voice stop with fallback")
        assert_ok(
            window._latest_state_snapshot.voice_runtime["status"] == "idle",
            "release should return to idle after CPU fallback",
        )

        # Verify STT backend metadata
        vr = window._latest_state_snapshot.voice_runtime
        assert_ok(vr.get("stt_backend") == "cpu", f"stt_backend should be 'cpu', got {vr.get('stt_backend')!r}")
        assert_ok(
            "cuda" in (vr.get("stt_fallback_reason") or "").lower(),
            f"stt_fallback_reason should contain cuda error, got {vr.get('stt_fallback_reason')!r}",
        )

        # Verify HMI shows fallback indicator
        stt_text = window.control_panel._voice_stt_label.text()
        assert_ok("GPU → CPU" in stt_text, f"HMI should show GPU→CPU fallback, got {stt_text!r}")

        # Verify transcript was still processed
        latest_result = load_json(sandbox.last_request_result_path)
        assert_ok(
            latest_result["request_text"] == sandbox.transcript_text,
            "voice submit should persist transcript even with CPU fallback",
        )

        close_window(app, window)
        print("WHISPER_GPU_CPU_FALLBACK_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.bin_dir = root / "bin"
        self.tools_dir = self.home / "lucy" / "lucy-v8" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
        self.voice_runtime_path = self.state_dir / "voice_runtime.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.transcript_text = "hello from gpu fallback offscreen test"
        self.response_text = "mock response for gpu fallback test"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._install_common_binaries()
        self.write_runtime_lifecycle()

    def prepare_import_environment(self) -> None:
        os.environ["HOME"] = str(self.home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["PATH"] = f"{self.bin_dir}:/usr/bin:/bin"
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(self.state_dir.parent)
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(AUTHORITY_ROOT)
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        os.environ["PYTHONPATH"] = f"{REPO_TOOLS_ROOT}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
        sys.path.insert(0, str(REPO_UI_ROOT))

    def _install_common_binaries(self) -> None:
        write_executable(
            self.bin_dir / "arecord",
            """
            #!/usr/bin/env python3
            import signal
            import sys
            import time

            running = True

            def stop(_sig, _frame):
                global running
                running = False

            signal.signal(signal.SIGINT, stop)
            signal.signal(signal.SIGTERM, stop)
            # Write raw PCM to stdout until stopped
            while running:
                sys.stdout.buffer.write(bytes(2048))
                sys.stdout.buffer.flush()
                time.sleep(0.05)
            """,
        )
        # Mock whisper: fails without --no-gpu, succeeds with --no-gpu
        write_executable(
            self.bin_dir / "whisper",
            f"""
            #!/usr/bin/env python3
            import sys

            args = sys.argv[1:]
            if "--no-gpu" not in args and "-ng" not in args:
                print("CUDA out of memory error: failed to allocate GPU memory", file=sys.stderr)
                raise SystemExit(1)

            prefix = args[args.index("-of") + 1]
            with open(prefix + ".txt", "w", encoding="utf-8") as handle:
                handle.write({self.transcript_text!r})
            """,
        )
        write_executable(
            self.bin_dir / "espeak-ng",
            """
            #!/usr/bin/env python3
            raise SystemExit(0)
            """,
        )

    def write_voice_state(self, value: str) -> None:
        self.current_state_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "test-profile",
                    "mode": "auto",
                    "memory": "on",
                    "evidence": "on",
                    "voice": value,
                    "model": "local-lucy",
                    "approval_required": False,
                    "status": "ready",
                    "last_updated": "2026-03-21T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def write_runtime_lifecycle(self) -> None:
        self.runtime_lifecycle_path.write_text(
            json.dumps({"running": True, "status": "running", "pid": 43210}) + "\n",
            encoding="utf-8",
        )

    def write_request_tool(self, mode: str) -> None:
        tool_path = self.tools_dir / "runtime_request.py"
        tool_path.parent.mkdir(parents=True, exist_ok=True)
        if mode == "success":
            content = f"""
import json, sys, os
from pathlib import Path
result = {{
    "status": "completed",
    "response_text": {self.response_text!r},
    "request_id": "req-fallback-001",
    "route": {{"mode": "online"}},
    "outcome": {{"outcome_code": "answered"}},
}}
print(json.dumps(result))
"""
        else:
            content = """
import json, sys
print(json.dumps({"status": "failed", "error": "mock failure", "request_id": ""}))
"""
        tool_path.write_text(content.strip() + "\n", encoding="utf-8")
        tool_path.chmod(tool_path.stat().st_mode | stat.S_IXUSR)

        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content.strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build_window(app, window_cls):
    window = window_cls()
    window.refresh_runtime_state()
    app.processEvents()
    return window


def close_window(app, window) -> None:
    window._state_refresh_timer.stop()
    window.close()
    window.deleteLater()
    app.processEvents()


def wait_for(predicate, app, timeout_seconds: float, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {label}")


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
