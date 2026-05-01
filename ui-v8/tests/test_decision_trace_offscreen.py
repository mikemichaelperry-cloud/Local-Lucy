#!/usr/bin/env python3
"""Offscreen test for decision trace display (v8 direct payload injection)."""
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
    from app.main_window import OperatorConsoleWindow
    from PySide6.QtWidgets import QApplication

    # Clean history and last-result files for isolated test
    REQUEST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REQUEST_HISTORY_FILE.write_text("", encoding="utf-8")
    REQUEST_RESULT_FILE.write_text("", encoding="utf-8")

    app = QApplication([])
    window = OperatorConsoleWindow()
    window.resize(960, 720)
    window.show()
    app.processEvents()

    summary_button = window.conversation_panel._decision_trace_summary_button
    assert_ok(not summary_button.isEnabled(), "decision trace summary should start disabled without request metadata")
    assert_ok(window._decision_trace_panel.isHidden(), "decision trace drawer should start collapsed")

    # Inject payload directly (v8: bypass subprocess submit)
    payload = {
        "request_id": "req-trace-test",
        "status": "completed",
        "request_text": "show me the latest AI lab policy updates",
        "response_text": "synthetic decision trace response",
        "route": {
            "selected_route": "AUGMENTED",
            "mode": "AUGMENTED",
            "intent_class": "policy_ai",
            "reason": "offscreen decision trace test",
            "confidence": "0.87",
            "query": "show me the latest AI lab policy updates",
            "utc": "2026-03-25T00:00:00Z",
        },
        "outcome": {
            "requested_mode": "AUGMENTED",
            "final_mode": "AUGMENTED",
            "evidence_mode": "validated",
            "trust_class": "unverified_with_extended_context_for_operator_review",
            "outcome_code": "augmented_answer",
            "action_hint": "none",
            "fallback_used": "false",
            "augmented_provider": "openai",
            "augmented_provider_used": "openai",
            "augmented_provider_call_reason": "direct",
            "augmented_provider_status": "available",
            "augmented_provider_selection_reason": "synthesis/explanation task",
            "augmented_provider_selection_query": "explain entropy in plain english with engineering intuition",
            "augmented_provider_selection_rule": "plain_explanation",
            "augmented_direct_request": "0",
            "augmented_answer_contract": {
                "answer": "synthetic decision trace response",
                "verification_status": "unverified",
                "estimated_confidence_pct": 34,
                "estimated_confidence_band": "Low",
                "estimated_confidence_label": "34% (Low, estimated)",
                "source_basis": ["augmented_provider_openai", "local_model_background"],
                "provider_status": "available",
                "notes": "No allowlisted evidence confirmed this directly.",
            },
        },
        "control_state": {
            "mode": "online",
            "memory": "on",
            "evidence": "validated",
            "voice": "off",
            "augmentation_policy": "direct_allowed",
            "augmented_provider": "openai",
        },
        "completed_at": "2026-03-25T00:00:00Z",
    }

    # Write payload to history file and reload (v8: bypass submit, test UI rendering only)
    REQUEST_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(REQUEST_HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
    window._reload_request_history()
    window.refresh_runtime_state()
    app.processEvents()

    summary_text = summary_button.text()
    assert_ok(summary_button.isEnabled(), "decision trace summary should enable after request metadata arrives")
    assert_ok("AUGMENTED -> OPENAI" in summary_text, f"summary should show requested/effective path, got={summary_text!r}")
    assert_ok(
        "trust=unverified_with_extended_context_for_operator_review" in summary_text,
        f"summary should expose trust class, got={summary_text!r}",
    )
    assert_ok(
        "confidence=0.87" in summary_text,
        f"summary should expose route confidence, got={summary_text!r}",
    )
    assert_ok(
        summary_button.toolTip() == summary_text,
        "summary tooltip should expose the full unclipped decision trace summary",
    )
    assert_ok(window._decision_trace_panel.isHidden(), "decision trace drawer should remain collapsed until activated")

    summary_button.click()
    app.processEvents()

    assert_ok(not window._decision_trace_panel.isHidden(), "activating summary should reveal decision trace drawer")
    trace_text = window._decision_trace_view.toPlainText()
    assert_ok("Requested Mode: AUGMENTED" in trace_text, "drawer should render requested mode")
    assert_ok("Effective Mode: AUGMENTED" in trace_text, "drawer should render effective mode")
    assert_ok("Requested Route:" not in trace_text, "drawer should omit requested route when payload does not provide one")
    assert_ok("Selected Route: AUGMENTED" in trace_text, "drawer should render selected route")
    assert_ok("Intent Classification: policy_ai" in trace_text, "drawer should render intent classification")
    assert_ok("Evidence Mode: validated" in trace_text, "drawer should render evidence mode")
    assert_ok("Augmented Provider: openai" in trace_text, "drawer should render augmented provider")
    assert_ok(
        "Provider Selection Reason: synthesis/explanation task" in trace_text,
        "drawer should render provider selection reason when available",
    )
    assert_ok(
        "Provider Selection Query: explain entropy in plain english with engineering intuition" in trace_text,
        "drawer should render normalized provider selection query when available",
    )
    assert_ok(
        "Provider Selection Rule: plain_explanation" in trace_text,
        "drawer should render provider selection rule when available",
    )
    assert_ok(
        "Verification Status: unverified" in trace_text,
        "drawer should render verification status when an augmented contract is present",
    )
    assert_ok(
        "Estimated Confidence: 34% (Low, estimated)" in trace_text,
        "drawer should render estimated confidence when an augmented contract is present",
    )
    assert_ok(
        "Source Basis: augmented_provider_openai, local_model_background" in trace_text,
        "drawer should render source basis when an augmented contract is present",
    )
    assert_ok(
        "Trust Class: unverified_with_extended_context_for_operator_review" in trace_text,
        "drawer should render trust class",
    )
    assert_ok("Outcome Code: augmented_answer" in trace_text, "drawer should render outcome code")
    assert_ok("Route Confidence: 0.87" in trace_text, "drawer should render route confidence")
    assert_ok("Reason: offscreen decision trace test" in trace_text, "drawer should render available reason text")

    window.close()
    window.deleteLater()
    app.processEvents()
    print("DECISION_TRACE_OFFSCREEN_OK")
    return 0


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
