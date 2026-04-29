#!/usr/bin/env python3
"""
Tests for Mode Auto context depth detection.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.memory_service as ms


class TestMemoryAutoDepth(unittest.TestCase):
    """Tests for automatic shallow/deep context detection."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_conn = ms._CONN_CACHE

    def setUp(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_path
        ms._close_connection()

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

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # _detect_context_depth
    # ------------------------------------------------------------------

    def test_pronoun_queries_are_deep(self):
        self.assertEqual(ms._detect_context_depth("Would you consider him elected?"), "deep")
        self.assertEqual(ms._detect_context_depth("What about her?"), "deep")
        self.assertEqual(ms._detect_context_depth("Tell me about it"), "deep")

    def test_followup_queries_are_deep(self):
        self.assertEqual(ms._detect_context_depth("What about the power supply?"), "deep")
        self.assertEqual(ms._detect_context_depth("Tell me more"), "deep")
        self.assertEqual(ms._detect_context_depth("Elaborate on that"), "deep")

    def test_reference_queries_are_deep(self):
        self.assertEqual(ms._detect_context_depth("The same for 6L6"), "deep")
        self.assertEqual(ms._detect_context_depth("As discussed earlier"), "deep")

    def test_standalone_queries_are_shallow(self):
        self.assertEqual(ms._detect_context_depth("What is Ohm's law?"), "shallow")
        self.assertEqual(ms._detect_context_depth("Who is Abu Mazen?"), "shallow")
        self.assertEqual(ms._detect_context_depth("Capital of France"), "shallow")

    def test_empty_query_is_shallow(self):
        self.assertEqual(ms._detect_context_depth(""), "shallow")
        self.assertEqual(ms._detect_context_depth("   "), "shallow")

    def test_short_why_is_deep(self):
        # "Why?" alone is ambiguous but usually a follow-up; treat as deep
        self.assertEqual(ms._detect_context_depth("Why?"), "deep")
        # "How?" without follow-up words is treated as shallow
        self.assertEqual(ms._detect_context_depth("How?"), "shallow")

    # ------------------------------------------------------------------
    # assemble_context respects depth
    # ------------------------------------------------------------------

    def test_shallow_mode_returns_only_recent_turns(self):
        ms.store_turn("user", "Q1")
        ms.store_turn("assistant", "A1")
        ctx = ms.assemble_context(depth="shallow")
        self.assertIn("User: Q1", ctx)
        self.assertNotIn("Session summary", ctx)
        self.assertNotIn("Previous session", ctx)

    def test_deep_mode_includes_summaries(self):
        # Seed a summary
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("default", "We discussed tubes.", 6),
        )
        conn.commit()
        ms.store_turn("user", "Q1")
        ctx = ms.assemble_context(depth="deep")
        self.assertIn("Session summary: We discussed tubes.", ctx)

    def test_auto_detects_shallow_for_standalone(self):
        ms.store_turn("user", "Q1")
        ms.store_turn("assistant", "A1")
        ctx = ms.assemble_context(query="What is Ohm's law?", depth="auto")
        self.assertIn("User: Q1", ctx)
        self.assertNotIn("Session summary", ctx)

    def test_auto_detects_deep_for_pronoun(self):
        # Seed a summary
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("default", "We discussed tubes.", 6),
        )
        conn.commit()
        ms.store_turn("user", "Q1")
        ctx = ms.assemble_context(query="Would you consider him elected?", depth="auto")
        self.assertIn("Session summary: We discussed tubes.", ctx)


if __name__ == "__main__":
    unittest.main()
