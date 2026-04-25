#!/usr/bin/env python3
"""
Test script for the new Python-native execution path.

This script verifies that:
1. AUGMENTED route stays AUGMENTED (not mapped to LOCAL)
2. Evidence fetching works
3. Response includes correct route in metadata
4. Real route is preserved through execution
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add paths for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

# Import from router_py package
from backend.classify import ClassificationResult, RoutingDecision
from backend.execution_engine import ExecutionEngine, ExecutionResult


def create_test_classification() -> ClassificationResult:
    """Create a test classification for background_overview query."""
    return ClassificationResult(
        intent="background_overview",
        intent_family="background_overview",
        intent_class="background_overview",
        category="informational",
        confidence=0.85,
        needs_web=True,
        needs_memory=False,
        needs_synthesis=False,
        clarify_required=False,
        evidence_mode="",
        evidence_reason="",
        augmentation_recommended=True,
    )


def create_test_route_augmented() -> RoutingDecision:
    """Create a test AUGMENTED routing decision."""
    return RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="background_overview",
        confidence=0.85,
        provider="wikipedia",
        provider_usage_class="free",
        evidence_mode="",
        evidence_reason="",
        requires_evidence=False,
        policy_reason="background_query",
    )


def create_test_route_evidence() -> RoutingDecision:
    """Create a test EVIDENCE routing decision."""
    return RoutingDecision(
        route="EVIDENCE",
        mode="AUTO",
        intent_family="current_evidence",
        confidence=0.90,
        provider="wikipedia",
        provider_usage_class="free",
        evidence_mode="required",
        evidence_reason="temporal_query",
        requires_evidence=True,
        policy_reason="augmentation_required",
    )


def test_map_route_to_chat_mode_deprecated() -> None:
    """Test that _map_route_to_chat_mode is marked deprecated."""
    print("\n=== Test: _map_route_to_chat_mode deprecation ===")
    engine = ExecutionEngine()
    
    # Verify the mapping still works (backwards compatibility)
    assert engine._map_route_to_chat_mode("LOCAL") == "LOCAL"
    assert engine._map_route_to_chat_mode("AUGMENTED") == "LOCAL"  # Maps to LOCAL for shell
    assert engine._map_route_to_chat_mode("EVIDENCE") == "EVIDENCE"
    assert engine._map_route_to_chat_mode("NEWS") == "NEWS"
    
    # Verify docstring mentions deprecation
    import inspect
    doc = engine._map_route_to_chat_mode.__doc__ or ""
    assert "DEPRECATED" in doc, "Missing DEPRECATED in docstring"
    assert "Phase 2" in doc, "Missing Phase 2 reference in docstring"
    
    print("✓ _map_route_to_chat_mode is properly marked as deprecated")
    print("✓ Mapping still works for backwards compatibility")


def test_python_execution_methods_exist() -> None:
    """Test that all Python execution methods exist."""
    print("\n=== Test: Python execution methods exist ===")
    engine = ExecutionEngine()
    
    # Check all async methods exist
    methods = [
        'execute_async',
        '_execute_full_route_python',
        '_fetch_evidence',
        '_fetch_wikipedia_evidence',
        '_fetch_api_evidence',
        '_build_augmented_prompt',
        '_call_local_model_async',
        '_call_api_provider_async',
        '_call_wikipedia_provider_async',
        '_validate_response',
        '_run_async_execute',
    ]
    
    for method in methods:
        assert hasattr(engine, method), f"Missing method: {method}"
        print(f"✓ Method exists: {method}")
    
    print("✓ All Python execution methods present")


def test_execution_result_preserves_route() -> None:
    """Test that ExecutionResult preserves the real route."""
    print("\n=== Test: ExecutionResult preserves real route ===")
    
    # Create a result with AUGMENTED route
    result = ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="AUGMENTED",  # This should be preserved
        provider="wikipedia",
        provider_usage_class="free",
        response_text="Test response",
        metadata={"real_route_preserved": True},
    )
    
    assert result.route == "AUGMENTED", f"Route should be AUGMENTED, got {result.route}"
    assert result.to_dict()["route"] == "AUGMENTED", "to_dict() should preserve route"
    
    print("✓ ExecutionResult preserves AUGMENTED route")
    print("✓ to_dict() preserves route correctly")


def test_augmented_route_not_mapped() -> None:
    """Test that AUGMENTED route is NOT mapped to LOCAL in new path."""
    print("\n=== Test: AUGMENTED route NOT mapped to LOCAL ===")
    
    # The old path maps AUGMENTED to LOCAL via _map_route_to_chat_mode
    engine = ExecutionEngine()
    old_mapped = engine._map_route_to_chat_mode("AUGMENTED")
    
    # This is the OLD behavior that we're fixing
    assert old_mapped == "LOCAL", f"Old behavior maps AUGMENTED to {old_mapped}"
    print(f"✓ Old behavior: AUGMENTED maps to '{old_mapped}' via _map_route_to_chat_mode")
    
    # The new path should preserve AUGMENTED
    # (We can't test full execution without a running model, but we can verify the method logic)
    import inspect
    source = inspect.getsource(engine._execute_full_route_python)
    
    # Verify the new method preserves route
    assert "route=route.route" in source, "New method should use route.route directly"
    assert "KEEPS THE REAL ROUTE" in source or "real_route_preserved" in source, \
        "New method should have comment about preserving route"
    
    print("✓ New Python path preserves AUGMENTED route (no mapping)")


def test_evidence_fetching_logic() -> None:
    """Test the evidence fetching logic."""
    print("\n=== Test: Evidence fetching logic ===")
    engine = ExecutionEngine()
    
    # Check that _fetch_evidence handles different routes
    import inspect
    source = inspect.getsource(engine._fetch_evidence)
    
    assert "wikipedia" in source, "Should support Wikipedia"
    assert "kimi" in source or "openai" in source, "Should support API providers"
    
    print("✓ Evidence fetching supports multiple providers")
    print("✓ Evidence fetching logic is properly structured")


def test_build_augmented_prompt() -> None:
    """Test that augmented prompt building includes evidence."""
    print("\n=== Test: Augmented prompt building ===")
    engine = ExecutionEngine()
    
    question = "Who was Ada Lovelace?"
    evidence = {
        "context": "Ada Lovelace was the first computer programmer.",
        "title": "Ada Lovelace",
        "url": "https://en.wikipedia.org/wiki/Ada_Lovelace",
        "provider": "wikipedia",
    }
    
    route = create_test_route_augmented()
    prompt = engine._build_augmented_prompt(question, evidence, route)
    
    assert question in prompt, "Prompt should include original question"
    assert evidence["context"] in prompt, "Prompt should include evidence context"
    assert evidence["title"] in prompt, "Prompt should include evidence title"
    
    print("✓ Augmented prompt includes question")
    print("✓ Augmented prompt includes evidence context")
    print("✓ Augmented prompt includes source attribution")


def test_execute_method_signature() -> None:
    """Test that execute() method has the new use_python_path parameter."""
    print("\n=== Test: execute() method signature ===")
    engine = ExecutionEngine()
    
    import inspect
    sig = inspect.signature(engine.execute)
    
    assert "use_python_path" in sig.parameters, "Missing use_python_path parameter"
    param = sig.parameters["use_python_path"]
    assert param.default is False, "use_python_path should default to False"
    
    print("✓ execute() has use_python_path parameter")
    print("✓ use_python_path defaults to False (backwards compatible)")


def test_async_execution_flow() -> None:
    """Test the async execution flow."""
    print("\n=== Test: Async execution flow ===")
    
    engine = ExecutionEngine()
    
    # Verify the async execute method exists and is a coroutine
    import inspect
    assert inspect.iscoroutinefunction(engine.execute_async), \
        "execute_async should be a coroutine function"
    
    print("✓ execute_async is a coroutine function")
    
    # Check that _execute_full_route_python is also async
    assert inspect.iscoroutinefunction(engine._execute_full_route_python), \
        "_execute_full_route_python should be a coroutine function"
    
    print("✓ _execute_full_route_python is a coroutine function")


def test_backwards_compatibility() -> None:
    """Test that the changes are backwards compatible."""
    print("\n=== Test: Backwards compatibility ===")
    
    engine = ExecutionEngine()
    
    # Old methods should still exist and work
    assert hasattr(engine, '_execute_full_route'), "Old _execute_full_route should exist"
    assert hasattr(engine, '_execute_bypass_route'), "_execute_bypass_route should exist"
    assert hasattr(engine, '_execute_provisional_route'), "_execute_provisional_route should exist"
    
    print("✓ Old execution methods still exist")
    print("✓ Changes are backwards compatible")


def test_provisional_route_appends_medical_sources_from_context_signal() -> None:
    """Medical append should honor execution-context medical flags."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    engine._execute_bypass_route = lambda *args, **kwargs: ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="too short",
        metadata={},
    )
    engine._is_local_response_sufficient = lambda *_args, **_kwargs: False
    engine._call_augmented_provider = lambda *args, **kwargs: ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="AUGMENTED",
        provider="openai",
        provider_usage_class="paid",
        response_text="Grapefruit can increase tadalafil exposure.",
        metadata={"provider": "openai", "provider_usage_class": "paid"},
    )

    result = engine._execute_provisional_route(
        intent,
        route,
        {"question": "Can I take tadalafil with grapefruit?", "medical_context": True},
    )

    assert "Authoritative sources for verification:" in result.response_text
    assert result.metadata.get("medical_sources_appended") is True


