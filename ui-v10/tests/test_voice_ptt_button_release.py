#!/usr/bin/env python3
"""Regression test for release-to-send button behavior.

Changing a QPushButton's text/enabled state while it is pressed can cancel the
active press and prevent the released() signal from firing.  This test verifies
that updating the control panel's voice runtime state to "listening" while the
PTT button is held down does not break the subsequent released() signal.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = REPO_UI_ROOT.parent

os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_ROOT))
os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")

sys.path.insert(0, str(REPO_UI_ROOT))
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))

from app.panels.control_panel import ControlPanel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def _build_app_and_panel():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    panel = ControlPanel()
    panel.set_backend_enabled(True)
    return app, panel


def test_ptt_released_signal_fires_after_listening_state_update():
    """Pressing PTT, switching to listening, then releasing must emit released()."""
    app, panel = _build_app_and_panel()

    pressed_count = [0]
    released_count = [0]
    panel.ptt_pressed_requested.connect(lambda: pressed_count.__setitem__(0, pressed_count[0] + 1))
    panel.ptt_released_requested.connect(
        lambda: released_count.__setitem__(0, released_count[0] + 1)
    )

    # Voice on, idle, backend available
    panel._backend_available = True
    panel._voice_runtime = {
        "available": True,
        "listening": False,
        "processing": False,
        "status": "idle",
        "last_error": "",
        "stt": "whisper",
        "tts": "kokoro",
    }
    panel.update_control_state(
        top_status={
            "Profile": "lucy-v10",
            "Mode": "auto",
            "Conversation": "on",
            "Memory": "on",
            "Evidence": "on",
            "Voice": "on",
            "Augmented Policy": "fallback_only",
            "Augmented Provider": "wikipedia",
            "Learner": "on",
        },
        current_state={"model": "local-lucy-llama31", "gemma4_smart_routing": "off"},
    )
    app.processEvents()
    assert panel._voice_ptt_button.text() == "Hold to Talk", (
        f"initial button text unexpected: {panel._voice_ptt_button.text()!r}"
    )

    # Simulate press
    panel._voice_ptt_button.setDown(True)
    panel.ptt_pressed_requested.emit()
    app.processEvents()
    assert pressed_count[0] == 1, f"expected 1 pressed signal, got {pressed_count[0]}"

    # Backend reports listening (this is when the button text would change)
    panel._voice_runtime = {
        "available": True,
        "listening": True,
        "processing": False,
        "status": "listening",
        "last_error": "",
        "stt": "whisper",
        "tts": "kokoro",
    }
    panel._refresh_voice_ptt()
    app.processEvents()

    # The button text should NOT have changed while it is down.
    assert panel._voice_ptt_button.text() == "Hold to Talk", (
        f"button text changed while pressed: {panel._voice_ptt_button.text()!r}"
    )

    # Simulate release
    panel._voice_ptt_button.setDown(False)
    panel.ptt_released_requested.emit()
    app.processEvents()

    assert released_count[0] == 1, f"expected 1 released signal, got {released_count[0]}"
