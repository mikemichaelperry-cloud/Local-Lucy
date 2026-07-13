#!/usr/bin/env python3
"""Tests for the automatic local-model selector."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.model_selector import (
    _query_bucket,
    generate_ab_pair,
    is_auto_model,
    select_local_model,
    select_model,
)
from router_py.request_types import RoutingDecision


def test_simple_query_defaults_to_general_model():
    model = select_local_model(
        "What is the capital of France?",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "local-lucy-llama31"


def test_memory_query_defaults_to_llama31():
    model = select_local_model(
        "What did we discuss earlier?",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "local-lucy-llama31"


def test_coding_query_defaults_to_llama31():
    model = select_local_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "local-lucy-llama31"


def test_reasoning_query_defaults_to_llama31():
    model = select_local_model(
        "Explain your reasoning for rejecting the null hypothesis.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "local-lucy-llama31"


def test_pinned_model_is_respected():
    model = select_local_model(
        "What is the capital of France?",
        context={"LUCY_LOCAL_MODEL": "gemma4:12b-it-qat"},
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "gemma4:12b-it-qat"


def test_autonomous_mode_overrides_pin():
    model = select_local_model(
        "What is the capital of France?",
        context={
            "LUCY_LOCAL_MODEL": "gemma4:12b-it-qat",
            "LUCY_AUTONOMOUS_MODEL_SELECTION": "true",
        },
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
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
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "local-lucy-llama31"


def test_query_bucket_classification():
    assert _query_bucket("What did I say earlier?") == "memory"
    assert _query_bucket("Debug this Python script.") == "coding"
    assert _query_bucket("Prove that sqrt(2) is irrational.") == "reasoning"
    assert _query_bucket("hi") == "fast"
    assert _query_bucket("What is the capital of France?") == "general"


def test_deep_thought_query_selects_heavy_model():
    model = select_local_model(
        "Provide a deep analysis of the philosophical implications of free will.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model == "gemma4:12b-it-qat"


def test_deep_thought_bucket_classification():
    assert (
        _query_bucket("Give me an exhaustive review of quantum interpretations.") == "deep_thought"
    )
    assert _query_bucket("Synthesize the literature on consciousness.") == "deep_thought"
    assert (
        _query_bucket("Compare and contrast in depth the major ethical frameworks.")
        == "deep_thought"
    )


def test_base_name_matches_latest_tag():
    """A base model name should resolve to the installed :latest variant."""
    model = select_local_model(
        "What is the capital of France?",
        available=["local-lucy-llama31:latest", "gemma4:12b-it-qat:latest"],
    )
    assert model == "local-lucy-llama31:latest"


def test_coding_base_name_matches_latest_tag():
    model = select_local_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31:latest", "gemma4:12b-it-qat:latest"],
    )
    assert model == "local-lucy-llama31:latest"


def test_select_model_general_defaults_to_llama31():
    rec = select_model(
        "What is the capital of France?",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert rec["recommended"] == "local-lucy-llama31"
    assert rec["competing"] == "gemma4:12b-it-qat"
    assert rec["confidence"] > 0.7
    assert "latency_budget_ms" in rec


def test_select_model_factual_route_uses_llama31():
    for route in ("NEWS", "TIME", "WEATHER", "FINANCE", "EVIDENCE"):
        rec = select_model(
            "test query",
            route=route,
            available=["local-lucy-llama31", "gemma4:12b-it-qat"],
        )
        assert rec["recommended"] == "local-lucy-llama31", route
        assert "factual" in rec["reason"].lower() or route in rec["reason"], rec["reason"]


def test_select_model_coding_uses_llama31():
    rec = select_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert rec["recommended"] == "local-lucy-llama31"
    assert rec["competing"] == "gemma4:12b-it-qat"


def test_select_model_coding_falls_back_without_gemma4():
    rec = select_model(
        "Write a Python function to reverse a string.",
        available=["local-lucy-llama31"],
    )
    assert rec["recommended"] == "local-lucy-llama31"
    assert "llama" in rec["reason"].lower()


def test_select_model_deep_thought_prefers_gemma4():
    rec = select_model(
        "Provide a deep analysis of free will.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert rec["recommended"] == "gemma4:12b-it-qat"


def test_select_model_deep_thought_recommends_gemma4_regardless_of_available():
    rec = select_model(
        "Provide a deep analysis of free will.",
        available=["local-lucy-llama31"],
    )
    assert rec["recommended"] == "gemma4:12b-it-qat"


def test_select_model_memory_uses_llama31():
    rec = select_model(
        "What did I say earlier?",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert rec["recommended"] == "local-lucy-llama31"


def test_select_model_creative_uses_llama31():
    rec = select_model(
        "Write a short poem about autumn.",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert rec["recommended"] == "local-lucy-llama31"


def test_select_model_qwen_not_recommended_for_factual_classes():
    """Removed Qwen tags must not be recommended for factual/current/evidence classes."""
    queries = [
        ("What is the latest news?", "NEWS"),
        ("What time is it in Tokyo?", "TIME"),
        ("Will it rain today?", "WEATHER"),
        ("What is Apple's stock price?", "FINANCE"),
        ("What are the symptoms of flu?", "EVIDENCE"),
    ]
    available = ["local-lucy-llama31", "gemma4:12b-it-qat"]
    for query, route in queries:
        rec = select_model(query, route=route, available=available)
        assert rec["recommended"] == "local-lucy-llama31", (query, route, rec)
        assert "qwen" not in rec["recommended"].lower()


def test_is_auto_model_detects_auto():
    assert is_auto_model("auto") is True
    assert is_auto_model("Auto (Lucy chooses per query)") is True
    assert is_auto_model("AUTO") is True
    assert is_auto_model(None) is True
    assert is_auto_model("local-lucy") is False
    assert is_auto_model("") is True


def test_generate_ab_pair_returns_recommended_and_competing():
    model_a, model_b = generate_ab_pair(
        "What is the capital of France?",
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert model_a == "local-lucy-llama31"
    assert model_b == "gemma4:12b-it-qat"
    assert model_a != model_b
