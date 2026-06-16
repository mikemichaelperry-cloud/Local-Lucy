#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

REPO_UI_ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

sys.path.insert(0, str(REPO_UI_ROOT))

from app.panels.status_panel import StatusPanel


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_trusted_fallback_warning_texts(qapp):
    panel = StatusPanel()
    payload = {
        "route": {"mode": "EVIDENCE"},
        "outcome": {
            "final_mode": "EVIDENCE",
            "trust_class": "trusted",
            "outcome_code": "answered",
            "ANSWER_BASIS": "trusted_domain_fallback",
            "LIVE_FETCH_STATUS": "failed",
            "CONFIDENCE": "limited",
            "DEGRADED_REASON": "search_no_results",
        },
    }

    assert panel._answer_path_text(payload) == "Trusted fallback (limited)"
    assert panel._operator_note_text(payload) == (
        "Limited confidence: live trusted fetch failed; showing fallback from trusted domains (search_no_results)."
    )


def test_old_payload_without_trusted_metadata_still_parses(qapp):
    panel = StatusPanel()
    payload = {
        "route": {"mode": "EVIDENCE"},
        "outcome": {
            "final_mode": "EVIDENCE",
            "trust_class": "trusted",
            "outcome_code": "answered",
        },
    }

    assert panel._answer_path_text(payload) == "Evidence-backed answer"
    assert panel._operator_note_text(payload) == "Answer is grounded in current evidence."
