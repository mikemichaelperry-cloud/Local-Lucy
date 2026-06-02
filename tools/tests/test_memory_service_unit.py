#!/usr/bin/env python3
"""
Unit tests for tools/memory/memory_service.py

Uses a temporary in-memory SQLite DB to avoid polluting production state.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure tools/ is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.memory_service as ms


class TestMemoryServiceUnit(unittest.TestCase):
    """Pure unit tests for memory_service with isolated DB."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_conn = ms._CONN_CACHE

    def setUp(self):
        # Point to a fresh temp DB for every test
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
    # store_turn / get_recent_turns
    # ------------------------------------------------------------------

    def test_store_and_retrieve_single_turn(self):
        ms.store_turn("user", "Hello")
        turns = ms.get_recent_turns(limit=10)
        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[0]["text"], "Hello")

    def test_store_user_and_assistant(self):
        ms.store_turn("user", "What's the weather?")
        ms.store_turn("assistant", "It's sunny.")
        turns = ms.get_recent_turns(limit=10)
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[1]["role"], "assistant")

    def test_limit_respected(self):
        for i in range(10):
            ms.store_turn("user", f"msg {i}")
        turns = ms.get_recent_turns(limit=3)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[-1]["text"], "msg 9")

    def test_order_is_oldest_first(self):
        ms.store_turn("user", "first")
        ms.store_turn("assistant", "second")
        ms.store_turn("user", "third")
        turns = ms.get_recent_turns(limit=10)
        texts = [t["text"] for t in turns]
        self.assertEqual(texts, ["first", "second", "third"])

    def test_store_turn_strips_text(self):
        ms.store_turn("user", "  padded  ")
        turns = ms.get_recent_turns()
        self.assertEqual(turns[0]["text"], "padded")

    def test_store_turn_empty_string_noop(self):
        ms.store_turn("user", "")
        self.assertEqual(ms.get_turn_count(), 0)

    def test_store_turn_invalid_role_raises(self):
        with self.assertRaises(ValueError):
            ms.store_turn("bot", "Hello")

    # ------------------------------------------------------------------
    # format_turns_for_prompt
    # ------------------------------------------------------------------

    def test_format_single_turn(self):
        turns = [{"role": "user", "text": "Hello"}]
        self.assertEqual(ms.format_turns_for_prompt(turns), "User: Hello")

    def test_format_user_and_assistant(self):
        turns = [
            {"role": "user", "text": "Hi"},
            {"role": "assistant", "text": "Hey there"},
        ]
        expected = "User: Hi\n\nAssistant: Hey there"
        self.assertEqual(ms.format_turns_for_prompt(turns), expected)

    def test_format_empty_list(self):
        self.assertEqual(ms.format_turns_for_prompt([]), "")

    # ------------------------------------------------------------------
    # get_all_turns
    # ------------------------------------------------------------------

    def test_get_all_turns(self):
        ms.store_turn("user", "a")
        ms.store_turn("assistant", "b")
        ms.store_turn("user", "c")
        all_turns = ms.get_all_turns()
        self.assertEqual(len(all_turns), 3)
        self.assertEqual(all_turns[0]["text"], "a")
        self.assertEqual(all_turns[-1]["text"], "c")

    # ------------------------------------------------------------------
    # clear_session
    # ------------------------------------------------------------------

    def test_clear_session_removes_turns(self):
        ms.store_turn("user", "keep me")
        ms.store_turn("assistant", "ok")
        self.assertEqual(ms.get_turn_count(), 2)
        ms.clear_session()
        self.assertEqual(ms.get_turn_count(), 0)
        self.assertEqual(ms.get_recent_turns(), [])

    def test_clear_session_isolated_by_session(self):
        ms.store_turn("user", "default", session_id="default")
        ms.store_turn("user", "other", session_id="other")
        ms.clear_session("other")
        self.assertEqual(ms.get_turn_count("default"), 1)
        self.assertEqual(ms.get_turn_count("other"), 0)

    # ------------------------------------------------------------------
    # get_session_count / get_turn_count
    # ------------------------------------------------------------------

    def test_get_turn_count(self):
        self.assertEqual(ms.get_turn_count(), 0)
        ms.store_turn("user", "x")
        self.assertEqual(ms.get_turn_count(), 1)

    def test_get_session_count(self):
        self.assertEqual(ms.get_session_count(), 0)
        ms.store_turn("user", "a", session_id="s1")
        ms.store_turn("user", "b", session_id="s2")
        self.assertEqual(ms.get_session_count(), 2)

    # ------------------------------------------------------------------
    # persistent facts
    # ------------------------------------------------------------------

    def test_store_persistent_fact_saves_embedding(self):
        with patch.object(ms, "_compute_fact_embedding", return_value=[0.5, 0.5]):
            fid = ms.store_persistent_fact("I have a cat named Luna.", category="pets")
        conn = ms._get_connection()
        row = conn.execute(
            "SELECT embedding, embedding_model FROM persistent_facts WHERE id = ?", (fid,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIsNotNone(row[0])
        vec = json.loads(row[0].decode("utf-8"))
        self.assertEqual(vec, [0.5, 0.5])

    def test_get_relevant_persistent_facts_selects_pet_fact(self):
        embeddings = {
            "What is my dog's name?": [1.0, 0.0],
            "Rex is your dog.": [0.99, 0.01],
            "Your daughter Anna lives in Haifa.": [0.0, 1.0],
            "Project Atlas uses Go.": [-1.0, 0.0],
        }

        with patch.object(ms, "_compute_fact_embedding", side_effect=lambda text: embeddings.get(text)):
            ms.store_persistent_fact("Rex is your dog.", category="pets")
            ms.store_persistent_fact("Your daughter Anna lives in Haifa.", category="family")
            ms.store_persistent_fact("Project Atlas uses Go.", category="project")

            facts = ms.get_relevant_persistent_facts(
                "What is my dog's name?",
                limit=3,
                threshold=0.80,
            )

        self.assertEqual(facts, ["Rex is your dog."])

    def test_get_relevant_persistent_facts_selects_family_fact(self):
        embeddings = {
            "Where does my daughter live?": [0.0, 1.0],
            "Rex is your dog.": [1.0, 0.0],
            "Your daughter Anna lives in Haifa.": [0.02, 0.98],
        }

        with patch.object(ms, "_compute_fact_embedding", side_effect=lambda text: embeddings.get(text)):
            ms.store_persistent_fact("Rex is your dog.", category="pets")
            ms.store_persistent_fact("Your daughter Anna lives in Haifa.", category="family")

            facts = ms.get_relevant_persistent_facts(
                "Where does my daughter live?",
                limit=3,
                threshold=0.80,
            )

        self.assertEqual(facts, ["Your daughter Anna lives in Haifa."])

    def test_get_relevant_persistent_facts_returns_empty_on_embedding_failure(self):
        ms.store_persistent_fact("Rex is your dog.", category="pets")
        ms.store_persistent_fact("Your daughter Anna lives in Haifa.", category="family")

        with patch.object(ms, "_compute_fact_embedding", return_value=None):
            facts = ms.get_relevant_persistent_facts("What is my dog's name?")

        self.assertEqual(facts, [])

    def test_get_relevant_persistent_facts_backfills_missing_embeddings(self):
        # Store facts without embedding (simulate old row)
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO persistent_facts (fact_text, category, embedding, embedding_model) VALUES (?, ?, ?, ?)",
            ("I drive a Tesla.", "car", None, None),
        )
        conn.commit()

        embeddings = {
            "What car do I drive?": [1.0, 0.0],
            "I drive a Tesla.": [0.95, 0.05],
        }

        with patch.object(ms, "_compute_fact_embedding", side_effect=lambda text: embeddings.get(text)):
            facts = ms.get_relevant_persistent_facts(
                "What car do I drive?",
                limit=3,
                threshold=0.80,
            )

        self.assertEqual(facts, ["I drive a Tesla."])
        # Verify embedding was backfilled
        row = conn.execute(
            "SELECT embedding FROM persistent_facts WHERE fact_text = ?", ("I drive a Tesla.",)
        ).fetchone()
        self.assertIsNotNone(row[0])


if __name__ == "__main__":
    unittest.main()
