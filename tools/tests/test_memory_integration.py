#!/usr/bin/env python3
"""
Integration tests for memory layer dual-write behaviour.

Verifies that:
1. execution_engine._load_session_memory_context reads from SQLite first
2. Falls back to text file when SQLite is empty / missing
3. runtime_request.append_chat_memory_turn writes to both SQLite and text file
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure tools/ is on path
TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))

import memory.memory_service as ms


class TestMemoryIntegration(unittest.TestCase):
    """Integration tests spanning memory_service + existing code paths."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_conn = ms._CONN_CACHE
        cls._orig_session_memory = os.environ.get("LUCY_SESSION_MEMORY", "")
        cls._orig_chat_memory_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "")

    def setUp(self):
        # Fresh temp DB
        self.tmp_fd, self.tmp_db_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_db_path
        ms._close_connection()

        # Fresh temp text file
        self.tmp_text_fd, self.tmp_text_path = tempfile.mkstemp(suffix=".txt")
        os.close(self.tmp_text_fd)
        os.environ["LUCY_RUNTIME_CHAT_MEMORY_FILE"] = self.tmp_text_path

        # Enable session memory
        os.environ["LUCY_SESSION_MEMORY"] = "1"

    def tearDown(self):
        ms._close_connection()
        for p in (self.tmp_db_path, self.tmp_text_path):
            try:
                os.unlink(p)
            except OSError:
                pass

        # Restore env
        if self._orig_db_env:
            os.environ["LUCY_MEMORY_DB_PATH"] = self._orig_db_env
        else:
            os.environ.pop("LUCY_MEMORY_DB_PATH", None)

        if self._orig_chat_memory_file:
            os.environ["LUCY_RUNTIME_CHAT_MEMORY_FILE"] = self._orig_chat_memory_file
        else:
            os.environ.pop("LUCY_RUNTIME_CHAT_MEMORY_FILE", None)

        if self._orig_session_memory:
            os.environ["LUCY_SESSION_MEMORY"] = self._orig_session_memory
        else:
            os.environ.pop("LUCY_SESSION_MEMORY", None)

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # execution_engine read path
    # ------------------------------------------------------------------

    def test_execution_engine_reads_from_sqlite_when_data_exists(self):
        """If SQLite has turns, _load_session_memory_context should return them."""
        ms.store_turn("user", "What's the weather?")
        ms.store_turn("assistant", "It's sunny today.")

        from router_py.execution_engine import _load_session_memory_context
        context = _load_session_memory_context()

        self.assertIn("User: What's the weather?", context)
        self.assertIn("Assistant: It's sunny today.", context)

    def test_execution_engine_falls_back_to_text_file_when_sqlite_empty(self):
        """If SQLite has no turns, fall back to the text file."""
        text_path = Path(self.tmp_text_path)
        text_path.write_text("User: Fallback question\nAssistant: Fallback answer\n\n", encoding="utf-8")

        from router_py.execution_engine import _load_session_memory_context
        context = _load_session_memory_context()

        self.assertIn("User: Fallback question", context)
        self.assertIn("Assistant: Fallback answer", context)

    def test_execution_engine_returns_empty_when_memory_disabled(self):
        """LUCY_SESSION_MEMORY=0 should yield empty string regardless of data."""
        os.environ["LUCY_SESSION_MEMORY"] = "0"
        ms.store_turn("user", "Should not appear")

        from router_py.execution_engine import _load_session_memory_context
        context = _load_session_memory_context()
        self.assertEqual(context, "")

    # ------------------------------------------------------------------
    # runtime_request write path
    # ------------------------------------------------------------------

    def test_append_chat_memory_turn_writes_to_both_stores(self):
        """append_chat_memory_turn should populate SQLite AND the text file."""
        from runtime_request import append_chat_memory_turn

        mem_path = Path(self.tmp_text_path)
        append_chat_memory_turn(mem_path, "Hello world", "Hi there")

        # SQLite side
        turns = ms.get_recent_turns(limit=10)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["text"], "Hello world")
        self.assertEqual(turns[1]["text"], "Hi there")

        # Text-file side
        text = mem_path.read_text(encoding="utf-8")
        self.assertIn("User: Hello world", text)
        self.assertIn("Assistant: Hi there", text)

    def test_append_chat_memory_turn_text_file_still_works_on_sqlite_error(self):
        """If SQLite fails, text file must still be written."""
        # Break the DB path so SQLite open will fail
        os.environ["LUCY_MEMORY_DB_PATH"] = "/nonexistent_dir/impossible.db"
        ms._close_connection()

        from runtime_request import append_chat_memory_turn
        mem_path = Path(self.tmp_text_path)
        append_chat_memory_turn(mem_path, "Test question", "Test answer")

        text = mem_path.read_text(encoding="utf-8")
        self.assertIn("User: Test question", text)
        self.assertIn("Assistant: Test answer", text)

    # ------------------------------------------------------------------
    # Limit behaviour parity
    # ------------------------------------------------------------------

    def test_append_respects_max_turns(self):
        """Text file trimming to max_turns should still work."""
        from runtime_request import append_chat_memory_turn

        mem_path = Path(self.tmp_text_path)
        for i in range(8):
            append_chat_memory_turn(mem_path, f"Q{i}", f"A{i}", max_turns=3)

        text = mem_path.read_text(encoding="utf-8")
        # Only last 3 turns should remain in text file
        self.assertIn("Q5", text)
        self.assertIn("Q6", text)
        self.assertIn("Q7", text)
        self.assertNotIn("Q4", text)


if __name__ == "__main__":
    unittest.main()
