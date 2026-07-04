"""Context relevance guard.

Hybrid semantic + keyword/entity scoring for retrieved evidence and
session-memory turns. The goal is to stop obviously irrelevant context
(e.g. a Wikipedia article about China for a Japan query, or a stale wrong
assistant turn) from reaching the LLM prompt.

Additional hardening signals (Phase 1-2):
- Provenance scoring: Wikipedia / medical / official APIs score higher;
  generated text and memory score lower.
- Temporal compatibility: current-fact queries penalise evidence older than
  30 days (weather and time sources are exempt).
- Entity collision: a query named entity that does not appear in the evidence
  reduces the score.
- Answerability: evidence with no content-word overlap with the question is
  heavily discounted.

Semantic models are loaded lazily on first use. If sentence-transformers is
not installed or a model fails to load, the guard falls back to deterministic
keyword overlap so requests never crash.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_EVIDENCE_THRESHOLD = 0.50
_MEMORY_THRESHOLD = 0.30

_EVIDENCE_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MEMORY_BI_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"

# Lazy-loaded singletons. A truthy value means "loaded", False means
# "tried and failed" so we don't retry on every call.
_ce_model: Any | None = None
_bi_model: Any | None = None

# Hardening constants
_CURRENT_MARKERS = {"current", "latest", "now", "today", "price"}
_STALE_DAYS = 30
_ANSWERABILITY_PENALTY = 0.1
_ENTITY_COLLISION_PENALTY = 0.5
_TEMPORAL_PENALTY = 0.7

# Provenance labels ordered from most to least trustworthy for evidence.
_TRUSTED_PROVENANCES = {"wikipedia", "medical", "finance", "weather", "news"}


def _sigmoid(x: float) -> float:
    """Map an unbounded logit to [0.0, 1.0]."""
    x = float(x)
    if math.isnan(x):
        return 0.0
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _load_ce_model() -> Any | None:
    """Lazy-load the evidence cross-encoder."""
    global _ce_model
    if _ce_model is None:
        try:
            from sentence_transformers import CrossEncoder

            _ce_model = CrossEncoder(
                _EVIDENCE_CROSS_ENCODER,
                max_length=512,
                device="cpu",
            )
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load evidence cross-encoder %s: %s. Falling back to keyword relevance.",
                _EVIDENCE_CROSS_ENCODER,
                exc,
            )
            _ce_model = False
    return _ce_model if _ce_model else None


def _load_bi_model() -> Any | None:
    """Lazy-load the memory bi-encoder."""
    global _bi_model
    if _bi_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _bi_model = SentenceTransformer(_MEMORY_BI_ENCODER, device="cpu")
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load memory bi-encoder %s: %s. Falling back to keyword relevance.",
                _MEMORY_BI_ENCODER,
                exc,
            )
            _bi_model = False
    return _bi_model if _bi_model else None


def _evidence_text(evidence: dict[str, Any]) -> str:
    """Assemble a single text string from an evidence dict."""
    if not evidence:
        return ""
    title = str(evidence.get("title", "") or "")
    body = str(
        evidence.get("context") or evidence.get("content") or evidence.get("formatted") or ""
    )
    return f"{title} {body}".strip()


def _extract_provenance(evidence: dict[str, Any]) -> str:
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


def _apply_provenance(score: float, provenance: str) -> float:
    """Adjust *score* based on evidence provenance."""
    if provenance in _TRUSTED_PROVENANCES:
        return min(1.0, score + 0.05)
    if provenance == "generated":
        return score * 0.8
    if provenance == "memory":
        return score * 0.9
    return score


def _is_current_query(question: str) -> bool:
    """Return True if the question asks for current/latest information."""
    norm = _normalize(question)
    return any(marker in norm for marker in _CURRENT_MARKERS)


def _parse_date(value: str) -> datetime | None:
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


def _apply_temporal_penalty(
    question: str, evidence: dict[str, Any], score: float, provenance: str
) -> float:
    """Penalise stale evidence for current-fact queries."""
    if provenance in ("weather", "time"):
        return score
    if not _is_current_query(question):
        return score

    date_value = evidence.get("date") or evidence.get("published")
    if not date_value:
        return score

    parsed = _parse_date(str(date_value))
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

    if age_days > _STALE_DAYS:
        return score * _TEMPORAL_PENALTY
    return score


def _extract_named_entities(text: str) -> set[str]:
    """Extract simple named-entity candidates (capitalised word sequences)."""
    if not text:
        return set()

    # Split into sentences so we can ignore sentence-initial single words.
    sentences = re.split(r"[.!?]\s+", text)
    entities: set[str] = set()
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for match in re.finditer(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b", sentence):
            entity = match.group(1)
            start = match.start()
            # Ignore a single capitalised word that starts the sentence.
            if start == 0 and " " not in entity:
                continue
            entities.add(entity.lower())
    return entities


def _apply_entity_collision(question: str, evidence: dict[str, Any], score: float) -> float:
    """Reduce score when the evidence refers to a different named entity."""
    place_tail = _extract_place_tail(question)
    query_entities = _extract_named_entities(question)
    if place_tail:
        query_entities.add(place_tail.lower())

    if not query_entities:
        return score

    evidence_text = _evidence_text(evidence)
    evidence_entities = _extract_named_entities(evidence_text)

    if not evidence_entities:
        return score

    if not (query_entities & evidence_entities):
        return score * _ENTITY_COLLISION_PENALTY
    return score


def _apply_answerability_penalty(question: str, evidence_text: str, score: float) -> float:
    """Discount evidence that shares no content words with the question."""
    keywords = _extract_keywords(question)
    if not keywords:
        return score
    evidence_norm = _normalize(evidence_text)
    if not any(kw in evidence_norm for kw in keywords):
        return score * _ANSWERABILITY_PENALTY
    return score


def _keyword_evidence_score(question: str, evidence: dict[str, Any]) -> float:
    """Fallback keyword/entity scorer for evidence."""
    text = _evidence_text(evidence)
    if not text:
        return 0.0

    combined = _normalize(text)

    tail = _extract_place_tail(question)
    if tail:
        if _contains_tail(combined, tail):
            keywords = _extract_keywords(question)
            if keywords:
                matched = sum(1 for kw in keywords if kw in combined)
                # Intentional boost: this preserves the original keyword guard
                # behavior, not the simplified raw-ratio snippet in the plan.
                return max(0.6, matched / len(keywords))
            # Same intentional boost when no question keywords remain.
            return 0.8
        return 0.0

    keywords = _extract_keywords(question)
    if not keywords:
        return 0.3 if combined else 0.0

    matched = sum(1 for kw in keywords if kw in combined)
    return matched / len(keywords)


def _keyword_memory_score(question: str, turn: str) -> float:
    """Fallback keyword/entity scorer for a memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    turn_norm = _normalize(turn)

    tail = _extract_place_tail(question)
    if tail and _contains_tail(turn_norm, tail):
        return 0.9

    keywords = _extract_keywords(question)
    if not keywords:
        return 0.0

    matched = sum(1 for kw in keywords if kw in turn_norm)
    return matched / len(keywords)


