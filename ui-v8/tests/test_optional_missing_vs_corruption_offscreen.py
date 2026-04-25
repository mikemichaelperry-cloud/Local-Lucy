#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path


REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="optional_missing_vs_corruption_") as tmp_dir:
        home = Path(tmp_dir) / "home"
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
                "augmentation_policy": "direct_allowed",
                "augmented_provider": "openai",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-04-03T20:00:00Z",
            },
        )
        write_json(state_dir / "runtime_lifecycle.json", {"running": True, "status": "running", "pid": 12345})
        (state_dir / "last_route.json").write_text("{invalid json\n", encoding="utf-8")

        os.environ["HOME"] = str(home)
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        os.environ["LUCY_UI_STATE_DIR"] = str(state_dir)
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
        window.show()
        window.refresh_runtime_state()
        window._handle_interface_level_selected("advanced")
        app.processEvents()

        runtime_summary = window.status_panel._runtime_summary_labels
        runtime_detail = window.status_panel._runtime_detail_labels
        assert_ok(
            runtime_summary["Current Route"].text() == "invalid json",
            f"corrupted optional route artifact should remain visible as invalid json, got={runtime_summary['Current Route'].text()!r}",
        )
        assert_ok(
            runtime_summary["Source Type"].text() == "invalid json",
            f"corrupted optional route details should remain visible as invalid json, got={runtime_summary['Source Type'].text()!r}",
        )
        assert_ok(
            runtime_detail["Preprocess Active"].text() == "not yet populated",
            f"missing optional preprocess artifact should stay neutral, got={runtime_detail['Preprocess Active'].text()!r}",
        )
        assert_ok(
            runtime_detail["Reduced Scope"].text() == "not yet populated",
            f"missing optional preprocess detail should stay neutral, got={runtime_detail['Reduced Scope'].text()!r}",
        )

        window.close()
        window.deleteLater()
        app.processEvents()
        print("OPTIONAL_MISSING_VS_CORRUPTION_OFFSCREEN_OK")
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
