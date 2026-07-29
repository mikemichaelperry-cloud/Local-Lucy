#!/usr/bin/env python3
"""ExecutionEngine invocation for the request pipeline.

This module holds the execution step that used to live inline in
``request_pipeline.process()``. It is responsible for:

* Configuring and instantiating ``ExecutionEngine``
* Converting ``PipelineContext`` to the legacy dict format
* Calling ``ExecutionEngine.execute()``
* Returning a structured ``ExecutionResult`` on failure as well as success
  so that the facade can build a ``RouterOutcome`` in both paths.
"""

from __future__ import annotations

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

from router_py.request_types import (
    ClassificationResult,
    ExecutionResult,
    PipelineContext,
    RoutingDecision,
)
from router_py.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)


def execute_request(
    classification: ClassificationResult,
    decision: RoutingDecision,
    pipeline_ctx: PipelineContext,
    model: str | None,
    timeout: int,
) -> ExecutionResult:
    """
    Execute the selected route via ``ExecutionEngine``.

    Args:
        classification: The classified intent.
        decision: The normalized routing decision.
        pipeline_ctx: The fully assembled execution context.
        model: Optional model override.
        timeout: Request timeout in seconds.

    Returns:
        ``ExecutionResult`` on success, or a failure result with
        ``outcome_code="execution_error"`` if the engine raises.
    """
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
        return result

    except Exception as exc:
        logger.exception("ExecutionEngine failed")
        return ExecutionResult(
            status="failed",
            outcome_code="execution_error",
            route=decision.route,
            provider=decision.provider,
            provider_usage_class=decision.provider_usage_class,
            error_message=str(exc),
            execution_time_ms=0,
            metadata={},
            evidence_reason=decision.evidence_reason,
            policy_reason=decision.policy_reason,
        )
