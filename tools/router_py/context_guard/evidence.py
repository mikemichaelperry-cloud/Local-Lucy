"""Evidence relevance scoring for the context relevance guard."""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

from .config import (
    ANSWERABILITY_PENALTY,
    CURRENT_MARKERS,
    ENTITY_COLLISION_PENALTY,
    EVIDENCE_THRESHOLD,
    STALE_DAYS,
    TEMPORAL_PENALTY,
    TRUSTED_PROVENANCES,
)
from .text import (
    contains_tail,
    extract_keywords,
    extract_named_entities,
    extract_place_tail,
    normalize,
)

logger = logging.getLogger("context_guard")


def sigmoid(x: float) -> float:
    """Map an unbounded logit to [0.0, 1.0]."""
    x = float(x)
    if math.isnan(x):
        return 0.0
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def evidence_text(evidence: dict[str, Any]) -> str:
    """Assemble a single text string from an evidence dict."""
    if not evidence:
        return ""
    title = str(evidence.get("title", "") or "")
    body = str(
        evidence.get("context") or evidence.get("content") or evidence.get("formatted") or ""
    )
    return f"{title} {body}".strip()


def extract_provenance(evidence: dict[str, Any]) -> str:
    """Return a provenance label for an evidence item."""
    if not evidence:
        return "unknown"

    provenance = str(evidence.get("provenance", "") or "").lower().strip()
    if provenance in {
        "wikipedia",
        "news",
        "medical",
        "finance",
        "weather",
        "generated",
        "memory",
    }:
        return provenance

    provider = str(evidence.get("provider", "") or "").lower()
    source = str(evidence.get("source", "") or "").lower()

    if "wikipedia" in provider or "wikipedia" in source:
        return "wikipedia"
    if provider in ("news", "rss") or "news" in provider:
        return "news"
    if "medical" in provider or "pubmed" in source or "medline" in source:
        return "medical"
    if provider in ("finance", "yahoo") or "finance" in provider:
        return "finance"
    if provider in ("weather", "wttr") or "weather" in provider:
        return "weather"
    if provider in ("openai", "kimi", "generated", "llm"):
        return "generated"
    if provider == "memory" or "memory" in source:
        return "memory"

    return "unknown"


def apply_provenance(score: float, provenance: str) -> float:
    """Adjust *score* based on evidence provenance."""
    if provenance in TRUSTED_PROVENANCES:
        return min(1.0, score + 0.05)
    if provenance == "generated":
        return score * 0.8
    if provenance == "memory":
        return score * 0.9
    return score


def is_current_query(question: str) -> bool:
    """Return True if the question asks for current/latest information."""
    norm = normalize(question)
    return any(marker in norm for marker in CURRENT_MARKERS)


def parse_date(value: str) -> datetime | None:
    """Best-effort date parsing with fallback regex extraction."""
    if not value:
        return None

    try:
        from dateutil import parser as dateutil_parser

        return dateutil_parser.parse(value)
    except Exception:
        pass

    # Fallback: common ISO / US / verbal date patterns.
    patterns = [
        (
            r"(\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?)",
            None,
        ),
        (r"(\d{2}/\d{2}/\d{4})", "%m/%d/%Y"),
        (
            r"(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
            "%d %B %Y",
        ),
    ]

    for pattern, fmt in patterns:
        match = re.search(pattern, value, re.IGNORECASE)
        if not match:
            continue
        candidate = match.group(1)
        try:
            if fmt:
                return datetime.strptime(candidate, fmt)
            return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
        except Exception:
            continue

    return None


def apply_temporal_penalty(
    question: str, evidence: dict[str, Any], score: float, provenance: str
) -> float:
    """Penalise stale evidence for current-fact queries."""
    if provenance in ("weather", "time"):
        return score
    if not is_current_query(question):
        return score

    date_value = evidence.get("date") or evidence.get("published")
    if not date_value:
        return score

    parsed = parse_date(str(date_value))
    if parsed is None:
        return score

    try:
        if parsed.tzinfo is None:
            now = datetime.now()
        else:
            now = datetime.now(timezone.utc)
        age_days = (now - parsed).days
    except Exception:
        return score

    if age_days > STALE_DAYS:
        return score * TEMPORAL_PENALTY
    return score


