#!/usr/bin/env python3
"""Frozen routing precedence and shared signal vocabulary.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and precedence changes are out of
scope unless they fix a demonstrated bug.
"""

import re
from typing import Dict

ROUTING_PRECEDENCE_VERSION = "v1"
ROUTING_PRECEDENCE_LADDER = (
    "doc_source",
    "medical_high_stakes",
    "ambiguity",
    "temporal_live",
    "current_product",
    "conceptual_local",
)


TEMPORAL_SIGNAL_PATTERN = (
    r"\b(latest|most recent|today|recent|recently|right now|at the moment|now|currently|nowadays|"
    r"this week|this month|this year|as of|rn|up to date|update on|"
    r"won|happening|going on|just happened|breaking|developing|latest development|"
    r"current status|situation in|update on)\b"
)
RELATIVE_TIME_WINDOW_PATTERN = r"\b(?:in\s+the\s+)?(?:past|last)\s+(?:\d+\s+)?(?:day|days|week|weeks|month|months|year|years)\b"
CURRENT_TOPIC_PATTERN = (
    r"\b(news|events?|developments?|status|situation|conditions?|tensions?|deadline|deadlines|filing deadline|"
    r"price|prices|weather|temperature|schedule|availability|advisory|travel|stock market|market|inflation|"
    r"war|conflict|military action|ceasefire|talks?|hostilities|fighting|strikes?|offensive|standoff)\b"
)
CURRENT_PUBLIC_OFFICE_PATTERN = (
    r"\b(president|prime minister|chancellor|premier|mayor|governor|leader|head of state|head of government)\b"
)
NEWS_TERM_PATTERN = r"\b(news|headline|headlines|breaking|update|updates)\b"
CONFLICT_TERM_PATTERN = (
    r"\b(war|conflict|military action|ceasefire|talks?|hostilities|fighting|strikes?|offensive|tensions?|standoff)\b"
)
SOURCE_REQUEST_PATTERN = r"\b(source|sources|citation|citations|cite|verify|proof|evidence|url|link|wikipedia|wiki|http)\b"
MEDIA_RELIABILITY_TOPIC_PATTERN = (
    r"\b(bias|biased|unbiased|neutral|objective|balanced|fair|trustworthy|credible|reliable|factual|accuracy|propaganda|slant|partisan)\b"
)
MEDIA_PUBLICATION_PATTERN = (
    r"\b(bbc|fox news|reuters|cnn|guardian|new york times|nytimes|nyt|washington post|wall street journal|wsj|"
    r"al jazeera|abc news|nbc news|cbs news|news network|newspaper|publication|broadcaster|outlet)\b"
)
GEOPOLITICS_PATTERN = (
    r"\b(israel|israeli|gaza|hamas|hezbollah|iran|lebanon|ukraine|russia|syria|tehran|middle east|"
    r"idf|knesset|west bank|south china sea|taiwan|china|un|eu)\b"
)
ISRAEL_REGION_PATTERN = r"\b(israel|israeli|gaza|hamas|hezbollah|iran|lebanon|idf|knesset|west bank)\b"
# Time-of-day queries that need real-time data (e.g., "What time is it in London?")
# Matches: "what time is it", "what's the time", "current time in", "time in Paris"
# Excludes: "what time does", "what time is the meeting"
TIME_QUERY_PATTERN = (
    r"\b(what time|what's the time|what is the time|current time)\b" 
    r"|\btime\s+is\s+it\b"
    r"|\btime\s+in\s+[a-z]"  # "time in London", "time in Tokyo"
)


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text or "", flags=re.IGNORECASE) is not None


def is_probable_culinary_source_misrecognition(text: str) -> bool:
    if not _has_re(text, r"\bsource\b"):
        return False
    if _has_re(text, r"\b(sources|citation|citations|cite|verify|proof|evidence|url|link|wikipedia|wiki|http)\b"):
        return False
    if _has_re(text, r"\b(source code|primary source|data source|news source|open source)\b"):
        return False
    if _has_re(
        text,
        r"\b(recipe|recipes|cook|cooking|sauce|tomato|chicken|breast|breasts|ingredient|ingredients|garlic|onion|olive oil|oven|bake|roast|fry|pan[- ]?sear|kilogram|kilograms|kg)\b",
    ):
        return True
    return _has_re(text, r"\bbased source\b")


