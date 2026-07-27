# Phase 8e Completion Report — Split `tools/router_py/policy_router.py`

**Date:** 2026-07-27  
**Branch:** `phase8-policy-router-split` (HEAD `e3d29a4`, ahead of `main` at `d73f1cd`)  
**Scope:** `tools/router_py/policy_router.py` → `tools/router_py/policy_router/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/policy_router.py` into a focused `tools/router_py/policy_router/` package while keeping both `from policy_router import ...` and `from router_py.policy_router import ...` working unchanged.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/policy_router/__init__.py` | Public re-exports (`PolicyDecision`, `PolicyRouter`) and sys.path setup for direct imports |
| `tools/router_py/policy_router/models.py` | `PolicyDecision` dataclass |
| `tools/router_py/policy_router/gates.py` | All deterministic gate functions and phrase-list constants (renamed from the original `policy_router.py`) |
| `tools/router_py/policy_router/router.py` | `PolicyRouter` class with `DEFAULT_GATES` |

### Deleted/renamed file

- `tools/router_py/policy_router.py` was renamed to `tools/router_py/policy_router/gates.py` (git detects this as a rename).

### Callers

No import changes were required. Existing callers continue to work:

- `from router_py.policy_router import PolicyRouter, PolicyDecision`
  - `tools/router_py/classify.py`
  - `tools/router_py/test_policy_router.py`
  - `tests/test_specific_entity_fact_gate.py`
  - `models/router/collect_real_world_examples.py`
- `from policy_router import PolicyRouter`
  - `models/router/evaluate_holdout.py`

Internal package imports use relative imports (`.models`, `.gates`) so the package works when imported directly as `policy_router`.

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/policy_router/ tools/router_py/classify.py tools/router_py/test_policy_router.py
```

Result: `All checks passed!`

### Policy router unit tests

```bash
python3 -m pytest tools/router_py/test_policy_router.py -q --tb=line
```

Result: `28 passed in 0.07s`

### Specific entity fact gate test

```bash
python3 -m pytest tests/test_specific_entity_fact_gate.py -q --tb=line
```

Result: `1 passed in 0.13s`

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `701 passed, 7 skipped, 261 deselected, 169 subtests passed in 114.46s`

### Direct-import sanity check

```bash
python3 -c "import sys; sys.path.insert(0, 'tools/router_py'); from policy_router import PolicyRouter, PolicyDecision; print('direct ok')"
# -> direct ok

python3 -c "import sys; sys.path.insert(0, 'tools'); from router_py.policy_router import PolicyRouter, PolicyDecision; print('router_py ok')"
# -> router_py ok
```

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | `test_policy_router.py` and `test_specific_entity_fact_gate.py` pass; public API unchanged |
| Callers migrated | ✅ | No import changes needed; both `policy_router` and `router_py.policy_router` resolve |
| Old module removed | ✅ | `policy_router.py` renamed to `policy_router/gates.py` |
| Lint clean | ✅ | `ruff check` passes on package and callers |
| Fast suite passes | ✅ | 701 passed, no regressions |
| Scope respected | ✅ | Only `policy_router.py` split into `policy_router/` package; no caller logic changed |

## Notes

- The `gates.py` module still contains all gate implementations; a future deeper split could separate individual gates (weather, finance, medical, etc.) into their own modules, but that was deferred to keep the change low-risk.
- `PolicyRouter.DEFAULT_GATES` remains unchanged in behavior and ordering.
- Relative imports inside the package keep direct `from policy_router import ...` working for `models/router/` scripts that add only `tools/router_py` to `sys.path`.

## Next steps

Continue Phase 8 with the next module split. Recommended order:
1. `tools/router_py/local_answer.py`
2. `tools/router_py/execution_engine.py`
3. `tools/router_py/classify.py` (last — highest risk)
