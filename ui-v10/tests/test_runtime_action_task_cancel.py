#!/usr/bin/env python3
"""Regression tests for RuntimeActionTask cancellation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_UI_ROOT))

from app.services.runtime_bridge import CommandResult, RuntimeActionTask


class FakeBridge:
    def run_action(self, action: str, requested_value: str, context=None) -> CommandResult:
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status="ok",
            returncode=0,
            stdout="done",
            stderr="",
            timed_out=False,
            payload=None,
        )


def test_runtime_action_task_has_cancel_method() -> None:
    task = RuntimeActionTask(FakeBridge(), "test_action", "value")
    assert hasattr(task, "cancel")
    assert callable(task.cancel)


def test_runtime_action_task_cancel_before_run_is_cancelled() -> None:
    task = RuntimeActionTask(FakeBridge(), "test_action", "value")
    task.cancel()
    assert task.is_cancelled()
