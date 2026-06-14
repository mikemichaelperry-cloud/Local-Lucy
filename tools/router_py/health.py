#!/usr/bin/env python3
"""Local Lucy v10 — Health Check

Lightweight CLI health probe for operational monitoring.

Usage:
    python -m tools.router_py.health          # human-readable
    python -m tools.router_py.health --json   # machine-readable

Returns exit code 0 if healthy, 1 if degraded, 2 if unhealthy.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.request
from pathlib import Path


def _check_ollama() -> dict:
    url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
    tags_url = url.replace("/api/generate", "/api/tags")
    try:
        req = urllib.request.Request(tags_url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return {"status": "healthy", "detail": "Ollama responding"}
    except Exception as exc:
        return {"status": "unhealthy", "detail": f"Ollama unreachable: {exc}"}
    return {"status": "unhealthy", "detail": "Ollama non-200"}


def _check_sqlite() -> dict:
    db_path = Path(os.environ.get("LUCY_STATE_DB", "state/lucy_state.db"))
    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "healthy", "detail": "SQLite writable"}
    except Exception as exc:
        return {"status": "unhealthy", "detail": f"SQLite error: {exc}"}


def _check_embedding_model() -> dict:
    try:
        from sentence_transformers import SentenceTransformer
        model_path = Path("models/router/finetuned_minilm")
        if model_path.exists():
            _ = SentenceTransformer(str(model_path))
            return {"status": "healthy", "detail": "Embedding model loaded"}
        return {"status": "degraded", "detail": "No finetuned model; fallback to default MiniLM"}
    except Exception as exc:
        return {"status": "degraded", "detail": f"Embedding load warning: {exc}"}


def _check_searxng() -> dict:
    try:
        req = urllib.request.Request("http://127.0.0.1:8080/", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status == 200:
                return {"status": "healthy", "detail": "SearXNG responding"}
    except Exception:
        pass
    return {"status": "degraded", "detail": "SearXNG not reachable (optional)"}


def _check_voice() -> dict:
    voice_runtime = Path(os.environ.get("LUCY_VOICE_RUNTIME_FILE", "runtime/state/voice_runtime.json"))
    if not voice_runtime.exists():
        return {"status": "healthy", "detail": "Voice idle (no runtime file)"}
    try:
        data = json.loads(voice_runtime.read_text())
        state = data.get("state", "idle")
        if state in ("idle", "ready"):
            return {"status": "healthy", "detail": f"Voice {state}"}
        return {"status": "degraded", "detail": f"Voice state: {state}"}
    except Exception as exc:
        return {"status": "degraded", "detail": f"Voice runtime unreadable: {exc}"}


def run(*, output_json: bool = False) -> int:
    checks = {
        "ollama": _check_ollama(),
        "sqlite": _check_sqlite(),
        "embedding_model": _check_embedding_model(),
        "searxng": _check_searxng(),
        "voice": _check_voice(),
    }

    worst = max(
        checks.values(),
        key=lambda c: {"healthy": 0, "degraded": 1, "unhealthy": 2}[c["status"]],
    )["status"]

    result = {
        "status": worst,
        "checks": checks,
    }

    if output_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Local Lucy Health: {worst.upper()}")
        print("-" * 40)
        for name, check in checks.items():
            icon = {"healthy": "✓", "degraded": "!", "unhealthy": "✗"}[check["status"]]
            print(f"  [{icon}] {name:20s} {check['status']:10s} — {check['detail']}")

    return {"healthy": 0, "degraded": 1, "unhealthy": 2}[worst]


if __name__ == "__main__":
    use_json = "--json" in sys.argv
    sys.exit(run(output_json=use_json))
