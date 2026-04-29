#!/usr/bin/env python3
"""
Tests for memory_service auto-summarization and context assembly.

Uses a temporary in-memory SQLite DB and mocks the Ollama call.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure tools/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.memory_service as ms


class TestMemorySummarization(unittest.TestCase):
    """Tests for auto-summarization, summary storage, and context assembly."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_conn = ms._CONN_CACHE
        cls._orig_threshold = os.environ.get("LUCY_MEMORY_SUMMARIZE_THRESHOLD", "")

    def setUp(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_path
        ms._close_connection()
        # Disable auto-summarize by default so store_turn doesn't trigger it
        os.environ["LUCY_MEMORY_SUMMARIZE_THRESHOLD"] = "9999"

    def tearDown(self):
        ms._close_connection()
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass
        if self._orig_db_env:
            os.environ["LUCY_MEMORY_DB_PATH"] = self._orig_db_env
        else:
            os.environ.pop("LUCY_MEMORY_DB_PATH", None)
        if self._orig_threshold:
            os.environ["LUCY_MEMORY_SUMMARIZE_THRESHOLD"] = self._orig_threshold
        else:
            os.environ.pop("LUCY_MEMORY_SUMMARIZE_THRESHOLD", None)

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # maybe_summarize_session threshold logic
    # ------------------------------------------------------------------

    def test_maybe_summarize_skips_when_under_threshold(self):
        for i in range(5):
            ms.store_turn("user", f"Q{i}")
        self.assertFalse(ms.maybe_summarize_session(threshold=10))
        self.assertIsNone(ms.get_session_summary())

    def test_maybe_summarize_triggers_when_over_threshold(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Mock summary."):
            for i in range(12):
                ms.store_turn("user", f"Q{i}")
            self.assertTrue(ms.maybe_summarize_session(threshold=10))
            self.assertEqual(ms.get_session_summary(), "Mock summary.")

    def test_maybe_summarize_clears_turns_after_success(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Mock summary."):
            for i in range(12):
                ms.store_turn("user", f"Q{i}")
            self.assertEqual(ms.get_turn_count(), 12)
            ms.maybe_summarize_session(threshold=10)
            self.assertEqual(ms.get_turn_count(), 0)

    def test_maybe_summarize_noop_when_ollama_fails(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value=None):
            for i in range(12):
                ms.store_turn("user", f"Q{i}")
            self.assertFalse(ms.maybe_summarize_session(threshold=10))
            self.assertEqual(ms.get_turn_count(), 12)

    def test_maybe_summarize_upserts_existing_summary(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="First summary."):
            for i in range(12):
                ms.store_turn("user", f"Q{i}")
            ms.maybe_summarize_session(threshold=10)

        # Add more turns, trigger again
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Updated summary."):
            for i in range(12):
                ms.store_turn("user", f"NewQ{i}")
            ms.maybe_summarize_session(threshold=10)

        self.assertEqual(ms.get_session_summary(), "Updated summary.")

    def test_threshold_zero_disables_summarization(self):
        with patch.object(ms, "_summarize_turns_with_ollama") as mock_ollama:
            for i in range(50):
                ms.store_turn("user", f"Q{i}")
            self.assertFalse(ms.maybe_summarize_session(threshold=0))
            mock_ollama.assert_not_called()

    # ------------------------------------------------------------------
    # assemble_context
    # ------------------------------------------------------------------

    def test_assemble_context_with_only_recent_turns(self):
        ms.store_turn("user", "Hello")
        ms.store_turn("assistant", "Hi")
        ctx = ms.assemble_context(max_chars=500)
        self.assertIn("User: Hello", ctx)
        self.assertIn("Assistant: Hi", ctx)

    def test_assemble_context_includes_current_summary(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="We discussed tubes."):
            for i in range(12):
                ms.store_turn("user", f"Q{i}")
            ms.maybe_summarize_session(threshold=10)

        # Add fresh turns after summary
        ms.store_turn("user", "What's next?")
        ms.store_turn("assistant", "Let's build it.")

        ctx = ms.assemble_context(max_chars=500, depth="deep", mode="local")
        self.assertIn("Session summary: We discussed tubes.", ctx)
        self.assertIn("User: What's next?", ctx)
        self.assertIn("Assistant: Let's build it.", ctx)

    def test_assemble_context_truncates_to_max_chars(self):
        for i in range(20):
            ms.store_turn("user", f"Very long question text number {i} with padding")
        ctx = ms.assemble_context(max_chars=100)
        self.assertLessEqual(len(ctx), 100)

    def test_assemble_context_returns_empty_when_nothing(self):
        self.assertEqual(ms.assemble_context(), "")

    # ------------------------------------------------------------------
    # _summarize_turns_with_ollama format
    # ------------------------------------------------------------------

    def test_summarize_turns_format_includes_conversation(self):
        turns = [
            {"role": "user", "text": "What is Ohm's law?"},
            {"role": "assistant", "text": "V = I × R."},
        ]
        # We can't call real Ollama in unit tests; just verify the function
        # constructs a prompt with the conversation text.
        prompt_text = ms.format_turns_for_prompt(turns)
        self.assertIn("User: What is Ohm's law?", prompt_text)
        self.assertIn("Assistant: V = I × R.", prompt_text)


if __name__ == "__main__":
    unittest.main()