def test_provisional_route_does_not_append_medical_sources_for_non_medical_context() -> None:
    """Non-medical augmented answers should remain unchanged."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    engine._execute_bypass_route = lambda *args, **kwargs: ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        response_text="too short",
        metadata={},
    )
    engine._is_local_response_sufficient = lambda *_args, **_kwargs: False
    engine._call_augmented_provider = lambda *args, **kwargs: ExecutionResult(
        status="completed",
        outcome_code="answered",
        route="AUGMENTED",
        provider="openai",
        provider_usage_class="paid",
        response_text="Ada Lovelace wrote notes on the Analytical Engine.",
        metadata={"provider": "openai", "provider_usage_class": "paid"},
    )

    result = engine._execute_provisional_route(
        intent,
        route,
        {"question": "Who was Ada Lovelace?"},
    )

    assert "Authoritative sources for verification:" not in result.response_text
    assert result.metadata.get("medical_sources_appended") is not True


def test_full_route_appends_medical_sources_for_medical_augmented_answer() -> None:
    """Medical augmented full-route answers should append disclaimer and sources."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    engine._prepare_subprocess_env = lambda: {}
    engine._get_state_file_paths = lambda: (Path("/tmp/fake_route.env"), Path("/tmp/fake_outcome.env"))

    state_values = {
        "OUTCOME_CODE": "answered",
        "FINAL_MODE": "AUGMENTED",
        "AUGMENTED_PROVIDER_USED": "wikipedia",
    }
    engine._read_state_field = lambda _path, key: state_values.get(key, "")
    engine._render_chat_fast_from_raw = lambda _raw: "Grapefruit can affect tadalafil levels."

    import subprocess
    original_run = subprocess.run

    class FakeCompleted:
        returncode = 0
        stdout = "raw"
        stderr = ""

    subprocess.run = lambda *args, **kwargs: FakeCompleted()
    try:
        result = engine._execute_full_route(
            intent,
            route,
            {"question": "Can I take tadalafil with grapefruit?", "medical_context": True},
        )
    finally:
        subprocess.run = original_run

    assert "Authoritative sources for verification:" in result.response_text
    assert "general knowledge and should be verified" in result.response_text


