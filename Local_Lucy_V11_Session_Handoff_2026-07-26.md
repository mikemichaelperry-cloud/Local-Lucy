# Local Lucy V11 — Session Handoff

**Date:** 2026-07-26 (evening)  
**Branch:** `main` in `/home/mike/lucy-v11`  
**V10 preserved at:** `/home/mike/lucy-v10` (clean, read-only)  
**Supersedes:** `/home/mike/Desktop/archived_handoffs/Local_Lucy_V11_Session_Handoff_2026-07-25.md`

---

## Current checkpoint

Local Lucy V11 is a **provisional runnable checkpoint**. This session completed Phase 7 and consolidated all prior uncommitted Phase 9/10/11/12 work onto `main`.

- Branch `main` is active with 74 commits ahead of `origin/main`.
- **Phase 7 complete:** `StateManager` legacy `.env` wrappers (`migrate_from_env()`, `write_env_backup()`) removed.
- **Phases 9/10/11/12 artifacts committed:** regression tests, harnesses, accuracy suite, reports, plans, packaging identity files, and the supporting production changes that make them pass.
- **Full router regression suite passes:** 931 passed, 12 skipped, 178 subtests passed.
- **V10 untouched** and source-checksum-valid.
- Next milestone: **live testing**, then Phase 8 — incremental module splitting.

### Repository heads

```text
V11: 66f4a9ef860ea23391ee1f9ce84f443d3a1af8c3 (main, ahead 74)
V10: ec5dcbb3ddb0f67f6c020a1c162190ad2ca89a21
```

### Uncommitted V11 state

```text
?? state/
```

Only the runtime `state/` directory is untracked (gitignored runtime output). All intentional source changes are committed.

---

## Absolute rules (carry forward)

1. `/home/mike/lucy-v10` is read-only.
2. Do not commit, tag, format, test-write, migrate, clean, or modify anything inside V10.
3. Do not copy files back into V10.
4. Do not share writable databases, state, configuration, logs, caches, sockets, PID files, lock files or virtual environments between V10 and V11.
5. Do not begin large module splitting until the working tree is clean and the regression gates pass.
6. Do not introduce compatibility fallbacks merely to make tests pass.
7. Do not silently use mock or test backends in production.
8. Do not skip or weaken tests without explicit justification.
9. Do not perform mass formatting.
10. Do not combine unrelated changes in one commit.
11. Do not redesign components outside the active phase.
12. Stop at a failed gate and fix the root cause before continuing.
13. Preserve all currently working V11 behaviour unless an intentional change is documented and tested.
14. Never expose API keys in reports, commits, logs or command output.

---

## First commands next session

```bash
git -C /home/mike/lucy-v11 status --short --branch
git -C /home/mike/lucy-v11 rev-parse HEAD
git -C /home/mike/lucy-v10 status --short --branch
git -C /home/mike/lucy-v10 rev-parse HEAD
python3 -m pytest /home/mike/lucy-v11/tools/router_py/ -q --tb=line
```

Confirm the working tree is clean (only `state/` untracked), then proceed with live testing or Phase 8.

---

## Agreed execution plan

### Block 1 — Stabilize the running source installation

Goal: V11 is a clean standalone source-tree installation.

- [x] Phase 0 — Freeze the checkpoint
- [x] Phase 1 — Centralize V11 namespace
- [x] Phase 2 — Inventory and baseline the complete inherited test surface
- [x] Phase 4 — Remove unsafe runtime fallbacks
- [x] Phase 5 — Complete isolation verification
- [x] Phase 6 — Secret and repository integrity audit

### Block 2 — Preserve functionality and user continuity

Goal: V11 can reasonably be considered a standalone functional successor to V10.

- [x] Phase 3 — Explicit V10-to-V11 state migration (mandatory)
- [x] Complete full test-parity reconciliation
- [x] Gemma/Llama request-parity and deterministic routing
- [x] Phase 10 — Packaging and installation identity
- [x] Phase 11 — Voice robustness testing
- [x] Phase 7 — Remove remaining compatibility wrappers

### Block 3 — Improve architecture and intelligence

Goal: Cleaner code and measured accuracy improvement.

- [ ] **Phase 8** — incremental module splitting, one module at a time, with characterization tests.
- [x] Phase 9 — routing traces and subject-aware self-capability routing
- [x] Phase 12 — initial 25–40-case accuracy/intuition suite; compare V10 vs V11

### Current decision gate

**Live testing first.** Before starting Phase 8, run V11 through real usage (CLI, HMI, voice if possible) and confirm behavior is satisfactory. Phase 8 starts only after you approve.

