#!/usr/bin/env python3
"""Regression tests for Gemma 4 model identity prompt."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from router_py.local_answer import LocalAnswer, LocalAnswerConfig, _MODEL_IDENTITIES, get_self_knowledge


def test_gemma4_has_model_identity():
    """Gemma 4 must have its own identity entry instead of falling back to Llama 3."""
    assert "gemma4:12b-it-qat" in _MODEL_IDENTITIES, (
        "gemma4:12b-it-qat missing from _MODEL_IDENTITIES"
    )
    identity = get_self_knowledge("gemma4:12b-it-qat")
    assert "gemma4" in identity.lower(), f"Gemma 4 identity should mention gemma4, got: {identity}"
    assert "llama3.1" not in identity.lower(), (
        f"Gemma 4 identity should not mention llama3.1, got: {identity}"
    )


class _FakeUrlopenResponse:
    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_urlopen(calls: list[dict], req, timeout=None):
    """Record the request and return a plausible Ollama response."""
    body = req.data
    parsed = json.loads(body.decode("utf-8")) if body else {}
    calls.append({"url": req.full_url, "body": parsed})
    # /api/ps returns empty; /api/generate returns a minimal response.
    if req.full_url.endswith("/api/ps"):
        return _FakeUrlopenResponse(b'{"models": []}')
    return _FakeUrlopenResponse(json.dumps({"response": "mocked response"}).encode("utf-8"))


@pytest.mark.asyncio
async def test_gemma4_word_count_gets_thinking_headroom():
    """A 500-word creative request on Gemma 4 must reserve thinking-model tokens."""
    config = LocalAnswerConfig()
    config.model = "local-lucy-gemma4"
    config.num_predict_long = 1536
    config.creative_max_tokens = 4096
    answer = LocalAnswer(config)

    # The generation profile turns 500 words into 2000 visible-output tokens.
    profile, num_predict, _ = answer._set_generation_profile("LOCAL", "CHAT", "Write a 500 word story about a dog.")
    assert profile == "chat_long"
    assert num_predict == 2000

    calls: list[dict] = []
    with patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: _fake_urlopen(calls, req, timeout)):
        text, _duration = await answer._call_ollama("prompt", num_predict, route_mode="LOCAL")

    generate_calls = [c for c in calls if c["url"].endswith("/api/generate")]
    assert len(generate_calls) == 1
    sent_num_predict = generate_calls[0]["body"]["options"]["num_predict"]
    # Gemma 4 is a thinking model (multiplier 4), so the payload must reserve
    # headroom for internal reasoning without truncating the visible 500 words.
    assert sent_num_predict == 8000, f"expected 8000 tokens for Gemma 4, got {sent_num_predict}"


@pytest.mark.asyncio
async def test_llama_word_count_keeps_visible_budget():
    """A non-thinking model should not inflate the word-count token budget."""
    config = LocalAnswerConfig()
    config.model = "local-lucy-llama31"
    config.num_predict_long = 1536
    config.creative_max_tokens = 4096
    answer = LocalAnswer(config)

    profile, num_predict, _ = answer._set_generation_profile("LOCAL", "CHAT", "Write a 500 word story about a dog.")
    assert profile == "chat_long"
    assert num_predict == 2000

    calls: list[dict] = []
    with patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: _fake_urlopen(calls, req, timeout)):
        text, _duration = await answer._call_ollama("prompt", num_predict, route_mode="LOCAL")

    generate_calls = [c for c in calls if c["url"].endswith("/api/generate")]
    assert len(generate_calls) == 1
    sent_num_predict = generate_calls[0]["body"]["options"]["num_predict"]
    # Llama 3.1 is not a thinking model, so the visible budget stays as requested.
    assert sent_num_predict == 2000, f"expected 2000 tokens for Llama, got {sent_num_predict}"


def test_continue_requests_are_treated_as_followups():
    """Continuation prompts must keep prior conversation context."""
    answer = LocalAnswer(LocalAnswerConfig())
    assert answer._context_followup_requested("That was truncated, please continue")
    assert answer._context_followup_requested("please continue the story")
    assert answer._context_followup_requested("continue from where you left off")
    assert answer._context_followup_requested("finish it")
    assert answer._context_followup_requested("you got cut off")
    assert answer._context_followup_requested("Repeat this story")
    assert answer._context_followup_requested("say that again")
    assert answer._context_followup_requested("what did you just say")
