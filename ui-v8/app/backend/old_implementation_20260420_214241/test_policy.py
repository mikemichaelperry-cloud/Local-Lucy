#!/usr/bin/env python3
"""
Unit tests for policy functions.
Tests verify Python output matches shell behavior.
"""

import subprocess
import sys
import unittest
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from policy import (
    normalize_augmentation_policy,
    requires_evidence_mode,
    provider_usage_class_for,
    manifest_evidence_selection_label,
)


# Path to shell implementations for comparison
ROUTER_DIR = Path(__file__).parent.parent / "router"
EXECUTE_PLAN = ROUTER_DIR / "execute_plan.sh"


def call_shell_normalize(policy: str) -> str:
    """Call the shell version of normalize_augmentation_policy."""
    # Inline the shell function to avoid sourcing entire execute_plan.sh
    cmd = f'''
normalize_augmentation_policy() {{
  local raw
  raw="$(printf "%s" "${{1:-disabled}}" | tr "[:upper:]" "[:lower:]")"
  case "${{raw}}" in
    disabled|off|none|0|false|no) printf "%s" "disabled" ;;
    fallback_only|fallback|1|true|yes|on) printf "%s" "fallback_only" ;;
    direct_allowed|direct|2) printf "%s" "direct_allowed" ;;
    *) printf "%s" "disabled" ;;
  esac
}}
normalize_augmentation_policy '{policy}'
'''
    result = subprocess.run(
        ["bash", "-c", cmd],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


class TestNormalizeAugmentationPolicy(unittest.TestCase):
    """Test normalize_augmentation_policy function."""
    
    def test_disabled_variants(self):
        """Test all variants that should normalize to 'disabled'."""
        disabled_variants = [
            "disabled", "DISABLED", "Disabled",
            "off", "OFF", "Off",
            "none", "NONE", "None",
            "0", "false", "FALSE", "False",
            "no", "NO", "No",
            "", "  disabled  "
        ]
        for variant in disabled_variants:
            with self.subTest(variant=variant):
                result = normalize_augmentation_policy(variant)
                self.assertEqual(result, "disabled")
    
    def test_fallback_variants(self):
        """Test all variants that should normalize to 'fallback_only'."""
        fallback_variants = [
            "fallback_only", "FALLBACK_ONLY",
            "fallback", "FALLBACK", "Fallback",
            "1", "true", "TRUE", "True",
            "yes", "YES", "Yes",
            "on", "ON", "On"
        ]
        for variant in fallback_variants:
            with self.subTest(variant=variant):
                result = normalize_augmentation_policy(variant)
                self.assertEqual(result, "fallback_only")
    
    def test_direct_allowed_variants(self):
        """Test all variants that should normalize to 'direct_allowed'."""
        direct_variants = [
            "direct_allowed", "DIRECT_ALLOWED",
            "direct", "DIRECT", "Direct",
            "2"
        ]
        for variant in direct_variants:
            with self.subTest(variant=variant):
                result = normalize_augmentation_policy(variant)
                self.assertEqual(result, "direct_allowed")
    
    def test_unknown_defaults_to_disabled(self):
        """Test that unknown values default to 'disabled'."""
        unknown_variants = [
            "invalid", "unknown", "random_string",
            "enabled", "auto", "maybe"
        ]
        for variant in unknown_variants:
            with self.subTest(variant=variant):
                result = normalize_augmentation_policy(variant)
                self.assertEqual(result, "disabled")


class TestRequiresEvidenceMode(unittest.TestCase):
    """Test requires_evidence_mode function."""
    
    def test_medical_keywords_trigger_evidence(self):
        """Test that medical keywords trigger evidence mode."""
        medical_queries = [
            ("What are the symptoms of flu?", "medical_context"),
            ("How to treat a headache?", "medical_context"),
            ("Diabetes medication", "medical_context"),
            ("Heart attack symptoms", "medical_context"),
            ("Is this infection serious?", "medical_context"),
            ("Vaccination schedule", "medical_context"),
            ("Pregnancy test results", "medical_context"),
            ("Cancer treatment options", "medical_context"),
            ("Prescription drug interactions", "medical_context"),
            ("Emergency room or urgent care?", "medical_context"),
        ]
        for query, expected_reason in medical_queries:
            with self.subTest(query=query):
                requires, reason = requires_evidence_mode(query)
                self.assertTrue(requires)
                self.assertEqual(reason, expected_reason)
    
    def test_conflict_keywords_trigger_evidence(self):
        """Test that live conflict keywords trigger evidence mode."""
        conflict_queries = [
            ("Breaking news about the war", "conflict_live"),
            ("Latest updates on the conflict", "conflict_live"),
            ("What happened today in Ukraine?", "conflict_live"),
            ("Current situation in Gaza", "conflict_live"),
        ]
        for query, expected_reason in conflict_queries:
            with self.subTest(query=query):
                requires, reason = requires_evidence_mode(query)
                self.assertTrue(requires)
                self.assertEqual(reason, expected_reason)
    
    def test_source_verification_triggers_evidence(self):
        """Test that source verification requests trigger evidence mode."""
        source_queries = [
            ("What's your source for that?", "source_request"),
            ("Cite your references", "source_request"),
            ("Where did you get this information?", "source_request"),
            ("Evidence please", "source_request"),
            ("Verify this claim", "source_request"),
        ]
        for query, expected_reason in source_queries:
            with self.subTest(query=query):
                requires, reason = requires_evidence_mode(query)
                self.assertTrue(requires)
                self.assertEqual(reason, expected_reason)
    
    def test_normal_queries_no_evidence(self):
        """Test that normal queries don't require evidence mode."""
        normal_queries = [
            "Hello",
            "What is the weather today?",
            "Tell me about dinosaurs",
            "How does photosynthesis work?",
            "Who was Ada Lovelace?",
            "What is 2+2?",
            "Explain quantum mechanics",
            "Recipe for chocolate cake",
        ]
        for query in normal_queries:
            with self.subTest(query=query):
                requires, reason = requires_evidence_mode(query)
                self.assertFalse(requires)
                self.assertEqual(reason, "default_light")
    
    def test_empty_query(self):
        """Test empty query handling."""
        requires, reason = requires_evidence_mode("")
        self.assertFalse(requires)
        self.assertEqual(reason, "default_light")


class TestProviderUsageClass(unittest.TestCase):
    """Test provider_usage_class_for function."""
    
    def test_paid_providers(self):
        """Test classification of paid providers."""
        self.assertEqual(provider_usage_class_for("openai"), "paid")
        self.assertEqual(provider_usage_class_for("OPENAI"), "paid")
        self.assertEqual(provider_usage_class_for("OpenAI"), "paid")
        self.assertEqual(provider_usage_class_for("kimi"), "paid")
        self.assertEqual(provider_usage_class_for("GROK"), "paid")
    
    def test_free_providers(self):
        """Test classification of free providers."""
        self.assertEqual(provider_usage_class_for("wikipedia"), "free")
        self.assertEqual(provider_usage_class_for("WIKIPEDIA"), "free")
    
    def test_local_provider(self):
        """Test classification of local provider."""
        self.assertEqual(provider_usage_class_for("local"), "local")
        self.assertEqual(provider_usage_class_for("LOCAL"), "local")
    
    def test_unknown_providers(self):
        """Test classification of unknown providers."""
        self.assertEqual(provider_usage_class_for("unknown"), "none")
        self.assertEqual(provider_usage_class_for(""), "none")
        self.assertEqual(provider_usage_class_for("random"), "none")


class TestManifestEvidenceSelectionLabel(unittest.TestCase):
    """Test manifest_evidence_selection_label function."""
    
    def test_no_evidence_mode(self):
        """Test when no evidence mode is selected."""
        self.assertEqual(
            manifest_evidence_selection_label(None, None),
            "not_applicable"
        )
        self.assertEqual(
            manifest_evidence_selection_label("", "reason"),
            "not_applicable"
        )
    
    def test_default_light(self):
        """Test default light reason."""
        self.assertEqual(
            manifest_evidence_selection_label("light", "default_light"),
            "default-light"
        )
        self.assertEqual(
            manifest_evidence_selection_label("light", ""),
            "default-light"
        )
    
    def test_explicit_user_triggered(self):
        """Test explicit user triggered reasons."""
        self.assertEqual(
            manifest_evidence_selection_label("required", "explicit_user"),
            "explicit-user-triggered"
        )
        self.assertEqual(
            manifest_evidence_selection_label("required", "source_request"),
            "explicit-user-triggered"
        )
    
    def test_policy_triggered(self):
        """Test policy triggered reasons."""
        self.assertEqual(
            manifest_evidence_selection_label("required", "policy_medical"),
            "policy-triggered"
        )
        self.assertEqual(
            manifest_evidence_selection_label("required", "medical_context"),
            "policy-triggered"
        )
        self.assertEqual(
            manifest_evidence_selection_label("required", "conflict_live"),
            "policy-triggered"
        )
    
    def test_manifest_selected(self):
        """Test manifest selected fallback."""
        self.assertEqual(
            manifest_evidence_selection_label("required", "unknown_reason"),
            "manifest-selected"
        )
        self.assertEqual(
            manifest_evidence_selection_label("required", "calculated"),
            "manifest-selected"
        )


class TestShellCompatibility(unittest.TestCase):
    """Verify Python output matches shell output where applicable."""
    
    def test_normalize_matches_shell(self):
        """Test that Python normalize matches shell implementation."""
        if not EXECUTE_PLAN.exists():
            self.skipTest("Shell implementation not found")
        
        test_cases = [
            "disabled", "fallback_only", "direct_allowed",
            "off", "fallback", "direct",
            "0", "1", "2",
            "unknown", "invalid"
        ]
        
        for policy in test_cases:
            with self.subTest(policy=policy):
                py_result = normalize_augmentation_policy(policy)
                try:
                    sh_result = call_shell_normalize(policy)
                except subprocess.CalledProcessError:
                    # Shell returns empty for unknown, Python returns "disabled"
                    sh_result = "disabled"
                
                self.assertEqual(
                    py_result, sh_result,
                    f"Mismatch for '{policy}': Python={py_result}, Shell={sh_result}"
                )


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestNormalizeAugmentationPolicy))
    suite.addTests(loader.loadTestsFromTestCase(TestRequiresEvidenceMode))
    suite.addTests(loader.loadTestsFromTestCase(TestProviderUsageClass))
    suite.addTests(loader.loadTestsFromTestCase(TestManifestEvidenceSelectionLabel))
    suite.addTests(loader.loadTestsFromTestCase(TestShellCompatibility))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
