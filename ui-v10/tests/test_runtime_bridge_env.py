#!/usr/bin/env python3
"""Regression tests: _apply_state_to_env maps control toggles to process env."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def _bridge_with_state(state_overrides: dict[str, object]) -> "object":
    """Build a RuntimeBridge against a temp state file; return (bridge, env)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.runtime_bridge import RuntimeBridge

    state = {
        "schema_version": 1,
        "profile": "lucy-v11",
        "mode": "auto",
        "conversation": "off",
        "memory": "off",
        "evidence": "off",
        "voice": "off",
        "augmentation_policy": "disabled",
        "augmented_provider": "wikipedia",
        "model": "local-lucy-llama31",
        "gemma4_smart_routing": "off",
        "self_analysis_mode": "off",
        "learner": "off",
        "approval_required": False,
        "status": "ready",
        "last_updated": "2026-01-01T00:00:00Z",
    }
    state.update(state_overrides)

    tmpdir = tempfile.TemporaryDirectory()
    state_dir = Path(tmpdir.name) / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "current_state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")

    env = {"LUCY_RUNTIME_STATE_FILE": str(state_file)}
    with patch.dict(os.environ, env):
        bridge = RuntimeBridge()
        bridge._apply_state_to_env()
        captured = dict(os.environ)
    tmpdir.cleanup()
    return captured


def test_learner_toggle_on_sets_lucy_auto_learn():
    """HMI learner toggle 'on' must enable auto-learning via LUCY_AUTO_LEARN=1."""
    env = _bridge_with_state({"learner": "on"})
    assert env.get("LUCY_AUTO_LEARN") == "1"


def test_learner_toggle_off_clears_lucy_auto_learn():
    """HMI learner toggle 'off' must force LUCY_AUTO_LEARN=0 even if env had 1."""
    with patch.dict(os.environ, {"LUCY_AUTO_LEARN": "1"}):
        env = _bridge_with_state({"learner": "off"})
    assert env.get("LUCY_AUTO_LEARN") == "0"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
