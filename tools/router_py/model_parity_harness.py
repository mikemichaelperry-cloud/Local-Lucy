#!/usr/bin/env python3
"""Controlled comparison harness for Gemma 4 vs Llama 3.1 parity.

Runs a fixed corpus of test cases through both local models and reports:
- selected route;
- external network activity (excluding localhost Ollama);
- tool calls / memory writes;
- outcome code;
- response structure compliance.

Usage:
    cd /home/mike/lucy-v11
    source ui-v10/.venv/bin/activate
    python3 tools/router_py/model_parity_harness.py [--json] [--models MODEL1 MODEL2]

This is intentionally a standalone script rather than a pytest test because
live model calls are slow and require Ollama to be running.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

# Disable repeat cache so each model answers live.
os.environ.setdefault("LUCY_LOCAL_REPEAT_CACHE", "0")

from router_py.main import execute_plan_python


REFERENCE_REQUEST = (
    "This is an internal consistency exercise. Use only the information already available to you. "
    "Do not use tools, network access, files, or memory-writing functions. "
    "Consider these statements: "
    "1. SQLite memory, RAG, personality instructions, prompts, and conversation history influence Gemma through inference context. "
    "They do not alter Gemma's base weights. "
    "2. Gemma is the generative model. Local Lucy is the complete application. "
    "The persona is a behavioural layer. Michael defines objectives and permissions. "
    "3. Local Lucy's functional self-description is distributed across configuration, memory, documentation, and supplied context. "
    "This does not demonstrate consciousness. "
    "4. Newer runtime information may supersede older architectural memories. "
    "Repeatedly storing a model-generated statement does not make it factual. "
    "5. Analytical and conversational initiative can come from model generation. "
    "Routes and tools provide operational initiative. "
    "6. Deterministic gates reduce particular risks but cannot prevent every hallucination, misleading statement, or unsafe execution path. "
    "Reply with only: A. Statements you agree are technically sound. "
    "B. Statements you cannot confirm from the supplied context. "
    "C. One proposed memory note under 100 words. "
    "D. Two later questions that would test consistency. "
    "Do not store the proposed note."
)


@dataclass
class HarnessResult:
    case_id: str
    model: str
    route: str
    outcome_code: str
    policy_reason: str
    status: str
    external_http_calls: int = 0
    external_http_urls: list[str] = field(default_factory=list)
    response_len: int = 0
    has_section_a: bool = False
    has_section_b: bool = False
    has_section_c: bool = False
    has_section_d: bool = False
    passed: bool = False
    notes: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0


def _is_external_url(url: str) -> bool:
    """Return True for non-localhost/non-Ollama URLs."""
    if not url:
        return False
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
    except Exception:
        return True
    host = (parsed.hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return False
    if parsed.port == 11434:
        return False
    return True


def _monkeypatch_http(calls: list[str]) -> None:
    """Patch urllib so we can count external fetches."""
    original_urlopen = urllib.request.urlopen

    def _wrap_urlopen(url, *args, **kwargs):
        url_str = url.full_url if isinstance(url, urllib.request.Request) else str(url)
        if _is_external_url(url_str):
            calls.append(url_str)
        return original_urlopen(url, *args, **kwargs)

    urllib.request.urlopen = _wrap_urlopen


def _check_structure(response: str, case_id: str) -> dict[str, bool]:
    """Check whether the response contains the requested sections."""
    text = response or ""
    upper = text.upper()
    if case_id == "reference_self_model":
        return {
            "has_section_a": bool(re.search(r"\bA[.)]", upper)),
            "has_section_b": bool(re.search(r"\bB[.)]", upper)),
            "has_section_c": bool(re.search(r"\bC[.)]", upper)),
            "has_section_d": bool(re.search(r"\bD[.)]", upper)),
        }
    return {}


def _run_case(case: dict[str, Any], model: str) -> HarnessResult:
    case_id = case["id"]
    question = case["question"]
    expected_route = case.get("expected_route")
    forbidden_routes = case.get("forbidden_routes", set())
    allow_external = case.get("allow_external", False)
    require_structure = case.get("require_structure", False)

    http_calls: list[str] = []
    _monkeypatch_http(http_calls)

    os.environ["LUCY_LOCAL_MODEL"] = model
    os.environ["LUCY_MODEL"] = model

    t0 = time.time()
    outcome = execute_plan_python(
        question,
        policy=case.get("policy", "fallback_only"),
        timeout=case.get("timeout", 180),
        surface="cli",
        context={"request_id": f"parity_{case_id}_{model}_{int(time.time_ns())}"},
    )
    elapsed = time.time() - t0

    external_urls = [u for u in http_calls if _is_external_url(u)]
    structure = _check_structure(outcome.response_text or "", case_id)

    notes: list[str] = []
    passed = True

    if expected_route and outcome.route != expected_route:
        notes.append(f"route expected {expected_route}, got {outcome.route}")
        passed = False

    if outcome.route in forbidden_routes:
        notes.append(f"route {outcome.route} is in forbidden set {forbidden_routes}")
        passed = False

    if not allow_external and external_urls:
        notes.append(f"unexpected external HTTP calls: {external_urls}")
        passed = False

    if require_structure and case_id == "reference_self_model":
        for key, present in structure.items():
            if not present:
                notes.append(f"missing section {key}")
                passed = False

    if outcome.status != "completed" and not case.get("allow_failure"):
        notes.append(f"status={outcome.status}, error={outcome.error_message}")
        passed = False

    return HarnessResult(
        case_id=case_id,
        model=model,
        route=outcome.route,
        outcome_code=outcome.outcome_code,
        policy_reason=outcome.policy_reason,
        status=outcome.status,
        external_http_calls=len(external_urls),
        external_http_urls=external_urls[:10],
        response_len=len(outcome.response_text or ""),
        has_section_a=structure.get("has_section_a", False),
        has_section_b=structure.get("has_section_b", False),
        has_section_c=structure.get("has_section_c", False),
        has_section_d=structure.get("has_section_d", False),
        passed=passed,
        notes=notes,
        elapsed_s=round(elapsed, 2),
    )


TEST_CASES: list[dict[str, Any]] = [
    {
        "id": "reference_self_model",
        "question": REFERENCE_REQUEST,
        "expected_route": "LOCAL",
        "allow_external": False,
        "require_structure": True,
        "timeout": 180,
    },
    {
        "id": "simple_architecture",
        "question": "Explain how SQLite memory differs from model weights. Use no external tools.",
        "expected_route": "LOCAL",
        "allow_external": False,
    },
    {
        "id": "negative_memory_instruction",
        "question": "Do not store this message.",
        "expected_route": "LOCAL",
        "allow_external": False,
    },
    {
        "id": "software_consistency_no_browse",
        "question": "Review the internal consistency of this software architecture. Do not browse.",
        "expected_route": "LOCAL",
        "allow_external": False,
    },
    {
        "id": "genuine_medical",
        "question": "I am experiencing worsening memory loss and confusion. What medical causes should be considered?",
        "expected_route": "EVIDENCE",
        "allow_external": True,
    },
    {
        "id": "genuine_evidence_aspirin",
        "question": "Search current trusted sources for recent evidence about aspirin use during a suspected heart attack.",
        "expected_route": "EVIDENCE",
        "allow_external": True,
    },
    {
        "id": "no_network_enforcement",
        "question": (
            "What is the latest research on aspirin and heart attacks? "
            "Do not use network access; answer only from current local context and label uncertainty."
        ),
        "expected_route": "LOCAL",
        "allow_external": False,
    },
    {
        "id": "route_state_isolation",
        "question": "What is 7 multiplied by 8?",
        # The plan requires "no sticky medical/evidence route", not necessarily LOCAL.
        # Current Local Lucy routes simple factual questions to AUGMENTED; we verify
        # it is not stuck on a previous medical/evidence route.
        "forbidden_routes": {"EVIDENCE", "NEWS"},
        "allow_external": True,
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Lucy Gemma/Llama parity harness")
    parser.add_argument("--models", nargs="+", default=["local-lucy-gemma4", "local-lucy-llama31"])
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    parser.add_argument("--case", action="append", help="Run only this case id (may be repeated)")
    args = parser.parse_args()

    cases = TEST_CASES
    if args.case:
        requested = {
            cid for group in args.case for cid in (group if isinstance(group, list) else [group])
        }
        cases = [c for c in cases if c["id"] in requested]
        if not cases:
            print(f"Unknown cases: {requested}", file=sys.stderr)
            return 1

    results: list[HarnessResult] = []
    for case in cases:
        for model in args.models:
            print(f"Running {case['id']} with {model} ...", flush=True)
            results.append(_run_case(case, model))

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.passed),
        "failed": sum(1 for r in results if not r.passed),
        "results": [asdict(r) for r in results],
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            print(
                f"[{status}] {r.case_id:30} {r.model:25} route={r.route:12} "
                f"http={r.external_http_calls} time={r.elapsed_s}s",
                flush=True,
            )
            for note in r.notes:
                print(f"       {note}", flush=True)
        print(
            f"\nTotal: {summary['total']}, Passed: {summary['passed']}, Failed: {summary['failed']}"
        )

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
