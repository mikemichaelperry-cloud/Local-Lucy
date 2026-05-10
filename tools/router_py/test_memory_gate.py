#!/usr/bin/env python3
"""
Unit tests for the memory-aware routing gate.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure router_py and memory modules are importable
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from classify import _memory_routing_gate


class TestMemoryRoutingGate(unittest.TestCase):
    """Test the _memory_routing_gate helper."""

    def setUp(self):
        """Clear memory env vars before each test."""
        self._orig_memory = os.environ.pop("LUCY_SESSION_MEMORY", None)
        self._orig_gate = os.environ.pop("LUCY_MEMORY_GATE", None)

    def tearDown(self):
        """Restore memory env vars after each test."""
        if self._orig_memory is not None:
            os.environ["LUCY_SESSION_MEMORY"] = self._orig_memory
        elif "LUCY_SESSION_MEMORY" in os.environ:
            del os.environ["LUCY_SESSION_MEMORY"]

        if self._orig_gate is not None:
            os.environ["LUCY_MEMORY_GATE"] = self._orig_gate
        elif "LUCY_MEMORY_GATE" in os.environ:
            del os.environ["LUCY_MEMORY_GATE"]

    # ------------------------------------------------------------------
    # Fast-reject paths (no DB lookup needed)
    # ------------------------------------------------------------------

    def test_gate_disabled_when_memory_off(self):
        """Gate returns None when LUCY_SESSION_MEMORY is not set."""
        os.environ["LUCY_SESSION_MEMORY"] = "0"
        result = _memory_routing_gate("What about that?", "WEATHER")
        self.assertIsNone(result)

    def test_gate_disabled_by_kill_switch(self):
        """Gate returns None when LUCY_MEMORY_GATE=0."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        os.environ["LUCY_MEMORY_GATE"] = "0"
        result = _memory_routing_gate("What about that?", "WEATHER")
        self.assertIsNone(result)

    def test_gate_noop_when_already_local(self):
        """Gate returns None when embedding route is already LOCAL."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        result = _memory_routing_gate("What about that?", "LOCAL")
        self.assertIsNone(result)

    def test_gate_noop_for_self_contained_query(self):
        """Gate returns None for queries without follow-up markers."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        result = _memory_routing_gate("What is the capital of France?", "AUGMENTED")
        self.assertIsNone(result)

    # ------------------------------------------------------------------
    # Memory-dependent paths (require DB or fallback file)
    # ------------------------------------------------------------------

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_overrides_when_memory_exists(self, mock_get_turns):
        """Gate overrides WEATHER -> LOCAL when follow-up and turns exist."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "My name is Mike"},
            {"role": "assistant", "text": "Nice to meet you, Mike."},
        ]
        result = _memory_routing_gate("What about that?", "WEATHER")
        self.assertEqual(result, "LOCAL")
        mock_get_turns.assert_called_once_with(session_id="default", limit=2)

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_noop_when_memory_empty(self, mock_get_turns):
        """Gate returns None when SQLite is empty."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = []
        result = _memory_routing_gate("What about that?", "WEATHER")
        self.assertIsNone(result)

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_explicit_recall(self, mock_get_turns):
        """Gate overrides to LOCAL for explicit recall queries."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "I live in Tel Aviv"},
        ]
        result = _memory_routing_gate("What did I say my name was?", "AUGMENTED")
        self.assertEqual(result, "LOCAL")

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_pronoun_followup(self, mock_get_turns):
        """Gate overrides to LOCAL for pronoun-heavy follow-ups."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "I bought a new car"},
        ]
        result = _memory_routing_gate("Should we keep using it?", "AUGMENTED")
        self.assertEqual(result, "LOCAL")

    # ------------------------------------------------------------------
    # Live-data keyword guard
    # ------------------------------------------------------------------

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_preserves_weather_with_followup(self, mock_get_turns):
        """Gate does NOT override 'What about the weather?' — live-data guard."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "Something earlier"},
        ]
        result = _memory_routing_gate("What about the weather?", "WEATHER")
        self.assertIsNone(result)
        mock_get_turns.assert_not_called()

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_preserves_news_with_followup(self, mock_get_turns):
        """Gate does NOT override news queries with follow-up markers."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "Something earlier"},
        ]
        result = _memory_routing_gate("What about the latest news?", "NEWS")
        self.assertIsNone(result)
        mock_get_turns.assert_not_called()

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_preserves_time_with_followup(self, mock_get_turns):
        """Gate does NOT override time queries with follow-up markers."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "Something earlier"},
        ]
        result = _memory_routing_gate("What time is it there?", "TIME")
        self.assertIsNone(result)
        mock_get_turns.assert_not_called()

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_preserves_stocks_with_followup(self, mock_get_turns):
        """Gate does NOT override stock queries with follow-up markers."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [
            {"role": "user", "text": "Something earlier"},
        ]
        result = _memory_routing_gate("What about that stock price?", "AUGMENTED")
        self.assertIsNone(result)
        mock_get_turns.assert_not_called()

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_empty_query(self, mock_get_turns):
        """Gate returns None for empty queries."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        result = _memory_routing_gate("", "WEATHER")
        self.assertIsNone(result)
        mock_get_turns.assert_not_called()

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_short_pronoun_query(self, mock_get_turns):
        """Very short pronoun queries trigger the gate."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [{"role": "user", "text": "hi"}]
        result = _memory_routing_gate("That?", "AUGMENTED")
        self.assertEqual(result, "LOCAL")

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_tell_me_more(self, mock_get_turns):
        """'Tell me more' triggers the gate."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.return_value = [{"role": "user", "text": "hi"}]
        result = _memory_routing_gate("Tell me more", "AUGMENTED")
        self.assertEqual(result, "LOCAL")

    @patch("memory.memory_service.get_recent_turns")
    def test_gate_fallback_to_text_file(self, mock_get_turns):
        """Gate falls back to legacy text file when SQLite import fails."""
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        mock_get_turns.side_effect = ImportError("No module named memory")

        # Create a temporary memory file
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_file = Path(tmpdir) / "state" / "chat_session_memory.txt"
            mem_file.parent.mkdir(parents=True, exist_ok=True)
            mem_file.write_text("User: Hello\nAssistant: Hi there\n")
            os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = tmpdir

            result = _memory_routing_gate("What about that?", "WEATHER")
            self.assertEqual(result, "LOCAL")

            del os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"]


if __name__ == "__main__":
    unittest.main()
