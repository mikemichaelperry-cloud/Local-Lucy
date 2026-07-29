#!/usr/bin/env python3
"""Source attribution builder for pipeline outcomes.

Produces a ``SourceAttribution`` record describing the provenance of an
answer, plus a human-readable trust label. All logic is gated by the
``source_attribution`` capability flag so the default pipeline behaviour
remains unchanged.
"""

from __future__ import annotations

from typing import Any

from router_py.pipeline.config import CapabilityFlags
from router_py.request_types import ExecutionResult, RoutingDecision, SourceAttribution


def build_source_attribution(
    decision: RoutingDecision,
    result: ExecutionResult,
    flags: CapabilityFlags | None = None,
) -> SourceAttribution | None:
    """Build a ``SourceAttribution`` from the routing decision and result.

    Returns ``None`` when the ``source_attribution`` capability flag is
    disabled, preserving the pre-Task-7 default behaviour.

    Rules:
        * route LOCAL + no evidence → basis "local", confidence "medium"
        * route LOCAL + evidence → basis "local", confidence "high"
        * route AUGMENTED → basis "augmented", confidence "medium"
        * route EVIDENCE with trusted sources → basis "evidence",
          confidence "high"
        * route NEWS → basis "evidence", confidence "medium"
        * no source metadata → basis "none", confidence "unknown"

    The caller is expected to pass ``CapabilityFlags`` (loaded once by
    ``request_pipeline.process()``) so this function does not re-read disk
    config on every outcome build.
    """
    if flags is None or not flags.source_attribution:
        return None

    metadata: dict[str, Any] = result.metadata or {}
    route = decision.route
    trust_class = metadata.get("trust_class", "")
    sources = _extract_sources(metadata)
    has_evidence = bool(metadata.get("evidence_fetched") or sources)

    if route == "LOCAL":
        confidence = "high" if has_evidence else "medium"
        return SourceAttribution(basis="local", sources=sources, confidence=confidence)

    if route == "AUGMENTED":
        return SourceAttribution(basis="augmented", sources=sources, confidence="medium")

    # ``trust_class == "trusted"`` is the execution engine's existing signal
    # that the fetched evidence came from a trusted-domain allowlist (e.g.
    # bounded medical/veterinary responses).  It is therefore equivalent to
    # "EVIDENCE with trusted sources" in the brief.
    if route == "EVIDENCE" and trust_class == "trusted":
        return SourceAttribution(basis="evidence", sources=sources, confidence="high")

    if route == "NEWS":
        return SourceAttribution(basis="evidence", sources=sources, confidence="medium")

    return SourceAttribution(basis="none", sources=sources, confidence="unknown")


def _extract_sources(metadata: dict[str, Any]) -> list[str]:
    """Extract source identifiers from execution metadata if present."""
    raw = metadata.get("sources")
    if isinstance(raw, list):
        return [str(s) for s in raw]
    return []


def build_trust_label(attribution: SourceAttribution) -> str:
    """Map an attribution record to a concise trust label."""
    basis = attribution.basis
    confidence = attribution.confidence

    if basis == "evidence" and confidence == "high":
        return "verified"
    if basis == "evidence" and confidence == "medium":
        return "partially_verified"
    if basis == "local":
        return "local_only"
    if basis == "augmented":
        return "augmented"
    if basis == "web_untrusted":
        return "untrusted"
    return "unknown"
