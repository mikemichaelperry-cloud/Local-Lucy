#!/usr/bin/env python3
"""
Request Pipeline — Single choke point for classify → route → execute.

Stage 3 of the Kimi Architecture Refactor.

All surfaces (HMI, CLI, voice) should eventually call `process()` instead of
reimplementing classify/route/execute inline.

Responsibilities:
1. Classify intent
2. Select route (with policy + memory gate)
3. Centralize provider resolution
4. Build PipelineContext
5. Execute via ExecutionEngine
6. Convert ExecutionResult → RouterOutcome

NOT responsibilities (stays in main.py entry wrapper):
- Feedback detection
- Route prefix parsing
- Execution lock
- Post-execution telemetry / memory persistence
- Shell/parity fallback paths
"""

from __future__ import annotations

import dataclasses
import logging
import os
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
from router_py.request_types import (
    ClassificationResult,
    ExecutionResult,
    PipelineContext,
    RouterOutcome,
    RoutingDecision,
)

# ---------------------------------------------------------------------------
# Routing & classification
# ---------------------------------------------------------------------------
from router_py.classify import classify_intent, select_route
from router_py.policy import normalize_augmentation_policy, provider_usage_class_for

# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------
from router_py import provider_resolver

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
from router_py.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline choke point
# ---------------------------------------------------------------------------


