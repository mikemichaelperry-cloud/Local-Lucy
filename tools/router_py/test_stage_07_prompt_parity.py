#!/usr/bin/env python3
"""STAGE_07 prompt construction and semantic model parity tests."""

from __future__ import annotations

import pytest

from router_py.local_answer import LocalAnswer, LocalAnswerConfig
from router_py.local_answer_core import engine as engine_module


@pytest.fixture(autouse=True)
def _disable_heartbeat(monkeypatch):
    """Do not spawn heartbeat threads during prompt-building tests."""
    monkeypatch.setattr(engine_module, "_start_heartbeat", lambda model: None)


def _build_prompt_for_model(model: str, query: str, **kwargs) -> str:
    """Build a prompt for the given backend model name."""
    config = LocalAnswerConfig()
    config.model = model
    answer = LocalAnswer(config)
    return answer._build_prompt(
        query=query,
        session_memory=kwargs.get("session_memory", ""),
        generation_profile=kwargs.get("generation_profile", "chat"),
        budget_instruction=kwargs.get("budget_instruction", ""),
        conversation_mode_active=kwargs.get("conversation_mode_active", False),
        conversation_system_block=kwargs.get("conversation_system_block", False),
        augmented_context=kwargs.get("augmented_context", ""),
    )


def _strip_identity_block(prompt: str) -> str:
    """Return the prompt with the model-specific identity paragraph removed."""
    lines = prompt.splitlines()
    filtered: list[str] = []
    skip_paragraph = False
    for line in lines:
        if "llama3.1:8b" in line or "gemma4:12b-it-qat" in line:
            skip_paragraph = True
            continue
        if skip_paragraph and line.strip() == "":
            skip_paragraph = False
            continue
        if not skip_paragraph:
            filtered.append(line)
    return "\n".join(filtered)


def test_s07_pp_001_prompts_differ_only_by_identity():
    """S07-PP-001: Same query produces identical prompts except identity line."""
    query = "What is the capital of France?"
    llama_prompt = _build_prompt_for_model("local-lucy-llama31", query)
    gemma_prompt = _build_prompt_for_model("local-lucy-gemma4", query)

    # Identity-specific text must be present in the correct prompt only.
    assert "llama3.1:8b" in llama_prompt
    assert "~8B parameters, 4096-token context" in llama_prompt
    assert "gemma4:12b-it-qat" not in llama_prompt

    assert "gemma4:12b-it-qat" in gemma_prompt
    assert "~12B parameters, 128k-token context" in gemma_prompt
    assert "llama3.1:8b" not in gemma_prompt

    # Everything else must be identical.
    assert _strip_identity_block(llama_prompt) == _strip_identity_block(gemma_prompt)


def test_s07_pp_002_memory_block_parity():
    """Session memory block is identical for Llama and Gemma."""
    query = "What did I ask earlier?"
    memory = "- User previously asked about the weather in Paris."
    llama_prompt = _build_prompt_for_model(
        "local-lucy-llama31", query, session_memory=memory
    )
    gemma_prompt = _build_prompt_for_model(
        "local-lucy-gemma4", query, session_memory=memory
    )
    assert _strip_identity_block(llama_prompt) == _strip_identity_block(gemma_prompt)
    assert memory in llama_prompt
    assert memory in gemma_prompt


def test_s07_pp_003_augmented_context_parity():
    """Augmented context block is identical for Llama and Gemma."""
    query = "Summarize the context."
    context = "DuckDuckGo result: Paris is the capital of France."
    llama_prompt = _build_prompt_for_model(
        "local-lucy-llama31", query, augmented_context=context
    )
    gemma_prompt = _build_prompt_for_model(
        "local-lucy-gemma4", query, augmented_context=context
    )
    assert _strip_identity_block(llama_prompt) == _strip_identity_block(gemma_prompt)
    assert context in llama_prompt
    assert context in gemma_prompt


def test_s07_pp_004_conversation_mode_parity():
    """Conversation mode directive is identical for Llama and Gemma."""
    query = "Should I buy an electric car?"
    llama_prompt = _build_prompt_for_model(
        "local-lucy-llama31",
        query,
        conversation_mode_active=True,
        conversation_system_block=True,
    )
    gemma_prompt = _build_prompt_for_model(
        "local-lucy-gemma4",
        query,
        conversation_mode_active=True,
        conversation_system_block=True,
    )
    assert "[CONVERSATION_MODE: sharp]" in llama_prompt
    assert "[CONVERSATION_MODE: sharp]" in gemma_prompt
    assert _strip_identity_block(llama_prompt) == _strip_identity_block(gemma_prompt)


def test_s07_pp_005_thinking_model_detection():
    """Gemma is detected as a thinking model; Llama is not."""
    llama = LocalAnswer(LocalAnswerConfig(model="local-lucy-llama31"))
    gemma = LocalAnswer(LocalAnswerConfig(model="local-lucy-gemma4"))

    assert llama._is_thinking_model() is False
    assert gemma._is_thinking_model() is True
