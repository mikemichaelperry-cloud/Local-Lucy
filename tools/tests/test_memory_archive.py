#!/usr/bin/env python3
"""
Tests for archived turn history and session auto-naming.
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


class TestMemoryArchive(unittest.TestCase):
    """Tests for archive table and session metadata."""

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
    # _archive_turns
    # ------------------------------------------------------------------

    def test_archive_turns_preserves_history(self):
        for i in range(3):
            ms.store_turn("user", f"Q{i}")
            ms.store_turn("assistant", f"A{i}")

        self.assertEqual(ms.get_turn_count(), 6)
        ms._archive_turns("default")
        self.assertEqual(ms.get_turn_count(), 0)

        archived = ms.get_archived_turns("default")
        self.assertEqual(len(archived), 6)
        self.assertEqual(archived[0]["text"], "Q0")
        self.assertEqual(archived[1]["text"], "A0")
        self.assertEqual(archived[0]["turn_index"], 0)
        self.assertEqual(archived[5]["turn_index"], 5)

    def test_archive_turns_isolated_by_session(self):
        ms.store_turn("user", "A1", session_id="A")
        ms.store_turn("user", "B1", session_id="B")
        ms._archive_turns("A")
        self.assertEqual(ms.get_turn_count("A"), 0)
        self.assertEqual(ms.get_turn_count("B"), 1)
        self.assertEqual(len(ms.get_archived_turns("A")), 1)
        self.assertEqual(len(ms.get_archived_turns("B")), 0)

    # ------------------------------------------------------------------
    # maybe_summarize_session archives before clearing
    # ------------------------------------------------------------------

    def test_summarize_archives_turns(self):
        for i in range(6):
            ms.store_turn("user", f"Q{i}")
            ms.store_turn("assistant", f"A{i}")

        with patch.object(ms, "_summarize_turns_with_ollama", return_value="Summary."):
            ms.maybe_summarize_session(threshold=5)

        self.assertEqual(ms.get_turn_count(), 0)
        archived = ms.get_archived_turns("default")
        self.assertEqual(len(archived), 12)
        self.assertEqual(archived[0]["text"], "Q0")

    # ------------------------------------------------------------------
    # Session auto-naming
    # ------------------------------------------------------------------

    def test_store_turn_records_first_query(self):
        ms.store_turn("user", "How do I bias a 6L6?", session_id="tubes")
        name = ms.get_session_display_name("tubes")
        self.assertEqual(name, "How do I bias a 6L6?")

    def test_store_turn_truncates_long_name(self):
        long_query = "A" * 100
        ms.store_turn("user", long_query, session_id="long")
        name = ms.get_session_display_name("long")
        self.assertLessEqual(len(name), 65)
        self.assertTrue(name.endswith("..."))

    def test_store_turn_only_records_first_user_turn(self):
        ms.store_turn("user", "First question", session_id="multi")
        ms.store_turn("assistant", "First answer", session_id="multi")
        ms.store_turn("user", "Second question", session_id="multi")
        name = ms.get_session_display_name("multi")
        self.assertEqual(name, "First question")

    def test_get_session_display_name_fallback(self):
        self.assertEqual(ms.get_session_display_name("unknown"), "unknown")

    def test_assistant_turn_does_not_set_name(self):
        ms.store_turn("assistant", "Hello", session_id="bot_first")
        name = ms.get_session_display_name("bot_first")
        self.assertEqual(name, "bot_first")


if __name__ == "__main__":
    unittest.main()
