# Phase 7 — StateManager Legacy `.env` Wrapper Removal Report

**Date:** 2026-07-26  
**Branch:** `v11-routing-parity-2026-07-25` in `/home/mike/lucy-v11`  
**V10 preserved at:** `/home/mike/lucy-v10` (clean, read-only)  
**Report author:** Local Lucy V11 build assistant

## Objectives

1. Remove the dead-code legacy `.env` migration helper from `StateManager` now that SQLite is the authoritative state store.
2. Remove the dead-code legacy `.env` backup helper that was retained during the SQLite transition.
3. Update the module docstring to remove the migration narrative.
4. Verify no source references remain and that the router test suite and lint still pass.

## Files changed

| Path | Change |
|------|--------|
| `tools/router_py/state_manager.py` | Removed `migrate_from_env()` and `write_env_backup()`; updated module docstring. |

## Methods removed

### `migrate_from_env(env_path: Optional[Path] = None) -> bool`

Read `last_route.env` / `last_outcome.env` from the repository root and imported their key/value pairs into SQLite. No callers existed; the SQLite store has been authoritative for multiple releases.

### `write_env_backup(key: str, value: str) -> bool`

Wrote key/value pairs to `state_backup.env` for backward compatibility during the transition. No callers existed; the transition is complete.

Both methods were pure deletions with no replacement interface.

## Implementation commits

| Commit | Subject | Files | Lines |
|--------|---------|-------|-------|
| `67c0b75` | `docs(state_manager): remove legacy .env migration narrative` | `tools/router_py/state_manager.py` | −5 |
| `50a33cc` | `refactor(state_manager): remove migrate_from_env legacy wrapper` | `tools/router_py/state_manager.py` | −69 |
| `36e585a` | `refactor(state_manager): remove write_env_backup legacy wrapper` | `tools/router_py/state_manager.py` | −42 |

## Verification

### No remaining source references

Command:

```bash
grep -R "migrate_from_env\|write_env_backup" \
  --include="*.py" --include="*.sh" \
  tools/ ui-v10/ models/
```

Result: **No source matches.** The only remaining occurrences are in design documents under `docs/superpowers/specs/` and `docs/superpowers/plans/`.

### Lint

Command:

```bash
python3 -m ruff check tools/router_py/state_manager.py
```

Result:

```
All checks passed!
```

### Router test suite

Command:

```bash
python3 -m pytest tools/router_py/ -q --tb=line
```

Result:

```
931 passed, 12 skipped, 178 subtests passed in 101.06s (0:01:41)
```

No regressions were introduced by the deletions.

## Phase 7 gate assessment

| Gate | Result |
|------|--------|
| Legacy `.env` migration wrapper removed | ✅ `migrate_from_env()` deleted |
| Legacy `.env` backup wrapper removed | ✅ `write_env_backup()` deleted |
| Module docstring no longer describes `.env` migration | ✅ Docstring updated |
| No remaining source references to removed methods | ✅ `grep` across `tools/`, `ui-v10/`, `models/` returned no matches |
| Router test suite passes | ✅ 931 passed, 12 skipped, 178 subtests passed |
| Lint clean on modified file | ✅ `ruff check tools/router_py/state_manager.py` |
| Scope respected | ✅ Only `tools/router_py/state_manager.py` was modified; no changes to `runtime_request.py`, `main.py`, `execution_engine.py`, or shell tests |

## Notes / follow-up

1. The active shell `.env` state contract (`last_route.env`, `last_outcome.env`) was explicitly out of scope for this phase and remains untouched.
2. Future migration-related work should operate on the SQLite schema through `schema_migrations.py`, not through `.env` files.

## Next steps

Per the handoff plan, the remaining pending phases are:

- **Phase 8** — Incremental module splitting.
- **Phase 12** — Expand the V10 vs V11 accuracy/intuition suite based on real failures observed in live usage.
