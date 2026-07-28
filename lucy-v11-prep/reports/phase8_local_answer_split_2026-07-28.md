# Phase 8g Completion Report — Split `tools/router_py/local_answer.py`

**Date:** 2026-07-28  
**Branch:** `phase8-local-answer-split` (HEAD `0cd3259`, ahead of `main` at `a80c889`)  
**Scope:** `tools/router_py/local_answer.py` → facade + `tools/router_py/local_answer_core/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/local_answer.py` into a focused subpackage while preserving the live heartbeat state that tests monkeypatch on the `router_py.local_answer` module.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/local_answer_core/__init__.py` | Package marker |
| `tools/router_py/local_answer_core/config.py` | `LocalAnswerConfig`, `AnswerResult`, `LatencyMetrics` |
| `tools/router_py/local_answer_core/self_knowledge.py` | Family facts, persona fragments, self-knowledge, context helpers, `_MODEL_IDENTITIES`, `WATER_WET_RESPONSE` |
| `tools/router_py/local_answer_core/utils.py` | `_OllamaWarmupThread`, `get_gpu_free_vram_mb` |
| `tools/router_py/local_answer_core/logger.py` | `LocalAnswerLogger` |
| `tools/router_py/local_answer_core/engine.py` | `LocalAnswer` class |

### Modified file

- `tools/router_py/local_answer.py` is now a thin facade that:
  - keeps the heartbeat functions/state (`_heartbeat_thread`, `_heartbeat_model`, `_heartbeat_stop`, `_ollama_heartbeat_ping`, `_heartbeat_loop`, `start_ollama_heartbeat`, `stop_ollama_heartbeat`)
  - re-exports all public and test-accessed symbols from `local_answer_core`
  - instantiates `_local_answer_logger`

### Monkeypatch compatibility

Tests patch and inspect heartbeat state on `router_py.local_answer`. To keep this working:

- All heartbeat state and functions remain in `tools/router_py/local_answer.py`.
- `engine.py` accesses the facade logger and `start_ollama_heartbeat` dynamically via `sys.modules` to avoid a circular import, so the facade can import the engine and the engine can call back into the facade at runtime.

### Callers

No import changes were required. Existing imports continue to work:

- `from router_py.local_answer import LocalAnswer, LocalAnswerConfig, ...`
- `from local_answer import LocalAnswer, LocalAnswerConfig, ...` (used by tests that add `tools/router_py` to `sys.path`)

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/local_answer.py tools/router_py/local_answer_core/
```

Result: `All checks passed!`

### Heartbeat monkeypatch test

```bash
python3 -m pytest tools/router_py/test_ollama_heartbeat_model_switch.py -m "slow and live" -q --tb=line
```

Result: `2 passed in 0.25s`

### Direct-import sanity check

```bash
python3 -c "import sys; sys.path.insert(0, 'tools/router_py'); from local_answer import LocalAnswer, LocalAnswerConfig, _MODEL_IDENTITIES; print('direct ok')"
# -> direct ok

python3 -c "import sys; sys.path.insert(0, 'tools'); from router_py.local_answer import LocalAnswer, LocalAnswerConfig, _MODEL_IDENTITIES, get_self_knowledge, start_ollama_heartbeat, _heartbeat_thread; print('router_py ok')"
# -> router_py ok
```

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `701 passed, 7 skipped, 261 deselected, 169 subtests passed in 56.67s`

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | Fast suite passes; heartbeat monkeypatch tests pass |
| Monkeypatch targets preserved | ✅ | Heartbeat state and functions kept in facade; engine uses dynamic lookups |
| Callers migrated | ✅ | No import changes needed |
| Old module refactored | ✅ | `local_answer.py` is now a facade; implementation moved to `local_answer_core/` |
| Lint clean | ✅ | `ruff check` passes |
| Fast suite passes | ✅ | 701 passed, no regressions |
| Scope respected | ✅ | Only `local_answer.py` and new `local_answer_core/` package touched |

## Notes

- The facade pattern was chosen specifically to keep heartbeat state on the `router_py.local_answer` module that tests patch. A same-name package would have broken those tests because submodule state would not be reachable through the facade assignments.
- `engine.py` uses `sys.modules` lookups for `_local_answer_logger` and `start_ollama_heartbeat` to avoid a circular import while still using the facade's instances.

## Next steps

Continue Phase 8 with the final candidate:
1. `tools/router_py/classify.py` — highest risk; split last.
