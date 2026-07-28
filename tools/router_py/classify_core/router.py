"""Embedding / k-NN router lifecycle and decision logging."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import RoutingDecision

_LOGGER = logging.getLogger(__name__)

_ROUTER = None
_ROUTER_LOCK = threading.Lock()


def _get_router():
    """Lazy-load the embedding router (v2)."""
    global _ROUTER
    if _ROUTER is not None:
        return _ROUTER if _ROUTER is not False else None

    with _ROUTER_LOCK:
        if _ROUTER is not None:
            return _ROUTER if _ROUTER is not False else None

        try:
            router_dir = Path(__file__).resolve().parent.parent.parent / "models" / "router"
            if str(router_dir) not in sys.path:
                sys.path.insert(0, str(router_dir))
            from hybrid_router_v2 import HybridRouterV2

            _ROUTER = HybridRouterV2(
                embeddings_path=str(router_dir / "comprehensive_embeddings.npy"),
                examples_path=str(router_dir / "comprehensive_examples.json"),
            )
        except Exception as _exc:
            _LOGGER.error(
                "router_load_failure",
                extra={
                    "exception_type": type(_exc).__name__,
                    "exception_message": str(_exc),
                },
                exc_info=True,
            )
            _ROUTER = False
    return _ROUTER if _ROUTER is not False else None


def prewarm_router() -> bool:
    """Eagerly load the embedding router."""
    try:
        router = _get_router()
        return router is not None
    except Exception:
        return False


def _get_log_path() -> Path | None:
    """Get router decision log path from environment."""
    log_dir = os.environ.get("LUCY_ROUTER_LOG_DIR")
    if log_dir:
        path = Path(log_dir) / "router_decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _log_decision(
    query: str,
    decision: RoutingDecision,
    *,
    embedding_route: str = "",
    guards_fired: list[str] | None = None,
    top_k_neighbours: list[dict] | None = None,
    memory_gate_override: str = "",
) -> None:
    """Log routing decision if logging is enabled."""
    log_path = _get_log_path()
    if not log_path:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "query": query,
            "route": decision.route,
            "intent": decision.intent_family,
            "confidence": decision.confidence,
            "provider": decision.provider,
            "evidence_reason": decision.evidence_reason,
            "policy_reason": decision.policy_reason,
            "embedding_route": embedding_route,
            "guards_fired": guards_fired or [],
            "top_k_neighbours": top_k_neighbours or [],
            "memory_gate_override": memory_gate_override,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
