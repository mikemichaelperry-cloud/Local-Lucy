#!/usr/bin/env python3
"""Provider resolution and route normalization for the request pipeline.

This module holds the normalization step that used to live inline in
``request_pipeline.process()``. It is responsible for:

* Caller-supplied route-prefix override
* One-shot ``augmented_direct_once`` override
* Centralized provider resolution via ``provider_resolver.apply_provider``
* Request-scoped capability constraints

All normalization runs unconditionally on every preliminary decision,
whether it came from the embedding router, an env bypass, or Gemma 4
smart-routing bypass.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import ClassificationResult, RoutingDecision
from router_py.policy import provider_usage_class_for
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


def resolve_provider(
    decision: RoutingDecision,
    classification: ClassificationResult,
    context: dict[str, Any] | None,
    *,
    route_prefix: str = "",
    augmented_direct_once: bool = False,
) -> RoutingDecision:
    """
    Apply all route-normalization steps to a preliminary decision.

    This runs unconditionally on every decision, whether it came from the
    embedding router, an env bypass, or Gemma 4 smart-routing bypass.
    Normalization steps (in order):

    1. Caller-supplied route prefix override.
    2. Explicit one-shot ``augmented_direct_once`` override.
    3. Centralized provider resolution.
    4. Request-scoped capability constraints.

    Args:
        decision: Preliminary routing decision.
        classification: The classified intent.
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
