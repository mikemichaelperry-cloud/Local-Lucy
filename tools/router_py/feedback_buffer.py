#!/usr/bin/env python3
"""Ring buffer for recent user-assistant exchanges.

Used by the feedback parser to attribute natural-language feedback
(e.g. "that was wrong") to the correct prior exchange.

The buffer persists to disk so feedback works across process restarts.
Only the last N turns are kept (default 5).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Persist in runtime namespace so it survives restarts
RUNTIME_NS = Path(
    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
)
BUFFER_PATH = RUNTIME_NS / "feedback_buffer.json"
DEFAULT_MAX_TURNS = 5


class Exchange:
    """A single user-assistant exchange."""

    def __init__(
        self,
        query: str,
        route: str,
        intent_family: str,
        response_text: str = "",
        confidence: float = 0.0,
        timestamp: Optional[str] = None,
    ):
        self.query = query
        self.route = route
        self.intent_family = intent_family
        self.response_text = response_text
        self.confidence = confidence
        self.timestamp = timestamp or datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "route": self.route,
            "intent_family": self.intent_family,
            "response_text": self.response_text,
            "confidence": self.confidence,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Exchange":
        return cls(
            query=d.get("query", ""),
            route=d.get("route", ""),
            intent_family=d.get("intent_family", ""),
            response_text=d.get("response_text", ""),
            confidence=d.get("confidence", 0.0),
            timestamp=d.get("timestamp", ""),
        )


class FeedbackBuffer:
    """Ring buffer of recent exchanges."""

    def __init__(self, max_turns: int = DEFAULT_MAX_TURNS):
        self.max_turns = max_turns
        self._exchanges: list[Exchange] = []
        self._load()

    def _load(self) -> None:
        if BUFFER_PATH.exists():
            try:
                with open(BUFFER_PATH) as f:
                    data = json.load(f)
                self._exchanges = [Exchange.from_dict(e) for e in data.get("exchanges", [])]
            except Exception:
                self._exchanges = []

    def _save(self) -> None:
        BUFFER_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BUFFER_PATH, "w") as f:
            json.dump(
                {
                    "exchanges": [e.to_dict() for e in self._exchanges],
                    "updated": datetime.now(timezone.utc).isoformat(),
                },
                f,
                indent=2,
            )

    def append(
        self,
        query: str,
        route: str,
        intent_family: str = "",
        response_text: str = "",
        confidence: float = 0.0,
    ) -> None:
        """Record a new exchange, trimming to max_turns."""
        self._exchanges.append(
            Exchange(
                query=query,
                route=route,
                intent_family=intent_family,
                response_text=response_text,
                confidence=confidence,
            )
        )
        if len(self._exchanges) > self.max_turns:
            self._exchanges = self._exchanges[-self.max_turns :]
        self._save()

    def last(self) -> Optional[Exchange]:
        """Return the most recent exchange, or None if empty."""
        return self._exchanges[-1] if self._exchanges else None

    def get_recent(self, n: int = 3) -> list[Exchange]:
        """Return the last n exchanges (most recent last)."""
        return self._exchanges[-n:] if self._exchanges else []

    def clear(self) -> None:
        """Clear the buffer."""
        self._exchanges = []
        self._save()

    def __len__(self) -> int:
        return len(self._exchanges)


# Singleton instance for convenience
_default_buffer: Optional[FeedbackBuffer] = None


def get_buffer() -> FeedbackBuffer:
    global _default_buffer
    if _default_buffer is None:
        _default_buffer = FeedbackBuffer()
    return _default_buffer


def record_exchange(
    query: str,
    route: str,
    intent_family: str = "",
    response_text: str = "",
    confidence: float = 0.0,
) -> None:
    """Convenience: record an exchange in the default buffer."""
    get_buffer().append(query, route, intent_family, response_text, confidence)
