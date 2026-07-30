#!/usr/bin/env python3
"""Runtime-state helpers for local answer components.

This module centralises reading the authoritative model state file so that
`router_py.local_answer` and `router_py.local_answer_core.utils` can share the
same logic without circular imports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(ROOT_DIR))

from tools.xdg_paths import lucy_runtime_namespace_root


def _get_active_model_from_state() -> str | None:
    """Read the currently selected model from the authoritative state file.

    Heartbeat/warmup threads use this instead of relying only on their
    thread-local model argument. That way a state change made through the
    HMI, CLI, or a profile reload is respected even if no new heartbeat
    thread is explicitly started for the new model.
    """
    raw_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip()
    if raw_state_file:
        state_file = Path(raw_state_file).expanduser()
    else:
        namespace = os.environ.get(
            "LUCY_RUNTIME_NAMESPACE_ROOT",
            str(lucy_runtime_namespace_root()),
        )
        state_file = Path(namespace).expanduser() / "state" / "current_state.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
        model = str(state.get("model", "")).strip()
        if model and model.lower() != "auto":
            return model
    except Exception:
        pass
    return None


__all__ = ["_get_active_model_from_state"]
