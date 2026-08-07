#!/usr/bin/env python3
"""Regression tests for execution-engine session-memory handling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from unittest.mock import patch

from memory.memory_service import MemoryService
from router_py.execution_engine import ExecutionEngine
from router_py.execution_engine.helpers import (
    _is_memory_or_followup_query,
    _load_session_memory_context_with_telemetry,
)
from router_py.request_types import ClassificationResult, RoutingDecision


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


def test_continuation_reserves_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(tmp_path / "mem.db"))
    monkeypatch.setenv("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "100")
    monkeypatch.setattr(
        "memory.memory_service.LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", 100
    )
    from router_py.execution_engine.helpers import _load_session_memory_context_with_telemetry

    text, telemetry = _load_session_memory_context_with_telemetry(
        session_id="s1", query="continue", max_chars=400
    )
    assert telemetry["continuation_reserve_chars"] == 100
    assert telemetry["memory_max_chars_used"] <= 300


def test_continuation_reserve_when_last_turn_truncated(monkeypatch, tmp_path):
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(tmp_path / "mem.db"))
    monkeypatch.setenv("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "100")
    monkeypatch.setattr(
        "memory.memory_service.LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", 100
    )
    from router_py.execution_engine.helpers import _load_session_memory_context_with_telemetry

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn(
        session_id="s1",
        role="assistant",
        text="This answer was cut off...",
        full_text="This answer was cut off mid-sentence and has more content hidden.",
        truncated=True,
    )

    text, telemetry = _load_session_memory_context_with_telemetry(
        session_id="s1", query="what is the weather today", max_chars=400
    )
    assert telemetry["continuation_reserve_chars"] > 0
    assert telemetry["memory_max_chars_used"] <= 300
    assert "This answer was cut off" in text


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


class TestExecutionEngineMemoryPrompt:
    """Execution engine prepends session memory with the authoritative preamble."""

    @pytest.mark.asyncio
    async def test_augmented_api_path_uses_authoritative_memory_preamble(self, monkeypatch):
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")

        engine = ExecutionEngine()
        intent = ClassificationResult(
            intent="question",
            intent_family="general",
        )
        route = RoutingDecision(
            route="AUGMENTED",
            mode="FORCED",
            intent_family="general",
            confidence=1.0,
            provider="openai",
            provider_usage_class="paid",
            evidence_mode="",
            evidence_reason="",
        )
        context = {"question": "what did I say earlier?", "request_id": "req-1"}

        captured_prompt = None

        async def fake_call_api(provider: str, prompt: str, ctx: dict):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "mocked response"

        with patch.object(
            engine,
            "_fetch_evidence",
            return_value={
                "context": "Some background.",
                "title": "Test",
                "url": "http://example.com",
                "provider": "test",
            },
        ):
            with patch(
                "router_py.execution_engine.is_evidence_relevant",
                return_value=True,
            ):
                with patch(
                    "router_py.execution_engine._load_session_memory_context_with_telemetry",
                    return_value=("User: hello\nAssistant: hi", {}),
                ):
                    with patch.object(
                        engine,
                        "_call_api_provider_async",
                        side_effect=fake_call_api,
                    ):
                        await engine.execute_async(intent, route, context)

        assert captured_prompt is not None
        assert "authoritative" in captured_prompt
        assert "look at the history first" in captured_prompt
        assert captured_prompt.find("authoritative") < captured_prompt.find("Question:")