def process(
    question: str,
    *,
    policy: str = "fallback_only",
    timeout: int = 130,
    surface: str = "cli",
    augmented_direct_once: bool = False,
    route_prefix: str = "",
    context: dict[str, Any] | None = None,
    classification: ClassificationResult | None = None,
    decision: RoutingDecision | None = None,
    model: str | None = None,
) -> tuple[RouterOutcome, ClassificationResult | None, RoutingDecision | None]:
    """
    Execute the full request pipeline: classify → route → execute.

    Args:
        question: The user's query text (prefixes already stripped by caller).
        policy: Augmentation policy.
        timeout: Request timeout in seconds.
        surface: Origin surface (cli, hmi, voice, api).
        augmented_direct_once: Force augmented route for this query.
        route_prefix: Pre-parsed route prefix (LOCAL, NEWS, etc.) or empty.
        context: Extra execution context from caller.

    Returns:
        Tuple of (RouterOutcome, ClassificationResult, RoutingDecision).
        ClassificationResult and RoutingDecision are returned so the caller
        can do post-processing (telemetry, memory, feedback attribution).

    When ``classification`` and ``decision`` are provided (e.g. parity mode),
    the pipeline skips classify/route and executes directly. This ensures
    parity comparisons use the exact same routing decision for both paths.
    """
    import time as _time

    _profiling = os.environ.get("LUCY_LATENCY_PROFILE", "").lower() in {"1", "true", "yes"}
    _profile: dict[str, int] = {}
    start_time = _time.time()

    # ------------------------------------------------------------------
    # 1. Classify (skipped if caller provides classification)
    # ------------------------------------------------------------------
    if classification is None:
        _t0 = _time.time()
        try:
            classification = classify_intent(question, surface=surface)
            if _profiling:
                _profile["classify_ms"] = int((_time.time() - _t0) * 1000)
        except Exception as exc:
            logger.exception("Classification failed")
            execution_time = int((_time.time() - start_time) * 1000)
            outcome = RouterOutcome(
                status="failed",
                outcome_code="classification_error",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                intent_family="unknown",
                confidence=0.0,
                error_message=f"Classification failed: {exc}",
                execution_time_ms=execution_time,
                evidence_reason="",
                policy_reason="classification_failed",
            )
            return outcome, None, None

    # ------------------------------------------------------------------
    # 2. Route (skipped if caller provides decision)
    # ------------------------------------------------------------------
    if decision is None:
        _t1 = _time.time()
        try:
            normalized_policy = normalize_augmentation_policy(policy)
            session_id = (context or {}).get(
                "session_id", os.environ.get("LUCY_SESSION_ID", "default")
            ) or "default"
            decision = select_route(
                classification, policy=normalized_policy, query=question, session_id=session_id
            )
            if _profiling:
                _profile["route_ms"] = int((_time.time() - _t1) * 1000)
        except Exception as exc:
            logger.exception("Routing failed")
            execution_time = int((_time.time() - start_time) * 1000)
            outcome = RouterOutcome(
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
            return outcome, classification, None

    # ------------------------------------------------------------------
    # 3. Apply overrides
    # ------------------------------------------------------------------

    # 3a. Route prefix override (e.g. "news: ..." → NEWS)
    if route_prefix and decision.route != route_prefix:
        decision = RoutingDecision(
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

    # 3b. Force augmented if requested
    if augmented_direct_once and decision.route == "LOCAL":
        env_provider = os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")
        decision = RoutingDecision(
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

    # 3c. Centralize provider resolution (single source of truth)
    _t2 = _time.time()
    decision = provider_resolver.apply_provider(decision, classification, context)
    if _profiling:
        _profile["provider_resolve_ms"] = int((_time.time() - _t2) * 1000)

    # ------------------------------------------------------------------
    # 4. Build PipelineContext
    # ------------------------------------------------------------------
    _t3 = _time.time()
    pipeline_ctx = PipelineContext.from_env(question=question, surface=surface)
    if context:
        # Merge caller-provided extras
        for key, value in context.items():
            if hasattr(pipeline_ctx, key):
                # Use object.__setattr__ because PipelineContext is frozen
                pipeline_ctx = dataclasses.replace(pipeline_ctx, **{key: value})
            else:
                pipeline_ctx = dataclasses.replace(
                    pipeline_ctx,
                    extras={**pipeline_ctx.extras, key: value},
                )

    # 4a. Override force_local from classification
    if classification.force_local:
        pipeline_ctx = dataclasses.replace(pipeline_ctx, force_local=True)

    if _profiling:
        _profile["context_build_ms"] = int((_time.time() - _t3) * 1000)

    # ------------------------------------------------------------------
    # 5. Execute
    # ------------------------------------------------------------------
    _t4 = _time.time()
    try:
        engine = ExecutionEngine(
            config={
                "timeout": timeout,
                "model": model or os.environ.get("LUCY_MODEL", "local-lucy-llama31"),
                "use_sqlite_state": True,
            }
        )

        exec_context = pipeline_ctx.to_dict()

        result = engine.execute(
            classification,
            decision,
            exec_context,
        )

    except Exception as exc:
        logger.exception("ExecutionEngine failed")
        execution_time = int((_time.time() - start_time) * 1000)
        if _profiling:
            _profile["execute_ms"] = int((_time.time() - _t4) * 1000)
            _profile["total_ms"] = execution_time
        outcome = RouterOutcome(
            status="failed",
            outcome_code="execution_error",
            route=decision.route,
            provider=decision.provider,
            provider_usage_class=decision.provider_usage_class,
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            error_message=str(exc),
            execution_time_ms=execution_time,
            metadata={"latency_profile": _profile} if _profiling else {},
            evidence_reason=decision.evidence_reason,
            policy_reason=decision.policy_reason,
        )
        return outcome, classification, decision

    if _profiling:
        _profile["execute_ms"] = int((_time.time() - _t4) * 1000)

    # ------------------------------------------------------------------
    # 6. Convert ExecutionResult → RouterOutcome
    # ------------------------------------------------------------------
    execution_time = int((_time.time() - start_time) * 1000)
    if _profiling:
        _profile["total_ms"] = execution_time
        _profile["overhead_ms"] = max(0, execution_time - _profile.get("execute_ms", 0))

    _meta = dict(result.metadata) if result.metadata else {}
    if _profiling:
        _meta["latency_profile"] = _profile

    outcome = RouterOutcome(
        status=result.status,
        outcome_code=result.outcome_code,
        route=result.route,
        provider=result.provider,
        provider_usage_class=result.provider_usage_class,
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        response_text=result.response_text,
        error_message=result.error_message,
        execution_time_ms=execution_time,
        metadata=_meta,
        evidence_reason=result.evidence_reason or decision.evidence_reason,
        policy_reason=result.policy_reason or decision.policy_reason,
    )

    return outcome, classification, decision
