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
    with tempfile.TemporaryDirectory(prefix="validated_insufficient_recovery_ui_") as tmp_dir:
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

        window._handle_submit_requested("Explain entropy in plain language")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "best effort recovery submit")
        app.processEvents()

        summary_text = window.conversation_panel._decision_trace_summary_button.text()
        assert_ok("EVIDENCE -> LOCAL" in summary_text, f"summary should reflect recovery landing on local path, got={summary_text!r}")
        assert_ok("best-effort recovery" in summary_text, f"summary should expose recovery note, got={summary_text!r}")
        assert_ok("trust=best-effort" in summary_text, f"summary should expose downgraded trust, got={summary_text!r}")

        request_summary = window.status_panel._request_summary_labels
        request_detail = window.status_panel._request_detail_labels
        answer_text = window.conversation_panel._history.toPlainText()
        expected_note = "Verification was insufficient, so a local best-effort answer was shown."
        assert_ok(
            request_summary["Answer Path"].text() == "Evidence insufficient -> local best-effort recovery",
            f"answer path should expose best-effort recovery, got={request_summary['Answer Path'].text()!r}",
        )
        assert_ok(
            request_summary["Trust"].text() == "best-effort",
            f"trust should stay visibly downgraded, got={request_summary['Trust'].text()!r}",
        )
        assert_ok(
            request_detail["Operator Note"].text() == expected_note,
            f"operator note should explain recovery, got={request_detail['Operator Note'].text()!r}",
        )
        assert_ok(
            request_detail["Verification Status"].text() == "unverified",
            f"verification status should remain visible, got={request_detail['Verification Status'].text()!r}",
        )
        assert_ok(
            request_detail["Estimated Confidence"].text() == "28% (Low, estimated)",
            f"estimated confidence should remain visible, got={request_detail['Estimated Confidence'].text()!r}",
        )
        assert_ok(
            request_detail["Source Basis"].text() == "local_model_background",
            f"source basis should remain visible, got={request_detail['Source Basis'].text()!r}",
        )
        assert_ok(
            request_detail["Primary Outcome"].text() == "validated_insufficient",
            f"primary truth should remain visible, got={request_detail['Primary Outcome'].text()!r}",
        )
        assert_ok(
            request_detail["Recovery Lane"].text() == "local_best_effort",
            f"recovery lane should remain visible, got={request_detail['Recovery Lane'].text()!r}",
        )
        assert_ok(
            "Path: Evidence insufficient -> local best-effort recovery" in answer_text,
            f"operator answer should expose best-effort path banner, got={answer_text!r}",
        )
        assert_ok(
            "Verification: unverified | Confidence: 28% (Low, estimated) | Source basis: local_model_background" in answer_text,
            f"operator answer should expose best-effort contract metadata, got={answer_text!r}",
        )

        summary_button = window.conversation_panel._decision_trace_summary_button
        summary_button.click()
        app.processEvents()
        trace_text = window._decision_trace_view.toPlainText()
        assert_ok(
            "Operator Summary: Recovery provided a local best-effort answer after insufficient evidence." in trace_text,
            "decision trace should explain the governed recovery outcome",
        )
        assert_ok(
            "Operator Trust: best-effort" in trace_text,
            "decision trace should expose downgraded trust",
        )
        assert_ok(
            "Primary Outcome Code: validated_insufficient" in trace_text,
            "decision trace should preserve the primary insufficiency truth",
        )
        assert_ok(
            "Recovery Lane: local_best_effort" in trace_text,
            "decision trace should expose the recovery lane",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("VALIDATED_INSUFFICIENT_RECOVERY_VISIBILITY_OFFSCREEN_OK")
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
                "completed_at": "2026-04-03T18:01:00Z",
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
                    "final_mode": "LOCAL",
                    "evidence_mode": "LIGHT",
                    "trust_class": "best_effort_unverified",
                    "outcome_code": "best_effort_recovery_answer",
                    "action_hint": "",
                    "answer_class": "best_effort_recovery_answer",
                    "provider_authorization": "not_applicable",
                    "operator_trust_label": "best-effort",
                    "operator_answer_path": "Evidence insufficient -> local best-effort recovery",
                    "operator_note": "Verification was insufficient, so a local best-effort answer was shown.",
                    "fallback_used": "true",
                    "fallback_reason": "validated_insufficient",
                    "primary_outcome_code": "validated_insufficient",
                    "primary_trust_class": "evidence_backed",
                    "recovery_attempted": "true",
                    "recovery_used": "true",
                    "recovery_eligible": "true",
                    "recovery_lane": "local_best_effort",
                    "augmented_provider": "none",
                    "augmented_provider_status": "not_used",
                    "augmented_provider_error_reason": "none",
                    "augmented_provider_used": "none",
                    "augmented_provider_call_reason": "none",
                    "augmented_direct_request": "false",
                    "evidence_created": "true",
                    "augmented_answer_contract": {
                        "answer": "Entropy is a measure of how spread out or unpredictable something is. In plain language, it tells you how many different arrangements are plausible before you learn more.",
                        "verification_status": "unverified",
                        "estimated_confidence_pct": 28,
                        "estimated_confidence_band": "Low",
                        "estimated_confidence_label": "28% (Low, estimated)",
                        "source_basis": ["local_model_background"],
                        "notes": "No allowlisted evidence confirmed this directly."
                    }
                },
                "request_id": f"req-best-effort-{time.time_ns()}",
                "request_text": request_text,
                "response_text": "Entropy is a measure of how spread out or unpredictable something is. In plain language, it tells you how many different arrangements are plausible before you learn more.",
                "route": {
                    "selected_route": "EVIDENCE",
                    "mode": "EVIDENCE",
                    "intent_class": "current_fact",
                    "reason": "router_classifier_mapper",
                    "query": request_text,
                    "utc": "2026-04-03T18:00:52Z"
                },
                "status": "completed"
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
                "last_updated": "2026-04-03T18:00:40Z",
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
