#!/usr/bin/env python3
"""Unit tests for the LoRA dataset builder."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import build_datasets as bd


class TestBuildDatasets(unittest.TestCase):
    """Tests for build_datasets.py"""

    def test_build_persona_dataset_schema(self) -> None:
        """Generated examples contain the required fields and valid values."""
        examples = bd.build_persona_dataset("michael", synthetic_count=2, seed=1)
        self.assertGreater(len(examples), 0)
        for ex in examples:
            self.assertEqual(ex.persona, "michael")
            self.assertIn(ex.source, {"spec_example", "synthetic", "replay"})
            self.assertTrue(ex.instruction)
            self.assertTrue(ex.response)
            self.assertTrue(ex.rule_tag)

    def test_forbidden_patterns_filtered(self) -> None:
        """Examples containing forbidden sycophancy patterns are rejected."""
        # The spec examples and synthetic generator should not produce these.
        examples = bd.build_persona_dataset("michael", synthetic_count=3, seed=1)
        for ex in examples:
            text = f"{ex.instruction} {ex.response}"
            for pattern in bd.FORBIDDEN_PATTERNS:
                self.assertIsNone(
                    pattern.search(text),
                    f"Forbidden pattern matched in michael: {text[:120]}",
                )

    def test_replay_examples_neutral(self) -> None:
        """Replay examples are persona-neutral and cover diverse topics."""
        self.assertGreaterEqual(len(bd.REPLAY_EXAMPLES), 10)
        for instruction, response in bd.REPLAY_EXAMPLES:
            self.assertTrue(instruction)
            self.assertTrue(response)

    def test_dataset_output_roundtrip(self) -> None:
        """write_jsonl produces valid JSONL that can be re-read."""
        examples = bd.build_persona_dataset("michael", synthetic_count=1, seed=1)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "michael.jsonl"
            bd.write_jsonl(examples, path)
            lines = path.read_text(encoding="utf-8").strip().split("\n")
            self.assertEqual(len(lines), len(examples))
            for line in lines:
                record = json.loads(line)
                self.assertIn("instruction", record)
                self.assertIn("response", record)
                self.assertIn("persona", record)
                self.assertIn("rule_tag", record)
                self.assertIn("source", record)


if __name__ == "__main__":
    unittest.main()
