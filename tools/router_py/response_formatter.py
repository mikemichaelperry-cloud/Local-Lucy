#!/usr/bin/env python3
"""
Response formatting and validation utilities.

Stage 7 of the Kimi Architecture Refactor.
Extracted from execution_engine.py to separate formatting concerns
from execution logic.

These are pure functions (no side effects, no I/O) that transform
raw response text into validated, formatted output.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from router_py.request_types import RoutingDecision


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_response(response: str, route: RoutingDecision | None = None) -> str:
    """
    Validate and sanitize a raw model response.

    Returns a safe fallback if the response is empty or indicates
    generation failure.
    """
    if not response or not response.strip():
        return "I apologize, but I couldn't generate a response. Please try again."

    validated = response.strip()

    if is_local_generation_failure_output(validated):
        return "I'm having trouble connecting to the model. Please try again."

    if not validated:
        return "I couldn't generate a response. Please rephrase your question."

    return validated


def is_local_generation_failure_output(body: str) -> bool:
    """Check if output indicates local generation failure."""
    n = guard_normalize(body)
    failure_patterns = [
        "127.0.0.1:11434",
        "ollama",
        "connection refused",
        "operation not permitted",
        "dial tcp",
    ]
    return any(pattern in n for pattern in failure_patterns)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_chat_fast_from_raw(raw: str) -> str:
    """
    Fast render of chat output from raw local model response.

    Strips validation markers and common error prefixes.
    """
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        if s in ("BEGIN_VALIDATED", "END_VALIDATED"):
            continue
        lines.append(s)

    text = " ".join(lines) if lines else raw.strip()

    # Strip common model-generated error prefixes (qwen3 thinking artifacts)
    error_prefixes = [
        "Error:", "error:", "ERROR:",
        "Sorry, I cannot", "sorry, i cannot",
        "I cannot answer", "i cannot answer",
    ]
    for prefix in error_prefixes:
        if text.startswith(prefix):
            text = text[len(prefix):].lstrip()

    return text.strip()


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def build_augmented_prompt(
    question: str,
    evidence: dict[str, Any] | None,
    route: RoutingDecision,
) -> str:
    """Build augmented prompt with evidence context."""
    if not evidence:
        return question

    # Trusted provider uses "content"; Wikipedia/news use "context"
    context_text = evidence.get("context") or evidence.get("content", "")
    if not context_text:
        return question

    title = evidence.get("title", "")
    url = evidence.get("url", "")
    provider = evidence.get("provider", "unknown")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    prompt_parts = [
        f"Question: {question}",
        f"Current date and time: {now}",
        "",
        "Background Context:",
        context_text,
    ]

    if title:
        prompt_parts.append(f"\nSource: {title}")
    if url:
        prompt_parts.append(f"URL: {url}")

    # Append trusted sources list if present
    sources = evidence.get("sources", [])
    if sources:
        prompt_parts.append(f"\nTrusted sources: {', '.join(sources[:6])}")

    prompt_parts.append(f"\nProvider: {provider}")
    prompt_parts.append(
        "\nBased on the background context above and your own knowledge, "
        "please answer the question. If the context is outdated or incomplete, "
        "say so and answer from your own knowledge up to your training cutoff."
    )

    return "\n".join(prompt_parts)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def guard_normalize(text: str | None) -> str:
    """Normalize text for guard pattern matching."""
    import re
    if not text:
        return ""
    normalized = text.lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def is_evidence_style_text(text: str) -> bool:
    """Check if text has evidence-style formatting."""
    n = guard_normalize(text)
    evidence_patterns = [
        "source:",
        "sources:",
        "according to",
        "retrieved from",
    ]
    return any(pattern in n for pattern in evidence_patterns)


# ---------------------------------------------------------------------------
# Legacy compat
# ---------------------------------------------------------------------------


def format_response(raw_response: str, metadata: dict[str, Any] | None = None) -> str:
    """
    Format and enhance a raw response.

    Currently a thin wrapper around strip(). Future stages may add:
    - Trust-class footers
    - Conversation cadence
    - Length trimming
    """
    return raw_response.strip()
