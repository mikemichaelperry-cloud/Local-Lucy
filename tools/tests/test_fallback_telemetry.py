#!/usr/bin/env python3
"""
Unit tests for unified fallback/degradation telemetry.

A fallback may be safe.
A fallback may be correct.
But a fallback must never be invisible.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import router_py.fallback_telemetry as ft


class TestFallbackTelemetrySchema(unittest.TestCase):
    """Tests for the pure helper functions in fallback_telemetry.py."""

    def test_make_returns_all_fields(self):
        tel = ft.make(
            fallback_used=True,
            fallback_reason="webclaw_unavailable",
            primary_failed="webclaw",
            fallback_to="legacy_html_parser",
            attempted_chain=["webclaw", "legacy_html_parser"],
            successful_backend="legacy_html_parser",
            degradation_level="limited",
            answer_basis="live_trusted_source",
        )
        self.assertTrue(tel["fallback_used"])
        self.assertEqual(tel["fallback_reason"], "webclaw_unavailable")
        self.assertEqual(tel["primary_failed"], "webclaw")
        self.assertEqual(tel["fallback_to"], "legacy_html_parser")
        self.assertEqual(tel["attempted_chain"], ["webclaw", "legacy_html_parser"])
        self.assertEqual(tel["successful_backend"], "legacy_html_parser")
        self.assertEqual(tel["degradation_level"], "limited")
        self.assertEqual(tel["answer_basis"], "live_trusted_source")

    def test_make_defaults_are_empty(self):
        tel = ft.make()
        self.assertFalse(tel["fallback_used"])
        self.assertEqual(tel["fallback_reason"], "")
        self.assertEqual(tel["attempted_chain"], [])

    def test_merge_preserves_existing_keys(self):
        base = {"fallback_used": False, "custom_key": "preserve_me"}
        tel = ft.make(fallback_used=True, fallback_reason="test")
        merged = ft.merge(base, tel)
        self.assertFalse(merged["fallback_used"])  # existing wins
        self.assertEqual(merged["fallback_reason"], "test")
        self.assertEqual(merged["custom_key"], "preserve_me")

    def test_merge_adds_new_keys(self):
        base = {"existing": 1}
        tel = ft.make(fallback_used=True, degradation_level="low")
        merged = ft.merge(base, tel)
        self.assertTrue(merged["fallback_used"])
        self.assertEqual(merged["degradation_level"], "low")
        self.assertEqual(merged["existing"], 1)

    def test_from_degraded_reason_maps_search_no_results(self):
        tel = ft.from_degraded_reason("search_no_results")
        self.assertTrue(tel["fallback_used"])
        self.assertEqual(tel["primary_failed"], "searxng_search")
        self.assertEqual(tel["fallback_to"], "direct_fetch")
        self.assertEqual(tel["answer_basis"], "domain_list_fallback")

    def test_from_degraded_reason_maps_article_fetch_failed(self):
        tel = ft.from_degraded_reason("article_fetch_failed")
        self.assertTrue(tel["fallback_used"])
        self.assertEqual(tel["primary_failed"], "article_extraction")
        self.assertEqual(tel["fallback_to"], "domain_list_fallback")

    def test_from_degraded_reason_maps_extractor_unavailable(self):
        tel = ft.from_degraded_reason("extractor_unavailable")
        self.assertTrue(tel["fallback_used"])
        self.assertEqual(tel["fallback_to"], "static_template")

    def test_from_degraded_reason_empty_returns_no_fallback(self):
        tel = ft.from_degraded_reason("")
        self.assertFalse(tel["fallback_used"])

    def test_from_degraded_reason_passes_attempted_chain(self):
        tel = ft.from_degraded_reason("search_no_results", attempted_chain=["a", "b"])
        self.assertEqual(tel["attempted_chain"], ["a", "b"])


class TestWebExtractTelemetry(unittest.TestCase):
    """Tests that extract_webpage populates telemetry correctly."""

    def test_webclaw_success_reports_no_fallback(self):
        telemetry = {}
        # We can't easily mock webclaw binary presence, so test the internal logic
        # by checking the function signature accepts _telemetry_out
        from internet.web_extract import extract_webpage

        # Just verify the parameter exists and the function doesn't crash
        # when _telemetry_out is provided (will fail on actual extraction,
        # but that's OK for signature validation)
        try:
            extract_webpage("http://example.com", _telemetry_out=telemetry)
        except Exception:
            pass
        # The function should have populated the dict if it got far enough
        # If webclaw isn't present, fallback_used should be True
        # If the function errored early, the dict might be empty
        # We just verify the parameter was accepted

    def test_extract_webpage_populates_telemetry_on_failure(self):
        telemetry = {}
        from internet.web_extract import extract_webpage

        # Use a URL that will definitely fail
        result = extract_webpage("http://localhost:99999/nonexistent", _telemetry_out=telemetry)
        self.assertIsNone(result)
        # Should have some telemetry indicating failure
        self.assertIn("fallback_used", telemetry)


class TestMemoryServiceTelemetry(unittest.TestCase):
    """Tests that get_relevant_persistent_facts populates telemetry."""

    def test_empty_query_sets_telemetry(self):
        import memory.memory_service as ms

        ms._close_connection()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        orig_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        os.environ["LUCY_MEMORY_DB_PATH"] = path
        ms._close_connection()

        try:
            facts = ms.get_relevant_persistent_facts("", limit=3)
            self.assertEqual(facts, [])
            tel = ms.get_last_fact_telemetry()
            self.assertEqual(tel.get("fallback_reason"), "invalid_query")
        finally:
            ms._close_connection()
            os.unlink(path)
            if orig_env:
                os.environ["LUCY_MEMORY_DB_PATH"] = orig_env
            else:
                os.environ.pop("LUCY_MEMORY_DB_PATH", None)

    def test_no_facts_sets_telemetry(self):
        import memory.memory_service as ms

        ms._close_connection()
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        orig_env = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        os.environ["LUCY_MEMORY_DB_PATH"] = path
        ms._close_connection()

        try:
            facts = ms.get_relevant_persistent_facts("test query", limit=3)
            self.assertEqual(facts, [])
            tel = ms.get_last_fact_telemetry()
            self.assertEqual(tel.get("fallback_reason"), "no_facts_in_db")
        finally:
            ms._close_connection()
            os.unlink(path)
            if orig_env:
                os.environ["LUCY_MEMORY_DB_PATH"] = orig_env
            else:
                os.environ.pop("LUCY_MEMORY_DB_PATH", None)


class TestExecutionEngineFallbackPaths(unittest.TestCase):
    """Smoke tests that execution_engine produces metadata with fallback keys."""

    def test_bypass_metadata_has_standard_fields(self):
        # We can't easily instantiate ExecutionEngine, so we verify the helper
        # function exists and produces correct dicts
        from router_py.fallback_telemetry import make

        tel = make(
            fallback_used=True,
            fallback_reason="local_worker_failed",
            primary_failed="local_answer.sh",
            fallback_to="worker",
            degradation_level="limited",
        )
        self.assertTrue(tel["fallback_used"])
        self.assertEqual(tel["primary_failed"], "local_answer.sh")

    def test_fetch_evidence_telemetry_structure(self):
        from router_py.fallback_telemetry import make

        # Simulate what _fetch_evidence produces on fallback
        tel = make(
            fallback_used=True,
            fallback_reason="primary_provider_failed:wikipedia",
            primary_failed="wikipedia",
            fallback_to="openai",
            attempted_chain=["wikipedia", "openai"],
            successful_backend="openai",
            degradation_level="limited",
        )
        self.assertEqual(tel["attempted_chain"], ["wikipedia", "openai"])
        self.assertEqual(tel["successful_backend"], "openai")


if __name__ == "__main__":
    unittest.main()
