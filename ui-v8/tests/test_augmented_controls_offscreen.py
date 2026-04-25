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
    with tempfile.TemporaryDirectory(prefix="augmented_controls_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()
        sandbox.install_runtime_control_tool()
        sandbox.install_runtime_request_tool()
        sandbox.write_current_state(augmentation_policy="disabled", augmented_provider="wikipedia")
        sandbox.write_runtime_lifecycle()

        from PySide6.QtWidgets import QApplication, QFrame
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.show()
        app.processEvents()
        window.refresh_runtime_state()
        app.processEvents()

        labels = window.status_panel._runtime_summary_labels
        assert_ok(window.conversation_panel.objectName() == "shellCard", "conversation panel should keep shell card container styling")
        assert_ok(window.conversation_panel.layout().contentsMargins().top() == 14, "conversation shell margins should match card layout spacing")
        assert_ok(window.conversation_panel._scroll_area is not None, "conversation panel should contain an internal scroll area")
        assert_ok(
            window.conversation_panel._scroll_area.parent() is window.conversation_panel,
            "scroll area should be nested inside conversation panel shell",
        )
        assert_ok(
            window.conversation_panel._scroll_area.frameShape() == QFrame.NoFrame,
            "conversation inner scroll area should not draw an extra frame over the shell",
        )
        assert_ok(
            not window.conversation_panel._scroll_area.viewport().autoFillBackground(),
            "conversation scroll viewport should not paint an opaque fallback background",
        )
        assert_ok(
            window.control_panel._current_values["conversation"] == "off",
            "initial conversation mode should follow current_state truth",
        )
        assert_ok(
            window.control_panel._current_values["augmentation_policy"] == "disabled",
            "initial augmented policy should follow current_state truth",
        )
        assert_ok(
            window.control_panel._current_values["augmented_provider"] == "wikipedia",
            "initial augmented provider should follow current_state truth",
        )
        assert_ok(labels["Augmented Policy"].text() == "disabled", "status should show disabled policy")
        assert_ok(labels["Configured Provider"].text() == "wikipedia", "status should show configured wikipedia provider")
        assert_ok(labels["Configured Provider Paid"].text() == "no", "status should classify configured wikipedia as unpaid")
        assert_ok(labels["Last Request Provider"].text() == "unknown", "status should show unknown last-request provider before any request")
        assert_ok(labels["Last Request Paid"].text() == "unknown", "status should show unknown last-request paid flag before any request")

        window.control_panel.conversation_change_requested.emit("on")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["conversation"] == "on"
            ),
            app,
            5.0,
            "set conversation on",
        )
        window.control_panel.augmented_provider_change_requested.emit("openai")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["augmented_provider"] == "openai"
            ),
            app,
            5.0,
            "set augmented provider openai",
        )
        window.control_panel.augmented_policy_change_requested.emit("direct_allowed")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["augmentation_policy"] == "direct_allowed"
            ),
            app,
            5.0,
            "set augmentation policy direct_allowed",
        )
        window.refresh_runtime_state()
        app.processEvents()

        current_state = sandbox.load_json(sandbox.current_state_path)
        assert_ok(current_state.get("conversation") == "on", "conversation change should persist via runtime_control")
        assert_ok(current_state.get("augmented_provider") == "openai", "provider change should persist via runtime_control")
        assert_ok(
            current_state.get("augmentation_policy") == "direct_allowed",
            "policy change should persist via runtime_control",
        )
        assert_ok(labels["Augmented Policy"].text() == "direct_allowed", "status should reflect direct_allowed")
        assert_ok(labels["Configured Provider"].text() == "openai", "status should reflect configured openai")
        assert_ok(labels["Configured Provider Paid"].text() == "yes", "status should classify configured openai as paid")

        window._handle_submit_requested("plain local request with no external context")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "direct_allowed normal submit")
        normal_outcome = latest_outcome(window)
        assert_ok(normal_outcome.get("final_mode") == "LOCAL", "normal routing should stay local without explicit override")
        assert_ok(
            str(normal_outcome.get("augmented_provider_used", "")).lower() == "none",
            "normal routing should not fabricate augmented usage",
        )
        assert_ok(labels["Last Request Provider"].text() == "none", "status should show that the last local request used no augmented provider")
        assert_ok(labels["Last Request Paid"].text() == "no", "status should show no paid provider on local request")

        window._handle_interface_level_selected("advanced")
        app.processEvents()
        window.resize(980, 360)
        app.processEvents()
        assert_ok(window.height() <= 620, "window should be allowed to reduce below the previous oversized minimum height")
        scroll_area = window.conversation_panel._scroll_area
        assert_ok(scroll_area is not None, "conversation panel should expose a scroll area for short windows")
        assert_ok(
            scroll_area.verticalScrollBar().maximum() > 0,
            "reduced height should enable scrolling so bottom controls remain reachable",
        )
        assert_ok(
            not window.conversation_panel._force_augmented_once_checkbox.isHidden(),
            "force-augmented-once control should be available in advanced view",
        )
        checkbox = window.conversation_panel._force_augmented_once_checkbox
        top_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().topLeft())
        bottom_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().bottomLeft())
        assert_ok(
            top_left.y() > scroll_area.viewport().height() or bottom_left.y() > scroll_area.viewport().height(),
            "before scrolling, reduced-height layout should place the bottom control below viewport",
        )
        scroll_area.ensureWidgetVisible(window.conversation_panel._force_augmented_once_checkbox)
        app.processEvents()
        top_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().topLeft())
        bottom_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().bottomLeft())
        assert_ok(
            top_left.y() >= 0 and bottom_left.y() <= scroll_area.viewport().height(),
            "after scrolling, force-augmented-once control should be visible in viewport",
        )
        window.conversation_panel._force_augmented_once_checkbox.setChecked(True)
        window._handle_submit_requested("plain local request with no external context")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "forced direct submit")
        forced_outcome = latest_outcome(window)
        assert_ok(forced_outcome.get("final_mode") == "AUGMENTED", "forced submit should run augmented path")
        assert_ok(forced_outcome.get("augmented_provider_used") == "openai", "forced path should use selected provider")
        assert_ok(
            str(forced_outcome.get("augmented_provider_call_reason", "")).lower() == "direct",
            "forced path should report direct call reason",
        )
        assert_ok(
            str(forced_outcome.get("augmented_paid_provider_invoked", "")).lower() == "true",
            "forced openai path should report paid invocation",
        )
        assert_ok(
            str(forced_outcome.get("augmented_direct_request", "")) == "1",
            "forced path should expose augmented_direct_request metadata",
        )
        assert_ok(labels["Last Request Provider"].text() == "openai", "status should show openai as last request provider")
        assert_ok(labels["Last Request Paid"].text() == "yes", "status should show paid invocation for direct openai request")
        request_labels = window.status_panel._request_detail_labels
        assert_ok(
            request_labels["Augmented Direct Request"].text() == "1",
            "request diagnostics should show one-shot direct override metadata",
        )
        assert_ok(
            not window.conversation_panel._force_augmented_once_checkbox.isChecked(),
            "force-augmented-once should reset after one submit",
        )
        assert_ok(
            labels["Session Augmented Calls"].text() == "1",
            f"forced direct submit should increment augmented counter once, got={labels['Session Augmented Calls'].text()!r}",
        )

        window._handle_submit_requested("plain local request with no external context")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "post-once submit")
        post_once_outcome = latest_outcome(window)
        assert_ok(post_once_outcome.get("final_mode") == "LOCAL", "one-shot override must not persist to later submits")
        assert_ok(
            str(post_once_outcome.get("augmented_direct_request", "")) in {"", "0", "false"},
            "non-forced submit should not report direct override",
        )

        window.control_panel.augmented_provider_change_requested.emit("wikipedia")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["augmented_provider"] == "wikipedia"
            ),
            app,
            5.0,
            "set augmented provider wikipedia",
        )
        window.control_panel.augmented_policy_change_requested.emit("fallback_only")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["augmentation_policy"] == "fallback_only"
            ),
            app,
            5.0,
            "set augmentation policy fallback_only",
        )
        window.refresh_runtime_state()
        app.processEvents()
        assert_ok(labels["Augmented Policy"].text() == "fallback_only", "status should reflect fallback_only")
        assert_ok(labels["Configured Provider"].text() == "wikipedia", "status should reflect configured wikipedia provider")
        assert_ok(labels["Configured Provider Paid"].text() == "no", "status should classify configured wikipedia as unpaid")

        window._handle_submit_requested("need internet context for this question")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "fallback_only submit")
        fallback_outcome = latest_outcome(window)
        assert_ok(fallback_outcome.get("final_mode") == "AUGMENTED", "fallback_only query should use augmented fallback")
        assert_ok(
            str(fallback_outcome.get("augmented_provider_call_reason", "")).lower() == "fallback",
            f"fallback path should report fallback reason, got={fallback_outcome.get('augmented_provider_call_reason')!r}",
        )
        assert_ok(fallback_outcome.get("augmented_provider_used") == "wikipedia", "fallback should use selected provider")
        assert_ok(
            str(fallback_outcome.get("augmented_paid_provider_invoked", "")).lower() == "false",
            "wikipedia fallback should not report paid invocation",
        )
        assert_ok(labels["Last Request Provider"].text() == "wikipedia", "status should show wikipedia as last request provider")
        assert_ok(labels["Last Request Paid"].text() == "no", "status should show unpaid last request fallback")
        assert_ok(
            labels["Session Augmented Calls"].text() == "2",
            f"fallback submit should increment augmented counter, got={labels['Session Augmented Calls'].text()!r}",
        )

        window.control_panel.augmented_policy_change_requested.emit("disabled")
        wait_for(
            lambda: (
                not window._any_backend_action_in_flight()
                and window.control_panel._current_values["augmentation_policy"] == "disabled"
            ),
            app,
            5.0,
            "set augmentation policy disabled",
        )
        window.refresh_runtime_state()
        app.processEvents()
        assert_ok(labels["Augmented Policy"].text() == "disabled", "status should reflect disabled policy")

        window._handle_submit_requested("augment this should be blocked")
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "disabled submit")
        disabled_outcome = latest_outcome(window)
        assert_ok(disabled_outcome.get("final_mode") == "LOCAL", "disabled policy should keep final mode local")
        assert_ok(
            str(disabled_outcome.get("augmented_provider_call_reason", "")).lower() == "disabled",
            "disabled policy should report disabled call reason",
        )
        assert_ok(
            str(disabled_outcome.get("augmented_provider_used", "")).lower() == "none",
            "disabled policy should not report augmented provider usage",
        )
        assert_ok(labels["Last Request Provider"].text() == "none", "status should show none for disabled non-augmented request")
        assert_ok(labels["Last Request Paid"].text() == "no", "status should show no paid provider for disabled request")

        assert_ok(
            labels["Session Augmented Calls"].text() == "2",
            f"only forced-direct plus fallback should count, got={labels['Session Augmented Calls'].text()!r}",
        )
        assert_ok(labels["Session Paid Augmented Calls"].text() == "1", "only paid openai call should increment paid counter")
        assert_ok(
            labels["Session Provider Counts"].text() == "openai=1 grok=0 wikipedia=1",
            "provider session counters should reflect forced-direct/fallback usage",
        )

        window._handle_interface_level_selected("advanced")
        app.processEvents()
        window.resize(1460, 900)
        app.processEvents()
        assert_ok(not window.event_log_panel.isHidden(), "advanced level should expose event log")
        assert_ok(
            window.event_log_panel.height() < window.conversation_panel.height(),
            "event log should remain smaller than the main conversation work area",
        )
        assert_ok(
            window.event_log_panel.height() <= int(window.conversation_panel.height() * 0.45),
            "event log default height should not consume excessive vertical space",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("AUGMENTED_CONTROLS_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / "lucy" / "snapshots" / "opt-experimental-v7-dev" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v7" / "state"
        self.logs_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v7" / "logs"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
        self.tools_dir.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

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

    def install_runtime_control_tool(self) -> None:
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")

    def install_runtime_request_tool(self) -> None:
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
                print(json.dumps({"status": "failed", "error": "invalid args"}))
                raise SystemExit(2)

            request_text = args[2]
            state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v7/state"))
            state_path = state_dir / "current_state.json"
            state = {}
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    state = {}

            policy = str(state.get("augmentation_policy", "disabled")).strip().lower()
            provider = str(state.get("augmented_provider", "wikipedia")).strip().lower()
            trigger = "augment" in request_text.lower() or "internet" in request_text.lower()
            force_direct_env = str(os.environ.get("LUCY_AUGMENTED_DIRECT_REQUEST", "0")).strip().lower() in {"1", "true", "yes", "on"}
            force_direct = force_direct_env or ("--augmented-direct-once" in args)
            paid_provider = provider in {"openai", "grok"}

            final_mode = "LOCAL"
            outcome_code = "answered"
            provider_used = "none"
            call_reason = "not_needed"
            paid_invoked = False

            if policy == "direct_allowed" and force_direct:
                final_mode = "AUGMENTED"
                outcome_code = "augmented_answer"
                provider_used = provider
                call_reason = "direct"
                paid_invoked = paid_provider
            elif policy == "direct_allowed" and trigger:
                final_mode = "AUGMENTED"
                outcome_code = "augmented_answer"
                provider_used = provider
                call_reason = "direct"
                paid_invoked = paid_provider
            elif policy == "fallback_only" and trigger:
                final_mode = "AUGMENTED"
                outcome_code = "augmented_fallback_answer"
                provider_used = provider
                call_reason = "fallback"
                paid_invoked = paid_provider
            elif policy == "disabled" and trigger:
                call_reason = "disabled"

            payload = {
                "accepted": True,
                "completed_at": "2026-03-25T00:00:00Z",
                "control_state": {
                    "mode": str(state.get("mode", "auto")),
                    "conversation": str(state.get("conversation", "off")),
                    "memory": str(state.get("memory", "on")),
                    "evidence": str(state.get("evidence", "on")),
                    "voice": str(state.get("voice", "off")),
                    "augmentation_policy": policy,
                    "augmented_provider": provider,
                },
                "error": "",
                "outcome": {
                    "action_hint": "",
                    "evidence_created": "false",
                    "outcome_code": outcome_code,
                    "rc": 0,
                    "utc": "2026-03-25T00:00:00Z",
                    "final_mode": final_mode,
                    "augmented_provider_selected": provider,
                    "augmented_provider_used": provider_used,
                    "augmented_provider_call_reason": call_reason,
                    "augmented_paid_provider_invoked": paid_invoked,
                    "augmented_direct_request": "1" if force_direct else "0",
                },
                "request_id": f"req-augmented-control-{time.time_ns()}",
                "request_text": request_text,
                "response_text": "synthetic offscreen response",
                "route": {
                    "mode": "AUGMENTED" if final_mode == "AUGMENTED" else "LOCAL",
                    "query": request_text,
                    "reason": "offscreen-augmented-controls-test",
                    "session_id": "",
                    "utc": "2026-03-25T00:00:00Z",
                },
                "status": "completed",
            }

            state_dir.mkdir(parents=True, exist_ok=True)
            (state_dir / "last_request_result.json").write_text(json.dumps(payload) + "\\n", encoding="utf-8")
            with open(state_dir / "request_history.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\\n")
            print(json.dumps(payload))
            """,
        )

    def write_current_state(self, *, augmentation_policy: str, augmented_provider: str) -> None:
        write_json(
            self.current_state_path,
            {
                "schema_version": 1,
                "profile": "test-profile",
                "mode": "auto",
                "conversation": "off",
                "memory": "on",
                "evidence": "on",
                "voice": "off",
                "augmentation_policy": augmentation_policy,
                "augmented_provider": augmented_provider,
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-25T00:00:00Z",
            },
        )

    def write_runtime_lifecycle(self) -> None:
        write_json(self.runtime_lifecycle_path, {"running": True, "status": "running", "pid": 54321})

    def load_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))


def latest_outcome(window) -> dict[str, object]:
    details = window._latest_request_details
    assert_ok(isinstance(details, dict), "latest request details should be available after submit")
    outcome = details.get("outcome")
    assert_ok(isinstance(outcome, dict), "outcome metadata should be present after submit")
    return outcome


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
