#!/usr/bin/env python3
"""Regression tests for execution-engine session-memory handling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from router_py.execution_engine.helpers import (
    _is_memory_or_followup_query,
    _load_session_memory_context_with_telemetry,
)


class TestExecutionEngineMemoryBudget:
    """Execution engine passes a 2400-char budget, overriding the service default."""

    def test_helper_passes_2400_char_budget(self, monkeypatch):
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        calls = {}

        def fake_assemble(*, max_chars, **kwargs):
            calls["max_chars"] = max_chars
            return "context", {}

        monkeypatch.setattr(
            "memory.memory_service.assemble_context_with_telemetry", fake_assemble
        )
        _load_session_memory_context_with_telemetry(query="hello", mode="local")
        assert calls.get("max_chars") == 2400


class TestMemoryOrFollowupQuery:
    """Detect queries that explicitly refer to the prior conversation."""

    @pytest.mark.parametrize(
        "query",
        [
            "Read my last answer please",
            "read my last answer",
            "Look at the context",
            "What did I say earlier?",
            "What did you say about that?",
            "And if she had two glasses of wine?",
            "What about the previous topic?",
            "Tell me more about that",
            "That was truncated, please continue",
            "please continue the story",
            "continue from where you left off",
            "finish it",
            "finish the story",
            "keep going",
            "you got cut off",
            "Repeat this story",
            "say that again",
            "what did you just say",
        ],
    )
    def test_detects_memory_and_followup_queries(self, query: str) -> None:
        assert _is_memory_or_followup_query(query) is True

    @pytest.mark.parametrize(
        "query",
        [
            "What is the capital of France?",
            "How does a transistor work?",
            "Tell me a joke",
            "What's the weather like?",
        ],
    )
    def test_allows_unrelated_queries(self, query: str) -> None:
        assert _is_memory_or_followup_query(query) is False
