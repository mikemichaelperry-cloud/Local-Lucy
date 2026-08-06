#!/usr/bin/env python3
"""Request Pipeline — thin facade for classify → route → execute.

Stage 3 of the Kimi Architecture Refactor.

All surfaces (HMI, CLI, voice) should eventually call `process()` instead of
reimplementing classify/route/execute inline.

This module is a thin orchestration facade. The actual work is delegated to
sub-modules under ``router_py.pipeline``:

* ``pipeline.classify`` — intent classification and smart-routing bypass
* ``pipeline.route`` — raw route selection and evidence-disabled gate
* ``pipeline.resolve_provider`` — route normalization and provider resolution
* ``pipeline.build_context`` — ``PipelineContext`` assembly
* ``pipeline.execute`` — ``ExecutionEngine`` invocation
* ``pipeline.outcome`` — ``ExecutionResult`` → ``RouterOutcome`` conversion

NOT responsibilities (stays in main.py entry wrapper):
- Feedback detection
- Route prefix parsing
- Execution lock
- Post-execution telemetry / memory persistence
- Shell/parity fallback paths
"""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------
from router_py.request_types import (
    ClassificationResult,
    RouterOutcome,
    RoutingDecision,
)

# ---------------------------------------------------------------------------
# Pipeline sub-modules
# ---------------------------------------------------------------------------
from router_py.pipeline import classify
from router_py.pipeline import route
from router_py.pipeline import resolve_provider
from router_py.pipeline import build_context
from router_py.pipeline import execute
from router_py.pipeline import outcome
from router_py.pipeline.config import load_capability_flags
from router_py.policy import normalize_augmentation_policy
from router_py.escalation import fetcher
from router_py.escalation.config import THIN_LOCAL_CONFIDENCE_THRESHOLD
from router_py.privacy import redact_untrusted_log_source

# Re-export for tests/code that patch the pipeline's classifier reference.
classify_intent = classify.classify_intent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight diagnostic trace (disabled by default)
# ---------------------------------------------------------------------------


def _diagnostics_enabled() -> bool:
    return os.environ.get("LUCY_ROUTER_DIAGNOSTICS", "").lower() in {"1", "true", "yes"}


def _diagnostics_path() -> Path:
    path = os.environ.get("LUCY_ROUTER_DIAGNOSTICS_PATH", "")
    if path:
        return Path(path)
    root = Path(__file__).resolve().parent.parent.parent
    return root / "qualification" / "router_diagnostics.jsonl"


def _write_router_diagnostic_trace(
    *,
    request_id: str,
    original_query: str,
    resolved_query: str,
    classification: ClassificationResult | None,
    pre_guard_decision: RoutingDecision | None,
    final_decision: RoutingDecision,
    flags,
    outcome_code: str,
) -> None:
    """Write a structured routing-trace entry when diagnostics are enabled."""
    if not _diagnostics_enabled():
        return

    raw_plan = classification.raw_plan if classification else {}
    if not isinstance(raw_plan, dict):
        raw_plan = {}

    candidate_routes = raw_plan.get("candidate_routes") or []
    if not candidate_routes and classification and classification.selected_route:
        candidate_routes = [classification.selected_route]

    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "request_id": request_id,
        "original_query": original_query,
        "resolved_query": resolved_query or original_query,
        "classifier_intent": classification.intent if classification else "",
        "classifier_confidence": classification.confidence if classification else 0.0,
        "classifier_intent_family": classification.intent_family if classification else "",
        "candidate_routes": candidate_routes,
        "pre_guard_route": pre_guard_decision.route if pre_guard_decision else "",
        "pre_guard_provider": pre_guard_decision.provider if pre_guard_decision else "",
        "final_route": final_decision.route,
        "final_provider": final_decision.provider,
        "execution_provider": final_decision.provider,
        "evidence_policy": final_decision.evidence_mode or "none",
        "evidence_reason": final_decision.evidence_reason or "",
        "policy_reason": final_decision.policy_reason or "",
        "reason_code": final_decision.reason_code or "",
        "matched_rule": final_decision.matched_rule or "",
        "capability_flags": {
            "source_attribution": flags.source_attribution,
            "suggest_web_escalation": flags.suggest_web_escalation,
            "auto_web_general_knowledge": flags.auto_web_general_knowledge,
            "trusted_sources_only_critical": flags.trusted_sources_only_critical,
        },
        "outcome_code": outcome_code,
    }

    try:
        path = _diagnostics_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
    except Exception as exc:
        logger.debug("router_diagnostic_trace_failed", exc_info=True)


