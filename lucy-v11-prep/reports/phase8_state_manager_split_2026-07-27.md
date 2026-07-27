# Phase 8 Completion Report — Split `tools/router_py/state_manager.py`

**Date:** 2026-07-27  
**Branch:** detached HEAD, `17edfbc` (ahead of `main` at `917e8ec`)  
**Scope:** `tools/router_py/state_manager.py` → `tools/router_py/state/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/state_manager.py` into a focused package:

- `tools/router_py/state/schema.py` — SQLite schema string and `init_database()`
- `tools/router_py/state/queries.py` — low-level SQL operations
- `tools/router_py/state/manager.py` — `StateManager` class and `get_state_manager()` factory
- `tools/router_py/state/__init__.py` — public re-export layer

Then migrate all direct callers and delete the old module.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/state/schema.py` | `SCHEMA_SQL`, `init_database()` |
| `tools/router_py/state/queries.py` | Query helpers accepting `(conn, namespace_id, ...)` |
| `tools/router_py/state/manager.py` | `StateManager` class delegating SQL to `queries.*` |
| `tools/router_py/state/__init__.py` | Public API: `StateManager`, `get_state_manager`, `init_database`, `SCHEMA_SQL` |
| `tools/router_py/test_state_manager_characterization.py` | Characterization tests for the public API |

### Deleted file

- `tools/router_py/state_manager.py`

### Callers migrated

- `tools/router_py/execution_engine_state.py`
- `tools/router_py/execution_engine.py`
- `tools/router_py/test_concurrency.py`
- `tools/router_py/test_resource_leaks.py`
- `tools/router_py/test_state_manager_characterization.py`

All imports now use `from router_py.state import ...`.

### Remaining references

```bash
grep -R "from router_py\.state_manager\|import router_py\.state_manager" \
  --include="*.py" tools/ ui-v10/
```

Result: `No remaining references`

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/state/
```

Result: `All checks passed!`

### Characterization tests

```bash
python3 -m pytest tools/router_py/test_state_manager_characterization.py -q --tb=line
```

Result: `11 passed in 0.22s`

### Broad router suite

The full `tools/router_py/` suite contains pre-existing, long-running live-LLM and real-router burn-in tests that do not complete within practical time limits in this environment. The suite was therefore run with the known slow/live files excluded:

```bash
timeout 300 python3 -m pytest tools/router_py/ \
  --ignore=tools/router_py/test_ollama_cleanup.py \
  --ignore=tools/router_py/test_ollama_heartbeat_model_switch.py \
  --ignore=tools/router_py/test_local_answer.py \
  --ignore=tools/router_py/test_self_analysis.py \
  --ignore=tools/router_py/test_semantic_regression.py \
  --ignore=tools/router_py/test_response_regression.py \
  --ignore=tools/router_py/test_request_tool.py \
  --ignore=tools/router_py/test_health_check.py \
  --ignore=tools/router_py/test_code_review_model_resolver.py \
  --ignore=tools/router_py/test_real_router_burn_in.py \
  --ignore=tools/router_py/test_tube_database_integrity.py \
  --ignore=tools/router_py/test_e2e_hmi_voice.py \
  --ignore=tools/router_py/test_classify.py \
  --ignore=tools/router_py/test_main.py \
  -q --tb=line
```

Result: `686 passed, 7 skipped, 169 subtests passed in 131.36s (0:02:11)`

No Task-8-related regressions were observed.

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Schema/migration unchanged | ✅ | `schema.py` is a verbatim move of `SCHEMA_SQL`; migrations still handled by `schema.apply_migrations` |
| Public API preserved | ✅ | Characterization tests pass; `StateManager` methods and signatures unchanged |
| Callers migrated | ✅ | Grep shows no remaining `router_py.state_manager` imports |
| Old module removed | ✅ | `git rm tools/router_py/state_manager.py` committed |
| Lint clean | ✅ | `ruff check tools/router_py/state/` passes |
| Tests pass | ✅ | 11 characterization tests + 686 broad suite tests pass |
| Scope respected | ✅ | Only `state_manager.py`, new `state/` package, and direct callers touched |

## Known limitations / follow-up

- Two runtime state directories (`state/` and `tools/state/`) are untracked in the working tree. They contain runtime artifacts such as `lucy_state.db` and `last_route.json` from earlier phases/tests. They are not part of this refactor and should be evaluated in a separate cleanup pass.
- The excluded slow/live tests were not run as part of this phase because they require live Ollama endpoints and take 20+ minutes. They are unrelated to the state-manager split.

## Next steps

1. (Recommended) Live-test V11 in its current state before proceeding to the next Phase 8 module split.
2. Continue Phase 8 with the next monolithic split target (e.g., `tools/router_py/policy.py`).
3. Clean up the untracked `state/` and `tools/state/` runtime directories once confirmed obsolete.
