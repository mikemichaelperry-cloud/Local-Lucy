#!/usr/bin/env python3
"""Critical-category guard for web-fetch escalation.

Blocks automatic web fetching for sensitive topics regardless of capability
flags. The category list is shared with the escalation suggestion logic so
policy stays consistent.

This module is intentionally limited to detection and helper functions. The
actual policy application lives in ``router_py.pipeline.route`` so that route
policy stays co-located with the other routing gates.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from router_py.escalation.config import CRITICAL_CATEGORIES
from router_py.request_types import ClassificationResult, RouterOutcome, RoutingDecision

logger = logging.getLogger(__name__)

# Mapping from critical category substring to the trusted-domain allowlist file
# that should be used when web sources are required.  Categories without an
# entry have no configured trusted source and are blocked when
# ``trusted_sources_only_critical`` is enabled.
TRUSTED_DOMAIN_FILES: dict[str, str] = {
    "medical": "config/trust/generated/medical_runtime.txt",
    "veterinary": "config/trust/generated/vet_runtime.txt",
    "vet": "config/trust/generated/vet_runtime.txt",
    "finance": "config/trust/generated/finance_runtime.txt",
    "financial": "config/trust/generated/finance_runtime.txt",
    "market": "config/trust/generated/finance_runtime.txt",
    "economic": "config/trust/generated/finance_runtime.txt",
    "legal": "config/trust/generated/policy_global_runtime.txt",
    "regulatory": "config/trust/generated/policy_global_runtime.txt",
    "travel": "config/trust/generated/travel_runtime.txt",
    "travel_advisory": "config/trust/generated/travel_runtime.txt",
}

# Fallback trusted-domain allowlist used when a critical EVIDENCE route already
# has provider="trusted" but no category-specific allowlist is configured.
DEFAULT_TRUSTED_DOMAIN_FILE: str = "config/trust/generated/allowlist_tier1.txt"


def is_critical_category(classification: ClassificationResult) -> bool:
    """Return True when the classification is in a critical category.

    Critical categories include medical, financial, legal, safety, identity,
    and related regulatory/market/travel topics. Web search must not be
    performed automatically for these.
    """
    category = (classification.category or "").lower()
    return any(crit in category for crit in CRITICAL_CATEGORIES)


def get_trusted_domains_file(classification: ClassificationResult) -> Path | None:
    """Resolve a trusted-domain allowlist file for a critical classification.

    Returns ``None`` when no trusted source list is configured for the
    category.
    """
    category = (classification.category or "").lower()
    for key, rel_path in TRUSTED_DOMAIN_FILES.items():
        if key in category:
            root = Path(__file__).resolve().parent.parent.parent.parent
            path = root / rel_path
            if path.exists():
                return path
    return None


def get_default_trusted_domains_file() -> Path | None:
    """Return the fallback trusted-domain allowlist file if it exists."""
    root = Path(__file__).resolve().parent.parent.parent.parent
    path = root / DEFAULT_TRUSTED_DOMAIN_FILE
    return path if path.exists() else None


def operator_blocked_outcome(
    decision: RoutingDecision,
    classification: ClassificationResult,
    start_time: float,
) -> RouterOutcome:
    """Return a clear ``operator_blocked`` outcome for a critical query.

    This helper is used across modules (``escalation`` and ``pipeline.route``),
    so it is public despite the earlier underscore prefix.
    """
    execution_time = int((time.time() - start_time) * 1000)
    logger.info(
        "critical_source_policy_blocked",
        extra={
            "route": decision.route,
            "category": classification.category,
        },
    )
    return RouterOutcome(
        status="completed",
        outcome_code="operator_blocked",
        route=decision.route,
        provider="local",
        provider_usage_class="local",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        response_text=(
            "This query requires trusted sources, which are not currently "
            "available for this category. Enable untrusted web sources or try "
            "a local-only query."
        ),
        execution_time_ms=execution_time,
        evidence_reason=decision.evidence_reason or classification.evidence_reason,
        policy_reason="trusted_sources_only_critical",
    )