# ---------------------------------------------------------------------------
# Backward-compatible re-exports
# ---------------------------------------------------------------------------
# These private helpers were originally defined inline in this module and are
# imported by existing tests. Re-exporting them keeps those imports working
# while the implementations live in pipeline/classify.py.
_self_analysis_state_path = classify._self_analysis_state_path
_self_analysis_mode_enabled = classify._self_analysis_mode_enabled
_self_analysis_file_reference = classify._self_analysis_file_reference
_is_gemma4_smart_routing_enabled = classify._is_gemma4_smart_routing_enabled
_gemma4_bypass_decision = classify._gemma4_bypass_decision
_forced_route_from_env = classify._forced_route_from_env
_bypass_classification_decision = classify._bypass_classification_decision
_looks_like_news = classify._looks_like_news
_looks_like_evidence = classify._looks_like_evidence


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

    # Load capability flags once per request; attribution/escalation logic
    # reads this instead of re-loading config from disk.
    _capability_flags = load_capability_flags()

    # Remember whether the caller supplied both classification and decision.
    # In parity/comparison mode we preserve the exact routing decision and
    # skip the request-scoped critical-source policy modification.
    _caller_supplied_both = classification is not None and decision is not None
    _pre_guard_decision: RoutingDecision | None = decision

    # ------------------------------------------------------------------
    # 0. Environment bypass (LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE)
    # ------------------------------------------------------------------
    forced_route = classify._forced_route_from_env(question)
    if forced_route:
        classification, decision = classify._bypass_classification_decision(question, forced_route)
    else:
        # ------------------------------------------------------------------
        # 1. Classify (skipped if caller provides classification)
        # ------------------------------------------------------------------
        if classification is None:
            _t0 = _time.time()
            classify_result, route_prefix, bypass_decision = classify.classify_question(
                question,
                surface=surface,
                model=model,
                route_prefix=route_prefix,
                context=context,
            )
            if isinstance(classify_result, RouterOutcome):
                return classify_result, None, None
            classification = classify_result
            if bypass_decision is not None:
                decision = bypass_decision
            if _profiling:
                _profile["classify_ms"] = int((_time.time() - _t0) * 1000)

        # ------------------------------------------------------------------
        # 2. Route (skipped if caller provides decision)
        # ------------------------------------------------------------------
        if decision is None:
            _t1 = _time.time()
            route_result = route.select_route_for_question(
                classification,
                question=question,
                policy=policy,
                context=context,
            )
            if isinstance(route_result, RouterOutcome):
                return route_result, classification, None
            decision = route_result
            if _profiling:
                _profile["route_ms"] = int((_time.time() - _t1) * 1000)

    # Capture route before provider resolution / policy gates for diagnostics.
    _pre_guard_decision = decision

    # ------------------------------------------------------------------
    # 3. Normalize decision — applies to router, bypass, and smart-routing
    #    decisions so route_prefix, augmented_direct_once, provider resolution,
    #    and request constraints always run unconditionally.
    # ------------------------------------------------------------------
    _t2 = _time.time()
    decision = resolve_provider.resolve_provider(
        decision,
        classification,
        context,
        route_prefix=route_prefix,
        augmented_direct_once=augmented_direct_once,
    )
    if _profiling:
        _profile["provider_resolve_ms"] = int((_time.time() - _t2) * 1000)

    # ------------------------------------------------------------------
    # 4. Critical-category trusted-source policy
    # ------------------------------------------------------------------
    # Skip the policy when the caller already provided both classification and
    # decision (parity mode), so comparison runs use the exact same decision.
    if not _caller_supplied_both:
        policy_result = route.apply_critical_source_policy(
            decision, classification, context, flags=_capability_flags, start_time=start_time
        )
        if isinstance(policy_result, RouterOutcome):
            return policy_result, classification, decision
        decision = policy_result

    # ------------------------------------------------------------------
    # 5. Evidence-disabled operator gate
    # ------------------------------------------------------------------
    gate_outcome, decision = route.apply_evidence_disabled_gate(
        decision, classification, start_time
    )
    if gate_outcome is not None:
        return gate_outcome, classification, decision

    # ------------------------------------------------------------------
    # 6. Build PipelineContext
    # ------------------------------------------------------------------
    _t3 = _time.time()
    pipeline_ctx = build_context.build_pipeline_context(question, surface, context, classification)
    if _profiling:
        _profile["context_build_ms"] = int((_time.time() - _t3) * 1000)

    # ------------------------------------------------------------------
    # 7. Execute
    # ------------------------------------------------------------------
    _t4 = _time.time()
    result = execute.execute_request(
        classification,
        decision,
        pipeline_ctx,
        model,
        timeout,
    )
    if _profiling:
        _profile["execute_ms"] = int((_time.time() - _t4) * 1000)

    # ------------------------------------------------------------------
    # 8. Convert ExecutionResult → RouterOutcome
    # ------------------------------------------------------------------
    router_outcome = outcome.build_outcome(
        result,
        classification,
        decision,
        start_time,
        _profile if _profiling else None,
        flags=_capability_flags,
    )

    # ------------------------------------------------------------------
    # 9. Optional general-knowledge web fetch (conservative expansion)
    # ------------------------------------------------------------------
    # Only run when the capability flag is enabled and the answer attribution is
    # thin. The fetcher performs its own critical-category guard (defense in
    # depth). Fetched sources are explicitly labelled untrusted and never
    # replace the local answer.
    if _capability_flags.auto_web_general_knowledge:
        # Web fetch is independent of the source_attribution capability flag.
        # When attribution is disabled, treat the basis as "none" so the
        # auto_web_general_knowledge flag can still trigger.
        attribution_basis = (
            router_outcome.source_attribution.basis
            if router_outcome.source_attribution is not None
            else "none"
        )
        attribution_confidence = (
            router_outcome.source_attribution.confidence
            if router_outcome.source_attribution is not None
            else "unknown"
        )
        is_evidence_backed = attribution_confidence == "high"
        raw_confidence = getattr(classification, "confidence", None)
        low_classifier_confidence = (
            isinstance(raw_confidence, (int, float))
            and raw_confidence < THIN_LOCAL_CONFIDENCE_THRESHOLD
        )
        is_thin_local = attribution_basis == "none" or (
            low_classifier_confidence and not is_evidence_backed
        )
        if decision.route == "LOCAL" and is_thin_local:
            fetched = fetcher.fetch_general_knowledge(
                question,
                allowed_domains=list(_capability_flags.auto_web_allowed_domains),
                classification=classification,
            )
            if fetched.url:
                redacted_title, redacted_url = redact_untrusted_log_source(
                    fetched.title,
                    fetched.url,
                    question,
                )
                router_outcome = replace(
                    router_outcome,
                    escalation_suggestion=(
                        f"Web sources found (untrusted): {redacted_title} — {redacted_url}"
                    ),
                )

    _write_router_diagnostic_trace(
        request_id=(router_outcome.request_id or ""),
        original_query=question,
        resolved_query=(context or {}).get("resolved_question", ""),
        classification=classification,
        pre_guard_decision=_pre_guard_decision,
        final_decision=decision,
        flags=_capability_flags,
        outcome_code=router_outcome.outcome_code,
    )

    return router_outcome, classification, decision
