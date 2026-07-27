# Phase 8 — Split `tools/router_py/state_manager.py` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tools/router_py/state_manager.py` into a focused `tools/router_py/state/` package (`schema.py`, `queries.py`, `manager.py`) and migrate callers, preserving behavior.

**Architecture:** Move schema/migration helpers to `schema.py`, low-level SQL operations to `queries.py` (functions accept `sqlite3.Connection` and `namespace_id`), and the public `StateManager` class plus factory helpers to `manager.py`. Update the four Python callers to import from `router_py.state`. No compatibility facade remains.

**Tech Stack:** Python 3, pytest, ruff, git

## Global Constraints

- Preserve all existing behavior; no schema or migration changes.
- Remove `tools/router_py/state_manager.py` after callers are migrated.
- Run the full `tools/router_py/` pytest suite after each task; no regressions allowed.
- Run `ruff check tools/router_py/state/` after code changes.
- Commit after each task.
- Do not touch modules outside `state_manager.py` and its direct callers.
- Do not split into domain-specific modules yet (routes/outcomes/sessions/etc. stay together).

---

### Task 1: Add characterization tests

**Files:**
- Create: `tools/router_py/test_state_manager_characterization.py`

**Interfaces:**
- Consumes: existing `router_py.state_manager.StateManager`, `get_state_manager`, `init_database`.
- Produces: passing tests that exercise every public method and must continue to pass after the split.

- [ ] **Step 1: Write the characterization test file**

```python
"""Characterization tests for StateManager public API.

These tests must pass before and after the state_manager.py split.
They use a temporary namespace root so they do not pollute global state.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_state_manager(tmp_path):
    """Return a StateManager backed by a temp namespace DB."""
    db_path = tmp_path / "state" / "lucy_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("LUCY_STATE_DB")
    os.environ["LUCY_STATE_DB"] = str(db_path)
    try:
        from router_py.state_manager import StateManager, get_state_manager, init_database

        assert init_database(db_path) is True
        sm = get_state_manager("characterization")
        yield sm
        sm.close()
    finally:
        if old is None:
            os.environ.pop("LUCY_STATE_DB", None)
        else:
            os.environ["LUCY_STATE_DB"] = old


def test_write_and_read_last_route(tmp_state_manager):
    assert tmp_state_manager.write_route(
        {"intent": "search", "confidence": 0.95, "strategy": "ml", "metadata": {"q": "x"}}
    )
    route = tmp_state_manager.read_last_route()
    assert route is not None
    assert route["intent"] == "search"
    assert route["confidence"] == pytest.approx(0.95)
    assert route["metadata"] == {"q": "x"}


def test_read_routes_pagination(tmp_state_manager):
    for i in range(3):
        assert tmp_state_manager.write_route(
            {"intent": f"intent_{i}", "confidence": 0.5 + i * 0.1}
        )
    routes = tmp_state_manager.read_routes(limit=2, offset=0)
    assert len(routes) == 2
    assert routes[0]["intent"] == "intent_2"


def test_write_and_read_last_outcome(tmp_state_manager):
    assert tmp_state_manager.write_outcome(
        {"success": True, "duration_ms": 150, "result": {"items": 5}}
    )
    outcome = tmp_state_manager.read_last_outcome()
    assert outcome is not None
    assert outcome["success"] is True
    assert outcome["result"] == {"items": 5}


def test_write_batch(tmp_state_manager):
    assert tmp_state_manager.write_batch(
        {"intent": "batch", "confidence": 0.8},
        {"success": True, "duration_ms": 10, "result": {}},
    )
    assert tmp_state_manager.read_last_route()["intent"] == "batch"
    assert tmp_state_manager.read_last_outcome()["success"] is True


def test_read_outcomes_filtering(tmp_state_manager):
    assert tmp_state_manager.write_outcome({"success": True})
    assert tmp_state_manager.write_outcome({"success": False})
    outcomes = tmp_state_manager.read_outcomes(success_only=True, limit=10)
    assert len(outcomes) == 1
    assert outcomes[0]["success"] is True


def test_session_lifecycle(tmp_state_manager):
    assert tmp_state_manager.write_session("s1", {"a": 1}, ttl_seconds=300)
    assert tmp_state_manager.read_session("s1") == {"a": 1}
    assert tmp_state_manager.delete_session("s1") is True
    assert tmp_state_manager.read_session("s1") is None


def test_session_expiration(tmp_state_manager):
    assert tmp_state_manager.write_session("s2", {"a": 1}, ttl_seconds=-1)
    assert tmp_state_manager.read_session("s2") is None


def test_lock_lifecycle(tmp_state_manager):
    assert tmp_state_manager.acquire_lock("lk", timeout=1.0) is True
    assert tmp_state_manager.is_locked("lk") is True
    assert tmp_state_manager.release_lock("lk") is True
    assert tmp_state_manager.is_locked("lk") is False


def test_telemetry(tmp_state_manager):
    assert tmp_state_manager.record_telemetry("evt", {"metric": 1})
    summary = tmp_state_manager.get_telemetry_summary()
    assert summary["total_count"] >= 1
    assert "evt" in summary["event_breakdown"]


def test_health_check(tmp_state_manager):
    health = tmp_state_manager.health_check()
    assert health["connected"] is True
    assert "routes" in health["tables"]


def test_context_manager(tmp_path):
    db_path = tmp_path / "state" / "lucy_state.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    old = os.environ.get("LUCY_STATE_DB")
    os.environ["LUCY_STATE_DB"] = str(db_path)
    try:
        from router_py.state_manager import StateManager

        with StateManager("ctx") as sm:
            assert sm.health_check()["connected"] is True
    finally:
        if old is None:
            os.environ.pop("LUCY_STATE_DB", None)
        else:
            os.environ["LUCY_STATE_DB"] = old
```

