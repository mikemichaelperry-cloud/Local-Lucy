# Phase 8 Remaining Splits — Detailed Report

**Date:** 2026-07-29  
**Project:** `/home/mike/lucy-v11`  
**Branch:** `main` (merged from `phase8-remaining-splits`)  
**Author:** Kimi Code CLI / Mike  
**Status:** Complete

---

## Executive Summary

This report documents the completion of the remaining Phase 8 large-module splits in Local Lucy v11. The work recovered from a system reboot, merged a long-lived split branch, and split one additional large production file. All changes preserve public APIs, pass the fast test suite, and keep v11 fully separated from v10.

**Final fast-suite result:** `879 passed, 7 skipped, 267 deselected, 169 subtests passed`.

---

## 1. Background

On 2026-07-29 the user's machine rebooted unexpectedly. At that point:
- The latest desktop handoff (`Local_Lucy_V11_Session_Handoff_2026-07-28.md`) described a completed session about the v11 non-truncating DB desktop shortcut and full archived-memory retrieval.
- The `context_guard.py` split was in progress but uncommitted.
- The `state_manager.py` split was complete on branch `phase8-state-manager-split` but never merged to `main`.
- `streaming_voice.py` was identified as the next large-file split candidate.

This session resumed from that state.

---

## 2. Work Performed

### 2.1 Workspace setup

- Created `.worktrees/` git worktree for isolation, then fell back to a feature branch `phase8-remaining-splits` in the main checkout because the project's authority-root validation expects a directory named `lucy-v11` and the worktree path broke runtime tests.
- Added `.worktrees/` to `.gitignore` on `main`.

### 2.2 context_guard.py split (post-reboot recovery)

**Original file:** `tools/router_py/context_guard.py` (671 lines)

**New package:** `tools/router_py/context_guard/`
- `__init__.py` — public facade, lazy model loaders
- `config.py` — thresholds, model names, penalty constants
- `evidence.py` — evidence relevance scoring
- `memory.py` — memory turn relevance filtering
- `text.py` — keyword/entity extraction helpers

**Commits:**
- `402557b` refactor(context_guard): split monolithic context_guard.py into focused package

**Verification:**
- `python3 -m py_compile tools/router_py/context_guard/*.py` — passed
- `bash scripts/run-fast-tests.sh` — 866 passed, 7 skipped, 169 subtests

**Notes:**
- The original code was already syntactically valid when recovered; only the commit message was cleaned up.

### 2.3 state_manager.py split merge

**Original file:** `tools/router_py/state_manager.py` (1,129 lines)

**Branch merged:** `phase8-state-manager-split` (commits `0445ba7`..`d9b28eb`)

**New package:** `tools/router_py/state/`
- `schema.py` — schema SQL and migration helpers
- `queries.py` — low-level query helpers
- `manager.py` — public `StateManager` class
- `__init__.py` — public exports

**Backward-compatibility fix:** After merging, tests expected `router_py.state_manager` to still exist. Added a thin facade `tools/router_py/state_manager.py` re-exporting `StateManager`, `get_state_manager`, `init_database`, and `SCHEMA_SQL`.

**Commits:**
- `608c2f0` refactor(state): merge completed state_manager.py split branch
- `d221946` fix(state): add backward-compatible state_manager facade after split

**Verification:**
- `python3 -m pytest tools/router_py/test_import_integrity.py tools/router_py/test_split_api_surface.py tools/router_py/test_state_level1_deterministic.py -v` — passed
- `bash scripts/run-fast-tests.sh` — 866 passed, 7 skipped, 169 subtests

**Notes:**
- The split branch was clean and complete; the only issue was the missing facade.
- `.gitignore` was later updated so `tools/router_py/state/` is not treated as runtime state.

### 2.4 streaming_voice.py split

**Original file:** `tools/router_py/streaming_voice.py` (969 lines)

**New package:** `tools/router_py/streaming_voice/`
- `__init__.py` — public facade, re-exports `StreamingVoicePipeline`, `KokoroWorkerManager`
- `__main__.py` — CLI entry point
- `levels.py` — VU meter / audio level helpers
- `worker.py` — Kokoro availability helpers and `KokoroWorkerManager`
- `text.py` — HTML stripping / TTS text cleaning
- `pipeline.py` — `StreamingVoicePipeline`

