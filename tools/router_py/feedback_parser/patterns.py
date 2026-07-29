#!/usr/bin/env python3
"""Regex patterns and low-level pattern-matching helpers for feedback parsing."""

from __future__ import annotations

import re
from typing import Optional

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
    # "the correct routing is LOCAL"
    r"correct\s+routing\s+(?:is|was)\s+" + ROUTE_NAMES,
    # "the correct answer is LOCAL"
    r"correct\s+answer\s+(?:is|was)\s+" + ROUTE_NAMES,
    # "it is LOCAL" / "it's LOCAL" (standalone correction)
    r"(?:it['\u2019]?s|it\s+is)\s+" + ROUTE_NAMES + r"\b",
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
    # Standalone "Incorrect" at start of utterance (e.g. "Incorrect, my dog is Oscar")
    r"^incorrect\b",
    r"^wrong\b",
    r"^nope\b",
    r"^not\s+right\b",
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

# Patterns for inferring correct route from failed responses
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

TIME_FAILURE_PATTERNS = [
    "could not determine timezone",
    "couldn't find the time",
    "unknown location",
    "sorry, i couldn't find the time",
]

NEWS_FAILURE_PATTERNS = [
    "unable to fetch live news",
    "news provider returned no articles",
    "failed to fetch news from all sources",
    "no articles found",
    "no rss feeds configured",
]

WEATHER_FAILURE_PATTERNS = [
    "could not fetch weather",
    "please specify a city",
    "could not parse weather data",
    "no location found",
]

_MEDICAL_KEYWORDS = [
    "symptom",
    "symptoms",
    "pain",
    "fever",
    "chest",
    "headache",
    "doctor",
    "medical",
    "treatment",
    "diagnosis",
    "prescription",
    "medication",
    "dosage",
    "side effect",
    "disease",
    "condition",
    "blood pressure",
    "diabetes",
    "cancer",
    "flu",
    "infection",
    "virus",
    "vaccine",
    "pregnancy",
    "mental health",
    "therapy",
    "surgery",
    "operation",
    "hospital",
    "medicine",
    "patient",
]

_FINANCIAL_KEYWORDS = [
    "stock",
    "price",
    "bitcoin",
    "ethereum",
    "crypto",
    "invest",
    "investing",
    "money",
    "market",
    "financial",
    "tax",
    "taxes",
    "mortgage",
    "loan",
    "credit",
    "debt",
    "budget",
    "salary",
    "income",
    "expense",
    "valuation",
    "worth",
    "insurance",
    "premium",
    "dividend",
    "portfolio",
    "retirement",
    "pension",
]

_LEGAL_KEYWORDS = [
    "legal",
    "law",
    "lawyer",
    "attorney",
    "court",
    "sue",
    "suing",
    "contract",
    "license",
    "illegal",
    "lawsuit",
    "settlement",
    "damages",
    "injunction",
    "felony",
    "misdemeanor",
    "warrant",
]

# Keywords used to detect semantic misroutes (query routed to live-data
# route but lacks any keywords for that route)
_TIME_KEYWORDS = [
    "time",
    "date",
    "day",
    "clock",
    "hour",
    "minute",
    "schedule",
    "timezone",
    "gmt",
    "pst",
    "est",
    "cet",
    "utc",
    "o'clock",
    "am",
    "pm",
]

_NEWS_KEYWORDS = [
    "news",
    "headlines",
    "breaking",
    "current events",
    "update",
    "latest",
    "report",
    "article",
    "happening",
    "developments",
    "trending",
]

_WEATHER_KEYWORDS = [
    "weather",
    "forecast",
    "temperature",
    "rain",
    "snow",
    "sunny",
    "cloudy",
    "windy",
    "storm",
    "humidity",
    "precipitation",
    "hot",
    "cold",
    "warm",
    "freezing",
    "chilly",
    "outside",
    "umbrella",
    "jacket",
    "coat",
]


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


def _has_pattern(text: str, patterns: list[str]) -> bool:
    """Check if text contains any of the patterns (case-insensitive)."""
    text_lower = text.lower()
    return any(p in text_lower for p in patterns)
