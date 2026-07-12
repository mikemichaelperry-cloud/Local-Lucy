#!/usr/bin/env python3
"""
Tests for topic-shift detection in memory context assembly.

Prevents context pollution like:
  Previous turn: "What did Albert Einstein discover?"
  Current query: "What's the simplest car mod to increase engine power?"
  → Should NOT inject Einstein context into the car query.

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


class TestMemoryTopicShift(unittest.TestCase):
    """Tests for _is_topic_shift and assemble_context topic-shift gating."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_topic_threshold = os.environ.get("LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD", "")
        cls._orig_conn = ms._CONN_CACHE

    def setUp(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_path
        os.environ["LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD"] = "0.50"
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
        if self._orig_topic_threshold:
            os.environ["LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD"] = self._orig_topic_threshold
        else:
            os.environ.pop("LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD", None)

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # _is_topic_shift direct tests
    # ------------------------------------------------------------------

    def test_topic_shift_detected_for_dissimilar_queries(self):
        """Einstein → car engine should be detected as a topic shift."""
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # Einstein query embedding
                [0.0, 1.0, 0.0],  # Car query embedding (orthogonal)
            ],
        ):
            result = ms._is_topic_shift(
                "What's the simplest and cheapest modification you can make to your car to increase engine power?",
                "What did Albert Einstein discover?",
            )
        self.assertTrue(result)

    def test_topic_shift_not_detected_for_similar_queries(self):
        """Follow-up about Einstein should NOT be a topic shift."""
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [0.95, 0.05, 0.0],  # Follow-up embedding (close to original)
                [1.0, 0.0, 0.0],  # Original Einstein embedding
            ],
        ):
            result = ms._is_topic_shift(
                "Tell me more about his theory of relativity",
                "What did Albert Einstein discover?",
            )
        self.assertFalse(result)

    def test_topic_shift_empty_query_returns_false(self):
        """Empty current query should not trigger topic shift."""
        result = ms._is_topic_shift("", "previous text")
        self.assertFalse(result)

    def test_topic_shift_empty_previous_returns_false(self):
        """Empty previous text should not trigger topic shift."""
        result = ms._is_topic_shift("current query", "")
        self.assertFalse(result)

    def test_topic_shift_embedding_failure_returns_false(self):
        """If Ollama embedding fails, gracefully degrade (no shift detected)."""
        with patch.object(ms, "_get_embedding", return_value=None):
            result = ms._is_topic_shift("current query", "previous text")
        self.assertFalse(result)

    def test_topic_shift_threshold_respects_env_var(self):
        """LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD should control sensitivity."""
        os.environ["LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD"] = "0.10"
        # Similarity = 0.5, threshold = 0.10 → should be a shift
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
        ):
            result = ms._is_topic_shift("current query text", "previous query text")
        self.assertTrue(result)

    # ------------------------------------------------------------------
    # assemble_context_with_telemetry — shallow depth
    # ------------------------------------------------------------------

    def test_shallow_blocks_context_on_topic_shift(self):
        """Shallow depth should return empty context when topic shifts."""
        ms.store_turn("user", "What did Albert Einstein discover?")
        ms.store_turn("assistant", "Einstein developed the theory of relativity.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current query embedding
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="What's the simplest and cheapest modification you can make to your car to increase engine power?",
                depth="shallow",
                mode="local",
            )

        self.assertEqual(ctx, "")
        self.assertEqual(telem["memory_topic_shift_detected"], "true")
        self.assertEqual(telem["memory_context_used"], "false")

    def test_shallow_allows_context_when_same_topic(self):
        """Shallow depth should keep context for same-topic follow-up."""
        ms.store_turn("user", "What did Albert Einstein discover?")
        ms.store_turn("assistant", "Einstein developed the theory of relativity.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [0.95, 0.05, 0.0],  # previous turn embedding
                [1.0, 0.0, 0.0],  # current query embedding (very similar)
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Tell me more about his theory of relativity",
                depth="shallow",
                mode="local",
            )

        self.assertIn("User: What did Albert Einstein discover?", ctx)
        self.assertEqual(telem["memory_context_used"], "true")
        # topic_shift_detected should NOT be in telemetry
        self.assertNotIn("memory_topic_shift_detected", telem)

    # ------------------------------------------------------------------
    # assemble_context_with_telemetry — deep / LOCAL mode
    # ------------------------------------------------------------------

    def test_deep_local_blocks_context_on_topic_shift(self):
        """Deep LOCAL should return empty context when topic shifts."""
        ms.store_turn("user", "What did Albert Einstein discover?")
        ms.store_turn("assistant", "Einstein developed the theory of relativity.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current query embedding
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="What's the simplest and cheapest modification you can make to your car to increase engine power?",
                depth="deep",
                mode="local",
            )

        self.assertEqual(ctx, "")
        self.assertEqual(telem["memory_topic_shift_detected"], "true")
        self.assertEqual(telem["memory_context_used"], "false")

    def test_deep_local_allows_context_when_same_topic(self):
        """Deep LOCAL should keep context for same-topic follow-up."""
        ms.store_turn("user", "What did Albert Einstein discover?")
        ms.store_turn("assistant", "Einstein developed the theory of relativity.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [0.95, 0.05, 0.0],  # previous turn embedding
                [1.0, 0.0, 0.0],  # current query embedding
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Tell me more about his theory of relativity",
                depth="deep",
                mode="local",
            )

        self.assertIn("User: What did Albert Einstein discover?", ctx)
        self.assertEqual(telem["memory_context_used"], "true")
        self.assertNotIn("memory_topic_shift_detected", telem)

    # ------------------------------------------------------------------
    # assemble_context_with_telemetry — deep / AUGMENTED mode
    # ------------------------------------------------------------------

    def test_deep_augmented_blocks_current_session_on_topic_shift(self):
        """Deep AUGMENTED should block current-session context on topic shift,
        but cross-session recall (already similarity-gated) may still appear."""
        # Seed a cross-session summary
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("tubes", "Tube amplifier design decisions.", 10),
        )
        conn.execute(
            "INSERT INTO summary_embeddings (session_id, embedding) VALUES (?, ?)",
            ("tubes", str([0.0, 1.0, 0.0]).encode()),
        )
        conn.commit()

        # Current session has Einstein turn
        ms.store_turn("user", "What did Albert Einstein discover?", session_id="current")
        ms.store_turn("assistant", "Einstein developed relativity.", session_id="current")

        # Current query is about cars (orthogonal to Einstein, but we mock
        # cross-session recall to match). The current-session turns should be
        # blocked by topic shift, but semantic recall may still inject tubes.
        call_count = [0]

        def _mock_embedding(text):
            call_count[0] += 1
            if "car" in text.lower() or "engine" in text.lower():
                return [0.0, 1.0, 0.0]  # matches tubes session
            return [1.0, 0.0, 0.0]  # Einstein direction

        with patch.object(ms, "_get_embedding", side_effect=_mock_embedding):
            ctx, telem = ms.assemble_context_with_telemetry(
                current_session_id="current",
                query="What's the simplest and cheapest modification you can make to your car to increase engine power?",
                depth="deep",
                mode="augmented",
            )

        # Current-session Einstein context should be blocked
        self.assertNotIn("Einstein", ctx)
        self.assertEqual(telem["memory_topic_shift_detected"], "true")

    # ------------------------------------------------------------------
    # Additional realistic topic-shift pairs
    # ------------------------------------------------------------------

    def test_cooking_to_finance_topic_shift(self):
        """Previous: cooking. Current: stock prices. Should block."""
        ms.store_turn("user", "How do I make sourdough bread?")
        ms.store_turn("assistant", "Mix flour, water, and starter...")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="What is Apple's stock price today?",
                depth="shallow",
                mode="local",
            )

        self.assertEqual(ctx, "")
        self.assertEqual(telem["memory_topic_shift_detected"], "true")

    def test_weather_followup_no_topic_shift(self):
        """Previous: weather. Current: will it rain tomorrow? Should keep."""
        ms.store_turn("user", "What's the weather in London?")
        ms.store_turn("assistant", "It's cloudy with a chance of rain.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [0.95, 0.05, 0.0],
                [1.0, 0.0, 0.0],
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Will it rain tomorrow?",
                depth="shallow",
                mode="local",
            )

        self.assertIn("London", ctx)
        self.assertNotIn("memory_topic_shift_detected", telem)

    # ------------------------------------------------------------------
    # Vague follow-ups must keep recent turns and ignore stale summaries
    # ------------------------------------------------------------------

    def test_vague_followup_keeps_recent_turns(self):
        """A vague follow-up like 'Full details please.' must keep recent turns."""
        ms.store_turn("user", "Have a look at your Architecture then give a better answer.")
        ms.store_turn("assistant", "My architecture includes PySide6/Qt6 HMI and Ollama.")

        # Force a low-similarity embedding so the naive gate would block; the
        # vague-followup override must keep context anyway.
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current query embedding (orthogonal)
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Full details please.",
                depth="deep",
                mode="local",
            )

        self.assertIn("Architecture", ctx)
        self.assertNotIn("memory_topic_shift_detected", telem)

    def test_vague_followup_drops_stale_summary(self):
        """A vague follow-up must not be answered from a stale session summary."""
        conn = ms._get_connection()
        conn.execute(
            "INSERT INTO session_summaries (session_id, summary_text, summarized_turn_count) VALUES (?, ?, ?)",
            ("default", "The user keeps asking about general relativity.", 10),
        )
        conn.commit()

        ms.store_turn("user", "Have a look at your Architecture then give a better answer.")
        ms.store_turn("assistant", "My architecture includes PySide6/Qt6 HMI and Ollama.")

        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Full details please.",
                depth="deep",
                mode="local",
            )

        self.assertIn("Architecture", ctx)
        self.assertNotIn("general relativity", ctx.lower())
        self.assertNotIn("Session summary", ctx)

    def test_vague_followup_variants(self):
        """Various vague detail requests should all be treated as follow-ups."""
        variants = [
            "Full details please.",
            "all details",
            "give me the details",
            "tell me everything",
            "details please",
        ]
        for q in variants:
            with self.subTest(query=q):
                self.assertTrue(
                    ms._is_vague_followup(q),
                    f"{q!r} should be detected as a vague follow-up",
                )

    def test_affirmation_followup_keeps_context(self):
        """Short affirmations like 'Yes, please.' must keep recent turns."""
        ms.store_turn("user", "Do you have a good recipe for roast beef and Yorkshire pudding?")
        ms.store_turn(
            "assistant",
            "I can provide you with a classic recipe... Would you like the detailed steps?",
        )

        # Orthogonal embeddings would normally trigger a topic-shift block.
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current query embedding (orthogonal)
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Yes, please.",
                depth="shallow",
                mode="local",
            )

        self.assertIn("roast beef", ctx.lower())
        self.assertNotIn("memory_topic_shift_detected", telem)
        self.assertEqual(telem["memory_context_used"], "true")

    def test_affirmation_followup_variants(self):
        """Common short affirmations should be treated as vague follow-ups."""
        variants = [
            "Yes, please.",
            "Sure.",
            "Go ahead.",
            "Yeah.",
            "Please.",
            "OK.",
            "Absolutely.",
        ]
        for q in variants:
            with self.subTest(query=q):
                self.assertTrue(
                    ms._is_vague_followup(q),
                    f"{q!r} should be detected as a vague follow-up",
                )

    # ------------------------------------------------------------------
    # Greetings / social openers must not pull stale context
    # ------------------------------------------------------------------

    def test_greeting_after_different_topic_blocks_context(self):
        """A greeting after an unrelated topic must not inject stale context."""
        ms.store_turn("user", "What is general relativity?")
        ms.store_turn(
            "assistant",
            "General relativity is a theory of gravitation developed by Albert Einstein.",
        )

        # MiniLM embedding is used by default; mock it to return orthogonal
        # vectors so the topic-shift gate is unambiguous.
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current greeting embedding
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Hi Lucy, how are you this evening?",
                depth="auto",
                mode="local",
            )

        self.assertEqual(ctx, "")
        self.assertEqual(telem["memory_topic_shift_detected"], "true")
        self.assertEqual(telem["memory_context_used"], "false")

    def test_greeting_variants_force_shallow_context(self):
        """Standalone greetings should be classified as shallow."""
        greetings = [
            "Hi Lucy",
            "Hello",
            "hey there",
            "Good evening",
            "How are you?",
            "How are you doing?",
            "How's it going?",
            "What's up?",
            "Hi Lucy, how are you this evening?",
        ]
        for q in greetings:
            with self.subTest(query=q):
                self.assertEqual(
                    ms._detect_context_depth(q),
                    "shallow",
                    f"{q!r} should be a shallow-context greeting",
                )

    def test_temporal_this_does_not_force_deep_context(self):
        """'this evening/morning/etc.' is temporal, not a conversational reference."""
        self.assertEqual(ms._detect_context_depth("this evening"), "shallow")
        self.assertEqual(ms._detect_context_depth("Call me this morning"), "shallow")

    # ------------------------------------------------------------------
    # Explicit continuation markers must keep context
    # ------------------------------------------------------------------

    def test_explicit_continuation_markers_are_vague_followups(self):
        """Phrases like 'Back to...' and 'One more thing about...' keep context."""
        continuations = [
            "Back to what we discussed earlier",
            "Returning to the budget question",
            "As for the timeline",
            "Speaking of relativity",
            "Regarding your last point",
            "One more thing about the project",
            "Another question: why is it slow?",
            "Also, what about the cost?",
            "Plus we need to consider safety",
            "What about this evening?",
            "How about using Python?",
        ]
        for q in continuations:
            with self.subTest(query=q):
                self.assertTrue(
                    ms._is_vague_followup(q),
                    f"{q!r} should be treated as a continuation",
                )

    def test_hello_one_more_thing_keeps_context(self):
        """'Hello—one more thing about relativity' should keep recent turns."""
        ms.store_turn("user", "What is general relativity?")
        ms.store_turn(
            "assistant",
            "General relativity is a theory of gravitation developed by Albert Einstein.",
        )

        # Force orthogonal embeddings so the naive gate would block.
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],  # previous turn embedding
                [0.0, 1.0, 0.0],  # current query embedding
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="Hello—one more thing about relativity",
                depth="auto",
                mode="local",
            )

        self.assertIn("Einstein", ctx)
        self.assertNotIn("memory_topic_shift_detected", telem)

    # ------------------------------------------------------------------
    # Bilingual greetings
    # ------------------------------------------------------------------

    def test_bilingual_greetings_force_shallow_context(self):
        """Common non-English greetings should be classified as shallow."""
        greetings = [
            # European (common second languages)
            "Hola",
            "Buenos días",
            "Buenas tardes",
            "¿Qué tal?",
            "Bonjour",
            "Bonsoir",
            "Salut",
            "Ça va",
            "Hallo",
            "Guten Tag",
            "Ciao",
            "Buongiorno",
            "Olá",
            "Bom dia",
        ]
        for q in greetings:
            with self.subTest(query=q):
                self.assertEqual(
                    ms._detect_context_depth(q),
                    "shallow",
                    f"{q!r} should be a shallow-context greeting",
                )

    # ------------------------------------------------------------------
    # Age-of-context guard
    # ------------------------------------------------------------------

    def test_old_previous_turn_does_not_trigger_topic_shift(self):
        """A short follow-up after a long pause should not be treated as a shift."""
        conn = ms._get_connection()
        # Insert an old user turn directly so we control the timestamp.
        old_ts = "2026-01-01T00:00:00Z"
        conn.execute(
            "INSERT INTO conversation_turns (session_id, role, text, created_at) VALUES (?, ?, ?, ?)",
            ("default", "user", "What did Albert Einstein discover?", old_ts),
        )
        conn.commit()

        # Even with orthogonal embeddings, the age guard should prevent a shift.
        with patch.object(
            ms,
            "_get_embedding",
            side_effect=[
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
        ):
            ctx, telem = ms.assemble_context_with_telemetry(
                query="What is the fastest car?",
                depth="shallow",
                mode="local",
            )

        self.assertIn("Einstein", ctx)
        self.assertNotIn("memory_topic_shift_detected", telem)


if __name__ == "__main__":
    unittest.main()
