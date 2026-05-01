#!/usr/bin/env python3
"""Offscreen test for augmented controls and session counters (v8 direct payload injection)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev")
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    import json

    from app.services.state_store import REQUEST_HISTORY_FILE, REQUEST_RESULT_FILE
    from PySide6.QtWidgets import QApplication, QFrame
    from app.main_window import OperatorConsoleWindow

    # Clean history and last-result files for isolated test
    REQUEST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUEST_HISTORY_FILE.write_text("", encoding="utf-8")
    REQUEST_RESULT_FILE.write_text("", encoding="utf-8")

    app = QApplication([])
    window = OperatorConsoleWindow()
    window.show()
    app.processEvents()
    window.refresh_runtime_state()
    app.processEvents()

    labels = window.status_panel._runtime_summary_labels

    # Layout assertions
    assert_ok(window.conversation_panel.objectName() == "shellCard", "conversation panel should keep shell card container styling")
    assert_ok(window.conversation_panel.layout().contentsMargins().top() == 14, "conversation shell margins should match card layout spacing")
    assert_ok(window.conversation_panel._scroll_area is not None, "conversation panel should contain an internal scroll area")
    assert_ok(
        window.conversation_panel._scroll_area.parent() is window.conversation_panel,
        "scroll area should be nested inside conversation panel shell",
    )
    assert_ok(
        window.conversation_panel._scroll_area.frameShape() == QFrame.NoFrame,
        "conversation inner scroll area should not draw an extra frame over the shell",
    )
    assert_ok(
        not window.conversation_panel._scroll_area.viewport().autoFillBackground(),
        "conversation scroll viewport should not paint an opaque fallback background",
    )

    # Inject local payload
    inject_payload(window, app, {
        "request_id": "req-local-1",
        "status": "completed",
        "request_text": "plain local request",
        "response_text": "local answer",
        "route": {"mode": "LOCAL", "reason": "factual_query", "confidence": "0.92"},
        "outcome": {"outcome_code": "answered", "final_mode": "LOCAL", "trust_class": "local", "augmented_provider_used": "none"},
    })

    assert_ok(labels["Last Request Provider"].text() == "none", "status should show none for local request")
    assert_ok(labels["Last Request Paid"].text() == "no", "status should show no paid provider for local request")

    # Inject forced augmented payload (OpenAI)
    inject_payload(window, app, {
        "request_id": "req-augmented-1",
        "status": "completed",
        "request_text": "plain local request with no external context",
        "response_text": "augmented answer",
        "route": {"mode": "AUGMENTED", "reason": "forced_direct", "confidence": "0.85"},
        "outcome": {
            "outcome_code": "augmented_answer",
            "final_mode": "AUGMENTED",
            "trust_class": "unverified",
            "augmented_provider_used": "openai",
            "augmented_provider_call_reason": "direct",
            "augmented_paid_provider_invoked": "true",
            "augmented_direct_request": "1",
        },
    })

    assert_ok(labels["Last Request Provider"].text() == "openai", "status should show openai as last request provider")
    assert_ok(labels["Last Request Paid"].text() == "yes", "status should show paid invocation for direct openai request")
    request_labels = window.status_panel._request_detail_labels
    assert_ok(
        request_labels["Augmented Direct Request"].text() == "1",
        "request diagnostics should show one-shot direct override metadata",
    )
    assert_ok(
        labels["Session Augmented Calls"].text() == "1",
        f"forced direct submit should increment augmented counter once, got={labels['Session Augmented Calls'].text()!r}",
    )

    # Inject Wikipedia fallback payload
    inject_payload(window, app, {
        "request_id": "req-wiki-1",
        "status": "completed",
        "request_text": "need internet context for this question",
        "response_text": "wikipedia answer",
        "route": {"mode": "AUGMENTED", "reason": "fallback", "confidence": "0.78"},
        "outcome": {
            "outcome_code": "augmented_fallback_answer",
            "final_mode": "AUGMENTED",
            "trust_class": "evidence_backed",
            "augmented_provider_used": "wikipedia",
            "augmented_provider_call_reason": "fallback",
            "augmented_paid_provider_invoked": "false",
            "augmented_direct_request": "0",
        },
    })

    assert_ok(labels["Last Request Provider"].text() == "wikipedia", "status should show wikipedia as last request provider")
    assert_ok(labels["Last Request Paid"].text() == "no", "status should show unpaid last request fallback")
    assert_ok(
        labels["Session Augmented Calls"].text() == "2",
        f"fallback submit should increment augmented counter, got={labels['Session Augmented Calls'].text()!r}",
    )
    assert_ok(labels["Session Paid Augmented Calls"].text() == "1", "only paid openai call should increment paid counter")

    # Advanced view layout assertions
    window._handle_interface_level_selected("advanced")
    app.processEvents()
    window.resize(980, 360)
    app.processEvents()
    assert_ok(window.height() <= 620, "window should be allowed to reduce below the previous oversized minimum height")
    scroll_area = window.conversation_panel._scroll_area
    assert_ok(scroll_area is not None, "conversation panel should expose a scroll area for short windows")
    assert_ok(
        scroll_area.verticalScrollBar().maximum() > 0,
        "reduced height should enable scrolling so bottom controls remain reachable",
    )
    assert_ok(
        not window.conversation_panel._force_augmented_once_checkbox.isHidden(),
        "force-augmented-once control should be available in advanced view",
    )
    checkbox = window.conversation_panel._force_augmented_once_checkbox
    top_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().topLeft())
    bottom_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().bottomLeft())
    assert_ok(
        top_left.y() > scroll_area.viewport().height() or bottom_left.y() > scroll_area.viewport().height(),
        "before scrolling, reduced-height layout should place the bottom control below viewport",
    )
    scroll_area.ensureWidgetVisible(window.conversation_panel._force_augmented_once_checkbox)
    app.processEvents()
    top_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().topLeft())
    bottom_left = checkbox.mapTo(scroll_area.viewport(), checkbox.rect().bottomLeft())
    assert_ok(
        top_left.y() >= 0 and bottom_left.y() <= scroll_area.viewport().height(),
        "after scrolling, force-augmented-once control should be visible in viewport",
    )

    # Event log visibility in advanced view
    window.resize(1460, 900)
    app.processEvents()
    assert_ok(not window.event_log_panel.isHidden(), "advanced level should expose event log")
    assert_ok(
        window.event_log_panel.height() < window.conversation_panel.height(),
        "event log should remain smaller than the main conversation work area",
    )

    window.close()
    window.deleteLater()
    app.processEvents()
    print("AUGMENTED_CONTROLS_OFFSCREEN_OK")
    return 0


def inject_payload(window, app, payload: dict) -> None:
    """Inject a request payload directly into the UI (v8: bypass subprocess submit)."""
    import json
    from app.services.state_store import REQUEST_HISTORY_FILE
    REQUEST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REQUEST_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    window._reload_request_history()
    window._update_session_augmented_counters_from_payload(payload)
    window.refresh_runtime_state()
    app.processEvents()


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
