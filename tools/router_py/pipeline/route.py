#!/usr/bin/env python3
"""Route selection and policy normalization for the request pipeline.

This module holds the routing step that used to live inline in
``request_pipeline.process()``. It is responsible for:

* Calling ``select_route`` with the normalized augmentation policy
* Applying route-prefix overrides
* Applying ``augmented_direct_once`` overrides
* Centralized provider resolution
* Request-scoped capability constraints
* The evidence-disabled operator gate
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

from router_py.request_types import (
    ClassificationResult,
    RouterOutcome,
    RoutingDecision,
)
from router_py.classify import select_route
from router_py.policy import (
    normalize_augmentation_policy,
    provider_usage_class_for,
)
from router_py.request_constraints import RequestConstraints
from router_py import provider_resolver

logger = logging.getLogger(__name__)


def _apply_route_prefix_override(
    decision: RoutingDecision, route_prefix: str
) -> RoutingDecision:
    """Override the selected route when the caller supplies a route prefix."""
    if not route_prefix or decision.route == route_prefix:
        return decision
    return RoutingDecision(
        route=route_prefix,
        mode="FORCED",
        intent_family=decision.intent_family,
        confidence=decision.confidence,
        provider=decision.provider,
        provider_usage_class=decision.provider_usage_class,
        evidence_mode=decision.evidence_mode,
        evidence_reason=decision.evidence_reason,
        requires_evidence=decision.requires_evidence,
        policy_reason=f"prefix_override_{route_prefix.lower()}",
        ephemeral=decision.ephemeral,
    )


def _apply_augmented_direct_once(
    decision: RoutingDecision, augmented_direct_once: bool
) -> RoutingDecision:
    """Force an otherwise LOCAL decision onto the AUGMENTED route."""
    if not augmented_direct_once or decision.route != "LOCAL":
        return decision
    env_provider = os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")
    return RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family=decision.intent_family,
        confidence=decision.confidence,
        provider=env_provider,
        provider_usage_class=provider_usage_class_for(env_provider),
        evidence_mode="required",
        evidence_reason="source_request",
        requires_evidence=True,
        policy_reason="augmented_direct_once",
        ephemeral=decision.ephemeral,
    )


def _apply_request_constraints(
    decision: RoutingDecision,
    classification: ClassificationResult,
    context: dict[str, Any] | None,
) -> RoutingDecision:
    """Apply request-scoped capability constraints, overriding operator settings."""
    constraints = (context or {}).get("request_constraints")
    if not isinstance(constraints, RequestConstraints):
        return decision

    network_routes = {"NEWS", "EVIDENCE", "AUGMENTED", "FULL"}
    tool_routes = {"TIME", "WEATHER", "FINANCE"}

    if constraints.network is False and decision.route in network_routes:
        logger.info(
            "request_constraint_blocks_network",
            extra={
                "route": decision.route,
                "request_id": (context or {}).get("request_id", ""),
            },
        )
        return dataclasses.replace(
            decision,
            route="LOCAL",
            mode="FALLBACK",
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
            evidence_reason="",
            requires_evidence=False,
            ephemeral=False,
            policy_reason="request_constraint_network_denied",
            decision_stage="operator_fallback",
            reason_code="request_constraint_network_denied",
        )

    if constraints.tools is False and decision.route in tool_routes:
        logger.info(
            "request_constraint_blocks_tools",
            extra={
                "route": decision.route,
                "request_id": (context or {}).get("request_id", ""),
            },
        )
        return dataclasses.replace(
            decision,
            route="LOCAL",
            mode="FALLBACK",
            provider="local",
            provider_usage_class="local",
            evidence_mode="",
            evidence_reason="",
            requires_evidence=False,
            ephemeral=False,
            policy_reason="request_constraint_tools_denied",
            decision_stage="operator_fallback",
            reason_code="request_constraint_tools_denied",
        )

    return decision


def normalize_decision(
    decision: RoutingDecision,
    *,
    classification: ClassificationResult,
    question: str,
    context: dict[str, Any] | None,
    route_prefix: str,
    augmented_direct_once: bool,
) -> RoutingDecision:
    """
    Apply all route-normalization steps to a preliminary decision.

    This runs unconditionally in the facade on every decision, whether it came
    from the embedding router, an env bypass, or Gemma 4 smart-routing bypass.
    Normalization steps (in order):

    1. Caller-supplied route prefix override.
    2. Explicit one-shot ``augmented_direct_once`` override.
    3. Centralized provider resolution.
    4. Request-scoped capability constraints.

    Args:
        decision: Preliminary routing decision.
        classification: The classified intent.
        question: The user's query text.
        context: Extra execution context from caller.
        route_prefix: Pre-parsed route prefix or empty string.
        augmented_direct_once: Force augmented route for this query.

    Returns:
        Normalized ``RoutingDecision``.
    """
    # Caller-supplied route prefix takes precedence.
    decision = _apply_route_prefix_override(decision, route_prefix)

    # Explicit one-shot augmented override.
    decision = _apply_augmented_direct_once(decision, augmented_direct_once)

    # Centralized provider resolution (single source of truth).
    decision = provider_resolver.apply_provider(decision, classification, context)

    # Request-scoped capability constraints (override operator settings).
    decision = _apply_request_constraints(decision, classification, context)

    return decision


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
