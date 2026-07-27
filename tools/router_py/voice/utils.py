#!/usr/bin/env python3
"""Voice utility helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any  # noqa: F401

logger = logging.getLogger(__name__)


def iso_now() -> str:
    """Return current UTC time as ISO-8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean_text(value: Any) -> str:
    """Clean and normalize text input."""
    if value is None:
        return ""
    return str(value).strip()


def log_voice_pipeline_start():
    """Log that Python voice pipeline is being used."""
    import logging

    logger = logging.getLogger(__name__)


class VoiceUsageLogger:
    """Logger for voice engine usage."""

    def __init__(self):
        self.log_dir = Path.home() / ".local" / "share" / "lucy" / "logs"
        self.log_file = self.log_dir / "voice_engine.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def log(self, level: str, msg: str):
        ts = datetime.now().isoformat()
        try:
            with open(self.log_file, "a") as f:
                f.write(f"{ts} [{level}] {msg}\n")
        except Exception:
            pass

    def info(self, msg: str):
        self.log("INFO", msg)


_voice_usage_logger = VoiceUsageLogger()
