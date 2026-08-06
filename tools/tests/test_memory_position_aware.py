#!/usr/bin/env python3
"""
Tests for position-aware session memory retrieval.

Recent turns are included verbatim; older turns are ranked by semantic
similarity to the current query and only the top matches are appended.
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


class TestMemoryPositionAware(unittest.TestCase):
    """Tests for position-aware context assembly."""

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
        os.environ["LUCY_MEMORY_SIMILARITY_THRESHOLD"] = "0.5"
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

    def _embedding_for_text(self, text: str) -> list[float]:
        """Return a deterministic embedding based on text content."""
        lowered = (text or "").lower()
        if "dog" in lowered or "loyal" in lowered or "labrador" in lowered:
            return [0.9, 0.1, 0.0]
        if "cat" in lowered or "whiskers" in lowered:
            return [0.1, 0.9, 0.0]
        if "what" in lowered and "breed" in lowered:
            return [0.85, 0.15, 0.0]
        return [0.33, 0.33, 0.34]

    def test_recent_turns_included_verbatim_and_old_irrelevant_turn_excluded(self):
        """Recent turns are always kept; older turns are filtered by relevance."""
        session_id = "position_test"
        # Older, irrelevant-to-dogs turn
        ms.store_turn(
            "user",
            "I used to have a cat named Whiskers.",
            session_id=session_id,
        )
        ms.store_turn(
            "assistant",
            "That is nice.",
            session_id=session_id,
        )
        # Recent dog-related turns
        ms.store_turn(
            "user",
            "Tell me about dogs.",
            session_id=session_id,
        )
        ms.store_turn(
            "assistant",
            "Dogs are loyal.",
            session_id=session_id,
        )

        with patch.object(ms, "_get_embedding", side_effect=self._embedding_for_text):
            context, telemetry = ms.assemble_context_with_telemetry(
                current_session_id=session_id,
                max_chars=2000,
                recent_turn_limit=2,
                query="What is the best dog breed?",
                depth="deep",
                mode="local",
            )

        lowered = context.lower()
        self.assertIn("dog", lowered)
        self.assertIn("loyal", lowered)
        self.assertNotIn("whiskers", lowered)
        self.assertEqual(telemetry.get("memory_turns_verbatim"), "2")
        # Semantic count reflects turns ranked above threshold, not final survivors.
        self.assertEqual(telemetry.get("memory_turns_semantic"), "1")

    def test_relevant_older_turn_appended_semantically(self):
        """An older turn that matches the query is appended via semantic ranking."""
        session_id = "semantic_test"
        # Older dog-related turn (beyond recent_limit=2)
        ms.store_turn(
            "user",
            "My previous dog was a Labrador.",
            session_id=session_id,
        )
        ms.store_turn(
            "assistant",
            "Labradors are friendly.",
            session_id=session_id,
        )
        # Recent dog-related turns
        ms.store_turn(
            "user",
            "Tell me about dogs.",
            session_id=session_id,
        )
        ms.store_turn(
            "assistant",
            "Dogs are loyal.",
            session_id=session_id,
        )

        with patch.object(ms, "_get_embedding", side_effect=self._embedding_for_text):
            context, telemetry = ms.assemble_context_with_telemetry(
                current_session_id=session_id,
                max_chars=2000,
                recent_turn_limit=2,
                query="What is the best dog breed?",
                depth="deep",
                mode="local",
            )

        lowered = context.lower()
        # Recent dog turns are verbatim
        self.assertIn("dog", lowered)
        self.assertIn("loyal", lowered)
        # Older dog turn is included semantically
        self.assertIn("labrador", lowered)
        self.assertEqual(telemetry.get("memory_turns_verbatim"), "2")
        self.assertEqual(telemetry.get("memory_turns_semantic"), "2")

    def test_truncate_preserves_recent_turns_first(self):
        """When context is truncated, recent verbatim turns survive longest."""
        session_id = "truncate_test"
        # Many short dog-related turns
        for i in range(10):
            ms.store_turn(
                "user",
                f"Question number {i} about dogs?",
                session_id=session_id,
            )
            ms.store_turn(
                "assistant",
                f"Answer number {i} about dogs.",
                session_id=session_id,
            )

        with patch.object(ms, "_get_embedding", side_effect=self._embedding_for_text):
            context, telemetry = ms.assemble_context_with_telemetry(
                current_session_id=session_id,
                max_chars=100,
                recent_turn_limit=2,
                query="dogs",
                depth="deep",
                mode="local",
            )

        lowered = context.lower()
        # Most recent turn must survive truncation
        self.assertIn("number 9", lowered)
        # Older semantic turns should be dropped before recent turns
        self.assertNotIn("number 0", lowered)
        self.assertEqual(telemetry.get("memory_turns_verbatim"), "2")
        # Semantic turns were selected but truncated out of the final context.
        self.assertGreater(int(telemetry.get("memory_turns_semantic", "0")), 0)


if __name__ == "__main__":
    unittest.main()
