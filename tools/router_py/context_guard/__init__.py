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
import os
from typing import Any

# Suppress noisy transformers/sentence-transformers progress bars during model
# load. Local Lucy loads several small embedding models at startup.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

logger = logging.getLogger(__name__)

from .config import (
    EVIDENCE_CROSS_ENCODER,
    EVIDENCE_THRESHOLD,
    MEMORY_BI_ENCODER,
    MEMORY_THRESHOLD,
)
from .evidence import is_evidence_relevant, score_evidence_relevance
from .memory import filter_memory_context, score_memory_relevance

# Lazy-loaded singletons. A truthy value means "loaded", False means
# "tried and failed" so we don't retry on every call.
_ce_model: Any | None = None
_bi_model: Any | None = None


def _load_ce_model() -> Any | None:
    """Lazy-load the evidence cross-encoder."""
    global _ce_model
    if _ce_model is None:
        try:
            from sentence_transformers import CrossEncoder

            _ce_model = CrossEncoder(
                EVIDENCE_CROSS_ENCODER,
                max_length=512,
                device="cpu",
            )
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load evidence cross-encoder %s: %s. Falling back to keyword relevance.",
                EVIDENCE_CROSS_ENCODER,
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

            _bi_model = SentenceTransformer(MEMORY_BI_ENCODER, device="cpu")
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load memory bi-encoder %s: %s. Falling back to keyword relevance.",
                MEMORY_BI_ENCODER,
                exc,
            )
            _bi_model = False
    return _bi_model if _bi_model else None


__all__ = [
    "score_evidence_relevance",
    "is_evidence_relevant",
    "score_memory_relevance",
    "filter_memory_context",
    "_load_ce_model",
    "_load_bi_model",
    "_ce_model",
    "_bi_model",
]
