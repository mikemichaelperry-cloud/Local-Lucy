#!/usr/bin/env python3
"""
Structured JSON logging for Lucy V8.

Provides:
- StructuredFormatter: outputs one JSON line per log record
- ContextualLogger: wraps logging.Logger with immutable request-scoped context
- configure_logging: sets up JSON formatting on the root logger

Usage:
    from router_py.structured_logging import configure_logging, get_structured_logger
    configure_logging(level="INFO")

    logger = get_structured_logger("router_py.main")
    bound = logger.bind(request_id="abc123", surface="voice", route="LOCAL")
    bound.info("Execution completed", extra={"latency_ms": 120})
    # → {"timestamp": "...", "level": "INFO", "logger": "router_py.main",
    #    "message": "Execution completed", "request_id": "abc123",
    #    "surface": "voice", "route": "LOCAL", "latency_ms": 120}
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# StructuredFormatter
# ---------------------------------------------------------------------------


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for log records.

    Outputs one compact JSON line per record.  Safe for mixed
    stdout / file consumers (e.g., systemd journal, log aggregators).
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: str = "%",
        validate: bool = True,
        *,
        defaults: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(fmt, datefmt, style, validate, defaults=defaults)

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields set via logging.info(..., extra={...})
        for key, value in record.__dict__.items():
            if key not in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "getMessage",
                "exc_info",
                "exc_text",
                "stack_info",
                "timestamp",
                "message",
                "level",
                "logger",
                "asctime",
            ):
                payload[key] = value

        # Exception info
        if record.exc_info:
            payload["exception"] = self._format_exception(record.exc_info)

        # Safe serialization: reject non-serializable values gracefully
        return json.dumps(payload, default=self._json_default, ensure_ascii=False)

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        from datetime import datetime, timezone

        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.isoformat(timespec="milliseconds")

    @staticmethod
    def _format_exception(exc_info: Any) -> str:
        return "".join(traceback.format_exception(*exc_info))

    @staticmethod
    def _json_default(obj: Any) -> Any:
        try:
            return str(obj)
        except Exception:
            return "<unserializable>"


# ---------------------------------------------------------------------------
# ContextualLogger
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContextualLogger:
    """
    Immutable logger wrapper that carries request-scoped context.

    Thread-safe: the underlying logger is shared, the context dict is
    immutable (copied on every bind).
    """

    _logger: logging.Logger
    _context: dict[str, Any] = field(default_factory=dict)

    def bind(self, **kwargs: Any) -> "ContextualLogger":
        """Return a new logger with additional bound fields."""
        new_ctx = dict(self._context)
        new_ctx.update(kwargs)
        return ContextualLogger(self._logger, new_ctx)

    def unbind(self, *keys: str) -> "ContextualLogger":
        """Return a new logger with specified keys removed."""
        new_ctx = {k: v for k, v in self._context.items() if k not in keys}
        return ContextualLogger(self._logger, new_ctx)

    def _log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        extra = kwargs.pop("extra", {})
        merged_extra = dict(self._context)
        merged_extra.update(extra)
        kwargs["extra"] = merged_extra
        self._logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("exc_info", True)
        self._log(logging.ERROR, msg, *args, **kwargs)

    # Passthrough for compatibility with logging.Logger attributes
    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def level(self) -> int:
        return self._logger.level

    def isEnabledFor(self, level: int) -> bool:
        return self._logger.isEnabledFor(level)

    def getEffectiveLevel(self) -> int:
        return self._logger.getEffectiveLevel()


# ---------------------------------------------------------------------------
# Module-level cache for logger instances
# ---------------------------------------------------------------------------

_logger_cache: dict[str, ContextualLogger] = {}
_logger_lock = threading.Lock()


def get_structured_logger(name: str) -> ContextualLogger:
    """Get or create a cached ContextualLogger."""
    with _logger_lock:
        if name not in _logger_cache:
            _logger_cache[name] = ContextualLogger(logging.getLogger(name))
        return _logger_cache[name]


def configure_logging(
    level: str | int = "INFO",
    handler: logging.Handler | None = None,
    force: bool = False,
) -> None:
    """
    Configure root logging with StructuredFormatter.

    Idempotent when called without an explicit handler (production use).
    When an explicit handler is passed, it always replaces existing handlers
    unless ``force=False`` and an existing StructuredFormatter handler is found.
    """
    root = logging.getLogger()

    # Convert string level
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    root.setLevel(level)

    # Idempotent fast-path only when no explicit handler is requested
    if handler is None and not force:
        for h in root.handlers:
            if isinstance(h.formatter, StructuredFormatter):
                h.setLevel(level)
                return

    # Remove existing handlers and add the new one
    for h in root.handlers[:]:
        root.removeHandler(h)

    h = handler or logging.StreamHandler(sys.stdout)
    h.setLevel(level)
    h.setFormatter(StructuredFormatter())
    root.addHandler(h)


def clear_logger_cache() -> None:
    """Clear the internal logger cache (useful for tests)."""
    global _logger_cache
    with _logger_lock:
        _logger_cache.clear()
