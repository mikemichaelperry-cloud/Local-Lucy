"""Context relevance guard.

Hybrid semantic + keyword/entity scoring for retrieved evidence and
session-memory turns. The goal is to stop obviously irrelevant context
(e.g. a Wikipedia article about China for a Japan query, or a stale wrong
assistant turn) from reaching the LLM prompt.

Semantic models are loaded lazily on first use. If sentence-transformers is
not installed or a model fails to load, the guard falls back to deterministic
keyword overlap so requests never crash.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

_EVIDENCE_THRESHOLD = 0.50
_MEMORY_THRESHOLD = 0.20

_EVIDENCE_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MEMORY_BI_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"

# Lazy-loaded singletons. A truthy value means "loaded", False means
# "tried and failed" so we don't retry on every call.
_ce_model: Any | None = None
_bi_model: Any | None = None


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
            return _sigmoid(raw)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Evidence semantic scoring failed: %s", exc)

    return _keyword_evidence_score(question, evidence)


def is_evidence_relevant(
    question: str,
    evidence: dict[str, Any],
    threshold: float = _EVIDENCE_THRESHOLD,
) -> bool:
    """Return True if *evidence* is relevant enough to inject into the prompt."""
    return score_evidence_relevance(question, evidence) >= threshold


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
        if score >= threshold:
            kept.append(turn)

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