def score_evidence_relevance(question: str, evidence: dict[str, Any]) -> float:
    """Return a 0.0-1.0 relevance score for *evidence* against *question*."""
    if not evidence:
        return 0.0

    text = _evidence_text(evidence)
    if not text:
        return 0.0

    model = _load_ce_model()
    if model is not None:
        try:
            raw = model.predict(
                [(question, text)],
                show_progress_bar=False,
            )[0]
            score = _sigmoid(raw)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Evidence semantic scoring failed: %s", exc)
            score = _keyword_evidence_score(question, evidence)
    else:
        score = _keyword_evidence_score(question, evidence)

    if score <= 0.0:
        return 0.0

    score = _apply_answerability_penalty(question, text, score)
    provenance = _extract_provenance(evidence)
    score = _apply_provenance(score, provenance)
    score = _apply_temporal_penalty(question, evidence, score, provenance)
    score = _apply_entity_collision(question, evidence, score)

    return max(0.0, min(1.0, score))


def is_evidence_relevant(
    question: str,
    evidence: dict[str, Any],
    threshold: float = _EVIDENCE_THRESHOLD,
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
                item_summary=_evidence_text(evidence)[:120],
                score=score,
                accepted=accepted,
                reason="semantic+keyword+provenance+temporal+entity+answerability",
                extra={
                    "provenance": _extract_provenance(evidence),
                    "threshold": threshold,
                    "title": str(evidence.get("title", ""))[:60],
                },
            )
        except Exception:
            logger.debug("Failed to record evidence decision metric", exc_info=True)

    return accepted


