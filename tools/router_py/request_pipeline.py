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
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

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
from router_py.core.medical_query_heuristics import detect_human_medication_query
from router_py.policy import normalize_augmentation_policy, provider_usage_class_for
from router_py.request_constraints import RequestConstraints

# ---------------------------------------------------------------------------
# Provider resolution
# ---------------------------------------------------------------------------
from router_py import provider_resolver

# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
from router_py.execution_engine import ExecutionEngine, extract_self_analysis_file_reference

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Self-analysis pre-check (must run before Gemma 4 smart-routing bypass)
# ---------------------------------------------------------------------------


def _self_analysis_state_path() -> Path:
    """Resolve current_state.json using the active runtime namespace."""
    namespace = os.environ.get(
        "LUCY_RUNTIME_NAMESPACE_ROOT",
        str(lucy_runtime_namespace_root()),
    )
    return Path(namespace) / "state" / "current_state.json"


def _self_analysis_mode_enabled() -> bool:
    """Return True if Engineering / self-analysis mode is on in state."""
    try:
        state = json.loads(_self_analysis_state_path().read_text(encoding="utf-8"))
        return str(state.get("self_analysis_mode", "off")).lower() == "on"
    except Exception:
        return False


def _self_analysis_file_reference(question: str) -> str | None:
    """Return a file reference if the question is a self-analysis request."""
    if not _self_analysis_mode_enabled():
        return None
    return extract_self_analysis_file_reference(question)


# ---------------------------------------------------------------------------
# Gemma 4 smart-routing helpers
# ---------------------------------------------------------------------------

_NEWS_RE = re.compile(r"\b(news|headlines|latest|breaking)\b", re.IGNORECASE)
_EVIDENCE_RE = re.compile(r"\b(research|study|evidence|paper|source|according to)\b", re.IGNORECASE)


def _is_gemma4_smart_routing_enabled(model: str) -> bool:
    """Return True if Gemma 4 smart routing is enabled for the given model."""
    if not model:
        return False
    name = model.lower()
    if not (name.startswith("gemma4") or name.startswith("local-lucy-gemma4")):
        return False
    return os.environ.get("LUCY_GEMMA4_SMART_ROUTING", "").lower() in ("1", "true", "on")


def _gemma4_bypass_decision(question: str) -> tuple[ClassificationResult, RoutingDecision]:
    """Create minimal classification + LOCAL routing decision for Gemma 4 bypass."""
    classification = ClassificationResult(
        intent="general",
        intent_family="general",
        intent_class="general",
        confidence=1.0,
        force_local=True,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="SMART",
        intent_family="general",
        confidence=1.0,
        provider="local",
        provider_usage_class="local",
        evidence_mode="none",
        policy_reason="gemma4_smart_routing",
    )
    return classification, decision


# ---------------------------------------------------------------------------
# Legacy shell-bypass env-var support (LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE)
# ---------------------------------------------------------------------------


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "on", "yes")


def _forced_route_from_env(question: str) -> str | None:
    """Return the route forced by LUCY_CHAT_FORCE_MODE, or None if not bypassed."""
    if not _is_truthy_env("LUCY_ROUTER_BYPASS"):
        return None
    forced = os.environ.get("LUCY_CHAT_FORCE_MODE", "").strip().upper()
    if forced in (
        "LOCAL",
        "NEWS",
        "EVIDENCE",
        "AUGMENTED",
        "FULL",
        "TIME",
        "WEATHER",
        "FINANCE",
        "CLARIFY",
    ):
        return forced
    # Infer from query when bypass is requested without an explicit mode.
    q = (question or "").lower()
    if re.search(r"\b(news|headlines|latest news|breaking news)\b", q):
        return "NEWS"
    return None


