#!/usr/bin/env python3
"""Conservative escalation suggestion logic for the request pipeline.

Escalation suggestions are produced only when the ``suggest_web_escalation``
capability flag is enabled. They are conservative by design: the pipeline never
fetches web sources automatically; it only tells the caller that web sources
might help.
"""

from __future__ import annotations

from router_py.escalation.config import (
    CRITICAL_CATEGORIES,
    SUGGESTION_CURRENT_INFO,
    SUGGESTION_GENERAL_KNOWLEDGE,
    THIN_LOCAL_CONFIDENCE_THRESHOLD,
)
from router_py.pipeline.config import CapabilityFlags
from router_py.request_types import (
    ClassificationResult,
    RoutingDecision,
    SourceAttribution,
)


def suggest_escalation(
    classification: ClassificationResult,
    decision: RoutingDecision,
    attribution: SourceAttribution | None,
    flags: CapabilityFlags | None,
) -> str:
    """Return a conservative web-escalation suggestion, or an empty string.

    Rules:
        * Disabled when ``flags.suggest_web_escalation`` is false or missing.
        * Never suggest for critical categories
          (medical, financial, legal, safety, personal identity).
        * Only suggest when the chosen route is LOCAL.
        * Suggest if the local answer looks thin
          (attribution basis is "none" or confidence is "low").
        * Suggest if the question signals a current-info need
          (``classification.needs_web`` is true) but was routed locally.

    Args:
        classification: The classified intent and routing signals.
        decision: The normalized routing decision.
        attribution: Optional source-attribution record for the answer.
        flags: Capability flags loaded once per request.

    Returns:
        A concise suggestion string, or "" when no escalation is advised.
    """
    if flags is None or not flags.suggest_web_escalation:
        return ""

    if decision.route != "LOCAL":
        return ""

    if _is_critical_category(classification):
        return ""

    # Thin local answer: no source basis, low attribution confidence, or a
    # classifier confidence below the conservative threshold.
    if attribution is not None and (
        attribution.basis == "none" or attribution.confidence == "low"
    ):
        return SUGGESTION_GENERAL_KNOWLEDGE

    # Low classifier confidence, unless the local answer is already backed by
    # evidence (high attribution confidence).  Guard against mocks or missing
    # values that may not be numeric.
    raw_confidence = getattr(classification, "confidence", None)
    if isinstance(raw_confidence, (int, float)):
        if raw_confidence < THIN_LOCAL_CONFIDENCE_THRESHOLD:
            if attribution is None or attribution.confidence != "high":
                return SUGGESTION_GENERAL_KNOWLEDGE

    # Current information need signalled by the classifier but routed locally.
    if classification.needs_web:
        return SUGGESTION_CURRENT_INFO

    return ""


def _is_critical_category(classification: ClassificationResult) -> bool:
    """Return True if the classification falls under a critical category."""
    category = (classification.category or "").lower()
    return any(crit in category for crit in CRITICAL_CATEGORIES)
