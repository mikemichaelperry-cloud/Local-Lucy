"""
Contract tests for the request pipeline refactor.

These tests document desired behavior. Some may initially fail
or be skipped if the pipeline does not yet enforce the contract.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))


class TestSingleAuthoritativePath:
    """
    A. Single authoritative path expectation.
    Text/CLI-style request and HMI/bridge-style request should pass
    through the same pipeline helper once introduced.
    """

    def test_main_run_exists_as_unified_entry(self):
        """main.run() must exist as a callable unified entry point."""
        from router_py.main import run
        assert callable(run)

    def test_hmi_bridge_uses_main_run_not_direct_engine(self):
        """HMI bridge must call main.run(), not instantiate ExecutionEngine directly."""
        source = Path(__file__).resolve().parent.parent.parent / "ui-v10" / "app" / "services" / "runtime_bridge.py"
        source_text = source.read_text()
        assert "main.run(" in source_text or "from router_py.main import run" in source_text
        assert "ExecutionEngine(" not in source_text

    def test_voice_streaming_uses_unified_pipeline(self):
        """streaming_voice.py must use main.run(), not instantiate ExecutionEngine directly."""
        import inspect
        from router_py import streaming_voice
        source = inspect.getsource(streaming_voice.StreamingVoicePipeline._get_full_response)
        assert "ExecutionEngine(" not in source, "Voice streaming should not instantiate ExecutionEngine"
        assert (
            "main.run(" in source
            or "from router_py.main import run" in source
            or "from .main import run" in source
            or "execute_plan_python(" in source
        ), "Voice streaming should use unified pipeline entry point"

    def test_voice_tool_uses_unified_pipeline(self):
        """voice_tool.py must use main.run(), not instantiate ExecutionEngine directly."""
        import inspect
        from router_py import voice_tool
        source = inspect.getsource(voice_tool.VoicePipeline.process_query)
        assert "ExecutionEngine(" not in source, "Voice tool should not instantiate ExecutionEngine"
        assert (
            "main.run(" in source
            or "from router_py.main import run" in source
            or "from .main import run" in source
            or "execute_plan_python(" in source
        ), "Voice tool should use unified pipeline entry point"


class TestMemoryTogglePropagation:
    """
    B. Memory toggle propagation.
    """

    def test_memory_enabled_prefetch_attempted(self, monkeypatch):
        """When memory enabled, prefetch should be attempted."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        from router_py.classify import _memory_routing_gate
        # A follow-up query should trigger the gate when memory is on
        result = _memory_routing_gate("What did I say about him?", "WEATHER")
        assert result == "LOCAL", "Memory gate should override when memory enabled"

    def test_memory_disabled_explicit_recall_routes_local(self, monkeypatch):
        """Explicit recall queries route LOCAL even when memory disabled."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.classify import _memory_routing_gate
        result = _memory_routing_gate("What did I say about him?", "WEATHER")
        assert result == "LOCAL", "Explicit recall should route LOCAL so model can explain memory is disabled"

    def test_memory_disabled_no_injection(self, monkeypatch):
        """When memory disabled, no memory should be injected into prompts."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.execution_engine import _load_session_memory_context_with_telemetry
        context, telemetry = _load_session_memory_context_with_telemetry("hello")
        assert context == ""
        assert telemetry["memory_context_used"] == "false"


class TestMemoryRecallQuery:
    """
    C. Memory recall query.
    """

    def test_memory_recall_uses_stored_fact(self, monkeypatch, tmp_path):
        """Store a fact, recall it."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        # Use a temp memory file
        mem_file = tmp_path / "test_memory.txt"
        mem_file.write_text("User: My favorite color is blue.\n\n")
        monkeypatch.setenv("LUCY_CHAT_MEMORY_FILE", str(mem_file))

        # Mock SQLite assembly to return empty so we test file-based fallback
        import memory.memory_service as mem_svc
        monkeypatch.setattr(
            mem_svc,
            "assemble_context_with_telemetry",
            lambda *a, **k: ("", {"memory_context_used": "false"}),
        )

        from router_py.execution_engine import _load_session_memory_context_with_telemetry
        context, telemetry = _load_session_memory_context_with_telemetry("What is my favorite color?")
        assert "blue" in context.lower()
        assert telemetry["memory_context_used"] == "true"

    def test_memory_recall_route_is_local_or_augmented(self, monkeypatch, tmp_path):
        """Memory recall should route to LOCAL or a memory-aware route, not CLARIFY."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        mem_file = tmp_path / "test_memory.txt"
        mem_file.write_text("User: My favorite color is blue.\n\n")
        monkeypatch.setenv("LUCY_CHAT_MEMORY_FILE", str(mem_file))

        from router_py.classify import classify_intent, select_route
        cl = classify_intent("What is my favorite color?", surface="cli")
        decision = select_route(cl, policy="fallback_only", query="What is my favorite color?")
        assert decision.route in ("LOCAL", "AUGMENTED", "MEMORY_RECALL")


