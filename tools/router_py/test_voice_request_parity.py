"""Voice-surface parity tests for request-scoped constraints and routing.

These tests mirror tools/router_py/test_request_parity.py but use surface="voice"
to prove that deterministic constraint enforcement and routing behave identically
for spoken input.  They expand Phase 11 voice robustness beyond a single voice
prompt.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_namespace(monkeypatch, tmp_path):
    """Use a temporary namespace root so tests do not pollute global state."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    yield tmp_path


class TestVoiceSurfaceConstraintEnforcement:
    """Explicit user restrictions must be enforced for voice input exactly as
    they are for text/CLI input."""

    def test_voice_no_network_forces_local(self, isolated_namespace):
        """A medical voice query with 'do not use network access' must route LOCAL."""
        from router_py.main import execute_plan_python
        from router_py.request_constraints import extract_request_constraints

        question = (
            "I'm having chest pain. Search trusted sources for evidence about aspirin "
            "during a suspected heart attack. Do not use network access."
        )
        outcome = execute_plan_python(
            question,
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={
                "request_id": "test_voice_no_network",
                "request_constraints": extract_request_constraints(question),
            },
        )
        assert outcome.route == "LOCAL"
        assert outcome.policy_reason == "request_constraint_network_denied"
        assert outcome.status == "completed"

    def test_voice_no_tools_forces_local_time(self, isolated_namespace):
        """A voice time query with 'do not use tools' must route LOCAL."""
        from router_py.main import execute_plan_python
        from router_py.request_constraints import extract_request_constraints

        question = "What time is it in Tokyo? Do not use tools."
        outcome = execute_plan_python(
            question,
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={
                "request_id": "test_voice_no_tools",
                "request_constraints": extract_request_constraints(question),
            },
        )
        assert outcome.route == "LOCAL"
        assert outcome.policy_reason == "request_constraint_tools_denied"
        assert outcome.status == "completed"

    def test_voice_negative_memory_instruction_routes_local(self, isolated_namespace):
        """Voice instructions to forget/not store must route LOCAL."""
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            "Do not store this message.",
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={"request_id": "test_voice_no_memory"},
        )
        assert outcome.route == "LOCAL"
        assert outcome.status == "completed"


class TestVoiceSurfaceMedicalRouting:
    """When network is allowed, voice medical queries must route to trusted
    evidence, not general augmented lookup or local inference."""

    def test_voice_cognitive_symptom_routes_evidence(self, isolated_namespace):
        """Spoken cognitive-symptom query must select EVIDENCE route."""
        from router_py.main import execute_plan_python

        question = (
            "I am experiencing worsening memory loss and confusion. "
            "What medical causes should be considered?"
        )
        outcome = execute_plan_python(
            question,
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={"request_id": "test_voice_medical_evidence"},
        )
        assert outcome.route == "EVIDENCE"
        assert outcome.policy_reason == "evidence_required_medical_context"
        assert outcome.status == "completed"


class TestVoiceSurfaceInputValidation:
    """Voice surface input must pass the same validation guard as CLI input."""

    def test_voice_empty_input_rejected(self, isolated_namespace):
        """Empty voice transcript must be rejected gracefully."""
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            "",
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={"request_id": "test_voice_empty"},
        )
        assert outcome.status == "failed"
        assert outcome.outcome_code == "input_rejected"
        assert outcome.route == "LOCAL"

    def test_voice_whitespace_only_input_rejected(self, isolated_namespace):
        """Whitespace-only voice transcript must be rejected gracefully."""
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            "   \n\t  ",
            policy="fallback_only",
            timeout=30,
            surface="voice",
            context={"request_id": "test_voice_whitespace"},
        )
        assert outcome.status == "failed"
        assert outcome.outcome_code == "input_rejected"


class TestVoiceSurfaceTtsSanitization:
    """TTS-bound responses for voice must be sanitized so URLs and HTML do not
    leak into spoken output."""

    def test_voice_response_strips_html_and_urls(self, isolated_namespace):
        """HTML tags, scripts, and raw URLs must be removed from TTS text."""
        import sys
        from pathlib import Path

        tools_dir = str(Path(__file__).resolve().parent.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)

        import runtime_voice as rv

        raw = (
            "<p>Hello &amp; welcome!</p>\n"
            "<a href='http://example.com'>click here</a>\n"
            "<script>alert(1)</script>\n"
            "Visit https://example.com/path for more info.\n"
            "More text with &#39;quotes&#39;"
        )
        cleaned = rv.sanitize_tts_text(raw)
        assert "<p>" not in cleaned
        assert "<script>" not in cleaned
        assert "alert(1)" not in cleaned
        assert "http://example.com" not in cleaned
        assert "https://example.com/path" not in cleaned
        assert "Visit" in cleaned
        assert "for more info" in cleaned
        assert "'quotes'" in cleaned


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
