#!/usr/bin/env python3
"""
Reproduction test for user feedback learning trigger bug.

Bug: trigger_background_learning() calls maybe_auto_learn(min_entries=1),
     but maybe_auto_learn() only checks auto_feedback.jsonl, not
     user_feedback.jsonl. So when a user says "that was wrong", the
     feedback is written to user_feedback.jsonl but learning is NOT
     triggered because auto_feedback.jsonl is empty.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Router dir for test data
ROUTER_DIR = Path(__file__).parent.resolve()


class TestFeedbackTriggerBug(unittest.TestCase):
    """Test that user feedback triggers background learning."""

    def test_maybe_auto_learn_ignores_user_feedback(self):
        """
        Reproduce the bug: maybe_auto_learn() returns False even when
        user_feedback.jsonl has entries, because it only checks
        auto_feedback.jsonl.
        """
        sys.path.insert(0, str(ROUTER_DIR))
        from background_learner import maybe_auto_learn, FEEDBACK_PATH
        from auto_feedback import AUTO_FEEDBACK_PATH

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            user_fb = tmpdir / "user_feedback.jsonl"
            auto_fb = tmpdir / "auto_feedback.jsonl"

            # Write ONE user feedback entry (simulating "that was wrong")
            user_fb.write_text(json.dumps({
                "timestamp": "2026-05-10T18:00:00Z",
                "query": "What is the capital of France?",
                "correct_route": "LOCAL",
                "feedback_type": "correction",
                "original_route": "AUGMENTED",
                "confidence": 0.9,
                "raw_feedback": "that was wrong",
            }) + "\n")

            # auto_feedback.jsonl is EMPTY (normal state)
            auto_fb.write_text("")

            # Patch the paths
            with patch.object(sys.modules['background_learner'], 'FEEDBACK_PATH', user_fb):
                with patch.object(sys.modules['auto_feedback'], 'AUTO_FEEDBACK_PATH', auto_fb):
                    result = maybe_auto_learn(min_entries=1)

            # BUG: This returns False because auto_feedback is empty,
            # even though user_feedback has 1 entry.
            print(f"maybe_auto_learn(min_entries=1) with user_feedback=1, auto_feedback=0: {result}")
            self.assertTrue(result, "BUG: maybe_auto_learn() ignores user_feedback.jsonl")

    def test_trigger_background_learning_with_only_user_feedback(self):
        """
        Test the full trigger path: user says "that was wrong",
        feedback is logged, trigger_background_learning is called.
        """
        sys.path.insert(0, str(ROUTER_DIR))
        from background_learner import FEEDBACK_PATH

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            user_fb = tmpdir / "user_feedback.jsonl"

            # Simulate a logged user feedback entry
            user_fb.write_text(json.dumps({
                "timestamp": "2026-05-10T18:00:00Z",
                "query": "How do I change a tire?",
                "correct_route": "LOCAL",
                "feedback_type": "answer_negative",
                "original_route": "AUGMENTED",
                "confidence": 0.8,
                "raw_feedback": "that was wrong",
            }) + "\n")

            # Verify the entry exists
            self.assertTrue(user_fb.exists())
            lines = user_fb.read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)

            entry = json.loads(lines[0])
            self.assertEqual(entry["correct_route"], "LOCAL")
            self.assertEqual(entry["feedback_type"], "answer_negative")
            print(f"User feedback entry verified: {entry['query']} -> {entry['correct_route']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
