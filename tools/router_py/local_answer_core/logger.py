#!/usr/bin/env python3
"""Local answer structured logger."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

class LocalAnswerLogger:
    """Logger for LocalAnswer operations.

    Keeps a persistent file handle to avoid open()/close() syscalls on every
    log entry (Phase 3C optimization).
    """

    def __init__(self):
        # ISOLATION: Use V8-specific logs if available, otherwise default
        import os

        v8_logs = os.environ.get("LUCY_LOGS_DIR")
        if v8_logs:
            self.log_dir = Path(v8_logs)
        else:
            self.log_dir = Path.home() / ".local" / "share" / "lucy-v11" / "logs"
        self.log_file = self.log_dir / "local_answer_py.log"
        self._file_handle = None
        self._ensure_log_dir()

    def _ensure_log_dir(self):
        """Ensure log directory exists."""
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_handle(self):
        """Lazily open and return persistent file handle."""
        if self._file_handle is None or self._file_handle.closed:
            try:
                self._file_handle = open(self.log_file, "a")
            except Exception:
                return None
        return self._file_handle

    def log(self, level: str, message: str) -> None:
        """Write log entry."""
        timestamp = datetime.now().isoformat()
        entry = f"{timestamp} [{level}] {message}\n"
        try:
            f = self._get_handle()
            if f:
                f.write(entry)
                f.flush()
        except Exception:
            pass  # Silently fail if logging fails

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def debug(self, message: str) -> None:
        self.log("DEBUG", message)

    def error(self, message: str) -> None:
        self.log("ERROR", message)

    def close(self) -> None:
        """Close the persistent file handle."""
        if self._file_handle and not self._file_handle.closed:
            try:
                self._file_handle.close()
            except Exception:
                pass
            self._file_handle = None


# Create global logger instance
