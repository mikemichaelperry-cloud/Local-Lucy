#!/usr/bin/env python3
"""Tests for user-location persistence and retrieval.

These tests reproduce the failure where the user says "I live in X" and a
later "restaurant in this area" query is answered with the timezone default
instead of the stored location.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_PROJECT_ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "tools"))

from router_py.local_answer_core import self_knowledge
from router_py.local_answer_core.config import LocalAnswerConfig
from router_py.local_answer_core.engine import LocalAnswer


@pytest.fixture
def temp_memory_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create an isolated memory database and point the memory service at it."""
    db_path = tmp_path / "memory.db"
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(db_path))
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))

    # Re-import memory service so it picks up the new env var
    import importlib

    import tools.memory.memory_service as memory_service

    importlib.reload(memory_service)

    # Initialise schema
    conn = sqlite3.connect(str(db_path))
    memory_service._ensure_schema(conn)
    conn.close()

    return db_path


def test_current_context_uses_stored_location(
    temp_memory_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Stored location fact should override timezone-derived location."""
    import tools.memory.memory_service as memory_service

    memory_service.store_persistent_fact(
        "User lives in Kibbutz Magal, Israel.", category="location"
    )

    # Force a timezone that would otherwise produce a different location.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    # Reload module so env var is picked up.
    import importlib

    importlib.reload(self_knowledge)

    context = self_knowledge._get_current_context()
    assert "Kibbutz Magal" in context, context
    assert "Japan" not in context, context


def test_build_prompt_includes_location_for_area_query(
    temp_memory_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A location-aware query should include the stored location fact."""
    import tools.memory.memory_service as memory_service

    memory_service.store_persistent_fact(
        "User lives in Kibbutz Magal, Israel.", category="location"
    )

    import router_py.local_answer_core.engine as engine_module

    monkeypatch.setattr(engine_module, "_start_heartbeat", lambda model: None)
    engine = LocalAnswer(config=LocalAnswerConfig(model="local-lucy-llama31"))
    prompt = engine._build_prompt(
        query="good restaurant in this area open on Saturday",
        session_memory="",
        generation_profile="",
        budget_instruction="",
        conversation_mode_active=False,
        conversation_system_block=False,
        augmented_context="",
    )
    assert "Kibbutz Magal" in prompt, prompt


def test_location_fact_extracted_from_user_statement(temp_memory_db: Path) -> None:
    """A user statement of residence should be extracted and stored."""
    # This test will fail until extraction is implemented in main.py.
    import tools.memory.memory_service as memory_service

    from router_py.main import _extract_location_fact

    _extract_location_fact("Actually I live in Kibbutz Magal in Israel.")

    facts = memory_service.get_persistent_facts(category="location")
    assert any("Kibbutz Magal" in f for f in facts), facts
