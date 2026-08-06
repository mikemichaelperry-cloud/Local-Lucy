#!/usr/bin/env python3
"""Unit tests for response formatting, validation, and limit handling.

Covers STAGE_12 output-parsing and boundary concerns without touching Ollama.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router_py.response_formatter import (
    build_augmented_prompt,
    guard_normalize,
    is_evidence_style_text,
    is_local_generation_failure_output,
    render_chat_fast_from_raw,
    validate_response,
)


class TestValidateResponse:
    def test_empty_response_returns_fallback(self) -> None:
        assert "couldn't generate" in validate_response("").lower()

    def test_whitespace_response_returns_fallback(self) -> None:
        assert "couldn't generate" in validate_response("   \n\t  ").lower()

    def test_valid_response_preserved(self) -> None:
        assert validate_response("  Hello world  ") == "Hello world"

    def test_connection_failure_replaced(self) -> None:
        assert "trouble connecting" in validate_response("connection refused").lower()

    def test_ollama_running_failure_replaced(self) -> None:
        assert "trouble connecting" in validate_response("ollama is not running").lower()


class TestIsLocalGenerationFailureOutput:
    def test_detects_connection_refused(self) -> None:
        assert is_local_generation_failure_output("connection refused")

    def test_detects_ollama_not_running(self) -> None:
        assert is_local_generation_failure_output("Could not connect to Ollama")

    def test_ignores_identity_mention_of_ollama(self) -> None:
        assert not is_local_generation_failure_output("I run via Ollama on your machine")

    def test_ignores_normal_answer(self) -> None:
        assert not is_local_generation_failure_output("Paris is the capital of France.")


class TestRenderChatFastFromRaw:
    def test_strips_validation_markers(self) -> None:
        raw = "BEGIN_VALIDATED\nHello world\nEND_VALIDATED"
        assert render_chat_fast_from_raw(raw) == "Hello world"

    def test_strips_error_prefixes(self) -> None:
        assert render_chat_fast_from_raw("Error: something") == "something"
        assert render_chat_fast_from_raw("Sorry, I cannot answer that.") == "answer that."

    def test_collapses_lines(self) -> None:
        raw = "Line one\nLine two\n\nLine three"
        assert render_chat_fast_from_raw(raw) == "Line one Line two Line three"


class TestTruncateEvidenceAndPromptLimits:
    def test_short_evidence_not_truncated(self) -> None:
        text = "This is a short evidence sentence."
        assert build_augmented_prompt("Q?", {"content": text}, None).startswith("Question: Q?")

    def test_long_evidence_truncated_at_sentence_boundary(self) -> None:
        # First sentence is > 600 chars so its period crosses the 50% threshold
        # and the truncator chooses the sentence boundary over a word boundary.
        first = "Word " * 160 + "is the end of the first sentence. "
        text = first + "word " * 2000 + "Final sentence."
        prompt = build_augmented_prompt("Q?", {"content": text}, None)
        assert "(Context truncated for length.)" in prompt
        # Extract the Background Context section.
        context_section = prompt.split("Background Context:", 1)[1].split("(Context truncated", 1)[0].strip()
        assert context_section.endswith("is the end of the first sentence.")

    def test_total_prompt_ceiling_drops_context(self) -> None:
        huge = "x" * 10000
        prompt = build_augmented_prompt("Q?", {"content": huge}, None, max_evidence_chars=5000)
        assert "Background context omitted" in prompt
        assert "Question: Q?" in prompt


class TestGuardHelpers:
    def test_guard_normalize_collapses_whitespace(self) -> None:
        assert guard_normalize("  Hello   WORLD  ") == "hello world"

    def test_is_evidence_style_text(self) -> None:
        assert is_evidence_style_text("According to sources:")
        assert not is_evidence_style_text("Just a plain answer.")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
