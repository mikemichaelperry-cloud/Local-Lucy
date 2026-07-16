#!/usr/bin/env python3
"""Offscreen regression test: SELF_REVIEW responses must not trigger TTS."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")

sys.path.insert(0, str(REPO_UI_ROOT))

from app.main_window import OperatorConsoleWindow as MainWindow
from app.panels.control_panel import ControlPanel
from app.services.runtime_bridge import CommandResult, RuntimeBridge
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


def _qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app  # type: ignore[return-value]


def _build_window(monkeypatch) -> MainWindow:
    """Create a MainWindow with background warm-up threads disabled for tests."""
    monkeypatch.setattr(RuntimeBridge, "_prime_voice_state", lambda self: None)
    monkeypatch.setattr(RuntimeBridge, "_background_warmup_ollama", lambda self: None)
    monkeypatch.setattr(RuntimeBridge, "_background_warmup_router", lambda self: None)
    return MainWindow()


def test_self_review_response_does_not_trigger_tts(monkeypatch):
    """A completed SELF_REVIEW result must skip Kokoro TTS."""
    app = _qapp()
    window = _build_window(monkeypatch)
    spoken: list[str] = []
    monkeypatch.setattr(window, "_speak_response_text", spoken.append)

    result = CommandResult(
        action="submit_request",
        requested_value=None,
        status="ok",
        returncode=0,
        stdout="Review report",
        stderr="",
        timed_out=False,
        payload={
            "status": "completed",
            "response_text": "Review report",
            "route": {
                "mode": "SELF_REVIEW",
                "final_mode": "SELF_REVIEW",
            },
        },
    )
    window._handle_submit_complete(result)
    app.processEvents()
    assert spoken == [], f"TTS should be suppressed for SELF_REVIEW, got {spoken!r}"


def test_non_self_review_response_triggers_tts(monkeypatch):
    """A normal completed result must still call TTS."""
    app = _qapp()
    window = _build_window(monkeypatch)
    spoken: list[str] = []
    monkeypatch.setattr(window, "_speak_response_text", spoken.append)

    result = CommandResult(
        action="submit_request",
        requested_value=None,
        status="ok",
        returncode=0,
        stdout="Hello world",
        stderr="",
        timed_out=False,
        payload={
            "status": "completed",
            "response_text": "Hello world",
            "route": {
                "mode": "LOCAL",
                "final_mode": "LOCAL",
            },
        },
    )
    window._handle_submit_complete(result)
    app.processEvents()
    assert spoken == ["Hello world"], f"TTS should fire for LOCAL route, got {spoken!r}"


def test_self_analysis_checkbox_exists_and_emits_signal():
    app = QApplication.instance() or QApplication([])
    panel = ControlPanel()
    panel.set_interface_level("engineering")

    received = []
    panel.self_analysis_change_requested.connect(lambda value: received.append(value))

    checkbox = panel._self_analysis_selector
    assert checkbox is not None
    assert checkbox.text() == "Self-Analysis Mode"

    checkbox.blockSignals(False)
    checkbox.setChecked(True)
    QTest.mouseClick(checkbox, Qt.LeftButton)

    assert "on" in received


def test_self_analysis_checkbox_state_preserved_on_noop_toggle():
    app = QApplication.instance() or QApplication([])
    panel = ControlPanel()
    panel.set_interface_level("engineering")

    # Simulate backend reporting self-analysis mode is on.
    panel.update_control_state(
        {"Profile": "default", "Mode": "offline"},
        current_state={"self_analysis_mode": "on"},
    )
    checkbox = panel._self_analysis_selector
    assert checkbox.isChecked()

    # Toggling to the same value should not clear the checkbox.
    received = []
    panel.self_analysis_change_requested.connect(lambda value: received.append(value))
    checkbox.blockSignals(False)
    checkbox.setChecked(True)
    QTest.mouseClick(checkbox, Qt.LeftButton)

    assert not received  # no signal emitted because value did not change
    assert checkbox.isChecked()
