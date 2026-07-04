#!/usr/bin/env python3
"""Deterministic policy-gate layer for Local Lucy routing.

This module separates operational/policy routing decisions from the semantic
k-NN router.  Each gate is a small, named, testable function that returns a
``PolicyDecision`` only when it is confident about the intended route.

The policy router is intentionally conservative: when in doubt it returns
``None`` and lets the embedding router handle the ambiguity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from router_py.request_types import ClassificationResult


@dataclass(frozen=True)
class PolicyDecision:
    """A deterministic routing decision produced by a policy gate.

    Carries everything needed to build a ``RoutingDecision`` plus trace
    metadata so the final route is explainable.
    """

    route: str
    reason_code: str
    matched_rule: str
    confidence: float = 1.0
    ephemeral: bool = False
    evidence_mode: str = ""
    evidence_reason: str = ""
    requires_evidence: bool = False
    provider: str = ""
    provider_usage_class: str = "local"
    policy_reason: str = ""
    trace: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Phrase lists used by the gates.
# These are intentionally narrow to avoid catching historical, metaphorical, or
# technical uses of words like "current", "latest", or "live".
# ---------------------------------------------------------------------------

_EVIDENCE_REQUEST_PHRASES = frozenset(
    {
        "verify this",
        "verify that",
        "search the web",
        "search online",
        "find sources",
        "find a source",
        "provide evidence",
        "provide sources",
        "cite sources",
        "cite your sources",
        "give me sources",
        "research this",
        "look this up",
        "check whether this is true",
        "check if this is true",
        "fact check",
        "fact-check",
        "peer-reviewed",
        "systematic review",
        "meta-analysis",
        "clinical trial",
    }
)

# Phrases that signal the user wants subjective analysis, critique, speculation,
# or conspiracy-style questioning rather than live data retrieval.
_LOCAL_REASONING_PHRASES = frozenset(
    {
        "what is your opinion",
        "in your opinion",
        "critique",
        "criticize",
        "evaluate",
        "speculate",
        "speculation",
        "hypothetically",
        "what if",
        "is it true that",
        "credible",
        "conspiracy theory",
        "conspiracy theories",
        "hoax",
        "controlled by aliens",
        "what happened at area 51",
        "flat earth",
        "moon landing fake",
        "lizard people",
        "should it be",
        "should they be",
        "should we be",
    }
)

# Markers that indicate the query is about a current/live fact, even if it is
# phrased as an opinion or speculation.  Queries matching both a local-reasoning
# phrase and a current-fact marker bypass the local-reasoning gate so finance,
# news, weather, time, or current-information gates can fire.
_CURRENT_FACT_MARKERS = frozenset(
    {
        "today",
        "now",
        "right now",
        "current",
        "currently",
        "this week",
        "this morning",
        "tonight",
        "this year",
        "latest",
        "just now",
        "as of today",
        "breaking",
    }
)

_CURRENT_OFFICE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bcurrent\s+(president|prime minister|mayor|governor|leader|head of state|king|queen|chancellor|premier)\s+of\b",
        r"\bwho\s+is\s+the\s+current\s+(president|prime minister|mayor|governor|leader|head of state|king|queen|chancellor|premier)\b",
        r"\bcurrent\s+(ceo|cfo|cto|chairman|chairperson|director)\s+of\b",
    )
)

_LATEST_RELEASE_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\blatest\s+(iphone|ipad|macbook|imac|android|samsung|pixel|galaxy|ios|macos|windows|ubuntu)\b",
        r"\blatest\s+(version|release|update)\s+of\b",
        r"\bcurrent\s+(version|release|update)\s+of\b",
        r"\bwhat\s+is\s+the\s+latest\s+version\s+of\b",
    )
)

_LIVE_EVENT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\blive\s+(score|scores|update|updates|match|game|stream)\b",
        r"\bcurrent\s+(score|scores)\b",
        r"\bwho\s+is\s+winning\b",
        r"\bflight\s+\w+\d+\s+(status|on time|delayed)\b",
        r"\bis\s+flight\s+\w+\d+\s+on\s+time\b",
        r"\bcurrent\s+(schedule|timetable)\s+(for|of)\b",
    )
)

# Queries that ask for factual details about a specific named real-world entity.
# The patterns require a capitalized multi-word or single-word proper noun after
# the trigger phrase, and they deliberately skip generic "what is X" science
# questions unless one of the factual frames below is present.
# (?i:...) makes the trigger case-insensitive; (?-i:...) keeps the proper noun
# case-sensitive so we only match real named entities.
_SPECIFIC_ENTITY_FACT_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"(?i:\b(?:actual\s+facts|facts|information|details|tell\s+me)\s+about\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)",
        r"(?i:\bhistory\s+of\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)",
        r"(?i:\bwhere\s+(?:is|are)\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)",
        r"(?i:\bwhen\s+(?:was|were)\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)(?i:\s+(?:founded|established|created|built|formed))",
        r"(?i:\bwho\s+(?:is|are|was|were)\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)",
        r"(?i:\bwhat\s+(?:is|are)\s+(?:the|a|an)?\s*)(?-i:[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)(?i:\s+(?:really|actually|in\s+reality))",
    )
)

# First/second person markers that should keep a query in LOCAL (personal/family
# or introspective), and creative markers that should not be treated as factual.
_ENTITY_FACT_EXCLUSION_TERMS = frozenset(
    {
        "my ",
        "your ",
        "our ",
        "story about",
        "poem about",
        "write about",
        "song about",
        "fictional",
        "fiction",
        "made-up",
        "imaginary",
    }
)

# Broad factual "who/what/when/where/why/how" lookups.  Routed to AUGMENTED
# unless they clearly belong to a local capability (translation, coding, math,
# creative, opinion, personal/meta) or are already handled by another gate.
_FACT_LOOKUP_QUESTION_WORDS_RE = re.compile(
    r"^(who|what|when|where|why|how|is|are|was|were|did|does|do|can|could|would|should|will|shall|has|have|had)\b",
    re.IGNORECASE,
)

_FACT_LOOKUP_EXCLUSION_TERMS = frozenset(
    {
        # Translation is a local capability.
        "translate",
        "translation",
        "in arabic",
        "in french",
        "in spanish",
        "in german",
        "in chinese",
        "in japanese",
        "in russian",
        "in italian",
        # Coding / technical how-to stays local (installation steps, debugging).
        "code",
        "function",
        "script",
        "program",
        "programming",
        "python",
        "javascript",
        "bash",
        "command",
        "install",
        "debug",
        "compile",
        "error",
        "library",
        "framework",
        # Math stays local.
        "calculate",
        "solve",
        "equation",
        "plus",
        "minus",
        "times",
        "divided by",
        "square root",
        "sum of",
        "product of",
        # Creative stays local.
        "story",
        "poem",
        "joke",
        "song",
        "write",
        "creative",
        # Opinion / advice stays local.
        "opinion",
        "think",
        "should i",
        "best",
        "worst",
        "recommend",
        # Personal / meta stays local.
        "my ",
        "your ",
        "our ",
        "you ",
        "yourself",
        "who are you",
        "what are you",
        "who am i",
        "what am i",
        # Covered by other gates (finance, weather, news, time, etc.).
        "weather",
        "forecast",
        "temperature",
        "stock",
        "price",
        "news",
        "headlines",
        "breaking",
    }
)

# Stable scientific concepts that the local model handles well; routing them out
# to AUGMENTED increases latency without improving answer quality.
_STABLE_SCIENCE_TERMS = frozenset(
    {
        "photosynthesis",
        "cellular respiration",
        "dna replication",
        "theory of relativity",
        "relativity",
        "mitosis",
        "meiosis",
        "natural selection",
        "evolution",
        "newton's laws",
        "gravity",
        "thermodynamics",
        "quantum mechanics",
        "atomic structure",
        "periodic table",
        "climate change",
        "greenhouse effect",
        "leaves make food",
        "solar system",
        "the sun",
        "how hot is the sun",
        "sun's surface",
    }
)

# DIY / procedural how-to phrasing that should stay local.
_DIY_HOWTO_PHRASES_RE = re.compile(
    r"\b(how do i|how to|how 2|how can i|how should i|step by step|instructions for|"
    r"guide to|tutorial for|patch a|change a|replace a|fix a|unclog|jump start|"
    r"jump-start|drywall|car tire|flat tire|sink drain)\b",
    re.IGNORECASE,
)

# Short pronoun-only follow-ups that lack a concrete subject.
_PRONOUN_FOLLOWUP_RE = re.compile(
    r"^(what about it|how about it|how does it work|how does it|what does it|"
    r"why is that|what is it|how is it|who is it|where is it|when is it)[\s\W]*$",
    re.IGNORECASE,
)

# Historical war / conflict phrasing not already caught by _is_historical_query.
_WAR_HISTORY_RE = re.compile(
    r"\b(world war|cold war|war of|war in|battle of|caused world war|"
    r"started world war|won the war|lost the war)\b",
    re.IGNORECASE,
)

# Terms that make a "current" query clearly historical or technical, not live.
_NON_CURRENT_CONTEXT = frozenset(
    {
        "history",
        "historical",
        "invented",
        "invention",
        "discovered",
        "discovery",
        "founded",
        "built",
        "during",
        "century",
        "electric",
        "electrical",
        "circuit",
        "current flow",
        "alternating current",
        "direct current",
        "eddy current",
    }
)

_YEAR_RE = re.compile(r"\b(1\d{3}|20\d{2})\b")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _has_evidence_request_intent(query: str) -> bool:
    """Detect explicit user requests for sources, verification, or research."""
    if not query:
        return False
    q = query.lower()
    return any(phrase in q for phrase in _EVIDENCE_REQUEST_PHRASES)


def _is_current_office_holder_query(query: str) -> bool:
    """Current office-holder / leadership queries that need fresh data."""
    if not query:
        return False
    q = query.lower()
    if any(ctx in q for ctx in _NON_CURRENT_CONTEXT):
        return False
    if _YEAR_RE.search(q):
        return False
    return any(p.search(q) for p in _CURRENT_OFFICE_PATTERNS)


def _is_latest_release_query(query: str) -> bool:
    """Latest product/software release queries that need current data."""
    if not query:
        return False
    q = query.lower()
    if any(ctx in q for ctx in _NON_CURRENT_CONTEXT):
        return False
    return any(p.search(q) for p in _LATEST_RELEASE_PATTERNS)


def _is_live_event_query(query: str) -> bool:
    """Live sports, flights, schedules — transient current information."""
    if not query:
        return False
    q = query.lower()
    if any(ctx in q for ctx in _NON_CURRENT_CONTEXT):
        return False
    return any(p.search(q) for p in _LIVE_EVENT_PATTERNS)


def _is_current_information_query(query: str) -> bool:
    """Conservative umbrella for current/changing non-financial facts."""
    return (
        _is_current_office_holder_query(query)
        or _is_latest_release_query(query)
        or _is_live_event_query(query)
    )


def _looks_like_attachment_query(context: dict[str, Any] | None) -> bool:
    """Route via attachment metadata when a file/image/document is present."""
    if not context:
        return False
    attachments = context.get("attachments") or context.get("files") or []
    return bool(attachments)


# ---------------------------------------------------------------------------
# Policy gates
#
# Each gate returns a PolicyDecision or None.  Gates are ordered by priority
# in PolicyRouter.  They should stay small, focused, and conservative.
# ---------------------------------------------------------------------------


def gate_personal_family(
    query: str, classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Queries about the user's own family/pets should use local memory facts."""
    # Avoid circular import at module load time.
    from router_py.classify import _is_personal_family_query

    if not query or not _is_personal_family_query(query):
        return None
    # If any evidence-required context is present, do not force LOCAL.  This
    # lets medical, veterinary, legal, and source-verification queries fall
    # through to the appropriate evidence path.
    if classification.evidence_mode == "required" or classification.evidence_reason in (
        "medical_context",
        "medical_body_symptom",
        "veterinary_context",
        "legal_context",
        "financial_data",
    ):
        return None
    return PolicyDecision(
        route="LOCAL",
        reason_code="policy:personal_family",
        matched_rule="personal_family",
        provider="local",
        provider_usage_class="local",
        policy_reason="personal_family_memory",
    )


