"""Request-scoped capability constraints.

Parses explicit user restrictions such as "do not use network access" or
"use only currently available information" into a typed, deterministic set of
capability flags that downstream routing and execution stages can enforce.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestConstraints:
    """Explicit capability restrictions supplied by the user for one request.

    Each field is ``True`` (capability explicitly allowed/required),
    ``False`` (capability explicitly denied), or ``None`` (not mentioned).
    """

    network: bool | None = None
    tools: bool | None = None
    file_read: bool | None = None
    file_write: bool | None = None
    memory_read: bool | None = None
    memory_write: bool | None = None
    local_only: bool | None = None


def extract_request_constraints(question: str) -> RequestConstraints:
    """Extract explicit capability restrictions from *question*.

    The parser looks for common natural-language denial phrases and for
    markers that require answers to use only locally available information.
    It is intentionally simple and deterministic: only explicit restrictions
    are reflected, and every field defaults to ``None`` when not mentioned.
    """
    if not question:
        return RequestConstraints()

    text = " ".join(question.lower().split())

    # Network access restrictions
    network = False if _has_any(text, _NETWORK_DENIALS) else None

    # Tool use restrictions
    tools = False if _has_any(text, _TOOL_DENIALS) else None

    # File access / write restrictions
    file_read = False if _has_any(text, _FILE_DENIALS) else None
    file_write = file_read

    # Memory access / write restrictions
    memory_write = False if _has_any(text, _MEMORY_WRITE_DENIALS) else None
    memory_read = None

    # Local-only / no external information restrictions
    local_only = True if _has_any(text, _LOCAL_ONLY_MARKERS) else None

    return RequestConstraints(
        network=network,
        tools=tools,
        file_read=file_read,
        file_write=file_write,
        memory_read=memory_read,
        memory_write=memory_write,
        local_only=local_only,
    )


# Phrase groups used by extract_request_constraints.
# Each entry is a regex that must match as a whole phrase/keyword.

_NETWORK_DENIALS = [
    # "do not use/access ... network access" within the same sentence/clause.
    re.compile(r"\bdo\s+not\s+(?:use|access)\b[^.]*?\bnetwork\s+access\b"),
    # Direct standalone denials.
    re.compile(r"\bdo\s+not\s+(?:use|access)\s+(?:the\s+)?internet\b"),
    re.compile(r"\bdo\s+not\s+browse\s+(?:the\s+)?web\b"),
    re.compile(r"\bno\s+(?:network\s+access|internet|web)\b"),
]

_TOOL_DENIALS = [
    re.compile(r"\bdo\s+not\s+use\s+tools\b"),
    re.compile(r"\bno\s+tools\b"),
]

_FILE_DENIALS = [
    # "do not access/use/read/write ... files" within the same sentence/clause.
    re.compile(r"\bdo\s+not\s+(?:access|use|read|write)\b[^.]*?\bfiles?\b"),
    re.compile(r"\bno\s+files?\b"),
]

_MEMORY_WRITE_DENIALS = [
    # "do not write/store/save ... memory" within the same sentence/clause.
    re.compile(r"\bdo\s+not\s+(?:write|store|save)\b[^.]*?\bmemory\b"),
    re.compile(r"\bdo\s+not\s+store\s+this\b"),
    re.compile(r"\bmemory-writing\b"),
]

_LOCAL_ONLY_MARKERS = [
    re.compile(r"\buse\s+only\s+(?:currently\s+available|the\s+information\s+already\s+available)\b"),
    re.compile(r"\banswer\s+only\s+from\s+(?:current\s+local\s+context|local\s+context)\b"),
    re.compile(r"\bonly\s+currently\s+available\s+information\b"),
]


def _has_any(text: str, patterns: list[re.Pattern[str]]) -> bool:
    """Return True if *text* matches any compiled pattern."""
    return any(pattern.search(text) for pattern in patterns)
