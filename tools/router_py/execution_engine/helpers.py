#!/usr/bin/env python3
"""Execution engine helper functions."""

from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

def _get_root():
    """Return the current execution_engine ROOT_DIR dynamically."""
    import router_py.execution_engine as _ee
    return _ee.ROOT_DIR

_MEDICAL_DOMAINS_CACHE: list[str] | None = None
_MEDICAL_DOMAINS_MTIME: float = 0.0
_MEDICAL_DEFAULT_DOMAINS = [
    "pubmed.ncbi.nlm.nih.gov",
    "medlineplus.gov",
    "dailymed.nlm.nih.gov",
    "cochranelibrary.com",
]

_TRUSTED_EVIDENCE_DEFAULTS = {
    "ANSWER_BASIS": "live_trusted_source",
    "LIVE_FETCH_STATUS": "success",
    "CONFIDENCE": "normal",
    "DEGRADED_REASON": "",
}

_CURRENT_FACT_MARKERS = {"current", "latest", "now", "today", "price"}

def _load_medical_domains(path: Path) -> list[str]:
    """Load medical domains with mtime-based caching."""
    global _MEDICAL_DOMAINS_CACHE, _MEDICAL_DOMAINS_MTIME
    try:
        mtime = path.stat().st_mtime
    except Exception:
        _MEDICAL_DOMAINS_CACHE = None
        _MEDICAL_DOMAINS_MTIME = 0.0
        return list(_MEDICAL_DEFAULT_DOMAINS)
    if _MEDICAL_DOMAINS_CACHE is not None and mtime == _MEDICAL_DOMAINS_MTIME:
        return _MEDICAL_DOMAINS_CACHE
    try:
        with open(path) as f:
            domains = [line.strip() for line in f if line.strip()]
        _MEDICAL_DOMAINS_CACHE = domains if domains else list(_MEDICAL_DEFAULT_DOMAINS)
        _MEDICAL_DOMAINS_MTIME = mtime
        return _MEDICAL_DOMAINS_CACHE
    except Exception:
        return list(_MEDICAL_DEFAULT_DOMAINS)