- [ ] **Step 2: Run the tests and confirm they pass**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_state_manager_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/test_state_manager_characterization.py
git commit -m "test(state): add StateManager characterization tests before split"
```

---

### Task 2: Create `tools/router_py/state/schema.py`

**Files:**
- Create: `tools/router_py/state/schema.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `SCHEMA_SQL: str`, `init_database(db_path: Optional[Path] = None) -> bool`.

- [ ] **Step 1: Create the schema module**

Create `tools/router_py/state/schema.py`:

```python
#!/usr/bin/env python3
"""SQLite schema and migration helpers for Local Lucy state."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

try:
    from ..schema_migrations import apply_migrations
except ImportError:
    from schema_migrations import apply_migrations


logger = logging.getLogger(__name__)

SCHEMA_SQL = """
-- Enable WAL mode for concurrent access
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- Namespaces for isolation
CREATE TABLE IF NOT EXISTS namespaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Routes table: stores routing decisions
CREATE TABLE IF NOT EXISTS routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    intent TEXT NOT NULL,
    confidence REAL NOT NULL,
    strategy TEXT,
    metadata TEXT,  -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Outcomes table: stores execution results
CREATE TABLE IF NOT EXISTS outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    route_id INTEGER,
    success BOOLEAN NOT NULL,
    duration_ms INTEGER,
    result TEXT,  -- JSON blob
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE,
    FOREIGN KEY (route_id) REFERENCES routes(id) ON DELETE SET NULL
);

-- Sessions table: tracks active sessions
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    session_key TEXT NOT NULL,
    data TEXT,  -- JSON blob
    expires_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(namespace_id, session_key),
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Telemetry table: metrics and events
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    event_data TEXT,  -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Distributed locks table
CREATE TABLE IF NOT EXISTS locks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    namespace_id INTEGER NOT NULL,
    lock_name TEXT NOT NULL,
    owner TEXT NOT NULL,
    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    UNIQUE(namespace_id, lock_name),
    FOREIGN KEY (namespace_id) REFERENCES namespaces(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_routes_namespace_created
    ON routes(namespace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_outcomes_namespace_created
    ON outcomes(namespace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_key
    ON sessions(session_key);
CREATE INDEX IF NOT EXISTS idx_telemetry_namespace_type
    ON telemetry(namespace_id, event_type, created_at);
CREATE INDEX IF NOT EXISTS idx_locks_expires
    ON locks(expires_at);
"""


def init_database(db_path: Optional[Path] = None) -> bool:
    """Initialize database without creating a StateManager instance.

    Useful for setup scripts and migrations.

    Args:
        db_path: Path to database file (default: state/lucy_state.db)

    Returns:
        bool: True if initialization succeeded
    """
    try:
        if db_path is None:
            router_root = Path(__file__).parent.parent.parent
            db_path = router_root / "state" / "lucy_state.db"

        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(db_path), timeout=30.0)
        try:
            version = apply_migrations(conn)
            logger.info(f"Database initialized at {db_path} (version {version})")
            return True
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.state.schema import SCHEMA_SQL, init_database; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/state/schema.py
git commit -m "refactor(state): add schema.py with SCHEMA_SQL and init_database"
```

---

### Task 3: Create `tools/router_py/state/queries.py`

