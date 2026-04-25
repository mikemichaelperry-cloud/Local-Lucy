#!/usr/bin/env python3
"""
Unit tests for classification integration functions.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from backend.classify import (
    ClassificationResult,
    RoutingDecision,
    _map_to_intent_family,
    _make_local_decision,
    _make_augmented_decision,
    select_route,
)


class TestIntentFamilyMapping(unittest.TestCase):
    """Test intent family mapping logic."""
    
    def test_direct_mappings(self):
        """Test explicit family mappings."""
        self.assertEqual(
            _map_to_intent_family("background_overview", "", ""),
            "background_overview"
        )
        self.assertEqual(
            _map_to_intent_family("synthesis_explanation", "", ""),
            "synthesis_explanation"
        )
        self.assertEqual(
            _map_to_intent_family("current_evidence", "", ""),
            "current_evidence"
        )
        self.assertEqual(
            _map_to_intent_family("local_answer", "", ""),
            "local_answer"
        )
    
    def test_category_inference(self):
        """Test intent family inference from category."""
        self.assertEqual(
            _map_to_intent_family("", "", "informational"),
            "background_overview"
        )
        self.assertEqual(
            _map_to_intent_family("", "", "factual"),
            "background_overview"
        )
        self.assertEqual(
            _map_to_intent_family("", "", "procedural"),
            "local_answer"
        )
        self.assertEqual(
            _map_to_intent_family("", "", "analytical"),
            "synthesis_explanation"
        )
    
    def test_default_fallback(self):
        """Test default fallback to local_answer."""
        self.assertEqual(
            _map_to_intent_family("unknown", "unknown", "unknown"),
            "local_answer"
        )


class TestLocalDecision(unittest.TestCase):
    """Test local decision creation."""
    
    def test_basic_local(self):
        """Test basic local decision."""
        classification = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            intent_class="local_answer",
            category="procedural",
            confidence=0.9,
            needs_web=False,
        )
        
        decision = _make_local_decision(classification)
        
        self.assertEqual(decision.route, "LOCAL")
        self.assertEqual(decision.provider, "local")
        self.assertEqual(decision.provider_usage_class, "local")
        self.assertEqual(decision.policy_reason, "local_sufficient")
    
    def test_local_preserves_evidence(self):
        """Test that evidence mode is preserved in local decision."""
        classification = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            intent_class="local_answer",
            category="procedural",
            confidence=0.9,
            needs_web=False,
            evidence_mode="required",
            evidence_reason="medical_context",
        )
        
        decision = _make_local_decision(classification)
        
        self.assertTrue(decision.requires_evidence)
        self.assertEqual(decision.evidence_mode, "required")
        self.assertEqual(decision.evidence_reason, "medical_context")


class TestAugmentedDecision(unittest.TestCase):
    """Test augmented decision creation."""
    
    def test_background_prefers_wikipedia(self):
        """Test background queries prefer wikipedia."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
        )
        
        decision = _make_augmented_decision(classification, prefer_paid=False)
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertEqual(decision.provider, "wikipedia")
        self.assertEqual(decision.provider_usage_class, "free")
    
    def test_evidence_prefers_paid(self):
        """Test evidence mode prefers paid provider."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="medical_context",
        )
        
        decision = _make_augmented_decision(classification, prefer_paid=True)
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertEqual(decision.provider, "openai")
        self.assertEqual(decision.provider_usage_class, "paid")


class TestRouteSelection(unittest.TestCase):
    """Test full route selection logic."""
    
    def test_forced_offline(self):
        """Test FORCED_OFFLINE mode."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
        )
        
        decision = select_route(classification, forced_mode="FORCED_OFFLINE")
        
        self.assertEqual(decision.route, "LOCAL")
        self.assertEqual(decision.provider, "local")
    
    def test_forced_online(self):
        """Test FORCED_ONLINE mode."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
        )
        
        decision = select_route(classification, forced_mode="FORCED_ONLINE")
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertEqual(decision.provider, "openai")  # Paid for forced online
    
    def test_clarify_required(self):
        """Test clarify required routes to CLARIFY."""
        classification = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            intent_class="local_answer",
            category="procedural",
            confidence=0.3,
            needs_web=False,
            clarify_required=True,
        )
        
        decision = select_route(classification)
        
        self.assertEqual(decision.route, "CLARIFY")
        self.assertEqual(decision.policy_reason, "clarification_required")
    
    def test_evidence_mode_trumps_policy(self):
        """Test evidence mode overrides policy."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="medical_context",
        )
        
        decision = select_route(classification, policy="disabled")
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertTrue(decision.requires_evidence)
    
    def test_policy_disabled(self):
        """Test disabled policy forces local."""
        classification = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.9,
            needs_web=True,
        )
        
        decision = select_route(classification, policy="disabled")
        
        self.assertEqual(decision.route, "LOCAL")
    
    def test_local_answer_stays_local(self):
        """Test local_answer intent family stays local."""
        classification = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            intent_class="local_answer",
            category="procedural",
            confidence=0.9,
            needs_web=False,
        )
        
        decision = select_route(classification)
        
        self.assertEqual(decision.route, "LOCAL")
        self.assertEqual(decision.intent_family, "local_answer")


class TestDataClasses(unittest.TestCase):
    """Test dataclass creation and immutability."""
    
    def test_classification_result_creation(self):
        """Test ClassificationResult can be created."""
        result = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            intent_class="background_overview",
            category="informational",
            confidence=0.85,
            needs_web=True,
        )
        
        self.assertEqual(result.intent, "background_overview")
        self.assertEqual(result.confidence, 0.85)
        self.assertTrue(result.needs_web)
    
    def test_routing_decision_creation(self):
        """Test RoutingDecision can be created."""
        decision = RoutingDecision(
            route="AUGMENTED",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.9,
            provider="wikipedia",
            provider_usage_class="free",
            evidence_mode="",
            evidence_reason="",
            requires_evidence=False,
            policy_reason="background_query",
        )
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertEqual(decision.provider, "wikipedia")


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    suite.addTests(loader.loadTestsFromTestCase(TestIntentFamilyMapping))
    suite.addTests(loader.loadTestsFromTestCase(TestLocalDecision))
    suite.addTests(loader.loadTestsFromTestCase(TestAugmentedDecision))
    suite.addTests(loader.loadTestsFromTestCase(TestRouteSelection))
    suite.addTests(loader.loadTestsFromTestCase(TestDataClasses))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
