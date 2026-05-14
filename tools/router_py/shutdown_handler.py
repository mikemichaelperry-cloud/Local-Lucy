#!/usr/bin/env python3
"""Graceful shutdown handler for SIGTERM / SIGINT.

Registers a global handler that closes StateWriter instances,
cleans up temporary namespace directories, and flushes SQLite WALs.
"""

from __future__ import annotations

import atexit
import logging
import os
import shutil
import signal
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global registry of objects that need cleanup on shutdown
_closeables: list[Any] = []
_registry_lock = threading.Lock()
_shutting_down = False


def register_closeable(obj: Any) -> None:
    """Register an object for graceful shutdown cleanup.

    The object should have a ``.close()`` method, or be a callable.
    """
    with _registry_lock:
        if obj not in _closeables:
            _closeables.append(obj)
            logger.debug(f"Registered closeable: {type(obj).__name__}")


def unregister_closeable(obj: Any) -> None:
    """Remove an object from the shutdown registry."""
    with _registry_lock:
        try:
            _closeables.remove(obj)
        except ValueError:
            pass


def _close_all() -> None:
    """Iterate the registry and close/clean up every registered object."""
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True

    with _registry_lock:
        items = list(_closeables)

    for item in items:
        try:
            if hasattr(item, "close"):
                item.close()
                logger.debug(f"Closed {type(item).__name__}")
            elif callable(item):
                item()
                logger.debug("Executed cleanup callable")
        except Exception as e:
            logger.warning(f"Error during shutdown cleanup: {e}")

    # Clean up temporary namespace directories under state/namespaces/
    try:
        root = Path(__file__).resolve().parent.parent.parent / "state" / "namespaces"
        if root.exists():
            for ns_dir in root.iterdir():
                if ns_dir.is_dir() and not ns_dir.name.startswith("."):
                    try:
                        shutil.rmtree(ns_dir)
                        logger.debug(f"Removed namespace directory: {ns_dir}")
                    except Exception as e:
                        logger.debug(f"Could not remove {ns_dir}: {e}")
    except Exception as e:
        logger.warning(f"Namespace cleanup error: {e}")


def _on_signal(signum: int, frame: Any) -> None:
    """Signal handler for SIGTERM / SIGINT."""
    sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
    logger.info(f"Received {sig_name}, initiating graceful shutdown...")
    _close_all()
    # Re-raise the default handler so the process actually exits
    signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def install() -> None:
    """Install SIGTERM / SIGINT handlers and atexit hook (idempotent)."""
    try:
        signal.signal(signal.SIGTERM, _on_signal)
        signal.signal(signal.SIGINT, _on_signal)
        logger.debug("Installed SIGTERM and SIGINT handlers")
    except ValueError:
        # May fail if not in main thread
        logger.debug("Could not install signal handlers (not in main thread)")

    atexit.register(_close_all)
    logger.debug("Registered atexit shutdown hook")