**Files:**
- Create: `tools/router_py/state/queries.py`

**Interfaces:**
- Consumes: `sqlite3.Connection` and `namespace_id: int`.
- Produces: query functions for namespaces, routes, outcomes, sessions, locks, telemetry.

- [ ] **Step 1: Create the queries module**

Create `tools/router_py/state/queries.py` by extracting the SQL bodies from `tools/router_py/state_manager.py`.

Each function must match the signature below and copy its SQL body verbatim from the corresponding `StateManager` method, replacing `self._get_connection()` / `self._transaction()` with the provided `conn: sqlite3.Connection` parameter and using the provided `namespace_id` instead of `self._namespace_id`.

Create the file starting from this header:

```python
#!/usr/bin/env python3
"""Low-level SQLite query operations for Local Lucy state."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
```

Then add these functions, copying implementation from the source method listed:

- `ensure_namespace(conn, namespace)` — copy from `StateManager._ensure_namespace()` (lines ~242-257). Use `conn` directly; do not commit.
- `write_route(conn, namespace_id, route_data)` — copy from `StateManager.write_route()` (lines ~263-306). Do not commit.
- `read_last_route(conn, namespace_id)` — copy from `StateManager.read_last_route()` (lines ~308-346).
- `read_routes(conn, namespace_id, limit=10, offset=0, since=None)` — copy from `StateManager.read_routes()` (lines ~348-402).
- `write_outcome(conn, namespace_id, outcome_data)` — copy from `StateManager.write_outcome()` (lines ~408-453). Do not commit.
- `write_batch(conn, namespace_id, route_data, outcome_data)` — copy from `StateManager.write_batch()` (lines ~455-508). Do not commit.
- `read_last_outcome(conn, namespace_id)` — copy from `StateManager.read_last_outcome()` (lines ~510-544).
- `read_outcomes(conn, namespace_id, success_only=False, limit=10, since=None)` — copy from `StateManager.read_outcomes()` (lines ~546-596).
- `write_session(conn, namespace_id, session_key, data, ttl_seconds=None)` — copy from `StateManager.write_session()` (lines ~602-640). Do not commit.
- `read_session(conn, namespace_id, session_key)` — copy from `StateManager.read_session()` (lines ~642-677). Note: the expired-row `DELETE` and `conn.commit()` inside this read must be preserved exactly as in the original.
- `delete_session(conn, namespace_id, session_key)` — copy from `StateManager.delete_session()` (lines ~679-701). Do not commit.
- `acquire_lock(conn, namespace_id, lock_name, timeout=5.0)` — copy only the body that executes inside one transaction from `StateManager.acquire_lock()` (lines ~733-758). The outer polling loop stays in `manager.py`.
- `release_lock(conn, namespace_id, lock_name, owner)` — copy from `StateManager.release_lock()` (lines ~767-792), accepting `owner` as an argument. Do not commit.
- `is_locked(conn, namespace_id, lock_name)` — copy from `StateManager.is_locked()` (lines ~796-823), including the expired-lock cleanup and `conn.commit()`.
- `record_telemetry(conn, namespace_id, event_type, event_data)` — copy from `StateManager.record_telemetry()` (lines ~829-854). Do not commit.
- `get_telemetry_summary(conn, namespace_id, event_type=None, since=None)` — copy from `StateManager.get_telemetry_summary()` (lines ~856-906).

Rules while copying:

- For write functions, do **not** call `conn.commit()`; the caller (`manager.py`) commits via its transaction context.
- For read functions, use `conn.execute(...)` directly.
- Keep all JSON serialization/deserialization identical to the original code.
- Keep the same return shapes (dict keys, list order, boolean conversions).

- [ ] **Step 2: Verify imports and run a quick smoke test**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.state import queries; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/state/queries.py
git commit -m "refactor(state): add queries.py with low-level state operations"
```

---

### Task 4: Create `tools/router_py/state/manager.py`

**Files:**
- Create: `tools/router_py/state/manager.py`

**Interfaces:**
- Consumes: `router_py.state.schema` (`init_database`), `router_py.state.queries` (all query helpers).
- Produces: `StateManager` class with identical public API, `get_state_manager()`.

- [ ] **Step 1: Create the manager module**

Create `tools/router_py/state/manager.py`. Move the `StateManager` class from `tools/router_py/state_manager.py` and replace inline SQL with calls to `queries.*`. Keep `_get_connection()`, `_transaction()`, `_init_schema()`, `_ensure_namespace()`, `health_check()`, `close()`, `__enter__`, `__exit__`, and `get_state_manager()`.

Create the file starting from this header:

```python
#!/usr/bin/env python3
"""SQLite-backed state manager for Local Lucy."""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from router_py.state import queries, schema

