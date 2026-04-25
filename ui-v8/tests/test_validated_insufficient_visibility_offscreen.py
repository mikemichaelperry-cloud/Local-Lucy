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
REPO_TOOLS_ROOT = Path("/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="validated_insufficient_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()
        sandbox.install_runtime_request_tool()
        sandbox.write_current_state()
        sandbox.write_runtime_lifecycle()

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.resize(960, 720)
        window.show()
        app.processEvents()
        window.refresh_runtime_state()
        app.processEvents()

        window._handle_submit_requested("Do you think that YouTube amplifiers are relevant today?")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "validated insufficient submit")
        app.processEvents()

        summary_text = window.conversation_panel._decision_trace_summary_button.text()
        assert_ok("EVIDENCE -> EVIDENCE" in summary_text, f"summary should reflect evidence mode, got={summary_text!r}")
        assert_ok(
            "evidence insufficient" in summary_text,
            f"summary should expose insufficient-evidence note, got={summary_text!r}",
        )
        assert_ok(
            "trust=insufficient-evidence" in summary_text,
            f"summary should override stale trust label, got={summary_text!r}",
        )
        assert_ok(
            "provider unavailable" in summary_text,
            f"summary should expose structured provider unavailability, got={summary_text!r}",
        )

        request_summary = window.status_panel._request_summary_labels
        request_detail = window.status_panel._request_detail_labels
        answer_text = window.conversation_panel._history.toPlainText()
        assert_ok(
            request_summary["Answer Path"].text() == "Evidence insufficient",
            f"answer path should expose insufficient evidence, got={request_summary['Answer Path'].text()!r}",
        )
        assert_ok(
            request_summary["Trust"].text() == "insufficient-evidence",
            f"trust should expose insufficient evidence, got={request_summary['Trust'].text()!r}",
        )
        assert_ok(
            request_summary["Augmented"].text() == "OPENAI unavailable",
            f"augmented summary should expose structured provider unavailability, got={request_summary['Augmented'].text()!r}",
        )
        expected_note = "Current evidence was insufficient. Next step: provide a narrower query or an allowlisted source URL."
        assert_ok(
            request_detail["Operator Note"].text() == expected_note,
            f"operator note should expose next step, got={request_detail['Operator Note'].text()!r}",
        )
        assert_ok(
            request_detail["Augmented Provider Status"].text() == "external_unavailable",
            f"request detail should expose structured provider status, got={request_detail['Augmented Provider Status'].text()!r}",
        )
        assert_ok(
            "Path: Evidence insufficient" in answer_text,
            f"operator response should expose insufficient-evidence path, got={answer_text!r}",
        )
        assert_ok(
            "Path: Evidence-backed answer" not in answer_text,
            "operator response should not report a successful evidence-backed path",
        )

        summary_button = window.conversation_panel._decision_trace_summary_button
        summary_button.click()
        app.processEvents()
        trace_text = window._decision_trace_view.toPlainText()
        assert_ok(
            f"Operator Summary: {expected_note}" in trace_text,
            "decision trace should explain the insufficient-evidence result",
        )
        assert_ok(
            "Operator Trust: insufficient-evidence" in trace_text,
            "decision trace should override stale trust label",
        )
        assert_ok(
            "Augmented Provider Status: external_unavailable" in trace_text,
            "decision trace should expose structured augmented provider status",
        )
        assert_ok(
            "Operator Answer Path: Evidence insufficient" in trace_text,
            "decision trace should override stale answer path",
        )
        assert_ok(
            f"Operator Note: {expected_note}" in trace_text,
            "decision trace should override stale operator note",
        )
        assert_ok(
            "Operator Answer Path: Evidence-backed answer" not in trace_text,
            "decision trace should not expose stale evidence-backed answer path",
        )
        assert_ok(
            "Operator Note: Answer is grounded in current evidence." not in trace_text,
            "decision trace should not expose stale evidence-grounded note",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("VALIDATED_INSUFFICIENT_VISIBILITY_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / "lucy" / "snapshots" / "opt-experimental-v7-dev" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v7" / "state"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def prepare_import_environment(self) -> None:
        os.environ["HOME"] = str(self.home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # Set required runtime namespace root (parent of state_dir)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(self.state_dir.parent)
        # Set required authority contract variables
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(self.home / "lucy" / "snapshots" / "opt-experimental-v7-dev")
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

    def install_runtime_request_tool(self) -> None:
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")
        write_executable(
            self.tools_dir / "runtime_request.py",
            """
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import time
            from pathlib import Path

            args = sys.argv[1:]
            if len(args) < 3 or args[0] != "submit" or args[1] != "--text":
                raise SystemExit(2)

            request_text = args[2]
            payload = {
                "accepted": True,
                "completed_at": "2026-04-03T15:22:26Z",
                "control_state": {
                    "mode": "auto",
                    "conversation": "on",
                    "memory": "on",
                    "evidence": "on",
                    "voice": "on",
                    "augmentation_policy": "direct_allowed",
                    "augmented_provider": "openai",
                    "model": "local-lucy",
                    "profile": "opt-experimental-v7-dev",
                },
                "error": "",
                "outcome": {
                    "requested_mode": "EVIDENCE",
                    "final_mode": "EVIDENCE",
                    "evidence_mode": "LIGHT",
                    "trust_class": "evidence_backed",
                    "outcome_code": "validated_insufficient",
                    "action_hint": "provide a narrower query or an allowlisted source URL",
                    "answer_class": "evidence_backed_answer",
                    "operator_trust_label": "evidence-backed",
                    "operator_answer_path": "Evidence-backed answer",
                    "operator_note": "Answer is grounded in current evidence.",
                    "fallback_used": "false",
                    "fallback_reason": "validated_insufficient_openai_provider_unavailable",
                    "augmented_provider": "openai",
                    "augmented_provider_status": "external_unavailable",
                    "augmented_provider_error_reason": "openai_network_error",
                    "augmented_provider_used": "none",
                    "augmented_provider_call_reason": "error",
                    "augmented_direct_request": "false",
                    "evidence_created": "true",
                },
                "request_id": f"req-insufficient-{time.time_ns()}",
                "request_text": request_text,
                "response_text": "From current sources:\\nUnable to answer from current evidence. Reason: validation_failed Action: provide a narrower query or an allowlisted source URL.",
                "route": {
                    "selected_route": "EVIDENCE",
                    "mode": "EVIDENCE",
                    "intent_class": "current_fact",
                    "reason": "router_classifier_mapper",
                    "query": request_text,
                    "utc": "2026-04-03T15:22:18Z",
                },
                "status": "completed",
            }

            state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v7/state"))
            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "last_request_result.json").write_text(json.dumps(payload) + "\\n", encoding="utf-8")
            with open(state_dir / "request_history.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\\n")
            print(json.dumps(payload))
            """,
        )

    def write_current_state(self) -> None:
        write_json(
            self.current_state_path,
            {
                "schema_version": 1,
                "profile": "opt-experimental-v7-dev",
                "mode": "auto",
                "conversation": "on",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-04-03T15:11:31Z",
            },
        )

    def write_runtime_lifecycle(self) -> None:
        write_json(self.runtime_lifecycle_path, {"running": True, "status": "running", "pid": 12345})


def wait_for(predicate, app, timeout_seconds: float, label: str) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise SystemExit(f"Timed out waiting for {label}")


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_executable(path: Path, source: str) -> None:
    path.write_text(textwrap.dedent(source).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


if __name__ == "__main__":
    raise SystemExit(main())
