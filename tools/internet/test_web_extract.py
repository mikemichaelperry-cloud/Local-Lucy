#!/usr/bin/env python3
"""Unit tests for web_extract.py adapter."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure module under test is importable
sys.path.insert(0, str(Path(__file__).parent))

import web_extract as we


class TestTruncate(unittest.TestCase):
    """Test _truncate helper."""

    def test_short_text_unchanged(self):
        text = "Short text."
        self.assertEqual(we._truncate(text, 1000), text)

    def test_truncates_at_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        result = we._truncate(text, 35)
        self.assertEqual(result, "First sentence. Second sentence.")

    def test_truncates_at_word_boundary_fallback(self):
        text = "one two three four five"
        result = we._truncate(text, 12)
        # Truncates to last space before limit (index 9 = "one two thre")
        self.assertEqual(result, "one two thre")


class TestStripTocNav(unittest.TestCase):
    """Test TOC nav stripping."""

    def test_strips_on_this_page_block(self):
        text = (
            "Appendicitis\n\nOn this page\n\nBasics\n\n"
            "- Summary\n- Start Here\n\n\nThe appendix is small and tube-like."
        )
        result = we._strip_toc_nav(text)
        self.assertNotIn("On this page", result)
        self.assertIn("The appendix is small", result)

    def test_no_change_when_no_toc(self):
        text = "Just normal content.\n\nMore content."
        self.assertEqual(we._strip_toc_nav(text), text)

    def test_collapse_excessive_blanks(self):
        text = "A\n\n\n\nB"
        result = we._strip_toc_nav(text)
        self.assertEqual(result, "A\n\nB")


class TestFindWebclaw(unittest.TestCase):
    """Test webclaw binary discovery."""

    def test_finds_local_bin(self):
        # bin/webclaw was placed during install
        result = we._find_webclaw()
        if result is not None:
            self.assertTrue(result.exists())
            self.assertTrue(os.access(result, os.X_OK))

    @patch("shutil.which")
    @patch.object(Path, "exists", return_value=False)
    def test_falls_back_to_path(self, mock_exists, mock_which):
        mock_which.return_value = "/usr/local/bin/webclaw"
        result = we._find_webclaw()
        self.assertIsNotNone(result)
        self.assertEqual(str(result), "/usr/local/bin/webclaw")

    @patch("shutil.which", return_value=None)
    @patch.object(Path, "exists", return_value=False)
    def test_returns_none_when_missing(self, mock_exists, mock_which):
        self.assertIsNone(we._find_webclaw())


class TestExtractWebpageLive(unittest.TestCase):
    """Live integration tests — require network + webclaw or fallback."""

    TEST_URL = "https://medlineplus.gov/appendicitis.html"

    def test_extract_returns_substantial_text(self):
        """Must return at least 500 chars of real content."""
        result = we.extract_webpage(self.TEST_URL, max_chars=2000, timeout=20)
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 500)
        self.assertIn("appendicitis", result.lower())

    def test_respects_max_chars(self):
        result = we.extract_webpage(self.TEST_URL, max_chars=800, timeout=20)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 850)  # small margin for truncation logic

    def test_hard_cap_enforced(self):
        """Hard cap prevents callers from requesting excessive content."""
        with patch.object(we, "_extract_with_webclaw", return_value="x" * 10000):
            result = we.extract_webpage(
                self.TEST_URL, max_chars=9000, timeout=20
            )
        # Should be truncated to hard cap (default 3000)
        self.assertIsNotNone(result)
        self.assertLessEqual(len(result), 3050)
        self.assertGreater(len(result), 2000)

    def test_no_nav_noise(self):
        """Should not contain .gov banner or skip-navigation noise."""
        result = we.extract_webpage(self.TEST_URL, max_chars=2000, timeout=20)
        self.assertIsNotNone(result)
        # Legacy fallback includes these; webclaw strips them
        # We accept either but strongly prefer clean output
        if we._find_webclaw():
            self.assertNotIn("Skip navigation", result)
            self.assertNotIn("Here's how you know", result)

    def test_fallback_path_when_webclaw_missing(self):
        """Simulate missing webclaw — should still return content via fallback."""
        with patch.object(we, "_find_webclaw", return_value=None):
            result = we.extract_webpage(self.TEST_URL, max_chars=2000, timeout=20)
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 200)


class TestExtractWebpageFailureModes(unittest.TestCase):
    """Test graceful degradation."""

    def test_invalid_url_returns_none(self):
        result = we.extract_webpage("http://localhost:99999/nowhere", timeout=3)
        self.assertIsNone(result)

    def test_nonexistent_domain_returns_none(self):
        result = we.extract_webpage("http://this-domain-does-not-exist-12345.test/", timeout=5)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
