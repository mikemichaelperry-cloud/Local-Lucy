#!/usr/bin/env python3
"""Tests for request_pipeline.py."""

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from router_py.request_types import ExecutionResult
from router_py.request_pipeline import (
    _gemma4_bypass_decision,
    _is_gemma4_smart_routing_enabled,
    _looks_like_evidence,
    _looks_like_news,
    process,
    _self_analysis_file_reference,
)


def test_is_gemma4_smart_routing_enabled_only_for_gemma4():
    with patch.dict(os.environ, {"LUCY_GEMMA4_SMART_ROUTING": "on"}, clear=False):
        assert _is_gemma4_smart_routing_enabled("gemma4:12b-it-qat") is True
        assert _is_gemma4_smart_routing_enabled("local-lucy-gemma4") is True
        assert _is_gemma4_smart_routing_enabled("local-lucy-llama31") is False
        assert _is_gemma4_smart_routing_enabled("") is False


def test_is_gemma4_smart_routing_disabled_by_default():
    with patch.dict(os.environ, {}, clear=True):
        assert _is_gemma4_smart_routing_enabled("gemma4:12b-it-qat") is False
        assert _is_gemma4_smart_routing_enabled("local-lucy-gemma4") is False


def test_gemma4_bypass_decision_is_local():
    classification, decision = _gemma4_bypass_decision("hello")
    assert decision.route == "LOCAL"
    assert decision.mode == "SMART"
    assert classification.intent_family == "general"
    assert classification.force_local is True


def test_looks_like_news():
    assert _looks_like_news("latest news about Israel") is True
    assert _looks_like_news("what is the capital of France") is False


def test_looks_like_evidence():
    assert _looks_like_evidence("evidence for climate change") is True
    assert _looks_like_evidence("what is the capital of France") is False


def test_gemma4_bypass_skips_classifier_for_general_query():
    env = {
        "LUCY_MODEL": "gemma4:12b-it-qat",
        "LUCY_GEMMA4_SMART_ROUTING": "on",
    }
    with patch.dict(os.environ, env, clear=True):
        with patch("router_py.request_pipeline.classify_intent") as mock_classify:
            process("what is 2+2")
            mock_classify.assert_not_called()


def test_gemma4_bypass_routes_news_pattern_to_news():
    env = {
        "LUCY_MODEL": "gemma4:12b-it-qat",
        "LUCY_GEMMA4_SMART_ROUTING": "on",
    }
    with patch.dict(os.environ, env, clear=True):
        outcome, classification, decision = process("latest news about Israel")
        assert decision is not None
        assert decision.route == "NEWS"


def test_gemma4_bypass_routes_evidence_pattern_to_evidence():
    env = {
        "LUCY_MODEL": "gemma4:12b-it-qat",
        "LUCY_GEMMA4_SMART_ROUTING": "on",
    }
    with patch.dict(os.environ, env, clear=True):
        outcome, classification, decision = process("evidence for climate change")
        assert decision is not None
        assert decision.route == "EVIDENCE"


def test_non_gemma_model_runs_classifier():
    env = {
        "LUCY_MODEL": "local-lucy-llama31",
        "LUCY_GEMMA4_SMART_ROUTING": "on",
    }
    with patch.dict(os.environ, env, clear=True):
        with patch("router_py.request_pipeline.classify_intent") as mock_classify:
            mock_classify.return_value.type = "general"
            process("what is 2+2")
            mock_classify.assert_called_once()


def test_gemma4_bypass_yields_to_self_analysis_mode(tmp_path, monkeypatch):
    """When Engineering/self-analysis mode is on, smart routing must not bypass it."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True)
    state_dir.joinpath("current_state.json").write_text(
        '{"self_analysis_mode": "on"}', encoding="utf-8"
    )
    # Create the referenced file so extraction succeeds.
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "router_py").mkdir()
    (tmp_path / "tools" / "router_py" / "classify.py").write_text("x = 1\n", encoding="utf-8")

    env = {
        "LUCY_MODEL": "gemma4:12b-it-qat",
        "LUCY_GEMMA4_SMART_ROUTING": "on",
        "LUCY_RUNTIME_NAMESPACE_ROOT": str(tmp_path),
    }
    with patch.dict(os.environ, env, clear=True):
        with patch("router_py.execution_engine.ROOT_DIR", tmp_path):
            with patch("router_py.request_pipeline._gemma4_bypass_decision") as mock_bypass:
                with patch("router_py.request_pipeline.classify_intent") as mock_classify:
                    with patch(
                        "router_py.request_pipeline.ExecutionEngine.execute_self_analysis"
                    ) as mock_execute:
                        mock_execute.return_value = ExecutionResult(
                            status="completed",
                            outcome_code="answered",
                            route="SELF_REVIEW",
                            provider="local",
                            provider_usage_class="local",
                            response_text="review result",
                            error_message="",
                            execution_time_ms=1,
                        )
                        file_path = str(tmp_path / "tools" / "router_py" / "classify.py")
                        outcome, classification, decision = process(f"review {file_path}")
                        mock_bypass.assert_not_called()
                        mock_execute.assert_called_once()
                        assert outcome.route == "SELF_REVIEW"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