def is_electrical_current_usage(text: str) -> bool:
    return _has_re(text, r"\bcurrent\b") and _has_re(
        text,
        r"\b(voltage|resistor|capacitor|inductor|transistor|diode|circuit|ohm|ohm's|amps?|amperage|electronics?|electric|electrical)\b",
    )


def is_current_public_office_query(text: str) -> bool:
    if not _has_re(text, CURRENT_PUBLIC_OFFICE_PATTERN):
        return False
    if _has_re(text, r"\b(former|previous|past|historical|history|who was|used to be)\b"):
        return False
    return _has_re(text, r"\b(current|currently|right now|today|now)\b")


def has_temporal_signal(text: str) -> bool:
    if _has_re(text, TEMPORAL_SIGNAL_PATTERN) or _has_re(text, RELATIVE_TIME_WINDOW_PATTERN):
        return True
    if is_current_public_office_query(text):
        return True
    if _has_re(text, r"\bcurrent\b") and not is_electrical_current_usage(text):
        return _has_re(text, CURRENT_TOPIC_PATTERN)
    return False


def is_time_query(text: str) -> bool:
    """Detect time-of-day queries that need real-time data.
    
    Examples:
        - "What time is it in London?"
        - "What's the time in Tokyo?"
        - "Current time in New York"
        - "Time in California"
    
    Excludes:
        - "What time does the store open?"
        - "What time is the meeting?"
    """
    # First check if it matches the time query pattern
    if not _has_re(text, TIME_QUERY_PATTERN):
        return False
    
    # Exclude scheduling questions (what time + verb/noun)
    # "what time does" - scheduling question
    if _has_re(text, r"\bwhat time\s+(does|do|did|will|can|should|would)\b"):
        return False
    # "what time is the" - scheduling question (but NOT "what time is it")
    if _has_re(text, r"\bwhat time\s+is\s+(the|a|an|this|that|my|your|his|her)\b"):
        return False
    
    return True


def has_news_term(text: str) -> bool:
    if _has_re(text, MEDIA_RELIABILITY_TOPIC_PATTERN) and _has_re(text, MEDIA_PUBLICATION_PATTERN):
        return False
    # Keep AI governance/policy update prompts off generic NEWS routing.
    if (
        _has_re(text, r"\b(update|updates)\b")
        and _has_re(text, r"\b(ai|artificial intelligence|genai|llm|foundation models?)\b")
        and _has_re(text, r"\b(policy|governance|regulation|safety)\b")
    ):
        return False
    return _has_re(text, NEWS_TERM_PATTERN)


def has_conflict_term(text: str) -> bool:
    return _has_re(text, CONFLICT_TERM_PATTERN)


def has_source_request_signal(text: str) -> bool:
    if is_probable_culinary_source_misrecognition(text):
        return False
    return _has_re(text, SOURCE_REQUEST_PATTERN)


def has_geopolitics_entity(text: str) -> bool:
    return _has_re(text, GEOPOLITICS_PATTERN)


def has_israel_region_entity(text: str) -> bool:
    return _has_re(text, ISRAEL_REGION_PATTERN)


def should_use_israel_news_region(text: str) -> bool:
    return has_israel_region_entity(text) and (has_temporal_signal(text) or has_news_term(text))


def build_common_signal_flags(text: str) -> Dict[str, bool]:
    return {
        "temporal": has_temporal_signal(text),
        "news": has_news_term(text),
        "conflict": has_conflict_term(text),
        "geopolitics": has_geopolitics_entity(text),
        "israel_region": should_use_israel_news_region(text),
        "source_request": has_source_request_signal(text),
        "url": _has_re(text, r"https?://"),
    }
