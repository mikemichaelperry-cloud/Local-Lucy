#!/usr/bin/env python3
"""
HMI/backend sync guard — proves that ui-v9/app/backend uses the canonical
router/execution code from tools/router_py, not stale duplicates.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup so we can import the backend wrappers
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_PKG = PROJECT_ROOT / "ui-v9" / "app"
if str(BACKEND_PKG) not in sys.path:
    sys.path.insert(0, str(BACKEND_PKG))
if str(PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "tools"))

# Canonical imports
from router_py.classify import classify_intent as canonical_classify_intent
from router_py.classify import select_route as canonical_select_route
from router_py.classify import ClassificationResult, RoutingDecision
from router_py.execution_engine import ExecutionEngine as canonical_ExecutionEngine
from router_py.execution_engine import ExecutionResult as canonical_ExecutionResult
from router_py.policy import requires_evidence_mode as canonical_requires_evidence_mode

# Backend imports (thin wrappers)
from backend import (
    classify_intent as backend_classify_intent,
    select_route as backend_select_route,
    ExecutionEngine as backend_ExecutionEngine,
    ExecutionResult as backend_ExecutionResult,
    requires_evidence_mode as backend_requires_evidence_mode,
)


class TestHMIBackendSync:
    """Verify backend wrappers reference the same objects as canonical code."""

    def test_classify_intent_identity(self):
        assert backend_classify_intent is canonical_classify_intent

    def test_select_route_identity(self):
        assert backend_select_route is canonical_select_route

    def test_execution_engine_identity(self):
        assert backend_ExecutionEngine is canonical_ExecutionEngine

    def test_execution_result_identity(self):
        assert backend_ExecutionResult is canonical_ExecutionResult

    def test_policy_requires_evidence_mode_identity(self):
        assert backend_requires_evidence_mode is canonical_requires_evidence_mode

    @pytest.mark.parametrize(
        "query,expected_route",
        [
            ("Who won the Battle of Waterloo?", "LOCAL"),
            ("Describe a vacuum tube", "LOCAL"),
            ("The the the the the", "LOCAL"),
            ("Give me the latest news about the war", "NEWS"),
            ("Not history - current Israeli news", "NEWS"),
            ("Explain the background of the Gaza war", "LOCAL"),
        ],
    )
    def test_route_probes_agree(self, query, expected_route):
        """Canonical and backend paths must agree on route for acceptance probes."""
        cls_canonical = canonical_classify_intent(query)
        dec_canonical = canonical_select_route(
            cls_canonical, query=query, policy="fallback_only"
        )

        cls_backend = backend_classify_intent(query)
        dec_backend = backend_select_route(
            cls_backend, query=query, policy="fallback_only"
        )

        assert dec_canonical.route == dec_backend.route, (
            f"Route mismatch for {query!r}: "
            f"canonical={dec_canonical.route}, backend={dec_backend.route}"
        )
        # Sanity-check against expected route (may be relaxed after policy updates)
        assert dec_canonical.route == expected_route, (
            f"Expected {expected_route} for {query!r}, got {dec_canonical.route}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
