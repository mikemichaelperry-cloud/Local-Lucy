#!/usr/bin/env python3
"""Local LLM answer generator - Python replacement for local_answer.sh.

This module provides:
- Async Ollama API client with connection pooling
- Query classification and policy enforcement
- Session memory management
- Response caching
- Identity/policy response handling
- Prompt building with various modes
- Latency profiling
- Conversation mode support
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# Ensure tools package (and thus tools.xdg_paths) is importable when this module
# is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_memory_db_path, lucy_runtime_namespace_root

try:
    import aiohttp

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Import capability query detector from classify (with fallback)
try:
    from router_py.classify import _is_capability_query
except ImportError:
    try:
        from classify import _is_capability_query
    except ImportError:

        def _is_capability_query(query: str) -> bool:
            return False


# Import memory context filter from context_guard (with fallback)
try:
    from router_py.context_guard import filter_memory_context
except ImportError:
    try:
        from context_guard import filter_memory_context
    except ImportError:

        def filter_memory_context(question: str, memory_text: str, threshold: float = 0.3) -> str:
            return memory_text


# Import tube database (with fallback for standalone execution)
_tube_db = None
try:
    _TUBES_PATH = str(Path(__file__).resolve().parents[2] / "data" / "tubes")
    if _TUBES_PATH not in sys.path:
        sys.path.insert(0, _TUBES_PATH)
    import tube_database

    _tube_db = tube_database
except Exception:
    _tube_db = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ollama keep-alive heartbeat: pings the default model every 30s to prevent
# cold-start unload.  With 12 GB VRAM this keeps ~8.5 GB resident, leaving
# 3.5 GB for Whisper GPU + headroom.  RTX 3060 power draw increase is
# negligible (~5 W) compared to the UX benefit of instant responses.
# ---------------------------------------------------------------------------
_heartbeat_thread: threading.Thread | None = None
_heartbeat_stop = threading.Event()
_heartbeat_model: str | None = None


def _ollama_heartbeat_ping(
    model: str = "local-lucy-llama31", url: str = "http://127.0.0.1:11434/api/generate"
) -> None:
    """Lightweight ping to keep the model loaded in Ollama VRAM."""
    # Abort if the heartbeat has been stopped or retargeted to a different model.
    if _heartbeat_stop.is_set() or _heartbeat_model != model:
        return
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(
                {"model": model, "prompt": "", "stream": False, "options": {"num_predict": 1}}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
    except Exception:
        pass  # Silently fail; Ollama may not be running yet


def _heartbeat_loop(model: str, interval: float = 30.0) -> None:
    while not _heartbeat_stop.is_set():
        # If the authoritative state file now points to a different model,
        # exit so the old model is not re-loaded behind the caller's back.
        active_model = _get_active_model_from_state() or model
        if active_model != model:
            break
        _ollama_heartbeat_ping(model)
        # Check again in case the model was switched while the ping was in flight.
        active_model = _get_active_model_from_state() or model
        if active_model != model:
            break
        _heartbeat_stop.wait(interval)


def start_ollama_heartbeat(model: str = "local-lucy-llama31") -> None:
    """Start background heartbeat thread, restarting it if the model changed.

    The heartbeat keeps only the currently selected model warm. When the user
    switches models, any previous heartbeat thread is stopped and a new one is
    started for the new model so the old model is not re-loaded behind the
    caller's back.
    """
    global _heartbeat_thread, _heartbeat_model
    if _heartbeat_thread is not None and _heartbeat_thread.is_alive() and _heartbeat_model == model:
        return
    stop_ollama_heartbeat()
    if _heartbeat_thread is not None:
        _heartbeat_thread.join(timeout=1.0)
    _heartbeat_stop.clear()
    _heartbeat_model = model
    _heartbeat_thread = threading.Thread(
        target=_heartbeat_loop,
        args=(model,),
        daemon=True,
        name="ollama-heartbeat",
    )
    _heartbeat_thread.start()
    logger.info(f"[HEARTBEAT] Started Ollama keep-alive for {model}")


def stop_ollama_heartbeat() -> None:
    """Signal heartbeat thread to stop."""
    _heartbeat_stop.set()


# Import active identity helpers from SQL memory service (with fallback for standalone use).
# Persistent-fact retrieval lives in router_py.local_answer_core.facts so it can be shared
# with the engine without creating circular imports.
try:
    from memory.memory_service import (
        get_current_user_identity as _get_current_user_identity,
        get_persistent_facts_revision as _get_persistent_facts_revision,
    )

    logger.info("[FACTS] Imported memory service helpers from memory.memory.service")
except ImportError as _e1:
    logger.warning(f"[FACTS] Failed to import from memory.memory_service: {_e1}")
    try:
        from tools.memory.memory_service import (
            get_current_user_identity as _get_current_user_identity,
            get_persistent_facts_revision as _get_persistent_facts_revision,
        )

        logger.info("[FACTS] Imported memory service helpers from tools.memory.memory_service")
    except ImportError as _e2:
        logger.error(
            f"[FACTS] Failed to import memory service helpers: {_e2}. Using fallback no-ops."
        )

        def _get_persistent_facts_revision(category=None):
            return ""

        def _get_current_user_identity() -> str | None:
            return None


# Re-export implementation symbols from the focused sub-package.
from router_py.local_answer_core.config import (
    AnswerResult,
    LatencyMetrics,
    LocalAnswerConfig,
)
from router_py.local_answer_core.engine import LocalAnswer
from router_py.local_answer_core.facts import _get_relevant_persistent_facts
from router_py.local_answer_core.logger import LocalAnswerLogger
from router_py.local_answer_core.state import _get_active_model_from_state
from router_py.local_answer_core.self_knowledge import (
    WATER_WET_RESPONSE,
    _MODEL_IDENTITIES,
    get_self_knowledge,
)
from router_py.local_answer_core.utils import (
    _OllamaWarmupThread,
    get_gpu_free_vram_mb,
)

_local_answer_logger = LocalAnswerLogger()
