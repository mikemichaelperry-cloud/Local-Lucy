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
    with tempfile.TemporaryDirectory(prefix="decision_trace_ui_") as tmp_dir:
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

        summary_button = window.conversation_panel._decision_trace_summary_button
        assert_ok(not summary_button.isEnabled(), "decision trace summary should start disabled without request metadata")
        assert_ok(window._decision_trace_panel.isHidden(), "decision trace drawer should start collapsed")

        window._handle_submit_requested("show me the latest AI lab policy updates")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "decision trace submit")
        app.processEvents()

        summary_text = summary_button.text()
        assert_ok(summary_button.isEnabled(), "decision trace summary should enable after request metadata arrives")
        assert_ok("AUGMENTED -> OPENAI" in summary_text, f"summary should show requested/effective path, got={summary_text!r}")
        assert_ok(
            "trust=unverified_with_extended_context_for_operator_review" in summary_text,
            f"summary should expose trust class, got={summary_text!r}",
        )
        assert_ok(
            summary_button.sizeHint().width() > summary_button.width(),
            "long summary should be width-constrained in compact layout for tooltip coverage",
        )
        assert_ok(
            summary_button.toolTip() == summary_text,
            "summary tooltip should expose the full unclipped decision trace summary",
        )
        assert_ok(window._decision_trace_panel.isHidden(), "decision trace drawer should remain collapsed until activated")

        summary_button.click()
        app.processEvents()

        assert_ok(not window._decision_trace_panel.isHidden(), "activating summary should reveal decision trace drawer")
        trace_text = window._decision_trace_view.toPlainText()
        assert_ok("Requested Mode: AUGMENTED" in trace_text, "drawer should render requested mode")
        assert_ok("Effective Mode: AUGMENTED" in trace_text, "drawer should render effective mode")
        assert_ok("Requested Route:" not in trace_text, "drawer should omit requested route when payload does not provide one")
        assert_ok("Selected Route: AUGMENTED" in trace_text, "drawer should render selected route")
        assert_ok("Intent Classification: policy_ai" in trace_text, "drawer should render intent classification")
        assert_ok("Evidence Mode: validated" in trace_text, "drawer should render evidence mode")
        assert_ok("Augmented Provider: openai" in trace_text, "drawer should render augmented provider")
        assert_ok(
            "Provider Selection Reason: synthesis/explanation task" in trace_text,
            "drawer should render provider selection reason when available",
        )
        assert_ok(
            "Provider Selection Query: explain entropy in plain english with engineering intuition" in trace_text,
            "drawer should render normalized provider selection query when available",
        )
        assert_ok(
            "Provider Selection Rule: plain_explanation" in trace_text,
            "drawer should render provider selection rule when available",
        )
        assert_ok(
            "Verification Status: unverified" in trace_text,
            "drawer should render verification status when an augmented contract is present",
        )
        assert_ok(
            "Estimated Confidence: 34% (Low, estimated)" in trace_text,
            "drawer should render estimated confidence when an augmented contract is present",
        )
        assert_ok(
            "Source Basis: augmented_provider_openai, local_model_background" in trace_text,
            "drawer should render source basis when an augmented contract is present",
        )
        assert_ok(
            "Trust Class: unverified_with_extended_context_for_operator_review" in trace_text,
            "drawer should render trust class",
        )
        assert_ok("Outcome Code: augmented_answer" in trace_text, "drawer should render outcome code")
        assert_ok("Reason: offscreen decision trace test" in trace_text, "drawer should render available reason text")

        window.close()
        window.deleteLater()
        app.processEvents()
        print("DECISION_TRACE_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / "lucy" / "snapshots" / "opt-experimental-v7-dev" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v7" / "state"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
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
                "completed_at": "2026-03-25T00:00:00Z",
                "control_state": {
                    "mode": "online",
                    "memory": "on",
                    "evidence": "validated",
                    "voice": "off",
                    "augmentation_policy": "direct_allowed",
                    "augmented_provider": "openai",
                },
                "error": "",
                "outcome": {
                    "requested_mode": "AUGMENTED",
                    "final_mode": "AUGMENTED",
                    "evidence_mode": "validated",
                    "trust_class": "unverified_with_extended_context_for_operator_review",
                    "outcome_code": "augmented_answer",
                    "action_hint": "none",
                    "fallback_used": "false",
                    "augmented_provider": "openai",
                    "augmented_provider_used": "openai",
                    "augmented_provider_call_reason": "direct",
                    "augmented_provider_status": "available",
                    "augmented_provider_selection_reason": "synthesis/explanation task",
                    "augmented_provider_selection_query": "explain entropy in plain english with engineering intuition",
                    "augmented_provider_selection_rule": "plain_explanation",
                    "augmented_direct_request": "0",
                    "augmented_answer_contract": {
                        "answer": "synthetic decision trace response",
                        "verification_status": "unverified",
                        "estimated_confidence_pct": 34,
                        "estimated_confidence_band": "Low",
                        "estimated_confidence_label": "34% (Low, estimated)",
                        "source_basis": ["augmented_provider_openai", "local_model_background"],
                        "provider_status": "available",
                        "notes": "No allowlisted evidence confirmed this directly."
                    },
                },
                "request_id": f"req-trace-{time.time_ns()}",
                "request_text": request_text,
                "response_text": "synthetic decision trace response",
                "route": {
                    "selected_route": "AUGMENTED",
                    "mode": "AUGMENTED",
                    "intent_class": "policy_ai",
                    "reason": "offscreen decision trace test",
                    "query": request_text,
                    "utc": "2026-03-25T00:00:00Z",
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
                "profile": "test-profile",
                "mode": "online",
                "memory": "on",
                "evidence": "on",
                "voice": "off",
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-25T00:00:00Z",
            },
        )

    def write_runtime_lifecycle(self) -> None:
        write_json(self.runtime_lifecycle_path, {"running": True, "status": "running", "pid": 54321})


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


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
