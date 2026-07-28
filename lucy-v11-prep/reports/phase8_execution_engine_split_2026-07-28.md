# Phase 8f Completion Report — Split `tools/router_py/execution_engine.py`

**Date:** 2026-07-28  
**Branch:** `phase8-execution-engine-split` (HEAD `1322048`, ahead of `main` at `033c7c6`)  
**Scope:** `tools/router_py/execution_engine.py` → `tools/router_py/execution_engine/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/execution_engine.py` into a focused package while preserving test monkeypatch targets (`router_py.execution_engine.ROOT_DIR` and `router_py.execution_engine.CodeReviewModelResolver`).

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/execution_engine/__init__.py` | `ExecutionEngine` class, `create_execution_engine`, `ROOT_DIR`, `HAS_PROVIDER_MODULES`, and re-exports of helper functions (renamed from the original `execution_engine.py`) |
| `tools/router_py/execution_engine/helpers.py` | Module-level helper functions: `_load_medical_domains`, `extract_self_analysis_file_reference`, `_trusted_evidence_metadata`, `_is_current_fact_query`, `_evidence_has_content`, `_load_session_memory_context_with_telemetry`, `_load_session_memory_context` |

### Deleted/renamed file

- `tools/router_py/execution_engine.py` was renamed to `tools/router_py/execution_engine/__init__.py` (git detects this as a rename).

### Monkeypatch compatibility

Tests patch `router_py.execution_engine.ROOT_DIR`. To keep this working:

- `ROOT_DIR` remains in `execution_engine/__init__.py`.
- `extract_self_analysis_file_reference` (now in `helpers.py`) uses a dynamic `_get_root()` helper that reads `router_py.execution_engine.ROOT_DIR` at call time, so patches are respected.
- `CodeReviewModelResolver` is still imported into `execution_engine/__init__.py`, so `monkeypatch.setattr("router_py.execution_engine.CodeReviewModelResolver", ...)` continues to work.

### Callers

No import changes were required. All existing imports continue to resolve through the package `__init__.py`:

- `from router_py.execution_engine import ExecutionEngine, ExecutionResult, ...`
- `from execution_engine import ExecutionEngine` (used by burn-in tests that add `tools/router_py` to `sys.path`)

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/execution_engine/ \
  tools/router_py/test_self_analysis.py \
  tools/router_py/test_request_pipeline_contract.py \
  tools/router_py/test_request_pipeline.py \
  tools/router_py/test_python_execution_path.py \
  tools/router_py/test_finance_routing.py \
  tools/router_py/test_medical_evidence_routing.py \
  tools/router_py/test_e2e_hmi_voice.py \
  tools/router_py/test_hmi_backend_sync.py
```

Result: `All checks passed!`

### Targeted tests

```bash
python3 -m pytest tools/router_py/test_self_analysis.py \
  tools/router_py/test_request_pipeline.py \
  tools/router_py/test_request_pipeline_contract.py -q --tb=line
```

Result: `33 passed, 44 deselected in 17.56s`

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `701 passed, 7 skipped, 261 deselected, 169 subtests passed in 61.19s`

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | Fast suite passes; targeted self-analysis/request-pipeline tests pass |
| Monkeypatch targets preserved | ✅ | `ROOT_DIR` and `CodeReviewModelResolver` still live in `execution_engine/__init__.py`; dynamic `_get_root()` respects patches |
| Callers migrated | ✅ | No import changes needed |
| Old module removed | ✅ | `execution_engine.py` renamed to `execution_engine/__init__.py` |
| Lint clean | ✅ | `ruff check` passes on package and callers |
| Fast suite passes | ✅ | 701 passed, no regressions |
| Scope respected | ✅ | Only helper functions moved; class and public API unchanged |

## Notes

- This is a conservative split: the `ExecutionEngine` class remains in `__init__.py` to avoid breaking monkeypatch expectations. A deeper split of the class into mixins/engines can be a future phase.
- `helpers.py` sets up `sys.path` so it can still be imported directly if needed, matching the original module's standalone-load behavior.

## Next steps

Continue Phase 8 with the remaining candidates:
1. `tools/router_py/local_answer.py` — needs a supervised plan because tests monkeypatch live heartbeat state.
2. `tools/router_py/classify.py` — highest risk; split last.
