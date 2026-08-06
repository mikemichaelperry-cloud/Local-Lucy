#!/usr/bin/env python3
"""Privacy helpers for STAGE_15 — audit and log redaction.

These are pure functions (no side effects) that decide what may safely appear
in normal logs and memory.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse


def _domain_from_url(url: str) -> str:
    """Return the registered-style domain, or the full netloc if parsing fails."""
    try:
        netloc = urlparse(url).netloc.lower()
    except Exception:
        return "unknown"
    if not netloc:
        return "unknown"
    # Strip leading www.
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _query_terms(query: str) -> set[str]:
    """Return lowercase alphanumeric words of length >= 4 from the query."""
    return {
        term.lower()
        for term in re.findall(r"[a-zA-Z0-9]+", query or "")
        if len(term) >= 4
    }


def redact_untrusted_log_source(
    title: str,
    url: str,
    query: str,
    *,
    redacted_title: str = "[untrusted source title redacted]",
) -> tuple[str, str]:
    """Redact an untrusted web source for normal logs.

    The URL is reduced to its domain.  The title is replaced with a generic
    placeholder if any significant query term appears in it, preventing
    sensitive query text from leaking into logs.

    Returns: (redacted_title, domain_only_url)
    """
    domain = _domain_from_url(url)
    terms = _query_terms(query)
    title_lower = (title or "").lower()
    if terms and any(term in title_lower for term in terms):
        return redacted_title, domain
    return title, domain


# Pattern matching the untrusted-source annotation produced by the pipeline.
_UNTRUSTED_SOURCE_ANNOTATION_RE = re.compile(
    r"\s*Web sources found \(untrusted\):.*?\s*—\s*\S+",
    re.IGNORECASE,
)


def strip_untrusted_source_annotations(text: str) -> str:
    """Remove untrusted web-source annotations from text before storage.

    This prevents untrusted URLs and titles from being persisted to chat
    memory or ordinary logs.
    """
    if not text:
        return text
    return _UNTRUSTED_SOURCE_ANNOTATION_RE.sub("", text).strip()
