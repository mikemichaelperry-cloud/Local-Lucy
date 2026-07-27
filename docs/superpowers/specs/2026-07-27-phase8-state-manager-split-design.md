# Phase 8 — Split `tools/router_py/state_manager.py` Design

**Date:** 2026-07-27  
**Branch:** `main` in `/home/mike/lucy-v11`  
**Author:** Local Lucy V11 build assistant

## Goal

Split the 1,129-line `tools/router_py/state_manager.py` into a small, focused `tools/router_py/state/` package with clear single-responsibility modules. Update callers to import from the new modules. Preserve all existing behavior and keep the full `tools/router_py/` test suite passing.

## Background

`tools/router_py/state_manager.py` currently contains:

- Schema definition (`SCHEMA_SQL`) and standalone `init_database()` helper.
- Low-level SQL operations for namespaces, routes, outcomes, sessions, locks, and telemetry.
- The public `StateManager` class that wraps connection management, transactions, and the higher-level API.
- Module-level helper functions `get_state_manager()` and `init_database()`.
- A `__main__` block with manual smoke tests.

This violates the single-responsibility principle and makes the file hard to navigate. The public API has few callers, so this is a safe first module split for Phase 8.

## Scope

### In scope

- Create `tools/router_py/state/__init__.py`.
- Create `tools/router_py/state/schema.py` and move `SCHEMA_SQL` and `init_database()` into it.
- Create `tools/router_py/state/queries.py` and move low-level SQL operations into it.
- Create `tools/router_py/state/manager.py` and move the `StateManager` class, `get_state_manager()`, and context-manager/utility methods into it.
- Update all callers (`execution_engine_state.py`, tests, etc.) to import from the new modules.
- Add characterization tests that prove behavior is unchanged.
- Remove or deprecate the old `tools/router_py/state_manager.py` file.
- Run the full `tools/router_py/` pytest suite and `ruff`.

### Out of scope

- Refactoring logic inside the moved functions beyond what is required for the split.
- Changing the database schema or migration behavior.
- Splitting `state_manager.py` into domain-specific modules (routes, outcomes, etc.) — that is a future pass.
- Touching any module other than `state_manager.py` and its direct callers.

## Design

### New package layout

```text
tools/router_py/state/
├── __init__.py          # Re-exports the public API for convenience
├── schema.py            # SCHEMA_SQL + init_database()
├── queries.py           # Low-level SQL operations (namespace, route, outcome, session, lock, telemetry)
└── manager.py           # StateManager class + get_state_manager() + health_check()/close()
```

### Module responsibilities

#### `schema.py`

- Exports `SCHEMA_SQL`.
- Exports `init_database(db_path: Optional[Path] = None) -> bool`.
- Imports and calls `apply_migrations` from `schema_migrations`.

#### `queries.py`

- Provides query functions that accept a `sqlite3.Connection` (or a connection factory) and a `namespace_id`.
- Each function returns plain dicts/lists, not `StateManager` state.
- Functions mirror the current SQL in `state_manager.py`:
  - `ensure_namespace(conn, namespace: str) -> int`
  - `write_route(conn, namespace_id: int, route_data: dict) -> bool`
  - `read_last_route(conn, namespace_id: int) -> Optional[dict]`
  - `read_routes(conn, namespace_id: int, limit, offset, since) -> List[dict]`
  - `write_outcome(conn, namespace_id: int, outcome_data: dict) -> bool`
  - `write_batch(conn, namespace_id: int, route_data, outcome_data) -> bool`
  - `read_last_outcome(conn, namespace_id: int) -> Optional[dict]`
  - `read_outcomes(conn, namespace_id: int, success_only, limit, since) -> List[dict]`
  - `write_session(conn, namespace_id: int, session_key, data, ttl_seconds) -> bool`
  - `read_session(conn, namespace_id: int, session_key) -> Optional[dict]`
  - `delete_session(conn, namespace_id: int, session_key) -> bool`
  - `acquire_lock(conn, namespace_id: int, lock_name, timeout) -> bool`
  - `release_lock(conn, namespace_id: int, lock_name, owner) -> bool`
  - `is_locked(conn, namespace_id: int, lock_name) -> bool`
  - `record_telemetry(conn, namespace_id: int, event_type, event_data) -> bool`
  - `get_telemetry_summary(conn, namespace_id: int, event_type, since) -> dict`

Some operations need transaction semantics. `queries.py` functions should accept a connection and leave transaction management to the caller (`manager.py`).

#### `manager.py`

- `StateManager` class with the same public methods as today.
- `_get_connection()`, `_transaction()`, `_init_schema()`, `_ensure_namespace()` stay here.
- Public methods delegate SQL work to `queries.py` while retaining connection/transaction handling.
- `get_state_manager(namespace: str = "default") -> StateManager`.
- `health_check()` and `close()` / context manager stay here.

#### `__init__.py`

Re-export the public API so callers can still use:

```python
from router_py.state import StateManager, get_state_manager, init_database
```

### Caller migration

Files that currently import from `router_py.state_manager` will be updated:

- `tools/router_py/execution_engine_state.py`
- Any tests that import `StateManager` or `init_database` directly from `state_manager`.

Replace:

```python
from router_py.state_manager import StateManager, get_state_manager, init_database
```

with:

```python
from router_py.state import StateManager, get_state_manager, init_database
```

### Backward compatibility

No temporary facade file. The old `tools/router_py/state_manager.py` is removed. Callers are migrated in the same commit. Because there are few callers, this is low risk.

## Testing strategy

1. **Characterization tests:** Before moving code, add tests that exercise the full public `StateManager` API against a temporary namespace. These tests must pass before and after the split.
2. **Existing suite:** Run `python3 -m pytest tools/router_py/ -q --tb=line` and confirm the same pass/skip/subtest counts as the current baseline.
3. **Import checks:** Verify every updated caller imports cleanly.

## Success criteria

- `tools/router_py/state_manager.py` no longer exists.
- `tools/router_py/state/` package exists with `schema.py`, `queries.py`, `manager.py`, and `__init__.py`.
- All callers import from `router_py.state`.
- `python3 -m pytest tools/router_py/ -q` passes with no failures.
- `python3 -m ruff check tools/router_py/state/` passes.

## Risk assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Missed caller import | Low | Grep for `from router_py.state_manager` and `import router_py.state_manager`. |
| Behavior drift in query functions | Low | Characterization tests cover all public methods. |
| Transaction handling mistakes | Low | Keep transaction context manager in `manager.py`; query functions receive a connection. |
| Test fixtures break | Low | Run full suite after each step. |

## Next step

After this design is approved, invoke the `writing-plans` skill to produce the detailed implementation plan.
