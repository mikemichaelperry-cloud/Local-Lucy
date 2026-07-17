#!/usr/bin/env python3
"""
Provider Resolver — single source of truth for provider selection.

Stage 8 of the Kimi Architecture Refactor.

All provider resolution lives here. No other module should:
- Read LUCY_AUGMENTED_PROVIDER env var
- Apply medical safety overrides
- Pick default providers based on query type

The pipeline calls resolve_provider() ONCE after routing and before
execution. ExecutionEngine trusts the RoutingDecision it receives.

Resolution rules (in order of precedence):
1. Route type is not augmentable (LOCAL, TIME, WEATHER, etc.) → no change
2. Medical context → wikipedia (safety hardcoded, cannot be overridden)
3. User preference from context['augmented_provider'] (HMI, CLI)
4. User preference from LUCY_AUGMENTED_PROVIDER env var
5. Query-type default (background → wikipedia, medical/financial → openai)
"""

from __future__ import annotations

import logging
import os
from typing import Any

from router_py.request_types import ClassificationResult, RoutingDecision
from router_py.policy import provider_usage_class_for

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults by query type
# ---------------------------------------------------------------------------


def _default_provider_for(classification: ClassificationResult) -> str:
    """Pick the best default provider based on query classification."""
    evidence_reason = classification.evidence_reason
    intent_family = classification.intent_family

    if evidence_reason == "medical_context":
        return "kimi"  # High-quality sources for medical
    if evidence_reason in ("financial_data", "legal_context"):
        return "kimi"  # Accurate, current info
    if evidence_reason == "conflict_live":
        return "kimi"  # Real-time web search
    if intent_family in ("background_overview", "current_evidence"):
        return "wikipedia"  # Free, reliable background
    return "kimi"  # General fallback


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def resolve_provider(
    classification: ClassificationResult,
    context: dict[str, Any] | None = None,
    prefer_paid: bool = False,
) -> str:
    """
    Resolve the final augmented provider name.

    Args:
        classification: The classified intent (for query-type defaults).
        context: Execution context. Checked for 'augmented_provider' key.
        prefer_paid: If True, default to openai regardless of query type.

    Returns:
        Provider name: "wikipedia", "openai", "kimi", "trusted", or "local".
    """
    # 1. Medical / veterinary safety override — hardcoded, cannot be bypassed.
    #    These route to domain-restricted trusted sources (medlineplus, pubmed,
    #    avma, merckvetmanual, etc.) instead of general Wikipedia.
    if classification.evidence_reason in ("medical_context", "medical_body_symptom"):
        logger.debug("Medical safety: forcing provider to trusted")
        return "trusted"
    if classification.evidence_reason == "veterinary_context":
        logger.debug("Veterinary safety: forcing provider to trusted")
        return "trusted"

    # 2. User preference from context (HMI, CLI, voice surfaces set this)
    if context:
        user_provider = context.get("augmented_provider", "").strip().lower()
        if user_provider in ("wikipedia", "openai", "kimi"):
            logger.debug(f"Provider from context preference: {user_provider}")
            return user_provider

    # 3. User preference from environment variable
    env_provider = os.environ.get("LUCY_AUGMENTED_PROVIDER", "").strip().lower()
    if env_provider in ("wikipedia", "openai", "kimi"):
        logger.debug(f"Provider from env var: {env_provider}")
        return env_provider

    # 4. Paid preference override
    if prefer_paid:
        logger.debug("Provider from prefer_paid: kimi")
        return "kimi"

    # 5. Query-type default
    default = _default_provider_for(classification)
    logger.debug(f"Provider from query-type default: {default}")
    return default


def apply_provider(
    decision: RoutingDecision,
    classification: ClassificationResult,
    context: dict[str, Any] | None = None,
    prefer_paid: bool = False,
) -> RoutingDecision:
    """
    Apply resolved provider to a RoutingDecision.

    Returns a NEW RoutingDecision (frozen dataclass safe).
    Non-augmentable routes are returned unchanged.
    """
    if decision.route not in ("AUGMENTED", "FULL", "EVIDENCE", "NEWS"):
        return decision

    provider = resolve_provider(classification, context, prefer_paid=prefer_paid)

    if provider == decision.provider:
        return decision

    logger.info(f"Provider resolution: {decision.provider} → {provider}")
    import dataclasses

    return dataclasses.replace(
        decision,
        provider=provider,
        provider_usage_class=provider_usage_class_for(provider),
    )
