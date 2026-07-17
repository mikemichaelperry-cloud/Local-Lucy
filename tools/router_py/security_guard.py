#!/usr/bin/env python3
"""
Input validation and prompt injection guard.

Protects the pipeline from:
- Overly long inputs (DoS vector)
- Control character injection
- Known jailbreak / prompt injection patterns
- Role confusion attacks

Usage:
    from router_py.security_guard import validate_input, ValidationResult
    result = validate_input(question, surface="voice")
    if not result.accepted:
        return RouterOutcome(status="failed", outcome_code="input_rejected", ...)
    question = result.sanitized
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


# ---------------------------------------------------------------------------
# Surface-specific limits
# ---------------------------------------------------------------------------

SURFACE_LIMITS: dict[str, int] = {
    "cli": 4000,
    "hmi": 4000,
    "voice": 500,
    "api": 8000,
}

# ---------------------------------------------------------------------------
# Known jailbreak patterns (case-insensitive)
# ---------------------------------------------------------------------------

JAILBREAK_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
        "ignore_previous_instructions",
    ),
    (re.compile(r"disregard\s+your\s+instructions", re.IGNORECASE), "disregard_instructions"),
    (re.compile(r"you\s+are\s+now\s+.*ignore", re.IGNORECASE), "role_injection_ignore"),
    (re.compile(r"\bDAN\b.*\b(do\s+anything\s+now)\b", re.IGNORECASE), "dan_jailbreak"),
    (re.compile(r"\bdeveloper\s+mode\b", re.IGNORECASE), "developer_mode"),
    (re.compile(r"system\s+prompt.*leak", re.IGNORECASE), "system_prompt_leak"),
    (re.compile(r"leak.*system\s+prompt", re.IGNORECASE), "system_prompt_leak"),
    (re.compile(r"\bjailbreak\b", re.IGNORECASE), "jailbreak_keyword"),
    (re.compile(r"\bsudo\b.*\bmode\b", re.IGNORECASE), "sudo_mode"),
    (re.compile(r"^\s*:\s*(system|assistant|user)\b", re.IGNORECASE), "role_prefix_injection"),
    (
        re.compile(r"^\s*<\|(?:im_start|system|assistant|user)\|>", re.IGNORECASE),
        "chatml_tag_injection",
    ),
    (re.compile(r"\[\s*(system|assistant|user)\s*\]", re.IGNORECASE), "bracket_role_injection"),
    (re.compile(r"from\s+now\s+on\s+you\s+are", re.IGNORECASE), "role_override"),
    (re.compile(r"pretend\s+to\s+be", re.IGNORECASE), "pretend_role"),
    (re.compile(r"act\s+as\s+(?:if\s+you\s+(?:are|were)\s+)?", re.IGNORECASE), "act_as_role"),
    (re.compile(r"ignore\s+everything\s+before", re.IGNORECASE), "ignore_history"),
    (
        re.compile(r"forget\s+all\s+(previous|prior)\s+instructions", re.IGNORECASE),
        "forget_instructions",
    ),
    (re.compile(r"new\s+instructions?:", re.IGNORECASE), "new_instructions"),
    (re.compile(r"override\s+(?:your\s+)?settings", re.IGNORECASE), "override_settings"),
]

# Unicode control characters and homoglyphs commonly used for obfuscation
OBFUSCATION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\u200B-\u200D\uFEFF]"), "zero_width_chars"),  # ZWNJ, ZWJ, BOM
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationResult:
    """Result of input validation."""

    accepted: bool
    sanitized: str
    reason: str | None = None
    violations: list[str] = None

    def __post_init__(self):
        # Mutable default workaround
        if self.violations is None:
            object.__setattr__(self, "violations", [])


# ---------------------------------------------------------------------------
# InputValidator
# ---------------------------------------------------------------------------


class InputValidator:
    """Sanitizes and validates raw user input."""

    # Control chars to strip (allow \n, \t, \r for formatting)
    CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
    WHITESPACE_COLLAPSE_RE = re.compile(r"[ \t]+")
    MULTI_NEWLINE_RE = re.compile(r"\n{4,}")

    @classmethod
    def sanitize(cls, text: str) -> str:
        """
        Strip dangerous characters and normalize whitespace.

        - Removes control chars (except \n, \t, \r)
        - Removes zero-width joiners / Unicode BOMs
        - Collapses repeated spaces/tabs
        - Limits consecutive newlines to 3
        - Strips leading/trailing whitespace
        """
        # Remove control characters
        text = cls.CONTROL_CHARS_RE.sub("", text)
        # Remove obfuscation characters
        for pattern, _ in OBFUSCATION_PATTERNS:
            text = pattern.sub("", text)
        # Collapse horizontal whitespace
        text = cls.WHITESPACE_COLLAPSE_RE.sub(" ", text)
        # Limit vertical whitespace
        text = cls.MULTI_NEWLINE_RE.sub("\n\n\n", text)
        return text.strip()

    @classmethod
    def validate_length(cls, text: str, surface: str = "cli") -> tuple[bool, int]:
        """
        Check length against surface-specific limit.

        Returns (ok, limit).
        """
        limit = SURFACE_LIMITS.get(surface, SURFACE_LIMITS["cli"])
        return len(text) <= limit, limit


# ---------------------------------------------------------------------------
# PromptInjectionDetector
# ---------------------------------------------------------------------------


class PromptInjectionDetector:
    """Detects known prompt injection and jailbreak attempts."""

    @classmethod
    def detect(cls, text: str) -> tuple[bool, list[str]]:
        """
        Scan text for known injection patterns.

        Returns (is_injection, list_of_reasons).
        """
        reasons: list[str] = []
        for pattern, reason in JAILBREAK_PATTERNS:
            if pattern.search(text):
                reasons.append(reason)
        # Also check for excessive repetition (cheap obfuscation)
        if cls._has_excessive_repetition(text):
            reasons.append("excessive_repetition")
        return bool(reasons), reasons

    @classmethod
    def _has_excessive_repetition(cls, text: str, threshold: int = 10) -> bool:
        """Detect if the same character repeats excessively (e.g., 'aaaaaa...')."""
        if len(text) < 20:
            return False
        max_repeat = 1
        current_repeat = 1
        for i in range(1, len(text)):
            if text[i] == text[i - 1]:
                current_repeat += 1
                max_repeat = max(max_repeat, current_repeat)
            else:
                current_repeat = 1
        return max_repeat >= threshold


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_input(question: str, surface: str = "cli") -> ValidationResult:
    """
    Full validation pipeline for user input.

    Order of checks:
    1. Empty check
    2. Length validation (surface-specific)
    3. Sanitization (control chars, whitespace)
    4. Prompt injection detection

    Returns ValidationResult with sanitized text or rejection reason.
    """
    if not question or not question.strip():
        return ValidationResult(
            accepted=False,
            sanitized="",
            reason="empty_query",
            violations=["empty_query"],
        )

    # 1. Length check on raw input first
    ok, limit = InputValidator.validate_length(question, surface)
    if not ok:
        return ValidationResult(
            accepted=False,
            sanitized="",
            reason=f"input_too_long: {len(question)} chars exceeds {surface} limit of {limit}",
            violations=["input_too_long"],
        )

    # 2. Sanitize
    sanitized = InputValidator.sanitize(question)
    if not sanitized:
        return ValidationResult(
            accepted=False,
            sanitized="",
            reason="sanitization_result_empty",
            violations=["sanitization_result_empty"],
        )

    # 3. Re-check length after sanitization
    ok, limit = InputValidator.validate_length(sanitized, surface)
    if not ok:
        return ValidationResult(
            accepted=False,
            sanitized=sanitized,
            reason=f"sanitized_input_too_long: {len(sanitized)} chars exceeds {surface} limit of {limit}",
            violations=["sanitized_input_too_long"],
        )

    # 4. Prompt injection detection
    is_injection, reasons = PromptInjectionDetector.detect(sanitized)
    if is_injection:
        return ValidationResult(
            accepted=False,
            sanitized=sanitized,
            reason=f"prompt_injection_detected: {', '.join(reasons)}",
            violations=reasons,
        )

    return ValidationResult(
        accepted=True,
        sanitized=sanitized,
        reason=None,
        violations=[],
    )
