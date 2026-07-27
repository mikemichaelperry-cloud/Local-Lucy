# Pytest Markers for Fast Default Test Suite

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add pytest markers so the default `tools/router_py/` test run excludes slow/live-LLM tests, cutting routine verification time without losing the ability to run the full suite.

**Architecture:** Introduce `slow` and `live` markers in `pyproject.toml`, apply them at module level to the known long-running test files, update default `addopts` to skip them, and provide a convenience script. The full suite remains runnable by overriding the marker filter.

**Tech Stack:** Python 3, pytest, ruff, git

## Global Constraints

- Do not change test behavior or assertions.
- Do not delete tests.
- Preserve the existing `--ignore=tools/router_py/test_synthetic_adversarial.py` default.
- Keep the fast suite under ~5 minutes on this machine.
- Commit after each task.
- Run `ruff check tools/router_py/` after code changes.

---

### Task 1: Register markers in `pyproject.toml`

**Files:**
- Modify: `pyproject.toml:88-104`

**Interfaces:**
- Consumes: existing `[tool.pytest.ini_options]` section.
- Produces: registered `slow` and `live` markers; default `addopts` excludes them.

- [ ] **Step 1: Add marker definitions and update default addopts**

Replace:

```toml
[tool.pytest.ini_options]
testpaths = [
    "tools/router_py",
    "models/router",
    "tools/tests",
    "tools/voice/tests",
    "ui-v10/tests",
    "tests",
    "web_adapter",
]
asyncio_mode = "auto"
filterwarnings = [
    "ignore::pytest.PytestUnraisableExceptionWarning",
    "ignore::ResourceWarning:asyncio.base_events",
    "ignore::ResourceWarning:pytest.unraisableexception",
]
addopts = "--ignore=tools/router_py/test_synthetic_adversarial.py"
```

with:

```toml
[tool.pytest.ini_options]
testpaths = [
    "tools/router_py",
    "models/router",
    "tools/tests",
    "tools/voice/tests",
    "ui-v10/tests",
    "tests",
    "web_adapter",
]
asyncio_mode = "auto"
filterwarnings = [
    "ignore::pytest.PytestUnraisableExceptionWarning",
    "ignore::ResourceWarning:asyncio.base_events",
    "ignore::ResourceWarning:pytest.unraisableexception",
]
addopts = "--ignore=tools/router_py/test_synthetic_adversarial.py -m 'not slow and not live'"
markers = [
    "slow: tests that take more than a few seconds (burn-in, regression, heavy model loads)",
    "live: tests that require a running external service such as Ollama or the network",
]
```

- [ ] **Step 2: Verify pytest loads the config without errors**

Run:
```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ --collect-only -q 2>&1 | tail -5
```

Expected: collection completes, no marker warnings.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore(test): register slow/live pytest markers and skip them by default"
```

---

### Task 2: Mark slow/live test modules in `tools/router_py/`

**Files:**
- Modify: the following test modules (all under `tools/router_py/`):
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

**Interfaces:**
- Consumes: the `slow` and `live` markers registered in Task 1.
- Produces: module-level `pytestmark` that causes the default run to skip these files.

- [ ] **Step 1: Add marker declarations to each file**

For each file above, add at the top of the module (after the shebang/docstring if present):

```python
import pytest

pytestmark = [pytest.mark.slow, pytest.mark.live]
```

If the file already contains `import pytest`, do not add a duplicate import; only add the `pytestmark` line.

- [ ] **Step 2: Verify imports and collection**

Run:
```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ --collect-only -q 2>&1 | tail -10
```

Expected: collection completes without import errors.

- [ ] **Step 3: Run ruff**

```bash
cd /home/mike/lucy-v11
python3 -m ruff check tools/router_py/
```

Expected: `All checks passed!` (ruff per-file ignores already cover test files).

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/test_ollama_cleanup.py \
        tools/router_py/test_ollama_heartbeat_model_switch.py \
        tools/router_py/test_local_answer.py \
        tools/router_py/test_self_analysis.py \
        tools/router_py/test_semantic_regression.py \
        tools/router_py/test_response_regression.py \
        tools/router_py/test_request_tool.py \
        tools/router_py/test_health_check.py \
        tools/router_py/test_code_review_model_resolver.py \
        tools/router_py/test_real_router_burn_in.py \
        tools/router_py/test_tube_database_integrity.py \
        tools/router_py/test_e2e_hmi_voice.py \
        tools/router_py/test_classify.py \
        tools/router_py/test_main.py
git commit -m "chore(test): mark slow/live router_py test modules"
```

---

### Task 3: Add a fast-test convenience script

**Files:**
- Create: `scripts/run-fast-tests.sh`

**Interfaces:**
- Consumes: the default pytest configuration from `pyproject.toml`.
- Produces: a runnable script that executes the fast suite.

- [ ] **Step 1: Create the script**

```bash
#!/usr/bin/env bash
# Run the fast default test suite (excludes slow/live tests).
# To run the full suite including slow/live tests:
#   python3 -m pytest tools/router_py/ -m ""
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest tools/router_py/ -q --tb=line "$@"
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x /home/mike/lucy-v11/scripts/run-fast-tests.sh
```

- [ ] **Step 3: Verify it runs**

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

Expected: suite runs and passes in a few minutes.

- [ ] **Step 4: Commit**

```bash
git add scripts/run-fast-tests.sh
git commit -m "chore(test): add run-fast-tests.sh convenience script"
```

---

### Task 4: Verify timing and document the new workflow

**Files:**
- Modify: `lucy-v11-prep/reports/phase8_state_manager_split_2026-07-27.md` (add a note about the new fast-test command)

**Interfaces:**
- Consumes: the fast-test script and marker configuration.
- Produces: documented commands and measured runtime.

- [ ] **Step 1: Run the fast suite and record timing**

```bash
cd /home/mike/lucy-v11
time ./scripts/run-fast-tests.sh
```

Record the wall time and pass/skip counts.

- [ ] **Step 2: Confirm full suite is still runnable**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/ -m "" -q --tb=line
```

This should still collect and run all tests, including the marked slow/live ones.

- [ ] **Step 3: Append a note to the Phase 8 report**

Add a "Fast-test workflow" section at the end of `lucy-v11-prep/reports/phase8_state_manager_split_2026-07-27.md`:

```markdown
## Fast-test workflow (added after Phase 8 review)

To avoid waiting for the slow/live-LLM tests during routine development:

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

This runs the default `tools/router_py/` suite with `@pytest.mark.slow` and `@pytest.mark.live` tests excluded.

To run the full suite, including slow/live tests:

```bash
python3 -m pytest tools/router_py/ -m "" -q --tb=line
```
```

- [ ] **Step 4: Commit the report update**

```bash
git add lucy-v11-prep/reports/phase8_state_manager_split_2026-07-27.md
git commit -m "docs: document fast-test workflow in Phase 8 report"
```

---

## Self-review checklist

- [ ] Spec coverage: markers registered, slow/live files marked, fast script added, full suite still runnable.
- [ ] Placeholder scan: no TBD/TODO/fill-in-details.
- [ ] Type consistency: N/A.
