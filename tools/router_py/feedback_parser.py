#!/usr/bin/env python3
"""Natural-language feedback parser for Local Lucy.

Detects when the user is giving feedback about a prior response
(rather than asking a new question). Extracts corrections and
prepares them for the background learner.

Patterns detected:
  - Route corrections:  "that should have been LOCAL", "wrong route, it was NEWS"
  - Answer quality:     "that was wrong", "bad answer", "incorrect"
  - Positive feedback:  "that was right", "good answer", "perfect"
  - Retractions:        "forget that", "don't answer that", "ignore that"

Usage:
    from feedback_parser import parse_feedback, FeedbackType
    result = parse_feedback("that was wrong, it should have been LOCAL")
    if result:
        print(result.type, result.corrected_route, result.target_query)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum, auto
from pathlib import Path
from typing import Optional

try:
    from .feedback_buffer import get_buffer
except ImportError:
    from feedback_buffer import get_buffer

# Where to write user feedback for background_learner.py
RUNTIME_NS = Path(
    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
)
# feedback_parser.py lives in tools/router_py/ → go up two levels to project root → models/router
ROUTER_DIR = Path(__file__).resolve().parent.parent.parent / "models" / "router"
FEEDBACK_PATH = ROUTER_DIR / "user_feedback.jsonl"


class FeedbackType(Enum):
    ROUTE_CORRECTION = auto()
    ANSWER_NEGATIVE = auto()
    ANSWER_POSITIVE = auto()
    RETRACTION = auto()
    UNKNOWN = auto()


# ---------------------------------------------------------------------------
# Pattern definitions — ordered by specificity (most specific first)
# ---------------------------------------------------------------------------

# Route name extraction — matches "LOCAL", "NEWS", "TIME", "WEATHER", "AUGMENTED"
ROUTE_NAMES = r"\b(LOCAL|NEWS|TIME|WEATHER|AUGMENTED|CLARIFY|FULL|EVIDENCE)\b"

# Route correction patterns — user tells us the correct route
ROUTE_CORRECTION_PATTERNS = [
    # "it should have been LOCAL"
    r"(?:it\s+)?should\s+(?:have\s+)?been\s+" + ROUTE_NAMES,
    # "should be LOCAL"
    r"should\s+be\s+" + ROUTE_NAMES,
    # "route should be LOCAL"
    r"route\s+(?:should\s+be|was)\s+" + ROUTE_NAMES,
    # "wrong route, it was LOCAL"
    r"wrong\s+route.*?(?:was|is)\s+" + ROUTE_NAMES,
    # "that was LOCAL, not NEWS"
    r"that\s+was\s+" + ROUTE_NAMES + r"\s*,?\s*not\s+" + ROUTE_NAMES,
    # "not LOCAL, it should be NEWS"
    r"not\s+" + ROUTE_NAMES + r".*?should\s+be\s+" + ROUTE_NAMES,
    # "re-route to LOCAL"
    r"re[-\s]?route\s+(?:to|as)\s+" + ROUTE_NAMES,
]

# Answer-quality negative patterns
ANSWER_NEGATIVE_PATTERNS = [
    r"\bthat\s+was\s+wrong\b",
    r"\bwrong\s+answer\b",
    r"\bbad\s+answer\b",
    r"\bincorrect\s+answer\b",
    r"\bthat['’]?s?\s+incorrect\b",
    r"\bthat['’]?s?\s+wrong\b",
    r"\bnot\s+right\b",
    r"\bthat['’]?s?\s+not\s+right\b",
    r"\bthat['’]?s?\s+bad\b",
    r"\bthat['’]?s?\s+terrible\b",
    r"\bthat['’]?s?\s+awful\b",
    r"\bthat['’]?s?\s+nonsense\b",
    r"\bthat\s+made\s+no\s+sense\b",
    r"\bthat['’]?s?\s+not\s+what\s+I\s+asked\b",
    r"\byou\s+(?:didn['’]t\s+answer|misunderstood)\b",
]

# Answer-quality positive patterns
ANSWER_POSITIVE_PATTERNS = [
    r"\bthat\s+was\s+right\b",
    r"\bthat['’]?s?\s+right\b",
    r"\bthat['’]?s?\s+correct\b",
    r"\bgood\s+answer\b",
    r"\bgreat\s+answer\b",
    r"\bperfect\b",
    r"\bexactly\b",
    r"\bthat['’]?s?\s+what\s+I\s+wanted\b",
    r"\bthank\s*you\s*,?\s*that['’]?s?\s+helpful\b",
    r"\bnice\s+job\b",
    r"\bwell\s+done\b",
]

# Retraction patterns
RETRACTION_PATTERNS = [
    r"\bforget\s+that\b",
    r"\bdon['’]?t\s+answer\s+that\b",
    r"\bignore\s+that\b",
    r"\bnever\s+mind\b",
    r"\bnevermind\b",
    r"\bscratch\s+that\b",
    r"\bcancel\s+that\b",
]


@dataclass
class FeedbackResult:
    """Result of parsing a potential feedback utterance."""

    feedback_type: FeedbackType
    target_query: str
    original_route: str
    corrected_route: Optional[str] = None
    confidence: float = 1.0
    raw_text: str = ""

    @property
    def is_correction(self) -> bool:
        return self.feedback_type in (
            FeedbackType.ROUTE_CORRECTION,
            FeedbackType.ANSWER_NEGATIVE,
        )

    @property
    def is_positive(self) -> bool:
        return self.feedback_type == FeedbackType.ANSWER_POSITIVE

    @property
    def is_retraction(self) -> bool:
        return self.feedback_type == FeedbackType.RETRACTION


def _extract_route(text: str) -> Optional[str]:
    """Extract the first route name mentioned in text."""
    match = re.search(ROUTE_NAMES, text, re.IGNORECASE)
    return match.group(1).upper() if match else None


def _matches_any(text: str, patterns: list[str]) -> bool:
    """Check if text matches any of the regex patterns."""
    text_lower = text.lower()
    for pat in patterns:
        if re.search(pat, text_lower, re.IGNORECASE):
            return True
    return False


def parse_feedback(text: str) -> Optional[FeedbackResult]:
    """Parse a user utterance to detect feedback about a prior exchange.

    Returns None if the text does not appear to be feedback.
    """
    text_stripped = text.strip()
    if len(text_stripped) < 3:
        return None

    q_lower = text_stripped.lower()
    buf = get_buffer()
    last_ex = buf.last()

    # No prior exchange to attribute feedback to
    if last_ex is None:
        return None

    # --- 1. Route correction (most specific) ---
    if _matches_any(q_lower, ROUTE_CORRECTION_PATTERNS):
        corrected = _extract_route(text_stripped)
        # If they say "not LOCAL" without specifying what it IS, try to infer
        if corrected is None:
            # e.g. "that was wrong, not LOCAL" — we know original was LOCAL
            # but we don't know what it should be; fall through to generic negative
            pass
        else:
            return FeedbackResult(
                feedback_type=FeedbackType.ROUTE_CORRECTION,
                target_query=last_ex.query,
                original_route=last_ex.route,
                corrected_route=corrected,
                confidence=1.0,
                raw_text=text_stripped,
            )

    # --- 2. Retraction ---
    if _matches_any(q_lower, RETRACTION_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.RETRACTION,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=1.0,
            raw_text=text_stripped,
        )

    # --- 3. Negative answer quality ---
    if _matches_any(q_lower, ANSWER_NEGATIVE_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.ANSWER_NEGATIVE,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=0.8,
            raw_text=text_stripped,
        )

    # --- 4. Positive answer quality ---
    if _matches_any(q_lower, ANSWER_POSITIVE_PATTERNS):
        return FeedbackResult(
            feedback_type=FeedbackType.ANSWER_POSITIVE,
            target_query=last_ex.query,
            original_route=last_ex.route,
            confidence=0.8,
            raw_text=text_stripped,
        )

    return None


# Patterns for inferring correct route from failed responses
_AUGMENTED_FAILURE_PATTERNS = [
    "i don't know", "i don't have", "i'm not sure",
    "i don't have access to", "i cannot provide",
    "i don't have real-time", "i don't have current",
    "i don't have the ability", "i don't have information",
    "i don't have up-to-date", "error", "failed to",
    "unable to", "could not", "connection refused",
    "timeout", "503", "502", "404",
]

_LOCAL_MEDICAL_DISCLAIMER_PATTERNS = [
    "i'm not a medical professional", "i'm not a doctor",
    "consult a doctor", "seek medical advice",
    "this is not medical advice", "not a substitute for professional medical",
    "i'm not qualified to give medical", "please consult a healthcare",
    "i cannot provide medical",
]

_LOCAL_FINANCIAL_DISCLAIMER_PATTERNS = [
    "i'm not a financial advisor", "this is not financial advice",
    "consult a financial advisor", "not investment advice",
]

_LOCAL_LEGAL_DISCLAIMER_PATTERNS = [
    "i'm not a lawyer", "this is not legal advice",
    "consult an attorney", "seek legal counsel",
]

_MEDICAL_KEYWORDS = [
    "symptom", "symptoms", "pain", "fever", "chest", "headache",
    "doctor", "medical", "treatment", "diagnosis", "prescription",
    "medication", "dosage", "side effect", "disease", "condition",
    "blood pressure", "diabetes", "cancer", "flu", "infection",
    "virus", "vaccine", "pregnancy", "mental health", "therapy",
    "surgery", "operation", "hospital", "medicine", "patient",
]

_FINANCIAL_KEYWORDS = [
    "stock", "price", "bitcoin", "ethereum", "crypto", "invest",
    "investing", "money", "market", "financial", "tax", "taxes",
    "mortgage", "loan", "credit", "debt", "budget", "salary",
    "income", "expense", "valuation", "worth", "insurance",
    "premium", "dividend", "portfolio", "retirement", "pension",
]

_LEGAL_KEYWORDS = [
    "legal", "law", "lawyer", "attorney", "court", "sue", "suing",
    "contract", "license", "illegal", "lawsuit", "settlement",
    "damages", "injunction", "felony", "misdemeanor", "warrant",
]

_TIME_FAILURE_PATTERNS = [
    "could not determine timezone", "couldn't find the time",
    "unknown location", "sorry, i couldn't find the time",
]

_NEWS_FAILURE_PATTERNS = [
    "unable to fetch live news", "news provider returned no articles",
    "failed to fetch news from all sources", "no articles found",
    "no rss feeds configured",
]

_WEATHER_FAILURE_PATTERNS = [
    "could not fetch weather", "please specify a city",
    "could not parse weather data", "no location found",
]


def _has_pattern(text: str, patterns: list[str]) -> bool:
    """Check if text contains any of the patterns (case-insensitive)."""
    text_lower = text.lower()
    return any(p in text_lower for p in patterns)


def _infer_corrected_route(result: FeedbackResult) -> Optional[str]:
    """Infer the correct route from the last exchange when user says 'wrong' generically.

    Returns a route name (e.g. 'LOCAL', 'AUGMENTED') or None if inference is unsafe.
    """
    buf = get_buffer()
    last_ex = buf.last()
    if last_ex is None:
        return None

    original_route = (last_ex.route or "").upper()
    query = (last_ex.query or "").strip()
    response = (last_ex.response_text or "").strip()
    response_lower = response.lower()

    if not query or not response:
        return None

    # Safety: don't infer for creative writing (LOCAL is correct)
    if last_ex.intent_family in ("local_answer", "creative_writing"):
        # Only infer if there's a clear provider failure
        pass  # fall through to failure checks

    # Safety: low-confidence original route
    if last_ex.confidence < 0.5:
        return None

    # 1. AUGMENTED → LOCAL: provider failure, admission of ignorance, or empty
    if original_route == "AUGMENTED":
        if _has_pattern(response, _AUGMENTED_FAILURE_PATTERNS):
            return "LOCAL"
        if len(response) < 20:
            return "LOCAL"

    # 2. LOCAL → AUGMENTED: medical/financial/legal disclaimers
    if original_route == "LOCAL":
        query_lower = query.lower()
        if any(kw in query_lower for kw in _MEDICAL_KEYWORDS) and _has_pattern(response, _LOCAL_MEDICAL_DISCLAIMER_PATTERNS):
            return "AUGMENTED"
        if any(kw in query_lower for kw in _FINANCIAL_KEYWORDS) and _has_pattern(response, _LOCAL_FINANCIAL_DISCLAIMER_PATTERNS):
            return "AUGMENTED"
        if any(kw in query_lower for kw in _LEGAL_KEYWORDS) and _has_pattern(response, _LOCAL_LEGAL_DISCLAIMER_PATTERNS):
            return "AUGMENTED"

    # 3. TIME → LOCAL: timezone API failed
    if original_route == "TIME":
        if _has_pattern(response, _TIME_FAILURE_PATTERNS):
            return "LOCAL"

    # 4. NEWS → LOCAL: news fetch failed
    if original_route == "NEWS":
        if _has_pattern(response, _NEWS_FAILURE_PATTERNS):
            return "LOCAL"

    # 5. WEATHER → LOCAL: weather fetch failed
    if original_route == "WEATHER":
        if _has_pattern(response, _WEATHER_FAILURE_PATTERNS):
            return "LOCAL"

    return None


def log_user_feedback(result: FeedbackResult) -> bool:
    """Write a feedback result to user_feedback.jsonl for background_learner.

    Returns True if written successfully.
    """
    try:
        # Determine the corrected route
        if result.corrected_route:
            correct_route = result.corrected_route
        elif result.feedback_type == FeedbackType.ANSWER_NEGATIVE:
            # Try to infer the correct route from exchange quality signals
            inferred = _infer_corrected_route(result)
            if inferred:
                correct_route = inferred
                result.corrected_route = inferred
                result.confidence = min(result.confidence, 0.7)
            else:
                return False
        elif result.feedback_type == FeedbackType.ANSWER_POSITIVE:
            # Confirmation: strengthen the existing route
            correct_route = result.original_route
        elif result.feedback_type == FeedbackType.RETRACTION:
            # Remove from memory if it was stored there
            _retract_from_memory(result.target_query)
            return True
        else:
            return False

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": result.target_query,
            "correct_route": correct_route,
            "feedback_type": result.feedback_type.name.lower(),
            "original_route": result.original_route,
            "confidence": result.confidence,
            "raw_feedback": result.raw_text,
        }

        FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        # Also write to runtime log for visibility
        log_path = RUNTIME_NS / "logs" / "feedback_log.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

        return True
    except Exception:
        return False


def _retract_from_memory(query: str) -> None:
    """Remove a query from session memory if present."""
    try:
        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
        if not mem_file:
            return
        mem_path = Path(mem_file).expanduser()
        if not mem_path.exists():
            return
        content = mem_path.read_text(encoding="utf-8")
        blocks = [b.strip() for b in content.split("\n\n") if b.strip()]
        filtered = []
        for block in blocks:
            # Simple heuristic: if the block starts with this query, skip it
            if not block.lower().startswith(f"user: {query.lower()}"):
                filtered.append(block)
        if len(filtered) != len(blocks):
            mem_path.write_text("\n\n".join(filtered) + "\n\n", encoding="utf-8")
    except Exception:
        pass


def trigger_background_learning() -> bool:
    """Trigger background learner to rebuild embeddings from new feedback.

    Returns True if learning was triggered.
    """
    try:
        import sys as _sys
        router_dir = str(Path(__file__).parent.parent / "models" / "router")
        inserted = False
        if router_dir not in _sys.path:
            _sys.path.insert(0, router_dir)
            inserted = True

        from background_learner import maybe_auto_learn
        triggered = maybe_auto_learn(min_entries=1)

        if inserted and router_dir in _sys.path:
            _sys.path.remove(router_dir)

        return triggered
    except Exception as e:
        print(f"[Background learning trigger failed] {e}")
        return False


def apply_feedback(
    text: str,
    confirmation_callback: Optional[callable] = None,
) -> Optional[FeedbackResult]:
    """High-level entry: parse feedback, log it, trigger learning, optionally confirm.

    Args:
        text: The raw user utterance.
        confirmation_callback: Optional callable(text) for TTS confirmation.

    Returns:
        FeedbackResult if feedback was detected and handled, else None.
    """
    result = parse_feedback(text)
    if result is None:
        return None

    # Log the feedback
    logged = log_user_feedback(result)

    # Trigger background learning
    triggered = trigger_background_learning()

    # Confirmation message
    if result.feedback_type == FeedbackType.ROUTE_CORRECTION:
        msg = f"Got it. I'll remember that '{result.target_query[:40]}...' should route to {result.corrected_route}."
    elif result.feedback_type == FeedbackType.ANSWER_NEGATIVE:
        msg = "Noted. I'll work on improving that answer."
    elif result.feedback_type == FeedbackType.ANSWER_POSITIVE:
        msg = "Thanks for the feedback!"
    elif result.feedback_type == FeedbackType.RETRACTION:
        msg = "Okay, I've forgotten that."
    else:
        msg = "Noted."

    if confirmation_callback:
        confirmation_callback(msg)

    return result


if __name__ == "__main__":
    # Quick self-test — seed buffer with a prior exchange
    from feedback_buffer import get_buffer
    buf = get_buffer()
    buf.append("What is the weather in London?", "WEATHER", "ephemeral_query", "Sunny, 22C", 0.95)

    test_cases = [
        ("that was wrong, it should have been LOCAL", FeedbackType.ROUTE_CORRECTION),
        ("wrong route, that was NEWS", FeedbackType.ROUTE_CORRECTION),
        ("that was a bad answer", FeedbackType.ANSWER_NEGATIVE),
        ("perfect, thank you", FeedbackType.ANSWER_POSITIVE),
        ("forget that", FeedbackType.RETRACTION),
        ("what is the weather in London?", None),
    ]
    ok = 0
    for text, expected in test_cases:
        result = parse_feedback(text)
        detected = result.feedback_type if result else None
        status = "✅" if detected == expected else "❌"
        if detected == expected:
            ok += 1
        print(f"{status} {text!r:50s} → {detected}")
    print(f"\n{ok}/{len(test_cases)} tests passed")
