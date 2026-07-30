#!/usr/bin/env python3
"""Persistent-fact helpers for local answer components.

This module centralises the import of memory-service fact retrieval so that
both `router_py.local_answer` and `router_py.local_answer_core.engine` can
share the same fallback behaviour without circular imports.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from memory.memory_service import get_relevant_persistent_facts as _get_relevant_persistent_facts

    logger.info("[FACTS] Imported memory service helper from memory.memory_service")
except ImportError as _e1:
    logger.warning(f"[FACTS] Failed to import from memory.memory_service: {_e1}")
    try:
        from tools.memory.memory_service import get_relevant_persistent_facts as _get_relevant_persistent_facts

        logger.info("[FACTS] Imported memory service helper from tools.memory.memory_service")
    except ImportError as _e2:
        logger.error(f"[FACTS] Failed to import memory service helper: {_e2}. Using fallback no-op.")

        def _get_relevant_persistent_facts(query, category=None, limit=3, threshold=0.35):  # type: ignore[misc]
            return []


__all__ = ["_get_relevant_persistent_facts"]
