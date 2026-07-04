#!/usr/bin/env python3
"""Unit tests for the local light-RAG retriever."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.local_rag import LocalRAGRetriever, is_local_rag_enabled


class TestLocalRAGRetriever(unittest.TestCase):
    """Tests for LocalRAGRetriever retrieval and formatting."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.notes_dir = Path(self.tmpdir.name) / "approved"
        self.notes_dir.mkdir()
        self.retriever = LocalRAGRetriever(
            memory_notes_dir=self.notes_dir,
            fact_limit=2,
            note_limit=2,
            max_results=4,
        )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _write_note(self, filename: str, body: str, frontmatter: str = "") -> Path:
        path = self.notes_dir / filename
        if frontmatter:
            content = frontmatter.rstrip() + "\n\n" + body
        else:
            content = body
        path.write_text(content, encoding="utf-8")
        return path

    @patch("router_py.local_rag._get_relevant_persistent_facts")
    def test_retrieve_combines_facts_and_notes(self, mock_facts):
        mock_facts.return_value = ["Oscar should ignore cats."]
        self._write_note(
            "oscar.txt",
            "Training log: leave-it cue plus distance and reward for cat distraction.",
            frontmatter="[PROPOSAL]\nid: oscar-001",
        )

        results = self.retriever.retrieve("How do I stop my dog chasing cats?")
        sources = {r["source"] for r in results}

        self.assertIn("persistent_fact", sources)
        self.assertTrue(any("memory_note:" in s for s in sources))
        self.assertLessEqual(len(results), 4)
        # Body must be extracted, not the frontmatter id line.
        for r in results:
            self.assertNotIn("[PROPOSAL]", r["text"])

    @patch("router_py.local_rag._get_relevant_persistent_facts")
    def test_deduplicates_identical_text(self, mock_facts):
        fact_text = "Remember to water the ficus on Tuesdays."
        mock_facts.return_value = [fact_text]
        self._write_note("ficus.txt", fact_text)

        results = self.retriever.retrieve("When should I water the ficus?")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source"], "persistent_fact")

    @patch("router_py.local_rag._get_relevant_persistent_facts")
    def test_no_results_when_nothing_matches(self, mock_facts):
        mock_facts.return_value = []
        self._write_note("random.txt", "Quantum entanglement and superposition.")

        results = self.retriever.retrieve("What is the weather in Paris?")
        self.assertEqual(results, [])
        self.assertFalse(self.retriever.has_results("What is the weather in Paris?"))

    def test_format_context_returns_none_when_empty(self):
        retriever = LocalRAGRetriever(
            memory_notes_dir=self.notes_dir,
            fact_limit=2,
            note_limit=2,
        )
        context, sources = retriever.format_context("totally unrelated query")
        self.assertIsNone(context)
        self.assertIsNone(sources)

    @patch("router_py.local_rag._get_relevant_persistent_facts")
    def test_format_context_builds_numbered_block(self, mock_facts):
        mock_facts.return_value = ["Rachel's birthday is in March."]
        context, sources = self.retriever.format_context("When is Rachel's birthday?")

        self.assertIsNotNone(context)
        self.assertIn("Rachel's birthday is in March.", context)
        self.assertIn("persistent_fact", sources or [])
        self.assertTrue(context.startswith("1. persistent_fact"))

    def test_note_scoring_ignores_short_and_stopwords(self):
        # "the" and "a" are stopwords; "is" is too short/stopword; only "banana" matters.
        self._write_note("fruit.txt", "The banana is a fruit.")
        results = self.retriever.retrieve("Tell me about bananas")
        self.assertEqual(len(results), 1)
        self.assertIn("banana", results[0]["text"].lower())


class TestLocalRAGEnablement(unittest.TestCase):
    """Tests for the LUCY_ENABLE_LOCAL_RAG toggle."""

    def test_enabled_by_default(self):
        self.assertTrue(is_local_rag_enabled())

    def test_disabled_when_env_set(self):
        for value in ("0", "false", "no", "off"):
            with patch.dict(os.environ, {"LUCY_ENABLE_LOCAL_RAG": value}):
                self.assertFalse(is_local_rag_enabled())


if __name__ == "__main__":
    unittest.main()