**Process:**
1. Added characterization tests (`test_streaming_voice_characterization.py`).
2. Created the package and moved code.
3. Deleted the monolith.
4. Code review found split-introduced regressions.
5. Fixed regressions and cleaned style issues.

**Commits:**
- `6138134` test(streaming_voice): add characterization tests before split
- `d76a165` refactor(streaming_voice): split monolithic streaming_voice.py into focused package
- `32f2571` fix(streaming_voice): correct split-introduced typos and path errors
- `dff7930` style(streaming_voice): remove unused sys import

**Regressions found and fixed:**
1. Use-before-assignment typo in trailing-silence calculation (`trailing_silence` vs `trailing_samples`).
2. Missing import of `_get_ui_v10_python` in `pipeline.py`.
3. Worker script path off by one directory level.
4. Project-root traversal off by one level in `_get_ui_v10_python`.

**Verification:**
- `python3 -m pytest tools/router_py/test_streaming_voice_characterization.py -v` — 4 passed
- `python3 -m pytest tools/router_py/test_request_pipeline_contract.py::test_voice_streaming_uses_unified_pipeline -v` — 1 passed
- `bash scripts/run-fast-tests.sh` — 875 passed, 7 skipped, 169 subtests

### 2.5 Final review fixes

After the final whole-branch review, the following Important issues were addressed:

1. **context_guard private constants lost old names** — Added backward-compatible aliases (`_EVIDENCE_THRESHOLD`, `_MEMORY_THRESHOLD`, etc.) in `context_guard/__init__.py`.
2. **Missing context_guard characterization tests** — Added `test_context_guard_characterization.py`.
3. **voice_runtime.py bare streaming_voice import** — Changed to `from router_py.streaming_voice import StreamingVoicePipeline` and removed unnecessary `sys.path` insertion.

Additional Minor cleanups:
- Removed unused `import sys` from `streaming_voice/worker.py`.
- Removed unused `cursor = conn.cursor()` from `state/manager.py`.
- Replaced `Optional[str]` with `str | None` in `context_guard/memory.py` and `context_guard/text.py`.
- Switched `state/manager.py` to relative imports.
- Updated `.gitignore` to not ignore `tools/router_py/state/`.

**Commits:**
- `63c9817` fix(context_guard): add backward-compatible aliases for private constants
- `7bd931f` test(context_guard): add characterization tests for the split
- `89e166c` fix(voice_runtime): import streaming_voice through router_py package
- `a6d3e56` style(splits): clean unused imports, cursor, and use relative imports
- `c13dd8b` chore(git): do not ignore tools/router_py/state package

**Verification:**
- `bash scripts/run-fast-tests.sh` — 879 passed, 7 skipped, 267 deselected, 169 subtests

---

## 3. Test Summary

| Test Run | Result |
|---|---|
| Baseline fast suite (before any changes) | 864 passed, 7 skipped, 267 deselected, 169 subtests |
| After context_guard split | 866 passed, 7 skipped, 267 deselected, 169 subtests |
| After state_manager merge + facade | 866 passed, 7 skipped, 267 deselected, 169 subtests |
| After streaming_voice split | 875 passed, 7 skipped, 267 deselected, 169 subtests |
| Final (after review fixes and cleanups) | **879 passed, 7 skipped, 267 deselected, 169 subtests** |

All test runs completed without failures.

---

## 4. Assessment

### What went well

- The recovered `context_guard.py` split was clean and required only a commit.
- The `state_manager.py` split branch merged without conflicts.
- The `streaming_voice.py` split followed the established pattern: characterization tests first, then move code, then verify.
- Split-introduced regressions were caught by code review and fixed before merge.
- Final fast-suite count increased from 864 to 879, reflecting new characterization tests and no lost coverage.

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Split introduces path/import regressions | Code review + full fast suite on every change |
| Public API breakage for callers | Thin facades preserve original import paths |
| `state/` package ignored by `.gitignore` | Added explicit `!tools/router_py/state/` exception |
| Runtime tests fail due to worktree path | Switched to feature branch in main checkout |