def score_memory_relevance(question: str, turn: str) -> float:
    """Return a 0.0-1.0 relevance score for a single memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    model = _load_bi_model()
    if model is not None:
        try:
            import numpy as np

            q_emb = model.encode(
                [question],
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            t_emb = model.encode(
                [turn],
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            q_norm = np.linalg.norm(q_emb, axis=1)
            t_norm = np.linalg.norm(t_emb, axis=1)
            denom = q_norm * t_norm
            sim = np.divide(
                np.sum(q_emb * t_emb, axis=1),
                denom,
                out=np.zeros_like(denom),
                where=denom > 1e-9,
            )
            return float(sim[0])
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Memory semantic scoring failed: %s", exc)

    return _keyword_memory_score(question, turn)


def filter_memory_context(
    question: str,
    memory_text: str,
    threshold: float = _MEMORY_THRESHOLD,
    request_id: str | None = None,
) -> str:
    """Return only memory turns plausibly relevant to *question*.

    Turns are separated by blank lines. If nothing survives filtering, returns
    an empty string so callers can skip memory injection entirely.
    """
    if not memory_text.strip():
        return ""

    turns = [t.strip() for t in memory_text.split("\n\n") if t.strip()]
    kept: list[str] = []
    for turn in turns:
        score = score_memory_relevance(question, turn)
        accepted = score >= threshold
        if request_id:
            try:
                from metrics import record_context_decision

                record_context_decision(
                    request_id=request_id,
                    query=question,
                    kind="memory",
                    item_summary=turn[:120],
                    score=score,
                    accepted=accepted,
                    reason="semantic+keyword memory relevance",
                    extra={"threshold": threshold},
                )
            except Exception:
                logger.debug("Failed to record memory decision metric", exc_info=True)
        if accepted:
            kept.append(turn)

    if request_id:
        try:
            from metrics import record_context_usage

            record_context_usage(
                request_id=request_id,
                context_kind="memory",
                used=len(kept),
                total=len(turns),
            )
        except Exception:
            logger.debug("Failed to record memory usage metric", exc_info=True)

    return "\n\n".join(kept)


# --- retained keyword helpers (unchanged logic, only minor renames) ---

_STOP_WORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "must",
    "shall",
    "can",
    "need",
    "used",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "for",
    "with",
    "about",
    "from",
    "up",
    "down",
    "out",
    "off",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "when",
    "where",
    "why",
    "how",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "no",
    "nor",
    "not",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "now",
    "what",
    "which",
    "who",
    "whom",
    "whose",
    "this",
    "that",
    "these",
    "those",
    "i",
    "you",
    "he",
    "she",
    "it",
    "we",
    "they",
    "me",
    "him",
    "her",
    "us",
    "them",
    "my",
    "your",
    "his",
    "its",
    "our",
    "their",
    "and",
    "but",
    "or",
    "yet",
    "so",
    "if",
    "because",
    "although",
    "though",
    "while",
    "whereas",
    "main",
    "popular",
    "famous",
    "best",
    "top",
    "list",
    "tell",
    "give",
}

_KEYWORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
_PLACE_TAIL_RE = re.compile(r"\b(?:in|of)\s+([A-Za-z][A-Za-z\s]*?)\s*(?:[?.!])?\s*$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _extract_keywords(text: str) -> set[str]:
    keywords: set[str] = set()
    for w in _KEYWORD_RE.findall(_normalize(text)):
        if len(w) > 3 and w not in _STOP_WORDS:
            keywords.add(w)
    return keywords


def _extract_place_tail(text: str) -> str | None:
    match = _PLACE_TAIL_RE.search(text)
    if not match:
        return None
    tail = match.group(1).strip()
    tail = re.sub(r"^(?:the|a|an)\s+", "", tail, flags=re.IGNORECASE).strip()
    return tail if tail else None


def _contains_tail(text: str, tail: str) -> bool:
    if not tail:
        return False
    norm = _normalize(text)
    tail_norm = _normalize(tail)
    if tail_norm in norm:
        return True
    parts = [p for p in tail_norm.split() if p]
    if len(parts) > 1 and all(part in norm for part in parts):
        return True
    return False
