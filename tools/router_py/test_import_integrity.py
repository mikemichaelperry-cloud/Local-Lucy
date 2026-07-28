#!/usr/bin/env python3
"""Static import-integrity tests for the Phase 8 module splits.

These tests run in a clean subprocess to ensure that importing a production
module does not execute unwanted side effects (database open, Ollama init, etc.).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.static]

ROOT = Path(__file__).resolve().parent


def _production_module_names():
    """Yield every production .py file under tools/router_py/ as a dotted name."""
    for path in ROOT.rglob("*.py"):
        if path.name.startswith("test_") or path.name.startswith("bench_"):
            continue
        rel = path.relative_to(ROOT.parent)
        parts = rel.with_suffix("").parts
        yield ".".join(parts)


MODULE_NAMES = sorted(set(_production_module_names()))


@pytest.mark.parametrize("module_name", MODULE_NAMES)
def test_module_imports_in_subprocess(module_name: str):
    """Each production module must import without error in a fresh subprocess."""
    cmd = [sys.executable, "-c", f"import {module_name}; print('ok')"]
    result = subprocess.run(
        cmd,
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"Failed to import {module_name}:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "ok" in result.stdout


def test_core_modules_import_without_ollama_or_database():
    """Importing split core modules must not initialize Ollama or open SQLite."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import router_py.classify_core.guards, router_py.classify_core.intent, "
            "router_py.classify_core.memory, router_py.classify_core.router, "
            "router_py.classify_core.select, router_py.local_answer_core.config, "
            "router_py.local_answer_core.engine, router_py.local_answer_core.self_knowledge, "
            "router_py.local_answer_core.utils, router_py.state.schema, "
            "router_py.state.queries; print('ok')"
        ),
    ]
    result = subprocess.run(cmd, cwd=ROOT.parent, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_facades_import_without_circular_imports():
    """The main facades must import together without circular-import errors."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import router_py.classify; import router_py.local_answer; "
            "import router_py.execution_engine; import router_py.state_manager; "
            "import router_py.policy; import router_py.policy_router; "
            "import router_py.news; import router_py.voice; print('ok')"
        ),
    ]
    result = subprocess.run(cmd, cwd=ROOT.parent, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
