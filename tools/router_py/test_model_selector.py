#!/usr/bin/env python3
"""Tests for the automatic local-model selector."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.model_selector import _query_bucket, select_local_model
from router_py.request_types import RoutingDecision


def test_simple_query_defaults_to_general_model():
    model = select_local_model(
        "What is the capital of France?",
        available=["local-lucy-llama31", "local-lucy-qwen3"],
    )
    assert model == "local-lucy-llama31"


def test_memory_query_selects_memory_model():
    model = select_local_model(
        "What did we discuss earlier?",
        available=["local-lucy-llama31", "local-lucy-memory"],
    )
    assert model == "local-lucy-memory"


def test_coding_query_selects_coding_model():
    model = select_local_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31", "local-lucy-qwen3"],
    )
    assert model == "local-lucy-qwen3"


def test_reasoning_query_selects_reasoning_model():
    model = select_local_model(
        "Explain your reasoning for rejecting the null hypothesis.",
        available=["local-lucy-llama31", "local-lucy-stable"],
    )
    assert model == "local-lucy-stable"


def test_pinned_model_is_respected():
    model = select_local_model(
        "What is the capital of France?",
        context={"LUCY_LOCAL_MODEL": "local-lucy-mistral"},
        available=["local-lucy-llama31", "local-lucy-mistral"],
    )
    assert model == "local-lucy-mistral"


def test_autonomous_mode_overrides_pin():
    model = select_local_model(
        "What is the capital of France?",
        context={
            "LUCY_LOCAL_MODEL": "local-lucy-qwen3",
            "LUCY_AUTONOMOUS_MODEL_SELECTION": "true",
        },
        available=["local-lucy-llama31", "local-lucy-qwen3"],
    )
    assert model == "local-lucy-llama31"


def test_persona_variant_selected_when_available():
    model = select_local_model(
        "What is the capital of France?",
        context={"persona": "michael"},
        available=["local-lucy-llama31", "local-lucy-llama31-michael"],
    )
    assert model == "local-lucy-llama31-michael"


def test_unavailable_bucket_falls_back():
    model = select_local_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31"],
    )
    assert model == "local-lucy-llama31"


def test_route_intent_family_influences_selection():
    route = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="synthesis_explanation",
        confidence=0.8,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )
    model = select_local_model(
        "Tell me about climate change.",
        route=route,
        available=["local-lucy-llama31", "local-lucy-stable"],
    )
    assert model == "local-lucy-stable"


def test_query_bucket_classification():
    assert _query_bucket("What did I say earlier?") == "memory"
    assert _query_bucket("Debug this Python script.") == "coding"
    assert _query_bucket("Prove that sqrt(2) is irrational.") == "reasoning"
    assert _query_bucket("hi") == "fast"
    assert _query_bucket("What is the capital of France?") == "general"


def test_deep_thought_query_selects_heavy_model():
    model = select_local_model(
        "Provide a deep analysis of the philosophical implications of free will.",
        available=["local-lucy-llama31", "qwen3:30b"],
    )
    assert model == "qwen3:30b"


def test_deep_thought_bucket_classification():
    assert _query_bucket("Give me an exhaustive review of quantum interpretations.") == "deep_thought"
    assert _query_bucket("Synthesize the literature on consciousness.") == "deep_thought"
    assert (
        _query_bucket("Compare and contrast in depth the major ethical frameworks.")
        == "deep_thought"
    )


def test_base_name_matches_latest_tag():
    """A base model name should resolve to the installed :latest variant."""
    model = select_local_model(
        "What is the capital of France?",
        available=["local-lucy-llama31:latest", "local-lucy-qwen3:latest"],
    )
    assert model == "local-lucy-llama31:latest"


def test_coding_base_name_matches_latest_tag():
    model = select_local_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31:latest", "local-lucy-qwen3:latest"],
    )
    assert model == "local-lucy-qwen3:latest"
