#!/usr/bin/env python3
"""Quick regression tests for the answer-quality fixes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "router_py"))

from router_py.request_pipeline import process


QUERIES = [
    {
        "text": "How Israeli is treated in Japan.",
        "expected_route": "AUGMENTED",
        "expected_provider": "web_untrusted",
        "must_not_contain": ["Live sources are unavailable"],
    },
    {
        "text": "You have the ability to connect to the internet either through augmented or evidence and there is also a gateway through Duck.Go.",
        "expected_route": ("LOCAL", "AUGMENTED"),
        "must_not_contain": ["qualified professional", "veterinary"],
    },
    {
        "text": "What is DuckDuckGo?",
        "expected_route": ("LOCAL", "AUGMENTED"),
        "must_not_contain": ["qualified professional", "veterinary"],
    },
]


def _check(item: dict, outcome, decision) -> bool:
    expected_route = item["expected_route"]
    routes = expected_route if isinstance(expected_route, tuple) else (expected_route,)
    route_ok = outcome.route in routes or (decision and decision.route in routes)

    expected_provider = item.get("expected_provider")
    provider_ok = (
        outcome.provider == expected_provider if expected_provider else True
    )

    response = outcome.response_text or ""
    forbidden_ok = all(phrase.lower() not in response.lower() for phrase in item.get("must_not_contain", []))

    return route_ok and provider_ok and forbidden_ok


def main() -> int:
    all_ok = True
    for item in QUERIES:
        text = item["text"]
        print(f"\n>>> {text!r}")
        outcome, classification, decision = process(text, surface="cli", timeout=130)
        print(f"route={outcome.route!r} provider={outcome.provider!r}")
        print(f"outcome_code={outcome.outcome_code!r}")
        print(f"trust_label={outcome.trust_label!r}")
        print(f"response_text={outcome.response_text[:300]!r}")
        if decision:
            print(f"decision.evidence_reason={decision.evidence_reason!r}")
        ok = _check(item, outcome, decision)
        all_ok = all_ok and ok
        print("PASS" if ok else "FAIL")
    print(f"\n{'ALL PASSED' if all_ok else 'SOME FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
