#!/usr/bin/env python3
"""CPU-only unit tests for tools/lora/evaluate_persona.py.

These tests mock Ollama so they run without GPU or a live Ollama server.
"""

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import evaluate_persona as ep


class TestLoadCases(unittest.TestCase):
    def test_load_cases_skips_blank_lines(self):
        text = '\n{"query": "hi", "persona": "michael", "checks": []}\n\n'
        path = Path(self._temp_with(text))
        cases = ep.load_cases(path)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["persona"], "michael")

    def _temp_with(self, text: str) -> str:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(text)
            return f.name


class _FakeResponse:
    def __init__(self, body_dict: dict, captured: dict):
        self._body = json.dumps(body_dict).encode("utf-8")
        self._captured = captured

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class TestQueryOllama(unittest.TestCase):
    def _fake_urlopen(self, response_text: str):
        captured = {}

        def opener(req, **_kwargs):
            data = json.loads(req.data.decode("utf-8")) if req.data else {}
            captured["body"] = data
            return _FakeResponse({"response": response_text}, captured)

        opener.last_body = captured
        return opener

    def test_prompt_only(self):
        fake = self._fake_urlopen("hello")
        with patch("urllib.request.urlopen", fake):
            text = ep.query_ollama("m", "q", "http://x")
        self.assertEqual(text, "hello")
        self.assertNotIn("system", fake.last_body["body"])

    def test_system_prompt_injection(self):
        fake = self._fake_urlopen("hello")
        with patch("urllib.request.urlopen", fake):
            ep.query_ollama("m", "q", "http://x", system="[PERSONA: Michael]")
        self.assertEqual(fake.last_body["body"].get("system"), "[PERSONA: Michael]")


class TestRunCase(unittest.TestCase):
    def test_contains_pass_and_fail(self):
        case = {
            "query": "What is 2+2?",
            "persona": "michael",
            "checks": [
                {"type": "contains", "value": "4"},
                {"type": "not_contains", "value": "5"},
            ],
        }
        with patch.object(ep, "query_ollama", return_value="The answer is 4."):
            result = ep.run_case(case, "m", "http://x")
        self.assertTrue(result["passed"])

        with patch.object(ep, "query_ollama", return_value="The answer is 5."):
            result = ep.run_case(case, "m", "http://x")
        self.assertFalse(result["passed"])
        self.assertEqual(len(result["failures"]), 2)


class TestMainIntegration(unittest.TestCase):
    def _make_cases(self, text: str) -> str:
        import tempfile

        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            f.write(text)
            return f.name

    @patch.object(ep, "query_ollama", return_value="I am Local Lucy, speaking with Michael.")
    def test_passing_run(self, _mock_query):
        cases = self._make_cases(
            json.dumps(
                {
                    "query": "Who am I?",
                    "persona": "michael",
                    "checks": [
                        {"type": "contains", "value": "Michael"},
                    ],
                }
            )
            + "\n"
        )
        with patch("sys.argv", ["evaluate_persona.py", "--model", "m", "--cases", cases]):
            rc = ep.main()
        self.assertEqual(rc, 0)

    @patch.object(ep, "query_ollama", return_value="I am Local Lucy, speaking with Michael.")
    def test_json_output(self, _mock_query):
        cases = self._make_cases(
            json.dumps(
                {
                    "query": "Who am I?",
                    "persona": "michael",
                    "checks": [{"type": "contains", "value": "Michael"}],
                }
            )
            + "\n"
        )
        captured = io.StringIO()
        with patch("sys.argv", ["evaluate_persona.py", "--model", "m", "--cases", cases, "--json"]):
            with patch("sys.stdout", captured):
                rc = ep.main()
        self.assertEqual(rc, 0)
        report = json.loads(captured.getvalue())
        self.assertEqual(report["passed"], 1)
        self.assertEqual(report["total"], 1)
        self.assertIn("per_persona", report)
        self.assertIn("michael", report["per_persona"])

    @patch.object(ep, "query_ollama", return_value="I am Local Lucy, speaking with Michael.")
    def test_prompt_persona_loads_fragment(self, mock_query):
        cases = self._make_cases(
            json.dumps(
                {
                    "query": "Who am I?",
                    "persona": "michael",
                    "checks": [{"type": "contains", "value": "Michael"}],
                }
            )
            + "\n"
        )
        with patch(
            "sys.argv",
            [
                "evaluate_persona.py",
                "--model",
                "m",
                "--cases",
                cases,
                "--prompt-persona",
                "michael",
            ],
        ):
            ep.main()
        # The system prompt should be the michael fragment.
        _, kwargs = mock_query.call_args
        self.assertIn("system", kwargs)
        self.assertIn("Michael", kwargs["system"])


if __name__ == "__main__":
    unittest.main()
