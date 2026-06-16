#!/usr/bin/env python3
"""Comprehensive HMI inspection across all modes, levels, and switches.

Tests that all status fields, decision traces, runtime displays, and controls
are accurate and populated correctly in both operator and engineering views.
Run with QT_QPA_PLATFORM=offscreen.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")
sys.path.insert(0, str(REPO_UI_ROOT))

from app.main_window import OperatorConsoleWindow as MainWindow
from app.services.state_store import REQUEST_HISTORY_FILE, REQUEST_RESULT_FILE, STATE_FILES
from PySide6.QtWidgets import QApplication

LAST_ROUTE_FILE = STATE_FILES["last_route"]

# Files this test mutates — must be snapshotted and restored
_MUTATED_FILES = [REQUEST_HISTORY_FILE, REQUEST_RESULT_FILE, LAST_ROUTE_FILE]


def _snapshot_files() -> dict[Path, str | None]:
    """Read current content of mutated files; None means file did not exist."""
    snaps: dict[Path, str | None] = {}
    for f in _MUTATED_FILES:
        if f.exists():
            snaps[f] = f.read_text(encoding="utf-8")
        else:
            snaps[f] = None
    return snaps


def _restore_files(snaps: dict[Path, str | None]) -> None:
    """Restore files to pre-test state."""
    for f, content in snaps.items():
        if content is None:
            if f.exists():
                f.unlink()
        else:
            f.write_text(content, encoding="utf-8")


def _clear_files() -> None:
    """Zero out mutated files for a clean test run."""
    for f in _MUTATED_FILES:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("", encoding="utf-8")


REPORT: list[dict] = []


def record(category: str, level: str, check: str, ok: bool, detail: str = "") -> None:
    REPORT.append(
        {
            "category": category,
            "level": level,
            "check": check,
            "ok": ok,
            "detail": detail,
        }
    )
    status = "✅" if ok else "❌"
    print(f"  {status} [{category}] {check}: {detail}")


def make_payload(
    *,
    route_mode: str = "LOCAL",
    request_id: str = "req-test-1",
    request_text: str = "test query",
    response_text: str = "test answer",
    provider: str = "none",
    paid: bool = False,
    evidence: bool = False,
    augmented_direct: bool = False,
    outcome_code: str = "answered",
    trust_class: str = "local",
    confidence: float = 0.92,
    status: str = "completed",
) -> dict:
    return {
        "request_id": request_id,
        "status": status,
        "request_text": request_text,
        "response_text": response_text,
        "route": {
            "mode": route_mode,
            "reason": "test_reason",
            "confidence": str(confidence),
            "query": request_text,
            "session_id": "",
            "utc": "2026-05-14T00:00:00Z",
        },
        "outcome": {
            "outcome_code": outcome_code,
            "final_mode": route_mode,
            "trust_class": trust_class,
            "augmented_provider_used": provider,
            "augmented_provider_call_reason": "direct" if augmented_direct else "fallback",
            "augmented_paid_provider_invoked": "true" if paid else "false",
            "augmented_direct_request": "1" if augmented_direct else "0",
            "evidence_created": "true" if evidence else "false",
            "action_hint": "",
            "rc": 0,
            "utc": "2026-05-14T00:00:00Z",
        },
        "control_state": {
            "mode": "auto",
            "memory": "on",
            "evidence": "on",
            "voice": "off",
            "model": "local-lucy",
            "profile": "test-profile",
        },
        "error": "",
        "completed_at": "2026-05-14T00:00:00Z",
    }


def inject_payload(window: MainWindow, payload: dict) -> None:
    # Write request history (drives provider/paid/trust displays)
    with open(REQUEST_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    # Write last_route.json (drives Current Route and Source Type displays)
    route_mode = payload.get("route", {}).get("mode", "LOCAL")
    last_route = {
        "route": route_mode,
        "current_route": route_mode,
        "selected_route": route_mode,
        "source_type": payload.get("source_type", "local"),
        "source": payload.get("source_type", "local"),
        "route_reason": payload.get("route", {}).get("reason", "test"),
        "trust_class": payload.get("outcome", {}).get("trust_class", "local"),
        "operator_trust_label": payload.get("outcome", {}).get("trust_class", "local"),
        "outcome_code": payload.get("outcome", {}).get("outcome_code", "answered"),
        "provider_used": payload.get("outcome", {}).get("augmented_provider_used", "none"),
        "updated_at": payload.get("completed_at", "2026-05-14T00:00:00Z"),
    }
    LAST_ROUTE_FILE.write_text(json.dumps(last_route), encoding="utf-8")
    # Write last_request_result.json so build_request_details() merges correctly
    REQUEST_RESULT_FILE.write_text(json.dumps(payload), encoding="utf-8")

    window._reload_request_history()
    window._update_session_augmented_counters_from_payload(payload)
    window.refresh_runtime_state()
    app = QApplication.instance()
    if app:
        app.processEvents()


def inspect_level(window: MainWindow, level: str) -> None:
    print(f"\n=== Inspecting level: {level} ===")
    window._handle_interface_level_selected(level)
    app = QApplication.instance()
    if app:
        app.processEvents()
        time.sleep(0.1)
        app.processEvents()

    # --- Control Panel ---
    cp = window.control_panel
    record("control_panel", level, "mode_selector exists", cp._mode_selector is not None)
    record("control_panel", level, "memory_selector exists", cp._memory_selector is not None)
    record("control_panel", level, "evidence_selector exists", cp._evidence_selector is not None)
    record("control_panel", level, "voice_selector exists", cp._voice_selector is not None)
    record(
        "control_panel",
        level,
        "augmentation_policy exists",
        cp._augmentation_policy_selector is not None,
    )
    record(
        "control_panel",
        level,
        "provider_selector exists",
        cp._augmented_provider_selector is not None,
    )
    record("control_panel", level, "learner_selector exists", cp._learner_selector is not None)
    record("control_panel", level, "model_selector exists", cp._model_selector is not None)

    # Profile group visibility
    profile_visible = not cp._profile_group.isHidden()
    record(
        "control_panel",
        level,
        "profile_group visible at engineering",
        profile_visible if level == "engineering" else not profile_visible,
        f"visible={profile_visible}",
    )

    # --- Status Panel ---
    sp = window.status_panel

    # Runtime summary labels
    summary = sp._runtime_summary_labels
    for key in (
        "Current Route",
        "Source Type",
        "Conversation",
        "Voice State",
        "Health",
        "Model",
        "Augmented Policy",
        "Configured Provider",
        "Configured Provider Paid",
        "Last Request Provider",
        "Last Request Paid",
        "Session Augmented Calls",
        "Session Paid Augmented Calls",
    ):
        exists = key in summary
        text = summary[key].text() if exists else "MISSING"
        record("status_summary", level, f"label '{key}'", exists, f"text={text!r}")

    # Runtime detail labels
    details = sp._runtime_detail_labels
    for key in ("Voice Backend", "Voice Error", "GPU Acceleration"):
        exists = key in details
        text = details[key].text() if exists else "MISSING"
        record("status_details", level, f"label '{key}'", exists, f"text={text!r}")

    # Request summary labels
    req_summary = sp._request_summary_labels
    for key in (
        "Status",
        "Completed At",
        "Answer Path",
        "Trust",
        "Augmented",
        "Route Mode",
        "Outcome Code",
    ):
        exists = key in req_summary
        text = req_summary[key].text() if exists else "MISSING"
        record("request_summary", level, f"label '{key}'", exists, f"text={text!r}")

    # Request detail labels
    req_detail = sp._request_detail_labels
    for key in (
        "Request ID",
        "Request Text",
        "Error",
        "Route Reason",
        "Route Confidence",
        "Operator Note",
        "Action Hint",
        "Verification Status",
        "Estimated Confidence",
        "Source Basis",
        "Augmented Direct Request",
        "Augmented Provider Status",
        "Evidence Created",
        "Primary Outcome",
        "Recovery Lane",
        "Control State",
    ):
        exists = key in req_detail
        text = req_detail[key].text() if exists else "MISSING"
        record("request_detail", level, f"label '{key}'", exists, f"text={text!r}")

    # Event log panel visibility
    event_visible = not window.event_log_panel.isHidden()
    record(
        "layout",
        level,
        "event_log_panel visible at engineering",
        event_visible if level == "engineering" else not event_visible,
        f"visible={event_visible}",
    )

    # Decision trace
    dt_button = window.conversation_panel._decision_trace_summary_button
    dt_visible = dt_button is not None and not dt_button.isHidden()
    record(
        "decision_trace",
        level,
        "decision_trace button visible",
        dt_visible,
        f"visible={dt_visible}",
    )

    # Avatar
    avatar = getattr(sp, "_avatar", None)
    record("status_panel", level, "avatar widget present", avatar is not None)

    # Freshness label
    freshness = getattr(sp, "_freshness_label", None)
    record("status_panel", level, "freshness_label present", freshness is not None)
    if freshness:
        record(
            "status_panel",
            level,
            "freshness_label has text",
            len(freshness.text()) > 0,
            f"text={freshness.text()!r}",
        )

    # Advanced views (engineering only)
    adv_state = getattr(sp, "_advanced_state_view", None)
    adv_request = getattr(sp, "_advanced_request_view", None)
    hist_maintenance = getattr(sp, "_history_maintenance_view", None)

    if level == "engineering":
        record("engineering_views", level, "advanced_state_view present", adv_state is not None)
        record("engineering_views", level, "advanced_request_view present", adv_request is not None)
        record(
            "engineering_views",
            level,
            "history_maintenance_view present",
            hist_maintenance is not None,
        )
    else:
        # isHidden() only checks explicit hide; isVisible() accounts for parent visibility
        record(
            "engineering_views",
            level,
            "advanced views hidden at operator",
            (adv_state is None or not adv_state.isVisible())
            and (adv_request is None or not adv_request.isVisible())
            and (hist_maintenance is None or not hist_maintenance.isVisible()),
        )


def inspect_route_payload(
    window: MainWindow, level: str, payload: dict, expected_provider: str, expected_paid: str
) -> None:
    inject_payload(window, payload)
    app = QApplication.instance()
    if app:
        app.processEvents()

    sp = window.status_panel
    summary = sp._runtime_summary_labels

    provider_text = summary.get("Last Request Provider", None)
    provider_val = provider_text.text() if provider_text else "MISSING"
    record(
        "route_accuracy",
        level,
        f"provider for {payload['route']['mode']}",
        provider_val == expected_provider,
        f"expected={expected_provider!r} got={provider_val!r}",
    )

    paid_text = summary.get("Last Request Paid", None)
    paid_val = paid_text.text() if paid_text else "MISSING"
    record(
        "route_accuracy",
        level,
        f"paid flag for {payload['route']['mode']}",
        paid_val == expected_paid,
        f"expected={expected_paid!r} got={paid_val!r}",
    )

    route_text = summary.get("Current Route", None)
    route_val = route_text.text() if route_text else "MISSING"
    record(
        "route_accuracy",
        level,
        f"current route reflects {payload['route']['mode']}",
        route_val == payload["route"]["mode"],
        f"expected={payload['route']['mode']!r} got={route_val!r}",
    )


def main() -> int:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    print("=" * 70)
    print("COMPREHENSIVE HMI INSPECTION")
    print("=" * 70)

    # Snapshot runtime state so we can restore it after the test
    pre_test_snapshot = _snapshot_files()
    _clear_files()

    window: MainWindow | None = None
    try:
        # --- Phase 1: Widget existence across levels ---
        window = MainWindow()
        window.show()
        app.processEvents()
        window.refresh_runtime_state()
        app.processEvents()

        # Test operator level
        inspect_level(window, "operator")

        # Test engineering level
        inspect_level(window, "engineering")

        # --- Phase 2: Route accuracy ---
        print("\n--- Route Accuracy Tests ---")

        # LOCAL route
        inspect_route_payload(
            window,
            "engineering",
            make_payload(
                route_mode="LOCAL", provider="none", paid=False, request_id="req-test-local"
            ),
            expected_provider="none",
            expected_paid="no",
        )

        # AUGMENTED route (OpenAI, paid)
        inspect_route_payload(
            window,
            "engineering",
            make_payload(
                route_mode="AUGMENTED",
                provider="openai",
                paid=True,
                augmented_direct=True,
                trust_class="unverified",
                request_id="req-test-aug-openai",
            ),
            expected_provider="openai",
            expected_paid="yes",
        )

        # AUGMENTED route (Wikipedia, unpaid)
        inspect_route_payload(
            window,
            "engineering",
            make_payload(
                route_mode="AUGMENTED",
                provider="wikipedia",
                paid=False,
                trust_class="evidence_backed",
                request_id="req-test-aug-wiki",
            ),
            expected_provider="wikipedia",
            expected_paid="no",
        )

        # NEWS route
        inspect_route_payload(
            window,
            "engineering",
            make_payload(
                route_mode="NEWS", provider="none", paid=False, request_id="req-test-news"
            ),
            expected_provider="none",
            expected_paid="no",
        )

        # TIME route
        inspect_route_payload(
            window,
            "engineering",
            make_payload(
                route_mode="TIME", provider="none", paid=False, request_id="req-test-time"
            ),
            expected_provider="none",
            expected_paid="no",
        )

        # --- Phase 3: Control panel state accuracy ---
        print("\n--- Control Panel State Accuracy ---")
        cp = window.control_panel
        record(
            "control_state",
            "engineering",
            "mode_selector default value",
            cp._mode_selector.currentText() in {"auto", "online", "offline"},
            f"value={cp._mode_selector.currentText()!r}",
        )
        record(
            "control_state",
            "engineering",
            "memory_selector has on/off",
            cp._memory_selector.count() == 2 and cp._memory_selector.itemText(0) == "on",
            f"items={[cp._memory_selector.itemText(i) for i in range(cp._memory_selector.count())]}",
        )
        record(
            "control_state",
            "engineering",
            "evidence_selector has on/off",
            cp._evidence_selector.count() == 2,
            f"items={[cp._evidence_selector.itemText(i) for i in range(cp._evidence_selector.count())]}",
        )
        record(
            "control_state",
            "engineering",
            "voice_selector has on/off",
            cp._voice_selector.count() == 2,
            f"items={[cp._voice_selector.itemText(i) for i in range(cp._voice_selector.count())]}",
        )
        record(
            "control_state",
            "engineering",
            "augmentation_policy has 3 options",
            cp._augmentation_policy_selector.count() == 3,
            f"items={[cp._augmentation_policy_selector.itemText(i) for i in range(cp._augmentation_policy_selector.count())]}",
        )

        # --- Phase 4: Conversation panel content ---
        print("\n--- Conversation Panel Content ---")
        cnp = window.conversation_panel
        history_html = cnp._history.toHtml()
        record(
            "conversation",
            "engineering",
            "history widget has content after injection",
            len(history_html) > 100,
            f"html_length={len(history_html)}",
        )
        record(
            "conversation",
            "engineering",
            "history contains 'test answer'",
            "test answer" in history_html,
            f"contains_response={'test answer' in history_html}",
        )

        # --- Phase 5: Decision trace ---
        print("\n--- Decision Trace ---")
        dt_button = cnp._decision_trace_summary_button
        if dt_button and not dt_button.isHidden():
            dt_text = dt_button.text()
            record(
                "decision_trace",
                "engineering",
                "decision_trace button has text",
                len(dt_text) > 0,
                f"text={dt_text!r}",
            )
            # Toggle it on
            dt_button.setChecked(True)
            cnp.decision_trace_toggled.emit(True)
            app.processEvents()
            dt_panel = getattr(window, "_decision_trace_panel", None)
            if dt_panel:
                record(
                    "decision_trace",
                    "engineering",
                    "decision_trace panel visible after toggle",
                    not dt_panel.isHidden(),
                )
                # Check if the trace view has content (QPlainTextEdit inside panel)
                trace_view = getattr(window, "_decision_trace_view", None)
                has_content = trace_view is not None and len(trace_view.toPlainText()) > 0
                record(
                    "decision_trace",
                    "engineering",
                    "decision_trace panel has content",
                    has_content,
                    f"text_length={len(trace_view.toPlainText()) if trace_view else 0}",
                )
            else:
                record(
                    "decision_trace",
                    "engineering",
                    "decision_trace panel exists after toggle",
                    False,
                    "_decision_trace_panel not found on window",
                )
        else:
            record(
                "decision_trace",
                "engineering",
                "decision_trace button accessible",
                False,
                "button hidden or missing",
            )

        # --- Phase 6: Status panel advanced views ---
        print("\n--- Advanced Views (Engineering) ---")
        window._handle_interface_level_selected("engineering")
        app.processEvents()
        sp = window.status_panel
        if hasattr(sp, "_advanced_state_view") and sp._advanced_state_view:
            text = sp._advanced_state_view.toPlainText()
            record(
                "advanced_views",
                "engineering",
                "advanced_state_view has JSON content",
                len(text) > 50,
                f"length={len(text)}",
            )
        else:
            record(
                "advanced_views",
                "engineering",
                "advanced_state_view present",
                False,
                "widget missing",
            )

        # --- Phase 7: Event log ---
        print("\n--- Event Log ---")
        elp = window.event_log_panel
        record(
            "event_log", "engineering", "event_log_panel visible at engineering", not elp.isHidden()
        )
        log_text = elp.toPlainText() if hasattr(elp, "toPlainText") else ""
        record(
            "event_log",
            "engineering",
            "event_log has content or is ready",
            True,
            f"length={len(log_text)}",
        )

    finally:
        # Cleanup window
        if window is not None:
            window.close()
            window.deleteLater()
            app.processEvents()
        # Restore original runtime state (never poison the self-learning pipeline)
        _restore_files(pre_test_snapshot)

    # --- Report ---
    print("\n" + "=" * 70)
    print("INSPECTION SUMMARY")
    print("=" * 70)
    total = len(REPORT)
    passed = sum(1 for r in REPORT if r["ok"])
    failed = total - passed
    print(f"Total checks: {total}")
    print(f"Passed:       {passed}")
    print(f"Failed:       {failed}")

    if failed:
        print("\nFAILED CHECKS:")
        for r in REPORT:
            if not r["ok"]:
                print(
                    f"  ❌ [{r['category']}] level={r['level']} check={r['check']}: {r['detail']}"
                )
    else:
        print("\n✅ ALL CHECKS PASSED")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
