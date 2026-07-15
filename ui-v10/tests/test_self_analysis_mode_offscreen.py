import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.panels.control_panel import ControlPanel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


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
