#!/usr/bin/env python3
"""Tests that model stage scripts enforce single-model residency at start/end."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

# Make the stage scripts and router_py importable.
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "ui-v10"))
sys.path.insert(0, str(ROOT))

STAGE_SCRIPTS = [
    "stage_08_gemma_smoke.py",
    "stage_10_llama_smoke.py",
    "stage_09_gemma_scenario_suite.py",
    "stage_11_llama_scenario_suite.py",
    "stage_13_model_switch.py",
    "stage_16_hmi_soak.py",
]

STAGE_MODULES = [name[:-3] for name in STAGE_SCRIPTS]


def _import_stage(module_name: str) -> ModuleType:
    """Import a stage module, returning a fresh copy when possible."""
    full_name = f"tools.router_py.{module_name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    return importlib.import_module(full_name)


def _make_router_outcome(**overrides):
    """Return a minimal RouterOutcome-like object."""
    defaults = {
        "status": "completed",
        "route": "LOCAL",
        "outcome_code": "ok",
        "response_text": "test response",
        "error_message": "",
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


@pytest.mark.parametrize("script_name", STAGE_SCRIPTS)
def test_stage_script_imports_residency_helpers(script_name: str) -> None:
    """Each stage script must import the residency helpers from router_py.model_residency."""
    source = (HERE / script_name).read_text()
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "router_py.model_residency":
            imported_names.update(alias.name for alias in node.names)

    assert "assert_single_local_lucy_model" in imported_names, f"{script_name} missing assert import"
    assert "get_local_lucy_loaded_models" in imported_names, f"{script_name} missing getter import"


@pytest.mark.parametrize("script_name", STAGE_SCRIPTS)
def test_stage_script_calls_start_and_end_assertions(script_name: str) -> None:
    """Each stage script's main() must call the residency helpers at start and end."""
    source = (HERE / script_name).read_text()
    tree = ast.parse(source)

    calls: list[tuple[str, ...]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                continue
            args: list[object] = []
            for arg in node.args:
                try:
                    args.append(ast.literal_eval(arg))
                except ValueError:
                    break
            else:
                calls.append((name, *args))

    assert ("assert_single_local_lucy_model", "start") in calls, f"{script_name} missing start assertion"
    assert ("assert_single_local_lucy_model", "end") in calls, f"{script_name} missing end assertion"


class TestStage08RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_08_gemma_smoke")

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_gemma_exclusively") as mock_load, \
             patch.object(mod, "_set_state_model_to_gemma"), \
             patch.object(mod, "_run_hmi_surface_request", return_value={
                 "status": "ok",
                 "payload": {"route": {"mode": "LOCAL"}},
                 "stdout": "",
                 "stderr": "",
             }), \
             patch("router_py.main.execute_plan_python", return_value=_make_router_outcome()), \
             patch.object(mod, "unload_all_lucy_models"):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


class TestStage10RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_10_llama_smoke")

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_llama_exclusively") as mock_load, \
             patch.object(mod, "_set_state_model_to_llama"), \
             patch.object(mod, "_run_hmi_surface_request", return_value={
                 "status": "ok",
                 "payload": {"route": {"mode": "LOCAL"}},
                 "stdout": "",
                 "stderr": "",
             }), \
             patch("router_py.main.execute_plan_python", return_value=_make_router_outcome()), \
             patch.object(mod, "unload_all_lucy_models"):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


class TestStage09RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_09_gemma_scenario_suite")

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_gemma_exclusively"), \
             patch.object(mod, "_set_state_model_to_gemma"), \
             patch.object(mod, "_load_suite", return_value=[]), \
             patch.object(mod, "unload_all_lucy_models"):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


class TestStage11RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_11_llama_scenario_suite")

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_llama_exclusively"), \
             patch.object(mod, "_set_state_model_to_llama"), \
             patch.object(mod, "_load_suite", return_value=[]), \
             patch.object(mod, "unload_all_lucy_models"):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


class TestStage13RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_13_model_switch")

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_model_exclusively"), \
             patch.object(mod, "_set_state_model"), \
             patch.object(mod, "_run_step", return_value={
                 "passed": True,
                 "route": "LOCAL",
                 "loaded_models": [],
                 "response_text": "test",
             }), \
             patch.object(mod, "_run_memory_continuation_step", return_value={
                 "passed": True,
                 "mentions_oscar": True,
                 "continues_narrative": True,
                 "notes": [],
             }), \
             patch.object(mod, "unload_all_lucy_models"):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


class TestStage16RuntimeResidency:
    def test_calls_residency_helpers_at_runtime(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
        monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

        mod = _import_stage("stage_16_hmi_soak")

        fake_bridge = MagicMock()
        fake_bridge.run_action.return_value = MagicMock(
            status="ok", stdout="answer", stderr="", payload={"route": {"mode": "LOCAL"}}
        )

        with patch.object(mod, "assert_single_local_lucy_model") as mock_assert, \
             patch.object(mod, "get_local_lucy_loaded_models", return_value=[]) as mock_get, \
             patch.object(mod, "_load_model_exclusively"), \
             patch.object(mod, "_set_state_model"), \
             patch.object(mod, "_run_hmi_request", return_value={
                 "status": "ok",
                 "route": "LOCAL",
                 "stdout_len": 10,
                 "stderr": "",
             }), \
             patch.object(mod, "unload_all_lucy_models"), \
             patch("app.services.runtime_bridge.RuntimeBridge", return_value=fake_bridge):
            rc = mod.main()

        assert rc == 0
        mock_assert.assert_any_call("start")
        mock_assert.assert_any_call("end")
        mock_get.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
