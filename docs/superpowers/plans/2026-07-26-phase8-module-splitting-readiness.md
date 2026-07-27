# Phase 8 — Module Splitting Readiness Plan

**Date:** 2026-07-26  
**Branch:** `main` in `/home/mike/lucy-v11`  
**Status:** Not started — awaiting live-test approval and user go-ahead.

## Goal

Incrementally split oversized modules in `tools/router_py/` into smaller, single-responsibility units. Each split must be accompanied by characterization tests so behavior is preserved.

## Global constraints

- Split **one module per session/phase**.
- Preserve all existing behavior unless an intentional change is documented and tested.
- Add characterization tests **before** moving code.
- Run the full `tools/router_py/` pytest suite after each split.
- Run `ruff check` on all touched files.
- Do not rename public APIs unless necessary; if renamed, update all callers.
- Keep V10 read-only and untouched.

## Candidate modules (ranked by risk)

| Priority | Module | Lines | Why split / boundaries |
|----------|--------|-------|------------------------|
| 1 | `tools/router_py/state_manager.py` | ~1,129 | Clear boundaries: schema SQL, migration logic, query helpers, public manager API. Few external callers. |
| 2 | `tools/router_py/policy.py` | ~2,392 | Domain-specific guard lists (medical, software, finance, news, etc.) can become submodules. |
| 3 | `tools/router_py/policy_router.py` | ~1,835 | Individual guard groups (time, weather, finance, news, medical, constraints) can be split out. |
| 4 | `tools/router_py/local_answer.py` | ~2,584 | Prompt builders, post-processors, and response formatters are separable. |
| 5 | `tools/router_py/execution_engine.py` | ~2,456 | Provider dispatch, plan execution, and result assembly are distinct. |
| 6 | `tools/router_py/classify.py` | ~2,859 | Central and heavily wired; split only after lower-risk modules are done. |

## Recommended first module: `state_manager.py`

### Proposed decomposition

- `router_py/state/schema.py` — schema SQL, migration helpers.
- `router_py/state/queries.py` — low-level query helpers (namespaces, routes, outcomes, telemetry, locks).
- `router_py/state/manager.py` — public `StateManager` class that wires schema and queries.

### Why this first

- Few external callers (mainly `execution_engine_state.py` and tests).
- Well-defined internal boundaries.
- Low blast radius if something goes wrong.
- Provides a template for later, riskier splits.

## Pre-flight checklist before Phase 8 starts

- [ ] Working tree is clean on `main` (only `state/` runtime output untracked).
- [ ] Full `tools/router_py/` test suite passes.
- [ ] User has approved live-testing results.
- [ ] A specific module has been chosen for the first split.

## Suggested first task when Phase 8 begins

1. Read `tools/router_py/state_manager.py` and identify internal sections.
2. Create `router_py/state/` package.
3. Move schema SQL and migration helpers to `schema.py`.
4. Move query helpers to `queries.py`.
5. Keep `StateManager` public API unchanged in `manager.py`.
6. Update imports in `state_manager.py` to re-export the public API for backward compatibility.
7. Add characterization tests that assert the public API behaves identically before and after the split.
8. Run full router suite and `ruff`.
9. Commit.
10. Write/update Phase 8 report.

## Next session trigger

Start Phase 8 only after the user explicitly approves following live testing.
