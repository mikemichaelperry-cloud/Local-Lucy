# Local Lucy V11 Spring-Cleanup TODO — Start 2026-07-17

**Goal:** Pay down technical debt, consolidate duplicated paths, and make the codebase easier to reason about and modify.

**Baseline before starting:**
- `cd /home/mike/lucy-v10`
- `python3 -m pytest tools/router_py/test_self_analysis.py tools/router_py/test_local_answer.py tools/router_py/test_code_review_model_resolver.py ui-v10/tests/test_self_analysis_mode_offscreen.py -q` → 111 passed
- `ruff check tools/router_py ui-v10/app ui-v10/tests && ruff format --check tools/router_py ui-v10/app ui-v10/tests` → clean

---

## Phase 1: State consolidation and config standardization

- [ ] Audit every place runtime state is read/written:
  - `tools/runtime_control.py`
  - `tools/router_py/execution_engine.py`
  - `ui-v10/app/services/runtime_bridge.py`
  - SQLite `StateManager`
  - Namespace files under `state/namespaces/`
- [ ] Define a single typed config object loaded once at startup.
- [ ] Make env vars an override layer, not a parallel source of truth.
- [ ] Remove duplicated toggle normalization logic.
- [ ] Add tests that verify state round-trips correctly.

**Acceptance:** All existing tests pass; no behavior change; fewer `os.environ.get` calls.

---

## Phase 2: Merge duplicate self-review paths

- [ ] Compare `ExecutionEngine` self-analysis dispatch with `tools/runtime_request.py submit-review`.
- [ ] Decide which path owns code review (recommend: `ExecutionEngine`).
- [ ] Migrate useful behavior from the loser into the winner.
- [ ] Delete the loser and its tests.
- [ ] Update any HMI/runtime_bridge references.

**Acceptance:** Only one code-review entry point remains; all tests pass.

---

## Phase 3: Split `tools/router_py/local_answer.py`

- [ ] Extract `LocalAnswerConfig` into its own module.
- [ ] Extract Ollama client/call logic.
- [ ] Extract cache logic.
- [ ] Extract heartbeat/warmup logic.
- [ ] Leave `LocalAnswer` facade in place with minimal changes.

**Acceptance:** Each new module is <400 lines; all tests pass.

---

## Phase 4: Split `tools/router_py/execution_engine.py`

- [ ] Extract self-analysis dispatch.
- [ ] Extract medical handling.
- [ ] Extract metrics/telemetry recording.
- [ ] Keep main route execution in `ExecutionEngine`.

**Acceptance:** Each new module has one clear responsibility; all tests pass.

---

## Phase 5: Fix async boundaries

- [ ] Make `CodeReviewModelResolver` async or run `_list_installed_models` via `asyncio.to_thread`.
- [ ] Audit `_call_ollama` and file I/O for blocking calls.
- [ ] Move blocking operations off the event loop.

**Acceptance:** No synchronous network/disk calls inside async paths; tests pass.

---

## Phase 6: Replace hard-coded short-circuits with data

- [ ] Move 807 tube answers into a small knowledge table.
- [ ] Move personal/fact resolver data into the same table or a dedicated facts module.
- [ ] Move fixed policy responses into config/data files.
- [ ] Keep `local_answer.py` free of domain-specific special cases.

**Acceptance:** Adding a new fixed answer does not require editing `local_answer.py`; tests pass.

---

## Phase 7: Add integration tests

- [ ] Add seam tests: HMI → runtime_bridge → execution engine → Ollama client.
- [ ] Add tests for state changes propagating through the system.
- [ ] Add tests for voice bypass in Engineering mode vs normal mode.

**Acceptance:** New integration tests pass; no regressions.

---

## Phase 8: Documentation consolidation

- [ ] Merge `ARCHITECTURE.md` and `Architecture.md` into one authoritative file.
- [ ] Add one-paragraph contract for each major module.
- [ ] Update `AGENTS.md` if build/test commands changed.

**Acceptance:** A new developer can understand the system from `Architecture.md` alone.

---

## Suggested order for tomorrow

1. Phase 1 (low risk, high clarity).
2. Phase 2 (removes confusion).
3. Then pick between Phase 3 or Phase 5 based on what feels more pressing.

**Estimated first session:** Phase 1 only. Do not try to do multiple phases in one go.
