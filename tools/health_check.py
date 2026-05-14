#!/usr/bin/env python3
"""Health check endpoint for Local Lucy V8.

Verifies the status of critical external services and returns JSON.

Usage:
    python3 tools/health_check.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path
from typing import Any

# Project root
ROOT_DIR = Path(__file__).resolve().parent.parent


def _check_ollama() -> dict[str, Any]:
    """Check if Ollama API is responding."""
    url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/tags")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "status": "healthy",
                "detail": f"Ollama responding; {len(models)} model(s) loaded",
                "models": models,
            }
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


def _check_whisper() -> dict[str, Any]:
    """Check if Whisper worker process is alive."""
    try:
        sys_path = str(ROOT_DIR / "tools")
        if sys_path not in os.sys.path:
            import sys
            sys.path.insert(0, sys_path)
        from voice.whisper_worker import resolve_whisper_worker_pid_file
        pid_file = resolve_whisper_worker_pid_file()
        if not pid_file.exists():
            return {"status": "unhealthy", "detail": "Whisper PID file not found"}
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)  # signal 0 is existence check
        return {"status": "healthy", "detail": f"Whisper worker running (pid {pid})"}
    except ProcessLookupError:
        return {"status": "unhealthy", "detail": "Whisper worker process not found"}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


def _check_router_model() -> dict[str, Any]:
    """Check if router model files exist."""
    embeddings = ROOT_DIR / "models" / "router" / "comprehensive_embeddings.npy"
    examples = ROOT_DIR / "models" / "router" / "comprehensive_examples.json"
    try:
        if not embeddings.exists():
            return {"status": "unhealthy", "detail": f"Missing {embeddings}"}
        if not examples.exists():
            return {"status": "unhealthy", "detail": f"Missing {examples}"}
        return {
            "status": "healthy",
            "detail": f"Router model files present ({embeddings.stat().st_size} bytes)",
        }
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


def _check_state_manager() -> dict[str, Any]:
    """Check if SQLite state DB is accessible."""
    db_path = ROOT_DIR / "state" / "lucy_state.db"
    try:
        if not db_path.exists():
            return {"status": "unhealthy", "detail": f"DB not found: {db_path}"}
        conn = sqlite3.connect(str(db_path), timeout=2.0)
        cur = conn.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return {"status": "healthy", "detail": f"SQLite DB accessible ({db_path})"}
    except Exception as e:
        return {"status": "unhealthy", "detail": str(e)}


def run_health_check() -> dict[str, Any]:
    """Run all health checks and return combined result."""
    checks = {
        "ollama": _check_ollama(),
        "whisper": _check_whisper(),
        "router_model": _check_router_model(),
        "state_manager": _check_state_manager(),
    }
    healthy = all(c["status"] == "healthy" for c in checks.values())
    return {
        "healthy": healthy,
        "checks": checks,
    }


if __name__ == "__main__":
    print(json.dumps(run_health_check(), indent=2))
