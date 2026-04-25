#!/usr/bin/env python3
"""
Unit tests for main router orchestrator (Phase 4 Strangler Fig).
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from main import (
    RouterOutcome,
    ShadowComparison,
    _compare_outcomes,
    _classify_difference,
)


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


class TestClassifyDifference(unittest.TestCase):
    """Test difference classification."""
    
    def test_true_parity_match(self):
        """Test identical outcomes classify as true_parity."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        comparison = ShadowComparison(
            query="test",
            shell_result=shell,
            python_result=python,
            match=True,
            differences=[],
        )
        
        classification = _classify_difference(comparison, shell, python)
        self.assertEqual(classification, "true_parity")
    
    def test_intended_improvement(self):
        """Test intent_family fix classifies as intended_improvement."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",  # Shell bug
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",  # Python corrects
            confidence=0.9,
        )
        
        comparison = ShadowComparison(
            query="test",
            shell_result=shell,
            python_result=python,
            match=False,
            differences=["intent_family: shell=unknown, python=local_answer"],
        )
        
        classification = _classify_difference(comparison, shell, python)
        self.assertEqual(classification, "intended_improvement")
    
    def test_hard_regression_python_fails(self):
        """Test Python failure with shell success is hard_regression."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message="Something broke",
        )
        
        comparison = ShadowComparison(
            query="test",
            shell_result=shell,
            python_result=python,
            match=False,
            differences=["status: shell=completed, python=failed"],
        )
        
        classification = _classify_difference(comparison, shell, python)
        self.assertEqual(classification, "hard_regression")
    
    def test_suspicious_drift_route_change(self):
        """Test route change is suspicious_drift."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",  # Shell went local
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",  # Python went augmented
            provider="wikipedia",
            provider_usage_class="free",
            intent_family="background_overview",
            confidence=0.9,
        )
        
        comparison = ShadowComparison(
            query="test",
            shell_result=shell,
            python_result=python,
            match=False,
            differences=["route: shell=LOCAL, python=AUGMENTED"],
        )
        
        classification = _classify_difference(comparison, shell, python)
        self.assertEqual(classification, "suspicious_drift")


class TestShadowComparison(unittest.TestCase):
    """Test shadow mode comparison."""
    
    def test_identical_outcomes(self):
        """Test comparison of identical outcomes."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
            response_text="Answer",
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
            response_text="Answer",
        )
        
        comparison = _compare_outcomes("test query", shell, python)
        
        self.assertTrue(comparison.match)
        self.assertEqual(len(comparison.differences), 0)
    
    def test_different_routes(self):
        """Test comparison with different routes."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            intent_family="background_overview",
            confidence=0.9,
        )
        
        comparison = _compare_outcomes("test query", shell, python)
        
        self.assertFalse(comparison.match)
        self.assertIn("route: shell=LOCAL, python=AUGMENTED", comparison.differences)
        self.assertIn("provider: shell=local, python=wikipedia", comparison.differences)
    
    def test_different_status(self):
        """Test comparison with different status."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.0,
            error_message="Something failed",
        )
        
        comparison = _compare_outcomes("test query", shell, python)
        
        self.assertFalse(comparison.match)
        self.assertIn("status: shell=completed, python=failed", comparison.differences)
    
    def test_shadow_comparison_to_dict(self):
        """Test ShadowComparison to_dict."""
        shell = RouterOutcome(
            status="completed",
            outcome_code="local_answer",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.9,
        )
        
        python = RouterOutcome(
            status="completed",
            outcome_code="augmented_answer",
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            intent_family="background_overview",
            confidence=0.85,
        )
        
        comparison = ShadowComparison(
            query="test query",
            shell_result=shell,
            python_result=python,
            match=False,
            differences=["route differs"],
        )
        
        d = comparison.to_dict()
        
        self.assertEqual(d["query"], "test query")
        self.assertEqual(d["match"], False)
        self.assertEqual(d["differences"], ["route differs"])
        self.assertIsNotNone(d["shell"])
        self.assertIsNotNone(d["python"])


class TestExecutionModes(unittest.TestCase):
    """Test different execution modes."""
    
    def test_python_mode_structured_result(self):
        """Test that Python mode returns structured result."""
        from main import execute_plan_python
        
        # Simple query that should route local
        result = execute_plan_python("What is 2+2?", policy="fallback_only")
        
        # Should have all required fields
        self.assertIn(result.status, ["completed", "failed"])
        self.assertIn(result.route, ["LOCAL", "AUGMENTED", "CLARIFY"])
        self.assertIsNotNone(result.request_id)
        self.assertGreaterEqual(result.execution_time_ms, 0)
    
    def test_shell_mode_fallback(self):
        """Test that shell mode falls back gracefully."""
        from main import execute_plan_shell
        
        # This should work even if router is not fully functional
        result = execute_plan_shell("test", policy="fallback_only", timeout=5)
        
        # Should return some outcome
        self.assertIsNotNone(result)
        self.assertIn(result.status, ["completed", "failed", "timeout"])


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


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestRouterOutcome))
    suite.addTests(loader.loadTestsFromTestCase(TestClassifyDifference))
    suite.addTests(loader.loadTestsFromTestCase(TestShadowComparison))
    suite.addTests(loader.loadTestsFromTestCase(TestExecutionModes))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
