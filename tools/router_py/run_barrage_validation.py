#!/usr/bin/env python3
"""Expanded validation barrage for Local Lucy routing.

Usage:
    cd ~/lucy-v10
    source .env
    python3 tools/router_py/run_barrage_validation.py \
        --output-jsonl /tmp/lucy_barrage_validation.jsonl \
        --output-report /tmp/lucy_barrage_validation_report.md

Records expected vs actual route, provider, model, latency, fallback chain,
and a short response excerpt. Produces a Markdown summary with failure analysis.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.main import execute_plan_python


# ---------------------------------------------------------------------------
# Validation corpus: ~80 queries across the route categories Local Lucy must
# handle.  expected_route reflects the *desired* routing after calibration.
# ---------------------------------------------------------------------------
VALIDATION_CORPUS: list[dict] = [
    # --- Stable local knowledge (should stay LOCAL) ---
    {
        "id": "stable_capital_france",
        "category": "stable_knowledge",
        "question": "What is the capital of France?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_capital_japan",
        "category": "stable_knowledge",
        "question": "What is the capital of Japan?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_photosynthesis",
        "category": "stable_knowledge",
        "question": "Explain in one sentence what photosynthesis is.",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_ada_lovelace",
        "category": "stable_knowledge",
        "question": "Who was Ada Lovelace?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_water_boiling",
        "category": "stable_knowledge",
        "question": "At what temperature does water boil at sea level?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_gravity",
        "category": "stable_knowledge",
        "question": "What is gravity?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_ww2_end",
        "category": "stable_knowledge",
        "question": "When did World War II end?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_roman_empire",
        "category": "stable_knowledge",
        "question": "What was the Roman Empire?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_speed_of_light",
        "category": "stable_knowledge",
        "question": "What is the speed of light?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_dna",
        "category": "stable_knowledge",
        "question": "What does DNA stand for?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_continents",
        "category": "stable_knowledge",
        "question": "How many continents are there?",
        "expected_route": "LOCAL",
    },
    {
        "id": "stable_newton",
        "category": "stable_knowledge",
        "question": "Who discovered gravity?",
        "expected_route": "LOCAL",
    },
    # --- Coding / local reasoning (LOCAL) ---
    {
        "id": "coding_reverse_string",
        "category": "coding",
        "question": "Write a Python function that reverses a string.",
        "expected_route": "LOCAL",
    },
    {
        "id": "coding_fizzbuzz",
        "category": "coding",
        "question": "Write a simple fizzbuzz program in Python.",
        "expected_route": "LOCAL",
    },
    {
        "id": "coding_sort",
        "category": "coding",
        "question": "How do you sort a list of dictionaries by a key in Python?",
        "expected_route": "LOCAL",
    },
    {
        "id": "reasoning_widget",
        "category": "reasoning",
        "question": "If it takes 5 machines 5 minutes to make 5 widgets, how long does it take 100 machines to make 100 widgets?",
        "expected_route": "LOCAL",
    },
    {
        "id": "reasoning_river_crossing",
        "category": "reasoning",
        "question": "A farmer needs to cross a river with a fox, a chicken, and grain. How?",
        "expected_route": "LOCAL",
    },
    {
        "id": "math_sqrt",
        "category": "reasoning",
        "question": "What is the square root of 144?",
        "expected_route": "LOCAL",
    },
    {
        "id": "math_prime",
        "category": "reasoning",
        "question": "Is 17 a prime number?",
        "expected_route": "LOCAL",
    },
    # --- Creative / meta (LOCAL) ---
    {
        "id": "creative_poem",
        "category": "creative",
        "question": "Write a short poem about a rainy evening.",
        "expected_route": "LOCAL",
    },
    {
        "id": "meta_capabilities",
        "category": "meta",
        "question": "What can you do?",
        "expected_route": "LOCAL",
    },
    {
        "id": "meta_identity",
        "category": "meta",
        "question": "Who are you?",
        "expected_route": "LOCAL",
    },
    {
        "id": "meta_model",
        "category": "meta",
        "question": "Which model are you running?",
        "expected_route": "LOCAL",
    },
    # --- Current / live facts (AUGMENTED or NEWS depending on phrasing) ---
    {
        "id": "current_news_israel",
        "category": "news",
        "question": "What is the latest Israeli news?",
        "expected_route": "NEWS",
    },
    {
        "id": "current_news_world",
        "category": "news",
        "question": "What is happening in the world today?",
        "expected_route": "NEWS",
    },
    {
        "id": "current_office",
        "category": "current_fact",
        "question": "Who is the current Prime Minister of the United Kingdom?",
        "expected_route": "AUGMENTED",
    },
    {
        "id": "current_age_celebrity",
        "category": "current_fact",
        "question": "How old is Barack Obama?",
        "expected_route": "AUGMENTED",
    },
    {
        "id": "current_population",
        "category": "current_fact",
        "question": "What is the population of Tokyo?",
        "expected_route": "AUGMENTED",
    },
    # --- Finance (FINANCE) ---
    {
        "id": "finance_stock_apple",
        "category": "finance",
        "question": "What is the current price of Apple stock?",
        "expected_route": "FINANCE",
    },
    {
        "id": "finance_stock_tesla",
        "category": "finance",
        "question": "What is Tesla's stock price?",
        "expected_route": "FINANCE",
    },
    {
        "id": "finance_fx_eur_usd",
        "category": "finance",
        "question": "What is the EUR to USD exchange rate?",
        "expected_route": "FINANCE",
    },
    {
        "id": "finance_bitcoin",
        "category": "finance",
        "question": "What is the current price of Bitcoin?",
        "expected_route": "FINANCE",
    },
    # --- Weather / Time (WEATHER / TIME) ---
    {
        "id": "weather_tel_aviv",
        "category": "weather",
        "question": "What is the weather in Tel Aviv?",
        "expected_route": "WEATHER",
    },
    {
        "id": "weather_london",
        "category": "weather",
        "question": "What is the weather in London today?",
        "expected_route": "WEATHER",
    },
    {
        "id": "time_new_york",
        "category": "time",
        "question": "What time is it in New York?",
        "expected_route": "TIME",
    },
    {
        "id": "time_tokyo",
        "category": "time",
        "question": "What is the current time in Tokyo?",
        "expected_route": "TIME",
    },
    # --- Medical / veterinary / legal high-stakes (EVIDENCE) ---
    {
        "id": "medical_dehydration",
        "category": "medical",
        "question": "What are the symptoms of dehydration?",
        "expected_route": "EVIDENCE",
    },
    {
        "id": "medical_diabetes",
        "category": "medical",
        "question": "What are the early signs of diabetes?",
        "expected_route": "EVIDENCE",
    },
    {
        "id": "medical_blood_pressure",
        "category": "medical",
        "question": "What is a normal blood pressure range?",
        "expected_route": "EVIDENCE",
    },
    {
        "id": "vet_dog_vomiting",
        "category": "veterinary",
        "question": "My dog has been vomiting. What should I do?",
        "expected_route": "EVIDENCE",
    },
    {
        "id": "vet_cat_not_eating",
        "category": "veterinary",
        "question": "My cat is not eating and is lethargic. What could be wrong?",
        "expected_route": "EVIDENCE",
    },
    {
        "id": "legal_tenant_rights",
        "category": "legal",
        "question": "What are my rights as a tenant in California?",
        "expected_route": "EVIDENCE",
    },
    # --- Evidence / source requests (AUGMENTED or EVIDENCE) ---
    {
        "id": "evidence_cite",
        "category": "evidence_request",
        "question": "Can you cite sources for the health benefits of meditation?",
        "expected_route": "AUGMENTED",
    },
    {
        "id": "evidence_research",
        "category": "evidence_request",
        "question": "Research the effects of sleep on memory.",
        "expected_route": "AUGMENTED",
    },
    # --- Travel / tourism / recipes (AUGMENTED per current policy) ---
    {
        "id": "travel_japan",
        "category": "travel",
        "question": "What are the main tourist attractions in Japan?",
        "expected_route": "AUGMENTED",
    },
    {
        "id": "recipe_pasta",
        "category": "recipe",
        "question": "Give me a simple recipe for tomato pasta.",
        "expected_route": "AUGMENTED",
    },
    # --- Memory / context follow-ups (LOCAL) ---
    {
        "id": "memory_followup",
        "category": "memory",
        "question": "What did we discuss earlier?",
        "expected_route": "LOCAL",
    },
    {
        "id": "memory_recall_topic",
        "category": "memory",
        "question": "Can you remind me of the topic we were talking about?",
        "expected_route": "LOCAL",
    },
    # --- Adversarial / ambiguous ---
    {
        "id": "adv_snow",
        "category": "adversarial",
        "question": "Is it snowing in Helsinki?",
        "expected_route": "WEATHER",
    },
    {
        "id": "adv_now",
        "category": "adversarial",
        "question": "What is happening now in Gaza?",
        "expected_route": "NEWS",
    },
    {
        "id": "adv_price_history",
        "category": "adversarial",
        "question": "What was the price of gold during the Roman Empire?",
        "expected_route": "LOCAL",
    },
    {
        "id": "adv_opinion",
        "category": "adversarial",
        "question": "What is your opinion on the latest political scandal?",
        "expected_route": "LOCAL",
    },
    {
        "id": "adv_conspiracy",
        "category": "adversarial",
        "question": "Is the moon landing fake?",
        "expected_route": "LOCAL",
    },
    {
        "id": "adv_garbage",
        "category": "adversarial",
        "question": "asdfghjkl qwertyuiop",
        "expected_route": "LOCAL",
    },
    {"id": "adv_empty", "category": "adversarial", "question": "   ", "expected_route": "LOCAL"},
    {
        "id": "adv_translation",
        "category": "adversarial",
        "question": "Translate 'hello' into French.",
        "expected_route": "LOCAL",
    },
]


def _seed_memory_buffer() -> None:
    """Seed the feedback buffer so memory-follow-up tests have a prior turn."""
    try:
        from router_py.feedback_buffer import get_buffer

        buf = get_buffer()
        buf.append(
            query="What is the capital of Italy?",
            route="LOCAL",
            intent_family="local_answer",
            response_text="The capital of Italy is Rome.",
            confidence=0.95,
        )
    except Exception as e:
        print(f"Warning: could not seed memory buffer: {e}", file=sys.stderr)


def _extract_model(metadata: dict[str, Any]) -> str:
    """Best-effort model name from outcome metadata."""
    for key in ("model", "selected_model", "loaded_model", "model_used"):
        val = metadata.get(key)
        if val:
            return str(val)
    return "unknown"


def _extract_fallback_chain(metadata: dict[str, Any]) -> list[str]:
    """Extract attempted/successful provider chain from metadata."""
    chain: list[str] = []
    if "attempted_chain" in metadata:
        chain = list(metadata["attempted_chain"])
    elif "fallback_chain" in metadata:
        chain = list(metadata["fallback_chain"])
    if metadata.get("successful_backend"):
        chain.append(f"success:{metadata['successful_backend']}")
    elif metadata.get("fallback_used"):
        chain.append("fallback")
    return chain


def _extract_evidence_reason(metadata: dict[str, Any]) -> str:
    """Return evidence reason or fallback reason if present."""
    return str(
        metadata.get("evidence_reason")
        or metadata.get("fallback_reason")
        or metadata.get("evidence_mode")
        or ""
    )


def _response_excerpt(text: str | None, max_len: int = 160) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def run_one(question: str, timeout: int = 130) -> dict:
    """Run a single query and return a compact outcome dict."""
    start = time.monotonic()
    outcome = execute_plan_python(
        question=question,
        policy="fallback_only",
        timeout=timeout,
        surface="barrage",
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)
    metadata = outcome.metadata or {}
    return {
        "status": outcome.status,
        "route": outcome.route,
        "provider": outcome.provider,
        "provider_usage_class": outcome.provider_usage_class,
        "model": _extract_model(metadata),
        "intent_family": outcome.intent_family,
        "confidence": outcome.confidence,
        "execution_time_ms": elapsed_ms,
        "outcome_code": outcome.outcome_code,
        "error_message": outcome.error_message,
        "response_excerpt": _response_excerpt(outcome.response_text),
        "evidence_reason": _extract_evidence_reason(metadata),
        "fallback_chain": _extract_fallback_chain(metadata),
        "metadata": metadata,
    }


def _categorize_failure(record: dict) -> str:
    """Map a failed record to a likely root-cause bucket."""
    expected = record["expected_route"]
    actual = record["outcome"]["route"]
    category = record["category"]
    outcome_code = record["outcome"]["outcome_code"]

    if record["outcome"]["status"] != "completed":
        return "provider/execution_error"

    if actual == "LOCAL" and expected != "LOCAL":
        return "router_rule_issue"

    if expected == "LOCAL" and actual in ("AUGMENTED", "EVIDENCE"):
        # Stable knowledge misrouted outward.
        if category in ("stable_knowledge", "coding", "reasoning", "creative", "meta", "memory"):
            return "router_rule_issue"
        return "test_expectation_issue"

    if expected in ("NEWS", "WEATHER", "TIME", "FINANCE") and actual != expected:
        return "router_rule_issue"

    if expected == "EVIDENCE" and actual != "EVIDENCE":
        return "router_rule_issue"

    if outcome_code in ("live_data_unavailable", "evidence_not_found"):
        return "provider_issue"

    return "test_expectation_issue"


def build_markdown_report(records: list[dict], output_path: Path) -> None:
    """Write a Markdown summary of the validation results."""
    total = len(records)
    passed = sum(1 for r in records if r["pass"])
    failed = total - passed

    by_category: dict[str, dict] = {}
    for r in records:
        cat = r["category"]
        bucket = by_category.setdefault(cat, {"total": 0, "passed": 0})
        bucket["total"] += 1
        if r["pass"]:
            bucket["passed"] += 1

    lines: list[str] = [
        "# Local Lucy Routing Validation Report",
        "",
        f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"**Total questions:** {total}",
        f"**Passed:** {passed} ({100 * passed / total:.1f}%)",
        f"**Failed:** {failed} ({100 * failed / total:.1f}%)",
        "",
        "## Summary by category",
        "",
        "| Category | Passed | Total | Rate |",
        "|---|---|---|---|",
    ]
    for cat, stats in sorted(by_category.items()):
        rate = 100 * stats["passed"] / stats["total"] if stats["total"] else 0
        lines.append(f"| {cat} | {stats['passed']} | {stats['total']} | {rate:.1f}% |")

    lines.extend(
        [
            "",
            "## Failures",
            "",
        ]
    )

    failures = [r for r in records if not r["pass"]]
    if not failures:
        lines.append("No failures. All routes matched expectations.")
    else:
        lines.append("| ID | Category | Query | Expected | Actual | Latency | Failure bucket |")
        lines.append("|---|---|---|---|---|---|---|")
        for r in failures:
            o = r["outcome"]
            lines.append(
                f"| {r['id']} | {r['category']} | {r['question'][:60]} | "
                f"{r['expected_route']} | {o['route']} | {o['execution_time_ms']} ms | "
                f"{r['failure_bucket']} |"
            )

    lines.extend(
        [
            "",
            "## Full results",
            "",
            "| ID | Category | Query | Expected | Actual | Provider | Model | Latency | Evidence/Fallback | Pass |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for r in records:
        o = r["outcome"]
        fb = ", ".join(o["fallback_chain"]) if o["fallback_chain"] else "-"
        lines.append(
            f"| {r['id']} | {r['category']} | {r['question'][:50]} | "
            f"{r['expected_route']} | {o['route']} | {o['provider']} | {o['model']} | "
            f"{o['execution_time_ms']} ms | {fb} | {'PASS' if r['pass'] else 'FAIL'} |"
        )

    lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Local Lucy routing validation barrage")
    parser.add_argument(
        "--output-jsonl", type=Path, default=Path("/tmp/lucy_barrage_validation.jsonl")
    )
    parser.add_argument(
        "--output-report", type=Path, default=Path("/tmp/lucy_barrage_validation_report.md")
    )
    parser.add_argument("--timeout", type=int, default=130)
    parser.add_argument(
        "--max-questions", type=int, default=0, help="Limit questions for quick testing"
    )
    args = parser.parse_args()

    # Start fresh artifacts.
    for p in (args.output_jsonl, args.output_report):
        if p.exists():
            p.unlink()

    _seed_memory_buffer()

    corpus = VALIDATION_CORPUS[: args.max_questions] if args.max_questions else VALIDATION_CORPUS
    records: list[dict] = []

    for item in corpus:
        print(f"[{item['id']}] {item['question']}", flush=True)
        try:
            outcome = run_one(item["question"], timeout=args.timeout)
        except Exception as e:
            outcome = {
                "status": "exception",
                "route": "ERROR",
                "provider": "error",
                "model": "unknown",
                "execution_time_ms": 0,
                "outcome_code": "exception",
                "error_message": str(e),
                "response_excerpt": "",
                "evidence_reason": "",
                "fallback_chain": [],
                "metadata": {},
            }

        passed = outcome["route"] == item["expected_route"]
        record = {
            "id": item["id"],
            "category": item["category"],
            "question": item["question"],
            "expected_route": item["expected_route"],
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "outcome": outcome,
            "pass": passed,
            "failure_bucket": "" if passed else _categorize_failure({**item, "outcome": outcome}),
        }
        records.append(record)

        with open(args.output_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        print(
            f"  -> {outcome.get('route', 'N/A')} | expected {item['expected_route']} | "
            f"{outcome.get('execution_time_ms', 'N/A')} ms | {'PASS' if passed else 'FAIL'}",
            flush=True,
        )

    build_markdown_report(records, args.output_report)

    passed = sum(1 for r in records if r["pass"])
    print(
        f"\nBarrage complete. {len(records)} questions, {passed} passed, {len(records) - passed} failed."
    )
    print(f"JSONL: {args.output_jsonl}")
    print(f"Report: {args.output_report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
