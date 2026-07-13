#!/usr/bin/env python3
"""Regression tests for Gemma 4 smart-routing state persistence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_CONTROL = REPO_ROOT / "tools" / "runtime_control.py"


@pytest.fixture
def isolated_runtime(tmp_path: Path):
    """Provide an isolated runtime namespace and clean environment."""
    namespace = tmp_path / "runtime"
    env = os.environ.copy()
    env["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "0"
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(namespace)
    env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(REPO_ROOT)
    env["LUCY_GEMMA4_SMART_ROUTING"] = "0"
    return namespace, env


def _run_cli(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_CONTROL), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def _state_file(namespace: Path) -> Path:
    return namespace / "state" / "current_state.json"


def _ensure_state(namespace: Path, env: dict[str, str]) -> None:
    _run_cli(env, "ensure-state")


def test_direct_update_gemma4_smart_routing_field(isolated_runtime):
    """update_state_field must accept the gemma4_smart_routing field."""
    namespace, env = isolated_runtime
    sys.path.insert(0, str(REPO_ROOT / "tools"))
    from runtime_control import update_state_field

    _ensure_state(namespace, env)
    state_file = _state_file(namespace)
    result = update_state_field(state_file, "gemma4_smart_routing", "on")
    assert result.value == "on"
    assert result.state["gemma4_smart_routing"] == "on"


def test_cli_set_gemma4_smart_routing(isolated_runtime):
    """CLI must expose set-gemma4-smart-routing and persist the value."""
    namespace, env = isolated_runtime
    _ensure_state(namespace, env)

    result = _run_cli(env, "set-gemma4-smart-routing", "--value", "on")
    assert result.returncode == 0, result.stderr

    state = json.loads(_state_file(namespace).read_text(encoding="utf-8"))
    assert state["gemma4_smart_routing"] == "on"

    result = _run_cli(env, "set-gemma4-smart-routing", "--value", "off")
    assert result.returncode == 0, result.stderr

    state = json.loads(_state_file(namespace).read_text(encoding="utf-8"))
    assert state["gemma4_smart_routing"] == "off"


def test_print_env_includes_gemma4_smart_routing(isolated_runtime):
    """print-env must export LUCY_GEMMA4_SMART_ROUTING."""
    namespace, env = isolated_runtime
    _ensure_state(namespace, env)
    _run_cli(env, "set-gemma4-smart-routing", "--value", "on")

    result = _run_cli(env, "print-env")
    assert result.returncode == 0, result.stderr
    assert "LUCY_GEMMA4_SMART_ROUTING=1" in result.stdout

    _run_cli(env, "set-gemma4-smart-routing", "--value", "off")
    result = _run_cli(env, "print-env")
    assert result.returncode == 0, result.stderr
    assert "LUCY_GEMMA4_SMART_ROUTING=0" in result.stdout


def test_cli_set_model_accepts_gemma4(isolated_runtime):
    """CLI set-model must accept gemma4:12b-it-qat."""
    namespace, env = isolated_runtime
    _ensure_state(namespace, env)

    result = _run_cli(env, "set-model", "--value", "gemma4:12b-it-qat")
    assert result.returncode == 0, result.stderr

    state = json.loads(_state_file(namespace).read_text(encoding="utf-8"))
    assert state["model"] == "gemma4:12b-it-qat"
    assert state["active_model"] == "gemma4:12b-it-qat"