def extract_self_analysis_file_reference(
    question: str,
    last_file: str | None = None,
    project_root: Path | None = None,
) -> str | None:
    """Return a relative path if *question* asks to analyze/review/improve a file.

    This is the module-level implementation shared by the execution engine and
    the request pipeline.  It must stay independent of engine instance state so
    it can be called before routing decisions are made.
    """
    root = project_root or _get_root()
    q = question.lower()
    if not any(k in q for k in ("analyze", "analyse", "review", "improve", "inspect")):
        return None

    # Look for quoted or bare file paths ending in .py.  Accept both relative
    # paths and absolute paths that users paste from their terminal.
    matches = re.findall(r"[\'\"]?([\w\-/]+\.py)[\'\"]?", question)
    if matches:
        raw = matches[0]
        candidates: list[Path] = []
        raw_path = Path(raw)
        if raw_path.is_absolute():
            candidates.append(raw_path.resolve())
        # Also try stripping common project prefixes and resolving under root.
        normalized = raw.lstrip("/")
        for prefix in ("lucy-v10/", "lucy-v11/", "lucy/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        candidates.append((root / normalized).resolve())
        for candidate in candidates:
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.exists():
                return str(candidate.relative_to(root))
        return None

    # Look for directory references (e.g. "review tools/router_py").  Require a
    # slash so we do not treat every keyword as a path, and require the target to
    # exist under the project root.
    dir_matches = re.findall(r"[\'\"]?([\w\-/]+)[\'\"]?", question)
    for raw in dir_matches:
        if "/" not in raw:
            continue
        candidates: list[Path] = []
        raw_path = Path(raw)
        if raw_path.is_absolute():
            candidates.append(raw_path.resolve())
        normalized = raw.lstrip("/")
        for prefix in ("lucy-v10/", "lucy-v11/", "lucy/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        candidates.append((root / normalized).resolve())
        for candidate in candidates:
            try:
                candidate.relative_to(root)
            except ValueError:
                continue
            if candidate.is_dir():
                return str(candidate.relative_to(root))

    # Look for module-style dotted paths (e.g. ui_v10.app.panels.control_panel)
    matches = re.findall(r"([\w]+(?:\.[\w]+)+)", question)
    for m in matches:
        converted = m.replace(".", "/") + ".py"
        if "ui_v10" in converted:
            converted = converted.replace("ui_v10", "ui-v10")
        candidate = (root / converted).resolve()
        if candidate.exists():
            return str(candidate.relative_to(root))

    if last_file:
        followup_markers = (
            " it",
            "that file",
            "this file",
            "the file",
            "same file",
            "again",
        )
        if any(marker in q for marker in followup_markers):
            return last_file

    return None


def _trusted_evidence_metadata(
    payload: dict[str, Any] | None,
    *,
    answer_basis: str | None = None,
    live_fetch_status: str | None = None,
    confidence: str | None = None,
    degraded_reason: str | None = None,
) -> dict[str, str]:
    source = payload if isinstance(payload, dict) else {}
    return {
        "ANSWER_BASIS": str(
            source.get("ANSWER_BASIS") or answer_basis or _TRUSTED_EVIDENCE_DEFAULTS["ANSWER_BASIS"]
        ).strip(),
        "LIVE_FETCH_STATUS": str(
            source.get("LIVE_FETCH_STATUS")
            or live_fetch_status
            or _TRUSTED_EVIDENCE_DEFAULTS["LIVE_FETCH_STATUS"]
        ).strip(),
        "CONFIDENCE": str(
            source.get("CONFIDENCE") or confidence or _TRUSTED_EVIDENCE_DEFAULTS["CONFIDENCE"]
        ).strip(),
        "DEGRADED_REASON": str(
            source.get("DEGRADED_REASON")
            or degraded_reason
            or _TRUSTED_EVIDENCE_DEFAULTS["DEGRADED_REASON"]
        ).strip(),
    }

def _is_current_fact_query(question: str) -> bool:
    """Return True when the query asks for current/latest/real-time information."""
    norm = re.sub(r"\s+", " ", (question or "").lower().strip())
    return any(re.search(rf"\b{re.escape(marker)}\b", norm) for marker in _CURRENT_FACT_MARKERS)


def _evidence_has_content(evidence: dict[str, Any] | None) -> bool:
    """Return True when *evidence* actually contains usable content."""
    if not evidence or not isinstance(evidence, dict):
        return False
    return bool(
        evidence.get("context")
        or evidence.get("content")
        or evidence.get("formatted")
        or evidence.get("bounded_response")
        or evidence.get("html_context")
    )


def _load_session_memory_context_with_telemetry(
    query: str = "", depth: str = "auto", mode: str = "local", session_id: str = "default"
) -> tuple[str, dict[str, str]]:
    """
    Load session memory context and capture telemetry.

    Returns:
        Tuple of (context_string, telemetry_dict).
        telemetry_dict contains:
            memory_context_used: "true" or "false"
            memory_mode_used: "local", "augmented", or "none"
            memory_depth_used: "shallow", "deep", or "none"
            memory_top_score: similarity of top match or "none"
            memory_session_injected: session_id of top injected match or "none"
            memory_top_gap: gap between top 1 and top 2 or "none"
    """
    telemetry: dict[str, str] = {
        "memory_context_used": "false",
        "memory_mode_used": "none",
        "memory_depth_used": "none",
        "memory_top_score": "none",
        "memory_session_injected": "none",
        "memory_top_gap": "none",
    }

    # Check if memory is enabled
    if os.environ.get("LUCY_SESSION_MEMORY", "0") != "1":
        return "", telemetry

    # SQLite-first read attempt (summary-aware context assembly)
    try:
        from memory.memory_service import assemble_context_with_telemetry

        context, telemetry = assemble_context_with_telemetry(
            current_session_id=session_id, max_chars=1200, query=query, depth=depth, mode=mode
        )
        if context:
            return context, telemetry
    except Exception:
        logging.warning("SQLite memory read failed, falling back to text file", exc_info=True)

    # Get memory file path (check both runtime and standard env vars)
    mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
    if not mem_file:
        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
    if not mem_file:
        # Resolve default at call time so namespace overrides are honoured.
        mem_file = str(lucy_runtime_namespace_root() / "state" / "chat_session_memory.txt")

    mem_path = Path(mem_file).expanduser()

    try:
        with open(mem_path, "r", encoding="utf-8") as f:
            # Only include lines starting with "User: " or "Assistant: "
            lines = [line.rstrip("\n") for line in f if line.startswith(("User: ", "Assistant: "))]
    except (OSError, FileNotFoundError):
        return "", telemetry

    if not lines:
        return "", telemetry

    # Limit context size (last 16 lines, max 500 chars)
    max_lines = 16
    max_chars = 500
    context = "\n".join(lines[-max_lines:]).strip()

    if len(context) > max_chars:
        context = context[-max_chars:]

    if context:
        telemetry["memory_context_used"] = "true"
        telemetry["memory_mode_used"] = mode
        telemetry["memory_depth_used"] = depth
    return context, telemetry


def _load_session_memory_context(
    query: str = "", depth: str = "auto", mode: str = "local", session_id: str = "default"
) -> str:
    """
    Load session memory context from the chat memory file.

    Backward-compatible wrapper that returns only the context string.
    """
    context, _ = _load_session_memory_context_with_telemetry(
        query, depth, mode, session_id=session_id
    )
    return context
