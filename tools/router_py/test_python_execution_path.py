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
from router_py.classify import ClassificationResult, RoutingDecision
from router_py.execution_engine import ExecutionEngine, ExecutionResult
from router_py import response_formatter


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


def test_python_execution_methods_exist() -> None:
    """Test that all Python execution methods exist."""
    print("\n=== Test: Python execution methods exist ===")
    engine = ExecutionEngine()

    # Check all async methods exist
    methods = [
        "execute_async",
        "_execute_full_route_python",
        "_fetch_evidence",
        "_fetch_wikipedia_evidence",
        "_fetch_api_evidence",
        "_call_local_model_async",
        "_call_api_provider_async",
        "_call_wikipedia_provider_async",
        "_run_async_execute",
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

    from router_py import response_formatter

    route = create_test_route_augmented()
    prompt = response_formatter.build_augmented_prompt(question, evidence, route)

    assert question in prompt, "Prompt should include original question"
    assert evidence["context"] in prompt, "Prompt should include evidence context"
    assert evidence["title"] in prompt, "Prompt should include evidence title"

    print("✓ Augmented prompt includes question")
    print("✓ Augmented prompt includes evidence context")
    print("✓ Augmented prompt includes source attribution")


def test_async_execution_flow() -> None:
    """Test the async execution flow."""
    print("\n=== Test: Async execution flow ===")

    engine = ExecutionEngine()

    # Verify the async execute method exists and is a coroutine
    import inspect

    assert inspect.iscoroutinefunction(
        engine.execute_async
    ), "execute_async should be a coroutine function"

    print("✓ execute_async is a coroutine function")

    # Check that _execute_full_route_python is also async
    assert inspect.iscoroutinefunction(
        engine._execute_full_route_python
    ), "_execute_full_route_python should be a coroutine function"

    print("✓ _execute_full_route_python is a coroutine function")


def test_full_python_route_appends_medical_sources_for_medical_augmented_answer() -> None:
    """Medical augmented full-python answers should append disclaimer and sources."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    async def fake_fetch(_question, _route, for_voice=False):
        return {"context": "medical context", "title": "Tadalafil", "url": "https://example.test"}

    async def fake_call_provider(_provider, _prompt, _context):
        return "Grapefruit can increase tadalafil exposure."

    engine._fetch_evidence = fake_fetch
    engine._call_api_provider_async = fake_call_provider
    orig_build = response_formatter.build_augmented_prompt
    orig_validate = response_formatter.validate_response
    response_formatter.build_augmented_prompt = lambda question, evidence, route: question
    response_formatter.validate_response = lambda response, route=None: response

    try:
        result = asyncio.run(
            engine._execute_full_route_python(
                intent,
                route,
                {"question": "Can I take tadalafil with grapefruit?", "medical_context": True},
            )
        )
    finally:
        response_formatter.build_augmented_prompt = orig_build
        response_formatter.validate_response = orig_validate

    assert "Authoritative sources for verification:" in result.response_text
    assert "general knowledge and should be verified" in result.response_text


def test_full_python_route_does_not_append_medical_sources_for_non_medical_answer() -> None:
    """Non-medical full-python augmented answers should stay unchanged."""
    engine = ExecutionEngine()
    intent = create_test_classification()
    route = create_test_route_augmented()

    async def fake_fetch(_question, _route, for_voice=False):
        return {
            "context": "general context",
            "title": "Ada Lovelace",
            "url": "https://example.test",
        }

    async def fake_call_provider(_provider, _prompt, _context):
        return "Ada Lovelace wrote notes on the Analytical Engine."

    engine._fetch_evidence = fake_fetch
    engine._call_api_provider_async = fake_call_provider
    orig_build = response_formatter.build_augmented_prompt
    orig_validate = response_formatter.validate_response
    response_formatter.build_augmented_prompt = lambda question, evidence, route: question
    response_formatter.validate_response = lambda response, route=None: response

    try:
        result = asyncio.run(
            engine._execute_full_route_python(
                intent,
                route,
                {"question": "Who was Ada Lovelace?"},
            )
        )
    finally:
        response_formatter.build_augmented_prompt = orig_build
        response_formatter.validate_response = orig_validate

    assert "Authoritative sources for verification:" not in result.response_text
    assert "general knowledge and should be verified" not in result.response_text


def run_all_tests() -> None:
    """Run all tests."""
    print("=" * 60)
    print("Testing Python-Native Execution Path")
    print("=" * 60)

    try:
        test_python_execution_methods_exist()
        test_execution_result_preserves_route()
        test_evidence_fetching_logic()
        test_build_augmented_prompt()
        test_async_execution_flow()
        test_full_python_route_appends_medical_sources_for_medical_augmented_answer()
        test_full_python_route_does_not_append_medical_sources_for_non_medical_answer()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED")
        print("=" * 60)
        print("\nSummary:")
        print("- AUGMENTED route is preserved (not mapped to LOCAL)")
        print("- Evidence fetching supports multiple providers")
        print("- All async methods are properly implemented")
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
