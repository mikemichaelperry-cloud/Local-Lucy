#!/usr/bin/env python3
"""
Comprehensive tests for Evidence and Augmented modes.

Tests:
1. Evidence fetching from each provider (Wikipedia, Kimi, OpenAI)
2. Augmented prompt building with evidence
3. Full EVIDENCE route execution (local model + evidence)
4. Full AUGMENTED route execution (provider direct answer)
5. Provider fallback chains
6. Memory injection in augmented modes

Usage:
    cd /home/mike/lucy-v10
    source ui-v10/.venv/bin/activate
    python3 tools/tests/test_evidence_augmented_modes.py
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Setup paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "router_py"))
sys.path.insert(0, str(ROOT / "models" / "router"))

# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------
from router_py import response_formatter
from router_py.execution_engine import ExecutionEngine
from router_py.providers.evidence import (
    fetch_api_evidence,
    fetch_time_evidence,
    fetch_weather_evidence,
    fetch_wikipedia_evidence,
)
from router_py.request_types import ClassificationResult, RoutingDecision

# ---------------------------------------------------------------------------
# Test framework
# ---------------------------------------------------------------------------

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, details: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}")
        if details:
            print(f"     → {details}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ---------------------------------------------------------------------------
# Section 1: Direct evidence fetching from providers
# ---------------------------------------------------------------------------


async def test_evidence_fetching():
    section("1. Direct Evidence Fetching")

    # 1a. Wikipedia
    print("\n  1a. Wikipedia evidence...")
    try:
        wiki = await fetch_wikipedia_evidence("What is quantum computing?")
        check("Wikipedia returns dict", isinstance(wiki, dict), f"got {type(wiki)}")
        if wiki:
            check(
                "Wikipedia has context",
                bool(wiki.get("context")),
                f"context={wiki.get('context')!r}",
            )
            check("Wikipedia has provider", wiki.get("provider") == "wikipedia")
            check(
                "Wikipedia context is non-empty",
                len(wiki.get("context", "")) > 50,
                f"len={len(wiki.get('context', ''))}",
            )
            print(f"     Context preview: {wiki.get('context', '')[:120]}...")
    except Exception as e:
        check("Wikipedia evidence fetch", False, str(e))

    # 1b. Kimi
    print("\n  1b. Kimi evidence...")
    try:
        kimi = await fetch_api_evidence("What is quantum computing?", "kimi", timeout=30)
        check("Kimi returns dict", isinstance(kimi, dict), f"got {type(kimi)}")
        if kimi:
            check("Kimi has context", bool(kimi.get("context")), f"context={kimi.get('context')!r}")
            check("Kimi has provider", kimi.get("provider") == "kimi")
            print(f"     Context preview: {kimi.get('context', '')[:120]}...")
    except Exception as e:
        check("Kimi evidence fetch", False, str(e))

    # 1c. OpenAI
    print("\n  1c. OpenAI evidence...")
    try:
        openai = await fetch_api_evidence("What is quantum computing?", "openai", timeout=30)
        check("OpenAI returns dict", isinstance(openai, dict), f"got {type(openai)}")
        if openai:
            check(
                "OpenAI has context",
                bool(openai.get("context")),
                f"context={openai.get('context')!r}",
            )
            check("OpenAI has provider", openai.get("provider") == "openai")
            print(f"     Context preview: {openai.get('context', '')[:120]}...")
    except Exception as e:
        check("OpenAI evidence fetch", False, str(e))

    # 1d. Time
    print("\n  1d. Time evidence...")
    try:
        time_ev = await fetch_time_evidence("What time is it in Tokyo?")
        check("Time returns dict", isinstance(time_ev, dict), f"got {type(time_ev)}")
        if time_ev:
            check("Time has ok", time_ev.get("ok") is True, f"ok={time_ev.get('ok')}")
            check("Time has formatted", bool(time_ev.get("formatted")))
            print(f"     Result: {time_ev.get('formatted', 'N/A')}")
    except Exception as e:
        check("Time evidence fetch", False, str(e))

    # 1e. Weather
    print("\n  1e. Weather evidence...")
    try:
        weather = await fetch_weather_evidence("What is the weather in London?")
        check("Weather returns dict", isinstance(weather, dict), f"got {type(weather)}")
        if weather:
            check("Weather has ok", weather.get("ok") is True, f"ok={weather.get('ok')}")
            check("Weather has formatted", bool(weather.get("formatted")))
            print(f"     Result: {weather.get('formatted', 'N/A')[:100]}...")
    except Exception as e:
        check("Weather evidence fetch", False, str(e))


# ---------------------------------------------------------------------------
# Section 2: Augmented prompt building
# ---------------------------------------------------------------------------


def test_augmented_prompt():
    section("2. Augmented Prompt Building")

    evidence = {
        "context": "Quantum computing uses qubits which can exist in superposition.",
        "title": "Quantum Computing",
        "url": "https://example.com/quantum",
        "provider": "wikipedia",
    }
    route = RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="background_overview",
        confidence=0.85,
        provider="wikipedia",
        provider_usage_class="free",
        evidence_mode="required",
        evidence_reason="background_overview",
        requires_evidence=True,
        policy_reason="test",
    )

    prompt = response_formatter.build_augmented_prompt(
        "What is quantum computing?", evidence, route
    )
    check("Prompt contains question", "What is quantum computing?" in prompt)
    check("Prompt contains context", "Quantum computing uses qubits" in prompt)
    check("Prompt contains source", "Source: Quantum Computing" in prompt)
    check("Prompt contains URL", "https://example.com/quantum" in prompt)
    check("Prompt contains provider", "Provider: wikipedia" in prompt)
    check("Prompt ends with instruction", "Based on the background context above" in prompt)

    # Empty evidence
    prompt_empty = response_formatter.build_augmented_prompt("What is X?", None, route)
    check("Empty evidence returns question only", prompt_empty == "What is X?")


# ---------------------------------------------------------------------------
# Section 3: Full execution paths
# ---------------------------------------------------------------------------


async def test_full_execution_paths():
    section("3. Full Execution Paths")

    engine = ExecutionEngine(config={"timeout": 60})

    # 3a. TIME route
    print("\n  3a. TIME route...")
    try:
        intent = ClassificationResult(
            intent="time_query",
            intent_family="current_evidence",
            category="time_query",
            confidence=0.95,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="time_query",
            force_local=False,
        )
        route = RoutingDecision(
            route="TIME",
            provider="timeapi",
            provider_usage_class="free",
            mode="AUTO",
            intent_family="current_evidence",
            confidence=0.95,
            evidence_mode="required",
            evidence_reason="time_query",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What time is it in Tokyo?"}
        )
        check("TIME route completed", result.status == "completed", f"status={result.status}")
        check(
            "TIME route has response",
            len(result.response_text) > 5,
            f"text={result.response_text!r}",
        )
        check("TIME route provider is timeapi", result.provider == "timeapi")
        print(f"     Response: {result.response_text[:100]}...")
    except Exception as e:
        check("TIME route execution", False, str(e))

    # 3b. WEATHER route
    print("\n  3b. WEATHER route...")
    try:
        intent = ClassificationResult(
            intent="weather_query",
            intent_family="current_evidence",
            category="weather",
            confidence=0.95,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="weather_query",
            force_local=False,
        )
        route = RoutingDecision(
            route="WEATHER",
            provider="weather",
            provider_usage_class="free",
            mode="AUTO",
            intent_family="current_evidence",
            confidence=0.95,
            evidence_mode="required",
            evidence_reason="weather_query",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is the weather in London?"}
        )
        check("WEATHER route completed", result.status == "completed", f"status={result.status}")
        check(
            "WEATHER route has response",
            len(result.response_text) > 5,
            f"text={result.response_text!r}",
        )
        check("WEATHER route provider is weather", result.provider == "weather")
        print(f"     Response: {result.response_text[:100]}...")
    except Exception as e:
        check("WEATHER route execution", False, str(e))

    # 3c. EVIDENCE route (local model WITH evidence)
    print("\n  3c. EVIDENCE route (local model + Wikipedia evidence)...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="background_overview",
            force_local=False,
        )
        route = RoutingDecision(
            route="EVIDENCE",
            provider="local",
            provider_usage_class="local",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode="required",
            evidence_reason="background_overview",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is quantum computing?"}
        )
        check("EVIDENCE route completed", result.status == "completed", f"status={result.status}")
        check(
            "EVIDENCE route has response",
            len(result.response_text) > 20,
            f"text={result.response_text!r}",
        )
        check("EVIDENCE route provider is local", result.provider == "local")
        print(f"     Response: {result.response_text[:150]}...")
    except Exception as e:
        check("EVIDENCE route execution", False, str(e))

    # 3d. AUGMENTED route (Wikipedia → local synthesis)
    print("\n  3d. AUGMENTED route (Wikipedia evidence → local synthesis)...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="background_overview",
            force_local=False,
        )
        route = RoutingDecision(
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode="required",
            evidence_reason="background_overview",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is quantum computing?"}
        )
        check("AUGMENTED route completed", result.status == "completed", f"status={result.status}")
        check(
            "AUGMENTED route has response",
            len(result.response_text) > 20,
            f"text={result.response_text!r}",
        )
        # Should fall back to local if wikipedia evidence isn't enough
        print(f"     Response: {result.response_text[:150]}...")
    except Exception as e:
        check("AUGMENTED route execution", False, str(e))

    # 3e. FULL route (Kimi direct answer)
    print("\n  3e. FULL route (Kimi direct answer)...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="background_overview",
            force_local=False,
        )
        route = RoutingDecision(
            route="FULL",
            provider="kimi",
            provider_usage_class="paid",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode="required",
            evidence_reason="background_overview",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is quantum computing?"}
        )
        check("FULL route completed", result.status == "completed", f"status={result.status}")
        check(
            "FULL route has response",
            len(result.response_text) > 20,
            f"text={result.response_text!r}",
        )
        check("FULL route provider is kimi", result.provider == "kimi")
        print(f"     Response: {result.response_text[:150]}...")
    except Exception as e:
        check("FULL route execution", False, str(e))

    # 3f. FULL route (OpenAI direct answer)
    print("\n  3f. FULL route (OpenAI direct answer)...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="background_overview",
            force_local=False,
        )
        route = RoutingDecision(
            route="FULL",
            provider="openai",
            provider_usage_class="paid",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode="required",
            evidence_reason="background_overview",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is quantum computing?"}
        )
        check(
            "FULL (OpenAI) route completed", result.status == "completed", f"status={result.status}"
        )
        check(
            "FULL (OpenAI) route has response",
            len(result.response_text) > 20,
            f"text={result.response_text!r}",
        )
        check("FULL (OpenAI) route provider is openai", result.provider == "openai")
        print(f"     Response: {result.response_text[:150]}...")
    except Exception as e:
        check("FULL (OpenAI) route execution", False, str(e))


# ---------------------------------------------------------------------------
# Section 4: Provider fallback chains
# ---------------------------------------------------------------------------


async def test_provider_fallback_chains():
    section("4. Provider Fallback Chains")

    engine = ExecutionEngine(config={"timeout": 60})

    # 4a. _call_augmented_provider with forced provider chain
    print("\n  4a. Augmented provider chain: wikipedia → kimi → openai...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="AUGMENTED",
            provider="wikipedia",
            provider_usage_class="free",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="test",
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            engine._call_augmented_provider,
            "What is general relativity?",
            intent,
            route,
            {"augmented_provider": "wikipedia"},
        )
        check("Fallback chain completed", result.status == "completed", f"status={result.status}")
        check("Fallback chain has response", len(result.response_text) > 20)
        print(f"     Provider used: {result.provider}")
        print(f"     Response: {result.response_text[:120]}...")
    except Exception as e:
        check("Fallback chain execution", False, str(e))

    # 4b. _call_augmented_provider with kimi first
    print("\n  4b. Augmented provider chain: kimi → openai → wikipedia...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="AUGMENTED",
            provider="kimi",
            provider_usage_class="paid",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="test",
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            engine._call_augmented_provider,
            "What is dark matter?",
            intent,
            route,
            {"augmented_provider": "kimi"},
        )
        check("Kimi-first chain completed", result.status == "completed", f"status={result.status}")
        check("Kimi-first chain has response", len(result.response_text) > 20)
        check("Kimi-first provider is kimi", result.provider == "kimi")
        print(f"     Provider used: {result.provider}")
        print(f"     Response: {result.response_text[:120]}...")
    except Exception as e:
        check("Kimi-first chain execution", False, str(e))

    # 4c. _call_augmented_provider with openai first
    print("\n  4c. Augmented provider chain: openai → kimi → wikipedia...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="AUGMENTED",
            provider="openai",
            provider_usage_class="paid",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="test",
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            engine._call_augmented_provider,
            "What is dark energy?",
            intent,
            route,
            {"augmented_provider": "openai"},
        )
        check(
            "OpenAI-first chain completed", result.status == "completed", f"status={result.status}"
        )
        check("OpenAI-first chain has response", len(result.response_text) > 20)
        check("OpenAI-first provider is openai", result.provider == "openai")
        print(f"     Provider used: {result.provider}")
        print(f"     Response: {result.response_text[:120]}...")
    except Exception as e:
        check("OpenAI-first chain execution", False, str(e))


# ---------------------------------------------------------------------------
# Section 5: Memory injection in augmented modes
# ---------------------------------------------------------------------------


async def test_memory_injection():
    section("5. Memory Injection in Augmented Modes")

    # Check that _load_session_memory_context_with_telemetry passes the question
    from router_py.execution_engine import _load_session_memory_context_with_telemetry

    print("\n  5a. Memory loader receives question (not full prompt)...")
    mem, telem = _load_session_memory_context_with_telemetry("What is quantum computing?")
    check("Memory loader returns string", isinstance(mem, str))
    check("Memory telemetry has keys", "memory_context_used" in telem)

    print("\n  5b. Memory is included in augmented prompt...")
    evidence = {
        "context": "Quantum computing uses qubits.",
        "title": "Quantum Computing",
        "url": "",
        "provider": "wikipedia",
    }
    route = RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="background_overview",
        confidence=0.85,
        provider="local",
        provider_usage_class="local",
        evidence_mode="required",
        evidence_reason="background_overview",
        requires_evidence=True,
        policy_reason="test",
    )
    prompt = response_formatter.build_augmented_prompt(
        "What is quantum computing?", evidence, route
    )
    check("Augmented prompt has question", "What is quantum computing?" in prompt)
    check("Augmented prompt has evidence", "Quantum computing uses qubits" in prompt)

    print("\n  5c. Full EVIDENCE execution with memory...")
    engine = ExecutionEngine(config={"timeout": 60})
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode="required",
            evidence_reason="background_overview",
            force_local=False,
        )
        route = RoutingDecision(
            route="EVIDENCE",
            provider="local",
            provider_usage_class="local",
            mode="AUTO",
            intent_family="background_overview",
            confidence=0.85,
            evidence_mode="required",
            evidence_reason="background_overview",
            requires_evidence=True,
            policy_reason="test",
        )
        result = await engine.execute_async(
            intent, route, {"question": "What is quantum computing?"}
        )
        check("EVIDENCE with memory completed", result.status == "completed")
        check("EVIDENCE with memory has response", len(result.response_text) > 20)
        print(f"     Response: {result.response_text[:120]}...")
    except Exception as e:
        check("EVIDENCE with memory", False, str(e))


# ---------------------------------------------------------------------------
# Section 6: Provisional route (local first, fallback to augmentation)
# ---------------------------------------------------------------------------


async def test_provisional_route():
    section("6. Provisional Route (local first + augmentation fallback)")

    engine = ExecutionEngine(config={"timeout": 60})

    print("\n  6a. Provisional with simple factual query...")
    try:
        intent = ClassificationResult(
            intent="local_answer",
            intent_family="local_answer",
            category="general",
            confidence=0.95,
            needs_web=False,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            mode="AUTO",
            intent_family="local_answer",
            confidence=0.95,
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="local_sufficient",
        )
        result = await engine.execute_async(intent, route, {"question": "What is 2+2?"})
        check("Provisional local completed", result.status == "completed")
        check("Provisional local has response", len(result.response_text) > 0)
        print(f"     Response: {result.response_text[:80]}...")
    except Exception as e:
        check("Provisional local", False, str(e))

    print("\n  6b. Provisional with web query (should attempt augmentation fallback)...")
    try:
        intent = ClassificationResult(
            intent="background_overview",
            intent_family="background_overview",
            category="science",
            confidence=0.85,
            needs_web=True,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            mode="AUTO",
            intent_family="local_answer",
            confidence=0.95,
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="local_first_fallback_allowed",
        )
        # Set policy to fallback_only to trigger provisional behavior
        result = await engine.execute_async(
            intent,
            route,
            {
                "question": "What is the latest news about space exploration?",
                "augmentation_policy": "fallback_only",
            },
        )
        check("Provisional fallback completed", result.status == "completed")
        check("Provisional fallback has response", len(result.response_text) > 20)
        print(f"     Route: {result.route}, Provider: {result.provider}")
        print(f"     Response: {result.response_text[:120]}...")
    except Exception as e:
        check("Provisional fallback", False, str(e))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    print("=" * 60)
    print("  Evidence & Augmented Mode Comprehensive Test Suite")
    print("=" * 60)
    print(f"\n  Root: {ROOT}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    await test_evidence_fetching()
    test_augmented_prompt()
    await test_full_execution_paths()
    await test_provider_fallback_chains()
    await test_memory_injection()
    await test_provisional_route()

    print("\n" + "=" * 60)
    print(f"  Results: {PASSED} passed, {FAILED} failed")
    print("=" * 60)
    return FAILED == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
