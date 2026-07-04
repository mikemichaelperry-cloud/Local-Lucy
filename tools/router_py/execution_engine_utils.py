#!/usr/bin/env python3
"""Pure utility functions extracted from execution_engine.py.

These functions have no dependency on ExecutionEngine state and can be
used independently for testing or by other modules.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Imported here because _local_fast_guard_normalize delegates to it
from router_py import response_formatter


def is_truthy(value: str | None) -> bool:
    """
    Parse boolean from string.

    Args:
        value: String to parse (e.g., "true", "1", "yes", "")

    Returns:
        True for "true", "1", "yes", "on" (case-insensitive), False otherwise
    """
    if not value:
        return False
    return value.lower() in ("1", "true", "yes", "on")


def sha256_text(text: str) -> str:
    """
    Generate SHA-256 hash of text.

    Args:
        text: String to hash

    Returns:
        Hexadecimal SHA-256 hash string (64 characters)
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def deterministic_pick_index(seed: str, mod: int) -> int:
    """
    Deterministically select an index from 0 to mod-1 based on seed.

    Uses SHA-256 hash of the seed and takes first 8 hex digits to create
    a deterministic pseudo-random selection.

    Args:
        seed: Seed string for deterministic selection
        mod: Modulo value (must be positive)

    Returns:
        Integer index from 0 to mod-1

    Raises:
        ValueError: If mod is not positive
    """
    if mod <= 0:
        raise ValueError(f"mod must be positive, got {mod}")
    h = sha256_text(seed)
    hex_val = h[:8]
    return int(hex_val, 16) % mod


def provider_usage_class_for(provider: str | None) -> str:
    """
    Map provider name to usage class.

    Args:
        provider: Provider name (e.g., "openai", "kimi", "wikipedia", "local")

    Returns:
        Usage class: "paid", "free", "local", or "none"
    """
    if not provider:
        return "none"
    match provider.lower():
        case "openai" | "kimi":
            return "paid"
        case "wikipedia" | "finance" | "trusted":
            return "free"
        case "local":
            return "local"
        case _:
            return "none"


def is_category_specific_query(question: str, intent_family: str) -> bool:
    """
    Check if query is category-specific (news, medical, finance).
    These queries should try trusted sources first.

    Args:
        question: The user question
        intent_family: Classified intent family

    Returns:
        True if this is a category-specific query
    """
    q_lower = question.lower()

    if intent_family == "current_evidence":
        return True

    news_keywords = [
        "news",
        "headline",
        "headlines",
        "breaking",
        "latest",
        "current events",
        "world news",
        "today's news",
    ]
    if any(kw in q_lower for kw in news_keywords):
        return True

    medical_keywords = [
        "medical",
        "medication",
        "medicine",
        "drug",
        "dose",
        "dosage",
        "side effect",
        "interaction",
        "contraindication",
        "health",
        "prescription",
        "treatment",
    ]
    if any(kw in q_lower for kw in medical_keywords):
        return True

    finance_keywords = [
        "finance",
        "stock",
        "market",
        "economy",
        "currency",
        "exchange rate",
        "investment",
        "financial",
    ]
    if any(kw in q_lower for kw in finance_keywords):
        return True

    return False


def normalize_augmentation_policy(raw: str | None) -> str:
    """
    Normalize augmentation policy string to canonical value.

    Args:
        raw: Raw policy string (e.g., "disabled", "fallback", "direct")

    Returns:
        Canonical policy: "disabled", "fallback_only", or "direct_allowed"
    """
    if not raw:
        return "disabled"
    normalized = raw.lower()
    match normalized:
        case "disabled" | "off" | "none" | "0" | "false" | "no":
            return "disabled"
        case "fallback_only" | "fallback" | "1" | "true" | "yes" | "on":
            return "fallback_only"
        case "direct_allowed" | "direct" | "2":
            return "direct_allowed"
        case "auto":
            # Autonomous mode: let the router decide when to augment.
            return "direct_allowed"
        case _:
            return "disabled"


def local_fast_guard_normalize(text: str | None) -> str:
    """Alias for response_formatter.guard_normalize."""
    return response_formatter.guard_normalize(text)
