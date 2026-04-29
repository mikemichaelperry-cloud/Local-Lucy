#!/usr/bin/env python3
"""
Tests for semantic cross-session recall (embeddings + cosine similarity).

Mocks Ollama embedding calls to avoid needing a live model.
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


class TestMemorySemantic(unittest.TestCase):
    """Tests for embedding-based semantic recall."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_threshold = os.environ.get("LUCY_MEMORY_SIMILARITY_THRESHOLD", "")
        cls._orig_max = os.environ.get("LUCY_MEMORY_MAX_INJECTED_SESSIONS", "")
        cls._orig_gap = os.environ.get("LUCY_MEMORY_REQUIRE_TOP_GAP", "")
        cls._orig_conn = ms._CONN_CACHE

    def setUp(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_path
        os.environ["LUCY_MEMORY_SIMILARITY_THRESHOLD"] = "0.0"
        os.environ["LUCY_MEMORY_MAX_INJECTED_SESSIONS"] = "10"
        os.environ["LUCY_MEMORY_REQUIRE_TOP_GAP"] = "0.0"
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
        if self._orig_threshold:
            os.environ["LUCY_MEMORY_SIMILARITY_THRESHOLD"] = self._orig_threshold
        else:
            os.environ.pop("LUCY_MEMORY_SIMILARITY_THRESHOLD", None)
        if self._orig_gap:
            os.environ["LUCY_MEMORY_REQUIRE_TOP_GAP"] = self._orig_gap
        else:
            os.environ.pop("LUCY_MEMORY_REQUIRE_TOP_GAP", None)
        if self._orig_max:
            os.environ["LUCY_MEMORY_MAX_INJECTED_SESSIONS"] = self._orig_max
        else:
            os.environ.pop("LUCY_MEMORY_MAX_INJECTED_SESSIONS", None)

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # Cosine similarity
    # ------------------------------------------------------------------

    def test_cosine_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        self.assertAlmostEqual(ms._cosine_similarity(v, v), 1.0, places=5)

    def test_cosine_orthogonal_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        self.assertAlmostEqual(ms._cosine_similarity(a, b), 0.0, places=5)

    def test_cosine_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        self.assertAlmostEqual(ms._cosine_similarity(a, b), -1.0, places=5)

    def test_cosine_zero_vector(self):
        self.assertEqual(ms._cosine_similarity([0.0, 0.0], [1.0, 2.0]), 0.0)

    # ------------------------------------------------------------------
    # find_relevant_sessions (with mocked embeddings)
    # ------------------------------------------------------------------

    def test_find_relevant_sessions_returns_empty_when_no_embeddings(self):
        result = ms.find_relevant_sessions("What about tubes?", top_k=2)
        self.assertEqual(result, [])

    def test_find_relevant_sessions_ranks_by_similarity(self):
        # Create two sessions with summaries and embeddings
        for session_id, summary, vector in [
            ("tubes", "Tube amp project discussion.", [1.0, 0.0, 0.0]),
            ("python", "Python refactoring session.", [0.0, 1.0, 0.0]),
        ]:
            conn = ms._get_connection()
            conn.execute(
                "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
                (session_id, summary, 10),
            )
            conn.execute(
                "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?)",
                (session_id, str(vector).encode()),
            )
            conn.commit()

        # Mock embedding to return a vector closer to "tubes"
        with patch.object(ms, "_get_embedding", return_value=[0.9, 0.1, 0.0]):
            results = ms.find_relevant_sessions("tube amplifiers", top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["session_id"], "tubes")
        self.assertGreater(results[0]["similarity"], results[1]["similarity"])

    def test_find_relevant_sessions_empty_query(self):
        self.assertEqual(ms.find_relevant_sessions(""), [])
        self.assertEqual(ms.find_relevant_sessions("   "), [])

    def test_find_relevant_sessions_respects_top_k(self):
        for i in range(5):
            sid = f"s{i}"
            conn = ms._get_connection()
            conn.execute(
                "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
                (sid, f"Summary {i}.", 5),
            )
            conn.execute(
                "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?)",
                (sid, str([float(i), 0.0, 0.0]).encode()),
            )
            conn.commit()

        with patch.object(ms, "_get_embedding", return_value=[2.0, 0.0, 0.0]):
            results = ms.find_relevant_sessions("test", top_k=2)
        self.assertEqual(len(results), 2)

    def test_find_relevant_sessions_respects_threshold(self):
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("a", "Summary A.", 5),
        )
        conn.execute(
            "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?)",
            ("a", str([1.0, 0.0, 0.0]).encode()),
        )
        conn.commit()

        # Query vector orthogonal → similarity 0
        with patch.object(ms, "_get_embedding", return_value=[0.0, 1.0, 0.0]):
            results = ms.find_relevant_sessions("test", top_k=2, similarity_threshold=0.5)
        self.assertEqual(len(results), 0)

    def test_find_relevant_sessions_fallback_on_embedding_failure(self):
        with patch.object(ms, "_get_embedding", return_value=None):
            results = ms.find_relevant_sessions("test")
        self.assertEqual(results, [])

    # ------------------------------------------------------------------
    # assemble_context with semantic recall
    # ------------------------------------------------------------------

    def test_assemble_context_with_query_uses_semantic_recall(self):
        # Seed a session with summary+embedding
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("tubes", "Tube amplifier design decisions.", 10),
        )
        conn.execute(
            "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?)",
            ("tubes", str([1.0, 0.0, 0.0]).encode()),
        )
        conn.commit()

        # Current session has a fresh turn
        ms.store_turn("user", "What transformer?", session_id="current")

        with patch.object(ms, "_get_embedding", return_value=[0.95, 0.05, 0.0]):
            ctx = ms.assemble_context(current_session_id="current", query="tube amp transformer", max_chars=500, depth="deep", mode="augmented")

        self.assertIn("Related session: Tube amplifier design decisions.", ctx)
        self.assertIn("User: What transformer?", ctx)

    def test_assemble_context_without_query_skips_semantic(self):
        # No embeddings needed — just turns
        ms.store_turn("user", "Hello")
        ms.store_turn("assistant", "Hi")
        ctx = ms.assemble_context(query="")
        self.assertIn("User: Hello", ctx)
        self.assertNotIn("Related session", ctx)


if __name__ == "__main__":
    unittest.main()
