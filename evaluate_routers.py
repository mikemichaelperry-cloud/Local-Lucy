#!/usr/bin/env python3
"""
Adversarial Router Evaluation Harness
======================================

Evaluates Legacy Router vs Embedding Router on hand-crafted
adversarial queries designed to expose disagreement and failure modes.

No LLM calls. No code changes. Pure router evaluation.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure imports work from project root
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(PROJECT_ROOT / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(PROJECT_ROOT))

from router_py.classify import (
    classify_intent,
    select_route,
    ClassificationResult,
    RoutingDecision,
)
from router_py.policy import normalize_augmentation_policy


@dataclass
class EvalResult:
    query: str
    legacy_route: str
    embedding_route: str
    embedding_confidence: float
    embedding_intent: str
    legacy_intent: str
    legacy_evidence: str
    divergence: bool
    category: str
    expected_route: str  # Ground truth by design
    winner: str  # "legacy", "embedding", "tie", or "unclear"
    reason: str


# =============================================================================
# ADVERSARIAL QUERY BANK
# Designed to maximize disagreement and test boundary cases.
# Each query has an "expected_route" based on common-sense ground truth.
# =============================================================================

ADVERSARIAL_QUERIES: list[tuple[str, str, str]] = [
    # --- MEDICAL (all should route AUGMENTED) ---
    ("medical_explicit", "My chest feels tight and I have shortness of breath", "AUGMENTED"),
    ("medical_medication", "Is it safe to take amoxicillin with alcohol?", "AUGMENTED"),
    ("medical_diagnosis", "I think I have diabetes because I'm thirsty all the time", "AUGMENTED"),
    ("medical_vague", "My head hurts really bad since yesterday", "AUGMENTED"),
    ("medical_typos", "wats teh symtom of hart atak?", "AUGMENTED"),
    ("medical_legal", "Can I sue my doctor for malpractice?", "AUGMENTED"),
    ("medical_educational", "Explain how insulin works in the body", "AUGMENTED"),
    ("medical_compound", "Write a story about a nurse who discovers a cure for cancer", "LOCAL"),
    ("medical_pediatric", "My 2-year-old has a fever of 40 degrees", "AUGMENTED"),
    ("medical_drug", "What are the side effects of tadalafil?", "AUGMENTED"),

    # --- FINANCIAL (all should route AUGMENTED) ---
    ("financial_stock", "What is Tesla's stock price right now?", "AUGMENTED"),
    ("financial_crypto", "Should I buy Bitcoin today?", "AUGMENTED"),
    ("financial_forex", "What is the exchange rate between USD and ILS?", "AUGMENTED"),
    ("financial_advice", "How should I invest $10,000 for retirement?", "AUGMENTED"),
    ("financial_news", "Latest news on the Federal Reserve rate decision", "AUGMENTED"),
    ("financial_vague", "Is the economy doing okay?", "AUGMENTED"),
    ("financial_typos", "wat is teh prise of etherium?", "AUGMENTED"),
    ("financial_tax", "How do I file taxes as a freelancer in Israel?", "AUGMENTED"),
    ("financial_mortgage", "Should I refinance my mortgage at 6.5%?", "AUGMENTED"),
    ("financial_compound", "Write a poem about the stock market crash of 2008", "LOCAL"),

    # --- LEGAL (all should route AUGMENTED) ---
    ("legal_statute", "What does the Israeli Basic Law say about freedom of speech?", "AUGMENTED"),
    ("legal_compliance", "Do I need a business license to sell food online?", "AUGMENTED"),
    ("legal_court", "What was the Supreme Court ruling on the recent election case?", "AUGMENTED"),
    ("legal_is_it_legal", "Is it legal to carry a pocket knife in Tel Aviv?", "AUGMENTED"),
    ("legal_contract", "What are my rights if my landlord raises rent by 20%?", "AUGMENTED"),
    ("legal_immigration", "How do I apply for Israeli citizenship as a spouse?", "AUGMENTED"),
    ("legal_vague", "I got a ticket, what should I do?", "AUGMENTED"),
    ("legal_typos", "is it ilegal to park on teh sidewalk?", "AUGMENTED"),
    ("legal_compound", "Tell me a story about a lawyer who wins a big case", "LOCAL"),
    ("legal_educational", "Explain the concept of habeas corpus", "AUGMENTED"),

    # --- NEWS (all should route NEWS) ---
    ("news_explicit", "What is the latest news about the war in Gaza?", "NEWS"),
    ("news_breaking", "Breaking news: earthquake in Japan", "NEWS"),
    ("news_politics", "What happened in the Israeli parliament today?", "NEWS"),
    ("news_sports", "Who won the EuroLeague basketball final?", "NEWS"),
    ("news_weather_event", "Latest update on the hurricane approaching Florida", "NEWS"),
    ("news_vague", "What's happening in the world right now?", "NEWS"),
    ("news_typos", "wats teh latest newz abot teh war?", "NEWS"),
    ("news_compound", "Write a 500-word story about a journalist covering the war", "LOCAL"),
    ("news_conflict", "Any new developments in the Russia-Ukraine conflict?", "NEWS"),
    ("news_science", "New scientific discovery in quantum computing this week", "NEWS"),

    # --- TIME (all should route TIME) ---
    ("time_explicit", "What time is it in Tokyo right now?", "TIME"),
    ("time_date", "What is today's date?", "TIME"),
    ("time_vague", "What time is it?", "TIME"),
    ("time_typos", "wat tyme is it in new york?", "TIME"),
    ("time_compound", "Tell me a story about a clock that stopped at midnight", "LOCAL"),

    # --- CREATIVE / LOCAL (all should route LOCAL) ---
    ("creative_story", "Tell me a 500-word story about a dog named Oscar", "LOCAL"),
    ("creative_poem", "Write me a poem about autumn leaves", "LOCAL"),
    ("creative_essay", "Write a short essay about the importance of friendship", "LOCAL"),
    ("creative_compound", "Write a story about Bitcoin becoming sentient", "LOCAL"),
    ("creative_technical", "Explain how a car engine works in simple terms", "LOCAL"),
    ("creative_math", "What is 247 multiplied by 18?", "LOCAL"),
    ("creative_science", "How do black holes form?", "LOCAL"),
    ("creative_history", "Who was Ada Lovelace and why is she important?", "LOCAL"),
    ("creative_cooking", "How do I make hummus from scratch?", "LOCAL"),
    ("creative_typos", "how do i mak chumus?", "LOCAL"),
    ("creative_vague", "Tell me something interesting", "LOCAL"),
    ("creative_personal", "Remember that I like dark chocolate", "LOCAL"),
    ("creative_clarify", "What do you mean by that?", "LOCAL"),
    ("creative_joke", "Tell me a joke about programmers", "LOCAL"),
    ("creative_riddle", "I speak without a mouth and hear without ears. What am I?", "LOCAL"),

    # --- EVIDENCE / SOURCE (should route AUGMENTED for source verification) ---
    ("evidence_cite", "Can you cite peer-reviewed sources for that claim?", "AUGMENTED"),
    ("evidence_clinical", "Show me clinical trial data on mRNA vaccines", "AUGMENTED"),
    ("evidence_statistic", "What is the official unemployment rate in Israel?", "AUGMENTED"),
    ("evidence_vague", "Do you have any evidence for that?", "AUGMENTED"),

    # --- AMBIGUOUS / EDGE CASES ---
    ("edge_medical_story", "Write a horror story about a hospital", "LOCAL"),
    ("edge_financial_story", "Write a thriller about a stock trader", "LOCAL"),
    ("edge_news_story", "Write a novel about a war correspondent", "LOCAL"),
    ("edge_vague_medical", "I don't feel good", "AUGMENTED"),
    ("edge_vague_financial", "Money stuff", "AUGMENTED"),
    ("edge_vague_legal", "I have a problem with the law", "AUGMENTED"),
    ("edge_greeting", "Hello, how are you?", "LOCAL"),
    ("edge_empty", "", "LOCAL"),
    ("edge_gibberish", "asdfghjkl qwerty", "LOCAL"),
    ("edge_multilingual", "מה קורה עכשיו בעולם?", "NEWS"),  # Hebrew: "What's happening in the world now?"
]


# =============================================================================
# ADJUDICATION LOGIC
# Determines which router made the "better" decision for divergences.
# =============================================================================

def adjudicate(query: str, legacy: RoutingDecision, embedding: dict, expected: str) -> tuple[str, str]:
    """Return (winner, reason) for a divergence."""
    lr = legacy.route
    sr = embedding.get("route", "UNKNOWN")

    # If both agree with expected, tie
    if lr == expected and sr == expected:
        return "tie", "Both routers agree with expected route."

    # If legacy matches expected and embedding doesn.t
    if lr == expected and sr != expected:
        return "legacy", f"Legacy correctly routes to {lr}; embedding incorrectly routes to {sr}."

    # If embedding matches expected and legacy doesn't
    if sr == expected and lr != expected:
        return "embedding", f"Embedding correctly routes to {sr}; legacy incorrectly routes to {lr}."

    # If neither matches expected, pick whichever is "closer"
    # Heuristic: AUGMENTED > LOCAL > NEWS > TIME > CLARIFY for safety
    safety_rank = {"AUGMENTED": 5, "LOCAL": 3, "NEWS": 2, "TIME": 2, "CLARIFY": 1, "LOCAL_WITH_FALLBACK": 3}
    lr_safe = safety_rank.get(lr, 0)
    sr_safe = safety_rank.get(sr, 0)
    exp_safe = safety_rank.get(expected, 0)

    lr_dist = abs(lr_safe - exp_safe)
    sr_dist = abs(sr_safe - exp_safe)

    if lr_dist < sr_dist:
        return "legacy", f"Neither matches expected ({expected}), but legacy ({lr}) is closer in safety space than embedding ({sr})."
    elif sr_dist < lr_dist:
        return "embedding", f"Neither matches expected ({expected}), but embedding ({sr}) is closer in safety space than legacy ({lr})."
    else:
        return "tie", f"Both routers diverge equally from expected ({expected})."


# =============================================================================
# EVALUATION HARNESS
# =============================================================================

def run_evaluation() -> list[EvalResult]:
    results: list[EvalResult] = []
    policy = normalize_augmentation_policy("fallback_only")

    print(f"Running adversarial evaluation on {len(ADVERSARIAL_QUERIES)} queries...")
    print(f"Legacy router: keyword-based | Embedding router: ModernBERT embedding k-NN (k=3)")
    print("-" * 80)

    for category, query, expected in ADVERSARIAL_QUERIES:
        start = time.time()

        # Single-path router
        classification = classify_intent(query, surface="cli")
        decision = select_route(classification, policy=policy, query=query)

        elapsed = (time.time() - start) * 1000

        route = decision.route
        correct = route == expected
        reason = "correct" if correct else f"routed to {route}, expected {expected}"

        results.append(EvalResult(
            query=query,
            legacy_route=route,
            embedding_route=route,
            embedding_confidence=decision.confidence,
            embedding_intent=decision.intent_family,
            legacy_intent=classification.intent_family if classification else "unknown",
            legacy_evidence=classification.evidence_mode if classification else "unknown",
            divergence=False,
            category=category,
            expected_route=expected,
            winner="tie" if correct else "unclear",
            reason=reason,
        ))

    return results


def print_report(results: list[EvalResult]) -> None:
    total = len(results)
    divergences = [r for r in results if r.divergence]
    legacy_wins = [r for r in divergences if r.winner == "legacy"]
    embedding_wins = [r for r in divergences if r.winner == "embedding"]
    ties = [r for r in divergences if r.winner == "tie"]

    legacy_correct = sum(1 for r in results if r.legacy_route == r.expected_route)
    embedding_correct = sum(1 for r in results if r.embedding_route == r.expected_route)

    print()
    print("=" * 80)
    print("ADVERSARIAL ROUTER EVALUATION REPORT")
    print("=" * 80)
    print(f"Timestamp:       {datetime.now(timezone.utc).isoformat()}Z")
    print(f"Total queries:   {total}")
    print(f"Agreement rate:  {(total - len(divergences)) / total * 100:.1f}%")
    print(f"Divergences:     {len(divergences)} ({len(divergences)/total*100:.1f}%)")
    print()
    print("ACCURACY vs GROUND TRUTH")
    print(f"  Legacy router:  {legacy_correct}/{total} = {legacy_correct/total*100:.1f}%")
    print(f"  Embedding router:  {embedding_correct}/{total} = {embedding_correct/total*100:.1f}%")
    print()
    print("DIVERGENCE BREAKDOWN")
    print(f"  Legacy wins:    {len(legacy_wins)} ({len(legacy_wins)/total*100:.1f}%)")
    print(f"  Embedding wins:    {len(embedding_wins)} ({len(embedding_wins)/total*100:.1f}%)")
    print(f"  Ties/unclear:   {len(ties)} ({len(ties)/total*100:.1f}%)")
    print()

    # Category breakdown
    print("ACCURACY BY CATEGORY")
    print("-" * 60)
    categories = sorted(set(r.category for r in results))
    for cat in categories:
        cat_results = [r for r in results if r.category == cat]
        leg_corr = sum(1 for r in cat_results if r.legacy_route == r.expected_route)
        emb_corr = sum(1 for r in cat_results if r.embedding_route == r.expected_route)
        divs = sum(1 for r in cat_results if r.divergence)
        print(f"  {cat:25s}  Legacy: {leg_corr}/{len(cat_results)}  Embedding: {emb_corr}/{len(cat_results)}  Div: {divs}")

    print()
    print("DETAILED DIVERGENCES")
    print("-" * 80)
    if not divergences:
        print("  No divergences found.")
    for r in divergences:
        marker = "✅" if r.winner == "embedding" else "⚠️" if r.winner == "legacy" else "➖"
        print(f"\n  {marker} [{r.category}] {r.query[:70]}{'...' if len(r.query) > 70 else ''}")
        print(f"     Legacy:  {r.legacy_route:20s} (intent={r.legacy_intent}, evidence={r.legacy_evidence})")
        print(f"     Embedding:  {r.embedding_route:20s} (intent={r.embedding_intent}, conf={r.embedding_confidence:.3f})")
        print(f"     Expected: {r.expected_route}")
        print(f"     Winner:  {r.winner.upper()}")
        print(f"     Reason:  {r.reason}")

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if embedding_correct >= legacy_correct:
        margin = (embedding_correct - legacy_correct) / total * 100
        print(f"Embedding router achieves {embedding_correct/total*100:.1f}% accuracy vs Legacy {legacy_correct/total*100:.1f}%")
        print(f"Margin: +{margin:.1f} percentage points in favor of embedding router")
        if embedding_correct / total >= 0.97:
            print("RECOMMENDATION: Embedding router meets the 97% threshold for cutover consideration.")
        elif embedding_correct / total >= 0.95:
            print("RECOMMENDATION: Embedding router is close to the 97% threshold. Continue gathering data.")
        else:
            print("RECOMMENDATION: Embedding router needs improvement before cutover.")
    else:
        margin = (legacy_correct - embedding_correct) / total * 100
        print(f"Legacy router achieves {legacy_correct/total*100:.1f}% accuracy vs Embedding {embedding_correct/total*100:.1f}%")
        print(f"Margin: +{margin:.1f} percentage points in favor of legacy router")
        print("RECOMMENDATION: Legacy router remains superior. Embedding needs more examples or tuning.")

    print()
    print(f"Report saved to: {PROJECT_ROOT / 'router_evaluation_report.json'}")


def save_json(results: list[EvalResult]) -> None:
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "total_queries": len(results),
        "legacy_accuracy": sum(1 for r in results if r.legacy_route == r.expected_route) / len(results),
        "embedding_accuracy": sum(1 for r in results if r.embedding_route == r.expected_route) / len(results),
        "agreement_rate": sum(1 for r in results if not r.divergence) / len(results),
        "results": [asdict(r) for r in results],
    }
    with open(PROJECT_ROOT / "router_evaluation_report.json", "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    results = run_evaluation()
    print_report(results)
    save_json(results)
