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

import logging
import os
import sys
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

# Re-export for tests/code that patch the pipeline's classifier reference.
classify_intent = classify.classify_intent

logger = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------
    # 0. Environment bypass (LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE)
    # ------------------------------------------------------------------
    forced_route = classify._forced_route_from_env(question)
    if forced_route:
        classification, decision = classify._bypass_classification_decision(
            question, forced_route
        )
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
    # 4. Evidence-disabled operator gate
    # ------------------------------------------------------------------
    gate_outcome, decision = route.apply_evidence_disabled_gate(
        decision, classification, start_time
    )
    if gate_outcome is not None:
        return gate_outcome, classification, decision

    # ------------------------------------------------------------------
    # 5. Build PipelineContext
    # ------------------------------------------------------------------
    _t3 = _time.time()
    pipeline_ctx = build_context.build_pipeline_context(
        question, surface, context, classification
    )
    if _profiling:
        _profile["context_build_ms"] = int((_time.time() - _t3) * 1000)

    # ------------------------------------------------------------------
    # 6. Execute
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
    # 7. Convert ExecutionResult → RouterOutcome
    # ------------------------------------------------------------------
    return outcome.build_outcome(
        result,
        classification,
        decision,
        start_time,
        _profile if _profiling else None,
        flags=_capability_flags,
    ), classification, decision