def apply_entity_collision(question: str, evidence: dict[str, Any], score: float) -> float:
    """Reduce score when the evidence refers to a different named entity."""
    place_tail = extract_place_tail(question)
    query_entities = extract_named_entities(question)
    if place_tail:
        query_entities.add(place_tail.lower())

    if not query_entities:
        return score

    text = evidence_text(evidence)
    evidence_entities = extract_named_entities(text)

    if not evidence_entities:
        return score

    if not (query_entities & evidence_entities):
        return score * ENTITY_COLLISION_PENALTY
    return score


def apply_answerability_penalty(question: str, evidence_text: str, score: float) -> float:
    """Discount evidence that shares no content words with the question."""
    keywords = extract_keywords(question)
    if not keywords:
        return score
    evidence_norm = normalize(evidence_text)
    if not any(kw in evidence_norm for kw in keywords):
        return score * ANSWERABILITY_PENALTY
    return score


def keyword_evidence_score(question: str, evidence: dict[str, Any]) -> float:
    """Fallback keyword/entity scorer for evidence."""
    text = evidence_text(evidence)
    if not text:
        return 0.0

    combined = normalize(text)

    tail = extract_place_tail(question)
    if tail:
        if contains_tail(combined, tail):
            keywords = extract_keywords(question)
            if keywords:
                matched = sum(1 for kw in keywords if kw in combined)
                # Intentional boost: this preserves the original keyword guard
                # behavior, not the simplified raw-ratio snippet in the plan.
                return max(0.6, matched / len(keywords))
            # Same intentional boost when no question keywords remain.
            return 0.8
        return 0.0

    keywords = extract_keywords(question)
    if not keywords:
        return 0.3 if combined else 0.0

    matched = sum(1 for kw in keywords if kw in combined)
    return matched / len(keywords)


def score_evidence_relevance(question: str, evidence: dict[str, Any]) -> float:
    """Return a 0.0-1.0 relevance score for *evidence* against *question*."""
    if not evidence:
        return 0.0

    text = evidence_text(evidence)
    if not text:
        return 0.0

    # Import lazily from the package so tests can patch context_guard._load_ce_model.
    from context_guard import _load_ce_model

    model = _load_ce_model()
    if model is not None:
        try:
            raw = model.predict(
                [(question, text)],
                show_progress_bar=False,
            )[0]
            score = sigmoid(raw)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Evidence semantic scoring failed: %s", exc)
            score = keyword_evidence_score(question, evidence)
    else:
        score = keyword_evidence_score(question, evidence)

    if score <= 0.0:
        return 0.0

    score = apply_answerability_penalty(question, text, score)
    provenance = extract_provenance(evidence)
    score = apply_provenance(score, provenance)
    score = apply_temporal_penalty(question, evidence, score, provenance)
    score = apply_entity_collision(question, evidence, score)

    return max(0.0, min(1.0, score))


def is_evidence_relevant(
    question: str,
    evidence: dict[str, Any],
    threshold: float = EVIDENCE_THRESHOLD,
    request_id: str | None = None,
) -> bool:
    """Return True if *evidence* is relevant enough to inject into the prompt."""
    score = score_evidence_relevance(question, evidence)
    accepted = score >= threshold

    if request_id:
        try:
            from metrics import record_context_decision

            record_context_decision(
                request_id=request_id,
                query=question,
                kind="evidence",
                item_summary=evidence_text(evidence)[:120],
                score=score,
                accepted=accepted,
                reason="semantic+keyword+provenance+temporal+entity+answerability",
                extra={
                    "provenance": extract_provenance(evidence),
                    "threshold": threshold,
                    "title": str(evidence.get("title", ""))[:60],
                },
            )
        except Exception:
            logger.debug("Failed to record evidence decision metric", exc_info=True)

    return accepted
