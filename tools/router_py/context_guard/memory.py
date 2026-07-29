"""Memory relevance scoring and filtering for the context relevance guard."""

from __future__ import annotations

import logging
from typing import Optional

from .config import MEMORY_THRESHOLD
from .text import contains_tail, extract_keywords, extract_place_tail, normalize

logger = logging.getLogger("context_guard")


def keyword_memory_score(question: str, turn: str) -> float:
    """Fallback keyword/entity scorer for a memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    turn_norm = normalize(turn)

    tail = extract_place_tail(question)
    if tail and contains_tail(turn_norm, tail):
        return 0.9

    keywords = extract_keywords(question)
    if not keywords:
        return 0.0

    matched = sum(1 for kw in keywords if kw in turn_norm)
    return matched / len(keywords)


def score_memory_relevance(question: str, turn: str) -> float:
    """Return a 0.0-1.0 relevance score for a single memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    # Import lazily from the package so tests can patch context_guard._load_bi_model.
    from context_guard import _load_bi_model

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

    return keyword_memory_score(question, turn)


def filter_memory_context(
    question: str,
    memory_text: str,
    threshold: float = MEMORY_THRESHOLD,
    request_id: Optional[str] = None,
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
