# Phase 7 — StateManager Legacy `.env` Wrapper Removal Design

**Date:** 2026-07-26  
**Branch:** `v11-routing-parity-2026-07-25` in `/home/mike/lucy-v11`  
**Author:** Local Lucy V11 build assistant

## Goal
Remove the dead-code legacy `.env` state wrappers from `tools/router_py/state_manager.py` now that regression mapping is complete and SQLite is the authoritative state store.

## Background

`tools/router_py/state_manager.py` was introduced as the SQLite-backed replacement for shell-based state management. Its docstring and two helper methods were left in place to migrate and backup state to legacy `.env` files during a transition period:

- `migrate_from_env()` — reads `last_route.env` / `last_outcome.env` from the project root and imports them into SQLite.
- `write_env_backup()` — writes key/value pairs to `state_backup.env` in the project root.

A codebase-wide search shows **no callers** for either method. SQLite writes are handled by `write_route()`, `write_outcome()`, and `write_batch()`. The transition period is over.

## Scope

### In scope
- Delete `migrate_from_env()` from `tools/router_py/state_manager.py`.
- Delete `write_env_backup()` from `tools/router_py/state_manager.py`.
- Update the module docstring to remove the `.env` migration/backup narrative.
- Verify no imports or call sites remain.
- Run the `tools/router_py/` pytest suite and `ruff`.

### Out of scope
- The active shell state contract in `runtime_request.py` (`last_route.env`, `last_outcome.env`).
- The outcome telemetry mirror in `tools/router_py/main.py`.
- `.env` path constants in `tools/router_py/execution_engine.py`.
- Legacy namespace diagnostics in `runtime_request.py` / `execution_engine_state.py`.
- `xdg_paths.py` namespace overrides.

These surfaces are intentionally left untouched because they have active callers and shell tests; removing them would require a separate, larger sub-phase.

## Design

The change is a straightforward deletion of unused private helper code:

1. Remove the entire `# Migration from Legacy (.env files)` block (lines ~921–987).
2. Remove the entire `write_env_backup()` method (lines ~989–1026).
3. Update the module-level docstring to state that SQLite is the sole state backend.
4. Confirm with `grep` that `migrate_from_env` and `write_env_backup` no longer appear in the repository outside of this spec.
5. Run tests and lint.

## Risk assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Breaks a hidden caller | Low | Grep confirmed zero call sites; pytest suite will catch import-time errors. |
| Breaks shell tests | None | Shell `.env` contract is out of scope. |
| Lint/formatting | Low | Run `ruff check` on the modified file. |

## Success criteria

- `tools/router_py/state_manager.py` no longer contains `migrate_from_env` or `write_env_backup`.
- `python3 -m pytest tools/router_py/ -q` passes with the same count as before (931 passed, 12 skipped, 178 subtests passed at time of writing).
- `python3 -m ruff check tools/router_py/state_manager.py` passes.

## Next step

After this spec is approved, invoke the `writing-plans` skill to produce the detailed implementation plan.
