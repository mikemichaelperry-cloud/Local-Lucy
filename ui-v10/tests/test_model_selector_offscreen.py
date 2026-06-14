#!/usr/bin/env python3
"""Offscreen test for model selector integration."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def test_model_selector():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"))
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v10")
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.state_store import STATE_DIRECTORY
    from app.main_window import OperatorConsoleWindow
    from PySide6.QtWidgets import QApplication

    # Ensure state directory exists with a known model
    STATE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIRECTORY / "current_state.json"
    state_file.write_text(
        json.dumps({
            "schema_version": 1,
            "profile": "lucy-v10",
            "mode": "auto",
            "conversation": "on",
            "memory": "on",
            "evidence": "on",
            "voice": "off",
            "augmentation_policy": "disabled",
            "augmented_provider": "wikipedia",
            "model": "local-lucy",
            "approval_required": False,
            "status": "ready",
            "last_updated": "2026-03-25T00:00:00Z",
        }, indent=2),
        encoding="utf-8",
    )

    app = QApplication([])
    window = OperatorConsoleWindow()
    window.show()
    app.processEvents()
    window.refresh_runtime_state()
    app.processEvents()

    # 1. Model selector should reflect runtime state
    model_selector = window.control_panel._model_selector
    assert_ok(model_selector is not None, "control panel should expose model selector")
    assert_ok(
        model_selector.currentText() == "local-lucy (qwen3 14B)",
        f"model selector should reflect current state, got={model_selector.currentText()!r}",
    )

    # 2. Status panel should show the model
    status_labels = window.status_panel._runtime_summary_labels
    assert_ok(
        status_labels["Model"].text() == "local-lucy",
        f"status panel should show active model, got={status_labels['Model'].text()!r}",
    )

    # 3. Available models should include the expected option
    items = [model_selector.itemText(i) for i in range(model_selector.count())]
    assert_ok("local-lucy (qwen3 14B)" in items, "model selector should offer local-lucy")

    # 4. Changing model should emit signal
    # Prime _current_values so the control panel sees a change
    window.control_panel._current_values["model"] = "other-model"
    received: list[str] = []
    window.control_panel.model_change_requested.connect(lambda v: received.append(v))
    model_selector.setCurrentIndex(model_selector.findText("local-lucy (qwen3 14B)"))
    model_selector.activated.emit(model_selector.currentIndex())
    app.processEvents()
    assert_ok(
        received == ["local-lucy"],
        f"model change signal should emit selected model, got={received!r}",
    )

    # 5. Selector should not allow invalid values
    assert_ok(
        model_selector.findText("qwen3:30b") == -1,
        "model selector should not offer models that exceed GPU VRAM",
    )

    window.close()
    window.deleteLater()
    app.processEvents()
    print("MODEL_SELECTOR_OFFSCREEN_OK")


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    return pytest.main([__file__, "-v"])


if __name__ == "__main__":
    raise SystemExit(main())
