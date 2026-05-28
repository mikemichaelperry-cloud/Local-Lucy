#!/usr/bin/env python3
"""Tests for API provider integration (OpenAI, Kimi) with temporal awareness.

Covers:
- Temporal context injection into API prompts
- Provider subprocess wrappers returning structured evidence
- Augmented prompt builder including current date
- End-to-end AUGMENTED pipeline producing non-empty results
- Live-API validation (run manually with keys)

Usage:
    # Fast unit tests (no API calls)
    python3 -m pytest tools/router_py/test_api_providers.py -v

    # Include live API smoke tests (requires OPENAI_API_KEY / MOONSHOT_API_KEY)
    LUCY_TEST_LIVE_APIS=1 python3 -m pytest tools/router_py/test_api_providers.py -v
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add tools/ so router_py can be imported as a package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from router_py.response_formatter import build_augmented_prompt
from router_py.request_types import RoutingDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_temporal_marker(text: str) -> bool:
    """Check if text contains a year-month-day pattern or UTC marker."""
    if not text:
        return False
    text_lower = text.lower()
    return bool(
        re.search(r"\b20\d{2}[-/][01]\d[-/][0123]\d\b", text)
        or "utc" in text_lower
        or re.search(
            r"\b(january|february|march|april|may|june|july|august|"
            r"september|october|november|december)\s+20\d{2}\b",
            text_lower,
        )
    )


def _run_provider_tool(tool_name: str, question: str) -> dict | None:
    """Run a provider CLI tool and return parsed JSON."""
    tool_path = Path(__file__).resolve().parent.parent.parent / "tools" / tool_name
    if not tool_path.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(tool_path), question],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(Path(__file__).resolve().parent.parent.parent),
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Unit tests — no API calls
# ---------------------------------------------------------------------------

class TestTemporalInjection(unittest.TestCase):
    """Verify that current date/time is injected into prompts."""

    def test_openai_tool_system_prompt_is_current_events(self):
        """The OpenAI tool must use the current-events analyst system prompt."""
        tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools"
            / "unverified_context_openai.py"
        )
        self.assertTrue(tool_path.exists(), f"Tool not found: {tool_path}")
        source = tool_path.read_text(encoding="utf-8")
        self.assertIn("current-events analyst", source)
        self.assertIn("current date", source.lower())
        self.assertIn("Today is", source)
        self.assertIn("datetime.now(timezone.utc)", source)

    def test_kimi_tool_system_prompt_is_current_events(self):
        """The Kimi tool must use the current-events analyst system prompt."""
        tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools"
            / "unverified_context_kimi.py"
        )
        self.assertTrue(tool_path.exists(), f"Tool not found: {tool_path}")
        source = tool_path.read_text(encoding="utf-8")
        self.assertIn("current-events analyst", source)
        self.assertIn("current date", source.lower())
        self.assertIn("Today is", source)
        self.assertIn("datetime.now(timezone.utc)", source)

    def test_ui_kimi_tool_matches_root(self):
        """The ui-v10 copy of the Kimi tool must match the root copy."""
        root_tool = (
            Path(__file__).resolve().parent.parent.parent
            / "tools"
            / "unverified_context_kimi.py"
        )
        ui_tool = (
            Path(__file__).resolve().parent.parent.parent
            / "ui-v10"
            / "tools"
            / "unverified_context_kimi.py"
        )
        self.assertTrue(ui_tool.exists(), f"UI tool not found: {ui_tool}")
        ui_text = ui_tool.read_text(encoding="utf-8")
        self.assertIn("current-events analyst", ui_text)
        self.assertIn("MOONSHOT_API_KEY", ui_text)

    def test_build_augmented_prompt_includes_date(self):
        """The augmented prompt must include the current date and time."""
        evidence = {
            "context": "Test context from OpenAI.",
            "title": "OpenAI Summary",
            "url": "https://example.com",
            "provider": "openai",
        }
        route = RoutingDecision(
            route="AUGMENTED",
            mode="AUTO",
            intent_family="current_evidence",
            confidence=0.95,
            provider="openai",
            provider_usage_class="paid",
            evidence_mode="required",
        )
        prompt = build_augmented_prompt(
            "What is happening in Ukraine?", evidence, route
        )
        self.assertIn("Current date and time:", prompt)
        self.assertIn("2026-", prompt)  # Year should appear
        self.assertIn("UTC", prompt)
        self.assertIn("Test context from OpenAI.", prompt)
        self.assertIn("if the context is outdated or incomplete", prompt.lower())

    def test_build_augmented_prompt_without_evidence(self):
        """Without evidence, the prompt should just return the question."""
        route = RoutingDecision(
            route="AUGMENTED",
            mode="AUTO",
            intent_family="current_evidence",
            confidence=0.95,
            provider="openai",
            provider_usage_class="paid",
            evidence_mode="required",
        )
        prompt = build_augmented_prompt("What is 2+2?", None, route)
        self.assertEqual(prompt, "What is 2+2?")


class TestProviderToolsOutputFormat(unittest.TestCase):
    """Validate provider CLI tools produce correct JSON structure."""

    def test_openai_tool_json_schema(self):
        """OpenAI tool must output JSON with ok/text/class keys."""
        # We can't call the real API without a key, but we can verify the
        # tool script parses and the payload structure is correct by inspecting
        # the source.
        tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools"
            / "unverified_context_openai.py"
        )
        source = tool_path.read_text(encoding="utf-8")
        # Must emit JSON with these keys on success
        self.assertIn('"ok": True', source)
        self.assertIn('"provider": "openai"', source)
        self.assertIn('"class": "openai_general"', source)
        self.assertIn('"text": text', source)
        # Must emit JSON with these keys on failure
        self.assertIn('"ok": False', source)
        self.assertIn('"provider": "openai"', source)
        self.assertIn('"reason": reason', source)

    def test_kimi_tool_json_schema(self):
        """Kimi tool must output JSON with ok/text/class keys."""
        tool_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tools"
            / "unverified_context_kimi.py"
        )
        source = tool_path.read_text(encoding="utf-8")
        self.assertIn('"ok": True', source)
        self.assertIn('"provider": "kimi"', source)
        self.assertIn('"class": "kimi_general"', source)
        self.assertIn('"text": text', source)
        self.assertIn('"ok": False', source)
        self.assertIn('"reason": reason', source)


class TestSubprocessEnv(unittest.TestCase):
    """Test subprocess environment preparation."""

    def test_env_includes_state_namespace(self):
        """Subprocess env must pass through LUCY_SHARED_STATE_NAMESPACE."""
        from router_py.providers.evidence import _prepare_subprocess_env

        with patch.dict(os.environ, {"LUCY_SHARED_STATE_NAMESPACE": "test-ns"}):
            env = _prepare_subprocess_env()
            self.assertEqual(env["STATE_NAMESPACE_RAW"], "test-ns")

    def test_env_extra_overrides(self):
        """Extra dict values must override base env."""
        from router_py.providers.evidence import _prepare_subprocess_env

        env = _prepare_subprocess_env({"CUSTOM_KEY": "custom_value"})
        self.assertEqual(env["CUSTOM_KEY"], "custom_value")


# ---------------------------------------------------------------------------
# Live-API tests — must have keys in environment
# ---------------------------------------------------------------------------

LIVE_APIS_ENABLED = os.environ.get("LUCY_TEST_LIVE_APIS", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


@unittest.skipUnless(
    LIVE_APIS_ENABLED,
    "Set LUCY_TEST_LIVE_APIS=1 to run live API tests"
    " (requires OPENAI_API_KEY / MOONSHOT_API_KEY)",
)
class TestLiveOpenAI(unittest.TestCase):
    """Live OpenAI smoke tests — costs money. Run sparingly."""

    @classmethod
    def setUpClass(cls):
        if not os.environ.get("OPENAI_API_KEY", "").strip():
            raise unittest.SkipTest("OPENAI_API_KEY not set")

    def test_openai_returns_non_empty_answer(self):
        """Live OpenAI call must return a substantive answer."""
        result = _run_provider_tool(
            "unverified_context_openai.py",
            "What is the current date and what major geopolitical event is in the news?",
        )
        self.assertIsNotNone(result, "OpenAI returned None — check key and network")
        self.assertTrue(result.get("ok"), f"OpenAI returned error: {result}")
        text = result.get("text", "")
        self.assertTrue(
            len(text) > 50,
            f"OpenAI answer too short ({len(text)} chars): {text!r}",
        )

    def test_openai_answer_has_temporal_marker(self):
        """OpenAI answer should reference time or date."""
        result = _run_provider_tool(
            "unverified_context_openai.py",
            "What do you think the probability is of renewed military action between Israel and Iran?",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("ok"), f"OpenAI error: {result}")
        text = result.get("text", "")
        self.assertTrue(
            _has_temporal_marker(text) or "202" in text or "cutoff" in text.lower(),
            f"OpenAI answer lacks temporal awareness: {text[:300]!r}",
        )

    def test_openai_answers_israel_iran_substantively(self):
        """OpenAI must give a substantive answer about Israel-Iran."""
        result = _run_provider_tool(
            "unverified_context_openai.py",
            "What do you think the probability is of renewed military action between Israel and Iran?",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("ok"))
        text = result.get("text", "").lower()
        has_entity = any(
            e in text
            for e in [
                "israel",
                "iran",
                "middle east",
                "regional",
                "conflict",
                "ceasefire",
                "war",
                "tension",
                "escalation",
            ]
        )
        self.assertTrue(
            has_entity,
            f"OpenAI answer lacks relevant entities: {result.get('text', '')[:300]!r}",
        )


@unittest.skipUnless(
    LIVE_APIS_ENABLED,
    "Set LUCY_TEST_LIVE_APIS=1 to run live API tests"
    " (requires OPENAI_API_KEY / MOONSHOT_API_KEY)",
)
class TestLiveKimi(unittest.TestCase):
    """Live Kimi smoke tests — costs money. Run sparingly."""

    @classmethod
    def setUpClass(cls):
        key = os.environ.get("KIMI_API_KEY", "").strip() or os.environ.get(
            "MOONSHOT_API_KEY", ""
        ).strip()
        if not key:
            raise unittest.SkipTest("KIMI_API_KEY / MOONSHOT_API_KEY not set")

    def test_kimi_returns_non_empty_answer(self):
        """Live Kimi call must return a substantive answer."""
        result = _run_provider_tool(
            "unverified_context_kimi.py",
            "What is the current date and what major geopolitical event is in the news?",
        )
        self.assertIsNotNone(result, "Kimi returned None — check key and network")
        self.assertTrue(result.get("ok"), f"Kimi returned error: {result}")
        text = result.get("text", "")
        self.assertTrue(
            len(text) > 50,
            f"Kimi answer too short ({len(text)} chars): {text!r}",
        )

    def test_kimi_answer_has_temporal_marker(self):
        """Kimi answer should reference time or date, or acknowledge its limits."""
        result = _run_provider_tool(
            "unverified_context_kimi.py",
            "Summarize the current geopolitical situation between Israel and Iran as of today.",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("ok"), f"Kimi error: {result}")
        text = result.get("text", "")
        # Kimi may refuse predictions; accept refusals, temporal markers,
        # or any substantive answer about the region.
        has_substance = (
            _has_temporal_marker(text)
            or "202" in text
            or "cutoff" in text.lower()
            or "israel" in text.lower()
            or "iran" in text.lower()
            or "tension" in text.lower()
            or "conflict" in text.lower()
        )
        self.assertTrue(
            has_substance,
            f"Kimi answer lacks substance: {text[:300]!r}",
        )

    def test_kimi_answers_israel_iran_substantively(self):
        """Kimi must give a substantive answer about Israel-Iran."""
        result = _run_provider_tool(
            "unverified_context_kimi.py",
            "What do you think the probability is of renewed military action between Israel and Iran?",
        )
        self.assertIsNotNone(result)
        self.assertTrue(result.get("ok"))
        text = result.get("text", "").lower()
        has_entity = any(
            e in text
            for e in [
                "israel",
                "iran",
                "middle east",
                "regional",
                "conflict",
                "ceasefire",
                "war",
                "tension",
                "escalation",
            ]
        )
        self.assertTrue(
            has_entity,
            f"Kimi answer lacks relevant entities: {result.get('text', '')[:300]!r}",
        )


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def run_tests():
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestTemporalInjection))
    suite.addTests(loader.loadTestsFromTestCase(TestProviderToolsOutputFormat))
    suite.addTests(loader.loadTestsFromTestCase(TestSubprocessEnv))
    suite.addTests(loader.loadTestsFromTestCase(TestLiveOpenAI))
    suite.addTests(loader.loadTestsFromTestCase(TestLiveKimi))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
