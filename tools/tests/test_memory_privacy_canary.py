#!/usr/bin/env python3
"""Synthetic privacy-canary tests for expanded memory window.

Verifies that a synthetic canary stored in persistent memory is only retrieved
when relevant, does not leak into unrelated responses, and is not transmitted
in outbound web/evidence requests.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

CANARY = "LL-PRIVACY-CANARY-8A61"
CANARY_FACT = f"The user's private activation phrase is {CANARY}."


@pytest.fixture
def isolated_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated runtime namespace and memory DB."""
    namespace = tmp_path / "namespace"
    state_dir = namespace / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "memory.db"

    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(namespace))
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
    monkeypatch.setenv("LUCY_WARMUP_ENABLED", "0")
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
    monkeypatch.setenv("LUCY_EVIDENCE_ENABLED", "1")
    monkeypatch.setenv("LUCY_ENABLE_INTERNET", "1")

    import tools.memory.memory_service as memory_service

    conn = sqlite3.connect(str(db_path))
    memory_service._ensure_schema(conn)
    conn.close()
    return namespace


@pytest.fixture
def captured_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Block outbound HTTP and capture every URL the backend tries to fetch."""
    urls: list[str] = []

    def _blocking_urlopen(req: Any, *args: Any, **kwargs: Any) -> Any:
        url = req.full_url if hasattr(req, "full_url") else str(req)
        urls.append(url)
        raise urllib.error.URLError("network disabled in canary test")

    monkeypatch.setattr(urllib.request, "urlopen", _blocking_urlopen)
    return urls


def test_canary_is_stored_and_retrieved(isolated_namespace: Path) -> None:
    """A synthetic canary fact can be stored and retrieved by relevant query."""
    import tools.memory.memory_service as memory_service

    memory_service.store_persistent_fact(CANARY_FACT, category="privacy")
    facts = memory_service.get_relevant_persistent_facts(
        f"What is my activation phrase? {CANARY}",
        category="privacy",
        limit=3,
    )
    assert any(CANARY in f for f in facts), f"Canary not retrieved: {facts}"


def test_canary_not_retrieved_for_unrelated_query(isolated_namespace: Path) -> None:
    """An unrelated query must not retrieve the canary fact."""
    import tools.memory.memory_service as memory_service

    memory_service.store_persistent_fact(CANARY_FACT, category="privacy")
    facts = memory_service.get_relevant_persistent_facts(
        "What is the capital of France?",
        category="privacy",
        limit=3,
    )
    assert not any(CANARY in f for f in facts), f"Canary leaked to unrelated query: {facts}"


def test_canary_not_sent_in_web_fetch_urls(
    isolated_namespace: Path,
    captured_urls: list[str],
) -> None:
    """The canary must not appear in outbound URLs for an unrelated query."""
    import tools.memory.memory_service as memory_service
    from router_py.request_pipeline import process

    memory_service.store_persistent_fact(CANARY_FACT, category="privacy")

    outcome, _, _ = process("What is the capital of France?")
    assert outcome.status == "completed"

    decoded = " ".join(urllib.parse.unquote(u) for u in captured_urls)
    assert CANARY not in decoded, f"Canary found in outbound URLs: {captured_urls}"


def test_canary_not_sent_when_force_local(
    isolated_namespace: Path,
    captured_urls: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With force_local active, no outbound request containing the canary is made."""
    import tools.memory.memory_service as memory_service
    from router_py.request_pipeline import process

    monkeypatch.setenv("LUCY_FORCE_LOCAL", "1")

    memory_service.store_persistent_fact(CANARY_FACT, category="privacy")

    outcome, _, _ = process(f"Tell me about {CANARY}")
    assert outcome.status == "completed"
    # Local Ollama API calls are expected; the canary must not appear in any
    # captured URL (web or local).
    decoded = " ".join(urllib.parse.unquote(u) for u in captured_urls)
    assert CANARY not in decoded, f"Canary leaked to captured URLs under force_local: {captured_urls}"


def test_canary_not_persisted_outside_memory_db(isolated_namespace: Path) -> None:
    """After storage, the canary must only exist in the memory DB, not in chat memory."""
    import tools.memory.memory_service as memory_service

    memory_service.store_persistent_fact(CANARY_FACT, category="privacy")

    # The canary may be in the memory DB.
    db_path = isolated_namespace / "state" / "memory.db"
    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT fact_text FROM persistent_facts").fetchall()
    conn.close()
    assert any(CANARY in r[0] for r in rows)

    # It must not have leaked into the chat session memory file.
    chat_memory = isolated_namespace / "state" / "chat_session_memory.txt"
    if chat_memory.exists():
        assert CANARY not in chat_memory.read_text(encoding="utf-8")
