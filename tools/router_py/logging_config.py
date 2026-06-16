#!/usr/bin/env python3
"""
Convenience logging configuration for router_py.

Thin wrapper around the existing ``structured_logging`` formatter so the
rest of the router can use a standard-library style API:

    from router_py.logging_config import get_logger, setup_logging

    setup_logging(level=logging.INFO, json=True)
    logger = get_logger("router_py.main")
    logger.info("pipeline_start", extra={"request_id": request_id})
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

from router_py.structured_logging import StructuredFormatter


def get_logger(name: str) -> logging.Logger:
    """Return a standard ``logging.Logger`` with the given name."""
    return logging.getLogger(name)


def setup_logging(
    level: int = logging.INFO,
    json: bool = True,
    stream: TextIO = sys.stdout,
) -> None:
    """
    Configure the root logger for router output.

    Args:
        level: Minimum log level (default ``logging.INFO``).
        json: If ``True`` (default), emit compact structured JSON lines using
            the project's ``StructuredFormatter``. If ``False``, emit plain
            text lines with ISO-8601 timestamps, logger name, level, and
            message.
        stream: Output stream (default ``sys.stdout``).
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if setup_logging is called more than once.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(stream)
    handler.setLevel(level)

    if json:
        formatter: logging.Formatter = StructuredFormatter()
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )

    handler.setFormatter(formatter)
    root.addHandler(handler)
