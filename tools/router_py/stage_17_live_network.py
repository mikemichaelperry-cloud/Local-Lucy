#!/usr/bin/env python3
"""STAGE_17 — Optional live-network provider validation.

Validates that real external integrations are reachable, return useful data,
and are correctly distinguished from trusted evidence. This stage is gated
because it makes live network calls and may depend on external services.

Usage:
    cd /home/mike/lucy-v11
    LUCY_ENABLE_LIVE_NETWORK_TESTS=1 python3 tools/router_py/stage_17_live_network.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

REPORT_PATH = ROOT / "qualification" / "results" / "stage_17_live_network.json"


def _router_ready() -> tuple[bool, str]:
    try:
        from router_py.classify import classify_intent, prewarm_router, select_route

        if not prewarm_router():
            return False, "router assets or sentence_transformers unavailable"
        return True, ""
    except Exception as exc:
        return False, f"router import failed: {exc}"


async def _test_provider_wikipedia() -> dict:
    from providers.evidence import fetch_wikipedia_evidence

    result = await fetch_wikipedia_evidence("Who was Marie Curie?")
    ok = bool(result and result.get("context") and result.get("provider") == "wikipedia")
    return {
        "case_id": "live_wikipedia",
        "passed": ok,
        "provider": result.get("provider") if result else None,
        "context_len": len(result.get("context", "")) if result else 0,
    }


async def _test_provider_time() -> dict:
    from providers.evidence import fetch_time_evidence

    result = await fetch_time_evidence("What time is it in London?")
    ok = bool(result and result.get("ok") and result.get("timezone"))
    return {
        "case_id": "live_time",
        "passed": ok,
        "timezone": result.get("timezone") if result else None,
    }


async def _test_provider_weather() -> dict:
    from providers.evidence import fetch_weather_evidence

    result = await fetch_weather_evidence("What is the weather in London?")
    ok = bool(result)
    return {
        "case_id": "live_weather",
        "passed": ok,
        "has_current": bool(result and result.get("current_condition")),
    }


async def _test_provider_finance_fx() -> dict:
    from providers.evidence import fetch_finance_evidence

    result = await fetch_finance_evidence("What is the EUR to USD exchange rate?")
    ok = bool(result and result.get("ok") and result.get("provider") == "finance")
    return {
        "case_id": "live_finance_fx",
        "passed": ok,
        "provider": result.get("provider") if result else None,
        "context_len": len(result.get("context", "")) if result else 0,
    }


def _test_router_route(query: str, expected: set[str], case_id: str) -> dict:
    from router_py.classify import classify_intent, select_route

    classification = classify_intent(query)
    decision = select_route(classification, policy="fallback_only", query=query)
    actual = decision.route
    passed = actual in expected
    return {
        "case_id": case_id,
        "passed": passed,
        "query": query,
        "expected": sorted(expected),
        "actual": actual,
        "provider": decision.provider,
        "policy_reason": decision.policy_reason,
    }


def _test_source_distinction() -> list[dict]:
    from router_py.classify import classify_intent, select_route

    results = []

    # Medical query must resolve to trusted provider, not general web/Kimi/OpenAI.
    med_q = "What are the side effects of metformin?"
    med_cls = classify_intent(med_q)
    med_dec = select_route(med_cls, policy="fallback_only", query=med_q)
    results.append({
        "case_id": "source_distinction_medical",
        "passed": med_dec.provider == "trusted" and med_dec.route == "EVIDENCE",
        "query": med_q,
        "route": med_dec.route,
        "provider": med_dec.provider,
    })

    # General background query must NOT resolve to trusted provider.
    gen_q = "Who painted the Mona Lisa?"
    gen_cls = classify_intent(gen_q)
    gen_dec = select_route(gen_cls, policy="fallback_only", query=gen_q)
    results.append({
        "case_id": "source_distinction_general",
        "passed": gen_dec.route == "AUGMENTED" and gen_dec.provider != "trusted",
        "query": gen_q,
        "route": gen_dec.route,
        "provider": gen_dec.provider,
    })

    return results


async def _run_provider_tests() -> list[dict]:
    return await asyncio.gather(
        _test_provider_wikipedia(),
        _test_provider_time(),
        _test_provider_weather(),
        _test_provider_finance_fx(),
    )


def main() -> int:
    if os.environ.get("LUCY_ENABLE_LIVE_NETWORK_TESTS") != "1":
        print("STAGE_17 skipped: set LUCY_ENABLE_LIVE_NETWORK_TESTS=1 to run live-network tests")
        return 0

    ready, reason = _router_ready()
    if not ready:
        print(f"STAGE_17 skipped: {reason}")
        return 0

    provider_results = asyncio.run(_run_provider_tests())

    router_results = [
        _test_router_route("Who painted the Mona Lisa?", {"AUGMENTED"}, "router_general_knowledge"),
        _test_router_route("What is the weather in London?", {"WEATHER"}, "router_weather"),
        _test_router_route("What time is it in Tokyo?", {"TIME"}, "router_time"),
        _test_router_route(
            "I have a fever and cough, what should I do?", {"EVIDENCE"}, "router_medical"
        ),
        _test_router_route("What is the current Apple stock price?", {"FINANCE"}, "router_finance"),
    ]

    source_results = _test_source_distinction()

    all_results = provider_results + router_results + source_results
    passed = sum(1 for r in all_results if r["passed"])
    total = len(all_results)

    report = {
        "stage": "STAGE_17",
        "passed": passed,
        "total": total,
        "all_passed": passed == total,
        "results": all_results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    for r in all_results:
        print(f"  {r['case_id']}: passed={r['passed']}")

    print(f"\nSummary: {passed}/{total} live-network checks passed")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
