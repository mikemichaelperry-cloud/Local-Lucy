#!/usr/bin/env python3
"""Policy router data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class PolicyDecision:
    """A deterministic routing decision produced by a policy gate.

    Carries everything needed to build a ``RoutingDecision`` plus trace
    metadata so the final route is explainable.
    """

    route: str
    reason_code: str
    matched_rule: str
    confidence: float = 1.0
    ephemeral: bool = False
    evidence_mode: str = ""
    evidence_reason: str = ""
    requires_evidence: bool = False
    provider: str = ""
    provider_usage_class: str = "local"
    policy_reason: str = ""
    trace: dict[str, Any] = field(default_factory=dict)
