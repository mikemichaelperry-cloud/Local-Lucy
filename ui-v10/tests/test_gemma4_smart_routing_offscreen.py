#!/usr/bin/env python3
"""Offscreen test for Gemma 4 smart-routing checkbox behaviour."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = REPO_UI_ROOT.parent


def _build_panel():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "tools"))

    from app.panels.control_panel import ControlPanel
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    panel = ControlPanel()
    panel.set_backend_enabled(True)
    app.processEvents()
    return app, panel


def test_gemma4_smart_routing_checkbox_enabled_for_gemma4():
    """Checkbox becomes enabled when the configured model is Gemma 4."""
    app, panel = _build_panel()
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "gemma4:12b-it-qat", "gemma4_smart_routing": "off"},
    )
    app.processEvents()
    assert panel._gemma4_smart_routing_selector.isEnabled()
    assert not panel._gemma4_smart_routing_selector.isChecked()


def test_gemma4_smart_routing_checkbox_disabled_for_non_gemma4():
    """Checkbox stays disabled when the configured model is not Gemma 4."""
    app, panel = _build_panel()
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "local-lucy-llama31", "gemma4_smart_routing": "off"},
    )
    app.processEvents()
    assert not panel._gemma4_smart_routing_selector.isEnabled()


def test_gemma4_smart_routing_toggle_emits_signal():
    """Toggling the checkbox emits the change signal with the correct value."""
    app, panel = _build_panel()
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "gemma4:12b-it-qat", "gemma4_smart_routing": "off"},
    )
    app.processEvents()

    received: list[str] = []
    panel.gemma4_smart_routing_change_requested.connect(lambda v: received.append(v))
    panel._gemma4_smart_routing_selector.setChecked(True)
    app.processEvents()
    assert received == ["on"]


def test_engineering_panel_uses_vertical_scroll_only():
    """The control panel must never show a horizontal scrollbar."""
    from PySide6.QtCore import Qt

    app, panel = _build_panel()
    panel.set_interface_level("engineering")
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "gemma4:12b-it-qat", "gemma4_smart_routing": "on"},
    )
    panel.resize(320, 600)
    app.processEvents()
    assert panel._scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_gemma4_smart_routing_update_does_not_emit_signal():
    """update_control_state must not re-emit the change signal while syncing the checkbox."""
    app, panel = _build_panel()
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "gemma4:12b-it-qat", "gemma4_smart_routing": "on"},
    )
    app.processEvents()

    received: list[str] = []
    panel.gemma4_smart_routing_change_requested.connect(lambda v: received.append(v))
    # Simulate the main-window refresh path that omits current_state.
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        }
    )
    app.processEvents()
    assert (
        received == []
    ), f"update_control_state emitted gemma4_smart_routing_change_requested: {received}"


def test_engineering_selectors_fit_inside_viewport():
    """All engineering combo-box selectors must be fully inside the scroll viewport."""
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    app, panel = _build_panel()
    panel.set_interface_level("engineering")
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "off",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "gemma4:12b-it-qat", "gemma4_smart_routing": "on"},
    )

    window = QWidget()
    layout = QVBoxLayout(window)
    layout.addWidget(panel)
    window.resize(320, 600)
    window.show()
    app.processEvents()

    viewport = panel._scroll_area.viewport()
    viewport_width = viewport.width()
    selectors = [
        panel._mode_selector,
        panel._conversation_selector,
        panel._evidence_selector,
        panel._augmentation_policy_selector,
        panel._augmented_provider_selector,
        panel._learner_selector,
        panel._model_selector,
    ]
    for selector in selectors:
        assert selector.isVisible()
        bottom_right = selector.mapTo(viewport, selector.rect().bottomRight())
        assert bottom_right.x() <= viewport_width, (
            f"{selector.objectName()} right edge ({bottom_right.x()}) exceeds "
            f"viewport width ({viewport_width})"
        )
