#!/usr/bin/env python3
"""Route selection and evidence-disabled operator gate for the request pipeline.

This module holds the routing step that used to live inline in
``request_pipeline.process()``. It is responsible for:

* Calling ``select_route`` with the normalized augmentation policy
* Returning routing errors as ``RouterOutcome``
* The evidence-disabled operator gate

Route normalization (route prefix, ``augmented_direct_once``, provider
resolution, and request-scoped capability constraints) lives in
``pipeline.resolve_provider`` and is applied by the facade after this step.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import ClassificationResult, RouterOutcome, RoutingDecision
from router_py.classify import select_route
from router_py.escalation.critical_guard import (
    _operator_blocked_outcome,
    get_default_trusted_domains_file,
    get_trusted_domains_file,
    is_critical_category,
)
from router_py.pipeline.config import load_capability_flags
from router_py.policy import normalize_augmentation_policy

logger = logging.getLogger(__name__)


def select_route_for_question(
    classification: ClassificationResult,
    question: str,
    policy: str,
    context: dict[str, Any] | None,
) -> RoutingDecision | RouterOutcome:
    """
    Select the raw route for a classified question.

    Normalization (route prefix, augmented_direct_once, provider resolution,
    request constraints) is intentionally applied by the facade so that bypass
    decisions receive the same treatment as router-produced decisions.

    Args:
        classification: The classified intent.
        question: The user's query text.
        policy: Augmentation policy name (e.g. ``fallback_only``).
        context: Extra execution context from caller.

    Returns:
        A raw ``RoutingDecision`` on success, or a ``RouterOutcome`` when
        routing itself raises an exception.
    """
    import time as _time

    start_time = _time.time()

    try:
        normalized_policy = normalize_augmentation_policy(policy)
        session_id = (context or {}).get(
            "session_id", os.environ.get("LUCY_SESSION_ID", "default")
        ) or "default"
        decision = select_route(
            classification, policy=normalized_policy, query=question, session_id=session_id
        )
    except Exception as exc:
        logger.exception("Routing failed")
        execution_time = int((_time.time() - start_time) * 1000)
        return RouterOutcome(
            status="failed",
            outcome_code="routing_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            error_message=f"Routing failed: {exc}",
            execution_time_ms=execution_time,
            evidence_reason=classification.evidence_reason,
            policy_reason="routing_failed",
        )

    return decision


def apply_critical_source_policy(
    decision: RoutingDecision,
    classification: ClassificationResult,
    context: dict[str, Any] | None = None,
    *,
    start_time: float | None = None,
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
        start_time: Pipeline start time used for blocked-outcome timing. When
            omitted, the current time is used (primarily for unit tests).

    Returns:
        An updated ``RoutingDecision`` on success, or a ``RouterOutcome`` with
        ``outcome_code="operator_blocked"`` when no trusted source is
        available.
    """
    policy_start = start_time if start_time is not None else time.time()
    flags = load_capability_flags()

    if not flags.trusted_sources_only_critical:
        return decision

    if not is_critical_category(classification):
        return decision

    # Determine whether a configured trusted source list exists.
    trusted_file = get_trusted_domains_file(classification)
    has_pre_trusted_provider = decision.provider == "trusted"
    has_trusted_source = has_pre_trusted_provider or trusted_file is not None

    # When a trusted source list is available, surface it to downstream
    # tooling. For EVIDENCE routes that already have a trusted provider but no
    # category-specific allowlist, fall back to the default trusted list so
    # the allow_domains_file context is always populated for critical web
    # handling.
    if context is not None and decision.route not in (
        "LOCAL",
        "CLARIFY",
        "SELF_REVIEW",
        "MEMORY_RECALL",
    ):
        if trusted_file is not None:
            context["allow_domains_file"] = str(trusted_file)
        elif decision.route == "EVIDENCE" and has_pre_trusted_provider:
            default_file = get_default_trusted_domains_file()
            if default_file is not None:
                context["allow_domains_file"] = str(default_file)

    # Routes that do not use external web sources are unaffected.
    if decision.route in ("LOCAL", "CLARIFY", "SELF_REVIEW", "MEMORY_RECALL"):
        return decision

    if not has_trusted_source:
        return _operator_blocked_outcome(decision, classification, policy_start)

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


def apply_evidence_disabled_gate(
    decision: RoutingDecision,
    classification: ClassificationResult,
    start_time: float,
) -> tuple[RouterOutcome | None, RoutingDecision]:
    """
    Enforce the evidence-disabled operator gate.

    When evidence is disabled:
    * NEWS and EVIDENCE routes are blocked and return an operator message.
    * AUGMENTED, FULL, TIME, WEATHER, and FINANCE routes degrade to LOCAL.

    Returns:
        ``(outcome, decision)``. If ``outcome`` is not None the caller must
        return it immediately; otherwise ``decision`` may have been updated.
    """
    evidence_enabled = os.environ.get(
        "LUCY_EVIDENCE_ENABLED", os.environ.get("LUCY_ENABLE_INTERNET", "0")
    ).strip().lower() in ("1", "true", "on", "yes")

    if not evidence_enabled and decision.route in ("NEWS", "EVIDENCE"):
        execution_time = int((time.time() - start_time) * 1000)
        logger.info("evidence_disabled_gate", extra={"route": decision.route})
        outcome = RouterOutcome(
            status="completed",
            outcome_code="operator_blocked",
            route=decision.route,
            provider="local",
            provider_usage_class="local",
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            response_text=(
                "Evidence disabled by operator control.\nEnable evidence to allow news routes."
            ),
            execution_time_ms=execution_time,
            evidence_reason=decision.evidence_reason,
            policy_reason="evidence_disabled",
        )
        return outcome, decision

    if not evidence_enabled and decision.route in (
        "AUGMENTED",
        "FULL",
        "WEATHER",
        "TIME",
        "FINANCE",
    ):
        logger.info(
            "evidence_disabled_local_fallback",
            extra={"original_route": decision.route},
        )
        decision = dataclasses.replace(
            decision,
            route="LOCAL",
            mode="FALLBACK",
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
            evidence_reason="",
            requires_evidence=False,
            ephemeral=False,
            policy_reason=f"evidence_disabled_fallback_from_{decision.route.lower()}",
            decision_stage="operator_fallback",
            reason_code="evidence_disabled_local_fallback",
        )

    return None, decision
