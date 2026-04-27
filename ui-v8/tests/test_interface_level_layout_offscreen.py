#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="interface_level_layout_") as tmp_dir:
        home = Path(tmp_dir) / "home"
        state_dir = home / "lucy" / "runtime" / "state"
        tools_dir = home / "lucy" / "snapshots" / "lucy-v8" / "tools"
        state_dir.mkdir(parents=True, exist_ok=True)
        tools_dir.mkdir(parents=True, exist_ok=True)

        write_json(
            state_dir / "current_state.json",
            {
                "schema_version": 1,
                "profile": "test-profile",
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-03-25T00:00:00Z",
            },
        )
        write_json(state_dir / "runtime_lifecycle.json", {"running": True, "status": "running", "pid": 12345})
        write_json(
            state_dir / "voice_runtime.json",
            {"available": True, "status": "idle", "listening": False, "processing": False},
        )

        history_entries = [build_history_entry(index) for index in range(1, 8)]
        write_json(state_dir / "last_request_result.json", history_entries[-1])
        (state_dir / "request_history.jsonl").write_text(
            "".join(json.dumps(entry) + "\n" for entry in history_entries),
            encoding="utf-8",
        )

        os.environ["HOME"] = str(home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        # Set required runtime namespace root (parent of state_dir)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(state_dir.parent)
        # Set required authority contract variables
        os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(home / "lucy" / "snapshots" / "lucy-v8")
        os.environ["LUCY_UI_ROOT"] = str(REPO_UI_ROOT)
        os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
        sys.path.insert(0, str(REPO_UI_ROOT))

        from PySide6.QtWidgets import QApplication, QScrollArea, QWidget
        from app.main_window import OperatorConsoleWindow

        app = QApplication([])
        window = OperatorConsoleWindow()
        window.show()
        window.refresh_runtime_state()
        app.processEvents()

        assert_ok(set(window._level_buttons.keys()) == {"operator", "advanced"}, "only operator/advanced levels should be exposed")
        assert_ok("engineering" not in window._level_buttons, "engineering level should no longer be exposed")
        assert_ok("service" not in window._level_buttons, "service level should no longer be exposed")

        for level in ("advanced",):
            window._handle_interface_level_selected(level)
            window.resize(1200, 760)
            app.processEvents()

            control_scroll = window.control_panel._scroll_area
            status_scroll = window.status_panel._scroll_area
            assert_ok(control_scroll is not None, f"{level}: control panel should expose an internal scroll area")
            assert_ok(status_scroll is not None, f"{level}: status panel should expose an internal scroll area")
            assert_ok(
                window.status_panel._runtime_summary_labels["Current Route"].text() == "not yet populated",
                f"{level}: optional route state should read as not yet populated",
            )
            assert_ok(
                window.status_panel._runtime_detail_labels["Preprocess Active"].text() == "not yet populated",
                f"{level}: optional preprocess state should read as not yet populated",
            )
            assert_ok(
                "file missing" not in window.status_panel._runtime_detail_labels["Voice Backend"].text().lower(),
                f"{level}: voice backend should avoid raw file-missing wording",
            )

            if level == "advanced":
                assert_ok(control_scroll.verticalScrollBar().maximum() > 0, "advanced: control panel should overflow vertically")
                assert_ok(status_scroll.verticalScrollBar().maximum() > 0, "advanced: status panel should overflow vertically")
                assert_section_usable(
                    app,
                    control_scroll,
                    window.control_panel._feature_group,
                    window.control_panel._augmented_provider_selector,
                    "advanced: runtime toggles",
                )
                assert_section_usable(
                    app,
                    status_scroll,
                    window.status_panel._request_detail_group,
                    window.status_panel._request_detail_cards["Control State"],
                    "advanced: request drill-down",
                )
                assert_section_usable(
                    app,
                    status_scroll,
                    window.status_panel._advanced_metadata_group,
                    window.status_panel._advanced_request_view,
                    "advanced: expanded runtime metadata",
                )
                assert_section_usable(
                    app,
                    status_scroll,
                    window.status_panel._history_maintenance_group,
                    window.status_panel._history_maintenance_view,
                    "advanced: history retention summary",
                )
                assert_ok(not window.event_log_panel.isHidden(), "advanced: event log should be visible")
        window.close()
        window.deleteLater()
        app.processEvents()
        print("INTERFACE_LEVEL_LAYOUT_OFFSCREEN_OK")
        return 0


def build_history_entry(index: int) -> dict[str, object]:
    return {
        "request_id": f"req-layout-{index}",
        "status": "completed",
        "completed_at": f"2026-03-25T00:00:0{index}Z",
        "request_text": f"layout diagnostic request {index}",
        "response_text": "synthetic response " * 24,
        "error": "",
        "route": {"mode": "AUGMENTED", "reason": "layout-test"},
        "outcome": {
            "outcome_code": "augmented_answer",
            "action_hint": "",
            "augmented_direct_request": "1",
            "evidence_created": "false",
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


def assert_section_usable(
    app,
    scroll_area: QScrollArea,
    section_widget: QWidget,
    target_widget: QWidget,
    label: str,
) -> None:
    assert_ok(section_widget is not None, f"{label}: section should exist")
    assert_ok(target_widget is not None, f"{label}: target widget should exist")
    assert_ok(section_widget.isVisible(), f"{label}: section should be visible at this interface level")
    assert_ok(target_widget.isVisible(), f"{label}: target widget should be visible at this interface level")

    minimum_height = section_widget.minimumSizeHint().height()
    assert_ok(
        section_widget.height() >= max(120, minimum_height - 12),
        f"{label}: section should retain practical height instead of collapsing",
    )
    target_minimum_height = target_widget.minimumSizeHint().height()
    assert_ok(
        target_widget.height() >= max(20, target_minimum_height - 8),
        f"{label}: key widget should retain practical height instead of collapsing",
    )

    content_widget = scroll_area.widget()
    assert_ok(content_widget is not None, f"{label}: scroll content should exist")
    scroll_bar = scroll_area.verticalScrollBar()
    target_top = target_widget.mapTo(content_widget, target_widget.rect().topLeft()).y()
    target_bottom = target_widget.mapTo(content_widget, target_widget.rect().bottomLeft()).y()

    scroll_bar.setValue(min(scroll_bar.maximum(), max(0, target_top)))
    app.processEvents()
    top_left = target_widget.mapTo(scroll_area.viewport(), target_widget.rect().topLeft())
    assert_ok(top_left.y() >= -8, f"{label}: section top should be reachable after scrolling")

    bottom_scroll = max(0, target_bottom - scroll_area.viewport().height())
    scroll_bar.setValue(min(scroll_bar.maximum(), bottom_scroll))
    app.processEvents()
    bottom_left = target_widget.mapTo(scroll_area.viewport(), target_widget.rect().bottomLeft())
    assert_ok(
        bottom_left.y() <= scroll_area.viewport().height() + 8,
        f"{label}: key widget bottom should be reachable after scrolling",
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
