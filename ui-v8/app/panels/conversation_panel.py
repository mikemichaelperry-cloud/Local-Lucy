from PySide6.QtCore import QTimer, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices, QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui_levels import SIMPLE, POWER, ENGINEERING, normalize_level, level_at_least, is_simple, is_engineering


class ConversationPanel(QFrame):
    clear_draft_requested = Signal()
    submit_requested = Signal(str)
    history_selection_changed = Signal(str)
    decision_trace_toggled = Signal(bool)
    voice_cancel_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("shellCard")
        self._entry_map: dict[str, dict[str, object]] = {}
        self._selection_blocked = False
        self._current_level = SIMPLE
        self._scroll_area: QScrollArea | None = None
        self._content_widget: QWidget | None = None
        self._input_label: QLabel | None = None
        self._actions_row: QHBoxLayout | None = None
        self._clear_button: QPushButton | None = None
        self._operator_submit_enabled = False

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 14, 14, 14)
        root_layout.setSpacing(0)

        scroll_area = QScrollArea()
        scroll_area.setObjectName("conversationScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.viewport().setObjectName("conversationScrollViewport")
        scroll_area.viewport().setAutoFillBackground(False)
        self._scroll_area = scroll_area
        root_layout.addWidget(scroll_area)

        content_widget = QWidget()
        content_widget.setObjectName("conversationScrollContent")
        content_widget.setAttribute(Qt.WA_StyledBackground, False)
        self._content_widget = content_widget
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        scroll_area.setWidget(content_widget)

        title = QLabel("Conversation / Output")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        history_label = QLabel("Recent History")
        history_label.setObjectName("cardLabel")
        self._history_label = history_label
        layout.addWidget(history_label)

        self._recent_history_summary = QPlainTextEdit()
        self._recent_history_summary.setReadOnly(True)
        self._recent_history_summary.setFixedHeight(110)
        self._recent_history_summary.setPlainText(self._default_recent_history_text())
        layout.addWidget(self._recent_history_summary, stretch=0)

        self._history_list = QListWidget()
        self._history_list.setSelectionMode(QListWidget.SingleSelection)
        self._history_list.setMinimumHeight(190)
        self._history_list.currentItemChanged.connect(self._handle_current_item_changed)
        layout.addWidget(self._history_list, stretch=0)

        output_label = QLabel("Latest Answer")
        output_label.setObjectName("cardLabel")
        self._output_label = output_label
        layout.addWidget(output_label)

        trace_row = QHBoxLayout()
        trace_row.setSpacing(8)

        trace_label = QLabel("Decision Trace")
        trace_label.setObjectName("cardLabel")
        trace_row.addWidget(trace_label)

        self._decision_trace_summary_button = QPushButton("Latest decision trace unavailable")
        self._decision_trace_summary_button.setObjectName("traceSummaryButton")
        self._decision_trace_summary_button.setCheckable(True)
        self._decision_trace_summary_button.setEnabled(False)
        self._decision_trace_summary_button.toggled.connect(self.decision_trace_toggled.emit)
        trace_row.addWidget(self._decision_trace_summary_button, stretch=1)
        layout.addLayout(trace_row)

        self._history = QTextBrowser()
        self._history.setOpenExternalLinks(False)  # We handle links manually to ensure they open in browser
        self._history.setOpenLinks(False)  # Prevent internal navigation to avoid "No document" warnings
        self._history.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._history.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._history.setPlainText(self._default_history_text())
        self._history.document().documentLayout().documentSizeChanged.connect(lambda _size: self._schedule_output_height_sync())
        # Enable clickable links - connect anchorClicked to open URLs in browser
        self._history.anchorClicked.connect(self._on_link_clicked)
        layout.addWidget(self._history, stretch=1)

        input_label = QLabel("Operator Input")
        input_label.setObjectName("cardLabel")
        self._input_label = input_label
        layout.addWidget(input_label)

        # Voice transcription preview (shown during voice input)
        self._voice_preview_label = QLabel("")
        self._voice_preview_label.setObjectName("cardLabel")
        self._voice_preview_label.setWordWrap(True)
        self._voice_preview_label.setStyleSheet("color: #7ec08b; font-style: italic;")
        self._voice_preview_label.setVisible(False)
        layout.addWidget(self._voice_preview_label)

        self._draft = QTextEdit()
        self._draft.setAcceptRichText(False)
        self._draft.setTabChangesFocus(False)
        self._draft.setFocusPolicy(Qt.StrongFocus)
        self._draft.setPlaceholderText(
            "Type an operator prompt here.\n\n"
            "Submit dispatches a single authoritative backend request.\n"
            "Slash text (for example /status) is sent as request text unless GUI command handling is implemented."
        )
        self._draft.setFixedHeight(120)
        layout.addWidget(self._draft)

        self._force_augmented_once_checkbox = QCheckBox("Force Augmented Once (test)")
        self._force_augmented_once_checkbox.setToolTip(
            "Advanced only: sends the next submit with one-shot direct augmented override metadata."
        )
        self._force_augmented_once_checkbox.setChecked(False)
        layout.addWidget(self._force_augmented_once_checkbox)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._actions_row = actions

        clear_button = QPushButton("Clear Draft")
        clear_button.clicked.connect(self.clear_draft_requested.emit)
        self._clear_button = clear_button
        self._submit_button = QPushButton("Submit")
        self._submit_button.clicked.connect(self._emit_submit_requested)

        actions.addWidget(clear_button)
        actions.addStretch(1)
        actions.addWidget(self._submit_button)
        layout.addLayout(actions)

        self.set_interface_level("operator")
        self._schedule_output_height_sync()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._schedule_output_height_sync()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Enter key to submit when draft has focus."""
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            # Only submit if draft has focus and submit is enabled
            if self._draft.hasFocus() and self._operator_submit_enabled:
                # Check if Shift is pressed - if so, insert newline
                if event.modifiers() & Qt.ShiftModifier:
                    super().keyPressEvent(event)
                    return
                self._emit_submit_requested()
                return
        super().keyPressEvent(event)

    def clear_draft(self) -> None:
        self._draft.clear()

    def draft_text(self) -> str:
        return self._draft.toPlainText()

    def draft_has_focus(self) -> bool:
        return self._draft.hasFocus() or self._draft.viewport().hasFocus()

    def focus_draft(self) -> None:
        self._draft.setFocus(Qt.OtherFocusReason)

    def set_submit_enabled(self, enabled: bool) -> None:
        self._operator_submit_enabled = enabled
        # Force augmented only available in Engineering level
        checkbox_enabled = enabled and is_engineering(self._current_level)
        self._force_augmented_once_checkbox.setEnabled(checkbox_enabled)
        self._sync_submit_state()

    def set_decision_trace_summary(self, summary: str, *, available: bool) -> None:
        button = self._decision_trace_summary_button
        button.setText(summary)
        button.setEnabled(available)
        button.setToolTip(summary if available else "")
        if not available and button.isChecked():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)

    def set_decision_trace_expanded(self, expanded: bool) -> None:
        button = self._decision_trace_summary_button
        if button.isChecked() == expanded:
            return
        button.blockSignals(True)
        button.setChecked(expanded)
        button.blockSignals(False)

    def consume_force_augmented_once(self) -> bool:
        # Force augmented only available in Engineering level
        if not is_engineering(self._current_level):
            return False
        if not self._force_augmented_once_checkbox.isChecked():
            return False
        self._force_augmented_once_checkbox.setChecked(False)
        return True

    def set_interface_level(self, level: str) -> None:
        """Apply HMI level to conversation panel.
        
        SIMPLE: Clean conversation view, minimal controls
        POWER: + History list access
        ENGINEERING: Full controls including force augmented
        """
        self._current_level = normalize_level(level)
        is_eng = is_engineering(self._current_level)
        is_pwr = level_at_least(self._current_level, POWER)
        
        # Labels change based on level
        self._history_label.setText("Request History" if is_pwr else "Recent Activity")
        self._output_label.setText("Response" if is_simple(self._current_level) else "Answer")
        
        # History view: summary for Simple, list for Power/Engineering
        self._recent_history_summary.setVisible(not is_pwr)
        self._history_list.setVisible(is_pwr)
        
        # Decision trace button always visible but may show different detail
        self._decision_trace_summary_button.setVisible(True)
        
        # Core conversation elements always visible
        self._history.setVisible(True)
        if self._input_label is not None:
            self._input_label.setVisible(True)
        self._draft.setVisible(True)
        self._submit_button.setVisible(True)
        if self._clear_button is not None:
            self._clear_button.setVisible(True)
        
        # Force augmented checkbox only in Engineering
        self._force_augmented_once_checkbox.setVisible(is_eng)
        self._force_augmented_once_checkbox.setEnabled(is_eng and self._submit_button.isEnabled())
        if not is_eng:
            self._force_augmented_once_checkbox.setChecked(False)
        
        self._sync_submit_state()
        self._schedule_output_height_sync()

    def set_voice_transcription_preview(self, text: str | None) -> None:
        """Display voice transcription preview during voice input.
        
        Args:
            text: Transcription text to display, or None/empty to hide
        """
        if not text:
            self._voice_preview_label.setText("")
            self._voice_preview_label.setVisible(False)
            return
        
        preview = text if len(text) <= 80 else f"{text[:77]}..."
        self._voice_preview_label.setText(f"🎤 {preview}")
        self._voice_preview_label.setVisible(True)

    def clear_voice_transcription_preview(self) -> None:
        """Clear voice transcription preview."""
        self._voice_preview_label.setText("")
        self._voice_preview_label.setVisible(False)

    def _debug_log(self, msg: str) -> None:
        """Write debug log to file."""
        import os
        from pathlib import Path
        log_path = Path.home() / "lucy-v8" / "ui_debug.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            from datetime import datetime
            f.write(f"{datetime.now().isoformat()} CONV {msg}\n")

    def set_history_entries(
        self,
        entries: list[dict[str, object]],
        *,
        selected_request_id: str | None = None,
    ) -> str | None:
        self._debug_log(f"set_history_entries: {len(entries)} entries")
        self._entry_map.clear()
        draft_had_focus = self.draft_has_focus()
        draft_cursor = self._draft.textCursor()
        self._selection_blocked = True
        self._history_list.clear()

        if not entries:
            self._selection_blocked = False
            self._set_plain_text(self._history, self._default_history_text(), reset_scroll=False)
            self._set_plain_text(self._recent_history_summary, self._default_recent_history_text(), reset_scroll=False)
            if draft_had_focus:
                self._draft.setTextCursor(draft_cursor)
                self.focus_draft()
            return None

        self._set_plain_text(self._recent_history_summary, self._build_recent_history_text(entries), reset_scroll=False)
        display_entries = list(reversed(entries))
        selected_id = selected_request_id or self._request_id(display_entries[0])

        for entry in display_entries:
            request_id = self._request_id(entry)
            self._entry_map[request_id] = entry
            item = QListWidgetItem(self._list_label(entry))
            item.setData(Qt.UserRole, request_id)
            self._history_list.addItem(item)

        applied_selection = self._select_request_id(selected_id)
        self._selection_blocked = False

        if applied_selection is None:
            self._set_plain_text(self._history, self._default_history_text(), reset_scroll=False)
            if draft_had_focus:
                self._draft.setTextCursor(draft_cursor)
                self.focus_draft()
            return None

        self._render_selected_entry(applied_selection)
        if draft_had_focus:
            self._draft.setTextCursor(draft_cursor)
            self.focus_draft()
        return applied_selection

    def _emit_submit_requested(self) -> None:
        self.submit_requested.emit(self.draft_text())

    def _sync_submit_state(self) -> None:
        self._submit_button.setEnabled(self._operator_submit_enabled)

    def _default_history_text(self) -> str:
        # Engineering gets technical message, Simple/Power get user-friendly
        if is_engineering(self._current_level):
            return (
                "[system] Backend submit path is authoritative and non-interactive.\n"
                "[system] No persisted request history is available yet."
            )
        return (
            "No requests yet.\n"
            "Type a message and press Send to start."
        )

    def _default_recent_history_text(self) -> str:
        return (
            "No history available yet.\n"
            "Your conversation will appear here."
        )

    def _handle_current_item_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        del previous
        if current is None:
            return
        request_id = str(current.data(Qt.UserRole) or "").strip()
        if not request_id:
            return
        self._render_selected_entry(request_id)
        if not self._selection_blocked:
            self.history_selection_changed.emit(request_id)

    def _select_request_id(self, request_id: str | None) -> str | None:
        target_id = (request_id or "").strip()
        if not target_id and self._history_list.count() > 0:
            first_item = self._history_list.item(0)
            target_id = str(first_item.data(Qt.UserRole) or "").strip()

        for index in range(self._history_list.count()):
            item = self._history_list.item(index)
            item_request_id = str(item.data(Qt.UserRole) or "").strip()
            if item_request_id == target_id:
                self._history_list.setCurrentRow(index)
                return item_request_id

        if self._history_list.count() > 0:
            self._history_list.setCurrentRow(0)
            first_item = self._history_list.item(0)
            return str(first_item.data(Qt.UserRole) or "").strip()
        return None

    def _render_selected_entry(self, request_id: str) -> None:
        self._debug_log(f"_render_selected_entry: {request_id}")
        entry = self._entry_map.get(request_id)
        if entry is None:
            self._debug_log("entry not found in map")
            self._set_plain_text(self._history, self._default_history_text(), reset_scroll=False)
            return
        formatted = self._format_history_entry(entry)
        self._debug_log(f"formatted text length: {len(formatted)}")
        self._set_plain_text(self._history, formatted, reset_scroll=True)

    def _build_recent_history_text(self, entries: list[dict[str, object]]) -> str:
        visible_entries = entries[-4:]
        if not visible_entries:
            return self._default_recent_history_text()

        lines = ["Recent authoritative requests:"]
        for entry in reversed(visible_entries):
            status = (self._entry_text(entry, "status") or "unknown").upper()
            completed_at = self._entry_text(entry, "completed_at") or "unknown"
            request_text = self._entry_text(entry, "request_text") or "unknown"
            preview = request_text if len(request_text) <= 64 else f"{request_text[:61]}..."
            lines.append(f"{status}  {completed_at}")
            lines.append(preview)
        return "\n".join(lines)

    def _list_label(self, entry: dict[str, object]) -> str:
        request_id = self._request_id(entry) or "unknown"
        status = self._entry_text(entry, "status") or "unknown"
        completed_at = self._entry_text(entry, "completed_at") or "unknown"
        request_text = self._entry_text(entry, "request_text") or "unknown"
        preview = request_text if len(request_text) <= 56 else f"{request_text[:53]}..."
        # Show processing/responding status more prominently
        if status == "processing":
            return f"⏳ PROCESSING...\n{preview}\n{request_id}"
        if status == "responding":
            return f"🗣️ RESPONDING...\n{preview}\n{request_id}"
        return f"{status.upper()}  {completed_at}\n{preview}\n{request_id}"

    def _request_id(self, entry: dict[str, object]) -> str:
        return self._entry_text(entry, "request_id")

    def _format_history_entry(self, entry: dict[str, object]) -> str:
        # Engineering gets diagnostic format, Simple/Power get clean format
        if is_engineering(self._current_level):
            return self._format_diagnostic_entry(entry)
        return self._format_operator_entry(entry)

    def _format_operator_entry(self, entry: dict[str, object]) -> str:
        import html as html_module
        
        request_text = self._entry_text(entry, "request_text") or "Unknown request."
        status = self._entry_text(entry, "status") or "unknown"
        
        # Escape request text for HTML
        request_text_html = html_module.escape(request_text)
        
        # Handle processing status specially
        if status == "processing":
            return self._build_html_response(
                f"Latest Request<br>{request_text_html}",
                "Processing...<br>⏳ Lucy is thinking..."
            )
        
        # Handle responding status - show full answer while TTS is speaking
        if status == "responding":
            response_text = self._entry_text(entry, "response_text")
            if response_text:
                # Check if response is HTML or plain text
                if self._is_html_content(response_text):
                    # Already HTML, embed directly
                    return self._build_html_response(
                        f"Latest Request<br>{request_text_html}",
                        f"<b>Latest Answer (speaking...)</b><br>{response_text}"
                    )
                else:
                    # Plain text, escape it
                    response_html = html_module.escape(response_text).replace('\n', '<br>')
                    return self._build_html_response(
                        f"Latest Request<br>{request_text_html}",
                        f"<b>Latest Answer (speaking...)</b><br>{response_html}"
                    )
            return self._build_html_response(
                f"Latest Request<br>{request_text_html}",
                "Responding...<br>🗣️ Speaking..."
            )
        
        has_failure = self._entry_has_operator_failure(entry)
        result_title = "Latest Result" if has_failure else "Latest Answer"
        
        # For non-failure responses, preserve original HTML (news links, etc.)
        raw_response = self._entry_text(entry, "response_text") or ""
        if not has_failure and self._is_html_content(raw_response):
            return self._build_html_response(
                f"Latest Request<br>{request_text_html}",
                f"<b>{result_title}</b><br>{raw_response}"
            )
        
        result_text = self._operator_failure_text(entry) if has_failure else self._operator_response_text(entry)
        
        # Check if result_text is HTML or plain text
        if self._is_html_content(result_text):
            # Already HTML, embed directly
            return self._build_html_response(
                f"Latest Request<br>{request_text_html}",
                f"<b>{result_title}</b><br>{result_text}"
            )
        else:
            # Plain text, escape it
            result_html = html_module.escape(result_text).replace('\n', '<br>')
            return self._build_html_response(
                f"Latest Request<br>{request_text_html}",
                f"<b>{result_title}</b><br>{result_html}"
            )
    
    def _build_html_response(self, request_section: str, response_section: str) -> str:
        """Build a complete HTML document for the response."""
        return f'''<!DOCTYPE html>
<html>
<head>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; font-size: 14px; line-height: 1.5; }}
b {{ font-weight: 600; }}
a {{ color: #0066cc; text-decoration: underline; }}
a:hover {{ color: #0052a3; }}
</style>
</head>
<body>
<div style="margin-bottom: 16px;">
<b>Latest Request</b><br>
{request_section}
</div>
<div>
{response_section}
</div>
</body>
</html>'''

    def _format_diagnostic_entry(self, entry: dict[str, object]) -> str:
        lines = [
            f"[request] {self._entry_text(entry, 'request_id') or 'unknown'}"
            f"  status={self._entry_text(entry, 'status') or 'unknown'}"
            f"  completed_at={self._entry_text(entry, 'completed_at') or 'unknown'}",
            f"[user] {self._entry_text(entry, 'request_text') or 'unknown'}",
        ]

        status = self._entry_text(entry, "status")
        if status == "completed":
            response_text = self._entry_text(entry, "response_text") or "empty response"
            lines.append(f"[assistant] {response_text}")
        else:
            failure_detail = self._entry_text(entry, "error") or status or "failed"
            lines.append(f"[system] request {status or 'failed'}: {failure_detail}")

        route = entry.get("route")
        if isinstance(route, dict):
            route_mode = self._entry_text(route, "mode")
            route_reason = self._entry_text(route, "reason")
            if route_mode or route_reason:
                lines.append(
                    f"[route] mode={route_mode or 'unknown'}"
                    f" reason={route_reason or 'unknown'}"
                )

        outcome = entry.get("outcome")
        if isinstance(outcome, dict):
            outcome_code = self._entry_text(outcome, "outcome_code")
            action_hint = self._entry_text(outcome, "action_hint")
            if outcome_code or action_hint:
                lines.append(
                    f"[outcome] code={outcome_code or 'unknown'}"
                    f" hint={action_hint or 'none'}"
                )

        return "\n".join(lines)

    def _operator_response_text(self, entry: dict[str, object]) -> str:
        response_text = self._entry_text(entry, "response_text")
        if not response_text:
            return "No answer was returned."

        contract = self._answer_contract(entry)
        cleaned_lines: list[str] = []
        for raw_line in response_text.replace("\r", "").splitlines():
            line = raw_line.strip()
            if not line:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue
            lowered = line.lower()
            if lowered.startswith("augmented fallback (unverified answer):"):
                continue
            if lowered.startswith("augmented mode (unverified answer):"):
                continue
            if lowered.startswith("augmented route (unverified answer):"):
                continue
            if lowered.startswith("run:"):
                continue
            if lowered.startswith("instruction:"):
                continue
            if lowered.startswith("unverified context source class:"):
                continue
            if lowered.startswith("unverified context reference:"):
                continue
            if lowered.startswith("unverified context excerpt:"):
                continue
            cleaned_lines.append(self._normalize_operator_answer_line(line))

        cleaned_response = str(contract.get("answer") or "").strip() or "\n".join(cleaned_lines).strip() or "No answer was returned."
        answer_path = self._operator_answer_path_text(entry)
        metadata_line = self._answer_contract_metadata_line(entry)
        rendered_lines: list[str] = []
        if answer_path:
            rendered_lines.append(f"Path: {answer_path}")
        if metadata_line:
            rendered_lines.append(metadata_line)
        rendered_lines.append(cleaned_response)
        return "\n".join(rendered_lines)

    @staticmethod
    def _normalize_operator_answer_line(line: str) -> str:
        if not line.startswith("- ["):
            return line
        if "): " not in line and "] :" not in line:
            return line
        if line.rstrip().endswith((".", "!", "?")):
            return line
        return f"{line}."

    def _entry_has_operator_failure(self, entry: dict[str, object]) -> bool:
        status = (self._entry_text(entry, "status") or "").lower()
        error_text = self._entry_text(entry, "error")
        response_text = self._entry_text(entry, "response_text")
        lowered_response = response_text.lower()
        if status and status not in {"completed"}:
            return True
        if error_text:
            return True
        if not response_text:
            return True
        return (
            lowered_response.startswith("error:")
            or lowered_response.startswith("timeout")
            or lowered_response.startswith("failed:")
        )

    def _operator_failure_text(self, entry: dict[str, object]) -> str:
        status = (self._entry_text(entry, "status") or "").lower()
        if status == "timeout":
            return "Lucy timed out before returning a usable answer."
        if status and status not in {"completed"}:
            return "Lucy could not complete this request."
        return "Lucy could not return a usable answer for this request."

    def _operator_answer_path_text(self, entry: dict[str, object]) -> str:
        outcome = entry.get("outcome")
        route = entry.get("route")
        control_state = entry.get("control_state")
        outcome_code = self._nested_entry_text(outcome, "outcome_code").lower()
        fallback_used = self._nested_entry_text(outcome, "fallback_used").lower() in {"1", "true", "yes", "on"}

        if outcome_code == "validated_insufficient" and not fallback_used:
            return "Evidence insufficient"

        contract_path = self._nested_entry_text(outcome, "operator_answer_path")
        if contract_path:
            return contract_path

        final_mode = self._nested_entry_text(outcome, "final_mode") or self._nested_entry_text(route, "mode")
        final_mode_upper = final_mode.upper()
        trust_class = self._nested_entry_text(outcome, "trust_class").lower()
        fallback_reason = self._nested_entry_text(outcome, "fallback_reason")
        provider = (
            self._nested_entry_text(outcome, "augmented_provider_used")
            or self._nested_entry_text(outcome, "augmented_provider")
            or self._nested_entry_text(control_state, "augmented_provider")
        )
        provider_label = provider.upper() if provider and provider.lower() != "none" else "augmented"

        if final_mode_upper == "AUGMENTED" and fallback_used:
            if fallback_reason == "local_generation_degraded":
                return f"Local degraded -> {provider_label} fallback"
            if fallback_reason == "validated_insufficient":
                return f"Evidence insufficient -> {provider_label} fallback"
            return f"{provider_label} fallback"
        if trust_class == "evidence_backed" or final_mode_upper == "EVIDENCE":
            return "Evidence-backed answer"
        if outcome_code == "clarification_requested" or final_mode_upper == "CLARIFY":
            return "Clarification requested"
        if final_mode_upper == "LOCAL":
            return "Local answer"
        return ""

    def _nested_entry_text(self, payload: object, key: str) -> str:
        if not isinstance(payload, dict):
            return ""
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip()

    def _answer_contract(self, entry: dict[str, object]) -> dict[str, object]:
        outcome = entry.get("outcome")
        if not isinstance(outcome, dict):
            return {}
        contract = outcome.get("augmented_answer_contract")
        return contract if isinstance(contract, dict) else {}

    def _answer_contract_metadata_line(self, entry: dict[str, object]) -> str:
        contract = self._answer_contract(entry)
        verification = str(contract.get("verification_status") or "").strip()
        confidence_label = str(contract.get("estimated_confidence_label") or "").strip()
        confidence = contract.get("estimated_confidence_pct")
        confidence_band = str(contract.get("estimated_confidence_band") or "").strip()
        source_basis = contract.get("source_basis")
        source_basis_text = ""
        if isinstance(source_basis, list):
            values = [str(item).strip() for item in source_basis if str(item).strip()]
            source_basis_text = ", ".join(values)
        else:
            source_basis_text = str(source_basis or "").strip()

        parts: list[str] = []
        if verification:
            parts.append(f"Verification: {verification}")
        if confidence_label:
            parts.append(f"Confidence: {confidence_label}")
        elif confidence not in {None, ""}:
            rendered_confidence = f"{confidence}%"
            if confidence_band:
                rendered_confidence = f"{rendered_confidence} ({confidence_band}, estimated)"
            else:
                rendered_confidence = f"{rendered_confidence} estimated"
            parts.append(f"Confidence: {rendered_confidence}")
        if source_basis_text:
            parts.append(f"Source basis: {source_basis_text}")
        return " | ".join(parts)

    def _on_link_clicked(self, url: QUrl) -> None:
        """Open clicked links in default browser.
        
        Note: Must prevent default navigation to avoid clearing the widget content.
        """
        # Store current content before opening link (in case navigation clears it)
        current_html = self._history.toHtml()
        
        # Open in external browser
        QDesktopServices.openUrl(url)
        
        # Restore content after a short delay (QTextBrowser may clear on navigation)
        QTimer.singleShot(50, lambda: self._restore_history_content(current_html))
    
    def _restore_history_content(self, html_content: str) -> None:
        """Restore history content if it was cleared by link navigation."""
        # Only restore if content was cleared (significantly shorter than expected)
        if len(self._history.toPlainText()) < 10 and len(html_content) > 100:
            self._history.setHtml(html_content)
            self._debug_log("Restored history content after link click")

    def _set_plain_text(self, widget: QPlainTextEdit | QTextEdit | QTextBrowser, text: str, *, reset_scroll: bool) -> None:
        widget_name = "_history" if widget is self._history else "other"
        self._debug_log(f"_set_plain_text: {widget_name}, text length: {len(text)}")
        if widget.toPlainText() == text:
            self._debug_log("text unchanged, skipping")
            return
        
        # Check if text is already a complete HTML document
        if text.strip().startswith('<!DOCTYPE html>') or text.strip().startswith('<html>'):
            # Already a complete HTML document, use as-is
            widget.setHtml(text)
            self._debug_log(f"Complete HTML document set, new length: {len(widget.toPlainText())}")
        elif self._is_html_content(text):
            # Has HTML tags but not a complete document, wrap it
            html_content = self._wrap_mixed_content_as_html(text)
            widget.setHtml(html_content)
            self._debug_log(f"Wrapped HTML content set, new length: {len(widget.toPlainText())}")
        else:
            widget.setPlainText(text)
            self._debug_log(f"plain text set, new length: {len(widget.toPlainText())}")
        
        if reset_scroll:
            widget.verticalScrollBar().setValue(0)
        if widget is self._history:
            self._schedule_output_height_sync()
    
    def _is_html_content(self, text: str) -> bool:
        """Check if text contains HTML markup."""
        if not text:
            return False
        # Simple heuristic: check for common HTML tags
        html_indicators = ['<p>', '<a ', '<b>', '<i>', '<br>', '<div>', '<span>', '&lt;', '&gt;', '&amp;']
        text_lower = text.lower()
        return any(indicator in text_lower for indicator in html_indicators)
    
    def _wrap_mixed_content_as_html(self, text: str) -> str:
        """Wrap mixed plain text and HTML content in proper HTML structure."""
        import html as html_module
        
        lines = text.split('\n')
        html_parts = ['<!DOCTYPE html><html><body style="font-family: sans-serif; font-size: 14px;">']
        
        in_html_block = False
        
        for line in lines:
            stripped = line.strip()
            if not stripped:
                html_parts.append('<br>')
                continue
            
            # Check if line is HTML or plain text
            if stripped.startswith('<') and ('>' in stripped or stripped.startswith('<a ')):
                # It's HTML, add as-is
                html_parts.append(line)
                in_html_block = True
            else:
                # It's plain text, escape and wrap
                if in_html_block and html_parts[-1].endswith('</p>'):
                    html_parts.append('<br>')
                escaped = html_module.escape(line)
                # Convert URLs in plain text to links
                escaped = self._make_urls_clickable(escaped)
                html_parts.append(f'<div>{escaped}</div>')
                in_html_block = False
        
        html_parts.append('</body></html>')
        return '\n'.join(html_parts)
    
    def _make_urls_clickable(self, text: str) -> str:
        """Convert http/https URLs in text to HTML links."""
        import re
        import html
        
        # URL pattern
        url_pattern = r'(https?://[^\s<>"]+)'
        
        def replace_url(match):
            url = match.group(1)
            # Don't double-escape if already escaped
            safe_url = html.escape(url) if '&' not in url or ';' not in url else url
            return f'<a href="{safe_url}" style="color: #0066cc;">{safe_url}</a>'
        
        return re.sub(url_pattern, replace_url, text)

    def _schedule_output_height_sync(self) -> None:
        QTimer.singleShot(0, self._sync_output_height)
        QTimer.singleShot(20, self._sync_output_height)

    def _sync_output_height(self) -> None:
        view = self._history
        if view is None:
            self._debug_log("_sync_output_height: view is None")
            return
        doc_height = view.document().documentLayout().documentSize().height()
        margins = view.contentsMargins()
        chrome_height = margins.top() + margins.bottom() + (view.frameWidth() * 2) + 18
        target_height = max(180, int(doc_height) + chrome_height)
        self._debug_log(f"_sync_output_height: doc_height={doc_height}, target={target_height}, current={view.height()}")
        if view.height() != target_height:
            view.setFixedHeight(target_height)
            self._debug_log(f"height set to {target_height}")

    def _entry_text(self, payload: dict[str, object], key: str) -> str:
        value = payload.get(key)
        if value is None:
            return ""
        return str(value).strip()
