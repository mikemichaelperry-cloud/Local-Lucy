from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGroupBox, QLabel, QLayout, QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from app.ui_levels import SIMPLE, POWER, ENGINEERING, level_at_least, is_engineering

DEFAULT_HISTORY_RETENTION_MAX_ENTRIES = 200


class StatusPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shellCard")
        self.setMinimumWidth(320)
        self._scroll_area: QScrollArea | None = None
        self._content_widget: QWidget | None = None
        self._current_level = SIMPLE
        self._latest_runtime_snapshot: dict[str, dict[str, str]] = {
            "top_status": {},
            "runtime_status": {},
            "file_paths": {},
        }
        self._latest_request_payload: dict[str, object] | None = None

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
        layout.setSpacing(10)
        layout.setSizeConstraint(QLayout.SetMinAndMaxSize)
        scroll_area.setWidget(content_widget)
        scroll_area.viewport().setObjectName("panelScrollViewport")
        scroll_area.viewport().setAutoFillBackground(False)

        title = QLabel("Runtime / Status")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        counter_note = QLabel(
            "Session augmented counters are GUI-session scoped, reset when this GUI restarts, "
            "derived conservatively from backend outcome metadata, and separate from terminal launcher counters."
        )
        counter_note.setObjectName("cardLabel")
        counter_note.setWordWrap(True)
        layout.addWidget(counter_note)

        # Freshness indicator - shows when status was last updated and warns if stale
        self._freshness_label = QLabel("Status: waiting for first update...")
        self._freshness_label.setObjectName("cardLabel")
        self._freshness_label.setWordWrap(True)
        layout.addWidget(self._freshness_label)

        # Legacy namespace warning (hidden by default, shown if detected)
        self._legacy_warning_label = QLabel("")
        self._legacy_warning_label.setObjectName("cardLabel")
        self._legacy_warning_label.setWordWrap(True)
        self._legacy_warning_label.hide()
        layout.addWidget(self._legacy_warning_label)

        self._snapshot_timestamp: datetime | None = None
        self._runtime_summary_labels: dict[str, QLabel] = {}
        self._runtime_summary_cards: dict[str, QFrame] = {}
        self._runtime_detail_labels: dict[str, QLabel] = {}
        self._runtime_detail_cards: dict[str, QFrame] = {}
        self._request_summary_labels: dict[str, QLabel] = {}
        self._request_summary_cards: dict[str, QFrame] = {}
        self._request_detail_labels: dict[str, QLabel] = {}
        self._request_detail_cards: dict[str, QFrame] = {}
        self._build_info_labels: dict[str, QLabel] = {}
        self._build_info_cards: dict[str, QFrame] = {}

        self._runtime_summary_group = self._build_group(
            "Runtime Summary",
            [
                ("Current Route", "unknown"),
                ("Source Type", "unknown"),
                ("Conversation", "unknown"),
                ("Voice State", "unknown"),
                ("Health", "unknown"),
                ("Augmented Policy", "unknown"),
                ("Configured Provider", "unknown"),
                ("Configured Provider Paid", "unknown"),
                ("Last Request Provider", "unknown"),
                ("Last Request Paid", "unknown"),
                ("Session Augmented Calls", "0"),
                ("Session Paid Augmented Calls", "0"),
                ("Session Provider Counts", "openai=0 kimi=0 wikipedia=0"),
            ],
            self._runtime_summary_labels,
            self._runtime_summary_cards,
        )
        layout.addWidget(self._runtime_summary_group)

        self._runtime_detail_group = self._build_group(
            "Runtime Details",
            [
                ("Voice Backend", "unknown"),
                ("Voice Error", "none"),
                ("GPU Acceleration", "checking..."),
                ("Preprocess Active", "unknown"),
                ("Reduced Scope", "unknown"),
                ("Patch Surface Summary", "unknown"),
                ("Uncertainty / Underspecified", "unknown"),
            ],
            self._runtime_detail_labels,
            self._runtime_detail_cards,
        )
        layout.addWidget(self._runtime_detail_group)
        self._build_info_group = self._build_group(
            "Build Information",
            [
                ("Version", "v8"),
                ("Snapshot", "opt-experimental-v8-dev"),
                ("Build Date", "2026-04-22"),
                ("Authority", "loading..."),
                ("State Path", "loading..."),
            ],
            self._build_info_labels,
            self._build_info_cards,
        )
        layout.addWidget(self._build_info_group)


        self._request_summary_group = self._build_group(
            "Request Diagnostics",
            [
                ("Status", "No request yet"),
                ("Completed At", "Not available"),
                ("Answer Path", "unknown"),
                ("Trust", "unknown"),
                ("Augmented", "not used"),
                ("Route Mode", "unknown"),
                ("Outcome Code", "unknown"),
            ],
            self._request_summary_labels,
            self._request_summary_cards,
        )
        layout.addWidget(self._request_summary_group)

        self._request_detail_group = self._build_group(
            "Request Drill-Down",
            [
                ("Request ID", "No persisted request entry"),
                ("Request Text", "unknown"),
                ("Error", "none"),
                ("Route Reason", "unknown"),
                ("Operator Note", "none"),
                ("Action Hint", "none"),
                ("Verification Status", "unknown"),
                ("Estimated Confidence", "unknown"),
                ("Source Basis", "unknown"),
                ("Augmented Direct Request", "unknown"),
                ("Augmented Provider Status", "unknown"),
                ("Evidence Created", "unknown"),
                ("Primary Outcome", "unknown"),
                ("Recovery Lane", "unknown"),
                ("Control State", "unavailable"),
            ],
            self._request_detail_labels,
            self._request_detail_cards,
        )
        layout.addWidget(self._request_detail_group)

        self._advanced_metadata_group = QGroupBox("Expanded Runtime Metadata")
        advanced_metadata_layout = QVBoxLayout(self._advanced_metadata_group)
        advanced_metadata_layout.setSpacing(8)
        advanced_state_label = QLabel("Expanded State / Runtime Metadata")
        advanced_state_label.setObjectName("cardLabel")
        advanced_metadata_layout.addWidget(advanced_state_label)
        self._advanced_state_view = QPlainTextEdit()
        self._advanced_state_view.setReadOnly(True)
        self._advanced_state_view.setFixedHeight(140)
        advanced_metadata_layout.addWidget(self._advanced_state_view)
        advanced_request_label = QLabel("Selected Request Metadata")
        advanced_request_label.setObjectName("cardLabel")
        advanced_metadata_layout.addWidget(advanced_request_label)
        self._advanced_request_view = QPlainTextEdit()
        self._advanced_request_view.setReadOnly(True)
        self._advanced_request_view.setFixedHeight(170)
        advanced_metadata_layout.addWidget(self._advanced_request_view)
        layout.addWidget(self._advanced_metadata_group)

        self._history_maintenance_group = QGroupBox("History / Retention Summary")
        history_maintenance_layout = QVBoxLayout(self._history_maintenance_group)
        history_maintenance_layout.setSpacing(8)
        history_maintenance_label = QLabel("Maintenance / Retention Summary")
        history_maintenance_label.setObjectName("cardLabel")
        history_maintenance_layout.addWidget(history_maintenance_label)
        self._history_maintenance_view = QPlainTextEdit()
        self._history_maintenance_view.setReadOnly(True)
        self._history_maintenance_view.setFixedHeight(130)
        history_maintenance_layout.addWidget(self._history_maintenance_view)
        layout.addWidget(self._history_maintenance_group)

        layout.addStretch(1)
        self.set_interface_level("operator")

    def update_status(self, values: dict[str, str]) -> None:
        for label_text, label_widget in self._runtime_summary_labels.items():
            label_widget.setText(self._format_runtime_value(label_text, values.get(label_text, "unknown")))
        for label_text, label_widget in self._runtime_detail_labels.items():
            # Skip GPU Acceleration - it's updated separately by _update_gpu_status
            if label_text == "GPU Acceleration":
                continue
            label_widget.setText(values.get(label_text, "unknown"))
        self._latest_runtime_snapshot["runtime_status"] = dict(values)

    def update_request_details(self, payload: dict[str, object] | None) -> None:
        summary_values = {
            "Status": self._payload_text(payload, "status") or "No request yet",
            "Completed At": self._payload_text(payload, "completed_at") or "Not available",
            "Answer Path": self._answer_path_text(payload),
            "Trust": self._operator_trust_text(payload),
            "Augmented": self._augmented_summary_text(payload),
            "Route Mode": self._nested_text(payload, "route", "mode") or "unknown",
            "Outcome Code": self._nested_text(payload, "outcome", "outcome_code") or "unknown",
        }
        detail_values = {
            "Request ID": self._payload_text(payload, "request_id") or "No persisted request entry",
            "Request Text": self._payload_text(payload, "request_text") or "unknown",
            "Error": self._payload_text(payload, "error") or "none",
            "Route Reason": self._nested_text(payload, "route", "reason") or "unknown",
            "Operator Note": self._operator_note_text(payload),
            "Action Hint": self._nested_text(payload, "outcome", "action_hint") or "none",
            "Verification Status": self._answer_contract_verification_text(payload),
            "Estimated Confidence": self._answer_contract_confidence_text(payload),
            "Source Basis": self._answer_contract_source_basis_text(payload),
            "Augmented Direct Request": self._nested_text(payload, "outcome", "augmented_direct_request") or "unknown",
            "Augmented Provider Status": self._nested_text(payload, "outcome", "augmented_provider_status") or "unknown",
            "Evidence Created": self._nested_text(payload, "outcome", "evidence_created") or "unknown",
            "Primary Outcome": self._nested_text(payload, "outcome", "primary_outcome_code") or "none",
            "Recovery Lane": self._nested_text(payload, "outcome", "recovery_lane") or "none",
            "Control State": self._control_state_text(payload),
        }
        for label_text, label_widget in self._request_summary_labels.items():
            label_widget.setText(summary_values.get(label_text, "unknown"))
        for label_text, label_widget in self._request_detail_labels.items():
            label_widget.setText(detail_values.get(label_text, "unknown"))
        self._latest_request_payload = payload

    def update_runtime_snapshot(self, snapshot) -> None:
        self._latest_runtime_snapshot = {
            "top_status": dict(snapshot.top_status),
            "runtime_status": dict(snapshot.runtime_status),
            "file_paths": dict(snapshot.file_paths),
        }
        
        # Update Build Information from snapshot
        self._build_info_labels.get("Version", QLabel()).setText("v8")
        self._build_info_labels.get("Snapshot", QLabel()).setText("opt-experimental-v8-dev")
        self._build_info_labels.get("Build Date", QLabel()).setText("2026-04-22")
        
        # Get paths from file_paths
        file_paths = dict(snapshot.file_paths)
        authority = file_paths.get("runtime_namespace_root", "unknown")
        if len(authority) > 40:
            authority = "..." + authority[-37:]
        self._build_info_labels.get("Authority", QLabel()).setText(authority)
        
        state_path = file_paths.get("current_state", "unknown")
        if len(state_path) > 40:
            state_path = "..." + state_path[-37:]
        self._build_info_labels.get("State Path", QLabel()).setText(state_path)
        # Parse and store timestamp, then update freshness indicator
        try:
            self._snapshot_timestamp = datetime.fromisoformat(snapshot.snapshot_timestamp)
        except (ValueError, AttributeError):
            self._snapshot_timestamp = None
        self._update_freshness_indicator()
        # Update legacy namespace warning
        self._update_legacy_warning(snapshot)
        # Update GPU status display
        self._update_gpu_status(snapshot)

    def _update_freshness_indicator(self) -> None:
        """Update the freshness label showing when data was last updated and if it's stale."""
        if self._snapshot_timestamp is None:
            self._freshness_label.setText("Status: waiting for first update...")
            self._freshness_label.setStyleSheet("")
            return

        now = datetime.now(timezone.utc)
        age_seconds = (now - self._snapshot_timestamp).total_seconds()

        # Format timestamp for display (local time, abbreviated)
        local_time = self._snapshot_timestamp.astimezone()
        time_str = local_time.strftime("%H:%M:%S")

        if age_seconds < 2:
            status_text = f"Updated: {time_str} (fresh)"
            style = "color: #2ecc71;"  # Green
        elif age_seconds < 5:
            status_text = f"Updated: {time_str} ({int(age_seconds)}s ago)"
            style = "color: #f1c40f;"  # Yellow
        else:
            status_text = f"Updated: {time_str} ({int(age_seconds)}s ago) - STALE"
            style = "color: #e74c3c; font-weight: bold;"  # Red + bold

        self._freshness_label.setText(status_text)
        self._freshness_label.setStyleSheet(style)

    def _update_legacy_warning(self, snapshot) -> None:
        """Show warning if legacy runtime namespace is detected."""
        if getattr(snapshot, 'legacy_namespace_detected', False):
            legacy_path = getattr(snapshot, 'legacy_namespace_path', '')
            warning_text = (
                f"⚠️ WARNING: Legacy runtime namespace detected at:\n{legacy_path}\n"
                "Data may exist in old location. Active namespace is in ~/.codex-api-home/"
            )
            self._legacy_warning_label.setText(warning_text)
            self._legacy_warning_label.setStyleSheet("color: #e67e22; font-weight: bold;")  # Orange
            self._legacy_warning_label.show()
        else:
            self._legacy_warning_label.hide()

    def _update_gpu_status(self, snapshot) -> None:
        """Update GPU acceleration status in Runtime Details."""
        gpu_info = getattr(snapshot, 'gpu_info', {})
        if not gpu_info:
            # Try to get from direct detection if snapshot doesn't have it
            from app.services.state_store import _detect_gpu_status
            gpu_info = _detect_gpu_status()
            if not gpu_info:
                return
        
        gpu_available = gpu_info.get('available', False)
        gpu_type = gpu_info.get('type', 'none')
        gpu_model = gpu_info.get('model', '')
        ollama_on_gpu = gpu_info.get('ollama_on_gpu', False)
        model_loaded = gpu_info.get('model_loaded', False)
        vram_used = gpu_info.get('vram_used_mb', 0)
        vram_total = gpu_info.get('vram_total_mb', 0)
        
        if gpu_available and ollama_on_gpu:
            status_text = f"✅ {gpu_type.upper()}: {gpu_model}"
            if vram_total > 0:
                status_text += f" ({vram_used}/{vram_total}MB)"
            tooltip = "GPU acceleration active - optimal performance"
            style = "color: #2ecc71;"  # Green
        elif gpu_available and model_loaded and not ollama_on_gpu:
            # Model is loaded but NOT using GPU - this is a real problem
            status_text = f"⚠️ {gpu_type.upper()}: {gpu_model} (CPU mode)"
            tooltip = "GPU detected but Ollama using CPU - check CUDA/ROCm installation"
            style = "color: #f1c40f;"  # Yellow
        elif gpu_available and not model_loaded:
            # No model loaded - this is normal idle state
            status_text = f"ℹ️ {gpu_type.upper()}: {gpu_model} (idle)"
            tooltip = "GPU ready - model will load on GPU when needed"
            style = "color: #3498db;"  # Blue
        else:
            status_text = "❌ CPU only"
            tooltip = "No GPU detected - performance will be slower"
            style = "color: #e74c3c;"  # Red
        
        if "GPU Acceleration" in self._runtime_detail_labels:
            label = self._runtime_detail_labels["GPU Acceleration"]
            label.setText(status_text)
            label.setStyleSheet(style)
            label.setToolTip(tooltip)

    def refresh_auxiliary_views(self) -> None:
        self._refresh_engineering_views()
        self._refresh_service_view()

    def set_interface_level(self, level: str) -> None:
        """Apply HMI level visibility to status panel elements.
        
        SIMPLE:     Build info only (minimal status)
        POWER:      Build info + operational status (route, provider, health)
        ENGINEERING: Everything including detailed diagnostics
        """
        self._current_level = level
        is_eng = is_engineering(level)
        is_pwr = level_at_least(level, POWER)
        
        # Runtime Summary visibility
        if is_eng:
            self._runtime_summary_group.setTitle("Runtime Summary")
            self._runtime_summary_group.setVisible(True)
            self._set_card_visibility(
                self._runtime_summary_cards,
                {
                    "Current Route", "Source Type", "Voice State", "Health",
                    "Augmented Policy", "Configured Provider", "Configured Provider Paid",
                    "Last Request Provider", "Last Request Paid",
                    "Session Augmented Calls", "Session Paid Augmented Calls", "Session Provider Counts",
                },
            )
        elif is_pwr:
            self._runtime_summary_group.setTitle("Runtime Status")
            self._runtime_summary_group.setVisible(True)
            self._set_card_visibility(
                self._runtime_summary_cards,
                {
                    "Current Route", "Source Type", "Voice State", "Health",
                    "Augmented Policy", "Configured Provider",
                },
            )
        else:
            # Simple: hide runtime summary completely
            self._runtime_summary_group.setVisible(False)
        
        # Runtime Detail visibility
        if is_eng:
            self._runtime_detail_group.setVisible(True)
            self._set_card_visibility(
                self._runtime_detail_cards,
                {
                    "Voice Backend", "Voice Error", "GPU Acceleration",
                    "Preprocess Active", "Reduced Scope", "Patch Surface Summary",
                    "Uncertainty / Underspecified",
                },
            )
        elif is_pwr:
            self._runtime_detail_group.setVisible(True)
            self._set_card_visibility(
                self._runtime_detail_cards,
                {"Voice Backend", "GPU Acceleration"},
            )
        else:
            self._runtime_detail_group.setVisible(False)
        
        # Request Summary visibility
        if is_eng:
            self._request_summary_group.setTitle("Request Diagnostics")
            self._request_summary_group.setVisible(True)
            self._set_card_visibility(
                self._request_summary_cards,
                {"Status", "Completed At", "Answer Path", "Trust", "Augmented", "Route Mode", "Outcome Code"},
            )
        elif is_pwr:
            self._request_summary_group.setTitle("Latest Request")
            self._request_summary_group.setVisible(True)
            self._set_card_visibility(
                self._request_summary_cards,
                {"Status", "Trust", "Augmented"},
            )
        else:
            self._request_summary_group.setVisible(False)
        
        # Engineering-only groups
        self._request_detail_group.setVisible(is_eng)
        self._advanced_metadata_group.setVisible(is_eng)
        self._history_maintenance_group.setVisible(is_eng)

    def _build_group(
        self,
        title: str,
        cards: list[tuple[str, str]],
        value_registry: dict[str, QLabel],
        card_registry: dict[str, QFrame],
    ) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setSpacing(8)
        for label, value in cards:
            card = self._build_card(label, value, value_registry)
            card_registry[label] = card
            layout.addWidget(card)
        return group

    def _build_card(
        self,
        label_text: str,
        value_text: str,
        registry: dict[str, QLabel],
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("statusChip")

        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(4)

        label = QLabel(label_text)
        label.setObjectName("cardLabel")

        value = QLabel(value_text)
        value.setObjectName("cardValue")
        value.setWordWrap(True)
        value.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        registry[label_text] = value

        layout.addWidget(label)
        layout.addWidget(value)
        return card

    def _set_card_visibility(self, card_registry: dict[str, QFrame], visible_labels: set[str]) -> None:
        for label, card in card_registry.items():
            card.setVisible(label in visible_labels)

    def _refresh_engineering_views(self) -> None:
        top_status = self._latest_runtime_snapshot.get("top_status", {})
        runtime_status = self._latest_runtime_snapshot.get("runtime_status", {})
        file_paths = self._latest_runtime_snapshot.get("file_paths", {})

        state_lines = ["[top_status]"]
        for key, value in top_status.items():
            state_lines.append(f"{key}: {value}")
        state_lines.append("")
        state_lines.append("[runtime_status]")
        for key, value in runtime_status.items():
            state_lines.append(f"{key}: {value}")
        state_lines.append("")
        state_lines.append("[file_paths]")
        for key, value in file_paths.items():
            state_lines.append(f"{key}: {value}")
        self._set_preserving_scroll(self._advanced_state_view, "\n".join(state_lines))

        if self._latest_request_payload is None:
            self._set_preserving_scroll(self._advanced_request_view, "No persisted request entry selected.")
            return
        self._set_preserving_scroll(
            self._advanced_request_view,
            json.dumps(self._latest_request_payload, indent=2, sort_keys=True),
        )

    def _refresh_service_view(self) -> None:
        file_paths = self._latest_runtime_snapshot.get("file_paths", {})
        request_history_path = file_paths.get("request_history", "unavailable")
        last_result_path = file_paths.get("last_request_result", "unavailable")
        history_path = self._path_or_none(request_history_path)
        active_count, invalid_count = self._history_entry_counts(history_path)
        archive_count, latest_archive = self._history_archive_summary(history_path)
        retention_cap = self._history_retention_cap_text()

        active_entries_line = f"Active entries: {active_count}"
        if invalid_count:
            active_entries_line = f"{active_entries_line} (invalid lines: {invalid_count})"

        summary_lines = [
            "Advanced visibility only. No destructive actions are live in this phase.",
            "",
            f"Active request history: {request_history_path}",
            active_entries_line,
            f"Retention cap (active): {retention_cap}",
            f"Archive files: {archive_count}",
            f"Latest archive: {latest_archive}",
            f"Latest request result: {last_result_path}",
            "Archive browsing: not exposed in the UI yet.",
            "Retention controls: backend-managed only.",
        ]
        self._set_preserving_scroll(self._history_maintenance_view, "\n".join(summary_lines))

    def _set_preserving_scroll(self, widget: QPlainTextEdit, text: str) -> None:
        if widget.toPlainText() == text:
            return
        widget.setPlainText(text)

    def capture_scroll_state(self) -> dict[str, int]:
        return {
            "advanced_state": self._advanced_state_view.verticalScrollBar().value(),
            "advanced_request": self._advanced_request_view.verticalScrollBar().value(),
        }

    def restore_scroll_state(self, state: dict[str, int] | None) -> None:
        if not isinstance(state, dict):
            return
        state_scroll = self._advanced_state_view.verticalScrollBar()
        request_scroll = self._advanced_request_view.verticalScrollBar()
        if "advanced_state" in state:
            state_scroll.setValue(min(int(state["advanced_state"]), state_scroll.maximum()))
        if "advanced_request" in state:
            request_scroll.setValue(min(int(state["advanced_request"]), request_scroll.maximum()))

    def set_scroll_view_updates_enabled(self, enabled: bool) -> None:
        widgets = (
            self._advanced_state_view,
            self._advanced_request_view,
            self._history_maintenance_view,
        )
        for widget in widgets:
            widget.setUpdatesEnabled(enabled)
            widget.viewport().setUpdatesEnabled(enabled)

    def _path_or_none(self, value: str) -> Path | None:
        raw = str(value or "").strip()
        if not raw or raw == "unavailable":
            return None
        return Path(raw).expanduser()

    def _history_entry_counts(self, history_path: Path | None) -> tuple[int, int]:
        if history_path is None or not history_path.exists() or not history_path.is_file():
            return 0, 0
        try:
            lines = history_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0, 0

        valid = 0
        invalid = 0
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                invalid += 1
                continue
            if isinstance(parsed, dict):
                valid += 1
            else:
                invalid += 1
        return valid, invalid

    def _history_archive_summary(self, history_path: Path | None) -> tuple[int, str]:
        if history_path is None:
            return 0, "none"
        archive_pattern = f"{history_path.stem}.*{history_path.suffix}"
        archive_paths = sorted(path for path in history_path.parent.glob(archive_pattern) if path.is_file())
        if not archive_paths:
            return 0, "none"
        return len(archive_paths), str(archive_paths[-1])

    def _history_retention_cap_text(self) -> str:
        raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_MAX_ENTRIES", "").strip()
        if not raw:
            return f"{DEFAULT_HISTORY_RETENTION_MAX_ENTRIES} (default)"
        try:
            value = int(raw)
        except ValueError:
            return f"{DEFAULT_HISTORY_RETENTION_MAX_ENTRIES} (default; invalid env '{raw}')"
        if value <= 0:
            return f"{DEFAULT_HISTORY_RETENTION_MAX_ENTRIES} (default; invalid env '{raw}')"
        return str(value)

    def _payload_text(self, payload: dict[str, object] | None, key: str) -> str:
        if not isinstance(payload, dict):
            return ""
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _nested_text(self, payload: dict[str, object] | None, key: str, nested_key: str) -> str:
        if not isinstance(payload, dict):
            return ""
        nested = payload.get(key)
        if not isinstance(nested, dict):
            return ""
        value = nested.get(nested_key)
        if value is None:
            return ""
        return str(value).strip()

    def _answer_contract(self, payload: dict[str, object] | None) -> dict[str, object]:
        if not isinstance(payload, dict):
            return {}
        outcome = payload.get("outcome")
        if not isinstance(outcome, dict):
            return {}
        contract = outcome.get("augmented_answer_contract")
        return contract if isinstance(contract, dict) else {}

    def _answer_contract_verification_text(self, payload: dict[str, object] | None) -> str:
        contract = self._answer_contract(payload)
        value = str(contract.get("verification_status") or "").strip()
        return value or "not applicable"

    def _answer_contract_confidence_text(self, payload: dict[str, object] | None) -> str:
        contract = self._answer_contract(payload)
        label = str(contract.get("estimated_confidence_label") or "").strip()
        if label:
            return label
        value = contract.get("estimated_confidence_pct")
        if value in {None, ""}:
            return "not applicable"
        band = str(contract.get("estimated_confidence_band") or "").strip()
        if band:
            return f"{value}% ({band}, estimated)"
        return f"{value}% estimated"

    def _answer_contract_source_basis_text(self, payload: dict[str, object] | None) -> str:
        contract = self._answer_contract(payload)
        source_basis = contract.get("source_basis")
        if isinstance(source_basis, list):
            values = [str(item).strip() for item in source_basis if str(item).strip()]
            return ", ".join(values) if values else "not applicable"
        value = str(source_basis or "").strip()
        return value or "not applicable"

    def _control_state_text(self, payload: dict[str, object] | None) -> str:
        if not isinstance(payload, dict):
            return "unavailable"
        control_state = payload.get("control_state")
        if not isinstance(control_state, dict) or not control_state:
            return "unavailable"
        ordered_keys = ("mode", "conversation", "memory", "evidence", "voice", "augmentation_policy", "augmented_provider", "model", "profile")
        parts = [
            f"{key}={control_state[key]}"
            for key in ordered_keys
            if key in control_state and str(control_state[key]).strip()
        ]
        return ", ".join(parts) if parts else "unavailable"

    def _format_runtime_value(self, label_text: str, value: str) -> str:
        if label_text != "Health":
            return value
        if is_engineering(self._current_level):
            return value

        normalized = str(value or "").strip().lower()
        if "status=running" in normalized or "running=true" in normalized:
            return "Running"
        if "status=stopped" in normalized or "running=false" in normalized:
            return "Stopped"
        if "status=failed" in normalized:
            return "Failed"
        return value

    def _answer_path_text(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            return "Evidence insufficient"

        contract_path = self._nested_text(payload, "outcome", "operator_answer_path")
        if contract_path:
            return contract_path
        final_mode = self._nested_text(payload, "outcome", "final_mode") or self._nested_text(payload, "route", "mode")
        final_mode_upper = final_mode.upper()
        trust_class = self._nested_text(payload, "outcome", "trust_class").lower()
        fallback_used = self._nested_text(payload, "outcome", "fallback_used").lower() in {"1", "true", "yes", "on"}
        fallback_reason = self._nested_text(payload, "outcome", "fallback_reason")
        provider = (
            self._nested_text(payload, "outcome", "augmented_provider_used")
            or self._nested_text(payload, "outcome", "augmented_provider")
            or self._nested_text(payload, "control_state", "augmented_provider")
        ).strip()
        provider_label = provider.upper() if provider and provider.lower() != "none" else "augmented"
        forced_augmented = self._nested_text(payload, "outcome", "augmented_direct_request").lower() in {"1", "true", "yes", "on"}
        outcome_code = self._nested_text(payload, "outcome", "outcome_code").lower()

        if final_mode_upper == "AUGMENTED":
            if fallback_used:
                if fallback_reason == "local_generation_degraded":
                    return f"Local degraded -> {provider_label} fallback"
                if fallback_reason == "validated_insufficient":
                    return f"Evidence insufficient -> {provider_label} fallback"
                return f"{provider_label} fallback"
            if forced_augmented:
                return f"Forced augmented -> {provider_label}"
            return f"Augmented via {provider_label}"
        if trust_class == "evidence_backed" or final_mode_upper == "EVIDENCE":
            return "Evidence-backed answer"
        if outcome_code == "clarification_requested" or final_mode_upper == "CLARIFY":
            return "Clarification requested"
        if final_mode_upper == "LOCAL":
            return "Local answer"
        return final_mode or "unknown"

    def _operator_trust_text(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            return "insufficient-evidence"
        return (
            self._nested_text(payload, "outcome", "operator_trust_label")
            or self._nested_text(payload, "outcome", "trust_class")
            or "unknown"
        )

    def _augmented_summary_text(self, payload: dict[str, object] | None) -> str:
        provider = self._augmented_provider_label(payload)
        status = self._nested_text(payload, "outcome", "augmented_provider_status").lower()

        if status == "available" and provider:
            return f"{provider} available"
        if status == "external_unavailable" and provider:
            return f"{provider} unavailable"
        if status == "misconfigured" and provider:
            return f"{provider} misconfigured"
        if status == "provider_error" and provider:
            return f"{provider} error"
        if status in {"disabled", "not_used"}:
            return "not used"

        call_reason = self._nested_text(payload, "outcome", "augmented_provider_call_reason").lower()
        if provider and provider != "NONE" and call_reason in {"direct", "fallback", "error"}:
            return f"{provider} used"
        if provider == "NONE":
            return "not used"
        return "unknown"

    def _operator_note_text(self, payload: dict[str, object] | None) -> str:
        if self._is_validated_insufficient(payload):
            action_hint = self._action_hint_text(payload)
            if action_hint:
                return f"Current evidence was insufficient. Next step: {action_hint}"
            return "Current evidence was insufficient for a reliable answer."

        contract_note = self._nested_text(payload, "outcome", "operator_note")
        if contract_note:
            return contract_note
        fallback_reason = self._nested_text(payload, "outcome", "fallback_reason")
        fallback_used = self._nested_text(payload, "outcome", "fallback_used").lower() in {"1", "true", "yes", "on"}
        trust_class = self._nested_text(payload, "outcome", "trust_class").lower()
        final_mode = (self._nested_text(payload, "outcome", "final_mode") or self._nested_text(payload, "route", "mode")).upper()
        outcome_code = self._nested_text(payload, "outcome", "outcome_code").lower()

        if fallback_used and fallback_reason == "local_generation_degraded":
            return "Escalated because the local answer degraded."
        if fallback_used and fallback_reason == "validated_insufficient":
            return "Escalated because the evidence path was insufficient."
        if trust_class == "evidence_backed" or final_mode == "EVIDENCE":
            return "Answer is grounded in current evidence."
        if outcome_code == "clarification_requested" or final_mode == "CLARIFY":
            return "A narrower question is required for correctness."
        return "No escalation was needed."

    def _action_hint_text(self, payload: dict[str, object] | None) -> str:
        action_hint = self._nested_text(payload, "outcome", "action_hint").strip()
        if not action_hint or action_hint.lower() == "none":
            return ""
        if action_hint[-1] not in ".!?":
            action_hint = f"{action_hint}."
        return action_hint

    def _is_validated_insufficient(self, payload: dict[str, object] | None) -> bool:
        outcome_code = self._nested_text(payload, "outcome", "outcome_code").lower()
        if outcome_code != "validated_insufficient":
            return False
        return self._nested_text(payload, "outcome", "fallback_used").lower() not in {"1", "true", "yes", "on"}

    def _augmented_provider_label(self, payload: dict[str, object] | None) -> str:
        provider = ""
        for candidate in (
            self._nested_text(payload, "outcome", "augmented_provider_used"),
            self._nested_text(payload, "outcome", "augmented_provider"),
            self._nested_text(payload, "control_state", "augmented_provider"),
        ):
            raw = str(candidate or "").strip()
            if not raw or raw.lower() == "none":
                continue
            provider = raw
            break
        if not provider:
            fallback = (
                self._nested_text(payload, "outcome", "augmented_provider_used")
                or self._nested_text(payload, "outcome", "augmented_provider")
                or self._nested_text(payload, "control_state", "augmented_provider")
            ).strip()
            if fallback.lower() == "none":
                return "NONE"
            return ""
        return provider.upper()