logger = logging.getLogger(__name__)
```

Then copy the `StateManager` class from `tools/router_py/state_manager.py` (lines ~135-976) and make these exact substitutions in each public method:

- `_ensure_namespace(self)`:

```python
with self._transaction() as conn:
    self._namespace_id = queries.ensure_namespace(conn, self.namespace)
return self._namespace_id
```

- `write_route(self, route_data)` → `with self._transaction() as conn: return queries.write_route(conn, self._namespace_id, route_data)`.
- `read_last_route(self)` → `conn = self._get_connection(); return queries.read_last_route(conn, self._namespace_id)`.
- `read_routes(self, limit=10, offset=0, since=None)` → pass `self._get_connection()` and `self._namespace_id` to `queries.read_routes`.
- `write_outcome(self, outcome_data)` → `with self._transaction() as conn: return queries.write_outcome(conn, self._namespace_id, outcome_data)`.
- `write_batch(self, route_data, outcome_data)` → `with self._transaction() as conn: return queries.write_batch(conn, self._namespace_id, route_data, outcome_data)`.
- `read_last_outcome(self)` → `conn = self._get_connection(); return queries.read_last_outcome(conn, self._namespace_id)`.
- `read_outcomes(self, success_only=False, limit=10, since=None)` → pass `self._get_connection()` and `self._namespace_id` to `queries.read_outcomes`.
- `write_session(self, session_key, data, ttl_seconds=None)` → `with self._transaction() as conn: return queries.write_session(conn, self._namespace_id, session_key, data, ttl_seconds)`.
- `read_session(self, session_key)` → `conn = self._get_connection(); return queries.read_session(conn, self._namespace_id, session_key)`.
- `delete_session(self, session_key)` → `with self._transaction() as conn: return queries.delete_session(conn, self._namespace_id, session_key)`.
- `acquire_lock(self, lock_name, timeout=5.0)`: keep the polling loop and `owner = f"{os.getpid()}_{threading.current_thread().ident}"` from the original. Inside the loop, replace the transaction body with:

```python
with self._transaction() as conn:
    queries.acquire_lock(conn, self._namespace_id, lock_name, timeout)
    return True
```

and handle `sqlite3.IntegrityError` as in the original.

- `release_lock(self, lock_name)`:

```python
owner = f"{os.getpid()}_{threading.current_thread().ident}"
try:
    with self._transaction() as conn:
        return queries.release_lock(conn, self._namespace_id, lock_name, owner)
except Exception as e:
    logger.error(f"Failed to release lock: {e}")
    return False
```

- `is_locked(self, lock_name)` → `conn = self._get_connection(); return queries.is_locked(conn, self._namespace_id, lock_name)`.
- `record_telemetry(self, event_type, event_data)` → `with self._transaction() as conn: return queries.record_telemetry(conn, self._namespace_id, event_type, event_data)`.
- `get_telemetry_summary(self, event_type=None, since=None)` → `conn = self._get_connection(); return queries.get_telemetry_summary(conn, self._namespace_id, event_type, since)`.

Keep `health_check()`, `close()`, `__enter__`, `__exit__` unchanged.

At module level, add:

```python
def get_state_manager(namespace: str = "default") -> StateManager:
    return StateManager(namespace=namespace)
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.state.manager import StateManager, get_state_manager; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/state/manager.py
git commit -m "refactor(state): add manager.py with StateManager public API"
```

---

### Task 5: Create `tools/router_py/state/__init__.py`

**Files:**
- Create: `tools/router_py/state/__init__.py`

**Interfaces:**
- Consumes: `manager`, `schema`, `queries`.
- Produces: public re-exports.

- [ ] **Step 1: Create the package init**

```python
#!/usr/bin/env python3
"""Local Lucy state persistence package."""

from router_py.state.manager import StateManager, get_state_manager
from router_py.state.schema import SCHEMA_SQL, init_database