### Known remaining issues

- `streaming_voice/__init__.py` still mutates `sys.path` at import time (preserved from monolith). This is a code smell but does not affect current behavior.
- `StreamingVoicePipeline` methods `_strip_html_for_tts` and `_clean_for_tts` shadow standalone functions imported from `.text`. This is confusing but functional.
- `context_guard.__all__` exposes internal singletons (`_ce_model`, `_bi_model`, `_load_ce_model`, `_load_bi_model`) for test patching convenience.

These are Minor and do not block live testing.

---

## 5. Remaining Large Files

The following production files in `tools/router_py/` remain large and are candidates for future splits:

| File | Lines | Risk | Recommendation |
|---|---|---|---|
| `plan_to_pipeline_cli.py` | ~794 | Low | Frozen baseline; do not split |
| `main.py` | ~740 | High | Central orchestrator; defer unless clearly bounded |
| `request_pipeline.py` | ~653 | High | Stage-3 choke point; defer unless clearly bounded |
| `execution_engine_state.py` | ~666 | Medium | State persistence layer; may shrink naturally |
| `voice_recorder.py` | ~528 | Low | Good next candidate |
| `self_analysis.py` | ~496 | Low | Self-contained; candidate after voice_recorder |
| `model_selector.py` | ~477 | Low | Self-contained; candidate after voice_recorder |

Test files over 500 lines (not production modules, but worth noting):

| File | Lines |
|---|---|
| `test_self_analysis.py` | 1,125 |
| `test_local_answer.py` | 989 |
| `test_execution_parity.py` | 912 |
| `test_execution_engine_state.py` | 739 |

---

## 6. Files Changed

Key files added, modified, or deleted:

**Added packages:**
- `tools/router_py/context_guard/`
- `tools/router_py/state/`
- `tools/router_py/streaming_voice/`

**Added tests:**
- `tools/router_py/test_context_guard_characterization.py`
- `tools/router_py/test_streaming_voice_characterization.py`

**Added facades:**
- `tools/router_py/state_manager.py`

**Deleted monoliths:**
- `tools/router_py/context_guard.py`
- `tools/router_py/streaming_voice.py`
- `tools/router_py/state_manager.py` (replaced by `state/` + facade)

**Modified:**
- `.gitignore`
- `tools/router_py/voice_runtime.py`
- `tools/router_py/execution_engine/__init__.py`
- `tools/router_py/execution_engine_state.py`
- `tools/router_py/test_concurrency.py`
- `tools/router_py/test_resource_leaks.py`
- `tools/router_py/test_state_manager_characterization.py`
- `Architecture.md`
- `config/architecture_prompt.txt`

---

## 7. Recommended Next Steps

1. **Live smoke test:** Run a few real queries through v11 (HMI or CLI) to confirm voice, memory, state, and routing still behave normally.
2. **Next split candidate:** `voice_recorder.py` (~528 lines) is a self-contained audio-recording module and the safest next split.
3. **Long-term:** Evaluate whether `main.py` and `request_pipeline.py` can be split without breaking the unified entry point. Defer until lower-risk modules are done.
4. **Architecture docs:** Keep `Architecture.md` and `config/architecture_prompt.txt` in sync after future splits.

---

## 8. Handoff and Report Locations

- Detailed report: `docs/reports/Phase8_Remaining_Splits_Report_2026-07-29.md`
- Session handoff: `dev_notes/SESSION_HANDOFF_2026-07-29T22-00-00+0300.md`
- Updated architecture: `Architecture.md`
- LLM architecture prompt: `config/architecture_prompt.txt`
- Progress ledger: `.superpowers/sdd/progress.md`

Copies on the Desktop:
- `Desktop/Phase8_Remaining_Splits_Report_2026-07-29.md`
- `Desktop/Local_Lucy_V11_Session_Handoff_2026-07-29.md`
- `Desktop/Local_Lucy_V11_Architecture_2026-07-29.md`

---

*End of report.*
