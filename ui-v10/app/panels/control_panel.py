from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui_levels import ENGINEERING, POWER, level_at_least
from app.widgets.vu_meter import VoiceVUMeter


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
    gemma4_smart_routing_change_requested = Signal(str)
    self_analysis_change_requested = Signal(str)
    learner_change_requested = Signal(str)
    ptt_pressed_requested = Signal()
    ptt_released_requested = Signal()
    reload_profile_requested = Signal()
    shutdown_requested = Signal()

    # Model label mapping: backend value → display label
    _MODEL_LABELS: dict[str, str] = {
        "auto": "Auto (Lucy chooses per query)",
        "local-lucy-llama31": "local-lucy-llama31 (llama3.1 8B)",
        "gemma4:12b-it-qat": "gemma4:12b-it-qat (gemma4 12B reasoning/multimodal)",
    }

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shellCard")
        self.setMinimumWidth(280)
        self._scroll_area: QScrollArea | None = None
        self._content_widget: QWidget | None = None
        self._operator_note: QLabel | None = None
        self._engineering_note: QLabel | None = None
        self._profile_note: QLabel | None = None
        self._operator_group: QGroupBox | None = None
        self._engineering_group: QGroupBox | None = None
        self._voice_ptt_group: QGroupBox | None = None
        self._profile_group: QGroupBox | None = None
        self._voice_ptt_button: QPushButton | None = None
        self._voice_ptt_status_label: QLabel | None = None
        self._voice_status_group: QGroupBox | None = None
        self._voice_stage_label: QLabel | None = None
        self._voice_stt_label: QLabel | None = None
        self._voice_tts_label: QLabel | None = None
        self._voice_progress: QProgressBar | None = None
        self._voice_transcription_preview: QLabel | None = None
        self._voice_vu_meter: VoiceVUMeter | None = None
        self._reload_profile_button: QPushButton | None = None
        self._profile_value_label: QLabel | None = None
        self._copy_button: QPushButton | None = None
        self._open_logs_button: QPushButton | None = None
        self._open_state_button: QPushButton | None = None
        self._safe_actions_note: QLabel | None = None
        self._model_recommendation_label: QLabel | None = None
        self._route_model_status_label: QLabel | None = None
        self._trust_source_summary_label: QLabel | None = None
        self._eng_selected_route_label: QLabel | None = None
        self._eng_selected_model_label: QLabel | None = None
        self._eng_confidence_margin_label: QLabel | None = None
        self._eng_provider_chain_label: QLabel | None = None
        self._eng_source_freshness_label: QLabel | None = None
        self._eng_latency_breakdown_label: QLabel | None = None
        self._eng_manual_override_label: QLabel | None = None
        self._eng_context_items_label: QLabel | None = None
        self._current_values = {
            "mode": "",
            "conversation": "",
            "memory": "",
            "evidence": "",
            "voice": "",
            "augmentation_policy": "",
            "augmented_provider": "",
            "model": "",
            "gemma4_smart_routing": "",
            "self_analysis_mode": "",
            "profile": "",
            "learner": "",
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
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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

        layout.addWidget(self._build_operator_group())
        layout.addWidget(self._build_engineering_group())
        layout.addWidget(self._build_voice_group())
        layout.addWidget(self._build_voice_status_group())
        layout.addWidget(self._build_profile_group())
        layout.addWidget(self._build_safe_actions_group())
        layout.addStretch(1)

    def _build_operator_group(self) -> QGroupBox:
        group = QGroupBox("Controls")
        self._operator_group = group

        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._memory_selector = QComboBox()
        self._memory_selector.addItems(["on", "off"])
        self._memory_selector.activated.connect(self._handle_memory_activated)

        self._voice_selector = QComboBox()
        self._voice_selector.addItems(["on", "off"])
        self._voice_selector.activated.connect(self._handle_voice_activated)

        self._route_model_status_label = QLabel("Route: — | Model: —")
        self._route_model_status_label.setObjectName("cardValue")
        self._route_model_status_label.setWordWrap(True)
        self._route_model_status_label.setToolTip(
            "Current routing decision and active model status."
        )

        self._trust_source_summary_label = QLabel("Trust: — | Source: —")
        self._trust_source_summary_label.setObjectName("cardLabel")
        self._trust_source_summary_label.setWordWrap(True)
        self._trust_source_summary_label.setToolTip(
            "Trust classification and source basis for the latest answer."
        )

        layout.addWidget(self._build_labeled_row("memory", self._memory_selector))
        layout.addWidget(self._build_labeled_row("voice", self._voice_selector))
        layout.addWidget(self._route_model_status_label)
        layout.addWidget(self._trust_source_summary_label)

        note = QLabel("Controls unavailable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._operator_note = note
        group.setDisabled(True)
        return group

    def _build_engineering_group(self) -> QGroupBox:
        group = QGroupBox("Engineering")
        self._engineering_group = group

        layout = QVBoxLayout(group)
        layout.setSpacing(8)

        self._mode_selector = QComboBox()
        self._mode_selector.addItems(["auto", "online", "offline"])
        self._mode_selector.activated.connect(self._handle_mode_activated)

        self._conversation_selector = QComboBox()
        self._conversation_selector.addItems(["on", "off"])
        self._conversation_selector.activated.connect(self._handle_conversation_activated)

        self._evidence_selector = QComboBox()
        self._evidence_selector.addItems(["on", "off"])
        self._evidence_selector.activated.connect(self._handle_evidence_activated)

        self._augmentation_policy_selector = QComboBox()
        self._augmentation_policy_selector.addItems(
            ["auto", "disabled", "fallback_only", "direct_allowed"]
        )
        self._augmentation_policy_selector.activated.connect(
            self._handle_augmentation_policy_activated
        )

        self._augmented_provider_selector = QComboBox()
        self._augmented_provider_selector.addItems(["auto", "wikipedia", "openai", "kimi"])
        self._augmented_provider_selector.activated.connect(
            self._handle_augmented_provider_activated
        )

        self._learner_selector = QComboBox()
        self._learner_selector.addItems(["on", "off"])
        self._learner_selector.activated.connect(self._handle_learner_activated)

        self._model_selector = QComboBox()
        self._model_selector.addItems(list(self._MODEL_LABELS.values()))
        self._model_selector.activated.connect(self._handle_model_activated)

        self._gemma4_smart_routing_selector = QCheckBox("Gemma 4 Smart Routing")
        self._gemma4_smart_routing_selector.setToolTip(
            "When on and Gemma 4 is selected, bypass the classifier/router and let Gemma 4 route internally."
        )
        self._gemma4_smart_routing_selector.setEnabled(False)
        self._gemma4_smart_routing_selector.stateChanged.connect(
            self._handle_gemma4_smart_routing_changed
        )

        self._gemma4_vram_warning_label = QLabel("")
        self._gemma4_vram_warning_label.setWordWrap(True)
        self._gemma4_vram_warning_label.setObjectName("cardValue")
        self._gemma4_vram_warning_label.setVisible(False)

        self._self_analysis_selector = QCheckBox("Self-Analysis Mode")
        self._self_analysis_selector.setToolTip(
            "When on, Lucy can parse her own code and suggest improvements."
        )
        self._self_analysis_selector.setEnabled(False)
        self._self_analysis_selector.stateChanged.connect(self._handle_self_analysis_changed)

        self._model_recommendation_label = QLabel("Model recommendation: —")
        self._model_recommendation_label.setObjectName("cardLabel")
        self._model_recommendation_label.setWordWrap(True)
        self._model_recommendation_label.setToolTip(
            "Engineering read-out of the last automatic model recommendation (Auto mode only)."
        )

        self._eng_selected_route_label = QLabel("Selected route: —")
        self._eng_selected_route_label.setObjectName("cardLabel")
        self._eng_selected_route_label.setWordWrap(True)

        self._eng_selected_model_label = QLabel("Selected model: —")
        self._eng_selected_model_label.setObjectName("cardLabel")
        self._eng_selected_model_label.setWordWrap(True)

        self._eng_confidence_margin_label = QLabel("Confidence: — | Margin: —")
        self._eng_confidence_margin_label.setObjectName("cardLabel")
        self._eng_confidence_margin_label.setWordWrap(True)

        self._eng_provider_chain_label = QLabel("Provider chain: —")
        self._eng_provider_chain_label.setObjectName("cardLabel")
        self._eng_provider_chain_label.setWordWrap(True)

        self._eng_source_freshness_label = QLabel("Source freshness: —")
        self._eng_source_freshness_label.setObjectName("cardLabel")
        self._eng_source_freshness_label.setWordWrap(True)

        self._eng_latency_breakdown_label = QLabel("Latency: —")
        self._eng_latency_breakdown_label.setObjectName("cardLabel")
        self._eng_latency_breakdown_label.setWordWrap(True)

        self._eng_manual_override_label = QLabel("Manual model override: —")
        self._eng_manual_override_label.setObjectName("cardLabel")
        self._eng_manual_override_label.setWordWrap(True)

        self._eng_context_items_label = QLabel("Context items: accepted=—, rejected=—")
        self._eng_context_items_label.setObjectName("cardLabel")
        self._eng_context_items_label.setWordWrap(True)

        layout.addWidget(self._build_labeled_row("mode", self._mode_selector))
        layout.addWidget(self._build_labeled_row("conversation", self._conversation_selector))
        layout.addWidget(self._build_labeled_row("evidence", self._evidence_selector))
        layout.addWidget(
            self._build_labeled_row("augmented policy", self._augmentation_policy_selector)
        )
        layout.addWidget(
            self._build_labeled_row("augmented provider", self._augmented_provider_selector)
        )
        layout.addWidget(self._build_labeled_row("auto-learn", self._learner_selector))
        layout.addWidget(self._build_labeled_row("model", self._model_selector))
        layout.addWidget(self._gemma4_smart_routing_selector)
        layout.addWidget(self._gemma4_vram_warning_label)
        layout.addWidget(self._self_analysis_selector)
        layout.addWidget(self._model_recommendation_label)
        layout.addWidget(self._eng_selected_route_label)
        layout.addWidget(self._eng_selected_model_label)
        layout.addWidget(self._eng_confidence_margin_label)
        layout.addWidget(self._eng_provider_chain_label)
        layout.addWidget(self._eng_source_freshness_label)
        layout.addWidget(self._eng_latency_breakdown_label)
        layout.addWidget(self._eng_manual_override_label)
        layout.addWidget(self._eng_context_items_label)

        note = QLabel("Engineering controls unavailable.")
        note.setWordWrap(True)
        layout.addWidget(note)
        self._engineering_note = note
        group.setDisabled(True)
        return group

    def _build_labeled_row(self, label_text: str, selector: QComboBox) -> QFrame:
        row = QFrame()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("cardLabel")
        label.setWordWrap(True)

        selector.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        selector.setMinimumContentsLength(12)
        selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout.addWidget(label)
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

        # STT Engine indicator
        stt_row = QHBoxLayout()
        self._voice_stt_label = QLabel("🎤 STT: detecting...")
        self._voice_stt_label.setObjectName("voiceSttLabel")
        self._voice_stt_label.setStyleSheet("color: #7f8d97; font-size: 11px;")
        stt_row.addWidget(self._voice_stt_label)
        stt_row.addStretch(1)
        layout.addLayout(stt_row)

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

        # VU meters for input/output audio levels
        self._voice_vu_meter = VoiceVUMeter()
        # Point VU meters at the voice audio levels file for fast polling.
        runtime_ns = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "")
        if runtime_ns:
            levels_path = (
                Path(runtime_ns).expanduser().resolve() / "state" / "voice_audio_levels.json"
            )
        else:
            levels_path = Path(__file__).resolve().parents[3] / "state" / "voice_audio_levels.json"
        self._voice_vu_meter.set_levels_file(levels_path)
        layout.addWidget(self._voice_vu_meter)

        # Transcription preview
        self._voice_transcription_preview = QLabel("")
        self._voice_transcription_preview.setObjectName("cardValue")
        self._voice_transcription_preview.setWordWrap(True)
        self._voice_transcription_preview.setStyleSheet("color: #94a5b1; font-style: italic;")
        layout.addWidget(self._voice_transcription_preview)

        group.setVisible(False)
        return group

    def update_voice_pipeline_status(
        self, stage: str, progress: float, transcription: str = ""
    ) -> None:
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

        memory_button = QPushButton("Manage Memory Facts")
        memory_button.clicked.connect(self._open_memory_manager)
        self._memory_button = memory_button

        shutdown_button = QPushButton("Shutdown Local Lucy")
        shutdown_button.setObjectName("shutdownButton")
        shutdown_button.clicked.connect(self.shutdown_requested.emit)
        self._shutdown_button = shutdown_button

        layout.addWidget(refresh_button)
        layout.addWidget(copy_button)
        layout.addWidget(open_logs_button)
        layout.addWidget(open_state_button)
        layout.addWidget(memory_button)
        layout.addWidget(shutdown_button)

        note = QLabel(
            "UI-local actions. Shutdown kills the process so code changes take effect on restart."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self._safe_actions_note = note
        return group

    def _open_memory_manager(self) -> None:
        from app.widgets.memory_manager_dialog import MemoryManagerDialog

        dialog = MemoryManagerDialog(self)
        dialog.exec()

    def apply_backend_capabilities(
        self, capability_notes: dict[str, str], backend_available: bool
    ) -> None:
        if self._engineering_note is not None:
            self._engineering_note.setText(
                capability_notes.get("mode_selection", self._engineering_note.text())
            )
        if self._operator_note is not None:
            self._operator_note.setText(
                capability_notes.get("feature_toggles", self._operator_note.text())
            )
        if self._profile_note is not None:
            self._profile_note.setText(
                capability_notes.get("profile_reload", self._profile_note.text())
            )
        self.set_backend_enabled(backend_available)

    def set_backend_busy(self, busy: bool) -> None:
        self._backend_busy = busy
        if self._operator_group is not None:
            self._operator_group.setEnabled(self._backend_available and not busy)
        if self._engineering_group is not None:
            self._engineering_group.setEnabled(self._backend_available and not busy)
        self._apply_profile_button_state(busy)
        self._refresh_voice_ptt()

    def set_backend_enabled(self, enabled: bool) -> None:
        self._backend_available = enabled
        if self._operator_group is not None:
            self._operator_group.setEnabled(enabled)
        if self._engineering_group is not None:
            self._engineering_group.setEnabled(enabled)
        self._refresh_voice_ptt()

    def set_profile_reload_available(self, available: bool) -> None:
        self._profile_available = available
        if self._profile_group is not None:
            self._profile_group.setEnabled(available)
        self._apply_profile_button_state(self._backend_busy)

    def set_interface_level(self, level: str) -> None:
        show_profile_group = level_at_least(level, ENGINEERING)
        show_power_widgets = level_at_least(level, POWER)
        # Trim the HMI for autonomous operation: advanced selectors are hidden at
        # operator level. They remain available to engineering/power users who need
        # to override Lucy's automatic choices.
        show_engineering = level_at_least(level, ENGINEERING)
        if self._operator_group is not None:
            self._operator_group.setVisible(True)
        if self._engineering_group is not None:
            self._engineering_group.setVisible(show_engineering)
        if self._profile_group is not None:
            self._profile_group.setVisible(show_profile_group)
        if self._engineering_note is not None:
            self._engineering_note.setVisible(show_engineering)
        if self._operator_note is not None:
            self._operator_note.setVisible(True)
        # Voice PTT visibility is controlled by voice state, not interface level
        self._refresh_voice_ptt()
        for widget in (
            self._profile_note,
            self._copy_button,
            self._open_logs_button,
            self._open_state_button,
            self._safe_actions_note,
        ):
            if widget is not None:
                widget.setVisible(show_power_widgets)

    def update_control_state(
        self,
        top_status: dict[str, str],
        current_state: dict[str, Any] | None = None,
        pending_values: dict[str, str] | None = None,
    ) -> None:
        # Use the authoritative current_state model value so the selector reflects
        # the configured model even when the top-status label is formatted with
        # active/load status.
        configured_model = ""
        if isinstance(current_state, dict):
            configured_model = str(current_state.get("model", "")).strip()
        if not configured_model:
            configured_model = top_status.get("Model", "").strip()
        if not configured_model:
            configured_model = "auto"

        values = {
            "profile": top_status.get("Profile", "").strip(),
            "mode": top_status.get("Mode", "").strip().lower(),
            "conversation": top_status.get("Conversation", "").strip().lower(),
            "memory": top_status.get("Memory", "").strip().lower(),
            "evidence": top_status.get("Evidence", "").strip().lower(),
            "voice": top_status.get("Voice", "").strip().lower(),
            "augmentation_policy": top_status.get("Augmented Policy", "").strip().lower(),
            "augmented_provider": top_status.get("Augmented Provider", "").strip().lower(),
            "model": configured_model,
            "learner": top_status.get("Learner", "").strip().lower(),
        }
        if isinstance(current_state, dict):
            values["gemma4_smart_routing"] = (
                str(current_state.get("gemma4_smart_routing", "off")).strip().lower()
            )
            values["self_analysis_mode"] = (
                str(current_state.get("self_analysis_mode", "off")).strip().lower()
            )
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
        self._set_selector_value(self._learner_selector, values.get("learner", ""))
        self._set_selector_value(self._model_selector, values.get("model", ""))
        if self._gemma4_smart_routing_selector is not None:
            self._gemma4_smart_routing_selector.setChecked(
                values.get("gemma4_smart_routing", "off") == "on"
            )
        if self._self_analysis_selector is not None:
            self._self_analysis_selector.setChecked(values.get("self_analysis_mode", "off") == "on")
            self._self_analysis_selector.setEnabled(self._backend_available)
        self._update_gemma4_smart_routing_visibility(values.get("model", ""))
        self._refresh_voice_ptt()

    def update_trace_summary(
        self, snapshot: Any, request_details: dict[str, Any] | None = None
    ) -> None:
        """Update the operator route/model indicator and engineering observability labels."""
        top_status: dict[str, str] = getattr(snapshot, "top_status", {}) or {}
        runtime_status: dict[str, str] = getattr(snapshot, "runtime_status", {}) or {}
        active_model_info: dict[str, Any] = getattr(snapshot, "active_model", {}) or {}

        configured_model = top_status.get("Model", runtime_status.get("Model", "unknown"))
        active_status = str(active_model_info.get("status", "unknown")).lower()
        if active_status == "running":
            model_status_text = configured_model
        else:
            model_status_text = f"{configured_model} — {active_status}"

        current_route = runtime_status.get("Current Route", top_status.get("Router", "unknown"))
        if self._route_model_status_label is not None:
            self._route_model_status_label.setText(
                f"Route: {current_route} | Model: {model_status_text}"
            )

        trust = "unknown"
        source = "unknown"
        if isinstance(request_details, dict):
            outcome = request_details.get("outcome")
            if isinstance(outcome, dict):
                trust = (
                    str(outcome.get("operator_trust_label") or "").strip()
                    or str(outcome.get("trust_class") or "").strip()
                    or "unknown"
                )
                contract = outcome.get("augmented_answer_contract")
                if isinstance(contract, dict):
                    basis = contract.get("source_basis")
                    if isinstance(basis, list):
                        parts = [str(x).strip() for x in basis if str(x).strip()]
                        source = ", ".join(parts) if parts else "unknown"
                    else:
                        source = str(basis or "").strip() or "unknown"
                else:
                    source = str(outcome.get("source_basis") or "").strip() or "unknown"
        if self._trust_source_summary_label is not None:
            self._trust_source_summary_label.setText(f"Trust: {trust} | Source: {source}")

        # Engineering observability read-outs
        if self._eng_selected_route_label is not None:
            self._eng_selected_route_label.setText(f"Selected route: {current_route}")

        selected_model = configured_model
        if self._eng_selected_model_label is not None:
            self._eng_selected_model_label.setText(f"Selected model: {selected_model}")

        confidence = "—"
        margin = "—"
        provider_chain = "local"
        latency = "—"
        accepted = "—"
        rejected = "—"
        if isinstance(request_details, dict):
            route = request_details.get("route")
            if isinstance(route, dict):
                confidence = str(route.get("confidence", "—"))
                try:
                    conf_float = float(route.get("confidence", 0))
                    margin = f"{max(0.0, 1.0 - conf_float):.2f}"
                except (TypeError, ValueError):
                    margin = "—"
            outcome = request_details.get("outcome")
            if isinstance(outcome, dict):
                provider = (
                    str(outcome.get("augmented_provider_used") or "").strip()
                    or str(outcome.get("augmented_provider") or "").strip()
                    or str(
                        (request_details.get("control_state") or {}).get("augmented_provider") or ""
                    ).strip()
                    or "none"
                )
                call_reason = str(
                    outcome.get("augmented_provider_call_reason") or "not_needed"
                ).strip()
                provider_chain = f"{provider} ({call_reason})"
                latency = f"{outcome.get('execution_time_ms', '—')} ms"
                evidence_created = str(outcome.get("evidence_created") or "").lower() in {
                    "1",
                    "true",
                    "yes",
                }
                accepted = "yes" if evidence_created else "no"
        if self._eng_confidence_margin_label is not None:
            self._eng_confidence_margin_label.setText(
                f"Confidence: {confidence} | Margin: {margin}"
            )
        if self._eng_provider_chain_label is not None:
            self._eng_provider_chain_label.setText(f"Provider chain: {provider_chain}")
        if self._eng_latency_breakdown_label is not None:
            self._eng_latency_breakdown_label.setText(f"Latency: {latency}")
        if self._eng_context_items_label is not None:
            self._eng_context_items_label.setText(
                f"Context items: accepted={accepted}, rejected={rejected}"
            )

        snapshot_timestamp = getattr(snapshot, "snapshot_timestamp", None)
        freshness = "unknown"
        if snapshot_timestamp:
            try:
                from datetime import datetime, timezone

                ts = datetime.fromisoformat(str(snapshot_timestamp))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - ts).total_seconds()
                freshness = f"{int(age)}s ago"
            except Exception:
                freshness = str(snapshot_timestamp)
        if self._eng_source_freshness_label is not None:
            self._eng_source_freshness_label.setText(f"Source freshness: {freshness}")

        manual_model = self._current_values.get("model", "auto")
        if self._eng_manual_override_label is not None:
            if manual_model and manual_model != "auto":
                self._eng_manual_override_label.setText(f"Manual model override: {manual_model}")
            else:
                self._eng_manual_override_label.setText("Manual model override: none (Auto)")

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
            if self._voice_vu_meter is not None:
                self._voice_vu_meter.reset()
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

        # Update VU meters from audio levels
        if self._voice_vu_meter is not None:
            input_level = int(self._voice_runtime.get("input_level", 0))
            output_level = int(self._voice_runtime.get("output_level", 0))
            self._voice_vu_meter.set_input_level(input_level)
            self._voice_vu_meter.set_output_level(output_level)

        # Update STT engine indicator
        if self._voice_stt_label is not None:
            stt_engine = str(self._voice_runtime.get("stt", "unknown")).lower()
            stt_device = str(self._voice_runtime.get("stt_device", "unknown")).lower()
            if stt_engine == "whisper":
                device_label = stt_device if stt_device not in {"none", "unknown", ""} else "CPU"
                self._voice_stt_label.setText(f"🎤 STT: Whisper ({device_label.upper()})")
                self._voice_stt_label.setStyleSheet(
                    "color: #2ecc71; font-size: 11px; font-weight: bold;"
                )
            elif stt_engine == "vosk":
                self._voice_stt_label.setText("🎤 STT: Vosk (CPU)")
                self._voice_stt_label.setStyleSheet("color: #f1c40f; font-size: 11px;")
            elif stt_engine in {"none", "unavailable", ""}:
                self._voice_stt_label.setText("🎤 STT: unavailable")
                self._voice_stt_label.setStyleSheet("color: #e74c3c; font-size: 11px;")
            else:
                self._voice_stt_label.setText(f"🎤 STT: {stt_engine}")
                self._voice_stt_label.setStyleSheet("color: #7f8d97; font-size: 11px;")

        # Update TTS engine indicator
        if self._voice_tts_label is not None:
            tts_engine = str(self._voice_runtime.get("tts", "none")).lower()
            tts_device = str(self._voice_runtime.get("tts_device", "none")).lower()
            if tts_engine == "kokoro":
                device_label = tts_device if tts_device != "none" else "GPU"
                self._voice_tts_label.setText(f"🔊 TTS: Kokoro ({device_label.upper()})")
                self._voice_tts_label.setStyleSheet(
                    "color: #2ecc71; font-size: 11px; font-weight: bold;"
                )
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
        if selector is self._model_selector:
            label = self._MODEL_LABELS.get(value, value)
            index = selector.findText(label)
        else:
            index = selector.findText(value)
        if index >= 0:
            selector.setCurrentIndex(index)
        else:
            selector.setCurrentIndex(-1)
        selector.blockSignals(False)

    def _handle_mode_activated(self, index: int) -> None:
        self._emit_if_changed(
            "mode", self._mode_selector.itemText(index), self.mode_change_requested
        )

    def _handle_conversation_activated(self, index: int) -> None:
        self._emit_if_changed(
            "conversation",
            self._conversation_selector.itemText(index),
            self.conversation_change_requested,
        )

    def _handle_memory_activated(self, index: int) -> None:
        self._emit_if_changed(
            "memory", self._memory_selector.itemText(index), self.memory_change_requested
        )

    def _handle_evidence_activated(self, index: int) -> None:
        self._emit_if_changed(
            "evidence", self._evidence_selector.itemText(index), self.evidence_change_requested
        )

    def _handle_voice_activated(self, index: int) -> None:
        self._emit_if_changed(
            "voice", self._voice_selector.itemText(index), self.voice_change_requested
        )

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

    def _handle_learner_activated(self, index: int) -> None:
        self._emit_if_changed(
            "learner", self._learner_selector.itemText(index), self.learner_change_requested
        )

    def _handle_model_activated(self, index: int) -> None:
        label = self._model_selector.itemText(index)
        # Reverse lookup: find backend value from display label
        model_value = next(
            (k for k, v in self._MODEL_LABELS.items() if v == label),
            label,
        )
        self._emit_if_changed(
            "model",
            model_value,
            self.model_change_requested,
        )
        self._update_gemma4_smart_routing_visibility(model_value)

    def _handle_gemma4_smart_routing_changed(self, state: int) -> None:
        value = "on" if state == 2 else "off"
        self._emit_if_changed(
            "gemma4_smart_routing",
            value,
            self.gemma4_smart_routing_change_requested,
        )

    def _handle_self_analysis_changed(self, state: int) -> None:
        value = "on" if state == 2 else "off"
        self._emit_if_changed(
            "self_analysis_mode",
            value,
            self.self_analysis_change_requested,
        )

    def _update_gemma4_smart_routing_visibility(self, model: str) -> None:
        is_gemma = bool(model) and model.lower().startswith("gemma4")
        self._gemma4_smart_routing_selector.setEnabled(is_gemma)
        if not is_gemma:
            self._gemma4_vram_warning_label.setText("")
            self._gemma4_vram_warning_label.setVisible(False)
            return
        from router_py.local_answer import get_gpu_free_vram_mb

        free_vram_mb = get_gpu_free_vram_mb()
        if free_vram_mb is not None and free_vram_mb < 12 * 1024:
            self._gemma4_vram_warning_label.setText(
                "Warning: Gemma 4 12B may be tight on this GPU. "
                "Short conversations are fine; long context or concurrent models may hit VRAM limits. "
                "Ollama can fall back to system RAM, but responses will be slower."
            )
            self._gemma4_vram_warning_label.setVisible(True)
        else:
            self._gemma4_vram_warning_label.setText("")
            self._gemma4_vram_warning_label.setVisible(False)

    def set_model_recommendation(self, text: str) -> None:
        """Update the engineering-only model recommendation read-out."""
        if self._model_recommendation_label is not None:
            self._model_recommendation_label.setText(f"Model recommendation: {text}")

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
                    "Learner": self._current_values.get("learner", ""),
                    "Model": self._current_values.get("model", ""),
                },
                current_state=self._current_values,
            )
            return
        signal.emit(requested_value)

    def _apply_profile_button_state(self, busy: bool) -> None:
        if self._profile_group is not None:
            self._profile_group.setEnabled(self._profile_available)
        if self._reload_profile_button is not None:
            self._reload_profile_button.setEnabled(self._profile_available and not busy)

    def _refresh_voice_ptt(self) -> None:
        if (
            self._voice_ptt_group is None
            or self._voice_ptt_button is None
            or self._voice_ptt_status_label is None
        ):
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

        # If the user is currently pressing the PTT button, do not mutate its
        # text or enabled state.  Changing those while the button is down can
        # cancel the active press and prevent the released() signal from firing,
        # which breaks release-to-send.
        if not self._voice_ptt_button.isDown():
            self._voice_ptt_button.setText(button_text)
            self._voice_ptt_button.setEnabled(button_enabled)
            self._voice_ptt_button.setProperty("voiceState", button_state)
            self._voice_ptt_button.style().unpolish(self._voice_ptt_button)
            self._voice_ptt_button.style().polish(self._voice_ptt_button)
        self._voice_ptt_status_label.setText(status_text)
