"""JSONL metrics sink for router decisions and context-guard telemetry.

Metrics are appended to a JSONL file under the Lucy runtime directory.
All public functions are wrapped in try/except so metrics failures can never
crash a request.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_METRICS_DIR = Path.home() / ".codex-api-home" / "lucy" / "runtime-v10" / "metrics"
_DEFAULT_METRICS_FILE = _DEFAULT_METRICS_DIR / "routing_metrics.jsonl"

# Module-level sink path. Tests may monkeypatch this to isolate output.
_METRICS_FILE: Path = _DEFAULT_METRICS_FILE
_lock = threading.Lock()


def _now_iso() -> str:
    """Return a UTC ISO-8601 timestamp."""
    return datetime.now(timezone.utc).isoformat()


def _ensure_file(path: Path) -> None:
    """Create parent directories for the metrics file if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _write_line(path: Path, record: dict[str, Any]) -> None:
    """Append a single JSON object as a line to *path*."""
    _ensure_file(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def record_request(
    request_id: str,
    query: str,
    route: str,
    model: str,
    provider: str,
    confidence: float,
    latency_ms: int,
    outcome_code: str,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record a top-level request outcome."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "request",
            "request_id": request_id,
            "query": query,
            "route": route,
            "model": model,
            "provider": provider,
            "confidence": confidence,
            "latency_ms": latency_ms,
            "outcome_code": outcome_code,
        }
        if error:
            record["error"] = error
        if extra:
            record["extra"] = extra
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record request metric", exc_info=True)


def record_context_decision(
    request_id: str,
    query: str,
    kind: str,
    item_summary: str,
    score: float,
    accepted: bool,
    reason: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record a single context-guard accept/reject decision."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "context_decision",
            "request_id": request_id,
            "query": query,
            "kind": kind,
            "item_summary": item_summary[:240],
            "score": score,
            "accepted": accepted,
            "reason": reason,
        }
        if extra:
            record["extra"] = extra
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record context decision metric", exc_info=True)


def record_context_usage(
    request_id: str,
    context_kind: str,
    used: int,
    total: int,
) -> None:
    """Record how many context items were used versus evaluated."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "context_usage",
            "request_id": request_id,
            "context_kind": context_kind,
            "used": used,
            "total": total,
        }
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record context usage metric", exc_info=True)


def record_model_selection_shadow(
    request_id: str,
    query: str,
    route: str,
    manual_model: str | None,
    recommended_model: str,
    competing_model: str,
    reason: str,
    confidence: float,
) -> None:
    """Record a shadow-mode automatic model-selection decision."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "model_selection_shadow",
            "request_id": request_id,
            "query": query,
            "route": route,
            "manual_model": manual_model or "",
            "recommended_model": recommended_model,
            "competing_model": competing_model,
            "reason": reason,
            "confidence": confidence,
        }
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record model selection shadow metric", exc_info=True)


def record_model_latency(
    request_id: str,
    model: str,
    latency_ms: int,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record the actual end-to-end latency for a model choice."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "model_latency",
            "request_id": request_id,
            "model": model,
            "latency_ms": latency_ms,
        }
        if extra:
            record["extra"] = extra
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record model latency metric", exc_info=True)


def record_ab_comparison(
    request_id: str,
    query: str,
    model_a: str,
    model_b: str,
    preferred_model: str,
) -> None:
    """Record the result of a blind A/B comparison."""
    try:
        record: dict[str, Any] = {
            "ts": _now_iso(),
            "type": "ab_comparison",
            "request_id": request_id,
            "query": query,
            "model_a": model_a,
            "model_b": model_b,
            "preferred_model": preferred_model,
        }
        with _lock:
            _write_line(_METRICS_FILE, record)
    except Exception:
        logger.debug("Failed to record A/B comparison metric", exc_info=True)
