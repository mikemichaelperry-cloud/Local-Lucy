#!/usr/bin/env python3
"""ExecutionResult → RouterOutcome conversion for the request pipeline.

This module holds the outcome-building step that used to live inline in
``request_pipeline.process()``. It is responsible for:

* Computing total execution time and optional latency profiling metadata
* Merging execution metadata with the latency profile
* Building the final ``RouterOutcome``

Source attribution fields are intentionally left at safe defaults here;
Task 7 will wire attribution and escalation logic behind capability flags.
"""

from __future__ import annotations

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
    ExecutionResult,
    RouterOutcome,
    RoutingDecision,
)


def build_outcome(
    result: ExecutionResult,
    classification: ClassificationResult,
    decision: RoutingDecision,
    start_time: float,
    profile: dict[str, int] | None,
) -> RouterOutcome:
    """
    Convert an ``ExecutionResult`` into a ``RouterOutcome``.

    Args:
        result: The result returned by ``execute_request``.
        classification: The classified intent.
        decision: The normalized routing decision.
        start_time: Pipeline start timestamp from ``time.time()``.
        profile: Optional latency profiling dictionary to enrich.

    Returns:
        The final ``RouterOutcome`` for the request.
    """
    execution_time = int((time.time() - start_time) * 1000)

    if profile is not None:
        profile["total_ms"] = execution_time
        profile["overhead_ms"] = max(0, execution_time - profile.get("execute_ms", 0))

    metadata: dict[str, Any] = dict(result.metadata) if result.metadata else {}
    if profile is not None:
        metadata["latency_profile"] = profile

    return RouterOutcome(
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
        metadata=metadata,
        evidence_reason=result.evidence_reason or decision.evidence_reason,
        policy_reason=result.policy_reason or decision.policy_reason,
    )
