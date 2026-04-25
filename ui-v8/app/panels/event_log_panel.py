from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout


class EventLogPanel(QFrame):
    clear_view_requested = Signal()
    acknowledge_alarms_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shellCard")
        self.setMinimumHeight(130)
        self.setMaximumHeight(180)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self._acknowledged = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Event Log")
        title.setObjectName("sectionTitle")
        header.addWidget(title)

        self._alarm_label = QLabel("EVENT STREAM NORMAL")
        self._alarm_label.setObjectName("eventStatus")
        header.addWidget(self._alarm_label)
        header.addStretch(1)

        clear_button = QPushButton("Clear View (Local)")
        clear_button.clicked.connect(self.clear_view_requested.emit)
        acknowledge_button = QPushButton("Acknowledge (Local)")
        acknowledge_button.clicked.connect(self.acknowledge_alarms_requested.emit)

        header.addWidget(acknowledge_button)
        header.addWidget(clear_button)
        layout.addLayout(header)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setPlainText(
            "00:00:00  shell.boot            Operator console initialized\n"
            "00:00:01  ui.status            Awaiting authoritative state refresh\n"
            "00:00:02  ui.controls          Control surface ready for authoritative bindings\n"
            "00:00:03  ui.conversation      Persisted history and request pane ready\n"
            "00:00:04  ui.runtime           Runtime and diagnostics panes ready"
        )
        layout.addWidget(self._log, stretch=1)

    def update_events(self, event_lines: list[str]) -> None:
        self._acknowledged = False
        text = "\n".join(event_lines)
        if self._log.toPlainText() != text:
            self._log.setPlainText(text)
        self._apply_alarm_state(event_lines)

    def capture_scroll_state(self) -> dict[str, int | bool]:
        scrollbar = self._log.verticalScrollBar()
        return {
            "event_log": scrollbar.value(),
            "event_log_pinned_bottom": scrollbar.value() == scrollbar.maximum(),
        }

    def restore_scroll_state(self, state: dict[str, int | bool] | None) -> None:
        if not isinstance(state, dict):
            return
        scrollbar = self._log.verticalScrollBar()
        if bool(state.get("event_log_pinned_bottom")):
            scrollbar.setValue(scrollbar.maximum())
            return
        if "event_log" in state:
            scrollbar.setValue(min(int(state["event_log"]), scrollbar.maximum()))

    def clear_view(self) -> None:
        self._acknowledged = True
        self._log.clear()
        self._alarm_label.setText("EVENT VIEW CLEARED (LOCAL)")
        self._alarm_label.setStyleSheet("color: #93a4af;")

    def acknowledge_alarms(self) -> None:
        self._acknowledged = True
        self._alarm_label.setText("ALARM ACKNOWLEDGED (LOCAL)")
        self._alarm_label.setStyleSheet("color: #d7c587;")

    def _apply_alarm_state(self, event_lines: list[str]) -> None:
        if self._acknowledged:
            self._alarm_label.setText("ALARM ACKNOWLEDGED (LOCAL)")
            self._alarm_label.setStyleSheet("color: #d7c587;")
            return

        joined = "\n".join(event_lines)
        if "[alarm" in joined:
            self._alarm_label.setText("ALARM PRESENT")
            self._alarm_label.setStyleSheet("color: #e58c86;")
            return
        if "[warning" in joined:
            self._alarm_label.setText("WARNINGS PRESENT")
            self._alarm_label.setStyleSheet("color: #d7c587;")
            return

        self._alarm_label.setText("EVENT STREAM NORMAL")
        self._alarm_label.setStyleSheet("color: #7ec08b;")

    def set_scroll_view_updates_enabled(self, enabled: bool) -> None:
        self._log.setUpdatesEnabled(enabled)
        self._log.viewport().setUpdatesEnabled(enabled)
