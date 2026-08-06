#!/usr/bin/env python3
"""Tests for anaphoric search-tool imperatives.

Reproduces the failure where the user, in a restaurant-recommendation thread,
says "Use DuckDuckGo search" and Local Lucy routes LOCAL with a capability
denial instead of searching the ongoing topic.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

from router_py import request_pipeline
from router_py.request_types import RouterOutcome


@pytest.fixture
def temp_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an isolated runtime namespace with a fresh feedback buffer."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    # Reset the singleton buffer so each test loads from the new namespace.
    import router_py.feedback_buffer as fb

    fb._default_buffer = None
    return tmp_path


def _record_exchange(query: str, route: str) -> None:
    """Write a single exchange to the feedback buffer."""
    from router_py.feedback_buffer import record_exchange

    record_exchange(
        query=query,
        route=route,
        intent_family="background_overview",
        response_text="prior answer",
        confidence=0.9,
    )


def test_search_imperative_resolves_to_prior_web_topic(
    temp_namespace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """"Use DuckDuckGo search" after an AUGMENTED query should inherit the topic."""
    _record_exchange("restaurants in Hadera open on Saturday", "AUGMENTED")

    captured: dict[str, Any] = {}

    def _fake_process(question: str, **kwargs: Any) -> tuple[RouterOutcome, Any, Any]:
        captured["question"] = question
        return (
            RouterOutcome(
                status="completed",
                outcome_code="answered",
                route="AUGMENTED",
                provider="wikipedia",
                provider_usage_class="free",
                response_text="fake",
            ),
            None,
            None,
        )

    monkeypatch.setattr(request_pipeline, "process", _fake_process)

    from router_py.main import execute_plan_python

    result = execute_plan_python("Use DuckDuckGo search")
    assert result.route == "AUGMENTED"
    assert "Hadera" in captured["question"], captured


def test_search_imperative_without_prior_topic_stays_clarify_or_local(
    temp_namespace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare search imperative with no web context should not invent a topic."""
    captured: dict[str, Any] = {}

    def _fake_process(question: str, **kwargs: Any) -> tuple[RouterOutcome, Any, Any]:
        captured["question"] = question
        return (
            RouterOutcome(
                status="completed",
                outcome_code="answered",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text="fake",
            ),
            None,
            None,
        )

    monkeypatch.setattr(request_pipeline, "process", _fake_process)

    from router_py.main import execute_plan_python

    result = execute_plan_python("Use DuckDuckGo search")
    # Without prior web context, the original question should be passed through
    # so the model can ask what to search for.
    assert captured["question"] == "Use DuckDuckGo search"


def test_capability_question_still_routes_local(
    temp_namespace: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuine capability question should not be rewritten as a search."""
    _record_exchange("restaurants in Hadera open on Saturday", "AUGMENTED")

    captured: dict[str, Any] = {}

    def _fake_process(question: str, **kwargs: Any) -> tuple[RouterOutcome, Any, Any]:
        captured["question"] = question
        return (
            RouterOutcome(
                status="completed",
                outcome_code="answered",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text="fake",
            ),
            None,
            None,
        )

    monkeypatch.setattr(request_pipeline, "process", _fake_process)

    from router_py.main import execute_plan_python

    result = execute_plan_python("Can you search the web?")
    # Capability questions must remain verbatim so the local model answers them.
    assert captured["question"] == "Can you search the web?"


@pytest.mark.parametrize("query", ["Can you search again?", "search again", "Search again please."])
def test_search_again_resolves_to_prior_web_topic(
    temp_namespace: Path,
    monkeypatch: pytest.MonkeyPatch,
    query: str,
) -> None:
    """"Search again" after a web-route exchange should inherit the prior topic."""
    _record_exchange("restaurants in Hadera open on Saturday", "AUGMENTED")

    captured: dict[str, Any] = {}

    def _fake_process(question: str, **kwargs: Any) -> tuple[RouterOutcome, Any, Any]:
        captured["question"] = question
        return (
            RouterOutcome(
                status="completed",
                outcome_code="answered",
                route="AUGMENTED",
                provider="wikipedia",
                provider_usage_class="free",
                response_text="fake",
            ),
            None,
            None,
        )

    monkeypatch.setattr(request_pipeline, "process", _fake_process)

    from router_py.main import execute_plan_python

    result = execute_plan_python(query)
    assert result.route == "AUGMENTED"
    assert "Hadera" in captured["question"], captured