__all__ = ["StateManager", "get_state_manager", "init_database", "SCHEMA_SQL"]
```

- [ ] **Step 2: Verify public imports**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.state import StateManager, get_state_manager, init_database, SCHEMA_SQL; print('ok')"
```

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/state/__init__.py
git commit -m "refactor(state): expose public API via state package __init__.py"
```

---

### Task 6: Migrate callers

**Files:**
- Modify: `tools/router_py/execution_engine_state.py:38`
- Modify: `tools/router_py/execution_engine.py:218`
- Modify: `tools/router_py/test_concurrency.py:24`
- Modify: `tools/router_py/test_resource_leaks.py:25`
- Modify: `tools/router_py/test_state_manager_characterization.py` (import lines)

**Interfaces:**
- No interface change; only import paths change from `router_py.state_manager` to `router_py.state`.

- [ ] **Step 1: Update imports in callers**

Replace in each file:

```python
from router_py.state_manager import StateManager
```

with:

```python
from router_py.state import StateManager
```

Replace:

```python
from router_py.state_manager import get_state_manager
```

with:

```python
from router_py.state import get_state_manager
```

Replace:

```python
from router_py.state_manager import get_state_manager, StateManager
```

with:

```python
from router_py.state import get_state_manager, StateManager
```

- [ ] **Step 2: Update the characterization test imports**

In `tools/router_py/test_state_manager_characterization.py`, change:

```python
from router_py.state_manager import StateManager, get_state_manager, init_database
```

to:

```python
from router_py.state import StateManager, get_state_manager, init_database
```

- [ ] **Step 3: Run caller import checks**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.execution_engine_state import StateWriter"
python3 -c "from router_py.execution_engine import ExecutionEngine"
python3 -c "import router_py.test_concurrency"
python3 -c "import router_py.test_resource_leaks"
python3 -c "import router_py.test_state_manager_characterization"
```

Expected: all imports succeed.

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/execution_engine_state.py \
        tools/router_py/execution_engine.py \
        tools/router_py/test_concurrency.py \
        tools/router_py/test_resource_leaks.py \
        tools/router_py/test_state_manager_characterization.py
git commit -m "refactor(state): migrate callers from state_manager to state package"
```

---

### Task 7: Delete the old `state_manager.py`

**Files:**
- Delete: `tools/router_py/state_manager.py`

**Interfaces:**
- Removes the old monolithic module; all callers now use `router_py.state`.

- [ ] **Step 1: Delete the file**

```bash
rm /home/mike/lucy-v11/tools/router_py/state_manager.py
```

- [ ] **Step 2: Confirm no remaining references in source**

```bash
cd /home/mike/lucy-v11
grep -R "from router_py\.state_manager\|import router_py\.state_manager" --include="*.py" tools/ ui-v10/ || true
```

Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git rm tools/router_py/state_manager.py
git commit -m "refactor(state): remove monolithic state_manager.py"
```

---

### Task 8: Run full tests and lint

**Files:**
- None (verification only).

**Interfaces:**
- Confirm no regressions.

- [ ] **Step 1: Run ruff**

```bash
cd /home/mike/lucy-v11
python3 -m ruff check tools/router_py/state/
```

Expected: `All checks passed!`

- [ ] **Step 2: Run characterization tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_state_manager_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run full router suite**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ -q --tb=line
```

Expected: `931 passed, 12 skipped, 178 subtests passed` (same baseline as before; exact count may shift by the number of new characterization tests).

- [ ] **Step 4: Commit verification results (optional)**

No code changes; just record the final counts in the Phase 8 report.

---

### Task 9: Write the Phase 8 completion report

**Files:**
- Create: `lucy-v11-prep/reports/phase8_state_manager_split_2026-07-27.md`

**Interfaces:**
- No code interface; report documents the change.

- [ ] **Step 1: Write the report**

The report should include:

- Date, branch, V10 preservation statement.
- Objective: split `state_manager.py`.
- New files: `tools/router_py/state/__init__.py`, `schema.py`, `queries.py`, `manager.py`.
- Deleted file: `tools/router_py/state_manager.py`.
- Callers migrated: `execution_engine_state.py`, `execution_engine.py`, `test_concurrency.py`, `test_resource_leaks.py`, plus the characterization tests.
- Verification: grep results, ruff result, pytest summary.
- Gate assessment table.
- Next steps: next Phase 8 module split (e.g., `policy.py`) or live testing.

- [ ] **Step 2: Commit the report**

```bash
git add lucy-v11-prep/reports/phase8_state_manager_split_2026-07-27.md
git commit -m "docs: Phase 8 report for state_manager.py split"
```

---

## Self-review checklist

- [ ] Spec coverage: schema.py, queries.py, manager.py, __init__.py, caller migration, deletion, characterization tests, full suite, lint, report.
- [ ] Placeholder scan: no TBD/TODO/"fill in details".
- [ ] Type consistency: `StateManager` public API unchanged; query helpers accept `(conn, namespace_id, ...)`.
- [ ] Scope: only `state_manager.py` and callers touched; no domain-specific split.
