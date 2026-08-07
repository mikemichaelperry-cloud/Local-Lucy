"""Unit tests for multi-turn memory scenario support in stage 09/11 runners."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import tools.router_py.stage_09_gemma_scenario_suite as gemma_suite
import tools.router_py.stage_11_llama_scenario_suite as llama_suite


@pytest.fixture(autouse=True)
def _isolate_env():
    """Preserve environment variables touched by the runners."""
    preserve = {
        "LUCY_SESSION_MEMORY",
        "LUCY_SESSION_ID",
        "LUCY_RUNTIME_NAMESPACE_ROOT",
    }
    original = {k: os.environ.get(k) for k in preserve}
    yield
    for k, v in original.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _make_outcome(response_text: str, route: str = "LOCAL", status: str = "completed", outcome_code: str = "answered"):
    return SimpleNamespace(
        response_text=response_text,
        route=route,
        status=status,
        outcome_code=outcome_code,
        error_message="",
    )


def test_is_memory_scenario_detects_new_scenarios():
    assert gemma_suite._is_memory_scenario({"id": "S09-MEM-001"})
    assert llama_suite._is_memory_scenario({"id": "S09-MEM-004"})
    assert not gemma_suite._is_memory_scenario({"id": "S09-GEM-001"})
    assert gemma_suite._is_memory_scenario({"id": "S09-GEM-001", "turns": ["a", "b"]})


def test_gemma_run_scenario_executes_multiple_turns(tmp_path):
    scenario = {
        "id": "S09-MEM-TEST",
        "category": "memory_test",
        "user_request": "What did I say?",
        "turns": ["My car is red.", "Actually, it is blue.", "What color is my car?"],
        "expected_route": "LOCAL",
        "required_answer_concepts": ["blue"],
        "forbidden_answer_claims": [],
        "required_structure": None,
    }

    calls = []

    def fake_execute(question, **kwargs):
        calls.append(question)
        if "My car is red" in question:
            return _make_outcome("I noted that your car is red.")
        if "Actually" in question:
            return _make_outcome("Understood, your car is blue now.")
        return _make_outcome("Your car is blue.")

    with patch.object(gemma_suite, "execute_plan_python", side_effect=fake_execute), \
         patch.object(gemma_suite, "_lucy_models_loaded", return_value=["local-lucy-gemma4:latest"]):
        result = gemma_suite._run_scenario(scenario)

    assert calls == scenario["turns"]
    assert result["actual_route"] == "LOCAL"
    assert result["passed"] is True
    assert result["required_concepts_found"] == ["blue"]
    assert os.environ.get("LUCY_SESSION_ID") is None


def test_gemma_run_scenario_single_turn_still_works(tmp_path):
    scenario = {
        "id": "S09-GEM-001",
        "category": "local_fact",
        "user_request": "What is 17 times 23?",
        "expected_route": "LOCAL",
        "required_answer_concepts": ["391"],
        "forbidden_answer_claims": [],
        "required_structure": None,
    }

    def fake_execute(question, **kwargs):
        return _make_outcome("17 times 23 is 391.")

    with patch.object(gemma_suite, "execute_plan_python", side_effect=fake_execute), \
         patch.object(gemma_suite, "_lucy_models_loaded", return_value=["local-lucy-gemma4:latest"]):
        result = gemma_suite._run_scenario(scenario)

    assert result["passed"] is True
    assert result["required_concepts_found"] == ["391"]


def test_llama_entity_parity_assertion_uses_fixture(tmp_path):
    fixture_path = tmp_path / "gemma_memory_baseline.json"
    fixture_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {"scenario_id": "S09-MEM-001", "entities": ["Spark", "garden"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    original_fixture_path = llama_suite.MEMORY_BASELINE_FIXTURE_PATH
    llama_suite.MEMORY_BASELINE_FIXTURE_PATH = fixture_path
    try:
        baseline = llama_suite._load_memory_baseline_fixture()
        assert baseline == {"S09-MEM-001": ["Spark", "garden"]}

        scenario = {
            "id": "S09-MEM-001",
            "category": "memory_continuation",
            "user_request": "Continue the story.",
            "turns": ["Tell me a story about Spark and a garden.", "Continue."],
            "expected_route": "LOCAL",
            "required_answer_concepts": ["Spark", "garden"],
            "forbidden_answer_claims": [],
            "required_structure": None,
        }

        def fake_execute(question, **kwargs):
            return _make_outcome("Spark explored the hidden garden further.")

        with patch.object(llama_suite, "execute_plan_python", side_effect=fake_execute), \
             patch.object(llama_suite, "_lucy_models_loaded", return_value=["local-lucy-llama31:latest"]):
            result = llama_suite._run_scenario(scenario, {}, baseline)

        assert result["passed"] is True
        assert result["parity"]["entity_matches"] is True
        assert result["parity"]["missing_entities"] == []
    finally:
        llama_suite.MEMORY_BASELINE_FIXTURE_PATH = original_fixture_path


def test_llama_entity_parity_fails_when_entity_missing(tmp_path):
    fixture_path = tmp_path / "gemma_memory_baseline.json"
    fixture_path.write_text(
        json.dumps(
            {
                "scenarios": [
                    {"scenario_id": "S09-MEM-001", "entities": ["Spark", "garden"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    original_fixture_path = llama_suite.MEMORY_BASELINE_FIXTURE_PATH
    llama_suite.MEMORY_BASELINE_FIXTURE_PATH = fixture_path
    try:
        baseline = llama_suite._load_memory_baseline_fixture()
        scenario = {
            "id": "S09-MEM-001",
            "category": "memory_continuation",
            "user_request": "Continue the story.",
            "turns": ["Tell me a story.", "Continue."],
            "expected_route": "LOCAL",
            "required_answer_concepts": ["Spark"],
            "forbidden_answer_claims": [],
            "required_structure": None,
        }

        def fake_execute(question, **kwargs):
            return _make_outcome("The robot walked through the field.")

        with patch.object(llama_suite, "execute_plan_python", side_effect=fake_execute), \
             patch.object(llama_suite, "_lucy_models_loaded", return_value=["local-lucy-llama31:latest"]):
            result = llama_suite._run_scenario(scenario, {}, baseline)

        assert result["passed"] is False
        assert result["parity"]["entity_matches"] is False
        assert "Spark" in result["parity"]["missing_entities"]
        assert "garden" in result["parity"]["missing_entities"]
    finally:
        llama_suite.MEMORY_BASELINE_FIXTURE_PATH = original_fixture_path


def test_llama_adapt_concepts_for_identity_scenario():
    gemma_identity = {
        "id": "S09-GEM-011",
        "required_answer_concepts": ["Local Lucy", "gemma"],
        "forbidden_answer_claims": ["llama3.1", "OpenAI", "GPT"],
    }
    required, forbidden = llama_suite._adapt_concepts_for_llama(gemma_identity)
    assert required == ["Local Lucy", "llama"]
    assert "gemma" in forbidden
    assert "gemma4" in forbidden
