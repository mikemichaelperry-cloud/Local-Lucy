#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="status_panel_augmented_") as tmp_dir:
        root = Path(tmp_dir)
        home = root / "home"
        state_dir = home / "lucy" / "runtime" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)

        write_json(
            state_dir / "current_state.json",
            {
                "schema_version": 1,
                "profile": "test-profile",
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "augmentation_policy": "disabled",
                "augmented_provider": "wikipedia",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-25T00:00:00Z",
            },
        )
        write_json(state_dir / "runtime_lifecycle.json", {"running": True, "status": "running", "pid": 12345})

        os.environ["HOME"] = str(home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # Set required runtime namespace root (parent of state_dir)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(state_dir.parent)
        # Set required authority contract variables
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(home / "lucy" / "snapshots" / "opt-experimental-v7-dev")
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.refresh_runtime_state()
        app.processEvents()

        labels = window.status_panel._runtime_summary_labels
        assert_ok(labels["Augmented Policy"].text() == "disabled", "augmented policy should reflect runtime truth")
        assert_ok(labels["Model"].text() == "local-lucy", "model should reflect runtime truth")
        assert_ok(labels["Configured Provider"].text() == "wikipedia", "configured provider should reflect runtime truth")
        assert_ok(labels["Configured Provider Paid"].text() == "no", "configured provider paid flag should reflect provider class")
        assert_ok(labels["Last Request Provider"].text() == "unknown", "last request provider should be unknown before any request")
        assert_ok(labels["Last Request Paid"].text() == "unknown", "last request paid status should be unknown before any request")
        assert_ok(labels["Session Augmented Calls"].text() == "0", "initial total counter should be 0")
        assert_ok(labels["Session Paid Augmented Calls"].text() == "0", "initial paid counter should be 0")
        assert_ok(
            labels["Session Provider Counts"].text() == "openai=0 kimi=0 wikipedia=0",
            "initial provider counters should be zeroed",
        )

        window._update_session_augmented_counters_from_payload(
            {
                "outcome": {
                    "final_mode": "AUGMENTED",
                    "outcome_code": "augmented_answer",
                    "augmented_provider_used": "openai",
                    "augmented_provider_call_reason": "direct",
                    "augmented_paid_provider_invoked": "true",
                }
            }
        )
        # Incomplete metadata should not fabricate counts.
        window._update_session_augmented_counters_from_payload(
            {
                "outcome": {
                    "final_mode": "AUGMENTED",
                    "outcome_code": "augmented_answer",
                    "augmented_provider_call_reason": "direct",
                }
            }
        )
        window._update_session_augmented_counters_from_payload(
            {
                "outcome": {
                    "final_mode": "AUGMENTED",
                    "outcome_code": "augmented_fallback_answer",
                    "augmented_provider_used": "wikipedia",
                    "augmented_provider_call_reason": "fallback",
                    "augmented_paid_provider_invoked": "false",
                }
            }
        )
        window.refresh_runtime_state()
        app.processEvents()

        assert_ok(labels["Last Request Provider"].text() == "unknown", "status should not fabricate provider usage from counters alone")
        assert_ok(labels["Last Request Paid"].text() == "unknown", "status should not fabricate paid usage from counters alone")
        assert_ok(labels["Session Augmented Calls"].text() == "2", "total counter should include only valid augmented usage")
        assert_ok(labels["Session Paid Augmented Calls"].text() == "1", "paid counter should increment only on explicit paid flag")
        assert_ok(
            labels["Session Provider Counts"].text() == "openai=1 kimi=0 wikipedia=1",
            "provider counters should reflect counted usage",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("STATUS_PANEL_AUGMENTED_COUNTERS_OFFSCREEN_OK")
        return 0


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