def _bypass_classification_decision(
    question: str, route: str
) -> tuple[ClassificationResult, RoutingDecision]:
    """Create classification + routing decision for a bypass/forced route."""
    q = (question or "").lower()
    route_providers = {
        "LOCAL": "local",
        "NEWS": "news",
        "EVIDENCE": "trusted",
        "AUGMENTED": os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia").strip().lower()
        or "wikipedia",
        "FULL": os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia").strip().lower()
        or "wikipedia",
        "TIME": "time",
        "WEATHER": "weather",
        "FINANCE": "finance",
        "CLARIFY": "local",
    }
    provider = route_providers.get(route, "local")

    if route == "NEWS":
        intent_family = "current_fact"
        evidence_reason = "news_query"
    elif route in ("WEATHER",):
        intent_family = "current_fact"
        evidence_reason = "weather_query"
    elif route in ("TIME",):
        intent_family = "current_fact"
        evidence_reason = "time_query"
    elif route == "FINANCE":
        intent_family = "current_fact"
        evidence_reason = "financial_data"
    elif route == "EVIDENCE":
        med_detector = detect_human_medication_query(q)
        if med_detector.get("detector_fired") or re.search(
            r"\b(medical|medication|medicine|drug|dose|dosage|side effect|interaction|contraindication)\b",
            q,
        ):
            intent_family = "evidence_check"
            evidence_reason = "medical_context"
        elif re.search(r"\b(stock|finance|currency|exchange rate|market|economy)\b", q):
            intent_family = "current_fact"
            evidence_reason = "financial_data"
        else:
            intent_family = "evidence_check"
            evidence_reason = "source_request"
    elif route == "AUGMENTED":
        intent_family = "background_overview"
        evidence_reason = "source_request"
    elif route == "FULL":
        intent_family = "background_overview"
        evidence_reason = "source_request"
    else:
        intent_family = "local_knowledge"
        evidence_reason = ""

    classification = ClassificationResult(
        intent=intent_family,
        intent_family=intent_family,
        intent_class="bypass",
        confidence=1.0,
        evidence_reason=evidence_reason,
        needs_web=route not in ("LOCAL", "CLARIFY"),
    )
    decision = RoutingDecision(
        route=route,
        mode="FORCED",
        intent_family=intent_family,
        confidence=1.0,
        provider=provider,
        provider_usage_class=provider_usage_class_for(provider),
        evidence_mode="required" if route not in ("LOCAL", "CLARIFY") else "",
        evidence_reason=evidence_reason,
        requires_evidence=route not in ("LOCAL", "CLARIFY"),
        policy_reason="env_bypass",
        decision_stage="env_override",
        reason_code="LUCY_ROUTER_BYPASS",
    )
    return classification, decision


def _looks_like_news(query: str) -> bool:
    return bool(_NEWS_RE.search(query))


def _looks_like_evidence(query: str) -> bool:
    return bool(_EVIDENCE_RE.search(query))


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
    # 0. Environment bypass (LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE)
    # ------------------------------------------------------------------
    forced_route = _forced_route_from_env(question)
    if forced_route:
        classification, decision = _bypass_classification_decision(question, forced_route)
    else:
        # ------------------------------------------------------------------
        # 0b. Gemma 4 smart-routing bypass
        # ------------------------------------------------------------------
        active_model = (
            model or os.environ.get("LUCY_MODEL", "") or os.environ.get("LUCY_LOCAL_MODEL", "")
        )
        # Engineering / self-analysis mode must not be bypassed, even by smart routing.
        _self_analysis_ref = _self_analysis_file_reference(question)
        if (
            classification is None
            and decision is None
            and _is_gemma4_smart_routing_enabled(active_model)
            and not route_prefix
            and _self_analysis_ref is None
        ):
            if _looks_like_news(question):
                route_prefix = "NEWS"
            elif _looks_like_evidence(question):
                route_prefix = "EVIDENCE"
            else:
                classification, decision = _gemma4_bypass_decision(question)

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

    # 3d. Request-scoped capability constraints (override operator settings)
    constraints = (context or {}).get("request_constraints")
    if isinstance(constraints, RequestConstraints):
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
            # Fall back to LOCAL so the model can answer from parametric/local
            # context rather than returning a generic denial.
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
                policy_reason="request_constraint_network_denied",
                decision_stage="operator_fallback",
                reason_code="request_constraint_network_denied",
            )
        elif constraints.tools is False and decision.route in tool_routes:
            logger.info(
                "request_constraint_blocks_tools",
                extra={
                    "route": decision.route,
                    "request_id": (context or {}).get("request_id", ""),
                },
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
                policy_reason="request_constraint_tools_denied",
                decision_stage="operator_fallback",
                reason_code="request_constraint_tools_denied",
            )

    # 3e. Evidence-disabled operator gate
    evidence_enabled = os.environ.get(
        "LUCY_EVIDENCE_ENABLED", os.environ.get("LUCY_ENABLE_INTERNET", "0")
    ).strip().lower() in ("1", "true", "on", "yes")
    if not evidence_enabled and decision.route in ("NEWS", "EVIDENCE"):
        execution_time = int((_time.time() - start_time) * 1000)
        logger.info("evidence_disabled_gate", extra={"route": decision.route})
        return (
            RouterOutcome(
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
            ),
            classification,
            decision,
        )

    if not evidence_enabled and decision.route in (
        "AUGMENTED",
        "FULL",
        "WEATHER",
        "TIME",
        "FINANCE",
    ):
        # These routes can be answered from local parametric knowledge when
        # external data is disabled. Degrade to LOCAL instead of blocking.
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
