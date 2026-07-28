"""Strict schema validator for model-generated planner output.

Planner output is expected to be a structured dict describing search queries
and, optionally, already-known URLs. This module rejects prose, malformed
JSON, isolated single-word queries, unknown fields, and invented URLs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


@dataclass(frozen=True)
class PlannerValidationResult:
    """Result of validating a planner output object."""

    valid: bool
    error_code: str | None = None


class PlannerValidator:
    """Validate planner output against a strict schema.

    A valid plan is a dict with exactly two fields:

    * ``queries``: a non-empty list of coherent, multi-word search strings.
    * ``urls``: a list of URLs (usually empty for model-generated plans).

    Any prose string, malformed JSON, unknown field, isolated word query, or
    fabricated URL causes the plan to be rejected with a typed error code.
    """

    _ALLOWED_FIELDS = frozenset({"queries", "urls"})
    _FABRICATED_PATH_TOKENS = frozenset(
        {"internal", "example", "test", "fake", "placeholder", "dummy", "mock"}
    )

    def validate(self, plan: Any) -> PlannerValidationResult:
        """Return a ``PlannerValidationResult`` for *plan*."""
        if isinstance(plan, str):
            return self._validate_string(plan)

        if not isinstance(plan, dict):
            return PlannerValidationResult(valid=False, error_code="invalid_structure")

        if set(plan.keys()) != self._ALLOWED_FIELDS:
            return PlannerValidationResult(valid=False, error_code="unknown_field")

        queries = plan.get("queries")
        if not isinstance(queries, list) or not queries:
            return PlannerValidationResult(valid=False, error_code="invalid_query")

        for query in queries:
            if not isinstance(query, str) or not self._is_coherent_query(query):
                return PlannerValidationResult(valid=False, error_code="invalid_query")

        urls = plan.get("urls")
        if not isinstance(urls, list):
            return PlannerValidationResult(valid=False, error_code="invalid_url")

        for url in urls:
            if not isinstance(url, str) or self._is_fabricated_url(url):
                return PlannerValidationResult(valid=False, error_code="invalid_url")

        return PlannerValidationResult(valid=True, error_code=None)

    def _validate_string(self, plan: str) -> PlannerValidationResult:
        """Handle a string plan: parse JSON if it looks structured, else prose."""
        text = plan.strip()
        if text.startswith(("{", "[")):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return PlannerValidationResult(valid=False, error_code="malformed_json")
            return self.validate(parsed)

        return PlannerValidationResult(valid=False, error_code="invalid_structure")

    def _is_coherent_query(self, query: str) -> bool:
        """Return True when *query* is a coherent, multi-word phrase."""
        cleaned = re.sub(r"\s+", " ", query.strip())
        return len(cleaned.split()) >= 2

    def _is_fabricated_url(self, url: str) -> bool:
        """Return True when *url* appears to be model-invented.

        Model-generated plans are not a trusted provenance for arbitrary URLs.
        Only syntactically valid HTTPS URLs that point to concrete resources
        (i.e. not root-level placeholder pages) are accepted.
        """
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return True

        path = parsed.path.lower()
        if any(token in path for token in self._FABRICATED_PATH_TOKENS):
            return True

        # Require a path with at least two meaningful segments. This rejects
        # invented root-level pages like /internal.html while keeping real
        # article-style URLs such as /ency/article/000033.htm.
        segments = [seg for seg in path.split("/") if seg]
        return len(segments) < 2
