#!/usr/bin/env python3
"""
Unit tests for main router orchestrator (Phase 4 Strangler Fig).
"""

import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

from main import RouterOutcome, _persist_memory_turn


class TestRouterOutcome(unittest.TestCase):
    """Test RouterOutcome dataclass."""
    
    def test_basic_creation(self):
        """Test creating a RouterOutcome."""
        outcome = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
            response_text="Hello!",
        )
        
        self.assertEqual(outcome.status, "completed")
        self.assertEqual(outcome.outcome_code, "local_answer")
        self.assertEqual(outcome.route, "LOCAL")
        self.assertEqual(outcome.response_text, "Hello!")
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        outcome = RouterOutcome(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            intent_family="background_overview",
            confidence=0.85,
            response_text="Answer here",
            execution_time_ms=1234,
            request_id="abc123",
        )
        
        d = outcome.to_dict()
        
        self.assertEqual(d["status"], "completed")
        self.assertEqual(d["provider"], "wikipedia")
        self.assertEqual(d["provider_usage_class"], "free")
        self.assertEqual(d["execution_time_ms"], 1234)
    
    def test_with_execution_time(self):
        """Test with_execution_time helper."""
        outcome = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        new_outcome = outcome.with_execution_time(500)
        
        self.assertEqual(new_outcome.execution_time_ms, 500)
        self.assertEqual(new_outcome.status, outcome.status)  # Other fields unchanged
    
    def test_with_request_id(self):
        """Test with_request_id helper."""
        outcome = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        new_outcome = outcome.with_request_id("req123")
        
        self.assertEqual(new_outcome.request_id, "req123")


class TestErrorHandling(unittest.TestCase):
    """Test error handling."""
    
    def test_empty_query(self):
        """Test handling of empty query."""
        from main import execute_plan_python
        
        result = execute_plan_python("")
        
        # Should handle gracefully
        self.assertIn(result.status, ["completed", "failed"])
    
    def test_very_long_query(self):
        """Test handling of very long query."""
        from main import execute_plan_python
        
        long_query = "word " * 1000
        result = execute_plan_python(long_query)
        
        # Should handle gracefully
        self.assertIn(result.status, ["completed", "failed"])
    
    def test_special_characters(self):
        """Test handling of special characters."""
        from main import execute_plan_python
        
        special_query = "What is 2+2? <script>alert('xss')</script> 'quotes' \"double\""
        result = execute_plan_python(special_query)
        
        # Should handle gracefully
        self.assertIn(result.status, ["completed", "failed"])


class TestPersistMemoryTurn(unittest.TestCase):
    """Test _persist_memory_turn session_id threading."""

    @patch("memory.memory_service.maybe_summarize_session")
    @patch("memory.memory_service.store_turn")
    def test_persist_turn_passes_session_id(self, mock_store_turn, mock_summarize):
        """store_turn receives the custom session_id."""
        _persist_memory_turn("Hello", "Hi there", session_id="session-42")
        calls = mock_store_turn.call_args_list
        self.assertEqual(calls[0], (("user", "Hello"), {"session_id": "session-42"}))
        self.assertEqual(calls[1], (("assistant", "Hi there"), {"session_id": "session-42"}))

    @patch("memory.memory_service.maybe_summarize_session")
    @patch("memory.memory_service.store_turn")
    def test_persist_turn_defaults_to_default_session(self, mock_store_turn, mock_summarize):
        """store_turn defaults to 'default' when no session_id provided."""
        _persist_memory_turn("Hello", "Hi there")
        calls = mock_store_turn.call_args_list
        self.assertEqual(calls[0], (("user", "Hello"), {"session_id": "default"}))
        self.assertEqual(calls[1], (("assistant", "Hi there"), {"session_id": "default"}))


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestRouterOutcome))
    suite.addTests(loader.loadTestsFromTestCase(TestPersistMemoryTurn))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
