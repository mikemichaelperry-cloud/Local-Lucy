#!/usr/bin/env python3
"""Pytest-discovered smoke tests for the standalone HMI offscreen scripts.

The CI pipeline previously invoked these scripts one-by-one in a shell block.
This module makes them first-class pytest tests so they are discovered,
reported, and counted alongside the rest of the suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "ui-v10" / "tests"
PYTHON = sys.executable

_OFFSCREEN_SCRIPTS = [
    "test_decision_trace_offscreen.py",
    "test_news_headline_punctuation_offscreen.py",
    "test_optional_missing_vs_corruption_offscreen.py",
    "test_scroll_preservation_offscreen.py",
    "test_voice_ptt_pause_removed_offscreen.py",
    "test_augmented_controls_offscreen.py",
]


def _namespace_root() -> Path:
    return Path(
        os.environ.get(
            "LUCY_RUNTIME_NAMESPACE_ROOT",
            Path.home() / ".codex-api-home" / "lucy" / "runtime-v10",
        )
    )


def _cleanup_state() -> None:
    """Remove mutable runtime files before each offscreen script, matching CI."""
    ns = _namespace_root()
    for name in ("request_history.jsonl", "last_request_result.json"):
        path = ns / "state" / name
        if path.exists():
            path.unlink()


@pytest.mark.parametrize("script_name", _OFFSCREEN_SCRIPTS)
def test_offscreen_script(script_name: str, tmp_path: Path) -> None:
    """Run a standalone offscreen script and assert it prints its OK marker."""
    script_path = TESTS_DIR / script_name
    assert script_path.exists(), f"missing offscreen script: {script_path}"

    _cleanup_state()

    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["OLLAMA_KEEP_ALIVE"] = "0"
    # The standalone scripts manage their own runtime namespace and set
    # contract mode internally. Do not leak a state directory from the
    # parent pytest process, or strict validation will fail.
    env.pop("LUCY_UI_STATE_DIR", None)

    result = subprocess.run(
        [PYTHON, str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO_ROOT),
    )

    stem = Path(script_name).stem
    if stem.startswith("test_"):
        stem = stem[5:]
    marker = f"{stem.upper()}_OK"
    stdout = result.stdout or ""
    stderr = result.stderr or ""

    assert result.returncode == 0, (
        f"{script_name} exited {result.returncode}\n"
        f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
    assert marker in stdout, (
        f"{script_name} did not print {marker}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    )