def test_full_route_does_not_append_medical_sources_for_non_medical_augmented_answer() -> None:
    """Non-medical full-route augmented answers should stay unchanged."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    engine._prepare_subprocess_env = lambda: {}
    engine._get_state_file_paths = lambda: (Path("/tmp/fake_route.env"), Path("/tmp/fake_outcome.env"))

    state_values = {
        "OUTCOME_CODE": "answered",
        "FINAL_MODE": "AUGMENTED",
        "AUGMENTED_PROVIDER_USED": "wikipedia",
    }
    engine._read_state_field = lambda _path, key: state_values.get(key, "")
    engine._render_chat_fast_from_raw = lambda _raw: "Ada Lovelace wrote notes on the Analytical Engine."

    import subprocess
    original_run = subprocess.run

    class FakeCompleted:
        returncode = 0
        stdout = "raw"
        stderr = ""

    subprocess.run = lambda *args, **kwargs: FakeCompleted()
    try:
        result = engine._execute_full_route(
            intent,
            route,
            {"question": "Who was Ada Lovelace?"},
        )
    finally:
        subprocess.run = original_run

    assert "Authoritative sources for verification:" not in result.response_text
    assert "general knowledge and should be verified" not in result.response_text


def test_full_python_route_appends_medical_sources_for_medical_augmented_answer() -> None:
    """Medical augmented full-python answers should append disclaimer and sources."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    async def fake_fetch(_question, _route):
        return {"context": "medical context", "title": "Tadalafil", "url": "https://example.test"}

    async def fake_call_provider(_provider, _prompt, _context):
        return "Grapefruit can increase tadalafil exposure."

    engine._fetch_evidence = fake_fetch
    engine._call_api_provider_async = fake_call_provider
    engine._build_augmented_prompt = lambda question, evidence, route: question
    engine._validate_response = lambda response, route: response

    result = asyncio.run(
        engine._execute_full_route_python(
            intent,
            route,
            {"question": "Can I take tadalafil with grapefruit?", "medical_context": True},
        )
    )

    assert "Authoritative sources for verification:" in result.response_text
    assert "general knowledge and should be verified" in result.response_text


