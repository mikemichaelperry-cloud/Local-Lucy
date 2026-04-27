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
    with tempfile.TemporaryDirectory(prefix="self_review_ui_") as tmp_dir:
        sandbox = Sandbox(Path(tmp_dir))
        sandbox.prepare_import_environment()
        sandbox.install_runtime_control_tool()
        sandbox.install_runtime_request_tool()
        sandbox.write_current_state(mode="auto")
        sandbox.write_runtime_lifecycle()

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.show()
        app.processEvents()
        window.refresh_runtime_state()
        app.processEvents()

        trigger = "review your own code and suggest broad architecture improvements"

        window._handle_submit_requested(trigger)
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()

        assert_ok(not sandbox.invocation_log_path.exists(), "operator view should not dispatch self-review requests")

        window._handle_interface_level_selected("advanced")
        app.processEvents()
        window._handle_submit_requested(trigger)
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "advanced self-review submit")

        invocations = sandbox.load_invocations()
        assert_ok(invocations == ["submit-review"], f"advanced auto self-review should use submit-review, got={invocations!r}")
        payload = sandbox.load_json(sandbox.last_request_result_path)
        assert_ok(payload.get("response_text") == "self review response", "self-review path should persist review response")
        outcome = payload.get("outcome", {})
        assert_ok(outcome.get("self_review_request") == "true", "self-review payload should mark read-only review mode")
        assert_ok(outcome.get("self_review_mode") == "read_only", "self-review payload should stay read-only")
        assert_ok(outcome.get("final_mode") == "SELF_REVIEW", "self-review path should not report LOCAL/EVIDENCE/AUGMENTED")
        route = payload.get("route", {})
        assert_ok(route.get("selected_route") == "SELF_REVIEW", "self-review route should stay isolated from normal routing")

        sandbox.write_current_state(mode="online")
        window.refresh_runtime_state()
        app.processEvents()
        window._handle_submit_requested(trigger)
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()
        assert_ok(
            sandbox.load_invocations() == ["submit-review"],
            "self-review trigger should stay blocked outside auto mode",
        )

        sandbox.write_current_state(mode="auto")
        window.refresh_runtime_state()
        app.processEvents()
        broad_trigger = "review your own code and suggest broad Local Lucy v7 efficiency improvements"
        window._handle_submit_requested(broad_trigger)
        wait_for(lambda: not window._any_backend_action_in_flight(), app, 8.0, "advanced broad self-review submit")
        assert_ok(
            sandbox.load_invocations() == ["submit-review", "submit-review"],
            "broad self-review wording should still use bounded submit-review path",
        )
        payload = sandbox.load_json(sandbox.last_request_result_path)
        outcome = payload.get("outcome", {})
        assert_ok(outcome.get("self_review_request") == "true", "broad self-review should remain read-only review")
        assert_ok(outcome.get("self_review_mode") == "read_only", "broad self-review should stay read-only")
        assert_ok(outcome.get("final_mode") == "SELF_REVIEW", "broad self-review should not be reclassified into normal routing")

        window.close()
        window.deleteLater()
        app.processEvents()
        print("SELF_REVIEW_SUBMIT_OFFSCREEN_OK")
        return 0


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.home = root / "home"
        self.tools_dir = self.home / "lucy" / "snapshots" / "lucy-v8" / "tools"
        self.state_dir = self.home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
        self.current_state_path = self.state_dir / "current_state.json"
        self.runtime_lifecycle_path = self.state_dir / "runtime_lifecycle.json"
        self.last_request_result_path = self.state_dir / "last_request_result.json"
        self.request_history_path = self.state_dir / "request_history.jsonl"
        self.invocation_log_path = self.state_dir / "self_review_invocations.json"
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

    def install_runtime_control_tool(self) -> None:
        shutil.copy2(REPO_TOOLS_ROOT / "runtime_control.py", self.tools_dir / "runtime_control.py")

    def install_runtime_request_tool(self) -> None:
        write_executable(
            self.tools_dir / "runtime_request.py",
            f"""
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import time
            from pathlib import Path

            args = sys.argv[1:]
            if len(args) < 3 or args[1] != "--text":
                raise SystemExit(2)

            command = args[0]
            request_text = args[2]
            state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v8/state"))
            state_dir.mkdir(parents=True, exist_ok=True)
            invocation_log = state_dir / "self_review_invocations.json"
            invocations = []
            if invocation_log.exists():
                invocations = json.loads(invocation_log.read_text(encoding="utf-8"))
            invocations.append(command)
            invocation_log.write_text(json.dumps(invocations), encoding="utf-8")

            if command == "submit-review":
                response_text = "self review response"
                outcome = {{
                    "requested_mode": "SELF_REVIEW",
                    "final_mode": "SELF_REVIEW",
                    "trust_class": "read_only_self_review",
                    "outcome_code": "self_review_answered",
                    "self_review_request": "true",
                    "self_review_mode": "read_only",
                }}
                route = {{
                    "selected_route": "SELF_REVIEW",
                    "mode": "SELF_REVIEW",
                    "reason": "authorized_read_only_self_review",
                    "query": request_text,
                    "utc": "2026-03-26T00:00:00Z",
                }}
            else:
                response_text = "plain response"
                outcome = {{
                    "requested_mode": "AUTO",
                    "final_mode": "LOCAL",
                    "trust_class": "unverified",
                    "outcome_code": "answered",
                }}
                route = {{
                    "selected_route": "LOCAL",
                    "mode": "LOCAL",
                    "reason": "normal-submit",
                    "query": request_text,
                    "utc": "2026-03-26T00:00:00Z",
                }}

            payload = {{
                "accepted": True,
                "completed_at": "2026-03-26T00:00:00Z",
                "control_state": {{
                    "mode": "auto",
                    "memory": "on",
                    "evidence": "on",
                    "voice": "off",
                    "augmentation_policy": "disabled",
                    "augmented_provider": "wikipedia",
                    "model": "local-lucy",
                    "profile": "test-profile",
                }},
                "error": "",
                "outcome": outcome,
                "request_id": f"req-{{time.time_ns()}}",
                "request_text": request_text,
                "response_text": response_text,
                "route": route,
                "status": "completed",
            }}

            (state_dir / "last_request_result.json").write_text(json.dumps(payload) + "\\n", encoding="utf-8")
            with open(state_dir / "request_history.jsonl", "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\\n")
            print(json.dumps(payload))
            """,
        )

    def write_current_state(self, *, mode: str) -> None:
        write_json(
            self.current_state_path,
            {
                "schema_version": 1,
                "profile": "test-profile",
                "mode": mode,
                "memory": "on",
                "evidence": "on",
                "voice": "off",
                "augmentation_policy": "disabled",
                "augmented_provider": "wikipedia",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-26T00:00:00Z",
            },
        )

    def write_runtime_lifecycle(self) -> None:
        write_json(self.runtime_lifecycle_path, {"running": True, "status": "running", "pid": 54321})

    def load_invocations(self) -> list[str]:
        if not self.invocation_log_path.exists():
            return []
        return json.loads(self.invocation_log_path.read_text(encoding="utf-8"))

    def load_json(self, path: Path) -> dict[str, object]:
        return json.loads(path.read_text(encoding="utf-8"))


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