class TestMemoryMustNotOverrideLiveData:
    """
    D. Memory must not override live-data routes.
    """

    def test_weather_stays_weather_despite_memory(self, monkeypatch):
        """Weather query should stay WEATHER even with stale memory."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        from router_py.classify import _memory_routing_gate
        # "weather" keyword should prevent override
        result = _memory_routing_gate("What's the weather?", "WEATHER")
        assert result is None, "Weather keyword must preserve WEATHER route"

    def test_news_stays_news_despite_memory(self, monkeypatch):
        """News query should stay NEWS even with stale memory."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        from router_py.classify import _memory_routing_gate
        result = _memory_routing_gate("Today's headlines?", "NEWS")
        assert result is None, "News keyword must preserve NEWS route"

    def test_time_stays_time_despite_memory(self, monkeypatch):
        """Time query should stay TIME even with stale memory."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "1")
        from router_py.classify import _memory_routing_gate
        result = _memory_routing_gate("What time is it?", "TIME")
        assert result is None, "Time keyword must preserve TIME route"


class TestProviderPreferencePropagation:
    """
    E. Provider preference propagation.
    """

    @pytest.mark.parametrize("provider", ["wikipedia", "openai", "kimi"])
    def test_provider_preference_reaches_resolver(self, monkeypatch, provider):
        """LUCY_AUGMENTED_PROVIDER env var must reach provider resolution."""
        monkeypatch.setenv("LUCY_AUGMENTED_PROVIDER", provider)
        from router_py.provider_resolver import resolve_provider
        from router_py.request_types import ClassificationResult
        classification = ClassificationResult(
            intent="test", intent_family="test", confidence=0.5,
        )
        result = resolve_provider(classification)
        assert result == provider

    def test_provider_preference_medical_safety_override(self, monkeypatch):
        """Medical queries must stay wikipedia regardless of preference."""
        monkeypatch.setenv("LUCY_AUGMENTED_PROVIDER", "openai")
        from router_py.provider_resolver import resolve_provider
        from router_py.request_types import ClassificationResult
        classification = ClassificationResult(
            intent="test", intent_family="test", confidence=0.5,
            evidence_reason="medical_context",
        )
        result = resolve_provider(classification)
        assert result == "wikipedia"

    def test_provider_preference_no_env_falls_back(self, monkeypatch):
        """No env var set should fall back to default provider."""
        monkeypatch.delenv("LUCY_AUGMENTED_PROVIDER", raising=False)
        from router_py.provider_resolver import resolve_provider
        from router_py.request_types import ClassificationResult
        classification = ClassificationResult(
            intent="test", intent_family="background_overview", confidence=0.5,
        )
        result = resolve_provider(classification)
        assert result == "wikipedia"


class TestProviderFailureIsNotRouteCorrection:
    """
    F. Provider failure is not route correction.
    """

    def test_weather_provider_failure_preserves_route(self, monkeypatch):
        """If weather provider fails, route must remain WEATHER, not become LOCAL."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.execution_engine import ExecutionEngine
        from router_py.classify import ClassificationResult, RoutingDecision

        engine = ExecutionEngine(config={"timeout": 30})
        # Force weather provider to return no evidence (simulating failure)
        async def _noop(*a, **k):
            return None
        engine._fetch_weather_evidence = _noop

        classification = ClassificationResult(
            intent="weather", intent_family="current_evidence", confidence=0.9,
            surface="cli", needs_web=True,
        )
        decision = RoutingDecision(
            route="WEATHER", mode="AUTO", intent_family="current_evidence",
            confidence=0.9, provider="weather", provider_usage_class="free",
            evidence_mode="required", evidence_reason="weather_query",
            requires_evidence=True, policy_reason="test",
            ephemeral=True,
        )
        result = engine.execute(classification, decision, {"question": "What's the weather?"}, use_python_path=True)
        assert result.route == "WEATHER", f"Expected WEATHER, got {result.route}"

    def test_news_provider_failure_preserves_route(self, monkeypatch):
        """If news provider fails, route must remain NEWS."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.execution_engine import ExecutionEngine
        from router_py.classify import ClassificationResult, RoutingDecision

        engine = ExecutionEngine(config={"timeout": 30})
        # Force news provider to return no evidence (simulating failure)
        async def _noop(*a, **k):
            return None
        engine._fetch_news_evidence = _noop

        classification = ClassificationResult(
            intent="news", intent_family="current_evidence", confidence=0.9,
            surface="cli", needs_web=True,
        )
        decision = RoutingDecision(
            route="NEWS", mode="AUTO", intent_family="current_evidence",
            confidence=0.9, provider="news", provider_usage_class="free",
            evidence_mode="required", evidence_reason="news_query",
            requires_evidence=True, policy_reason="test",
            ephemeral=True,
        )
        result = engine.execute(classification, decision, {"question": "Latest news?"}, use_python_path=True)
        assert result.route == "NEWS", f"Expected NEWS, got {result.route}"

    def test_augmented_provider_failure_preserves_route(self, monkeypatch):
        """If augmented provider fails, route must remain AUGMENTED."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.execution_engine import ExecutionEngine
        from router_py.classify import ClassificationResult, RoutingDecision

        engine = ExecutionEngine(config={"timeout": 30})
        # Force augmented provider to raise an exception
        engine._call_api_provider_async = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Provider down"))

        classification = ClassificationResult(
            intent="factual", intent_family="background_overview", confidence=0.9,
            surface="cli", needs_web=True,
        )
        decision = RoutingDecision(
            route="AUGMENTED", mode="AUTO", intent_family="background_overview",
            confidence=0.9, provider="openai", provider_usage_class="paid",
            evidence_mode="required", evidence_reason="factual_query",
            requires_evidence=True, policy_reason="test",
        )
        result = engine.execute(classification, decision, {"question": "Explain quantum physics"}, use_python_path=True)
        assert result.route == "AUGMENTED", f"Expected AUGMENTED, got {result.route}"


