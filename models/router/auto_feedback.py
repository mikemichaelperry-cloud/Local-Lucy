#!/usr/bin/env python3
"""Auto-feedback from answer quality — detects obvious misroutes.

This module analyzes execution results to detect cases where the router
probably made the wrong decision. It catches the most obvious cases:

1. AUGMENTED answer that fails (provider error, empty response, "I don't know")
2. LOCAL answer to a medical/financial/legal query that contains a disclaimer

These auto-detected misroutes are written to a feedback file that
background_learner.py can ingest during index rebuild.

Usage:
    from auto_feedback import analyze_answer_quality, log_auto_feedback
    suggestion = analyze_answer_quality(query, route, response_text)
    if suggestion:
        log_auto_feedback(suggestion)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Feedback file path
ROUTER_DIR = Path(__file__).parent
AUTO_FEEDBACK_PATH = ROUTER_DIR / "auto_feedback.jsonl"

# Heuristic patterns
AUGMENTED_FAILURE_PATTERNS = [
    "i don't know",
    "i don't have",
    "i'm not sure",
    "i don't have access to",
    "i cannot provide",
    "i don't have real-time",
    "i don't have current",
    "i don't have the ability",
    "i don't have information",
    "i don't have up-to-date",
    "i don't have access to real-time",
    "error",
    "failed to",
    "unable to",
    "could not",
    "connection refused",
    "timeout",
    "503",
    "502",
    "404",
]

LOCAL_MEDICAL_DISCLAIMER_PATTERNS = [
    "i'm not a medical professional",
    "i'm not a doctor",
    "consult a doctor",
    "seek medical advice",
    "this is not medical advice",
    "not a substitute for professional medical",
    "i'm not qualified to give medical",
    "please consult a healthcare",
    "i cannot provide medical",
]

LOCAL_FINANCIAL_DISCLAIMER_PATTERNS = [
    "i'm not a financial advisor",
    "this is not financial advice",
    "consult a financial advisor",
    "not investment advice",
]

LOCAL_LEGAL_DISCLAIMER_PATTERNS = [
    "i'm not a lawyer",
    "this is not legal advice",
    "consult an attorney",
    "seek legal counsel",
]


def _has_pattern(text: str, patterns: list[str]) -> bool:
    """Check if text contains any of the patterns (case-insensitive)."""
    text_lower = text.lower()
    return any(p in text_lower for p in patterns)


def analyze_answer_quality(
    query: str,
    route: str,
    response_text: str,
    error_message: str = "",
) -> dict[str, Any] | None:
    """Analyze answer quality and return auto-feedback if misroute detected.

    Returns None if no misroute is detected.

    Args:
        query: The original user query
        route: The route that was used (LOCAL, AUGMENTED, NEWS, TIME)
        response_text: The answer text returned to the user
        error_message: Any error message from execution

    Returns:
        Feedback dict with query, suggested_route, reason, confidence,
        or None if no misroute detected.
    """
    if not query or not query.strip():
        return None

    response_lower = (response_text or "").lower()
    error_lower = (error_message or "").lower()

    # Heuristic 1: AUGMENTED query got a failure response
    if route == "AUGMENTED":
        # Provider-level error
        if error_message and _has_pattern(error_message, [
            "error", "failed", "unable", "could not", "refused", "timeout",
            "503", "502", "404", "500", "connection",
        ]):
            return {
                "query": query,
                "suggested_route": "LOCAL",
                "reason": "augmented_provider_error",
                "confidence": 0.9,
                "details": f"Provider error: {error_message[:100]}",
            }

        # Answer contains "I don't know" or similar
        if _has_pattern(response_text, AUGMENTED_FAILURE_PATTERNS):
            return {
                "query": query,
                "suggested_route": "LOCAL",
                "reason": "augmented_answer_incomplete",
                "confidence": 0.7,
                "details": "AUGMENTED answer contained admission of ignorance",
            }

        # Empty or near-empty response
        if len(response_text.strip()) < 20:
            return {
                "query": query,
                "suggested_route": "LOCAL",
                "reason": "augmented_answer_empty",
                "confidence": 0.85,
                "details": f"AUGMENTED answer too short ({len(response_text.strip())} chars)",
            }

    # Heuristic 2: LOCAL answer to medical/financial/legal query contains disclaimer
    if route == "LOCAL":
        query_lower = query.lower()

        # Medical
        medical_keywords = ["symptom", "pain", "fever", "chest", "headache", "doctor", "medical", "treatment", "diagnosis", "prescription", "medication"]
        has_medical = any(kw in query_lower for kw in medical_keywords)
        if has_medical and _has_pattern(response_text, LOCAL_MEDICAL_DISCLAIMER_PATTERNS):
            return {
                "query": query,
                "suggested_route": "AUGMENTED",
                "reason": "local_had_medical_disclaimer",
                "confidence": 0.75,
                "details": "LOCAL medical answer contained medical disclaimer",
            }

        # Financial
        financial_keywords = ["stock", "price", "bitcoin", "invest", "money", "market", "financial", "tax", "mortgage", "loan"]
        has_financial = any(kw in query_lower for kw in financial_keywords)
        if has_financial and _has_pattern(response_text, LOCAL_FINANCIAL_DISCLAIMER_PATTERNS):
            return {
                "query": query,
                "suggested_route": "AUGMENTED",
                "reason": "local_had_financial_disclaimer",
                "confidence": 0.7,
                "details": "LOCAL financial answer contained financial disclaimer",
            }

        # Legal
        legal_keywords = ["legal", "law", "lawyer", "court", "sue", "contract", "license", "illegal"]
        has_legal = any(kw in query_lower for kw in legal_keywords)
        if has_legal and _has_pattern(response_text, LOCAL_LEGAL_DISCLAIMER_PATTERNS):
            return {
                "query": query,
                "suggested_route": "AUGMENTED",
                "reason": "local_had_legal_disclaimer",
                "confidence": 0.7,
                "details": "LOCAL legal answer contained legal disclaimer",
            }

        # Heuristic 3: LOCAL "I don't know" on factual questions
        # Philosophy: correct answer > locality. If local model admits ignorance,
        # we should have routed to augmented (evidence/tools) instead.
        factual_keywords = ["what is", "what are", "how to", "how do", "when did", "where is", "who is", "why does", "explain", "tell me about", "current", "today", "latest", "news", "price", "weather", "score"]
        has_factual = any(kw in query_lower for kw in factual_keywords)
        if has_factual and _has_pattern(response_text, [
            "i don't know", "i don't have", "i'm not sure", "i don't have information",
            "i don't have access", "i cannot provide", "i don't have real-time",
        ]):
            return {
                "query": query,
                "suggested_route": "AUGMENTED",
                "reason": "local_admitted_ignorance_factual",
                "confidence": 0.8,
                "details": "LOCAL model admitted ignorance on a factual query",
            }

        # Heuristic 4: LOCAL extremely short answer to factual question
        # Only flag near-empty responses (< 15 chars) as likely cop-outs.
        # Short but correct answers (e.g. math) should not be penalized.
        if has_factual and len(response_text.strip()) < 15:
            return {
                "query": query,
                "suggested_route": "AUGMENTED",
                "reason": "local_answer_too_short_factual",
                "confidence": 0.6,
                "details": f"LOCAL factual answer near-empty ({len(response_text.strip())} chars)",
            }

    return None


def log_auto_feedback(suggestion: dict[str, Any]) -> None:
    """Write auto-feedback entry to the auto-feedback log.

    Args:
        suggestion: Dict from analyze_answer_quality()
    """
    try:
        AUTO_FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "auto_feedback",
            "query": suggestion["query"],
            "correct_route": suggestion["suggested_route"],
            "reason": suggestion["reason"],
            "confidence": suggestion["confidence"],
            "details": suggestion.get("details", ""),
            "feedback_type": "auto_correction",
        }
        with open(AUTO_FEEDBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass  # Auto-feedback must never break execution


def load_auto_feedback(min_confidence: float = 0.6) -> list[dict]:
    """Load auto-feedback entries above confidence threshold.

    Args:
        min_confidence: Minimum confidence to include (0.0–1.0)

    Returns:
        List of feedback dicts
    """
    entries = []
    if not AUTO_FEEDBACK_PATH.exists():
        return entries

    with open(AUTO_FEEDBACK_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if entry.get("confidence", 0) >= min_confidence:
                    entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries


def clear_auto_feedback() -> None:
    """Clear the auto-feedback log after processing."""
    try:
        if AUTO_FEEDBACK_PATH.exists():
            processed_path = AUTO_FEEDBACK_PATH.with_suffix(".processed")
            os.replace(AUTO_FEEDBACK_PATH, processed_path)
    except Exception:
        pass


if __name__ == "__main__":
    # Self-test
    test_cases = [
        ("What is 2+2?", "LOCAL", "The answer is 4.", ""),
        ("My chest feels tight", "LOCAL", "I'm not a medical professional. Please consult a doctor.", ""),
        ("What is the stock price of Apple?", "AUGMENTED", "I don't have access to real-time stock prices.", ""),
        ("What is the capital of France?", "LOCAL", "Paris is the capital of France.", ""),
    ]

    for query, route, response, error in test_cases:
        result = analyze_answer_quality(query, route, response, error)
        if result:
            print(f"✗ {query[:40]:40s} → {route:12s} | suggest {result['suggested_route']:12s} | {result['reason']}")
        else:
            print(f"✓ {query[:40]:40s} → {route:12s} | OK")
