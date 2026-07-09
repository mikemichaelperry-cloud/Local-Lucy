#!/usr/bin/env python3
"""Ollama cleanup helpers for graceful Local Lucy shutdown.

On a 12 GB GPU two local models do not fit. This module provides helpers to
query Ollama's loaded models and unload the ones Local Lucy uses so VRAM is
released when Lucy exits or switches models.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_OLLAMA_API_URL = "http://127.0.0.1:11434"
LUCY_MODEL_PREFIXES = ("local-lucy",)


def _ollama_api_url() -> str:
    import os

    return os.environ.get("LUCY_OLLAMA_API_URL", DEFAULT_OLLAMA_API_URL).strip().rstrip("/")


def list_loaded_models() -> list[str]:
    """Return the names of models currently loaded by Ollama."""
    try:
        with urllib.request.urlopen(f"{_ollama_api_url()}/api/ps", timeout=5.0) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"Could not query Ollama /api/ps: {e}")
        return []

    models: list[str] = []
    for entry in data.get("models", []) or []:
        name = entry.get("name", "") or entry.get("model", "")
        if name:
            models.append(name)
    return models


def is_lucy_model(name: str) -> bool:
    """Return True if *name* looks like a Local Lucy managed model."""
    if not name:
        return False
    lowered = name.strip().lower()
    return any(lowered.startswith(prefix) for prefix in LUCY_MODEL_PREFIXES)


def unload_model(name: str) -> bool:
    """Ask Ollama to unload *name*. Return True if the call succeeded."""
    if not name:
        return False

    # Use the Ollama HTTP API to unload the model immediately.
    body = json.dumps(
        {
            "model": name,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
            "options": {"num_predict": 0},
        }
    ).encode("utf-8")
    try:
        request = urllib.request.Request(
            f"{_ollama_api_url()}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15.0):
            return True
    except Exception as e:
        logger.debug(f"Ollama API unload for {name} failed: {e}")
    return False


def unload_all_lucy_models() -> list[str]:
    """Unload every Local Lucy model Ollama currently has resident.

    Returns the names of models that were attempted to be unloaded.
    """
    attempted: list[str] = []
    for name in list_loaded_models():
        if is_lucy_model(name):
            attempted.append(name)
            unload_model(name)
    return attempted


def shutdown_cleanup() -> None:
    """Best-effort cleanup of Ollama models on Local Lucy shutdown.

    This is registered with the shutdown handler so VRAM is released when
    Local Lucy exits cleanly (SIGINT/SIGTERM/atexit).
    """
    try:
        unloaded = unload_all_lucy_models()
        if unloaded:
            logger.info(f"Shutdown cleanup unloaded Ollama models: {unloaded}")
    except Exception as e:
        logger.warning(f"Shutdown Ollama cleanup failed: {e}")
