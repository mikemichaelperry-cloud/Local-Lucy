#!/usr/bin/env python3
"""
Unified fallback/degradation telemetry schema for Local Lucy.

A fallback may be safe.
A fallback may be correct.
But a fallback must never be invisible.

This module provides pure helper functions for building and merging
standardized fallback metadata. It does not change behavior — it only
makes existing fallbacks observable.

Usage:
    from fallback_telemetry import make as ft, merge

    telemetry = ft(
        fallback_used=True,
        fallback_reason="webclaw_unavailable",
        primary_failed="webclaw",
        fallback_to="legacy_html_parser",
        successful_backend="legacy_html_parser",
        degradation_level="limited",
    )
    metadata = merge(existing_metadata, telemetry)
"""
from __future__ import annotations

from typing import Any


def make(
    *,
    fallback_used: bool = False,
    fallback_reason: str = "",
    primary_failed: str = "",
    fallback_to: str = "",
    attempted_chain: list[str] | None = None,
    successful_backend: str = "",
    degradation_level: str = "none",
    answer_basis: str = "",
) -> dict[str, Any]:
    """Build a standardized fallback-telemetry dict.

    All fields are optional; absent values are stored as empty strings / False /
    empty lists so callers can safely read them without KeyError checks.
    """
    return {
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "primary_failed": primary_failed,
        "fallback_to": fallback_to,
        "attempted_chain": list(attempted_chain) if attempted_chain else [],
        "successful_backend": successful_backend,
        "degradation_level": degradation_level,
        "answer_basis": answer_basis,
    }


def merge(base: dict[str, Any], telemetry: dict[str, Any]) -> dict[str, Any]:
    """Merge *telemetry* into *base* metadata without overwriting existing keys.

    Preserves backward compatibility: if *base* already has a key, it wins.
    This prevents newer telemetry from clobbering older, more specific fields.
    """
    out: dict[str, Any] = dict(base)
    for key, value in telemetry.items():
        if key not in out:
            out[key] = value
    return out


def from_degraded_reason(
    degraded_reason: str,
    *,
    attempted_chain: list[str] | None = None,
    successful_backend: str = "",
) -> dict[str, Any]:
    """Map a legacy DEGRADED_REASON string into the unified schema.

    This lets existing trusted-evidence paths (which already track
    DEGRADED_REASON) participate in the unified telemetry without
    duplicating logic.
    """
    if not degraded_reason:
        return make(
            attempted_chain=attempted_chain,
            successful_backend=successful_backend,
        )

    # Map known degraded reasons to standard fields
    level = "low"
    reason = degraded_reason
    primary = ""
    fallback = ""
    basis = ""

    if degraded_reason == "search_no_results":
        primary = "searxng_search"
        fallback = "direct_fetch"
        basis = "domain_list_fallback"
    elif degraded_reason == "article_fetch_failed":
        primary = "article_extraction"
        fallback = "domain_list_fallback"
        basis = "domain_list_fallback"
    elif degraded_reason == "extractor_unavailable":
        primary = "article_extraction"
        fallback = "static_template"
        basis = "static_template"
    elif degraded_reason == "static_trusted_template":
        primary = "live_fetch"
        fallback = "static_template"
        basis = "static_template"
    else:
        level = "limited"
        basis = "degraded"

    return make(
        fallback_used=True,
        fallback_reason=reason,
        primary_failed=primary,
        fallback_to=fallback,
        attempted_chain=attempted_chain,
        successful_backend=successful_backend,
        degradation_level=level,
        answer_basis=basis,
    )
