#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import textwrap
import time
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_TOOLS_ROOT = Path("/home/mike/lucy-v8/tools")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="voice_ptt_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()

        from PySide6.QtTest import QTest
        from PySide6.QtCore import QSettings
        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])

        sandbox.write_voice_state("on")
        sandbox.write_request_tool(mode="success")
        sandbox.install_actual_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window.show()
        wait_for(lambda: app.focusWidget() is not None, app, 2.0, "initial prompt focus")
        assert_ok(
            app.focusWidget() is window.conversation_panel._draft,
            f"initial focus should land on the operator draft, got {type(app.focusWidget()).__name__ if app.focusWidget() else 'None'}",
        )
        QTest.keyClicks(window.conversation_panel._draft, "hello")
        app.processEvents()
        assert_ok(window.conversation_panel._draft.toPlainText() == "hello", "initial typing should reach the operator draft")
        close_window(app, window)

        sandbox.write_voice_state("on")
        sandbox.write_request_tool(mode="success")
        sandbox.install_actual_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        assert_ok(not window.control_panel._voice_ptt_group.isHidden(), "voice=on should expose the PTT group")
        button_text = window.control_panel._voice_ptt_button.text()
        assert_ok(
            button_text in {"PTT Unavailable", "Hold to Talk"},
            f"unexpected initial PTT label: {button_text!r}",
        )
        if button_text == "PTT Unavailable":
            close_window(app, window)
            print("VOICE_PTT_OFFSCREEN_OK")
            return 0
        assert_ok(
            not hasattr(window.control_panel, "_voice_tts_pause_selector"),
            "voice pause control should be absent from active operator panel",
        )
        close_window(app, window)

        sandbox.write_voice_state("off")
        window = build_window(app, OperatorConsoleWindow)
        assert_ok(window.control_panel._voice_ptt_group.isHidden(), "voice=off should hide the PTT group")
        window._handle_interface_level_selected("advanced")
        app.processEvents()
        assert_ok(window.control_panel._voice_ptt_group.isHidden(), "advanced mode must keep voice=off hidden")
        close_window(app, window)

        QSettings("LocalLucy", "OperatorConsole").setValue("interface_level", "service")
        sandbox.write_voice_state("on")
        window = build_window(app, OperatorConsoleWindow)
        assert_ok(window._interface_level == "advanced", "legacy engineering/service settings should normalize to advanced")
        assert_ok(not window.control_panel._voice_ptt_group.isHidden(), "voice=on should remain visible after restore")
        close_window(app, window)

        sandbox.reset_request_outputs()
        sandbox.write_request_tool(mode="success")
        sandbox.install_actual_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window._handle_voice_ptt_pressed()
        wait_for(lambda: not window._voice_action_in_flight, app, 5.0, "voice start")
        assert_ok(window._latest_state_snapshot.voice_runtime["status"] == "listening", "press should enter listening")
        assert_ok(window.control_panel._voice_ptt_button.text() == "Release to Send", "listening label mismatch")
        window._handle_voice_ptt_pressed()
        app.processEvents()
        assert_ok(not window._voice_action_in_flight, "repeat press while listening should not launch a second action")
        window._handle_voice_ptt_released()
        wait_for(lambda: not window._voice_action_in_flight, app, 5.0, "voice stop")
        assert_ok(window._latest_state_snapshot.voice_runtime["status"] == "idle", "release should return to idle")
        assert_ok(window.control_panel._voice_ptt_button.text() == "Hold to Talk", "idle label mismatch after release")
        latest_result = load_json(sandbox.last_request_result_path)
        history_lines = load_history(sandbox.request_history_path)
        assert_ok(latest_result["request_text"] == sandbox.transcript_text, "voice submit should persist transcript")
        assert_ok(history_lines[-1]["request_text"] == sandbox.transcript_text, "voice history should stay coherent")
        assert_ok("mock response for offscreen voice test" in window.conversation_panel._history.toPlainText(), "latest answer pane should show the persisted voice result")
        close_window(app, window)

        sandbox.reset_request_outputs()
        sandbox.write_request_tool(mode="failure")
        sandbox.install_actual_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window._handle_voice_ptt_pressed()
        wait_for(lambda: not window._voice_action_in_flight, app, 5.0, "voice start before failure")
        window._handle_voice_ptt_released()
        wait_for(lambda: not window._voice_action_in_flight, app, 5.0, "voice stop failure")
        voice_failures = [line for line in window._ui_event_lines if "voice failed" in line]
        assert_ok(len(voice_failures) == 1, f"voice failure should emit once, got {voice_failures}")
        assert_ok(window._latest_state_snapshot.voice_runtime["status"] == "fault", "failed voice submit should surface fault")
        close_window(app, window)

        sandbox.remove_voice_tool()
        sandbox.voice_runtime_path.unlink(missing_ok=True)
        window = build_window(app, OperatorConsoleWindow)
        assert_ok(not window.control_panel._voice_ptt_group.isHidden(), "missing tool should not hide PTT when voice=on")
        assert_ok(not window.control_panel._voice_ptt_button.isEnabled(), "missing tool should disable the PTT button")
        before_events = list(window._ui_event_lines)
        window._handle_voice_ptt_pressed()
        app.processEvents()
        assert_ok(not window._voice_action_in_flight, "missing tool should not start a voice action")
        assert_ok(len(window._ui_event_lines) >= len(before_events), "missing tool press should not crash the UI")
        close_window(app, window)

        sandbox.install_timeout_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window._runtime_bridge.voice_start_timeout_seconds = 0.2
        window._handle_voice_ptt_pressed()
        wait_for(lambda: not window._voice_action_in_flight, app, 2.0, "voice start timeout")
        assert_ok(any("timeout" in line.lower() for line in window._ui_event_lines), "timeout path should emit a concise timeout event")
        close_window(app, window)

        sandbox.install_nonzero_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window._handle_voice_ptt_pressed()
        wait_for(lambda: not window._voice_action_in_flight, app, 2.0, "voice non-zero")
        assert_ok(any("voice failed" in line.lower() for line in window._ui_event_lines), "non-zero path should emit a voice failure event")
        close_window(app, window)

        sandbox.install_actual_voice_tool()
        sandbox.write_request_tool(mode="missing")
        sandbox.voice_runtime_path.unlink(missing_ok=True)
        window = build_window(app, OperatorConsoleWindow)
        assert_ok(not window.control_panel._voice_ptt_button.isEnabled(), "unavailable backend should disable PTT")
        assert_ok("unavailable" in window.control_panel._voice_ptt_status_label.text().lower() or "missing" in window.control_panel._voice_ptt_status_label.text().lower(), "unavailable backend should be clear to the operator")
        close_window(app, window)

        sandbox.write_voice_state("on")
        sandbox.write_request_tool(mode="success")
        sandbox.install_actual_voice_tool()
        window = build_window(app, OperatorConsoleWindow)
        window._handle_interface_level_selected("operator")
        app.processEvents()
        assert_ok(window.event_log_panel.isHidden(), "operator level should hide event log panel")
        assert_ok(window.control_panel._profile_group.isHidden(), "operator level should hide profile group")
        assert_ok(not window.conversation_panel._recent_history_summary.isHidden(), "operator level should show recent summary")
        assert_ok(window.conversation_panel._history_list.isHidden(), "operator level should hide persisted history list")
        assert_ok(window.status_panel._runtime_detail_group.isHidden(), "operator level should hide runtime detail cards")

        window._handle_interface_level_selected("advanced")
        app.processEvents()
        assert_ok(not window.event_log_panel.isHidden(), "advanced level should show event log panel")
        assert_ok(not window.control_panel._profile_group.isHidden(), "advanced level should show profile group")
        assert_ok(window.conversation_panel._recent_history_summary.isHidden(), "advanced level should hide recent summary")
        assert_ok(not window.conversation_panel._history_list.isHidden(), "advanced level should show persisted history list")
        assert_ok(not window.status_panel._runtime_detail_group.isHidden(), "advanced level should show runtime detail cards")
        assert_ok(not window.status_panel._advanced_metadata_group.isHidden(), "advanced level should show expanded metadata")
        assert_ok(not window.status_panel._history_maintenance_group.isHidden(), "advanced level should show retention summary")

        sandbox.reset_request_outputs()
        os.environ["LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES"] = "137"
        sandbox.write_request_history_entries(
            [
                sandbox.make_history_entry("req-service-1", "service one", mode="auto", memory="on", voice="on"),
                sandbox.make_history_entry("req-service-2", "service two", mode="offline", memory="off", voice="off"),
            ],
            invalid_lines=1,
        )
        archive_path = sandbox.write_request_history_archive(
            "20260322-010101",
            [sandbox.make_history_entry("req-archive-1", "archive one", mode="online", memory="on", voice="on")],
        )
        close_window(app, window)
        window = build_window(app, OperatorConsoleWindow)
        window._handle_interface_level_selected("advanced")
        app.processEvents()
        maintenance_text = window.status_panel._history_maintenance_view.toPlainText()
        assert_ok("Active entries: 2 (invalid lines: 1)" in maintenance_text, f"unexpected advanced history entry summary: {maintenance_text}")
        assert_ok("Retention cap (active): 137" in maintenance_text, f"unexpected advanced retention summary: {maintenance_text}")
        assert_ok("Archive files: 1" in maintenance_text, f"unexpected advanced archive summary: {maintenance_text}")
        assert_ok(str(archive_path) in maintenance_text, f"advanced summary should surface latest archive path: {maintenance_text}")
        close_window(app, window)
        os.environ.pop("LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES", None)

        sandbox.reset_request_outputs()
        old_entry = sandbox.make_history_entry("req-hist-old", "older request", mode="offline", memory="off", voice="off")
        new_entry = sandbox.make_history_entry("req-hist-new", "newer request", mode="auto", memory="on", voice="on")
        sandbox.write_request_history_entries([old_entry, new_entry])
        sandbox.write_last_request_result(new_entry)
        window = build_window(app, OperatorConsoleWindow)
        window._handle_interface_level_selected("advanced")
        app.processEvents()
        assert_ok(window.conversation_panel._history_list.count() >= 2, "advanced level should list persisted history entries")
        window.conversation_panel._history_list.setCurrentRow(1)
        app.processEvents()
        control_state_text = window.status_panel._request_detail_labels["Control State"].text()
        assert_ok("mode=offline" in control_state_text, f"control state should reflect selected history entry: {control_state_text}")
        assert_ok("voice=off" in control_state_text, f"control state should reflect selected history entry: {control_state_text}")
        close_window(app, window)

        print("VOICE_PTT_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.bin_dir = root / "bin"
        self.tools_dir = self.home / "lucy" / "lucy-v8" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
        self.logs_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "logs"
        self.voice_runtime_path = self.state_dir / "voice_runtime.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.transcript_text = "hello from offscreen voice test"
        self.response_text = "mock response for offscreen voice test"
        self.bin_dir.mkdir(parents=True, exist_ok=True)
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._install_common_binaries()
        self.write_runtime_lifecycle()

    def prepare_import_environment(self) -> None:
        os.environ["HOME"] = str(self.home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["PATH"] = f"{self.bin_dir}:/usr/bin:/bin"
        # Set required runtime namespace root (parent of state_dir)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(self.state_dir.parent)
        # Set required authority contract variables
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = "/home/mike/lucy-v8"
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

    def _install_common_binaries(self) -> None:
        write_executable(
            self.bin_dir / "arecord",
            """
            #!/usr/bin/env python3
            import signal
            import sys
            import time

            output_path = sys.argv[-1]
            running = True

            def stop(_sig, _frame):
                global running
                running = False

            signal.signal(signal.SIGINT, stop)
            signal.signal(signal.SIGTERM, stop)
            while running:
                time.sleep(0.05)
            with open(output_path, "wb") as handle:
                handle.write(b"RIFF....WAVEfmt ")
            """,
        )
        write_executable(
            self.bin_dir / "whisper",
            f"""
            #!/usr/bin/env python3
            import sys

            args = sys.argv[1:]
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

    def reset_request_outputs(self) -> None:
        self.last_request_result_path.unlink(missing_ok=True)
        self.request_history_path.unlink(missing_ok=True)
        for archive_path in self.state_dir.glob("request_history.*.jsonl"):
            archive_path.unlink(missing_ok=True)
        self.voice_runtime_path.unlink(missing_ok=True)

    def make_history_entry(
        self,
        request_id: str,
        request_text: str,
        *,
        mode: str,
        memory: str,
        voice: str,
        evidence: str = "on",
        model: str = "local-lucy",
        profile: str = "test-profile",
    ) -> dict[str, object]:
        return {
            "completed_at": "2026-03-21T00:00:00Z",
            "control_state": {
                "mode": mode,
                "memory": memory,
                "evidence": evidence,
                "voice": voice,
                "model": model,
                "profile": profile,
            },
            "error": "",
            "outcome": {
                "action_hint": "",
                "evidence_created": "false",
                "outcome_code": "answered",
                "rc": 0,
                "utc": "2026-03-21T00:00:00Z",
            },
            "request_id": request_id,
            "request_text": request_text,
            "response_text": self.response_text,
            "route": {
                "mode": "LOCAL",
                "query": request_text,
                "reason": "offscreen-test",
                "session_id": "",
                "utc": "2026-03-21T00:00:00Z",
            },
            "status": "completed",
        }

    def write_request_history_entries(self, entries: list[dict[str, object]], *, invalid_lines: int = 0) -> None:
        self.request_history_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(entry) for entry in entries]
        lines.extend(["{invalid json"] * max(invalid_lines, 0))
        self.request_history_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def write_request_history_archive(self, suffix: str, entries: list[dict[str, object]]) -> Path:
        archive_path = self.state_dir / f"request_history.{suffix}.jsonl"
        archive_lines = [json.dumps(entry) for entry in entries]
        archive_path.write_text("\n".join(archive_lines) + "\n", encoding="utf-8")
        return archive_path

    def write_last_request_result(self, payload: dict[str, object]) -> None:
        self.last_request_result_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    def install_actual_voice_tool(self) -> None:
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_voice.py", self.tools_dir / "runtime_voice.py")
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")

    def install_timeout_voice_tool(self) -> None:
        write_executable(
            self.tools_dir / "runtime_voice.py",
            """
            #!/usr/bin/env python3
            import time

            time.sleep(1.0)
            """,
        )

    def install_nonzero_voice_tool(self) -> None:
        write_executable(
            self.tools_dir / "runtime_voice.py",
            """
            #!/usr/bin/env python3
            import sys

            print("synthetic non-zero failure", file=sys.stderr)
            raise SystemExit(6)
            """,
        )

    def remove_voice_tool(self) -> None:
        (self.tools_dir / "runtime_voice.py").unlink(missing_ok=True)
        (self.tools_dir / "runtime_control.py").unlink(missing_ok=True)

    def write_request_tool(self, *, mode: str) -> None:
        request_tool = self.tools_dir / "runtime_request.py"
        if mode == "missing":
            request_tool.unlink(missing_ok=True)
            os.environ["LUCY_RUNTIME_REQUEST_TOOL"] = str(request_tool)
            return

        if mode == "failure":
            content = """
                #!/usr/bin/env python3
                import json
                print(json.dumps({"status": "failed", "error": "synthetic request failure", "request_id": "req-failure-1"}))
            """
        else:
            content = f"""
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                transcript = sys.argv[-1]
                state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v8/state"))
                state_dir.mkdir(parents=True, exist_ok=True)
                payload = {{
                    "accepted": True,
                    "completed_at": "2026-03-21T00:00:00Z",
                    "control_state": {{
                        "mode": "auto",
                        "memory": "on",
                        "evidence": "on",
                        "voice": "on",
                        "model": "local-lucy",
                        "profile": "test-profile",
                    }},
                    "error": "",
                    "outcome": {{
                        "action_hint": "",
                        "evidence_created": "false",
                        "outcome_code": "answered",
                        "rc": 0,
                        "utc": "2026-03-21T00:00:00Z",
                    }},
                    "request_id": "req-ui-success-1",
                    "request_text": transcript,
                    "response_text": {self.response_text!r},
                    "route": {{
                        "mode": "LOCAL",
                        "query": transcript,
                        "reason": "offscreen-test",
                        "session_id": "",
                        "utc": "2026-03-21T00:00:00Z",
                    }},
                    "status": "completed",
                }}
                with open(state_dir / "last_request_result.json", "w", encoding="utf-8") as handle:
                    json.dump(payload, handle)
                    handle.write("\\n")
                with open(state_dir / "request_history.jsonl", "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload) + "\\n")
                print(json.dumps(payload))
            """
        write_executable(request_tool, content)
        os.environ["LUCY_RUNTIME_REQUEST_TOOL"] = str(request_tool)


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


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_history(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
