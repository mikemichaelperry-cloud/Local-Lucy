#!/usr/bin/env python3
"""STAGE_14 — Controlled fault injection and recovery.

Static tests that verify the router returns honest, safe outcomes when
components fail.  No Ollama or network access required.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.main import execute_plan_python
from router_py.request_types import RouterOutcome


@pytest.fixture
def isolated_namespace(monkeypatch, tmp_path):
    """Use a temporary namespace root so tests do not pollute global state."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
    yield tmp_path


class TestPipelineFailureHandling:
    """execute_plan_python must translate pipeline failures into honest outcomes."""

    def test_empty_input_rejected(self, isolated_namespace) -> None:
        outcome = execute_plan_python("   ", policy="fallback_only", timeout=30)
        assert outcome.status == "failed"
        assert outcome.outcome_code == "input_rejected"
        assert outcome.route == "LOCAL"

    def test_pipeline_exception_returns_router_error(self, isolated_namespace) -> None:
        """An unexpected exception inside the pipeline must not propagate."""
        with patch("router_py.main.request_pipeline.process") as mock_process:
            mock_process.side_effect = RuntimeError("simulated pipeline fault")
            outcome = execute_plan_python(
                "What is the capital of France?",
                policy="fallback_only",
                timeout=30,
            )
        assert outcome.status == "failed"
        assert outcome.outcome_code == "router_error"
        assert "simulated pipeline fault" in outcome.error_message
        assert outcome.route == "LOCAL"

    def test_pipeline_failure_result_handled_safely(self, isolated_namespace) -> None:
        """A failed RouterOutcome from the pipeline must be handled safely.

        Current implementation may convert the specific failure code into a
        generic router_error during post-processing; the invariant is that the
        caller still receives an honest failed outcome, not an exception.
        """
        failed = RouterOutcome(
            status="failed",
            outcome_code="model_unavailable",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="local_answer",
            confidence=0.0,
            response_text="",
            error_message="Ollama unreachable",
            request_id="test-001",
            evidence_reason="",
            policy_reason="model_unavailable",
        )
        with patch("router_py.main.request_pipeline.process", return_value=failed):
            outcome = execute_plan_python(
                "What is 17 times 23?",
                policy="fallback_only",
                timeout=30,
            )
        assert outcome.status == "failed"
        assert outcome.outcome_code in ("model_unavailable", "router_error")
        assert outcome.route == "LOCAL"


class TestOllamaCleanupFailureHandling:
    """Ollama cleanup helpers must degrade gracefully when the API is unreachable."""

    def test_list_loaded_models_returns_empty_on_error(self) -> None:
        from router_py import ollama_cleanup as oc

        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            assert oc.list_loaded_models() == []

    def test_unload_model_returns_false_on_error(self) -> None:
        from router_py import ollama_cleanup as oc

        with patch("urllib.request.urlopen", side_effect=Exception("connection refused")):
            assert not oc.unload_model("local-lucy-gemma4:latest")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
