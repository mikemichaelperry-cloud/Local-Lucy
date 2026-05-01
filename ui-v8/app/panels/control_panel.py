from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui_levels import ENGINEERING, level_at_least


class ControlPanel(QFrame):
    refresh_requested = Signal()
    copy_state_requested = Signal()
    open_logs_requested = Signal()
    open_state_requested = Signal()
    mode_change_requested = Signal(str)
    conversation_change_requested = Signal(str)
    memory_change_requested = Signal(str)
    evidence_change_requested = Signal(str)
    voice_change_requested = Signal(str)
    augmented_policy_change_requested = Signal(str)
    augmented_provider_change_requested = Signal(str)
    model_change_requested = Signal(str)
    ptt_pressed_requested = Signal()
    ptt_released_requested = Signal()
    reload_profile_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shellCard")
        self.setMinimumWidth(280)
        self._scroll_area: QScrollArea | None = None
        self._content_widget: QWidget | None = None
        self._mode_note: QLabel | None = None
        self._feature_note: QLabel | None = None
        self._profile_note: QLabel | None = None
        self._mode_group: QGroupBox | None = None
        self._feature_group: QGroupBox | None = None
        self._voice_ptt_group: QGroupBox | None = None
        self._profile_group: QGroupBox | None = None
        self._voice_ptt_button: QPushButton | None = None
        self._voice_ptt_status_label: QLabel | None = None
        self._voice_status_group: QGroupBox | None = None
        self._voice_stage_label: QLabel | None = None
        self._voice_mode_label: QLabel | None = None
        self._voice_tts_label: QLabel | None = None
        self._voice_progress: QProgressBar | None = None
        self._voice_transcription_preview: QLabel | None = None
        self._reload_profile_button: QPushButton | None = None
        self._profile_value_label: QLabel | None = None
        self._copy_button: QPushButton | None = None
        self._open_logs_button: QPushButton | None = None
        self._open_state_button: QPushButton | None = None
        self._safe_actions_note: QLabel | None = None
        self._current_values = {
            "mode": "",
            "conversation": "",
            "memory": "",
            "evidence": "",
            "voice": "",
            "augmentation_policy": "",
            "augmented_provider": "",
            "model": "",
            "profile": "",
        }
        self._backend_available = False
        self._backend_busy = False
        self._profile_available = False
        self._voice_runtime: dict[str, Any] = {
            "available": False,
            "listening": False,
            "processing": False,
            "status": "unavailable",
            "last_error": "",
            "pipeline_stage": "idle",
            "pipeline_progress": 0.0,
            "transcription_preview": "",
        }
        self._voice_pulse_timer: QTimer | None = None
        self._voice_pulse_state: int = 0

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("panelScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        self._scroll_area = scroll_area
        root_layout.addWidget(scroll_area)

        content_widget = QWidget()
        content_widget.setObjectName("panelScrollContent")
        self._content_widget = content_widget
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        scroll_area.setWidget(content_widget)
        scroll_area.viewport().setObjectName("panelScrollViewport")
        scroll_area.viewport().setAutoFillBackground(False)

        title = QLabel("Control Panel")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        layout.addWidget(self._build_mode_group())
        layout.addWidget(self._build_feature_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_voice_status_group())
        layout.addWidget(self._build_profile_group())
        layout.addWidget(self._build_safe_actions_group())
        layout.addStretch(1)

    def _build_mode_group(self) -> QGroupBox:
        group = QGroupBox("Mode Selection")
        self._mode_group = group

        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._mode_selector = QComboBox()
        self._mode_selector.addItems(["auto", "online", "offline"])
        self._mode_selector.activated.connect(self._handle_mode_activated)
        layout.addWidget(self._build_labeled_row("mode", self._mode_selector))

        note = QLabel("Mode control unavailable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._mode_note = note
        group.setDisabled(True)
        return group

    def _build_feature_group(self) -> QGroupBox:
        group = QGroupBox("Runtime Toggles")
        self._feature_group = group

        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._memory_selector = QComboBox()
        self._memory_selector.addItems(["on", "off"])
        self._memory_selector.activated.connect(self._handle_memory_activated)

        self._conversation_selector = QComboBox()
        self._conversation_selector.addItems(["on", "off"])
        self._conversation_selector.activated.connect(self._handle_conversation_activated)

        self._evidence_selector = QComboBox()
        self._evidence_selector.addItems(["on", "off"])
        self._evidence_selector.activated.connect(self._handle_evidence_activated)

        self._voice_selector = QComboBox()
        self._voice_selector.addItems(["on", "off"])
        self._voice_selector.activated.connect(self._handle_voice_activated)

        self._augmentation_policy_selector = QComboBox()
        self._augmentation_policy_selector.addItems(["disabled", "fallback_only", "direct_allowed"])
        self._augmentation_policy_selector.activated.connect(self._handle_augmentation_policy_activated)

        self._augmented_provider_selector = QComboBox()
        self._augmented_provider_selector.addItems(["wikipedia", "openai", "kimi"])
        self._augmented_provider_selector.activated.connect(self._handle_augmented_provider_activated)

        self._model_selector = QComboBox()
        self._model_selector.addItems(["local-lucy", "local-lucy-qwen3"])
        self._model_selector.activated.connect(self._handle_model_activated)

        layout.addWidget(self._build_labeled_row("model", self._model_selector))
        layout.addWidget(self._build_labeled_row("conversation", self._conversation_selector))
        layout.addWidget(self._build_labeled_row("memory", self._memory_selector))
        layout.addWidget(self._build_labeled_row("evidence", self._evidence_selector))
        layout.addWidget(self._build_labeled_row("voice", self._voice_selector))
        layout.addWidget(self._build_labeled_row("augmented policy", self._augmentation_policy_selector))
        layout.addWidget(self._build_labeled_row("augmented provider", self._augmented_provider_selector))

        note = QLabel("Feature toggles unavailable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._feature_note = note
        group.setDisabled(True)
        return group

    def _build_labeled_row(self, label_text: str, selector: QComboBox) -> QFrame:
        row = QFrame()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("cardLabel")

        layout.addWidget(label)
        layout.addStretch(1)
        layout.addWidget(selector)
        return row

    def _build_voice_group(self) -> QGroupBox:
        group = QGroupBox("Voice PTT")
        self._voice_ptt_group = group
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        button = QPushButton("Hold to Talk")
        button.setObjectName("pttButton")
        button.pressed.connect(self.ptt_pressed_requested.emit)
        button.released.connect(self.ptt_released_requested.emit)
        self._voice_ptt_button = button
        layout.addWidget(button)

        status_label = QLabel("Voice PTT unavailable.")
        status_label.setWordWrap(True)
        self._voice_ptt_status_label = status_label
        layout.addWidget(status_label)

        group.setVisible(False)
        return group

    def _build_voice_status_group(self) -> QGroupBox:
        """Build voice pipeline status display group."""
        group = QGroupBox("Voice Pipeline Status")
        self._voice_status_group = group
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        # Stage indicator with icon
        stage_row = QHBoxLayout()
        self._voice_stage_label = QLabel("🔘 Idle")
        self._voice_stage_label.setObjectName("cardLabel")
        stage_row.addWidget(self._voice_stage_label)
        stage_row.addStretch(1)
        layout.addLayout(stage_row)

        # Voice mode indicator (Python vs Shell)
        mode_row = QHBoxLayout()
        voice_py = os.environ.get("LUCY_VOICE_PY", "0")
        voice_mode_text = "🐍 Python Voice" if voice_py == "1" else "🐚 Shell Voice"
        voice_mode_color = "#2ecc71" if voice_py == "1" else "#7f8d97"
        self._voice_mode_label = QLabel(voice_mode_text)
        self._voice_mode_label.setObjectName("voiceModeLabel")
        self._voice_mode_label.setStyleSheet(f"color: {voice_mode_color}; font-size: 11px; font-weight: bold;")
        mode_row.addWidget(self._voice_mode_label)
        mode_row.addStretch(1)
        layout.addLayout(mode_row)

        # TTS Engine indicator (Kokoro vs Piper)
        tts_row = QHBoxLayout()
        self._voice_tts_label = QLabel("🔊 TTS: detecting...")
        self._voice_tts_label.setObjectName("voiceTtsLabel")
        self._voice_tts_label.setStyleSheet("color: #7f8d97; font-size: 11px;")
        tts_row.addWidget(self._voice_tts_label)
        tts_row.addStretch(1)
        layout.addLayout(tts_row)

        # Progress bar for pipeline stages
        self._voice_progress = QProgressBar()
        self._voice_progress.setRange(0, 100)
        self._voice_progress.setValue(0)
        self._voice_progress.setTextVisible(False)
        self._voice_progress.setFixedHeight(6)
        layout.addWidget(self._voice_progress)

        # Transcription preview
        self._voice_transcription_preview = QLabel("")
        self._voice_transcription_preview.setObjectName("cardValue")
        self._voice_transcription_preview.setWordWrap(True)
        self._voice_transcription_preview.setStyleSheet("color: #94a5b1; font-style: italic;")
        layout.addWidget(self._voice_transcription_preview)

        group.setVisible(False)
        return group

    def update_voice_pipeline_status(self, stage: str, progress: float, transcription: str = "") -> None:
        """Update voice pipeline status display.
        
        Args:
            stage: Pipeline stage (idle, recording, transcribing, processing, speaking, error)
            progress: Progress value 0.0-1.0
            transcription: Optional transcription preview text
        """
        if self._voice_stage_label is None or self._voice_progress is None:
            return

        stage_names = {
            "idle": "🔘 Idle",
            "recording": "🔴 Recording...",
            "transcribing": "🟡 Transcribing...",
            "processing": "🔵 Processing...",
            "speaking": "🟢 Speaking...",
            "error": "❌ Error",
        }
        
        stage_colors = {
            "idle": "#7f8d97",
            "recording": "#e74c3c",
            "transcribing": "#f1c40f",
            "processing": "#3498db",
            "speaking": "#2ecc71",
            "error": "#e74c3c",
        }

        display_stage = stage_names.get(stage, f"⚪ {stage}")
        self._voice_stage_label.setText(display_stage)
        
        # Update progress bar
        self._voice_progress.setValue(int(progress * 100))
        color = stage_colors.get(stage, "#7f8d97")
        self._voice_progress.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

        # Update transcription preview
        if self._voice_transcription_preview is not None:
            if transcription:
                preview = transcription if len(transcription) <= 64 else f"{transcription[:61]}..."
                self._voice_transcription_preview.setText(f'"{preview}"')
                self._voice_transcription_preview.setVisible(True)
            else:
                self._voice_transcription_preview.setText("")
                self._voice_transcription_preview.setVisible(False)

        # Apply stage-based styling to the group
        if self._voice_status_group is not None:
            border_color = stage_colors.get(stage, "#2f3b45")
            self._voice_status_group.setStyleSheet(f"""
                QGroupBox {{ border: 2px solid {border_color}; }}
            """)

        # Start/stop pulse animation for recording stage
        if stage == "recording":
            self._start_voice_pulse()
        else:
            self._stop_voice_pulse()

    def _start_voice_pulse(self) -> None:
        """Start pulsing animation for recording indicator."""
        if self._voice_pulse_timer is not None:
            return
        self._voice_pulse_timer = QTimer(self)
        self._voice_pulse_timer.timeout.connect(self._on_voice_pulse)
        self._voice_pulse_timer.start(500)  # 500ms pulse

    def _stop_voice_pulse(self) -> None:
        """Stop pulsing animation."""
        if self._voice_pulse_timer is not None:
            self._voice_pulse_timer.stop()
            self._voice_pulse_timer = None

    def _on_voice_pulse(self) -> None:
        """Toggle pulse state for recording indicator."""
        if self._voice_stage_label is None:
            return
        self._voice_pulse_state = 1 - self._voice_pulse_state
        if self._voice_pulse_state:
            self._voice_stage_label.setText("🔴 Recording...")
        else:
            self._voice_stage_label.setText("⚪ Recording...")

    def _build_profile_group(self) -> QGroupBox:
        group = QGroupBox("Profile")
        self._profile_group = group
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        row = QHBoxLayout()
        row.setSpacing(8)

        name = QLabel("Active profile: unavailable")
        self._profile_value_label = name
        reload_button = QPushButton("Reset Profile Defaults")
        reload_button.clicked.connect(self.reload_profile_requested.emit)
        reload_button.setDisabled(True)
        self._reload_profile_button = reload_button

        row.addWidget(name, stretch=1)
        layout.addLayout(row)
        layout.addWidget(reload_button)
        note = QLabel("Profile defaults reset unavailable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._profile_note = note
        group.setDisabled(True)
        return group

    def _build_safe_actions_group(self) -> QGroupBox:
        group = QGroupBox("Actions")
        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        refresh_button = QPushButton("Refresh Now")
        refresh_button.clicked.connect(self.refresh_requested.emit)

        copy_button = QPushButton("Copy State Summary")
        copy_button.clicked.connect(self.copy_state_requested.emit)
        self._copy_button = copy_button

        open_logs_button = QPushButton("Open Log Directory")
        open_logs_button.clicked.connect(self.open_logs_requested.emit)
        self._open_logs_button = open_logs_button

        open_state_button = QPushButton("Open State Directory")
        open_state_button.clicked.connect(self.open_state_requested.emit)
        self._open_state_button = open_state_button

        layout.addWidget(refresh_button)
        layout.addWidget(copy_button)
        layout.addWidget(open_logs_button)
        layout.addWidget(open_state_button)

        note = QLabel("These actions are UI-local or read-safe only.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._safe_actions_note = note
        return group

    def apply_backend_capabilities(self, capability_notes: dict[str, str], backend_available: bool) -> None:
        if self._mode_note is not None:
            self._mode_note.setText(capability_notes.get("mode_selection", self._mode_note.text()))
        if self._feature_note is not None:
            self._feature_note.setText(capability_notes.get("feature_toggles", self._feature_note.text()))
        if self._profile_note is not None:
            self._profile_note.setText(capability_notes.get("profile_reload", self._profile_note.text()))
        self.set_backend_enabled(backend_available)

    def set_backend_busy(self, busy: bool) -> None:
        self._backend_busy = busy
        if self._mode_group is not None:
            self._mode_group.setEnabled(self._backend_available and not busy)
        if self._feature_group is not None:
            self._feature_group.setEnabled(self._backend_available and not busy)
        self._apply_profile_button_state(busy)
        self._refresh_voice_ptt()

    def set_backend_enabled(self, enabled: bool) -> None:
        self._backend_available = enabled
        if self._mode_group is not None:
            self._mode_group.setEnabled(enabled)
        if self._feature_group is not None:
            self._feature_group.setEnabled(enabled)
        self._refresh_voice_ptt()

    def set_profile_reload_available(self, available: bool) -> None:
        self._profile_available = available
        if self._profile_group is not None:
            self._profile_group.setEnabled(available)
        self._apply_profile_button_state(self._backend_busy)

    def set_interface_level(self, level: str) -> None:
        show_profile_group = level_at_least(level, ENGINEERING)
        for group in (
            self._mode_group,
            self._feature_group,
            self._profile_group,
        ):
            if group is not None:
                group.setVisible(group is not self._profile_group or show_profile_group)
        # Voice PTT visibility is controlled by voice state, not interface level
        self._refresh_voice_ptt()
        for widget in (
            self._mode_note,
            self._feature_note,
            self._profile_note,
            self._copy_button,
            self._open_logs_button,
            self._open_state_button,
            self._safe_actions_note,
        ):
            if widget is not None:
                widget.setVisible(level == ENGINEERING)

    def update_control_state(self, top_status: dict[str, str], current_state: dict[str, Any] | None = None) -> None:
        values = {
            "profile": top_status.get("Profile", "").strip(),
            "mode": top_status.get("Mode", "").strip().lower(),
            "conversation": top_status.get("Conversation", "").strip().lower(),
            "memory": top_status.get("Memory", "").strip().lower(),
            "evidence": top_status.get("Evidence", "").strip().lower(),
            "voice": top_status.get("Voice", "").strip().lower(),
            "augmentation_policy": top_status.get("Augmented Policy", "").strip().lower(),
            "augmented_provider": top_status.get("Augmented Provider", "").strip().lower(),
            "model": top_status.get("Model", "").strip(),
        }
        self._current_values.update(values)
        if self._profile_value_label is not None:
            profile_text = values["profile"] or "unavailable"
            self._profile_value_label.setText(f"Active profile: {profile_text}")
        self._set_selector_value(self._mode_selector, values["mode"])
        self._set_selector_value(self._conversation_selector, values["conversation"])
        self._set_selector_value(self._memory_selector, values["memory"])
        self._set_selector_value(self._evidence_selector, values["evidence"])
        self._set_selector_value(self._voice_selector, values["voice"])
        self._set_selector_value(self._augmentation_policy_selector, values["augmentation_policy"])
        self._set_selector_value(self._augmented_provider_selector, values["augmented_provider"])
        self._set_selector_value(self._model_selector, values.get("model", ""))
        self._refresh_voice_ptt()

    def update_voice_runtime(self, voice_runtime: dict[str, Any]) -> None:
        self._voice_runtime = dict(voice_runtime)
        self._refresh_voice_ptt()
        self._refresh_voice_status()

    def _refresh_voice_status(self) -> None:
        """Refresh voice pipeline status display based on runtime state."""
        if self._voice_status_group is None:
            return

        voice_enabled = self._current_values.get("voice", "") == "on"
        self._voice_status_group.setVisible(voice_enabled)
        if not voice_enabled:
            self._stop_voice_pulse()
            return

        # Get pipeline state from runtime
        stage = str(self._voice_runtime.get("pipeline_stage", "idle")).lower()
        progress = float(self._voice_runtime.get("pipeline_progress", 0.0))
        transcription = str(self._voice_runtime.get("transcription_preview", ""))
        
        # Derive stage from runtime state if not explicitly set
        status = str(self._voice_runtime.get("status", "unknown")).lower()
        listening = bool(self._voice_runtime.get("listening", False))
        processing = bool(self._voice_runtime.get("processing", False))
        
        if stage == "idle":
            if listening:
                stage = "recording"
                progress = max(progress, 0.25)
            elif processing:
                stage = "processing"
                progress = max(progress, 0.5)
            elif status in ("fault", "error"):
                stage = "error"
        
        self.update_voice_pipeline_status(stage, progress, transcription)
        
        # Update TTS engine indicator
        if self._voice_tts_label is not None:
            tts_engine = str(self._voice_runtime.get("tts", "none")).lower()
            if tts_engine == "kokoro":
                self._voice_tts_label.setText("🔊 TTS: Kokoro (GPU)")
                self._voice_tts_label.setStyleSheet("color: #2ecc71; font-size: 11px; font-weight: bold;")
            elif tts_engine == "piper":
                self._voice_tts_label.setText("🔊 TTS: Piper (CPU)")
                self._voice_tts_label.setStyleSheet("color: #f1c40f; font-size: 11px;")
            elif tts_engine == "none":
                self._voice_tts_label.setText("🔊 TTS: none")
                self._voice_tts_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
            else:
                self._voice_tts_label.setText(f"🔊 TTS: {tts_engine}")
                self._voice_tts_label.setStyleSheet("color: #7f8d97; font-size: 11px;")

    def _set_selector_value(self, selector: QComboBox, value: str) -> None:
        selector.blockSignals(True)
        index = selector.findText(value)
        if index >= 0:
            selector.setCurrentIndex(index)
        else:
            selector.setCurrentIndex(-1)
        selector.blockSignals(False)

    def _handle_mode_activated(self, index: int) -> None:
        self._emit_if_changed("mode", self._mode_selector.itemText(index), self.mode_change_requested)

    def _handle_conversation_activated(self, index: int) -> None:
        self._emit_if_changed("conversation", self._conversation_selector.itemText(index), self.conversation_change_requested)

    def _handle_memory_activated(self, index: int) -> None:
        self._emit_if_changed("memory", self._memory_selector.itemText(index), self.memory_change_requested)

    def _handle_evidence_activated(self, index: int) -> None:
        self._emit_if_changed("evidence", self._evidence_selector.itemText(index), self.evidence_change_requested)

    def _handle_voice_activated(self, index: int) -> None:
        self._emit_if_changed("voice", self._voice_selector.itemText(index), self.voice_change_requested)

    def _handle_augmentation_policy_activated(self, index: int) -> None:
        self._emit_if_changed(
            "augmentation_policy",
            self._augmentation_policy_selector.itemText(index),
            self.augmented_policy_change_requested,
        )

    def _handle_augmented_provider_activated(self, index: int) -> None:
        self._emit_if_changed(
            "augmented_provider",
            self._augmented_provider_selector.itemText(index),
            self.augmented_provider_change_requested,
        )

    def _handle_model_activated(self, index: int) -> None:
        self._emit_if_changed(
            "model",
            self._model_selector.itemText(index),
            self.model_change_requested,
        )

    def _emit_if_changed(self, key: str, requested_value: str, signal: Signal) -> None:
        if requested_value == self._current_values.get(key, ""):
            self.update_control_state(
                {
                    "Profile": self._current_values["profile"],
                    "Mode": self._current_values["mode"],
                    "Conversation": self._current_values["conversation"],
                    "Memory": self._current_values["memory"],
                    "Evidence": self._current_values["evidence"],
                    "Voice": self._current_values["voice"],
                    "Augmented Policy": self._current_values["augmentation_policy"],
                    "Augmented Provider": self._current_values["augmented_provider"],
                    "Model": self._current_values.get("model", ""),
                }
            )
            return
        signal.emit(requested_value)

    def _apply_profile_button_state(self, busy: bool) -> None:
        if self._profile_group is not None:
            self._profile_group.setEnabled(self._profile_available)
        if self._reload_profile_button is not None:
            self._reload_profile_button.setEnabled(self._profile_available and not busy)

    def _refresh_voice_ptt(self) -> None:
        if self._voice_ptt_group is None or self._voice_ptt_button is None or self._voice_ptt_status_label is None:
            return

        voice_enabled = self._current_values.get("voice", "") == "on"
        self._voice_ptt_group.setVisible(voice_enabled)
        if not voice_enabled:
            return

        status = str(self._voice_runtime.get("status", "unknown")).strip().lower()
        available = bool(self._voice_runtime.get("available", False)) and self._backend_available
        listening = bool(self._voice_runtime.get("listening", False))
        processing = bool(self._voice_runtime.get("processing", False))
        last_error = str(self._voice_runtime.get("last_error", "")).strip()

        button_state = "idle"
        button_text = "Hold to Talk"
        status_text = "Voice PTT: idle"
        button_enabled = available and not self._backend_busy

        if listening:
            button_state = "listening"
            button_text = "Release to Send"
            status_text = "Voice PTT: listening"
            button_enabled = True
        elif processing:
            button_state = "processing"
            button_text = "Processing..."
            status_text = "Voice PTT: processing"
            button_enabled = False
        elif not available or status == "unavailable":
            button_state = "unavailable"
            button_text = "PTT Unavailable"
            status_text = f"Voice PTT: {last_error or status or 'unavailable'}"
            button_enabled = False
        elif status == "fault":
            button_state = "fault"
            button_text = "PTT Fault"
            status_text = f"Voice PTT: {last_error or 'fault'}"
            button_enabled = False
        elif self._backend_busy:
            button_state = "busy"
            button_text = "Backend Busy"
            status_text = "Voice PTT: backend busy"
            button_enabled = False

        self._voice_ptt_button.setText(button_text)
        self._voice_ptt_button.setEnabled(button_enabled)
        self._voice_ptt_button.setProperty("voiceState", button_state)
        self._voice_ptt_button.style().unpolish(self._voice_ptt_button)
        self._voice_ptt_button.style().polish(self._voice_ptt_button)
        self._voice_ptt_status_label.setText(status_text)
