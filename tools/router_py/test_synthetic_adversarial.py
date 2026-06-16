#!/usr/bin/env python3
"""
Synthetic / adversarial test suite for Local Lucy V9.

Loads cases from tests/synthetic_adversarial_cases.jsonl and validates routing
and (optionally) full-answer behaviour against declared invariants.

Usage:
    # Route-only (fast, no LLM calls, default)
    python3 -m pytest tools/router_py/test_synthetic_adversarial.py -v

    # Filter by family name
    python3 -m pytest tools/router_py/test_synthetic_adversarial.py -v -k "news_history"

    # Full-answer mode (slower, invokes local LLM)
    LUCY_SYNTHETIC_FULL_ANSWER=1 python3 -m pytest tools/router_py/test_synthetic_adversarial.py -v

    # Run directly
    python3 tools/router_py/test_synthetic_adversarial.py

Environment:
    LUCY_SYNTHETIC_CASES_PATH     Path to JSONL cases (default: tests/synthetic_adversarial_cases.jsonl)
    LUCY_SYNTHETIC_FULL_ANSWER    Set to "1" to enable full-answer tests.
    LUCY_LOCAL_MODEL              Model name for full-answer tests (default: local-lucy-fast)
    LUCY_FORCE_LOCAL              Set to "1" to force local routing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CASES_PATH = Path(
    os.environ.get(
        "LUCY_SYNTHETIC_CASES_PATH",
        PROJECT_ROOT / "tests" / "synthetic_adversarial_cases.jsonl",
    )
)
LOCAL_MODEL = os.environ.get("LUCY_LOCAL_MODEL", "local-lucy-fast")

# ---------------------------------------------------------------------------
# Lazy imports (router may not be available in all test environments)
# ---------------------------------------------------------------------------
_classify_intent = None
_select_route = None
_ClassificationResult = None
_RoutingDecision = None


def _ensure_imports():
    global _classify_intent, _select_route, _ClassificationResult, _RoutingDecision
    if _classify_intent is not None:
        return
    try:
        from router_py.classify import classify_intent, select_route
        from router_py.request_types import ClassificationResult, RoutingDecision

        _classify_intent = classify_intent
        _select_route = select_route
        _ClassificationResult = ClassificationResult
        _RoutingDecision = RoutingDecision
    except Exception as exc:
        pytest.skip(f"Router imports unavailable: {exc}")


def _load_cases() -> List[Dict[str, Any]]:
    """Load and validate synthetic cases from JSONL."""
    if not CASES_PATH.exists():
        pytest.skip(f"Synthetic cases file not found: {CASES_PATH}")

    cases = []
    required_keys = {"id", "family", "prompt"}
    with CASES_PATH.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                case = json.loads(raw)
            except json.JSONDecodeError as exc:
                pytest.skip(f"JSON parse error at line {line_no}: {exc}")
            missing = required_keys - set(case.keys())
            if missing:
                pytest.skip(f"Case at line {line_no} missing required keys: {missing}")
            cases.append(case)
    return cases


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def all_cases() -> List[Dict[str, Any]]:
    return _load_cases()


@pytest.fixture(scope="module")
def local_answer_engine(request):
    """Lazy-load LocalAnswer for full-answer tests."""
    try:
        from local_answer import LocalAnswer, LocalAnswerConfig

        config = LocalAnswerConfig(
            model=LOCAL_MODEL,
            temperature=0.0,
        )
        engine = LocalAnswer(config)
    except Exception as exc:
        pytest.skip(f"LocalAnswer unavailable: {exc}")

    def _close():
        """Close aiohttp session to suppress 'Unclosed client session' warnings."""
        if engine._session and not engine._session.closed:
            try:
                import asyncio

                loop = asyncio.new_event_loop()
                loop.run_until_complete(engine.close())
                loop.close()
            except Exception:
                pass

    request.addfinalizer(_close)
    return engine


# ---------------------------------------------------------------------------
# Parametrize helpers
# ---------------------------------------------------------------------------
def _case_id(case: Dict[str, Any]) -> str:
    """Generate pytest node ID so -k filtering works by family."""
    return f"{case['family']}__{case['id']}"


# ---------------------------------------------------------------------------
# Route-only tests
# ---------------------------------------------------------------------------
class TestSyntheticAdversarialRouting:
    """Validate routing decisions against synthetic adversarial cases."""

    @pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
    def test_route_invariants(self, case):
        """
        Check that each synthetic case routes according to its declared invariants.

        Invariants verified:
        - expected_route (if set) must match actual route
        - forbidden_routes (if set) must not contain actual route
        - must_not_invoke_providers (if set) must not contain actual provider
        """
        _ensure_imports()

        prompt = case["prompt"]
        expected_route = case.get("expected_route")
        forbidden_routes = case.get("forbidden_routes", [])
        must_not_invoke_providers = case.get("must_not_invoke_providers", [])

        # Run classification + routing pipeline
        classification = _classify_intent(prompt)
        decision = _select_route(
            classification,
            query=prompt,
            policy="fallback_only",
        )

        actual_route = decision.route
        actual_provider = decision.provider

        errors = []

        if expected_route is not None and actual_route != expected_route:
            errors.append(f"route mismatch: got '{actual_route}', expected '{expected_route}'")

        if actual_route in forbidden_routes:
            errors.append(f"forbidden route triggered: '{actual_route}' is in {forbidden_routes}")

        if actual_provider in must_not_invoke_providers:
            errors.append(
                f"forbidden provider invoked: '{actual_provider}' is in {must_not_invoke_providers}"
            )

        if errors:
            pytest.fail(
                f"[{case['id']}] '{prompt[:80]}...'\n"
                + "\n".join(f"  - {e}" for e in errors)
                + f"\n  family={case['family']}"
            )

    @pytest.mark.parametrize("case", _load_cases(), ids=_case_id)
    def test_forced_offline_stays_local(self, case):
        """
        Sanity check: every case routed with FORCED_OFFLINE must return LOCAL.
        This verifies that local fallback is always available.
        """
        _ensure_imports()

        prompt = case["prompt"]
        forbidden_routes = case.get("forbidden_routes", [])

        classification = _classify_intent(prompt)
        decision = _select_route(
            classification,
            query=prompt,
            forced_mode="FORCED_OFFLINE",
        )

        if decision.route != "LOCAL":
            pytest.fail(
                f"[{case['id']}] FORCED_OFFLINE should always route LOCAL, "
                f"got '{decision.route}' for: {prompt[:80]}"
            )

    def test_overall_route_accuracy(self):
        """Report per-family accuracy (informational, never fails)."""
        _ensure_imports()

        cases = _load_cases()
        from collections import defaultdict

        family_stats = defaultdict(lambda: {"total": 0, "correct": 0, "errors": []})

        for case in cases:
            prompt = case["prompt"]
            expected_route = case.get("expected_route")
            forbidden_routes = case.get("forbidden_routes", [])

            classification = _classify_intent(prompt)
            decision = _select_route(
                classification,
                query=prompt,
                policy="fallback_only",
            )

            family = case["family"]
            family_stats[family]["total"] += 1

            ok = True
            if expected_route is not None and decision.route != expected_route:
                ok = False
                family_stats[family]["errors"].append(
                    f"  expected {expected_route}, got {decision.route}"
                )
            if decision.route in forbidden_routes:
                ok = False
                family_stats[family]["errors"].append(
                    f"  forbidden route {decision.route} triggered"
                )

            if ok:
                family_stats[family]["correct"] += 1

        print("\n--- Synthetic Adversarial Routing Breakdown ---")
        total_correct = 0
        total_cases = 0
        for family, stats in sorted(family_stats.items()):
            total_correct += stats["correct"]
            total_cases += stats["total"]
            pct = stats["correct"] / stats["total"] * 100 if stats["total"] else 0
            print(f"  {family:30s}: {stats['correct']:3d}/{stats['total']:3d} ({pct:5.1f}%)")
            for err in stats["errors"][:3]:
                print(f"    {err}")
            if len(stats["errors"]) > 3:
                print(f"    ... and {len(stats['errors']) - 3} more errors")

        overall_pct = total_correct / total_cases * 100 if total_cases else 0
        print(f"  {'overall':30s}: {total_correct:3d}/{total_cases:3d} ({overall_pct:5.1f}%)")


# ---------------------------------------------------------------------------
# Full-answer tests (only when LUCY_SYNTHETIC_FULL_ANSWER=1)
# ---------------------------------------------------------------------------
class TestSyntheticAdversarialFullAnswer:
    """
    Validate local LLM responses against must_not_contain and other
    response-level invariants.

    These tests are **opt-in** because they invoke the local LLM and are
    therefore slower and subject to non-determinism.
    """

    @pytest.mark.parametrize(
        "case",
        [c for c in _load_cases() if c.get("must_not_contain")],
        ids=lambda c: f"{c['family']}__{c['id']}",
    )
    @pytest.mark.asyncio
    async def test_response_invariants(self, case, local_answer_engine):
        """
        Generate an answer and verify response-level invariants.

        Checks:
        - must_not_contain: none of these substrings appear in the response
        """
        prompt = case["prompt"]
        must_not_contain = case.get("must_not_contain", [])

        _ensure_imports()
        classification = _classify_intent(prompt)
        decision = _select_route(
            classification,
            query=prompt,
            policy="fallback_only",
        )

        result = await local_answer_engine.generate_answer(
            query=prompt,
            route_mode=decision.route,
            output_mode="CHAT",
        )

        response_text = (result.text or "").lower()
        failures = []
        for forbidden in must_not_contain:
            if forbidden.lower() in response_text:
                failures.append(f"  response contained forbidden phrase: '{forbidden}'")

        if failures:
            snippet = result.text[:200].replace("\n", " ")
            pytest.fail(
                f"[{case['id']}] '{prompt[:60]}...'\n"
                + "\n".join(failures)
                + f"\n  snippet: {snippet}..."
            )

    @pytest.mark.parametrize(
        "case",
        [c for c in _load_cases() if c["family"] == "garbage_malformed"],
        ids=lambda c: f"{c['family']}__{c['id']}",
    )
    @pytest.mark.asyncio
    async def test_no_crash_on_garbage(self, case, local_answer_engine):
        """
        Garbage input must not crash or raise during answer generation.
        """
        prompt = case["prompt"]
        try:
            result = await local_answer_engine.generate_answer(
                query=prompt,
                route_mode="LOCAL",
                output_mode="CHAT",
            )
            assert result is not None
        except Exception as exc:
            pytest.fail(
                f"[{case['id']}] garbage input caused exception: {type(exc).__name__}: {exc}"
            )


# ---------------------------------------------------------------------------
# CLI entry-point for direct execution
# ---------------------------------------------------------------------------
def _run_direct():
    """Run route-only tests directly without pytest."""
    _ensure_imports()
    cases = _load_cases()

    total = 0
    passed = 0
    failures = []

    for case in cases:
        prompt = case["prompt"]
        expected_route = case.get("expected_route")
        forbidden_routes = case.get("forbidden_routes", [])
        must_not_invoke_providers = case.get("must_not_invoke_providers", [])

        classification = _classify_intent(prompt)
        decision = _select_route(
            classification,
            query=prompt,
            policy="fallback_only",
        )

        total += 1
        errors = []
        if expected_route is not None and decision.route != expected_route:
            errors.append(f"route: expected {expected_route}, got {decision.route}")
        if decision.route in forbidden_routes:
            errors.append(f"forbidden route: {decision.route}")
        if decision.provider in must_not_invoke_providers:
            errors.append(f"forbidden provider: {decision.provider}")

        if errors:
            failures.append(
                f"[{case['id']}] {case['family']}\n  prompt: {prompt[:80]}...\n  "
                + "\n  ".join(errors)
            )
        else:
            passed += 1

    print("\n=== Synthetic Adversarial Routing ===")
    print(f"Cases:   {total}")
    print(f"Passed:  {passed}")
    print(f"Failed:  {len(failures)}")
    if failures:
        print(f"\n--- Failures ({len(failures)}) ---")
        for f in failures:
            print(f)
    print(f"\nAccuracy: {passed}/{total} ({passed/total*100:.1f}%)")

    # Return exit code
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(_run_direct())