---

## Phase 8 readiness

Phase 8 will split oversized modules one at a time. Candidate modules by size (lines):

| Module | Lines | Notes |
|--------|-------|-------|
| `tools/router_py/classify.py` | ~2,859 | Central classifier; highest touch, highest risk. Split last. |
| `tools/router_py/local_answer.py` | ~2,584 | Local answer generation; large but self-contained. |
| `tools/router_py/execution_engine.py` | ~2,456 | Execution pipeline; split with care. |
| `tools/router_py/policy.py` | ~2,392 | Keyword guards; natural split by domain (medical, software, news, etc.). |
| `tools/router_py/policy_router.py` | ~1,835 | Policy routing; could split guard groups. |
| `tools/router_py/voice_tool.py` | ~1,865 | Voice processing; separate backend adapters. |
| `tools/router_py/news_provider.py` | ~1,282 | News provider; already focused. |
| `tools/router_py/state_manager.py` | ~1,129 | State manager; clear schema/query/manager boundaries. |

**Recommended first split:** `tools/router_py/state_manager.py` into:
- `state_manager.py` — public manager API
- `state_schema.py` — schema SQL and migrations
- `state_queries.py` — query helpers

This is low-risk because `state_manager.py` has few external callers and well-defined responsibilities.

A Phase 8 readiness plan has been saved at:
`/home/mike/lucy-v11/docs/superpowers/plans/2026-07-26-phase8-module-splitting-readiness.md`

---

## Known unresolved issues

- Packaging (AppImage, Debian) identity was corrected in committed files but a full end-to-end package build has not been run.
- Voice robustness is proven by automated tests; live microphone/PTT validation should be done before release.
- `PlannerValidator` is wired and unit-tested but the current evidence planner is deterministic; any future LLM planner must call it.
- Session-memory summarisation occasionally times out (unrelated to routing).

---

## Test baseline

- **pytest (full router suite):**
  - `tools/router_py/`: **931 passed, 12 skipped, 178 subtests passed** in ~172s
- **Lint:**
  - `python3 -m ruff check tools/router_py/state_manager.py` → clean

---

## Changes this session

| File / Area | Change |
|-------------|--------|
| `tools/router_py/state_manager.py` | Removed `migrate_from_env()` and `write_env_backup()`; clarified SQLite as sole backend. |
| `docs/superpowers/specs/2026-07-26-phase7-state-env-wrapper-removal-design.md` | Phase 7 design spec. |
| `docs/superpowers/plans/2026-07-26-phase7-state-env-wrapper-removal.md` | Phase 7 implementation plan. |
| `lucy-v11-prep/reports/phase7_state_env_wrapper_removal_2026-07-26.md` | Phase 7 completion report. |
| `tools/router_py/test_request_parity.py`, `model_parity_harness.py`, `request_constraints.py`, `url_provenance.py`, `planner_validator.py`, etc. | Committed Phase 9/10/11/12 artifacts and production changes. |
| `compare_v10_v11_accuracy.py`, `data/evaluation/v10_v11_accuracy_suite.jsonl`, `lucy-v11-prep/reports/phase12_v10_v11_accuracy_results.json` | Phase 12 accuracy suite. |
| `packaging/appimage/local-lucy-v11.desktop` | Phase 10 V11 desktop identity. |

---

## Reference files

- `/home/mike/lucy-v11/docs/superpowers/plans/2026-07-26-phase8-module-splitting-readiness.md`
- `/home/mike/lucy-v11/docs/superpowers/plans/2026-07-26-phase7-state-env-wrapper-removal.md`
- `/home/mike/lucy-v11/docs/superpowers/specs/2026-07-26-phase7-state-env-wrapper-removal-design.md`
- `/home/mike/lucy-v11/lucy-v11-prep/reports/phase7_state_env_wrapper_removal_2026-07-26.md`
- `/home/mike/lucy-v11/lucy-v11-prep/reports/phase9_routing_traces_2026-07-26.md`
- `/home/mike/lucy-v11/lucy-v11-prep/reports/phase10_packaging_report_2026-07-26.md`
- `/home/mike/lucy-v11/lucy-v11-prep/reports/phase11_voice_robustness_2026-07-26.md`
- `/home/mike/lucy-v11/lucy-v11-prep/reports/phase12_accuracy_intuition_2026-07-26.md`
- `/home/mike/lucy-v11/PARITY_REPAIR_REPORT.md`

---

*Next session starts with live testing V11. Approve Phase 8 only when satisfied.*