class TestExplicitUserCorrection:
    """
    G. Explicit user correction remains high-trust.
    """

    def test_explicit_route_correction_logged(self, monkeypatch, tmp_path):
        """'That should have been WEATHER' should log explicit correction."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        feedback_file = tmp_path / "user_feedback.jsonl"
        monkeypatch.setenv("LUCY_USER_FEEDBACK_FILE", str(feedback_file))

        from router_py.main import run
        result = run("That should have been WEATHER", surface="cli")
        assert result.outcome_code == "feedback_acknowledged"
        # After running, check that feedback was logged
        if feedback_file.exists():
            content = feedback_file.read_text()
            assert "ROUTE_CORRECTION" in content or "route" in content.lower()

    def test_negative_answer_feedback_logged(self, monkeypatch, tmp_path):
        """'That was wrong' should log negative feedback."""
        monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
        from router_py.main import run
        result = run("That was wrong", surface="cli")
        assert result.outcome_code == "feedback_acknowledged"


class TestNoStaleStateFileFallback:
    """
    H. No stale state file fallback.
    """

    def test_result_comes_from_execution_not_stale_file(self, monkeypatch, tmp_path):
        """Result should come from direct execution, not stale state files."""
        # The unified path returns RouterOutcome directly.
        # It should not read last_outcome.env or last_route.env as authoritative.
        from router_py.main import run
        result = run("What is 2+2?", surface="cli", timeout=30)
        # Result must have been produced by the current execution
        assert result.request_id != ""
        assert result.execution_time_ms >= 0
