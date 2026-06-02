#!/usr/bin/env python3
"""Unit tests for unverified_context_trusted.py live-fetch integration.

These tests verify the internal functions without requiring a working
SearXNG backend. Live network tests are in test_trusted_evidence_live_fetch.sh.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[2]
os.environ["LUCY_ROOT"] = str(ROOT)
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "internet"))

import unverified_context_trusted as uct


class TestDedupeDomains(unittest.TestCase):
    def test_removes_www_prefix(self):
        domains = ["www.example.com", "example.com", "feeds.example.com"]
        result = uct._dedupe_domains(domains)
        self.assertEqual(result, ["example.com"])

    def test_preserves_order(self):
        domains = ["a.com", "www.b.com", "c.com", "b.com"]
        result = uct._dedupe_domains(domains)
        self.assertEqual(result, ["a.com", "b.com", "c.com"])


class TestIsCategorySupported(unittest.TestCase):
    def test_veterinary_keywords(self):
        cat, sub = uct._is_category_supported("", "my dog has parvovirus")
        self.assertEqual(cat, "vet")
        self.assertEqual(sub, "vet")

    def test_medical_keywords(self):
        cat, sub = uct._is_category_supported("", "what is metformin dosage")
        self.assertEqual(cat, "medical")
        self.assertEqual(sub, "medical")

    def test_news_keywords(self):
        cat, sub = uct._is_category_supported("", "latest world news headlines")
        self.assertEqual(cat, "news_world")
        self.assertEqual(sub, "news")

    def test_unsupported_query(self):
        cat, sub = uct._is_category_supported("", "write me a poem")
        self.assertIsNone(cat)
        self.assertIsNone(sub)


class TestFormatMedicalResponseWithMockFetch(unittest.TestCase):
    @patch.object(uct, "_search_restricted", return_value=[
        {"url": "https://medlineplus.gov/appendicitis.html", "title": "Appendicitis"}
    ])
    @patch.object(uct, "_fetch_article_content", return_value="The appendix is a small, tube-like organ attached to the first part of the large intestine. It is located in the lower right part of the abdomen. It has no known function. A blockage inside of the appendix causes appendicitis. The blockage leads to increased pressure, problems with blood flow, and inflammation.")
    def test_returns_fetched_content_when_available(self, mock_fetch, mock_search):
        domains = ["medlineplus.gov", "mayoclinic.org"]
        result = uct._format_medical_response(domains, "symptoms of appendicitis")
        self.assertIn("The appendix is a small, tube-like organ", result)
        self.assertIn("Source: Appendicitis", result)
        mock_search.assert_called_once()
        mock_fetch.assert_called_once()

    @patch.object(uct, "_try_direct_fetch", return_value=None)
    @patch.object(uct, "_search_restricted", return_value=[])
    def test_falls_back_to_generic_when_no_results(self, mock_search, mock_direct):
        domains = ["medlineplus.gov"]
        result = uct._format_medical_response(domains, "symptoms of appendicitis")
        self.assertIn("Medical information is available", result)
        self.assertIn("medlineplus.gov", result)

    @patch.object(uct, "_search_restricted", return_value=[
        {"url": "https://medlineplus.gov/appendicitis.html", "title": "Appendicitis"}
    ])
    @patch.object(uct, "_fetch_article_content", return_value=None)
    def test_falls_back_when_fetch_returns_none(self, mock_fetch, mock_search):
        domains = ["medlineplus.gov"]
        result = uct._format_medical_response(domains, "symptoms of appendicitis")
        self.assertIn("Medical information is available", result)


class TestFormatVetResponseWithMockFetch(unittest.TestCase):
    @patch.object(uct, "_search_restricted", return_value=[
        {"url": "https://vcahospitals.com/kb/parvovirus", "title": "Parvovirus"}
    ])
    @patch.object(uct, "_fetch_article_content", return_value="Parvovirus is a highly contagious viral disease that can produce a life-threatening illness. The virus attacks rapidly dividing cells in a dog's body, most severely affecting the intestinal tract. Parvovirus also attacks the white blood cells, and when young animals are infected, the virus can damage the heart muscle and cause lifelong cardiac problems.")
    def test_returns_fetched_content(self, mock_fetch, mock_search):
        domains = ["vcahospitals.com", "avma.org"]
        result = uct._format_vet_response(domains, "what is parvovirus in dogs")
        self.assertIn("Parvovirus is a highly contagious viral disease", result)
        self.assertIn("Source: Parvovirus", result)

    @patch.object(uct, "_try_direct_fetch", return_value=None)
    @patch.object(uct, "_search_restricted", return_value=[])
    def test_emergency_warning_without_fetch(self, mock_search, mock_direct):
        domains = ["avma.org"]
        result = uct._format_vet_response(domains, "my dog is vomiting")
        self.assertIn("veterinary emergency", result)
        self.assertIn("avma.org", result)

    @patch.object(uct, "_search_restricted", return_value=[
        {"url": "https://vcahospitals.com/kb/bloat", "title": "Bloat"}
    ])
    @patch.object(uct, "_fetch_article_content", return_value="Bloat, also known as gastric dilatation-volvulus (GDV), is a life-threatening condition that can affect dogs. It occurs when the stomach fills with gas, food, or fluid and then twists. This twisting traps the contents and cuts off blood supply to the stomach and sometimes the spleen. Without immediate treatment, bloat can be fatal within hours.")
    def test_emergency_prepended_to_fetched_content(self, mock_fetch, mock_search):
        domains = ["vcahospitals.com"]
        result = uct._format_vet_response(domains, "my dog has bloat")
        self.assertIn("veterinary emergency", result)
        self.assertIn("Bloat, also known as gastric dilatation-volvulus", result)


class TestFetchContextEntryPoint(unittest.TestCase):
    @patch.object(uct, "_search_restricted", return_value=[
        {"url": "https://medlineplus.gov/appendicitis.html", "title": "Appendicitis"}
    ])
    @patch.object(
        uct,
        "_fetch_article_content",
        return_value="Appendicitis is inflammation of the appendix. It can cause severe abdominal pain, fever, nausea, and vomiting. It often needs urgent evaluation and may require surgery depending on severity and complications.",
    )
    def test_medical_context_live_fetch_metadata_success(self, mock_fetch, mock_search):
        result = uct.fetch_context("what is appendicitis", evidence_reason="medical_context")
        self.assertIsNotNone(result)
        self.assertEqual(result["ANSWER_BASIS"], "live_trusted_source")
        self.assertEqual(result["LIVE_FETCH_STATUS"], "success")
        self.assertEqual(result["CONFIDENCE"], "normal")
        self.assertEqual(result["DEGRADED_REASON"], "")

    def test_medical_context_returns_bounded(self):
        with patch.object(uct, "_search_restricted", return_value=[]):
            with patch.object(uct, "_try_direct_fetch", return_value=None):
                result = uct.fetch_context("what is appendicitis", evidence_reason="medical_context")
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertTrue(result["bounded_response"])
        self.assertIn("content", result)
        self.assertIn("sources", result)
        self.assertEqual(result["ANSWER_BASIS"], "trusted_domain_fallback")
        self.assertEqual(result["LIVE_FETCH_STATUS"], "failed")
        self.assertEqual(result["CONFIDENCE"], "limited")
        self.assertEqual(result["DEGRADED_REASON"], "search_no_results")

    def test_vet_context_returns_bounded(self):
        with patch.object(uct, "_search_restricted", return_value=[]):
            result = uct.fetch_context("dog vomiting", evidence_reason="veterinary_context")
        self.assertIsNotNone(result)
        self.assertTrue(result["ok"])
        self.assertTrue(result["bounded_response"])

    def test_unsupported_query_returns_none(self):
        result = uct.fetch_context("write me a poem", evidence_reason="")
        self.assertIsNone(result)


class TestVetTopicMapping(unittest.TestCase):
    """Verify vet direct-fetch URL generation maps conditions to correct sections."""

    def test_condition_animal_mapping_generates_urls(self):
        # _try_direct_fetch should produce condition-specific Merck URLs
        # when both an animal and a known condition are present.
        candidates = []
        with patch.object(uct, "extract_webpage", side_effect=lambda url, **kw: None) as mock_fetch:
            uct._try_direct_fetch("my dog is vomiting", "vet")
            calls = [c[0][0] for c in mock_fetch.call_args_list]
            # Should include the condition-specific Merck URL
            self.assertTrue(
                any("merckvetmanual.com/dog-owners/digestive-disorders-of-dogs/vomiting-in-dogs" in c for c in calls),
                f"Expected Merck vomiting URL in candidates, got: {calls}"
            )

    def test_two_word_condition_phrase_mapped(self):
        with patch.object(uct, "extract_webpage", side_effect=lambda url, **kw: None) as mock_fetch:
            uct._try_direct_fetch("dog ear infection", "vet")
            calls = [c[0][0] for c in mock_fetch.call_args_list]
            self.assertTrue(
                any("merckvetmanual.com/dog-owners/ear-disorders-of-dogs/ear-infections-in-dogs" in c for c in calls),
                f"Expected Merck ear-infection URL in candidates, got: {calls}"
            )

    def test_unknown_condition_falls_back_to_search(self):
        with patch.object(uct, "extract_webpage", side_effect=lambda url, **kw: None) as mock_fetch:
            uct._try_direct_fetch("dog xyzabc123 condition", "vet")
            calls = [c[0][0] for c in mock_fetch.call_args_list]
            self.assertTrue(
                any("merckvetmanual.com/?q=" in c for c in calls),
                f"Expected Merck search fallback, got: {calls}"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
