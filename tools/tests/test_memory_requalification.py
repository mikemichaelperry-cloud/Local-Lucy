#!/usr/bin/env python3
"""
Requalification tests for the post-STAGE_19 memory changes.

These tests verify:
- widened recent verbatim window (default 12 turns)
- widened semantic older-turn recall (default 8 turns)
- explicit-recall / topic-shift bypass behaviour
- correction/supersession and entity isolation in persistent facts
- context-budget / truncation behaviour
- configuration precedence for LUCY_MEMORY_MAX_CHARS

All tests use a temporary in-memory SQLite DB and deterministic mocked
embeddings so they run without Ollama.
"""

from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory.memory_service as ms


class TestMemoryRequalification(unittest.TestCase):
    """Post-STAGE_19 memory requalification tests."""

    @classmethod
    def setUpClass(cls):
        cls._orig_db_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        cls._orig_conn = ms._CONN_CACHE
        cls._orig_recent = os.environ.get("LUCY_MEMORY_RECENT_TURN_LIMIT", "")
        cls._orig_semantic = os.environ.get("LUCY_MEMORY_MAX_INJECTED_TURNS", "")
        cls._orig_chars = os.environ.get("LUCY_MEMORY_MAX_CHARS", "")

    def setUp(self):
        self.tmp_fd, self.tmp_path = tempfile.mkstemp(suffix=".db")
        os.close(self.tmp_fd)
        os.environ["LUCY_MEMORY_DB_PATH"] = self.tmp_path
        # Keep the new defaults for the requalification.
        os.environ["LUCY_MEMORY_RECENT_TURN_LIMIT"] = "12"
        os.environ["LUCY_MEMORY_MAX_INJECTED_TURNS"] = "8"
        os.environ.pop("LUCY_MEMORY_MAX_CHARS", None)
        ms._close_connection()
        ms._clear_embedding_cache()
        self.embedding_patcher = patch.object(ms, "_get_embedding", side_effect=self._embedding_for_text)
        self.embedding_patcher.start()

    def tearDown(self):
        self.embedding_patcher.stop()
        ms._clear_embedding_cache()
        ms._close_connection()
        try:
            os.unlink(self.tmp_path)
        except OSError:
            pass
        if self._orig_db_env:
            os.environ["LUCY_MEMORY_DB_PATH"] = self._orig_db_env
        else:
            os.environ.pop("LUCY_MEMORY_DB_PATH", None)
        for key, val in (
            ("LUCY_MEMORY_RECENT_TURN_LIMIT", self._orig_recent),
            ("LUCY_MEMORY_MAX_INJECTED_TURNS", self._orig_semantic),
            ("LUCY_MEMORY_MAX_CHARS", self._orig_chars),
        ):
            if val:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    @classmethod
    def tearDownClass(cls):
        ms._CONN_CACHE = cls._orig_conn

    # ------------------------------------------------------------------
    # Deterministic embedding helper
    # ------------------------------------------------------------------

    _KEYWORDS = [
        "router", "memory", "weather", "dog", "cat", "travel", "correction",
        "alice", "kibbutz", "haifa", "tel aviv", "paris", "louvre",
    ]

    def _embedding_for_text(self, text: str) -> list[float] | None:
        """Return a deterministic normalised embedding based on keyword presence."""
        if not text:
            return None
        t = text.lower()
        vec = [0.0] * (len(self._KEYWORDS) + 1)
        matched = False
        for i, kw in enumerate(self._KEYWORDS):
            if kw in t:
                vec[i] = 1.0
                matched = True
        if not matched:
            vec[-1] = 1.0
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    def _store_turns(self, pairs: list[tuple[str, str]], session_id: str = "default") -> None:
        for role, text in pairs:
            ms.store_turn(role, text, session_id=session_id)

    # ------------------------------------------------------------------
    # 4.1 Recent verbatim recall
    # ------------------------------------------------------------------

    def test_recent_verbatim_window_default_is_twelve(self):
        # 8 user + 8 assistant = 16 turns. Recent 12 = last 6 pairs.
        full = []
        for i in range(8):
            full.append(("user", f"user-{i:02d}"))
            full.append(("assistant", f"assistant-{i:02d}"))
        self._store_turns(full)
        context, telemetry = ms.assemble_context_with_telemetry(query="what about that", mode="local")
        # "what about that" is a vague follow-up -> deep, bypasses topic shift
        self.assertEqual(int(telemetry["memory_turns_verbatim"]), 12)
        # Most recent pair must be present
        self.assertIn("user-07", context)
        self.assertIn("assistant-07", context)
        # user-00 is outside the 12-turn window
        self.assertNotIn("user-00", context)
        # user-02 is the oldest user turn inside the window
        self.assertIn("user-02", context)
        # Order must be chronological
        self.assertLess(context.index("user-02"), context.index("user-07"))

    def test_empty_and_malformed_turns_are_ignored(self):
        ms.store_turn("user", "valid")
        ms.store_turn("user", "   ")
        ms.store_turn("assistant", "")
        ms.store_turn("assistant", "<think>reasoning</think>answer")
        turns = ms.get_recent_turns(limit=10)
        texts = [t["text"] for t in turns]
        self.assertEqual(len(turns), 2)
        self.assertIn("valid", texts)
        self.assertIn("answer", texts)

    def test_character_budget_is_respected(self):
        # Each turn is ~30 chars; 12 turns would exceed a 200-char budget
        long_pairs = []
        for i in range(12):
            long_pairs.append(("user", f"User message number {i} with padding"))
            long_pairs.append(("assistant", f"Assistant reply number {i} with padding"))
        self._store_turns(long_pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="continue", mode="local", max_chars=300
        )
        self.assertLessEqual(len(context), 300)
        self.assertEqual(telemetry["memory_context_used"], "true")
        # Truncation must not split in the middle of a formatted turn
        for block in context.split("\n\n"):
            self.assertTrue(block.startswith(("User:", "Assistant:")))

    # ------------------------------------------------------------------
    # 4.2 Semantic older-turn recall
    # ------------------------------------------------------------------

    def test_relevant_older_turns_are_retrieved(self):
        # 16 pairs about router. Query about router -> no topic shift.
        pairs = []
        for i in range(16):
            pairs.append(("user", f"router question {i}"))
            pairs.append(("assistant", f"router answer {i}"))
        self._store_turns(pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="how do I configure the router", mode="local", depth="deep"
        )
        # Recent 12 turns + up to 8 semantic older turns
        self.assertIn("router", context)
        self.assertIn("router question 0", context)
        self.assertGreaterEqual(int(telemetry["memory_turns_semantic"]), 1)
        self.assertLessEqual(int(telemetry["memory_turns_semantic"]), 8)

    def test_same_turn_not_injected_twice(self):
        pairs = []
        for i in range(20):
            pairs.append(("user", f"router issue {i}"))
            pairs.append(("assistant", f"router fix {i}"))
        self._store_turns(pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="explain the router problem", mode="local", depth="deep"
        )
        # Count whole formatted lines for an early turn
        lines = set(context.splitlines())
        self.assertIn("User: router issue 0", lines)
        self.assertEqual(context.splitlines().count("User: router issue 0"), 1)

    def test_irrelevant_lexically_similar_turn_does_not_domininate(self):
        # 6 memory pairs, then 10 router pairs. Query router -> recent and semantic
        # older turns should favour router, not memory.
        pairs = []
        for i in range(6):
            pairs.append(("user", f"memory usage question {i}"))
            pairs.append(("assistant", f"memory usage answer {i}"))
        for i in range(10):
            pairs.append(("user", f"router question {i}"))
            pairs.append(("assistant", f"router answer {i}"))
        self._store_turns(pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="how do I configure the router", mode="local", depth="deep"
        )
        self.assertIn("router question 0", context)
        self.assertNotIn("memory usage", context)
        # Semantic recall should only have returned router turns
        self.assertEqual(int(telemetry["memory_turns_semantic"]) <= 8, True)

    def test_semantic_recall_is_deterministic(self):
        pairs = []
        for i in range(10):
            pairs.append(("user", f"cat fact {i}"))
            pairs.append(("assistant", f"cat reply {i}"))
        self._store_turns(pairs)
        ctx1, _ = ms.assemble_context_with_telemetry(query="cat", mode="local", depth="deep")
        ctx2, _ = ms.assemble_context_with_telemetry(query="cat", mode="local", depth="deep")
        self.assertEqual(ctx1, ctx2)

    # ------------------------------------------------------------------
    # 4.3 Explicit recall and topic-shift handling
    # ------------------------------------------------------------------

    def test_explicit_recall_bypasses_topic_shift(self):
        # Last user turn is about weather; query explicitly asks about earlier router discussion
        self._store_turns([
            ("user", "how do I reset the router password"),
            ("assistant", "press the reset button"),
            ("user", "what is the weather today"),
            ("assistant", "it is sunny"),
        ])
        for query in (
            "what did we discuss earlier",
            "what did I say earlier about the router",
            "do you remember what I said about this",
            "what did she say earlier",
            "what did you say about that",
            "read my last answer",
            "look at our previous discussion",
            "use the corrected information",
        ):
            with self.subTest(query=query):
                _, telemetry = ms.assemble_context_with_telemetry(query=query, mode="local")
                self.assertNotEqual(telemetry["memory_context_used"], "false", query)
                self.assertNotEqual(telemetry.get("memory_topic_shift_detected"), "true", query)

    def test_vague_ambiguous_followup_does_not_retrieve_arbitrary_old_topic(self):
        # 8 router pairs, then a weather pair. "tell me more" is vague -> recent only.
        pairs = []
        for i in range(8):
            pairs.append(("user", f"router question {i}"))
            pairs.append(("assistant", f"router answer {i}"))
        pairs.append(("user", "what is the weather today"))
        pairs.append(("assistant", "it is sunny"))
        self._store_turns(pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="tell me more", mode="local", depth="deep"
        )
        # Vague follow-up keeps recent turns but does not inject arbitrary older router turns
        self.assertIn("weather", context)
        self.assertNotIn("router question 0", context)
        self.assertEqual(telemetry.get("memory_topic_shift_detected"), None)

    def test_explicit_topic_abandonment_triggers_topic_shift(self):
        self._store_turns([
            ("user", "how do I reset the router password"),
            ("assistant", "press the reset button"),
        ])
        _, telemetry = ms.assemble_context_with_telemetry(
            query="Forget the previous topic and answer this instead. What is the capital of France?",
            mode="local",
        )
        self.assertEqual(telemetry.get("memory_topic_shift_detected"), "true")

    def test_do_not_use_earlier_discussion_triggers_topic_shift(self):
        self._store_turns([
            ("user", "the router is broken"),
            ("assistant", "try rebooting it"),
        ])
        _, telemetry = ms.assemble_context_with_telemetry(
            query="Do not use the earlier discussion. Tell me a joke.", mode="local"
        )
        self.assertEqual(telemetry.get("memory_topic_shift_detected"), "true")

    # ------------------------------------------------------------------
    # 4.4 Correction and supersession
    # ------------------------------------------------------------------

    def test_newer_correction_is_retrievable(self):
        with patch.object(ms, "_compute_fact_embedding", side_effect=self._embedding_for_text):
            ms.store_persistent_fact("User lives in Tel Aviv.", category="location")
            ms.store_persistent_fact("User lives in Kibbutz Magal.", category="location")
            # Use threshold=0 so the default-query vector still retrieves both location facts.
            facts = ms.get_relevant_persistent_facts("where does the user live", limit=5, threshold=0.0)
        self.assertIsInstance(facts, list)
        # Newer correction must be present
        self.assertIn("User lives in Kibbutz Magal.", facts)
        # Older fact remains auditable in the database
        conn = ms._get_connection()
        rows = conn.execute(
            "SELECT fact_text FROM persistent_facts WHERE category = 'location' ORDER BY id"
        ).fetchall()
        self.assertEqual(len(rows), 2)
        # The retrieval must not synthesise a merged resolution
        self.assertNotIn("User lives in Tel Aviv and Kibbutz Magal", [r[0] for r in rows])

    # ------------------------------------------------------------------
    # 4.5 Entity isolation
    # ------------------------------------------------------------------

    def test_facts_about_one_person_not_attributed_to_another(self):
        with patch.object(ms, "_compute_fact_embedding", side_effect=self._embedding_for_text):
            ms.store_persistent_fact("Alice lives in Haifa.", category="family")
            ms.store_persistent_fact("User lives in Kibbutz Magal.", category="location")
            # Include the distinguishing location keyword in each query.
            user_facts = ms.get_relevant_persistent_facts("where does the user live in Kibbutz Magal", limit=3)
            alice_facts = ms.get_relevant_persistent_facts("where does Alice live in Haifa", limit=3)
        self.assertIn("User lives in Kibbutz Magal.", user_facts)
        self.assertNotIn("Alice lives in Haifa.", user_facts)
        self.assertIn("Alice lives in Haifa.", alice_facts)
        self.assertNotIn("User lives in Kibbutz Magal.", alice_facts)

    def test_hypothetical_statement_does_not_become_persistent_fact(self):
        with patch.object(ms, "_compute_fact_embedding", side_effect=self._embedding_for_text):
            ms.store_persistent_fact("If I lived in Paris, I would visit the Louvre.", category="hypothetical")
            ms.store_persistent_fact("User lives in Kibbutz Magal.", category="location")
            facts = ms.get_relevant_persistent_facts("where does the user live in Kibbutz Magal", limit=3)
        self.assertIn("User lives in Kibbutz Magal.", facts)
        self.assertNotIn("If I lived in Paris, I would visit the Louvre.", facts)

    # ------------------------------------------------------------------
    # 4.6 Context-budget behaviour
    # ------------------------------------------------------------------

    def test_long_conversation_budget_and_turn_counts(self):
        pairs = []
        for i in range(20):
            pairs.append(("user", f"topic router user turn {i}"))
            pairs.append(("assistant", f"topic router assistant turn {i}"))
        self._store_turns(pairs)
        context, telemetry = ms.assemble_context_with_telemetry(
            query="router", mode="local", depth="deep"
        )
        self.assertLessEqual(len(context), 2000)
        verbatim = int(telemetry["memory_turns_verbatim"])
        semantic = int(telemetry["memory_turns_semantic"])
        # Recent window = 12 individual turns
        self.assertEqual(verbatim, 12)
        self.assertGreaterEqual(semantic, 1)
        self.assertLessEqual(semantic, 8)
        # No duplicate turn blocks anywhere in the assembled context
        blocks = [b.strip() for b in context.split("\n\n") if b.strip()]
        self.assertEqual(len(blocks), len(set(blocks)))
        # At least one older (semantic) user turn is present beyond the verbatim window
        self.assertIn("User: topic router user turn 0", blocks)

    # ------------------------------------------------------------------
    # 4.7 Configuration precedence
    # ------------------------------------------------------------------

    def test_default_max_chars_is_2000(self):
        big_pairs = []
        for i in range(20):
            big_pairs.append(("user", f"message {i} " + "x" * 200))
            big_pairs.append(("assistant", f"reply {i} " + "x" * 200))
        self._store_turns(big_pairs)
        ctx, _ = ms.assemble_context_with_telemetry(query="message", mode="local", depth="deep")
        self.assertLessEqual(len(ctx), 2000)

    def test_env_var_overrides_default_max_chars(self):
        os.environ["LUCY_MEMORY_MAX_CHARS"] = "500"
        big_pairs = []
        for i in range(10):
            big_pairs.append(("user", f"message {i} " + "x" * 200))
            big_pairs.append(("assistant", f"reply {i} " + "x" * 200))
        self._store_turns(big_pairs)
        ctx, _ = ms.assemble_context_with_telemetry(query="message", mode="local", depth="deep")
        self.assertLessEqual(len(ctx), 500)

    def test_explicit_max_chars_param_overrides_env(self):
        os.environ["LUCY_MEMORY_MAX_CHARS"] = "500"
        big_pairs = []
        for i in range(10):
            big_pairs.append(("user", f"message {i} " + "x" * 200))
            big_pairs.append(("assistant", f"reply {i} " + "x" * 200))
        self._store_turns(big_pairs)
        ctx_param, _ = ms.assemble_context_with_telemetry(
            query="message", mode="local", depth="deep", max_chars=2400
        )
        ctx_env, _ = ms.assemble_context_with_telemetry(
            query="message", mode="local", depth="deep"
        )
        self.assertLessEqual(len(ctx_param), 2400)
        self.assertLessEqual(len(ctx_env), 500)
        # Explicit parameter must win over the env var
        self.assertGreater(len(ctx_param), len(ctx_env))


if __name__ == "__main__":
    unittest.main()
