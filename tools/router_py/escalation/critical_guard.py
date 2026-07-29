#!/usr/bin/env python3
"""Critical-category guard for web-fetch escalation.

Blocks automatic web fetching for sensitive topics regardless of capability
flags. The category list is shared with the escalation suggestion logic so
policy stays consistent.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from pathlib import Path
from typing import Any

from router_py.escalation.config import CRITICAL_CATEGORIES
from router_py.pipeline.config import load_capability_flags
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
}


def is_critical_category(classification: ClassificationResult) -> bool:
    """Return True when the classification is in a critical category.

    Critical categories include medical, financial, legal, safety, identity,
    and related regulatory/market/travel topics. Web search must not be
    performed automatically for these.
    """
    category = (classification.category or "").lower()
    return any(crit in category for crit in CRITICAL_CATEGORIES)


def _trusted_domains_file_for(classification: ClassificationResult) -> Path | None:
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


def _operator_blocked_outcome(
    decision: RoutingDecision,
    classification: ClassificationResult,
    start_time: float,
) -> RouterOutcome:
    """Return a clear ``operator_blocked`` outcome for a critical query."""
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


def apply_critical_source_policy(
    decision: RoutingDecision,
    classification: ClassificationResult,
    context: dict[str, Any] | None = None,
) -> RoutingDecision | RouterOutcome:
    """
    Enforce trusted-sources-only policy for critical categories.

    When the ``trusted_sources_only_critical`` capability flag is enabled and
    the classification is in a critical category (medical, financial, legal,
    safety, identity, etc.), web routes are restricted as follows:

    * NEWS → converted to EVIDENCE and restricted to trusted sources.
    * AUGMENTED → provider forced to ``trusted`` and evidence required.
    * EVIDENCE → provider forced to ``trusted`` if it was not already.
    * LOCAL → unchanged.

    If no trusted source list is configured for the category, an
    ``operator_blocked`` outcome is returned instead of allowing untrusted web
    sources.

    Args:
        decision: Normalized routing decision.
        classification: The classified intent.
        context: Optional execution context. When provided and a trusted
            allowlist exists, ``context["allow_domains_file"]`` is set to the
            trusted list path.

    Returns:
        An updated ``RoutingDecision`` on success, or a ``RouterOutcome`` with
        ``outcome_code="operator_blocked"`` when no trusted source is
        available.
    """
    start_time = time.time()
    flags = load_capability_flags()

    if not flags.trusted_sources_only_critical:
        return decision

    if not is_critical_category(classification):
        return decision

    # Determine whether a configured trusted source list exists.
    trusted_file = _trusted_domains_file_for(classification)
    has_trusted_source = decision.provider == "trusted" or trusted_file is not None

    if context is not None and trusted_file is not None:
        context["allow_domains_file"] = str(trusted_file)

    # Routes that do not use external web sources are unaffected.
    if decision.route in ("LOCAL", "CLARIFY", "SELF_REVIEW", "MEMORY_RECALL"):
        return decision

    if not has_trusted_source:
        return _operator_blocked_outcome(decision, classification, start_time)

    if decision.route == "NEWS":
        # Untrusted web news is not acceptable for critical categories; require
        # evidence from trusted domains instead.
        logger.info(
            "critical_source_policy_news_to_evidence",
            extra={"category": classification.category},
        )
        return dataclasses.replace(
            decision,
            route="EVIDENCE",
            provider="trusted",
            provider_usage_class="free",
            evidence_mode="required",
            evidence_reason=classification.evidence_reason
            or decision.evidence_reason
            or "trusted_source_required",
            requires_evidence=True,
            policy_reason="critical_trusted_sources_only",
            reason_code="news_to_evidence_trusted",
        )

    if decision.route == "AUGMENTED":
        logger.info(
            "critical_source_policy_augmented_to_trusted",
            extra={"category": classification.category},
        )
        return dataclasses.replace(
            decision,
            provider="trusted",
            provider_usage_class="free",
            evidence_mode="required",
            evidence_reason=classification.evidence_reason
            or decision.evidence_reason
            or "trusted_source_required",
            requires_evidence=True,
            policy_reason="critical_trusted_sources_only",
            reason_code="augmented_to_trusted",
        )

    if decision.route == "EVIDENCE":
        # Keep the EVIDENCE route but make sure the provider is trusted.
        if decision.provider == "trusted":
            return decision
        logger.info(
            "critical_source_policy_evidence_to_trusted",
            extra={"category": classification.category},
        )
        return dataclasses.replace(
            decision,
            provider="trusted",
            provider_usage_class="free",
            policy_reason="critical_trusted_sources_only",
            reason_code="evidence_trusted_provider",
        )

    # For any other route, fall back to trusted provider when web is involved.
    if decision.provider != "trusted":
        logger.info(
            "critical_source_policy_fallback_to_trusted",
            extra={"route": decision.route, "category": classification.category},
        )
        return dataclasses.replace(
            decision,
            provider="trusted",
            provider_usage_class="free",
            policy_reason="critical_trusted_sources_only",
            reason_code="route_to_trusted",
        )

    return decision
