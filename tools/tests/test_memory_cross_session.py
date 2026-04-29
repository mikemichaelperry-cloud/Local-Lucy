#!/usr/bin/env python3
"""
Tests for cross-session recall (other-session summaries in context assembly).
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.memory_service as ms


class TestMemoryCrossSession(unittest.TestCase):
    """Tests for multi-session summary isolation and cross-session context."""

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
        os.environ["LUCY_MEMORY_SUMMARIZE_THRESHOLD"] = "5"

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
    # get_other_session_summaries
    # ------------------------------------------------------------------

    def test_other_session_summaries_excludes_current(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Tube amp summary."):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="tubes")
            ms.maybe_summarize_session(session_id="tubes", threshold=5)

        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Python summary."):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="python")
            ms.maybe_summarize_session(session_id="python", threshold=5)

        others = ms.get_other_session_summaries(current_session_id="tubes")
        self.assertEqual(len(others), 1)
        self.assertEqual(others[0]["session_id"], "python")
        self.assertEqual(others[0]["summary_text"], "Python summary.")

    def test_other_session_summaries_respects_limit(self):
        for s in ("A", "B", "C"):
            with patch.object(ms, "_summarize_turns_with_ollama", return_value=f"Summary {s}."):
                for i in range(6):
                    ms.store_turn("user", f"Q{i}", session_id=s)
                ms.maybe_summarize_session(session_id=s, threshold=5)

        others = ms.get_other_session_summaries(current_session_id="D", limit=2)
        self.assertEqual(len(others), 2)

    def test_other_session_summaries_empty_when_none(self):
        others = ms.get_other_session_summaries(current_session_id="default")
        self.assertEqual(others, [])

    # ------------------------------------------------------------------
    # assemble_context with cross-session
    # ------------------------------------------------------------------

    def test_assemble_context_includes_other_sessions(self):
        # Create summary for session "tubes"
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Tube amp discussion."):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="tubes")
            ms.maybe_summarize_session(session_id="tubes", threshold=5)

        # Create summary for session "python"
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Python refactoring discussion."):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="python")
            ms.maybe_summarize_session(session_id="python", threshold=5)

        # Now ask from "python" perspective — should see "tubes" summary
        ctx = ms.assemble_context(current_session_id="python", max_chars=500, depth="deep", mode="augmented")
        self.assertIn("Previous session: Tube amp discussion.", ctx)
        self.assertIn("Session summary: Python refactoring discussion.", ctx)

    def test_assemble_context_trims_long_other_summaries(self):
        long_summary = "A" * 200
        with patch.object(ms, "_summarize_turns_with_ollama", return_value=long_summary):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="other")
            ms.maybe_summarize_session(session_id="other", threshold=5)

        ctx = ms.assemble_context(current_session_id="default", max_chars=500, depth="deep", mode="augmented")
        # Should be truncated with "..."
        self.assertIn("...", ctx)
        self.assertLess(len(ctx), 500 + 50)  # reasonable bound

    def test_assemble_context_no_duplicate_current_in_other(self):
        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Single summary."):
            for i in range(6):
                ms.store_turn("user", f"Q{i}", session_id="only")
            ms.maybe_summarize_session(session_id="only", threshold=5)

        ctx = ms.assemble_context(current_session_id="only", max_chars=500, depth="deep", mode="augmented")
        self.assertIn("Session summary: Single summary.", ctx)
        # Should NOT contain "Previous session"
        self.assertNotIn("Previous session", ctx)


if __name__ == "__main__":
    unittest.main()
