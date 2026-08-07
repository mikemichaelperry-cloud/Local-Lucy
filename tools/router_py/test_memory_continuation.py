import asyncio

import pytest


def _make_answer(model="local-lucy-llama31:latest", cache_enabled=False):
    from router_py.local_answer_core.config import LocalAnswerConfig
    from router_py.local_answer_core.engine import LocalAnswer

    return LocalAnswer(LocalAnswerConfig(model=model, cache_enabled=cache_enabled))


def test_truncated_turn_stores_full_text(tmp_path):
    from memory.memory_service import MemoryService

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn(
        "s1",
        "assistant",
        "short visible",
        full_text="long full text that was truncated",
        truncated=True,
    )
    rows = svc.get_recent_turns("s1", limit=1)
    assert rows[0]["text"] == "short visible"
    assert rows[0]["full_text"] == "long full text that was truncated"
    assert rows[0]["truncated"] == 1


def test_truncated_flag_without_differing_full_text(tmp_path):
    from memory.memory_service import MemoryService

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn("s1", "assistant", "same text", truncated=True)
    rows = svc.get_recent_turns("s1", limit=1)
    assert rows[0]["text"] == "same text"
    assert rows[0]["full_text"] is None
    assert rows[0]["truncated"] == 1


def test_continuation_prompt_includes_instruction():
    ans = _make_answer()
    try:
        prompt = ans._build_prompt(
            "continue",
            session_memory="previous: ...",
            generation_profile="chat",
            budget_instruction="",
            conversation_mode_active=False,
            conversation_system_block=False,
            is_continuation=True,
        )
        assert "cut off" in prompt
        assert "Continue from exactly where it left off" in prompt
    finally:
        asyncio.run(ans.close())


def test_truncation_marker_is_detected_and_stripped():
    from router_py.local_answer_core.engine import _TRUNCATION_MARKER

    ans = _make_answer()
    try:
        memory = f"User: hello\n\nAssistant: {_TRUNCATION_MARKER} cut off mid-sentence"
        assert ans._last_assistant_turn_was_truncated(memory) is True
        stripped = ans._strip_truncation_marker(memory)
        assert _TRUNCATION_MARKER not in stripped
        assert "Assistant: cut off mid-sentence" in stripped
    finally:
        asyncio.run(ans.close())


def test_last_assistant_turn_truncated_text_heuristic():
    ans = _make_answer()
    try:
        assert (
            ans._last_assistant_turn_was_truncated(
                "User: hi\n\nAssistant: I was cut off"
            )
            is True
        )
        assert (
            ans._last_assistant_turn_was_truncated(
                "User: hi\n\nAssistant: I am complete."
            )
            is False
        )
        assert ans._last_assistant_turn_was_truncated("") is False
    finally:
        asyncio.run(ans.close())


async def test_prior_truncation_injects_continuation_instruction(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(tmp_path / "mem.db"))
    monkeypatch.setenv("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "200")
    monkeypatch.setattr(
        "router_py.local_answer_core.engine.filter_memory_context",
        lambda _q, mem, _threshold=0.3: mem,
    )

    from memory.memory_service import MemoryService
    from router_py.execution_engine.helpers import (
        _load_session_memory_context_with_telemetry,
    )

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn(
        "s1",
        "assistant",
        "This answer was cut off...",
        full_text="This answer was cut off mid-sentence and has more content hidden.",
        truncated=True,
    )

    text, _telemetry = _load_session_memory_context_with_telemetry(
        session_id="s1", query="what is the weather today", max_chars=400
    )
    assert "This answer was cut off" in text

    ans = _make_answer()
    captured = {}

    async def fake_call(prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return "ok", 0, {"truncated": False}

    ans._call_ollama = fake_call
    try:
        await ans.generate_answer("what is the weather today", session_memory=text)
        assert "cut off" in captured["prompt"]
        assert "Continue from exactly where it left off" in captured["prompt"]
        assert "[PREVIOUS_ANSWER_TRUNCATED]" not in captured["prompt"]
    finally:
        await ans.close()


async def test_tell_me_more_after_complete_is_elaboration(monkeypatch, tmp_path):
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(tmp_path / "mem.db"))
    monkeypatch.setenv("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "200")
    monkeypatch.setattr(
        "router_py.local_answer_core.engine.filter_memory_context",
        lambda _q, mem, _threshold=0.3: mem,
    )

    from memory.memory_service import MemoryService
    from router_py.execution_engine.helpers import (
        _load_session_memory_context_with_telemetry,
    )

    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn(
        "s1",
        "assistant",
        "This is a complete answer.",
        truncated=False,
    )

    text, _telemetry = _load_session_memory_context_with_telemetry(
        session_id="s1", query="tell me more", max_chars=400
    )
    assert "This is a complete answer" in text

    ans = _make_answer()
    captured = {}

    async def fake_call(prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return "ok", 0, {"truncated": False}

    ans._call_ollama = fake_call
    try:
        await ans.generate_answer("tell me more", session_memory=text)
        assert "cut off" not in captured["prompt"]
        assert "Continue from exactly where it left off" not in captured["prompt"]
    finally:
        await ans.close()
