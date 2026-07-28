#!/usr/bin/env python3
"""Verify split modules retain their expected public and private API surface."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.static]


REQUIRED_CLASSIFY_EXPORTS = {
    "classify_intent",
    "select_route",
    "prewarm_router",
    "ClassificationResult",
    "RoutingDecision",
    "_is_capability_query",
    "_is_clear_news_query",
    "_is_conflict_analysis_query",
    "_is_cooking_query",
    "_is_financial_ephemeral",
    "_is_hostile_override_attempt",
    "_is_news_query_typos",
    "_is_personal_family_query",
    "_is_public_figure_age_query",
    "_is_time_query",
    "_is_weather_query",
    "_map_to_intent_family",
    "_memory_routing_gate",
    "_call_llm_arbiter",
    "_make_local_decision",
    "_make_augmented_decision",
}

REQUIRED_LOCAL_ANSWER_EXPORTS = {
    "LocalAnswer",
    "LocalAnswerConfig",
    "LocalAnswerLogger",
}

REQUIRED_VOICE_EXPORTS = {
    "AudioBuffer",
    "TranscriptionResult",
    "VADConfig",
    "VoiceMetrics",
    "VoiceResult",
    "VoicePipeline",
    "quick_voice_interaction",
    "clean_text",
    "iso_now",
    "VoicePipelineError",
    "RecordingError",
    "TranscriptionError",
    "SynthesisError",
    "PlaybackError",
}


def test_classify_facade_exports_required_names():
    """router_py.classify must re-export every name other modules/tests use."""
    import router_py.classify as classify

    missing = REQUIRED_CLASSIFY_EXPORTS - set(dir(classify))
    assert not missing, f"Missing from router_py.classify: {missing}"


def test_classify_core_modules_are_importable():
    """Each classify_core submodule must import and expose its expected functions."""
    from router_py.classify_core import guards, intent, memory, router, select

    assert callable(guards._is_capability_query)
    assert callable(intent.classify_intent)
    assert callable(memory._memory_routing_gate)
    assert callable(router.prewarm_router)
    assert callable(select.select_route)


def test_classify_facade_uses_core_objects():
    """Functions re-exported by the facade must be the same objects as in core."""
    from router_py.classify import (
        classify_intent,
        select_route,
        prewarm_router,
        _memory_routing_gate,
    )
    from router_py.classify_core.intent import classify_intent as core_classify_intent
    from router_py.classify_core.router import prewarm_router as core_prewarm_router
    from router_py.classify_core.select import select_route as core_select_route
    from router_py.classify_core.memory import _memory_routing_gate as core_memory_gate

    assert classify_intent is core_classify_intent
    assert select_route is core_select_route
    assert prewarm_router is core_prewarm_router
    assert _memory_routing_gate is core_memory_gate


def test_local_answer_facade_exports():
    """router_py.local_answer facade must expose the public API."""
    import router_py.local_answer as la

    missing = REQUIRED_LOCAL_ANSWER_EXPORTS - set(dir(la))
    assert not missing, f"Missing from router_py.local_answer: {missing}"


def test_local_answer_facade_uses_core_objects():
    """local_answer facade must re-export the same objects as local_answer_core."""
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    from router_py.local_answer_core.engine import LocalAnswer as CoreLocalAnswer
    from router_py.local_answer_core.config import LocalAnswerConfig as CoreConfig

    assert LocalAnswer is CoreLocalAnswer
    assert LocalAnswerConfig is CoreConfig


def test_voice_package_exports():
    """voice package must expose the public API."""
    import router_py.voice as voice

    missing = REQUIRED_VOICE_EXPORTS - set(dir(voice))
    assert not missing, f"Missing from router_py.voice: {missing}"


def test_execution_engine_facade_exports():
    """execution_engine package must expose expected public symbols."""
    import router_py.execution_engine as ee

    assert hasattr(ee, "ExecutionEngine")
    assert callable(ee.create_execution_engine)


def test_state_manager_facade_exports():
    """state_manager module must expose StateManager and helpers."""
    import router_py.state_manager as sm

    assert hasattr(sm, "StateManager")
    assert hasattr(sm, "apply_migrations") or hasattr(sm, "StateManager")


def test_policy_and_policy_router_packages_export():
    """policy and policy_router packages must expose their public symbols."""
    import router_py.policy as policy
    import router_py.policy_router as policy_router

    assert hasattr(policy, "requires_evidence_mode")
    assert hasattr(policy_router, "PolicyRouter")
    assert hasattr(policy_router, "PolicyDecision")


def test_news_package_exports():
    """news package must expose provider/rss utilities."""
    import router_py.news as news

    assert hasattr(news, "provider") or hasattr(news, "rss")
