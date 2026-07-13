"""Regression tests ensuring Local Lucy's active model universe is locked
to the allowed set.

Deviations from the original task brief:
- The brief described a RoutingDecision signature that did not match the
  actual codebase. These tests use the real router_py.request_types.RoutingDecision
  fields (route, mode, intent_family, confidence, provider,
  provider_usage_class, evidence_mode).
- The brief assumed direct argparse internals for reading runtime_control's
  model choices. Because the CLI uses subparsers, the test navigates
  parser._subparsers._actions and the set-model sub-parser's _actions to
  extract the allowed values, rather than inspecting top-level arguments.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make tools/router_py importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from router_py import model_selector
from router_py.request_types import RoutingDecision


def test_hmi_model_labels_limited_to_allowed_set():
    # Import the control panel from the HMI tree.
    ui_root = Path(__file__).resolve().parents[2] / "ui-v10"
    sys.path.insert(0, str(ui_root))
    from app.panels.control_panel import ControlPanel

    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert set(ControlPanel._MODEL_LABELS.keys()) == allowed


def test_runtime_control_model_choices_limited_to_allowed_set():
    # Import runtime_control from the tools tree.
    tools_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(tools_root))
    import importlib

    runtime_control = importlib.import_module("runtime_control")
    parser = runtime_control.build_parser()
    subparsers_action = [
        a
        for a in parser._subparsers._actions
        if hasattr(a, "choices") and isinstance(a.choices, dict)
    ][0]
    set_model_parser = subparsers_action.choices["set-model"]
    value_action = [
        a for a in set_model_parser._actions if hasattr(a, "choices") and a.dest == "value"
    ][0]
    choices = value_action.choices
    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert set(choices) == allowed


def _make_route(route_name: str, intent_family: str = "") -> RoutingDecision:
    return RoutingDecision(
        route=route_name,
        mode="AUTO",
        intent_family=intent_family,
        confidence=0.8,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )


@pytest.mark.parametrize(
    "query,route_name,intent_family",
    [
        ("What is the capital of France?", "AUGMENTED", "factual"),
        ("Write a Python function", "LOCAL", ""),
        ("What did we discuss earlier?", "LOCAL", ""),
        ("Solve 2+2", "LOCAL", ""),
        ("Explain step by step", "LOCAL", ""),
        ("Give me a deep analysis of climate change", "LOCAL", ""),
    ],
)
def test_select_model_never_recommends_removed_tag(query, route_name, intent_family):
    route = _make_route(route_name, intent_family=intent_family)
    result = model_selector.select_model(
        query,
        route=route,
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert result["recommended"] in allowed
    assert result["competing"] in allowed


def test_select_local_model_respects_pinned_allowed_model():
    result = model_selector.select_local_model(
        "hello",
        context={"local_model": "gemma4:12b-it-qat"},
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert result == "gemma4:12b-it-qat"
