#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="scroll_preservation_ui_") as tmp_dir:
        home = Path(tmp_dir) / "home"
        state_dir = home / ".codex-api-home" / "lucy" / "runtime-v7" / "state"
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
                "last_updated": "2026-04-08T00:00:00Z",
            },
        )
        write_json(state_dir / "runtime_lifecycle.json", {"running": True, "status": "running", "pid": 12345})
        write_json(
            state_dir / "voice_runtime.json",
            {"available": True, "status": "idle", "listening": False, "processing": False},
        )

        history_entries = [build_history_entry(index) for index in range(1, 10)]
        write_json(state_dir / "last_request_result.json", history_entries[-1])
        (state_dir / "request_history.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in history_entries),
            encoding="utf-8",
        )

        os.environ["HOME"] = str(home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # Set required runtime namespace root
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(home / ".codex-api-home" / "lucy" / "runtime-v7")
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = "/home/mike/lucy/snapshots/opt-experimental-v7-dev"
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

        from PySide6.QtWidgets import QApplication
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.show()
        window._handle_interface_level_selected("advanced")
        app.processEvents()
        for index in range(80):
            window._append_ui_event(f"[info] scroll test event {index}")
        app.processEvents()

        state_scroll = window.status_panel._advanced_state_view.verticalScrollBar()
        request_scroll = window.status_panel._advanced_request_view.verticalScrollBar()
        event_scroll = window.event_log_panel._log.verticalScrollBar()

        assert_ok(state_scroll.maximum() > 0, "status state view should overflow")
        assert_ok(request_scroll.maximum() > 0, "status request view should overflow")
        assert_ok(event_scroll.maximum() > 0, "event log should overflow")

        state_scroll.setValue(state_scroll.maximum() // 2)
        request_scroll.setValue(request_scroll.maximum() // 2)
        event_scroll.setValue(event_scroll.maximum() // 3)
        state_value = state_scroll.value()
        request_value = request_scroll.value()
        event_value = event_scroll.value()

        for cycle in range(1, 4):
            write_runtime_cycle(
                state_dir,
                cycle,
                suffix="!" * cycle,
                voice_status="listening" if cycle % 2 else "processing",
            )
            window.refresh_runtime_state()
            app.processEvents()
            app.processEvents()

            assert_ok(
                state_scroll.value() == state_value,
                f"state metadata scroll position should be preserved on cycle {cycle}",
            )
            assert_ok(
                request_scroll.value() == request_value,
                f"request metadata scroll position should be preserved on cycle {cycle}",
            )
            assert_ok(
                event_scroll.value() == event_value,
                f"event log should preserve manual scroll position on cycle {cycle}",
            )

        event_scroll.setValue(event_scroll.maximum())
        for cycle in range(4, 7):
            write_runtime_cycle(
                state_dir,
                cycle,
                suffix="!" * cycle,
                voice_status="listening" if cycle % 2 else "processing",
            )
            window.refresh_runtime_state()
            app.processEvents()
            app.processEvents()

            assert_ok(
                event_scroll.value() == event_scroll.maximum(),
                f"event log should stay pinned to bottom on cycle {cycle}",
            )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("SCROLL_PRESERVATION_OFFSCREEN_OK")
        return 0


def build_history_entry(index: int, *, suffix: str = "") -> dict[str, object]:
    return {
        "request_id": f"req-scroll-{index}",
        "status": "completed",
        "completed_at": f"2026-04-08T00:00:{index:02d}Z",
        "request_text": f"scroll preservation request {index}{suffix}",
        "response_text": "synthetic response " * 25,
        "error": "",
        "route": {"mode": "AUGMENTED", "reason": "scroll-test"},
        "outcome": {
            "outcome_code": "augmented_answer",
            "action_hint": "none",
            "augmented_direct_request": "1",
            "augmented_provider_status": "ok",
            "evidence_created": "true",
            "primary_outcome_code": "augmented_answer",
            "recovery_lane": "none",
        },
        "control_state": {
            "mode": "auto",
            "memory": "on",
            "evidence": "on",
            "voice": "on",
            "augmentation_policy": "direct_allowed",
            "augmented_provider": "openai",
        },
    }


def write_runtime_cycle(state_dir: Path, cycle: int, *, suffix: str, voice_status: str) -> None:
    mode = "online" if cycle % 2 else "offline"
    memory = "off" if cycle % 2 else "on"
    evidence = "off" if cycle % 2 else "on"
    augmentation_policy = "direct_allowed" if cycle % 2 else "disabled"
    augmented_provider = "openai" if cycle % 2 else "wikipedia"

    write_json(
        state_dir / "current_state.json",
        {
            "schema_version": 1,
            "profile": "test-profile",
            "mode": mode,
            "memory": memory,
            "evidence": evidence,
            "voice": "on",
            "augmentation_policy": augmentation_policy,
            "augmented_provider": augmented_provider,
            "model": "local-lucy",
            "approval_required": False,
            "status": "ready",
            "last_updated": f"2026-04-08T00:00:{cycle:02d}Z",
        },
    )
    write_json(
        state_dir / "voice_runtime.json",
        {
            "available": True,
            "status": voice_status,
            "listening": voice_status == "listening",
            "processing": voice_status == "processing",
        },
    )

    history_entries = [build_history_entry(index, suffix=suffix) for index in range(1, 10 + cycle)]
    write_json(state_dir / "last_request_result.json", history_entries[-1])
    (state_dir / "request_history.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in history_entries),
        encoding="utf-8",
    )


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
