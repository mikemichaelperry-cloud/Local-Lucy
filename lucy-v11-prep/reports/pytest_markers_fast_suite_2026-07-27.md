# Fast-Test Suite Report — Pytest Markers

**Date:** 2026-07-27  
**Branch:** `pytest-markers-fast-suite`  
**Goal:** Cut routine test time without losing the ability to run the full suite.

## Changes

- Registered `slow` and `live` pytest markers in `pyproject.toml`.
- Set default `addopts` to exclude `@pytest.mark.slow` and `@pytest.mark.live` tests.
- Marked the following long-running or live-service test modules under `tools/router_py/`:
  - `test_ollama_cleanup.py`
  - `test_ollama_heartbeat_model_switch.py`
  - `test_local_answer.py`
  - `test_self_analysis.py`
  - `test_semantic_regression.py`
  - `test_response_regression.py`
  - `test_request_tool.py`
  - `test_health_check.py`
  - `test_code_review_model_resolver.py`
  - `test_real_router_burn_in.py`
  - `test_tube_database_integrity.py`
  - `test_e2e_hmi_voice.py`
  - `test_classify.py`
  - `test_main.py`
- Created `scripts/run-fast-tests.sh` as a convenience wrapper.

## Verification

### Fast suite

```bash
./scripts/run-fast-tests.sh
```

Result:
```
686 passed, 7 skipped, 261 deselected, 169 subtests passed in 78.78s
```

### Full suite (override marker filter)

```bash
python3 -m pytest tools/router_py/ -m "" -q --tb=line
```

Result:
```
942 passed, 12 skipped in 841.59s
```

## Usage

Run the fast suite during routine development:

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

Run the full suite, including slow/live tests:

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ -m "" -q --tb=line
```

## Notes

- No test behavior or assertions were changed.
- Tests excluded by default are those that exercise live Ollama endpoints, heavy model loads, or long burn-in/regression runs.
- The full suite remains runnable and now completes in ~14 minutes in this environment.
