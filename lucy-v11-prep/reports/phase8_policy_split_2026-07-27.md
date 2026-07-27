# Phase 8d Completion Report — Split `tools/router_py/policy.py`

**Date:** 2026-07-27  
**Branch:** `phase8-policy-split` (HEAD `bc0a3a8`, ahead of `main` at `4371a62`)  
**Scope:** `tools/router_py/policy.py` → `tools/router_py/policy/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/policy.py` into a focused `tools/router_py/policy/` package while keeping `from policy import ...` and `from router_py.policy import ...` working unchanged.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/policy/__init__.py` | Public re-exports and private symbols used by callers |
| `tools/router_py/policy/utils.py` | `_phrase_in_text` helper |
| `tools/router_py/policy/historical.py` | `_is_historical_query` and historical regexes |
| `tools/router_py/policy/finance.py` | `_is_personal_finance_reasoning` and financial anchor regexes |
| `tools/router_py/policy/semantic.py` | MiniLM semantic guard (`_get_semantic_model`, `_semantic_classify`, embedding cache) |
| `tools/router_py/policy/core.py` | `AugmentationPolicy`, `normalize_augmentation_policy`, `requires_evidence_mode`, `provider_usage_class_for`, `manifest_evidence_selection_label` |

### Deleted/renamed file

- `tools/router_py/policy.py` was renamed to `tools/router_py/policy/core.py` (git detects this as a rename).

### Callers

No import changes were required. Both existing import styles continue to work:

- `from router_py.policy import ...` (used by `router_py/__init__.py`, `execution_engine.py`, `classify.py`, `provider_resolver.py`, `request_pipeline.py`, `policy_router.py`, `local_answer.py`, `bench_latency.py`, tests, and `ui-v10/app/backend/`)
- `from policy import ...` (used by `models/router/*` scripts and burn-in tests that add `tools/router_py` to `sys.path`)

Internal package imports use relative imports (`.core`, `.semantic`, etc.) so the package works when imported directly as `policy`.

### Remaining references

```bash
grep -R "from router_py\.policy import\|import router_py\.policy\|from policy import\|import policy" \
  --include="*.py" tools/ ui-v10/ models/router/ tests/
```

All existing references resolve to the new package.

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/policy/
```

Result: `All checks passed!`

### Policy unit tests

```bash
python3 -m pytest tools/router_py/test_policy.py -q --tb=line
```

Result: `25 passed, 1 skipped, 105 subtests passed in 4.83s`

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `701 passed, 7 skipped, 261 deselected, 169 subtests passed in 56.14s`

### Direct-import sanity check

```bash
python3 -c "import sys; sys.path.insert(0, 'tools/router_py'); from policy import requires_evidence_mode; print(requires_evidence_mode('flu symptoms'))"
# -> (True, 'medical_context')

python3 -c "from router_py.policy import requires_evidence_mode; print(requires_evidence_mode('hello'))"
# -> (False, 'default_light')
```

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | `test_policy.py` passes; public API symbols unchanged |
| Callers migrated | ✅ | No import changes needed; both `policy` and `router_py.policy` resolve |
| Old module removed | ✅ | `policy.py` renamed to `policy/core.py` |
| Lint clean | ✅ | `ruff check tools/router_py/policy/` passes |
| Fast suite passes | ✅ | 701 passed, no regressions |
| Scope respected | ✅ | Only `policy.py` split into `policy/` package; no caller logic changed |

## Notes

- `core.py` intentionally retains the full `requires_evidence_mode` implementation with its inline domain guards. A deeper split of the medical/veterinary/finance/conflict guards into separate modules is possible but was left out to avoid risky refactoring of the keyword logic.
- Relative imports inside the package keep both `from policy` and `from router_py.policy` import styles working, which is important for `models/router/` scripts and burn-in tests.
- `tools/router_py/policy/__init__.py` sets `HF_HUB_DISABLE_PROGRESS_BARS` and `TRANSFORMERS_VERBOSITY` before importing the semantic module, preserving the original import-time side effect.

## Next steps

Continue Phase 8 with the next module split. Recommended order:
1. `tools/router_py/policy_router.py`
2. `tools/router_py/local_answer.py`
3. `tools/router_py/execution_engine.py`
4. `tools/router_py/classify.py` (last — highest risk)
