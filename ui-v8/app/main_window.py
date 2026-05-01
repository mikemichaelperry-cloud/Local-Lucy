from __future__ import annotations

from datetime import datetime
import re
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings, QThreadPool, QTimer, Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.panels.control_panel import ControlPanel
from app.panels.conversation_panel import ConversationPanel
from app.panels.event_log_panel import EventLogPanel
from app.panels.status_panel import StatusPanel
from app.services.log_watcher import LogWatcher
from app.services.runtime_bridge import CommandResult, RuntimeActionTask, RuntimeBridge
from app.services.state_store import (
    build_request_details,
    get_state_directory,
    load_recent_request_history,
    load_runtime_snapshot,
    resolve_last_request_paid,
    resolve_last_request_provider,
)
from app.ui_levels import ENGINEERING, LEVELS, SIMPLE, display_level, level_at_least, normalize_level


APP_STYLESHEET = """
QMainWindow {
    background: #11161b;
}
QWidget {
    color: #d8e0e6;
    font-size: 13px;
}
QFrame#shellCard, QFrame#statusChip, QGroupBox {
    background: #1a2229;
    border: 1px solid #2f3b45;
    border-radius: 8px;
}
QLabel#sectionTitle {
    color: #eef3f6;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.5px;
}
QLabel#cardLabel {
    color: #94a5b1;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
}
QLabel#cardValue {
    color: #ecf2f6;
    font-size: 13px;
    font-weight: 600;
}
QLabel#eventStatus {
    color: #7ec08b;
    font-size: 11px;
    font-weight: 700;
}
QGroupBox {
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: #cfd7dd;
}
QPushButton {
    background: #2b3b46;
    border: 1px solid #445764;
    border-radius: 6px;
    color: #ecf2f6;
    min-height: 34px;
    padding: 6px 10px;
}
QPushButton:hover {
    background: #334753;
}
QPushButton#levelButton {
    min-height: 28px;
    padding: 4px 12px;
}
QPushButton#levelButton:checked {
    background: #53656f;
    border-color: #8698a4;
    color: #f2f6f8;
}
QPushButton#traceSummaryButton {
    background: #162029;
    border: 1px solid #32414b;
    border-radius: 6px;
    color: #d8e0e6;
    min-height: 28px;
    padding: 4px 8px;
    text-align: left;
}
QPushButton#traceSummaryButton:hover {
    background: #1d2a34;
}
QPushButton#traceSummaryButton:checked {
    background: #253743;
    border-color: #627481;
}
QPushButton#pttButton {
    min-height: 46px;
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 0.4px;
}
QPushButton#pttButton[voiceState="listening"] {
    background: #7a3a2f;
    border-color: #b26a58;
}
QPushButton#pttButton[voiceState="processing"] {
    background: #40505c;
    border-color: #60707d;
}
QPushButton#pttButton[voiceState="fault"],
QPushButton#pttButton[voiceState="unavailable"] {
    background: #41262a;
    border-color: #7f4348;
}
QGroupBox#voiceStatusFrame[stage="recording"] {
    border: 2px solid #e74c3c;
}
QGroupBox#voiceStatusFrame[stage="transcribing"] {
    border: 2px solid #f1c40f;
}
QGroupBox#voiceStatusFrame[stage="processing"] {
    border: 2px solid #3498db;
}
QGroupBox#voiceStatusFrame[stage="speaking"] {
    border: 2px solid #2ecc71;
}
QPushButton:disabled {
    background: #212b33;
    color: #7f8d97;
    border-color: #37434c;
}
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {
    background: #12191f;
    border: 1px solid #33424d;
    border-radius: 6px;
    color: #d8e0e6;
    padding: 6px;
}
QTextEdit, QPlainTextEdit {
    selection-background-color: #45657a;
}
QPlainTextEdit#decisionTraceView {
    font-family: monospace;
}
QCheckBox, QRadioButton {
    spacing: 8px;
}
QScrollArea#conversationScrollArea,
QWidget#conversationScrollViewport,
QWidget#conversationScrollContent,
QScrollArea#panelScrollArea,
QWidget#panelScrollViewport,
QWidget#panelScrollContent {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: #12191f;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #43535e;
    border-radius: 5px;
    min-height: 22px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
"""

SELF_REVIEW_TRIGGER_RE = re.compile(r"^\s*review your own code\b", re.IGNORECASE)


class OperatorConsoleWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._debug_log("OperatorConsoleWindow initializing")
        self.setWindowTitle("Local Lucy Operator Console")
        self.resize(1460, 900)
        # Allow reduced-height operation so per-panel scrolling can engage on smaller displays.
        self.setMinimumSize(960, 620)
        self.setStyleSheet(APP_STYLESHEET)
        self._settings = QSettings("LocalLucy", "OperatorConsole")
        self._interface_level = self._load_interface_level()

        self._log_watcher = LogWatcher()
        self._runtime_bridge = RuntimeBridge()
        
        # Log state store paths for debugging
        from app.services.state_store import RUNTIME_NAMESPACE_ROOT, STATE_DIRECTORY, REQUEST_HISTORY_FILE, STATE_FILES
        self._debug_log(f"RUNTIME_NAMESPACE_ROOT: {RUNTIME_NAMESPACE_ROOT}")
        self._debug_log(f"STATE_DIRECTORY: {STATE_DIRECTORY}")
        self._debug_log(f"REQUEST_HISTORY_FILE: {REQUEST_HISTORY_FILE}")
        self._debug_log(f"current_state file: {STATE_FILES['current_state']}")
        
        self._backend_controls_available = all(
            capability.available for capability in self._runtime_bridge.capabilities.values()
        )
        self._profile_reload_available = self._runtime_bridge.profile_available()
        self._submit_available = self._runtime_bridge.request_available()
        self._voice_ptt_available = self._runtime_bridge.voice_available()
        self._backend_action_in_flight = False
        self._voice_action_in_flight = False
        self._thread_pool = QThreadPool(self)
        self._action_task: RuntimeActionTask | None = None
        self._voice_action_task: RuntimeActionTask | None = None
        self._pending_action_label = ""
        self._pending_voice_action_label = ""
        self._voice_release_pending = False
        self._voice_ptt_active = False
        self._voice_elapsed_time = 0
        self._voice_action_timer = QTimer(self)
        self._voice_action_timer.setInterval(250)
        self._voice_action_timer.timeout.connect(self._on_voice_timer_tick)
        self._history_signature: tuple[str, ...] = ()
        self._history_render_level = ""
        self._history_entries: list[dict[str, object]] = []
        self._selected_request_id: str | None = None
        self._history_selection_pinned = False
        self._latest_request_details: dict[str, object] | None = None
        self._latest_decision_trace_details: dict[str, object] | None = None
        self._ui_event_lines: list[str] = []
        self._last_model_switch_time: float = 0.0
        self._pending_submit_force_augmented_once = False
        # GUI-session counters only; they reset on GUI restart and are separate from launcher session counters.
        self._session_augmented_calls_total = 0
        self._session_augmented_calls_paid = 0
        self._session_augmented_calls_openai = 0
        self._session_augmented_calls_kimi = 0
        self._session_augmented_calls_wikipedia = 0
        self._latest_state_snapshot = load_runtime_snapshot()
        self._sanitize_voice_runtime_on_startup()
        self._latest_log_snapshot = self._log_watcher.poll()
        self._initial_draft_focus_pending = True
        self._level_buttons: dict[str, QPushButton] = {}
        self._level_button_group: QButtonGroup | None = None

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(12)

        self._top_status_labels: dict[str, QLabel] = {}
        self._top_status_cards: dict[str, QFrame] = {}
        self._top_status_grid: QGridLayout | None = None
        self._top_status_order: list[str] = []
        root_layout.addWidget(self._build_top_status_bar())

        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)
        root_layout.addLayout(body_layout, stretch=1)

        self.control_panel = ControlPanel()
        self.conversation_panel = ConversationPanel()
        self.status_panel = StatusPanel()

        body_layout.addWidget(self.control_panel, stretch=23)
        body_layout.addWidget(self.conversation_panel, stretch=47)
        body_layout.addWidget(self.status_panel, stretch=30)

        self.event_log_panel = EventLogPanel()
        root_layout.addWidget(self.event_log_panel, stretch=0)
        self._decision_trace_panel = self._build_decision_trace_panel()
        root_layout.addWidget(self._decision_trace_panel, stretch=0)

        self.setCentralWidget(root)
        self.control_panel.apply_backend_capabilities(
            self._runtime_bridge.capability_notes(),
            self._backend_controls_available,
        )
        self.control_panel.set_profile_reload_available(self._profile_reload_available)
        self.conversation_panel.set_submit_enabled(self._submit_available)
        self._apply_interface_level(persist=False)
        if (
            self._backend_controls_available
            and self._profile_reload_available
            and self._submit_available
        ):
            self.statusBar().showMessage(
                "Console ready: authoritative controls, profile reset, and submit live."
            )
        elif self._backend_controls_available:
            self.statusBar().showMessage("Console ready: authoritative backend controls live.")
        else:
            self.statusBar().showMessage("Console ready: safe operator actions only.")
        self._wire_actions()

        self._state_refresh_timer = QTimer(self)
        self._state_refresh_timer.setInterval(1000)
        self._state_refresh_timer.timeout.connect(self.refresh_runtime_state)
        self._state_refresh_timer.start()
        self.refresh_runtime_state()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._initial_draft_focus_pending:
            return
        self._initial_draft_focus_pending = False
        QTimer.singleShot(0, self.conversation_panel.focus_draft)

    def refresh_runtime_state(self) -> None:
        self._debug_log("refresh_runtime_state called")
        scroll_state = self._capture_refresh_scroll_state()
        self.status_panel.set_scroll_view_updates_enabled(False)
        self.event_log_panel.set_scroll_view_updates_enabled(False)
        try:
            previous_voice_runtime = dict(getattr(self._latest_state_snapshot, "voice_runtime", {}))
            self._latest_state_snapshot = load_runtime_snapshot()
            self._latest_log_snapshot = self._log_watcher.poll()
            self._emit_voice_runtime_events(previous_voice_runtime, self._latest_state_snapshot.voice_runtime)
            self._reload_request_history()
            self._repaint_from_truth()
            self._restore_refresh_scroll_state(scroll_state)
        finally:
            self.status_panel.set_scroll_view_updates_enabled(True)
            self.event_log_panel.set_scroll_view_updates_enabled(True)

    def _capture_refresh_scroll_state(self) -> dict[str, object]:
        return {
            "status": self.status_panel.capture_scroll_state(),
            "event_log": self.event_log_panel.capture_scroll_state(),
        }

    def _restore_refresh_scroll_state(self, scroll_state: dict[str, object]) -> None:
        self.status_panel.restore_scroll_state(scroll_state.get("status"))
        self.event_log_panel.restore_scroll_state(scroll_state.get("event_log"))

    def _repaint_from_truth(self) -> None:
        for label_text, value in self._latest_state_snapshot.top_status.items():
            if label_text in self._top_status_labels:
                self._top_status_labels[label_text].setText(value)

        self.status_panel.update_runtime_snapshot(self._latest_state_snapshot)
        self.status_panel.update_status(self._runtime_status_with_session_counters())
        self.status_panel.update_request_details(self._latest_request_details)
        self.status_panel.set_interface_level(self._interface_level)
        self.status_panel.refresh_auxiliary_views()
        self.control_panel.set_interface_level(self._interface_level)
        self.conversation_panel.set_interface_level(self._interface_level)
        self._refresh_decision_trace()
        self.control_panel.update_control_state(
            self._latest_state_snapshot.top_status,
            self._latest_state_snapshot.current_state,
        )
        self.control_panel.update_voice_runtime(self._latest_state_snapshot.voice_runtime)
        
        # Update voice transcription preview in conversation panel
        voice_transcription = str(self._latest_state_snapshot.voice_runtime.get("transcription_preview", ""))
        self.conversation_panel.set_voice_transcription_preview(voice_transcription)
        self.control_panel.set_profile_reload_available(self._profile_reload_available)
        if not self._any_backend_action_in_flight():
            self.control_panel.set_backend_enabled(self._backend_controls_available)
            self.conversation_panel.set_submit_enabled(self._submit_available)
        self._render_event_log()

    def _render_event_log(self) -> None:
        merged_lines = self._ui_event_lines + self._latest_log_snapshot.lines
        self.event_log_panel.update_events(merged_lines[:240])

    def _append_ui_event(self, line: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._ui_event_lines.insert(0, f"{timestamp}  ui.action            {line}")
        self._ui_event_lines = self._ui_event_lines[:24]
        self._render_event_log()

    def _wire_actions(self) -> None:
        self.control_panel.refresh_requested.connect(self._handle_refresh_now)
        self.control_panel.copy_state_requested.connect(self._copy_state_summary)
        self.control_panel.open_logs_requested.connect(self._open_log_directory)
        self.control_panel.open_state_requested.connect(self._open_state_directory)
        self.control_panel.mode_change_requested.connect(
            lambda value: self._execute_backend_action("mode_selection", value, "mode change")
        )
        self.control_panel.conversation_change_requested.connect(
            lambda value: self._execute_backend_action("conversation_toggle", value, "conversation toggle")
        )
        self.control_panel.memory_change_requested.connect(
            lambda value: self._execute_backend_action("memory_toggle", value, "memory toggle")
        )
        self.control_panel.evidence_change_requested.connect(
            lambda value: self._execute_backend_action("evidence_toggle", value, "evidence toggle")
        )
        self.control_panel.voice_change_requested.connect(
            lambda value: self._execute_backend_action("voice_toggle", value, "voice toggle")
        )
        self.control_panel.augmented_policy_change_requested.connect(
            lambda value: self._execute_backend_action("augmentation_policy", value, "augmented policy change")
        )
        self.control_panel.augmented_provider_change_requested.connect(
            lambda value: self._execute_backend_action("augmented_provider", value, "augmented provider change")
        )
        self.control_panel.model_change_requested.connect(
            lambda value: self._execute_backend_action("model_selection", value, "model change")
        )
        self.control_panel.ptt_pressed_requested.connect(self._handle_voice_ptt_pressed)
        self.control_panel.ptt_released_requested.connect(self._handle_voice_ptt_released)
        self.control_panel.reload_profile_requested.connect(self._handle_reload_profile_requested)
        self.conversation_panel.clear_draft_requested.connect(self._clear_conversation_draft)
        self.conversation_panel.submit_requested.connect(self._handle_submit_requested)
        self.conversation_panel.history_selection_changed.connect(self._handle_history_selection_changed)
        self.conversation_panel.decision_trace_toggled.connect(self._handle_decision_trace_toggled)
        self.event_log_panel.clear_view_requested.connect(self._clear_event_view)
        self.event_log_panel.acknowledge_alarms_requested.connect(self._acknowledge_alarms)

    def _load_interface_level(self) -> str:
        saved_value = self._settings.value("interface_level", "operator")
        return normalize_level(saved_value if isinstance(saved_value, str) else str(saved_value))

    def _apply_interface_level(self, *, persist: bool) -> None:
        if self._level_button_group is not None:
            for level, button in self._level_buttons.items():
                button.blockSignals(True)
                button.setChecked(level == self._interface_level)
                button.blockSignals(False)
        if self._interface_level == SIMPLE:
            self._history_selection_pinned = False
            self._selected_request_id = None
        self.control_panel.set_interface_level(self._interface_level)
        self.conversation_panel.set_interface_level(self._interface_level)
        self.status_panel.set_interface_level(self._interface_level)
        self._apply_top_status_visibility()
        self.event_log_panel.setVisible(self._interface_level == ENGINEERING)
        if persist:
            self._settings.setValue("interface_level", self._interface_level)
        self._reload_request_history()
        self._repaint_from_truth()
        self.statusBar().showMessage(f"Interface level: {display_level(self._interface_level)}.", 2500)

    def _handle_interface_level_selected(self, level: str) -> None:
        normalized = normalize_level(level)
        if normalized == self._interface_level:
            return
        self._interface_level = normalized
        self._append_ui_event(f"[info] interface level -> {display_level(self._interface_level)}")
        self._apply_interface_level(persist=True)

    def _any_backend_action_in_flight(self) -> bool:
        return self._backend_action_in_flight or self._voice_action_in_flight

    def _handle_voice_ptt_pressed(self) -> None:
        if not self._voice_ptt_available:
            self._append_ui_event("[warning] voice ptt unavailable")
            self.statusBar().showMessage("Voice PTT unavailable.", 3000)
            self.refresh_runtime_state()
            return
        if self._any_backend_action_in_flight():
            self._append_ui_event("[warning] busy; ignored voice ptt start")
            self.statusBar().showMessage("Backend action already in flight.", 3000)
            self.refresh_runtime_state()
            return
        if self._payload_text(self._latest_state_snapshot.top_status, "Voice").lower() != "on":
            self._append_ui_event("[warning] voice ptt hidden by authoritative voice=off")
            self.statusBar().showMessage("Voice PTT unavailable while voice is off.", 3000)
            self.refresh_runtime_state()
            return
        if bool(self._latest_state_snapshot.voice_runtime.get("listening", False)):
            return

        self._voice_release_pending = False
        self._voice_ptt_active = True
        self._voice_elapsed_time = 0
        self._voice_action_timer.start()
        self._append_ui_event("[info] voice ptt start requested")
        self.statusBar().showMessage("Recording... 0.0s", 0)
        self._execute_voice_action("voice_ptt_start", "start", "voice ptt start")

    def _handle_voice_ptt_released(self) -> None:
        if self._voice_action_in_flight and self._pending_voice_action_label == "voice ptt start":
            self._voice_release_pending = True
            self.statusBar().showMessage("Voice release queued until capture starts.", 2000)
            return
        if self._voice_action_in_flight:
            return
        if not self._voice_ptt_active:
            return

        self._voice_ptt_active = False
        self._voice_action_timer.stop()
        self._append_ui_event("[info] voice stop requested")
        self.statusBar().showMessage("Stopping voice capture...", 0)
        self._execute_voice_action("voice_ptt_stop", "stop", "voice ptt stop")

    def _on_voice_timer_tick(self) -> None:
        if not self._voice_ptt_active:
            self._voice_action_timer.stop()
            return
        self._voice_elapsed_time += 250
        elapsed_s = self._voice_elapsed_time / 1000.0
        self.statusBar().showMessage(f"Recording... {elapsed_s:.1f}s", 0)

    def _execute_voice_action(self, action: str, requested_value: str, action_label: str) -> None:
        if self._voice_action_in_flight:
            return
        self._voice_action_in_flight = True
        self._pending_voice_action_label = action_label
        self.conversation_panel.set_submit_enabled(False)
        self._voice_action_task = RuntimeActionTask(self._runtime_bridge, action, requested_value)
        self._voice_action_task.signals.finished.connect(self._handle_backend_action_complete)
        self._thread_pool.start(self._voice_action_task)

    def _execute_backend_action(self, action: str, requested_value: str, action_label: str) -> None:
        if not self._backend_controls_available:
            self._append_ui_event(f"[warning] {action_label} unavailable")
            self.statusBar().showMessage("Backend controls unavailable.", 3000)
            self.refresh_runtime_state()
            return

        if self._any_backend_action_in_flight():
            self._append_ui_event(f"[warning] busy; ignored {action_label} -> {requested_value}")
            self.statusBar().showMessage("Backend action already in flight.", 3000)
            self.refresh_runtime_state()
            return

        # Model switch cooldown: prevent Ollama unload/load race
        if action == "model_selection":
            cooldown_remaining = 5.0 - (time.time() - self._last_model_switch_time)
            if cooldown_remaining > 0:
                self._append_ui_event(f"[warning] model switch cooldown {cooldown_remaining:.1f}s remaining")
                self.statusBar().showMessage(f"Model switch cooldown: {cooldown_remaining:.1f}s remaining.", 3000)
                self.refresh_runtime_state()
                return
            self._last_model_switch_time = time.time()

        self.control_panel.update_control_state(
            self._latest_state_snapshot.top_status,
            self._latest_state_snapshot.current_state,
        )
        self._set_backend_busy(True)
        self._pending_action_label = action_label
        self._append_ui_event(f"[info] {action_label} requested -> {requested_value}")
        self.statusBar().showMessage(f"Applying {action_label}: {requested_value}", 0)
        self._action_task = RuntimeActionTask(self._runtime_bridge, action, requested_value)
        self._action_task.signals.finished.connect(self._handle_backend_action_complete)
        self._thread_pool.start(self._action_task)

    def _handle_reload_profile_requested(self) -> None:
        if not self._profile_reload_available:
            self._append_ui_event("[warning] profile reset unavailable")
            self.statusBar().showMessage("Profile reset unavailable.", 3000)
            self.refresh_runtime_state()
            return
        if self._any_backend_action_in_flight():
            self._append_ui_event("[warning] busy; ignored profile reset")
            self.statusBar().showMessage("Backend action already in flight.", 3000)
            self.refresh_runtime_state()
            return

        self._set_backend_busy(True)
        self._pending_action_label = "profile reset"
        self._append_ui_event("[info] profile reset requested")
        self.statusBar().showMessage("Resetting profile/model to authoritative defaults...", 0)
        self._action_task = RuntimeActionTask(self._runtime_bridge, "reload_profile", "")
        self._action_task.signals.finished.connect(self._handle_backend_action_complete)
        self._thread_pool.start(self._action_task)

    @Slot(object)
    def _handle_backend_action_complete(self, result: CommandResult) -> None:
        if result.action in {"voice_ptt_start", "voice_ptt_stop", "voice_status"}:
            self._handle_voice_action_complete(result)
            return
        if result.action in {"submit_request", "submit_request_force_augmented_once", "submit_self_review_request"}:
            self._handle_submit_complete(result)
            return

        action_label = self._pending_action_label or result.action
        self.refresh_runtime_state()
        self._set_backend_busy(False)
        self._clear_action_worker_refs()
        action_suffix = f" -> {result.requested_value}" if result.requested_value else ""

        if result.status == "ok":
            self._append_ui_event(f"[info] {action_label} succeeded{action_suffix}")
            self._append_ui_event("[info] post-action refresh complete")
            self.statusBar().showMessage(
                f"{action_label.capitalize()} applied. State refresh complete.",
                3000,
            )
            return

        if result.status == "timeout":
            self._append_ui_event(f"[alarm] {action_label} timeout{action_suffix}")
            self._append_ui_event("[info] post-action refresh complete")
            self.statusBar().showMessage(f"{action_label.capitalize()} timed out.", 3000)
            return

        failure_detail = self._result_detail(result)
        self._append_ui_event(f"[alarm] {action_label} failed -> {failure_detail}")
        self._append_ui_event("[info] post-action refresh complete")
        self.statusBar().showMessage(f"{action_label.capitalize()} failed: {failure_detail}", 4000)

    def _handle_voice_action_complete(self, result: CommandResult) -> None:
        action_label = self._pending_voice_action_label or result.action
        if result.action == "voice_ptt_stop" and isinstance(result.payload, dict):
            # Clear transcription preview after successful voice turn
            self.conversation_panel.clear_voice_transcription_preview()
        self.refresh_runtime_state()
        self._voice_action_in_flight = False
        self._clear_voice_worker_refs()
        self.conversation_panel.set_submit_enabled(
            self._submit_available and not self._backend_action_in_flight
        )

        if result.action == "voice_ptt_start":
            if result.status == "ok" and bool(self._latest_state_snapshot.voice_runtime.get("listening", False)):
                if self._voice_release_pending:
                    self._voice_release_pending = False
                    self._voice_ptt_active = False
                    self._voice_action_timer.stop()
                    self._append_ui_event("[info] voice stop requested")
                    self.statusBar().showMessage("Stopping voice capture...", 0)
                    self._execute_voice_action("voice_ptt_stop", "stop", "voice ptt stop")
                    return
                self.statusBar().showMessage("Voice listening.", 2000)
                return

            self._voice_release_pending = False
            self._voice_ptt_active = False
            self._voice_action_timer.stop()
            if result.status == "timeout":
                timeout_detail = self._voice_failure_detail(result) or "timeout"
                if self._should_emit_local_voice_failure_event(timeout_detail):
                    self._append_ui_event(f"[alarm] {action_label} timeout")
                self.statusBar().showMessage(f"Voice start timed out: {timeout_detail}", 3000)
                return

            failure_detail = self._voice_failure_detail(result)
            if self._should_emit_local_voice_failure_event(failure_detail):
                self._append_ui_event(f"[alarm] voice failed -> {failure_detail}")
            self.statusBar().showMessage(f"Voice start failed: {failure_detail}", 4000)
            return

        if result.action == "voice_ptt_stop":
            self._voice_release_pending = False
            self._voice_ptt_active = False
            self._voice_action_timer.stop()
            if result.status == "ok":
                payload = result.payload if isinstance(result.payload, dict) else {}
                payload_status = self._payload_text(payload, "status") or "completed"
                transcript = self._payload_text(payload, "transcript")
                # Clear transcription preview
                self.conversation_panel.clear_voice_transcription_preview()
                if payload_status == "no_transcript" or not transcript:
                    self.statusBar().showMessage("Voice turn ended with no transcript.", 3000)
                else:
                    preview = transcript if len(transcript) <= 48 else f"{transcript[:45]}..."
                    self.statusBar().showMessage(f"Voice: '{preview}'", 3000)
                    self._append_ui_event(f"[info] voice transcript -> submit")
                    self._execute_backend_action("submit_request", transcript, "voice submit")
                return
            if result.status == "timeout":
                timeout_detail = self._voice_failure_detail(result) or "timeout"
                if self._should_emit_local_voice_failure_event(timeout_detail):
                    self._append_ui_event(f"[alarm] {action_label} timeout")
                self.statusBar().showMessage(f"Voice stop timed out: {timeout_detail}", 3000)
                # Force a voice status sync to recover state after timeout
                QTimer.singleShot(500, lambda: self._execute_voice_action("voice_status", "", "voice status sync"))
                return

            failure_detail = self._voice_failure_detail(result)
            if self._should_emit_local_voice_failure_event(failure_detail):
                self._append_ui_event(f"[alarm] voice failed -> {failure_detail}")
            self.statusBar().showMessage(f"Voice stop failed: {failure_detail}", 4000)
            return

    def _handle_submit_requested(self, request_text: str) -> None:
        request_text = request_text.strip()
        if not request_text:
            self._append_ui_event("[warning] empty submit rejected")
            self.statusBar().showMessage("Submit rejected: empty request.", 3000)
            return

        if not self._submit_available:
            self._append_ui_event("[warning] submit unavailable")
            self.statusBar().showMessage("Submit unavailable.", 3000)
            return

        if self._any_backend_action_in_flight():
            self._append_ui_event("[warning] busy; ignored submit request")
            self.statusBar().showMessage("Backend action already in flight.", 3000)
            return

        if self._is_self_review_request(request_text):
            if not level_at_least(self._interface_level, ENGINEERING):
                self._append_ui_event("[warning] self-review trigger blocked outside advanced views")
                self.statusBar().showMessage("Read-only self-review is available only in Advanced or Coding views.", 4000)
                return
            if self._current_mode() != "auto":
                self._append_ui_event("[warning] self-review trigger blocked outside auto mode")
                self.statusBar().showMessage("Read-only self-review is available only while mode is set to auto.", 4000)
                return
            force_augmented_once = False
            action = "submit_self_review_request"
            self._pending_action_label = "read-only self-review"
        else:
            force_augmented_once = self.conversation_panel.consume_force_augmented_once()
            action = "submit_request_force_augmented_once" if force_augmented_once else "submit_request"
            self._pending_action_label = "request submit"
        self._set_backend_busy(True)
        self._pending_submit_force_augmented_once = force_augmented_once
        if action == "submit_self_review_request":
            self._append_ui_event("[info] read-only self-review submitted")
            self.statusBar().showMessage("Submitting read-only self-review...", 0)
        elif force_augmented_once:
            self._append_ui_event("[info] request submitted with one-shot augmented override")
            self.statusBar().showMessage("Submitting authoritative request (force augmented once)...", 0)
        else:
            self._append_ui_event("[info] request submitted")
            self.statusBar().showMessage("Submitting authoritative request...", 0)
        self._action_task = RuntimeActionTask(self._runtime_bridge, action, request_text)
        self._action_task.signals.finished.connect(self._handle_backend_action_complete)
        self._thread_pool.start(self._action_task)

    def _handle_submit_complete(self, result: CommandResult) -> None:
        forced_override_used = self._pending_submit_force_augmented_once
        payload = self._resolve_request_result_payload(result)
        self._update_session_augmented_counters_from_payload(payload)
        self.refresh_runtime_state()
        self._set_backend_busy(False)
        self._clear_action_worker_refs()

        if forced_override_used:
            self._append_ui_event("[info] one-shot augmented override applied")

        if result.status == "timeout":
            self._append_ui_event("[alarm] request timed out")
            self._append_ui_event("[info] post-request refresh complete")
            self.statusBar().showMessage("Request timed out.", 4000)
            return

        if payload is None:
            failure_detail = self._result_detail(result)
            self._append_ui_event(f"[alarm] request failed -> {failure_detail}")
            self._append_ui_event("[info] post-request refresh complete")
            self.statusBar().showMessage(f"Request failed: {failure_detail}", 4000)
            return

        request_status = self._payload_text(payload, "status") or result.status
        if request_status == "completed":
            if result.action == "submit_self_review_request":
                self._append_ui_event("[info] read-only self-review completed")
                self.statusBar().showMessage("Read-only self-review completed. State refresh complete.", 3000)
            else:
                self._append_ui_event("[info] request completed")
                self.statusBar().showMessage("Request completed. State refresh complete.", 3000)
            self._append_request_metadata_events(payload)
            self._append_ui_event("[info] post-request refresh complete")
            # Trigger TTS for voice-enabled sessions
            response_text = self._payload_text(payload, "response_text") or result.stdout
            if response_text:
                self._speak_response_text(response_text)
            return

        if request_status == "timeout":
            self._append_ui_event("[alarm] request timed out")
            self._append_ui_event("[info] post-request refresh complete")
            self.statusBar().showMessage("Request timed out.", 4000)
            return

        failure_detail = self._payload_text(payload, "error") or self._result_detail(result)
        self._append_ui_event(f"[alarm] request {request_status or 'failed'} -> {failure_detail}")
        self._append_request_metadata_events(payload)
        self._append_ui_event("[info] post-request refresh complete")
        self.statusBar().showMessage(
            f"Request {request_status or 'failed'}: {failure_detail}",
            4000,
        )

    def _speak_response_text(self, text: str) -> None:
        """Fire TTS in background if voice is enabled."""
        voice_on = self._payload_text(self._latest_state_snapshot.top_status, "Voice").lower() == "on"
        if not voice_on:
            return
        task = RuntimeActionTask(self._runtime_bridge, "speak", text)
        task.signals.finished.connect(self._handle_speak_complete)
        self._thread_pool.start(task)

    def _handle_speak_complete(self, result: CommandResult) -> None:
        if result.status != "ok":
            self._append_ui_event(f"[warning] TTS failed -> {result.stderr or 'unknown'}")

    def _is_self_review_request(self, request_text: str) -> bool:
        return bool(SELF_REVIEW_TRIGGER_RE.search(request_text or ""))

    def _current_mode(self) -> str:
        return self._payload_text(self._latest_state_snapshot.top_status, "Mode").lower()

    @Slot()
    def _clear_action_worker_refs(self) -> None:
        self._action_task = None
        self._pending_action_label = ""
        self._pending_submit_force_augmented_once = False

    @Slot()
    def _clear_voice_worker_refs(self) -> None:
        self._voice_action_task = None
        self._pending_voice_action_label = ""

    def _set_backend_busy(self, busy: bool) -> None:
        self._backend_action_in_flight = busy
        self.control_panel.set_backend_busy(busy)
        self.conversation_panel.set_submit_enabled(
            self._submit_available and not busy and not self._voice_action_in_flight
        )

    def _result_detail(self, result: CommandResult) -> str:
        for text in (result.stderr, result.stdout):
            detail = text.strip()
            if detail:
                return detail.splitlines()[0][:140]
        if result.status == "timeout":
            return "timeout"
        return result.status

    def _voice_failure_detail(self, result: CommandResult) -> str:
        authoritative_detail = self._authoritative_voice_failure_detail()
        if authoritative_detail:
            return authoritative_detail
        return self._normalize_operator_detail(self._result_detail(result))

    def _authoritative_voice_failure_detail(self) -> str:
        status = str(self._latest_state_snapshot.voice_runtime.get("status", "")).strip().lower()
        if status not in {"fault", "unavailable"}:
            return ""
        detail = str(self._latest_state_snapshot.voice_runtime.get("last_error", "")).strip() or status
        return self._normalize_operator_detail(detail)

    def _should_emit_local_voice_failure_event(self, detail: str) -> bool:
        authoritative_detail = self._authoritative_voice_failure_detail()
        if not authoritative_detail:
            return True
        return authoritative_detail != self._normalize_operator_detail(detail)

    def _normalize_operator_detail(self, detail: str) -> str:
        normalized = str(detail or "").strip()
        while normalized[:6].lower() == "error:":
            normalized = normalized[6:].strip()
        return normalized or "unknown failure"

    @staticmethod
    def _is_pid_alive(pid: int | None) -> bool:
        if pid is None:
            return False
        try:
            os.kill(pid, 0)
        except (OSError, ProcessLookupError):
            return False
        return True

    def _sanitize_voice_runtime_on_startup(self) -> None:
        """Reset stale voice runtime state if recorder crashed while listening."""
        voice_runtime = getattr(self._latest_state_snapshot, "voice_runtime", {})
        if not isinstance(voice_runtime, dict):
            return
        if not bool(voice_runtime.get("listening", False)):
            return
        record_pid = voice_runtime.get("record_pid")
        if self._is_pid_alive(record_pid):
            return
        # Recorder PID is dead but state says listening — sanitize
        voice_runtime["listening"] = False
        voice_runtime["processing"] = False
        voice_runtime["status"] = "idle"
        voice_runtime["record_pid"] = None
        voice_runtime["processing_pid"] = None
        voice_runtime["capture_path"] = ""
        voice_runtime["last_error"] = voice_runtime.get("last_error", "") or "recovered from stale state"
        self._append_ui_event("[info] voice state sanitized: recovered from stale listening state")

    def _emit_voice_runtime_events(
        self,
        previous_voice_runtime: dict[str, object],
        current_voice_runtime: dict[str, object],
    ) -> None:
        previous_signature = (
            str(previous_voice_runtime.get("status", "")),
            bool(previous_voice_runtime.get("listening", False)),
            bool(previous_voice_runtime.get("processing", False)),
            bool(previous_voice_runtime.get("available", False)),
            str(previous_voice_runtime.get("last_error", "")).strip(),
        )
        current_signature = (
            str(current_voice_runtime.get("status", "")),
            bool(current_voice_runtime.get("listening", False)),
            bool(current_voice_runtime.get("processing", False)),
            bool(current_voice_runtime.get("available", False)),
            str(current_voice_runtime.get("last_error", "")).strip(),
        )
        if previous_signature == current_signature:
            return

        current_status = str(current_voice_runtime.get("status", "")).strip().lower()
        if current_status == "listening":
            self._append_ui_event("[info] voice listening")
        elif current_status == "processing":
            self._append_ui_event("[info] voice processing")
        elif current_status in {"fault", "unavailable"}:
            detail = str(current_voice_runtime.get("last_error", "")).strip() or current_status
            self._append_ui_event(f"[alarm] voice failed -> {detail}")

    def _handle_refresh_now(self) -> None:
        self.refresh_runtime_state()
        self._append_ui_event("[info] manual refresh complete")
        self.statusBar().showMessage("Refresh complete: state and log views reloaded.", 3000)

    def _clear_event_view(self) -> None:
        self.event_log_panel.clear_view()
        self.statusBar().showMessage("Event view cleared locally. Source logs unchanged.", 3000)

    def _clear_conversation_draft(self) -> None:
        self.conversation_panel.clear_draft()
        self.conversation_panel.focus_draft()
        self.statusBar().showMessage("Conversation draft cleared.", 3000)

    def _copy_state_summary(self) -> None:
        summary_lines = [
            "Local Lucy Operator Console",
            "",
            "[Top Status]",
        ]
        for key, value in self._latest_state_snapshot.top_status.items():
            summary_lines.append(f"{key}: {value}")

        summary_lines.append("")
        summary_lines.append("[Runtime Status]")
        for key, value in self._runtime_status_with_session_counters().items():
            summary_lines.append(f"{key}: {value}")

        summary_lines.append("")
        summary_lines.append("[Paths]")
        for key, value in self._latest_state_snapshot.file_paths.items():
            summary_lines.append(f"{key}: {value}")

        summary_lines.append(f"log_directory: {self._log_watcher.get_log_directory(self._latest_log_snapshot.active_paths)}")

        clipboard = QGuiApplication.clipboard()
        clipboard.setText("\n".join(summary_lines))
        self.statusBar().showMessage("State summary copied to clipboard.", 3000)

    def _open_log_directory(self) -> None:
        log_directory = self._log_watcher.get_log_directory(self._latest_log_snapshot.active_paths)
        self._open_directory(log_directory, "Log directory opened.", "Log directory unavailable.")

    def _open_state_directory(self) -> None:
        state_directory = get_state_directory()
        self._open_directory(state_directory, "State directory opened.", "State directory unavailable.")

    def _open_directory(self, directory, success_message: str, failure_message: str) -> None:
        if not directory.exists() or not directory.is_dir():
            self.statusBar().showMessage(failure_message, 3000)
            return

        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.statusBar().showMessage(success_message, 3000)
            return

        self.statusBar().showMessage(failure_message, 3000)

    def _acknowledge_alarms(self) -> None:
        self.event_log_panel.acknowledge_alarms()
        self.statusBar().showMessage("Alarm highlight acknowledged until next refresh.", 3000)

    def _resolve_request_result_payload(self, result: CommandResult) -> dict[str, object] | None:
        payload = result.payload if isinstance(result.payload, dict) else None
        return payload

    def _debug_log(self, msg: str) -> None:
        """Write debug log to file."""
        import os
        from pathlib import Path
        log_path = Path.home() / "lucy-v8" / "ui_debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat()} MAIN {msg}\n")

    def _reload_request_history(self) -> None:
        self._debug_log(f"_reload_request_history called")
        from app.services.state_store import REQUEST_HISTORY_FILE
        self._debug_log(f"REQUEST_HISTORY_FILE: {REQUEST_HISTORY_FILE}")
        history_result = load_recent_request_history()
        self._debug_log(f"history_result: {history_result.status}, entries: {len(history_result.entries)}")
        self._history_entries = history_result.entries
        available_ids = [
            self._payload_text(entry, "request_id")
            for entry in self._history_entries
            if self._payload_text(entry, "request_id")
        ]
        latest_id = available_ids[-1] if available_ids else None

        if self._interface_level == SIMPLE:
            selected_id = latest_id
            self._history_selection_pinned = False
        elif self._history_selection_pinned and self._selected_request_id in available_ids:
            selected_id = self._selected_request_id
        else:
            selected_id = latest_id
            if self._history_selection_pinned and selected_id != self._selected_request_id:
                self._history_selection_pinned = False

        previous_selected_id = self._selected_request_id
        signature = tuple(
            self._payload_text(entry, "request_id")
            for entry in self._history_entries
        )
        same_signature = signature == self._history_signature
        same_selection = selected_id == previous_selected_id
        same_level = self._interface_level == self._history_render_level

        self._debug_log(f"same_signature={same_signature}, same_selection={same_selection}, same_level={same_level}")
        self._debug_log(f"selected_id={selected_id}, interface_level={self._interface_level}")

        self._selected_request_id = selected_id
        self._latest_request_details = build_request_details(self._selected_history_entry())
        self._latest_decision_trace_details = build_request_details(self._latest_history_entry())

        if same_signature and same_selection and same_level:
            self._debug_log("skipping update (same signature, selection, level)")
            return

        self._history_signature = signature
        self._history_render_level = self._interface_level
        self._debug_log(f"calling set_history_entries with {len(self._history_entries)} entries, selected={selected_id}")
        applied_selection = self.conversation_panel.set_history_entries(
            self._history_entries,
            selected_request_id=selected_id,
        )
        self._debug_log(f"set_history_entries returned: {applied_selection}")
        self._selected_request_id = applied_selection
        self._latest_request_details = build_request_details(self._selected_history_entry())
        self._latest_decision_trace_details = build_request_details(self._latest_history_entry())

    def _selected_history_entry(self) -> dict[str, object] | None:
        selected_id = (self._selected_request_id or "").strip()
        for entry in self._history_entries:
            if self._payload_text(entry, "request_id") == selected_id:
                return entry
        return None

    def _latest_history_entry(self) -> dict[str, object] | None:
        if not self._history_entries:
            return None
        return self._history_entries[-1]

    @Slot(str)
    def _handle_history_selection_changed(self, request_id: str) -> None:
        latest_id = ""
        if self._history_entries:
            latest_id = self._payload_text(self._history_entries[-1], "request_id")
        self._selected_request_id = request_id.strip() or None
        self._history_selection_pinned = bool(self._selected_request_id and self._selected_request_id != latest_id)
        self._latest_request_details = build_request_details(self._selected_history_entry())
        self._latest_decision_trace_details = build_request_details(self._latest_history_entry())
        self.status_panel.update_request_details(self._latest_request_details)
        self._refresh_decision_trace()

    def _append_request_metadata_events(self, payload: dict[str, object]) -> None:
        route = payload.get("route")
        if isinstance(route, dict):
            route_mode = self._payload_text(route, "selected_route") or self._payload_text(route, "mode")
            route_reason = self._payload_text(route, "reason")
            if route_mode or route_reason:
                detail = route_mode or "unknown"
                if route_reason:
                    detail = f"{detail} / {route_reason}"
                self._append_ui_event(f"[info] route -> {detail}")

        outcome = payload.get("outcome")
        if isinstance(outcome, dict):
            outcome_code = self._payload_text(outcome, "outcome_code")
            action_hint = self._payload_text(outcome, "action_hint")
            if outcome_code or action_hint:
                detail = outcome_code or "unknown"
                if action_hint:
                    detail = f"{detail} / {action_hint}"
                self._append_ui_event(f"[info] outcome -> {detail}")

    def _payload_text(self, payload: dict[str, object] | None, key: str) -> str:
        if not isinstance(payload, dict):
            return ""
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _runtime_status_with_session_counters(self) -> dict[str, str]:
        values = dict(self._latest_state_snapshot.runtime_status)
        values["Model"] = self._latest_state_snapshot.top_status.get("Model", "unknown")
        values["Last Request Provider"] = self._latest_request_provider_used_text()
        values["Last Request Paid"] = self._latest_request_paid_text()
        values["Session Augmented Calls"] = str(self._session_augmented_calls_total)
        values["Session Paid Augmented Calls"] = str(self._session_augmented_calls_paid)
        values["Session Provider Counts"] = (
            f"openai={self._session_augmented_calls_openai} "
            f"kimi={self._session_augmented_calls_kimi} "
            f"wikipedia={self._session_augmented_calls_wikipedia}"
        )
        return values

    def _latest_request_provider_used_text(self) -> str:
        return resolve_last_request_provider(self._latest_request_details)

    def _latest_request_paid_text(self) -> str:
        return resolve_last_request_paid(self._latest_request_details)

    def _update_session_augmented_counters_from_payload(self, payload: dict[str, object] | None) -> None:
        if not isinstance(payload, dict):
            return
        # Support both direct outcome (text submit) and nested request outcome (voice)
        outcome = payload.get("outcome")
        if not isinstance(outcome, dict):
            # Voice path: outcome is nested inside request
            request_payload = payload.get("request")
            if isinstance(request_payload, dict):
                outcome = request_payload.get("outcome")
        if not isinstance(outcome, dict):
            return

        provider_used = (self._payload_text(outcome, "augmented_provider_used") or self._payload_text(outcome, "augmented_provider")).lower()
        if provider_used not in {"openai", "kimi", "wikipedia"}:
            provider_used = "none"
        call_reason = self._payload_text(outcome, "augmented_provider_call_reason").lower()
        final_mode = self._payload_text(outcome, "final_mode").upper()
        outcome_code = self._payload_text(outcome, "outcome_code").lower()
        paid_invoked = self._payload_text(outcome, "augmented_paid_provider_invoked").lower() == "true"

        # Conservative accounting: missing metadata undercounts instead of overcounting.
        countable = False
        if call_reason in {"direct", "fallback"}:
            countable = provider_used != "none"
        elif call_reason == "error":
            countable = provider_used != "none"
        elif outcome_code in {"augmented_answer", "augmented_fallback_answer"}:
            countable = provider_used != "none"
        elif final_mode == "AUGMENTED":
            countable = provider_used != "none"

        if not countable:
            return

        self._session_augmented_calls_total += 1
        if paid_invoked:
            self._session_augmented_calls_paid += 1
        if provider_used == "openai":
            self._session_augmented_calls_openai += 1
        elif provider_used == "kimi":
            self._session_augmented_calls_kimi += 1
        elif provider_used == "wikipedia":
            self._session_augmented_calls_wikipedia += 1

    def _apply_top_status_visibility(self) -> None:
        if self._top_status_grid is None:
            return

        if self._interface_level == ENGINEERING:
            visible_labels = list(self._top_status_order)
        elif level_at_least(self._interface_level, ENGINEERING):
            visible_labels = ["Profile", "Router", "Model", "Approval Required", "Overall Status"]
        else:
            visible_labels = ["Profile", "Router", "Model", "Overall Status"]

        while self._top_status_grid.count():
            item = self._top_status_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()

        for index, label in enumerate(visible_labels):
            chip = self._top_status_cards[label]
            chip.show()
            self._top_status_grid.addWidget(chip, index // 4, index % 4)

    def _build_decision_trace_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("shellCard")
        panel.setVisible(False)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)

        title = QLabel("Decision Trace")
        title.setObjectName("sectionTitle")
        header.addWidget(title)

        subtitle = QLabel("Latest request only")
        subtitle.setObjectName("cardLabel")
        header.addWidget(subtitle)
        header.addStretch(1)

        self._decision_trace_hide_button = QPushButton("Hide")
        self._decision_trace_hide_button.clicked.connect(lambda: self._set_decision_trace_expanded(False))
        header.addWidget(self._decision_trace_hide_button)
        layout.addLayout(header)

        view = QPlainTextEdit()
        view.setObjectName("decisionTraceView")
        view.setReadOnly(True)
        view.setFixedHeight(150)
        self._decision_trace_view = view
        layout.addWidget(view)
        return panel

    def _refresh_decision_trace(self) -> None:
        payload = self._latest_decision_trace_details
        summary = self._build_decision_trace_summary(payload)
        available = bool(summary)
        self.conversation_panel.set_decision_trace_summary(
            summary or "Latest decision trace unavailable",
            available=available,
        )
        self._decision_trace_view.setPlainText(
            self._build_decision_trace_text(payload) if available else "No latest request metadata available."
        )
        if not available:
            self._set_decision_trace_expanded(False)

    def _handle_decision_trace_toggled(self, expanded: bool) -> None:
        if expanded and self._latest_decision_trace_details is None:
            self.conversation_panel.set_decision_trace_expanded(False)
            return
        self._set_decision_trace_expanded(expanded)

    def _set_decision_trace_expanded(self, expanded: bool) -> None:
        self._decision_trace_panel.setVisible(expanded)
        self.conversation_panel.set_decision_trace_expanded(expanded)

    def _decision_trace_contract(self, payload: dict[str, object] | None) -> dict[str, str]:
        if not isinstance(payload, dict):
            return {}
        return {
            "requested_mode": self._trace_value(payload, ("outcome", "requested_mode"), ("route", "requested_mode")),
            "effective_mode": self._trace_value(payload, ("outcome", "final_mode"), ("route", "final_mode")),
            "requested_route": self._trace_value(payload, ("route", "requested_route")),
            "selected_route": self._trace_value(payload, ("route", "selected_route"), ("route", "mode")),
            "route_mode": self._trace_value(payload, ("route", "mode")),
            "intent_class": self._trace_value(payload, ("route", "intent_class")),
            "evidence_mode": self._trace_value(payload, ("outcome", "evidence_mode"), ("route", "evidence_mode"), ("control_state", "evidence")),
            "augmented_policy": self._trace_value(payload, ("outcome", "augmented_policy"), ("control_state", "augmentation_policy")),
            "augmented_provider": self._trace_augmented_provider(payload),
            "augmented_provider_status": self._trace_value(payload, ("outcome", "augmented_provider_status")),
            "augmented_provider_error_reason": self._trace_value(payload, ("outcome", "augmented_provider_error_reason")),
            "provider_selection_reason": self._trace_value(payload, ("outcome", "augmented_provider_selection_reason")),
            "provider_selection_query": self._trace_value(payload, ("outcome", "augmented_provider_selection_query")),
            "provider_selection_rule": self._trace_value(payload, ("outcome", "augmented_provider_selection_rule")),
            "context_title": self._trace_value(payload, ("outcome", "unverified_context_title")),
            "context_url": self._trace_value(payload, ("outcome", "unverified_context_url")),
            "answer_class": self._trace_value(payload, ("outcome", "answer_class")),
            "operator_trust_label": self._trace_value(payload, ("outcome", "operator_trust_label")),
            "operator_answer_path": self._trace_value(payload, ("outcome", "operator_answer_path")),
            "operator_note": self._trace_value(payload, ("outcome", "operator_note")),
            "verification_status": self._trace_value(payload, ("outcome", "augmented_answer_contract", "verification_status")),
            "estimated_confidence_pct": self._trace_value(payload, ("outcome", "augmented_answer_contract", "estimated_confidence_pct")),
            "estimated_confidence_band": self._trace_value(payload, ("outcome", "augmented_answer_contract", "estimated_confidence_band")),
            "estimated_confidence_label": self._trace_value(payload, ("outcome", "augmented_answer_contract", "estimated_confidence_label")),
            "source_basis": self._trace_answer_contract_source_basis(payload),
            "trust_class": self._trace_value(payload, ("outcome", "trust_class")),
            "outcome_code": self._trace_value(payload, ("outcome", "outcome_code")),
            "primary_outcome_code": self._trace_value(payload, ("outcome", "primary_outcome_code")),
            "recovery_lane": self._trace_value(payload, ("outcome", "recovery_lane")),
            "recovery_used": self._trace_value(payload, ("outcome", "recovery_used")),
            "action_hint": self._trace_value(payload, ("outcome", "action_hint")),
            "reason": self._trace_value(payload, ("route", "reason"), ("outcome", "fallback_reason")),
            "route_confidence": self._trace_value(payload, ("route", "confidence")),
            "forced_augmented": self._trace_value(payload, ("outcome", "augmented_direct_request")),
        }

    def _build_decision_trace_summary(self, payload: dict[str, object] | None) -> str:
        trace = self._decision_trace_contract(payload)
        if not trace:
            return ""
        requested_mode = trace["requested_mode"].upper()
        final_mode = trace["effective_mode"].upper()
        provider = trace["augmented_provider"].upper()
        trust_class = self._display_operator_trust(payload)
        outcome_code = trace["outcome_code"]
        forced_augmented = trace["forced_augmented"].lower() in {"1", "true", "yes", "on"}

        left = requested_mode or "LATEST"
        if forced_augmented and left == "AUGMENTED":
            left = "FORCED AUGMENTED"

        right = final_mode or "UNKNOWN"
        if right == "AUGMENTED" and provider and provider != "NONE":
            right = provider

        summary = f"{left} -> {right}"
        operator_note = self._operator_trace_note(payload)
        if operator_note:
            summary = f"{summary} | {operator_note}"
        provider_status_note = self._augmented_provider_status_note(payload)
        if provider_status_note:
            summary = f"{summary} | {provider_status_note}"
        route_confidence = trace.get("route_confidence")
        if route_confidence:
            summary = f"{summary} | confidence={route_confidence}"
        if trust_class:
            summary = f"{summary} | trust={trust_class}"
        elif outcome_code:
            summary = f"{summary} | outcome={outcome_code}"
        return summary

    def _build_decision_trace_text(self, payload: dict[str, object] | None) -> str:
        trace = self._decision_trace_contract(payload)
        if not trace:
            return "No latest request metadata available."

        fields = [
            ("Operator Summary", self._operator_trace_summary(payload)),
            ("Requested Mode", trace["requested_mode"]),
            ("Effective Mode", trace["effective_mode"]),
            ("Requested Route", trace["requested_route"]),
            ("Selected Route", trace["selected_route"]),
            ("Route Mode", trace["route_mode"]),
            ("Intent Classification", trace["intent_class"]),
            ("Evidence Mode", trace["evidence_mode"]),
            ("Augmented Policy", trace["augmented_policy"]),
            ("Augmented Provider", trace["augmented_provider"]),
            ("Augmented Provider Status", trace["augmented_provider_status"]),
            ("Augmented Provider Error", trace["augmented_provider_error_reason"]),
            ("Provider Selection Reason", trace["provider_selection_reason"]),
            ("Provider Selection Query", trace["provider_selection_query"]),
            ("Provider Selection Rule", trace["provider_selection_rule"]),
            ("Context Title", trace["context_title"]),
            ("Context URL", trace["context_url"]),
            ("Answer Class", trace["answer_class"]),
            ("Route Confidence", trace["route_confidence"]),
            ("Operator Trust", self._display_operator_trust(payload)),
            ("Operator Answer Path", self._display_operator_answer_path(payload)),
            ("Operator Note", self._display_operator_note(payload)),
            ("Verification Status", trace["verification_status"]),
            (
                "Estimated Confidence",
                trace["estimated_confidence_label"]
                or (
                    f"{trace['estimated_confidence_pct']}% ({trace['estimated_confidence_band']}, estimated)"
                    if trace["estimated_confidence_pct"] and trace["estimated_confidence_band"]
                    else (f"{trace['estimated_confidence_pct']}% estimated" if trace["estimated_confidence_pct"] else "")
                ),
            ),
            ("Source Basis", trace["source_basis"]),
            ("Trust Class", trace["trust_class"]),
            ("Outcome Code", trace["outcome_code"]),
            ("Primary Outcome Code", trace["primary_outcome_code"]),
            ("Recovery Used", trace["recovery_used"]),
            ("Recovery Lane", trace["recovery_lane"]),
            ("Fallback", self._trace_fallback_text(payload)),
            ("Action Hint", trace["action_hint"]),
            ("Reason", trace["reason"]),
        ]

        lines = []
        for label, value in fields:
            text = str(value or "").strip()
            if not text:
                continue
            lines.append(f"{label}: {text}")
        return "\n".join(lines) if lines else "No latest request metadata available."

    def _trace_fallback_text(self, payload: dict[str, object] | None) -> str:
        used = self._trace_value(payload, ("outcome", "fallback_used"))
        reason = self._trace_value(
            payload,
            ("outcome", "fallback_reason"),
            ("outcome", "augmented_provider_call_reason"),
        )
        if used and reason:
            return f"{used} ({reason})"
        return used or reason

    def _operator_trace_summary(self, payload: dict[str, object] | None) -> str:
        answer_path = self._display_operator_answer_path(payload)
        if self._is_validated_insufficient(payload):
            return self._display_operator_note(payload)
        if answer_path == "Evidence insufficient -> local best-effort recovery":
            return "Recovery provided a local best-effort answer after insufficient evidence."
        if answer_path.startswith("Local degraded -> "):
            provider = answer_path.replace("Local degraded -> ", "").replace(" fallback", "")
            return f"Escalated from degraded local answer to {provider} fallback."
        if answer_path.startswith("Evidence insufficient -> "):
            provider = answer_path.replace("Evidence insufficient -> ", "").replace(" fallback", "")
            return f"Escalated from insufficient evidence path to {provider} fallback."
        if answer_path == "Evidence-backed answer":
            return "Answer stayed on the evidence-backed path."
        if answer_path == "Clarification requested":
            return "A narrower question was required."
        if answer_path == "Local answer":
            return "Answer stayed on the local path."

        final_mode = (self._trace_value(payload, ("outcome", "final_mode")) or self._trace_value(payload, ("route", "mode"))).upper()
        trust_class = self._trace_value(payload, ("outcome", "trust_class")).lower()
        fallback_reason = self._trace_value(payload, ("outcome", "fallback_reason"))
        fallback_used = self._trace_value(payload, ("outcome", "fallback_used")).lower() in {"1", "true", "yes", "on"}
        provider = (
            self._trace_value(payload, ("outcome", "augmented_provider_used"))
            or self._trace_value(payload, ("outcome", "augmented_provider"))
            or self._trace_value(payload, ("control_state", "augmented_provider"))
        )
        provider_label = provider.upper() if provider and provider.lower() != "none" else "augmented"
        outcome_code = self._trace_value(payload, ("outcome", "outcome_code")).lower()

        if final_mode == "AUGMENTED" and fallback_used and fallback_reason == "local_generation_degraded":
            return f"Escalated from degraded local answer to {provider_label} fallback."
        if final_mode == "AUGMENTED" and fallback_used and fallback_reason == "validated_insufficient":
            return f"Escalated from insufficient evidence path to {provider_label} fallback."
        if trust_class == "evidence_backed" or final_mode == "EVIDENCE":
            return "Answer stayed on the evidence-backed path."
        if outcome_code == "clarification_requested" or final_mode == "CLARIFY":
            return "A narrower question was required."
        if final_mode == "LOCAL":
            return "Answer stayed on the local path."
        if final_mode == "SELF_REVIEW":
            return "Answer stayed on the self-review path."
        return ""

    def _operator_trace_note(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            return "evidence insufficient"
        summary = self._operator_trace_summary(payload)
        if summary.startswith("Recovery provided a local best-effort answer"):
            return "best-effort recovery"
        if summary.startswith("Escalated from degraded local answer"):
            return "local degraded"
        if summary.startswith("Escalated from insufficient evidence path"):
            return "evidence insufficient"
        if summary.startswith("Answer stayed on the evidence-backed path"):
            return "evidence-backed"
        if summary.startswith("Answer stayed on the local path"):
            return "local path"
        if summary.startswith("A narrower question was required"):
            return "clarify"
        return ""

    def _display_operator_trust(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            return "insufficient-evidence"
        return self._trace_value(payload, ("outcome", "operator_trust_label"), ("outcome", "trust_class"))

    def _display_operator_answer_path(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            return "Evidence insufficient"
        return self._trace_value(payload, ("outcome", "operator_answer_path"))

    def _display_operator_note(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            action_hint = self._trace_action_hint(payload)
            if action_hint:
                return f"Current evidence was insufficient. Next step: {action_hint}"
            return "Current evidence was insufficient for a reliable answer."
        return self._trace_value(payload, ("outcome", "operator_note"))

    def _augmented_provider_status_note(self, payload: dict[str, object] | None) -> str:
        status = self._trace_value(payload, ("outcome", "augmented_provider_status")).lower()
        if status == "external_unavailable":
            return "provider unavailable"
        if status == "misconfigured":
            return "provider misconfigured"
        if status == "provider_error":
            return "provider error"
        return ""

    def _trace_augmented_provider(self, payload: dict[str, object] | None) -> str:
        provider = ""
        for candidate in (
            self._trace_value(payload, ("outcome", "augmented_provider_used")),
            self._trace_value(payload, ("outcome", "augmented_provider")),
            self._trace_value(payload, ("control_state", "augmented_provider")),
        ):
            raw = str(candidate or "").strip()
            if not raw or raw.lower() == "none":
                continue
            provider = raw
            break
        if provider:
            return provider
        return self._trace_value(
            payload,
            ("outcome", "augmented_provider_used"),
            ("outcome", "augmented_provider"),
            ("control_state", "augmented_provider"),
        )

    def _trace_action_hint(self, payload: dict[str, object] | None) -> str:
        action_hint = self._trace_value(payload, ("outcome", "action_hint")).strip()
        if not action_hint or action_hint.lower() == "none":
            return ""
        if action_hint[-1] not in ".!?":
            action_hint = f"{action_hint}."
        return action_hint

    def _is_validated_insufficient(self, payload: dict[str, object] | None) -> bool:
        outcome_code = self._trace_value(payload, ("outcome", "outcome_code")).lower()
        if outcome_code != "validated_insufficient":
            return False
        return self._trace_value(payload, ("outcome", "fallback_used")).lower() not in {"1", "true", "yes", "on"}

    def _trace_value(
        self,
        payload: dict[str, object] | None,
        *paths: tuple[str, ...],
    ) -> str:
        for path in paths:
            value = self._trace_nested_value(payload, path)
            if value:
                return value
        return ""

    def _trace_answer_contract_source_basis(self, payload: dict[str, object] | None) -> str:
        current: object = payload
        for part in ("outcome", "augmented_answer_contract", "source_basis"):
            if not isinstance(current, dict):
                return ""
            current = current.get(part)
        if isinstance(current, list):
            values = [str(item).strip() for item in current if str(item).strip()]
            return ", ".join(values)
        if current is None:
            return ""
        return str(current).strip()

    def _trace_nested_value(self, payload: dict[str, object] | None, path: tuple[str, ...]) -> str:
        current = payload
        for part in path:
            if not isinstance(current, dict):
                return ""
            current = current.get(part)
        if current is None:
            return ""
        return str(current).strip()

    def _build_top_status_bar(self) -> QFrame:
        status_bar = QFrame()
        status_bar.setObjectName("shellCard")

        outer_layout = QVBoxLayout(status_bar)
        outer_layout.setContentsMargins(12, 12, 12, 12)
        outer_layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        level_label = QLabel("Interface Level")
        level_label.setObjectName("cardLabel")
        header.addWidget(level_label)

        self._level_button_group = QButtonGroup(self)
        self._level_button_group.setExclusive(True)
        for level in LEVELS:
            button = QPushButton(display_level(level))
            button.setObjectName("levelButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=level: self._handle_interface_level_selected(value))
            self._level_button_group.addButton(button)
            self._level_buttons[level] = button
            header.addWidget(button)

        header.addStretch(1)
        outer_layout.addLayout(header)

        layout = QGridLayout()
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(10)
        self._top_status_grid = layout

        fields = [
            ("Profile", "loading"),
            ("Mode", "loading"),
            ("Router", "loading"),
            ("Model", "loading"),
            ("Memory", "loading"),
            ("Evidence", "loading"),
            ("Voice", "loading"),
            ("Approval Required", "loading"),
            ("Overall Status", "loading"),
        ]

        self._top_status_order = [label for label, _ in fields]
        for index, (label, value) in enumerate(fields):
            row = index // 4
            column = index % 4
            layout.addWidget(self._build_status_chip(label, value), row, column)

        outer_layout.addLayout(layout)
        return status_bar

    def _build_status_chip(self, label_text: str, value_text: str) -> QFrame:
        chip = QFrame()
        chip.setObjectName("statusChip")

        layout = QVBoxLayout(chip)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("cardLabel")
        value = QLabel(value_text)
        value.setObjectName("cardValue")
        value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._top_status_labels[label_text] = value
        self._top_status_cards[label_text] = chip

        layout.addWidget(label)
        layout.addWidget(value)
        return chip
