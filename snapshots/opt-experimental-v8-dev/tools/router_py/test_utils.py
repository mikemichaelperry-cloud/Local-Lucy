#!/usr/bin/env python3
"""
Unit tests for router utility functions.
Verifies Python implementations match shell behavior.
"""

import subprocess
import sys
import unittest
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from utils import sha256_text, guard_normalize, deterministic_pick_index, is_allowed_repeat_body


# Path to isolated shell functions for testing
SHELL_FUNCS = "/tmp/test_shell_funcs.sh"


class TestSha256Text(unittest.TestCase):
    """Test sha256_text function against shell implementation."""
    
    def run_shell_sha256(self, text: str) -> str:
        """Run shell version for comparison."""
        cmd = [SHELL_FUNCS, "sha256_text", text]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip()
    
    def test_empty_string(self):
        """SHA256 of empty string."""
        python_result = sha256_text("")
        shell_result = self.run_shell_sha256("")
        self.assertEqual(python_result, shell_result,
                        f"Empty string mismatch: {python_result} vs {shell_result}")
    
    def test_simple_string(self):
        """SHA256 of simple string."""
        test_cases = ["hello", "test", "Local Lucy v8", "What is Git?"]
        for text in test_cases:
            with self.subTest(text=text):
                python_result = sha256_text(text)
                shell_result = self.run_shell_sha256(text)
                self.assertEqual(python_result, shell_result,
                               f"Mismatch for '{text}': {python_result} vs {shell_result}")
    
    def test_unicode(self):
        """SHA256 of unicode string."""
        text = "Hello 世界 🌍"
        python_result = sha256_text(text)
        # Shell may handle unicode differently, so just check format
        self.assertEqual(len(python_result), 64)  # SHA256 hex is 64 chars
        self.assertTrue(all(c in '0123456789abcdef' for c in python_result))
    
    def test_hash_format(self):
        """Verify hash format is correct."""
        result = sha256_text("test")
        self.assertEqual(len(result), 64)  # 256 bits = 64 hex chars
        self.assertTrue(all(c in '0123456789abcdef' for c in result))


class TestGuardNormalize(unittest.TestCase):
    """Test guard_normalize function against shell implementation."""
    
    def run_shell_normalize(self, text: str) -> str:
        """Run shell version for comparison."""
        cmd = [SHELL_FUNCS, "guard_normalize", text]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip()
    
    def test_empty(self):
        """Normalize empty string."""
        self.assertEqual(guard_normalize(""), "")
    
    def test_whitespace(self):
        """Collapse multiple whitespace."""
        test_cases = [
            ("hello   world", "hello world"),
            ("  leading", "leading"),
            ("trailing  ", "trailing"),
            ("  both  ", "both"),
        ]
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = guard_normalize(input_text)
                self.assertEqual(result, expected)
    
    def test_lowercase(self):
        """Convert to lowercase."""
        self.assertEqual(guard_normalize("HELLO WORLD"), "hello world")
        self.assertEqual(guard_normalize("Mixed CASE"), "mixed case")
    
    def test_shell_matches(self):
        """Verify Python matches shell behavior."""
        test_cases = [
            "Hello World",
            "  Multiple   Spaces  ",
            "UPPER lower",
            "tabs\t\t\tto\tspaces",
        ]
        for text in test_cases:
            with self.subTest(text=text):
                python_result = guard_normalize(text)
                shell_result = self.run_shell_normalize(text)
                self.assertEqual(python_result, shell_result,
                               f"Mismatch for '{text}': {python_result} vs {shell_result}")


class TestDeterministicPickIndex(unittest.TestCase):
    """Test deterministic_pick_index function."""
    
    def run_shell_pick(self, seed: str, mod: int) -> int:
        """Run shell version for comparison."""
        cmd = [SHELL_FUNCS, "deterministic_pick_index", seed, str(mod)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return int(result.stdout.strip())
    
    def test_range(self):
        """Result is within expected range."""
        for mod in [2, 5, 10, 100]:
            for seed in ["test", "hello", "seed123"]:
                with self.subTest(seed=seed, mod=mod):
                    result = deterministic_pick_index(seed, mod)
                    self.assertGreaterEqual(result, 0)
                    self.assertLess(result, mod)
    
    def test_deterministic(self):
        """Same seed produces same result."""
        for _ in range(10):
            result1 = deterministic_pick_index("test_seed", 10)
            result2 = deterministic_pick_index("test_seed", 10)
            self.assertEqual(result1, result2)
    
    def test_different_seeds(self):
        """Different seeds produce different results (usually)."""
        results = [deterministic_pick_index(f"seed{i}", 100) for i in range(10)]
        # Most should be different (not guaranteed but highly likely)
        unique_results = len(set(results))
        self.assertGreater(unique_results, 5, "Too many collisions")
    
    def test_shell_matches(self):
        """Verify Python matches shell behavior."""
        test_cases = [
            ("test", 10),
            ("hello", 5),
            ("query", 100),
            ("seed123", 7),
        ]
        for seed, mod in test_cases:
            with self.subTest(seed=seed, mod=mod):
                python_result = deterministic_pick_index(seed, mod)
                shell_result = self.run_shell_pick(seed, mod)
                self.assertEqual(python_result, shell_result,
                               f"Mismatch for seed='{seed}', mod={mod}: {python_result} vs {shell_result}")


class TestIsAllowedRepeatBody(unittest.TestCase):
    """Test is_allowed_repeat_body function."""
    
    def test_allowed_bodies(self):
        """These bodies should be allowed as repeats."""
        allowed = [
            "I could not generate a reply locally. Please retry, or switch mode.",
            "ERROR",
            "error",
            "  error  ",
        ]
        for body in allowed:
            with self.subTest(body=body):
                self.assertTrue(is_allowed_repeat_body(body), f"'{body}' should be allowed")
    
    def test_disallowed_bodies(self):
        """These bodies should not be allowed as repeats."""
        disallowed = [
            "Hello, how can I help you?",
            "Git is a version control system",
            "Some other response",
            "",
        ]
        for body in disallowed:
            with self.subTest(body=body):
                self.assertFalse(is_allowed_repeat_body(body), f"'{body}' should not be allowed")


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""
    
    def test_sha256_long_string(self):
        """SHA256 of very long string."""
        long_text = "a" * 10000
        result = sha256_text(long_text)
        self.assertEqual(len(result), 64)
    
    def test_guard_normalize_special_chars(self):
        """Normalize strings with special characters."""
        # These should not crash
        guard_normalize("Hello\nWorld\t!")
        guard_normalize("Special @#$% chars")
    
    def test_deterministic_mod_1(self):
        """Mod 1 should always return 0."""
        self.assertEqual(deterministic_pick_index("any", 1), 0)


def run_tests():
    """Run all tests and report results."""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
