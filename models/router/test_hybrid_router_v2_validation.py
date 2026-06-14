#!/usr/bin/env python3
"""
Regression tests for HybridRouterV2 example validation.

Proves that empty, blank, or structurally invalid training examples
are rejected at load time and cannot pollute the embedding index.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure router module is on path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))

from hybrid_router_v2 import HybridRouterV2


class TestExampleValidation(unittest.TestCase):
    """Test that invalid examples are rejected on router load."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.examples_path = Path(self.tmp_dir) / "test_examples.json"
        self.embeddings_path = Path(self.tmp_dir) / "test_embeddings.npy"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _write_examples(self, examples: list[dict]) -> None:
        with open(self.examples_path, "w") as f:
            json.dump(examples, f)

    def test_rejects_empty_query_string(self):
        """An example with empty query text must be dropped."""
        self._write_examples([
            {"query": "What is Python?", "labels": {"route": "LOCAL", "intent_family": "local_answer"}, "metadata": {}},
            {"query": "", "labels": {"route": "WEATHER", "intent_family": "ephemeral_query"}, "metadata": {}},
            {"query": "What time is it?", "labels": {"route": "TIME", "intent_family": "time_query"}, "metadata": {}},
        ])

        router = HybridRouterV2(
            embeddings_path=str(self.embeddings_path),
            examples_path=str(self.examples_path),
        )
        router._lazy_init()

        queries = [ex["query"] for ex in router.examples]
        self.assertIn("What is Python?", queries)
        self.assertIn("What time is it?", queries)
        self.assertNotIn("", queries)
        self.assertEqual(len(router.examples), 2)

    def test_rejects_blank_query_string(self):
        """An example with whitespace-only query text must be dropped."""
        self._write_examples([
            {"query": "What is Python?", "labels": {"route": "LOCAL", "intent_family": "local_answer"}, "metadata": {}},
            {"query": "   \t\n  ", "labels": {"route": "WEATHER", "intent_family": "ephemeral_query"}, "metadata": {}},
            {"query": "What time is it?", "labels": {"route": "TIME", "intent_family": "time_query"}, "metadata": {}},
        ])

        router = HybridRouterV2(
            embeddings_path=str(self.embeddings_path),
            examples_path=str(self.examples_path),
        )
        router._lazy_init()

        queries = [ex["query"] for ex in router.examples]
        self.assertNotIn("   \t\n  ", queries)
        self.assertEqual(len(router.examples), 2)

    def test_rejects_missing_labels(self):
        """An example without a labels dict must be dropped."""
        self._write_examples([
            {"query": "What is Python?", "labels": {"route": "LOCAL", "intent_family": "local_answer"}, "metadata": {}},
            {"query": "What is the weather?", "metadata": {}},
            {"query": "What time is it?", "labels": {"route": "TIME", "intent_family": "time_query"}, "metadata": {}},
        ])

        router = HybridRouterV2(
            embeddings_path=str(self.embeddings_path),
            examples_path=str(self.examples_path),
        )
        router._lazy_init()

        queries = [ex["query"] for ex in router.examples]
        self.assertNotIn("What is the weather?", queries)
        self.assertEqual(len(router.examples), 2)

    def test_rejects_missing_route(self):
        """An example with labels but no route must be dropped."""
        self._write_examples([
            {"query": "What is Python?", "labels": {"route": "LOCAL", "intent_family": "local_answer"}, "metadata": {}},
            {"query": "What is the weather?", "labels": {"intent_family": "ephemeral_query"}, "metadata": {}},
            {"query": "What time is it?", "labels": {"route": "TIME", "intent_family": "time_query"}, "metadata": {}},
        ])

        router = HybridRouterV2(
            embeddings_path=str(self.embeddings_path),
            examples_path=str(self.examples_path),
        )
        router._lazy_init()

        queries = [ex["query"] for ex in router.examples]
        self.assertNotIn("What is the weather?", queries)
        self.assertEqual(len(router.examples), 2)

    def test_rejects_non_dict_entry(self):
        """A non-dict entry in the examples list must be dropped."""
        self._write_examples([
            {"query": "What is Python?", "labels": {"route": "LOCAL", "intent_family": "local_answer"}, "metadata": {}},
            "this is not a dict",
            {"query": "What time is it?", "labels": {"route": "TIME", "intent_family": "time_query"}, "metadata": {}},
        ])

        router = HybridRouterV2(
            embeddings_path=str(self.embeddings_path),
            examples_path=str(self.examples_path),
        )
        router._lazy_init()

        queries = [ex["query"] for ex in router.examples]
        self.assertNotIn("this is not a dict", queries)
        self.assertEqual(len(router.examples), 2)

    def test_python_query_routes_local(self):
        """After fixing the mislabeled example, 'What is Python?' must route LOCAL."""
        router = HybridRouterV2(
            embeddings_path=str(Path(__file__).parent / "comprehensive_embeddings.npy"),
            examples_path=str(Path(__file__).parent / "comprehensive_examples.json"),
        )
        result = router.predict("What is Python?")
        self.assertEqual(result["route"], "LOCAL")
        self.assertGreater(result["confidence"], 0.5)
        # Top neighbour should be the exact-match example
        top1 = result.get("top_k_neighbours", [{}])[0]
        self.assertEqual(top1.get("query"), "What is Python?")
        self.assertEqual(top1.get("route"), "LOCAL")


if __name__ == "__main__":
    unittest.main()
