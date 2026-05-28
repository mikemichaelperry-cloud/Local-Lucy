#!/usr/bin/env python3
"""
Unit tests for classification integration functions.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.classify import (
    ClassificationResult,
    RoutingDecision,
    _map_to_intent_family,
    _make_local_decision,
    _make_augmented_decision,
    select_route,
    classify_intent,
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
            evidence_reason="financial_data",  # Non-medical to test prefer_paid
        )
        
        decision = _make_augmented_decision(classification, prefer_paid=True)
        
        self.assertEqual(decision.route, "AUGMENTED")
        self.assertEqual(decision.provider, "kimi")
        self.assertEqual(decision.provider_usage_class, "paid")
    
    def test_medical_safety_overrides_prefer_paid(self):
        """Medical context routes to EVIDENCE (strict trusted sources)."""
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
        
        self.assertEqual(decision.route, "EVIDENCE")
        self.assertEqual(decision.provider, "trusted")
        self.assertEqual(decision.provider_usage_class, "local")


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
        self.assertEqual(decision.provider, "kimi")  # Paid for forced online
    
    def test_clarify_required(self):
        """Test clarify_required no longer forces CLARIFY — embedding router decides."""
        classification = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            intent_class="local_answer",
            category="procedural",
            confidence=0.3,
            needs_web=False,
            clarify_required=True,
        )
        
        # Without query, falls back to local (no embedding router input)
        decision = select_route(classification)
        self.assertEqual(decision.route, "LOCAL")
        
        # With a genuine clarify query, embedding router returns LOCAL
        decision = select_route(classification, query="What do you mean by that?")
        self.assertEqual(decision.route, "LOCAL")
    
    def test_evidence_mode_trumps_fallback_policy(self):
        """Test evidence mode routes medical queries to EVIDENCE (strict trusted sources)."""
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
        
        decision = select_route(classification, policy="fallback_only")
        
        self.assertEqual(decision.route, "EVIDENCE")
        self.assertEqual(decision.provider, "trusted")
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




class TestSocialGreetingRouting(unittest.TestCase):
    """Test that the embedding router handles greetings without guards."""

    def setUp(self):
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))
        from hybrid_router_v2 import HybridRouterV2
        self.router = HybridRouterV2()

    def test_how_are_you_today_lucy(self):
        """Greeting with temporal keyword routes LOCAL via embedding router."""
        result = self.router.predict("How are you today Lucy?")
        self.assertEqual(result["route"], "LOCAL")

    def test_whats_up(self):
        """Short greeting routes LOCAL via embedding router."""
        result = self.router.predict("What's up?")
        self.assertEqual(result["route"], "LOCAL")

    def test_good_morning_lucy(self):
        """Morning greeting routes LOCAL via embedding router."""
        result = self.router.predict("Good morning Lucy")
        self.assertEqual(result["route"], "LOCAL")

    def test_how_are_you_different_not_greeting(self):
        """Non-greeting routes according to embedding router, not forced LOCAL."""
        result = self.router.predict("How are you going to fix the economy?")
        self.assertEqual(result["route"], "AUGMENTED")


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestRouting))
    suite.addTests(loader.loadTestsFromTestCase(TestDataClasses))
    suite.addTests(loader.loadTestsFromTestCase(TestSocialGreetingRouting))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
