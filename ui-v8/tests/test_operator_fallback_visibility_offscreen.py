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
    with tempfile.TemporaryDirectory(prefix="operator_fallback_ui_") as tmp_dir:
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

        window._handle_submit_requested("What are his current projects?")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "operator fallback submit")
        app.processEvents()

        summary_text = window.conversation_panel._decision_trace_summary_button.text()
        assert_ok("LOCAL -> OPENAI" in summary_text, f"decision trace should show local to openai path, got={summary_text!r}")
        assert_ok("local degraded" in summary_text, f"decision trace should expose degradation note, got={summary_text!r}")

        request_summary = window.status_panel._request_summary_labels
        request_detail = window.status_panel._request_detail_labels
        answer_text = window.conversation_panel._history.toPlainText()
        assert_ok(
            request_summary["Answer Path"].text() == "Local degraded -> OPENAI fallback",
            f"operator answer path should explain fallback, got={request_summary['Answer Path'].text()!r}",
        )
        assert_ok(
            request_summary["Trust"].text() == "unverified",
            f"operator trust should stay visible, got={request_summary['Trust'].text()!r}",
        )
        assert_ok(
            request_detail["Operator Note"].text() == "Escalated because the local answer degraded.",
            f"operator note should explain escalation, got={request_detail['Operator Note'].text()!r}",
        )
        assert_ok(
            request_detail["Verification Status"].text() == "unverified",
            f"verification status should remain visible, got={request_detail['Verification Status'].text()!r}",
        )
        assert_ok(
            request_detail["Estimated Confidence"].text() == "34% (Low, estimated)",
            f"estimated confidence should remain visible, got={request_detail['Estimated Confidence'].text()!r}",
        )
        assert_ok(
            request_detail["Source Basis"].text() == "augmented_provider_openai, local_model_background",
            f"source basis should remain visible, got={request_detail['Source Basis'].text()!r}",
        )
        assert_ok(
            "Path: Local degraded -> OPENAI fallback" in answer_text,
            f"operator answer should expose concise path banner, got={answer_text!r}",
        )
        assert_ok(
            "Verification: unverified | Confidence: 34% (Low, estimated) | Source basis: augmented_provider_openai, local_model_background" in answer_text,
            f"operator answer should expose concise augmented contract metadata, got={answer_text!r}",
        )
        assert_ok(
            "Augmented fallback (unverified answer):" not in answer_text,
            "operator answer should hide backend fallback scaffolding",
        )
        assert_ok(
            "Instruction:" not in answer_text and "Unverified context" not in answer_text,
            "operator answer should hide backend prompt residue",
        )
        assert_ok(
            window.conversation_panel._history.verticalScrollBar().maximum() == 0,
            "operator answer should expand to fit long content instead of truncating behind an inner scrollbar",
        )
        assert_ok(
            window.conversation_panel._history.height() >= 260,
            f"operator answer should grow for long responses, got height={window.conversation_panel._history.height()}",
        )

        summary_button = window.conversation_panel._decision_trace_summary_button
        summary_button.click()
        app.processEvents()
        trace_text = window._decision_trace_view.toPlainText()
        assert_ok(
            "Operator Summary: Escalated from degraded local answer to OPENAI fallback." in trace_text,
            "decision trace drawer should include the plain-English operator summary",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("OPERATOR_FALLBACK_VISIBILITY_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / "lucy" / "snapshots" / "lucy-v8" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
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
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(self.home / "lucy" / "snapshots" / "lucy-v8")
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
            answer_text = (
                "OpenAI-assisted fallback response for a longer wrapped operator-output scenario. "
                "Use boneless chicken breasts, season them well, brown them in batches, and then "
                "build the tomato sauce with onion, garlic, olive oil, crushed tomatoes, basil, and oregano. "
                "Let the sauce reduce before returning the chicken to finish gently so the meat stays tender. "
                "Keep enough sauce loose for serving, and spoon extra over the chicken so the full answer "
                "needs multiple wrapped lines inside the operator pane."
            )
            payload = {
                "accepted": True,
                "completed_at": "2026-03-29T00:00:00Z",
                "control_state": {
                    "mode": "auto",
                    "memory": "on",
                    "evidence": "on",
                    "voice": "off",
                    "augmentation_policy": "fallback_only",
                    "augmented_provider": "openai",
                    "model": "local-lucy",
                    "profile": "lucy-v8",
                },
                "error": "",
                "outcome": {
                    "requested_mode": "LOCAL",
                    "final_mode": "AUGMENTED",
                    "evidence_mode": "",
                    "trust_class": "evidence_backed",
                    "outcome_code": "augmented_fallback_answer",
                    "action_hint": "",
                    "answer_class": "augmented_unverified_fallback",
                    "provider_authorization": "authorized_by_runtime_state",
                    "operator_trust_label": "unverified",
                    "operator_answer_path": "Local degraded -> OPENAI fallback",
                    "operator_note": "Escalated because the local answer degraded.",
                    "fallback_used": "false",
                    "fallback_reason": "local_generation_degraded",
                    "augmented_provider": "openai",
                    "augmented_provider_used": "openai",
                    "augmented_provider_status": "available",
                    "augmented_provider_call_reason": "fallback",
                    "augmented_provider_selection_reason": "explicit provider selection",
                    "augmented_provider_selection_query": "none",
                    "augmented_provider_selection_rule": "explicit_provider",
                    "augmented_direct_request": "0",
                    "evidence_created": "false",
                    "augmented_answer_contract": {
                        "answer": answer_text,
                        "verification_status": "unverified",
                        "estimated_confidence_pct": 34,
                        "estimated_confidence_band": "Low",
                        "estimated_confidence_label": "34% (Low, estimated)",
                        "source_basis": ["augmented_provider_openai", "local_model_background"],
                        "provider_status": "available",
                        "notes": "No allowlisted evidence confirmed this directly."
                    }
                },
                "request_id": f"req-fallback-{time.time_ns()}",
                "request_text": request_text,
                "response_text": "Augmented fallback (unverified answer):\\n" + answer_text,
                "route": {
                    "selected_route": "LOCAL",
                    "mode": "LOCAL",
                    "intent_class": "local_answer",
                    "reason": "router_classifier_mapper",
                    "query": request_text,
                    "utc": "2026-03-29T00:00:00Z",
                },
                "status": "completed",
            }

            state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v8/state"))
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
                "profile": "lucy-v8",
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "off",
                "augmentation_policy": "fallback_only",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-29T00:00:00Z",
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