def gate_recreational_pet(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Casual pet outing/play queries are local opinion, not veterinary evidence.

    Prevents "should I walk my dog" or "what can I do with the dog today" from
    being misrouted to EVIDENCE just because they contain an animal word.
    """
    if not query:
        return None
    q = query.lower().strip()

    # Must contain an animal term (specific species or general pet/animal).
    has_animal = bool(
        re.search(
            r"\b(dog|cat|dogs|cats|puppy|puppies|kitten|kittens|pet|pets|animal|animals)\b",
            q,
        )
    )
    if not has_animal:
        return None

    # Do not treat health/disease queries as recreational.
    health_disease_terms = [
        "dysplasia", "cancer", "tumor", "lump", "vomiting", "diarrhea", "fever",
        "limp", "limping", "coughing", "sneezing", "scratching", "lethargic",
        "worms", "fleas", "ticks", "infection", "disease", "sick", "ill",
        "not eating", "refusing food", "lost weight", "pain", "hurt", "injured",
        "vet", "veterinary", "veterinarian", "emergency", "poison", "toxin",
    ]
    if any(term in q for term in health_disease_terms):
        return None

    # Recreational / outing / play indicators.
    recreational_indicators = [
        "walk",
        "walking",
        "outing",
        "outings",
        "play",
        "playing",
        "fun",
        "activity",
        "activities",
        "today",
        "this weekend",
        "do with",
        "take",
        "should i",
    ]
    if any(ind in q for ind in recreational_indicators):
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:recreational_pet",
            matched_rule="recreational_pet",
            provider="local",
            provider_usage_class="local",
            policy_reason="recreational_pet_query",
        )
    return None


def gate_medical_vet(
    query: str, classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Medical and veterinary queries require trusted evidence sources."""
    # Do not let the semantic classifier's medical false-positives swallow
    # obvious travel/tourism queries (e.g. "travel guide for Spain").  Keep the
    # medical route when real medical/veterinary terms are present.
    if query and _TRAVEL_PLACE_RE.search(query):
        q_lower = query.lower()
        medical_markers = (
            r"\bmedication\b", r"\bmedicine\b", r"\bprescription\b", r"\bdosage\b",
            r"\bvaccine\b", r"\bvaccination\b", r"\bmalaria\b", r"\bdengue\b",
            r"\binsurance\b", r"\bdoctor\b", r"\bhospital\b", r"\bclinic\b",
            r"\bpregnant\b", r"\bpregnancy\b", r"\bdiabetes\b", r"\ballergy\b",
            r"\ballergic\b", r"\bepipen\b", r"\bsymptom\b", r"\bsick\b",
            r"\billness\b", r"\bdisease\b", r"\binfection\b", r"\bpain\b",
            r"\bdog\b", r"\bcat\b", r"\bpet\b", r"\bveterinary\b", r"\bvet\b",
            r"\bpuppy\b", r"\bkitten\b",
        )
        if not any(re.search(m, q_lower) for m in medical_markers):
            return None
    if classification.evidence_reason in (
        "medical_context",
        "medical_body_symptom",
    ):
        return PolicyDecision(
            route="EVIDENCE",
            reason_code="policy:medical_evidence",
            matched_rule="medical_vet",
            evidence_mode="required",
            evidence_reason=classification.evidence_reason,
            requires_evidence=True,
            provider="trusted",
            provider_usage_class="local",
            policy_reason=f"evidence_required_{classification.evidence_reason}",
        )
    if classification.evidence_reason == "veterinary_context":
        return PolicyDecision(
            route="EVIDENCE",
            reason_code="policy:veterinary_evidence",
            matched_rule="medical_vet",
            evidence_mode="required",
            evidence_reason="veterinary_context",
            requires_evidence=True,
            provider="trusted",
            provider_usage_class="local",
            policy_reason="evidence_required_veterinary_context",
        )

    return None


def gate_ambiguous_local(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Adversarial cases where the embedding router confidently misroutes.

    These are known edge cases from the routing regression suite: planetary
    weather, historical financial prices, and the "news industry" as a topic.
    They look like live-data queries but are actually stable-knowledge or
    local-reasoning questions, so we force LOCAL before the embedding router
    can misclassify them.
    """
    if not query:
        return None
    q = query.lower().strip()

    # Planetary / space weather is a science question, not a live forecast.
    planetary_bodies = {
        "mars", "moon", "jupiter", "saturn", "venus", "mercury",
        "neptune", "uranus", "pluto", "sun", "solar system",
    }
    if "weather" in q and any(body in q for body in planetary_bodies):
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:planetary_weather_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="planetary_weather_is_science",
        )

    # "News industry" is a topic, not a request for current headlines.
    if "news industry" in q or "the news industry" in q:
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:news_topic_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="news_industry_is_topic",
        )

    # Financial instrument + explicit historical year is a history question.
    financial_terms = {
        "bitcoin", "btc", "ethereum", "eth", "stock", "stocks", "share", "shares",
        "gold", "silver", "oil", "gas", "price", "value", "traded",
    }
    if any(term in q for term in financial_terms) and re.search(r"\bin\s+19\d{2}\b|\bin\s+20\d{2}\b", q):
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:historical_finance_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="historical_finance_is_local",
        )

    # Generic commodity / household price lookups are local knowledge, not live finance.
    if "gallon of milk" in q or "price of milk" in q:
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:generic_commodity_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="generic_commodity_is_local",
        )

    # Common DIY / car-maintenance how-tos are local procedural knowledge.
    if q.startswith("how to jump start") or "jump start a car" in q or "jump-start a car" in q:
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:diy_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="diy_howto_is_local",
        )

    # "Hot" used metaphorically with trends/AI is not a weather query.
    if re.search(r"\bhot\b.*\btrends?\b.*\b(ai|artificial intelligence|tech|technology)\b", q):
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:metaphor_trends_local",
            matched_rule="ambiguous_local",
            provider="local",
            provider_usage_class="local",
            policy_reason="metaphorical_hot_trends_is_local",
        )

    return None


def gate_local_reasoning(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Opinion, critique, speculation, and conspiracy-style questions.

    These should be answered by the local model rather than routed to live
    data sources or news feeds.
    """
    if not query:
        return None
    q = query.lower().strip()
    if any(phrase in q for phrase in _LOCAL_REASONING_PHRASES):
        # If the query also references current/live facts, the user is asking
        # for reasoning *over* current information.  Route to AUGMENTED so the
        # answer can be grounded in current evidence rather than local opinion.
        if any(marker in q for marker in _CURRENT_FACT_MARKERS):
            return PolicyDecision(
                route="AUGMENTED",
                reason_code="policy:current_fact_reasoning",
                matched_rule="local_reasoning_current_fact",
                ephemeral=True,
                evidence_mode="required",
                evidence_reason="current_fact_with_reasoning",
                requires_evidence=True,
                provider="openai",
                provider_usage_class="paid",
                policy_reason="reasoning_over_current_facts",
            )
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:local_reasoning",
            matched_rule="local_reasoning",
            provider="local",
            provider_usage_class="local",
            policy_reason="subjective_or_speculative_reasoning",
        )
    return None


def _is_specific_entity_fact_query(query: str) -> bool:
    """Detect factual questions about a specific named real-world entity."""
    if not query:
        return False
    q = query.lower()
    # Skip personal/introspective/creative phrasing.
    if any(term in q for term in _ENTITY_FACT_EXCLUSION_TERMS):
        return False
    # Require one of the factual frames and a capitalized proper noun.
    return any(p.search(query) for p in _SPECIFIC_ENTITY_FACT_PATTERNS)


def gate_specific_entity_fact(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Specific named-place/person/organization factual queries -> AUGMENTED.

    This prevents the local model from hallucinating dates, locations, founders,
    and history for real-world entities. Wikipedia is tried first (free), with
    OpenAI/Kimi fallback in the AUGMENTED chain.
    """
    if not _is_specific_entity_fact_query(query):
        return None
    return PolicyDecision(
        route="AUGMENTED",
        reason_code="policy:specific_entity_fact",
        matched_rule="specific_entity_fact",
        evidence_mode="required",
        evidence_reason="specific_entity_fact",
        requires_evidence=True,
        provider="wikipedia",
        provider_usage_class="free",
        policy_reason="specific_entity_fact_lookup",
    )


def gate_finance(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Live financial market data."""
    from router_py.classify import _is_financial_ephemeral

    if query and _is_financial_ephemeral(query):
        return PolicyDecision(
            route="FINANCE",
            reason_code="policy:finance_ephemeral",
            matched_rule="finance",
            ephemeral=True,
            provider="finance",
            provider_usage_class="free",
            policy_reason="router_finance_guard",
        )
    return None


def gate_time(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Time-of-day queries."""
    from router_py.classify import _is_time_query

    if query and _is_time_query(query):
        return PolicyDecision(
            route="TIME",
            reason_code="policy:time_query",
            matched_rule="time",
            ephemeral=True,
            provider="timeapi",
            provider_usage_class="free",
            evidence_reason="time_query",
            policy_reason="router_time_guard",
        )
    return None


def gate_weather(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Weather forecasts / current conditions."""
    from router_py.classify import _is_weather_query

    if query and _is_weather_query(query):
        return PolicyDecision(
            route="WEATHER",
            reason_code="policy:weather_query",
            matched_rule="weather",
            ephemeral=True,
            provider="weather",
            provider_usage_class="free",
            evidence_reason="weather_query",
            policy_reason="router_weather_guard",
        )
    return None


def gate_news(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Explicit news phrasing (including typo-heavy variants)."""
    from router_py.classify import _is_clear_news_query, _is_news_query_typos

    if not query:
        return None
    if _is_clear_news_query(query) or _is_news_query_typos(query):
        return PolicyDecision(
            route="NEWS",
            reason_code="policy:news_phrase",
            matched_rule="news",
            ephemeral=True,
            provider="news",
            provider_usage_class="local",
            evidence_reason="news_synthesis",
            policy_reason="router_news_guard",
        )
    return None


def gate_evidence_request(
    query: str, classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Explicit user request for sources, verification, or research."""
    if not query:
        return None
    if not _has_evidence_request_intent(query):
        return None
    # Source requests that are not already medical/vet should go to AUGMENTED
    # with evidence required.
    return PolicyDecision(
        route="AUGMENTED",
        reason_code="policy:evidence_request",
        matched_rule="evidence_request",
        evidence_mode="required",
        evidence_reason="source_request",
        requires_evidence=True,
        provider="openai",
        provider_usage_class="paid",
        policy_reason="evidence_required_source_request",
    )


def gate_conflict_analysis(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Prediction / analysis questions about live conflicts."""
    from router_py.classify import _is_conflict_analysis_query

    if query and _is_conflict_analysis_query(query):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:conflict_analysis",
            matched_rule="conflict_analysis",
            ephemeral=True,
            evidence_mode="required",
            evidence_reason="conflict_live",
            requires_evidence=True,
            provider="openai",
            provider_usage_class="paid",
            policy_reason="router_conflict_analysis",
        )
    return None


def gate_public_figure_age(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Age of public figures — needs current-date verified answer."""
    from router_py.classify import _is_public_figure_age_query

    if query and _is_public_figure_age_query(query):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:public_figure_age",
            matched_rule="public_figure_age",
            evidence_mode="required",
            evidence_reason="public_figure_age",
            requires_evidence=True,
            provider="openai",
            provider_usage_class="paid",
            policy_reason="public_figure_age_override",
        )
    return None


def gate_recipe(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Cooking / recipe requests that benefit from web augmentation."""
    from router_py.classify import _is_cooking_query

    if query and _is_cooking_query(query):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:recipe_request",
            matched_rule="recipe",
            ephemeral=True,
            provider="wikipedia",
            provider_usage_class="free",
            policy_reason="router_recipe_guard",
        )
    return None


# Travel/tourism queries asking for places, attractions, or itinerary ideas in a
# specific destination.  These look like opinion requests ("suggest", "should")
# but are best answered with current, sourced destination information.
_TRAVEL_PLACE_RE = re.compile(
    r"\b(?:"
    r"places?\s+(?:to\s+(?:visit|see|go)\s+)?in|"
    r"things?\s+to\s+(?:do|see)\s+in|"
    r"what\s+to\s+(?:do|see)\s+in|"
    r"where\s+(?:to|should)(?:\s+we)?\s+(?:go|visit)(?:\s+(?:to|in))?|"
    r"(?:tourist\s+)?attractions?\s+in|"
    r"(?:visit|travel|trip|guide)\s+(?:to|in|for)|"
    r"going\s+to|"
    r"visiting"
    r")\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)"
)


def gate_travel_tourism(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Travel / tourism destination queries -> AUGMENTED (Wikipedia first)."""
    if not query:
        return None
    q = query.strip()
    # Require a capitalized place name so we don't catch generic "places to visit".
    if _TRAVEL_PLACE_RE.search(q):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:travel_tourism",
            matched_rule="travel_tourism",
            evidence_mode="required",
            evidence_reason="travel_tourism",
            requires_evidence=True,
            provider="wikipedia",
            provider_usage_class="free",
            policy_reason="travel_tourism_lookup",
        )
    return None


def _is_factual_lookup_query(query: str) -> bool:
    """Detect broad factual questions that should be verified externally."""
    if not query:
        return False
    q = query.lower().strip()
    # Keep very short or local-only utterances local.
    if len(q.split()) < 3:
        return False
    if any(term in q for term in _FACT_LOOKUP_EXCLUSION_TERMS):
        return False
    # Skip arithmetic / equations (e.g. "What is 2+2?").
    if re.search(r"[+\-*/=]", query):
        return False
    # Pronoun-only follow-ups reference prior context, not external facts.
    if _PRONOUN_FOLLOWUP_RE.search(q):
        return False
    # DIY / procedural how-tos are local capabilities.
    if _DIY_HOWTO_PHRASES_RE.search(q):
        return False
    # Stable scientific concepts are handled well by the local model.
    if any(term in q for term in _STABLE_SCIENCE_TERMS):
        return False
    # Historical queries (including wars) should not be treated as generic lookups.
    from router_py.policy import _is_historical_query

    if _is_historical_query(query):
        return False
    if _WAR_HISTORY_RE.search(q):
        return False
    # Personal-finance reasoning/advice stays local; only live market data goes out.
    from router_py.policy import _is_personal_finance_reasoning

    if _is_personal_finance_reasoning(query):
        return False
    return bool(_FACT_LOOKUP_QUESTION_WORDS_RE.search(q))


def gate_factual_lookup(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Broad factual lookups -> AUGMENTED with citation required.

    Implements the 'when in doubt, route out' rule: if the user asks a factual
    question that is not clearly a local capability and was not caught by a more
    specific gate, verify it through an external source rather than relying on
    the local model's parametric knowledge.
    """
    if not _is_factual_lookup_query(query):
        return None
    return PolicyDecision(
        route="AUGMENTED",
        reason_code="policy:factual_lookup",
        matched_rule="factual_lookup",
        evidence_mode="required",
        evidence_reason="factual_lookup",
        requires_evidence=True,
        provider="wikipedia",
        provider_usage_class="free",
        policy_reason="factual_lookup_truth_first",
    )


def gate_current_information(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Conservative current/changing facts not covered by other gates."""
    if not query:
        return None
    if not _is_current_information_query(query):
        return None
    return PolicyDecision(
        route="AUGMENTED",
        reason_code="policy:current_information",
        matched_rule="current_information",
        ephemeral=True,
        provider="openai",
        provider_usage_class="paid",
        policy_reason="router_current_information",
    )


def gate_attachment(
    query: str, _classification: ClassificationResult, context: dict[str, Any] | None
) -> PolicyDecision | None:
    """File/image/document input present in request metadata."""
    if _looks_like_attachment_query(context):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:attachment",
            matched_rule="attachment",
            provider="openai",
            provider_usage_class="paid",
            policy_reason="attachment_input",
        )
    return None


# Hebrew-script queries need deterministic routing because the embedding router
# and English keyword gates miss them. These patterns cover the most common
# Hebrew intents; anything unmatched falls through to the normal gates.
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_HEBREW_NEWS_TERMS = frozenset({"חדשות", "חדשות היום", "מה חדש", "עדכונים"})
_HEBREW_TIME_TERMS = frozenset({"מה השעה", "שעה עכשיו", "השעה בא"})
_HEBREW_WEATHER_TERMS = frozenset({"מזג אוויר", "תחזית", "מזג האוויר"})
_HEBREW_FACT_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"^מה[יוה]?\s+",
        r"^מי\s+",
        r"^איפה\s+",
        r"^מתי\s+",
        r"^למה\s+",
    )
)
# Hebrew translation/creative requests should stay LOCAL.
_HEBREW_LOCAL_PATTERNS = tuple(
    re.compile(p)
    for p in (
        r"איך\s+אומרים",
        r"איך\s+מגיעים",
        r"תכתוב\s+לי",
        r"כתוב\s+לי",
        r"ספר\s+לי\s+בדיחה",
    )
)


def gate_hebrew_query(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Deterministic routing for Hebrew-script queries.

    The English keyword gates and embedding router often misroute Hebrew.
    This gate catches the high-frequency Hebrew intents explicitly so that
    Hebrew Wikipedia / news / time / weather sources are used.
    """
    if not query or not _HEBREW_RE.search(query):
        return None
    q = query.strip()
    q_lower = q.lower()

    # Time
    if any(term in q_lower for term in _HEBREW_TIME_TERMS):
        return PolicyDecision(
            route="TIME",
            reason_code="policy:hebrew_time_query",
            matched_rule="hebrew_query",
            ephemeral=True,
            provider="timeapi",
            provider_usage_class="free",
            evidence_reason="time_query",
            policy_reason="hebrew_time_query",
        )

    # Weather
    if any(term in q_lower for term in _HEBREW_WEATHER_TERMS):
        return PolicyDecision(
            route="WEATHER",
            reason_code="policy:hebrew_weather_query",
            matched_rule="hebrew_query",
            ephemeral=True,
            provider="weather",
            provider_usage_class="free",
            evidence_reason="weather_query",
            policy_reason="hebrew_weather_query",
        )

    # News
    if any(term in q_lower for term in _HEBREW_NEWS_TERMS):
        return PolicyDecision(
            route="NEWS",
            reason_code="policy:hebrew_news_query",
            matched_rule="hebrew_query",
            ephemeral=True,
            provider="news",
            provider_usage_class="local",
            evidence_reason="news_synthesis",
            policy_reason="hebrew_news_query",
        )

    # Factual lookup (what/who/where/when/why/how)
    if any(p.search(q) for p in _HEBREW_FACT_PATTERNS):
        return PolicyDecision(
            route="AUGMENTED",
            reason_code="policy:hebrew_factual_lookup",
            matched_rule="hebrew_query",
            evidence_mode="required",
            evidence_reason="hebrew_factual_lookup",
            requires_evidence=True,
            provider="wikipedia",
            provider_usage_class="free",
            policy_reason="hebrew_factual_lookup",
        )

    return None


def gate_memory_followup(
    query: str, _classification: ClassificationResult, _context: dict[str, Any] | None
) -> PolicyDecision | None:
    """Explicit references to prior conversation should stay LOCAL.

    Generic memory queries like "what did we discuss earlier?" are easily
    misclassified as broad factual lookups because they start with a question
    word and share few keywords with the concrete prior topic. Keep them local
    so the session-memory context can answer them.
    """
    if not query:
        return None
    q = query.strip().lower()
    memory_phrases = (
        r"\bwhat\s+did\s+we\s+(discuss|talk|chat)\s+(earlier|before|about)\b",
        r"\bwhat\s+were\s+we\s+(discussing|talking|chatting)\s+(about|earlier|before)\b",
        r"\bwhat\s+did\s+i\s+(say|mention|ask)\s+(earlier|before)\b",
        r"\bwhat\s+did\s+you\s+(say|mention|tell\s+me)\s+(earlier|before)\b",
        r"\bwhat\s+was\s+(i|we)\s+(saying|talking|discussing)\s+(about|earlier|before)\b",
        r"\bremind\s+me\s+what\s+we\s+(discussed|talked|chatted)\s+(about|earlier|before)\b",
        r"\bwhat\s+was\s+our\s+(conversation|discussion)\s+about\b",
        r"\bwhat\s+have\s+we\s+been\s+(discussing|talking)\s+about\b",
    )
    if any(re.search(p, q) for p in memory_phrases):
        return PolicyDecision(
            route="LOCAL",
            reason_code="policy:memory_followup_local",
            matched_rule="memory_followup",
            provider="local",
            provider_usage_class="local",
            policy_reason="explicit_memory_reference",
        )
    return None


# ---------------------------------------------------------------------------
# Router orchestrator
# ---------------------------------------------------------------------------


class PolicyRouter:
    """Runs deterministic policy gates in priority order."""

    # Priority order matters: medical/vet must beat personal/family when symptoms
    # are present; weather must beat current-information; finance must beat
    # current-information for prices.
    DEFAULT_GATES = (
        gate_personal_family,
        gate_recreational_pet,
        gate_medical_vet,
        # Hebrew-script queries bypass the English keyword gates and embedding
        # router so that Hebrew Wikipedia / news / time / weather are used.
        # Placed early (after medical/vet) so English-centric gates do not
        # misroute Hebrew factual lookups to TIME, FINANCE, etc.
        gate_hebrew_query,
        # Specific external-source gates must run before the broad factual_lookup
        # gate so that time/weather/news/conflict/age/current queries keep their
        # dedicated routes and reason codes.
        gate_specific_entity_fact,
        gate_finance,
        gate_time,
        gate_weather,
        gate_news,
        gate_evidence_request,
        gate_conflict_analysis,
        gate_public_figure_age,
        gate_recipe,
        gate_travel_tourism,
        gate_current_information,
        # Explicit memory follow-ups must stay LOCAL; the broad factual_lookup
        # gate would otherwise misroute "what did we discuss earlier?" to
        # AUGMENTED because the query shares few keywords with the prior topic.
        gate_memory_followup,
        # Catch remaining broad factual lookups before local-reasoning/
        # ambiguous-local gates force them to the local model. The factual_lookup
        # gate carries its own exclusions for local capabilities (translation,
        # coding, math, creative, opinion, DIY, stable science, history).
        gate_factual_lookup,
        gate_local_reasoning,
        gate_ambiguous_local,
        gate_attachment,
    )

    def __init__(self, gates: tuple | None = None):
        self.gates = gates if gates is not None else self.DEFAULT_GATES

    def apply(
        self,
        query: str,
        classification: ClassificationResult,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision | None:
        """Return the first matching policy decision, or None if no gate matches."""
        for gate in self.gates:
            decision = gate(query, classification, context)
            if decision is not None:
                return decision
        return None