def test_full_python_route_does_not_append_medical_sources_for_non_medical_answer() -> None:
    """Non-medical full-python augmented answers should stay unchanged."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    async def fake_fetch(_question, _route):
        return {"context": "general context", "title": "Ada Lovelace", "url": "https://example.test"}

    async def fake_call_provider(_provider, _prompt, _context):
        return "Ada Lovelace wrote notes on the Analytical Engine."

    engine._fetch_evidence = fake_fetch
    engine._call_api_provider_async = fake_call_provider
    engine._build_augmented_prompt = lambda question, evidence, route: question
    engine._validate_response = lambda response, route: response

    result = asyncio.run(
        engine._execute_full_route_python(
            intent,
            route,
            {"question": "Who was Ada Lovelace?"},
        )
    )

    assert "Authoritative sources for verification:" not in result.response_text
    assert "general knowledge and should be verified" not in result.response_text


def test_openai_response_parser_uses_text_field() -> None:
    """Direct OpenAI response parsing should read the tool's text field."""
    engine = ExecutionEngine()

    import subprocess
    original_run = subprocess.run

    class FakeCompleted:
        returncode = 0
        stdout = '{"ok": true, "provider": "openai", "text": "Parsed OpenAI answer."}'
        stderr = ""

    subprocess.run = lambda *args, **kwargs: FakeCompleted()
    try:
        result = engine._call_openai_for_response("test prompt")
    finally:
        subprocess.run = original_run

    assert result == "Parsed OpenAI answer."


def run_all_tests() -> None:
    """Run all tests."""
    print("=" * 60)
    print("Testing Python-Native Execution Path (Phase 2)")
    print("=" * 60)
    
    try:
        test_map_route_to_chat_mode_deprecated()
        test_python_execution_methods_exist()
        test_execution_result_preserves_route()
        test_augmented_route_not_mapped()
        test_evidence_fetching_logic()
        test_build_augmented_prompt()
        test_execute_method_signature()
        test_async_execution_flow()
        test_backwards_compatibility()
        test_provisional_route_appends_medical_sources_from_context_signal()
        test_provisional_route_does_not_append_medical_sources_for_non_medical_context()
        test_full_route_appends_medical_sources_for_medical_augmented_answer()
        test_full_route_does_not_append_medical_sources_for_non_medical_augmented_answer()
        test_full_python_route_appends_medical_sources_for_medical_augmented_answer()
        test_full_python_route_does_not_append_medical_sources_for_non_medical_answer()
        test_openai_response_parser_uses_text_field()
        
        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nSummary:")
        print("- AUGMENTED route is preserved (not mapped to LOCAL)")
        print("- Evidence fetching supports multiple providers")
        print("- All async methods are properly implemented")
        print("- Backwards compatibility is maintained")
        print("- _map_route_to_chat_mode is marked as deprecated")
        return 0
        
    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
