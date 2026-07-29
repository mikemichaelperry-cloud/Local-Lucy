#!/usr/bin/env python3
"""PipelineContext assembly for the request pipeline.

This module holds the ``PipelineContext`` construction step that used to live
inline in ``request_pipeline.process()``. It is responsible for:

* Building a context from environment variables
* Merging caller-provided extras
* Applying classification-level overrides such as ``force_local``
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import ClassificationResult, PipelineContext


def build_pipeline_context(
    question: str,
    surface: str,
    context: dict[str, Any] | None,
    classification: ClassificationResult,
) -> PipelineContext:
    """
    Build the execution context for the current request.

    Args:
        question: The user's query text.
        surface: Origin surface (cli, hmi, voice, api).
        context: Extra execution context from caller.
        classification: The classified intent (used for force_local override).

    Returns:
        A fully populated ``PipelineContext``.
    """
    pipeline_ctx = PipelineContext.from_env(question=question, surface=surface)
    if context:
        # Merge caller-provided extras
        for key, value in context.items():
            if hasattr(pipeline_ctx, key):
                # Use dataclasses.replace because PipelineContext is frozen.
                pipeline_ctx = dataclasses.replace(pipeline_ctx, **{key: value})
            else:
                pipeline_ctx = dataclasses.replace(
                    pipeline_ctx,
                    extras={**pipeline_ctx.extras, key: value},
                )

    # Override force_local from classification
    if classification.force_local:
        pipeline_ctx = dataclasses.replace(pipeline_ctx, force_local=True)

    return pipeline_ctx
