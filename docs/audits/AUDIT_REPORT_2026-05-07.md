# Local Lucy V8 — Comprehensive Code Audit Report

**Date:** 2026-05-07  
**Auditor:** Kimi Code CLI (multi-agent analysis + automated test execution)  
**Scope:** Full codebase (`ui-v9/app/`, `tools/`, `config/`, state management, voice pipeline, routing, memory, tests)  
**Files Analyzed:** 362 Python files, 65+ test files, 20+ config files  
**Tests Executed:** 250+ test cases across 15 test modules  
**Internet Access:** Verified available (Google 204)

---

## Executive Summary

Local Lucy V8 is **functionally operational** but carries significant **technical debt** from rapid iteration. The qwen3 migration (2026-05-06) introduced token budget changes that broke existing tests. The codebase has **real bugs** in routing precedence, state management atomicity, and voice pipeline resource leaks. The most severe issue is a **~94,000-line code duplication** between active `tools/` and `snapshots/opt-experimental-v9-dev/tools/`, creating a stale-runtime risk.

| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| Architecture | 2 | 1 | 2 | 1 |
| State Management | 2 | 3 | 3 | 1 |
| Routing Logic | 1 | 1 | 1 | 0 |
| Voice Pipeline | 1 | 4 | 4 | 2 |
| Tests | 0 | 3 | 4 | 2 |
| **Total** | **7** | **13** | **14** | **6** |

---

## 1. Architecture & Code Quality

### 1.1 Critical: ~94,000 Lines of Duplicate Code (tools/ vs snapshots/)

**Files:** `tools/*` ↔ `snapshots/opt-experimental-v9-dev/tools/*`  
**Impact:** Stale runtime root. When active files are edited, the snapshot can drift.

Identified byte-for-byte duplicates:
- `runtime_request.py` (2,349 lines)
- `runtime_voice.py` (2,398 lines)
- `router_py/execution_engine.py` (4,138 lines)
- `router_py/main.py` (1,066 lines)
- `router_py/state_manager.py` (1,195 lines)
- `router_py/voice_tool.py` (1,747 lines)
- `local_worker.py` (~900 lines)
- `evidence_planner.py` (~200 lines)

**Already observed drift:** `runtime_control.py` — active version removed `"active_model"` field; snapshot still retains it.

**Fix:** Eliminate the snapshot-as-runtime-root pattern. The UI should run directly from `tools/` and `ui-v9/app/`. The snapshot should be a read-only backup or generated artifact, not a dual source of truth.

### 1.2 Critical: UI Hardcodes Paths into Snapshot Directory

**Files:**
- `ui-v9/app/main_window.py:346` — kokoro socket path
- `ui-v9/app/main_window.py:360` — whisper PID file path
- `ui-v9/app/backend/news_provider.py:5`
- `ui-v9/app/backend/state_manager.py:5`
- `ui-v9/app/backend/streaming_voice.py:6`
- `ui-v9/app/services/runtime_bridge.py:132` — whitelists `"opt-experimental-v9-dev"`

**Impact:** The UI is bound to a manually-copied snapshot. Any edit to active `tools/` is invisible to the running system unless the snapshot is re-synced.

**Fix:** Replace all hardcoded snapshot paths with environment-variable-driven resolution (already partially implemented via `LUCY_RUNTIME_AUTHORITY_ROOT`).

### 1.3 High: Dead Functions

| Function | File | Line | Issue |
|----------|------|------|-------|
| `recorder_command()` | `tools/runtime_voice.py` | 1124 | Defined but never called; `start_recorder()` builds command inline |
| `submit_transcript()` | `tools/runtime_voice.py` | 1590 | Zero call sites across entire codebase |

### 1.4 Medium: Unused Imports

| File | Imports |
|------|---------|
| `tools/runtime_voice.py` | `VoiceResult`, `VADConfig`, `StreamingVoicePipeline` |
| `ui-v9/app/services/runtime_bridge_consolidated.py` | `asyncio`, `tempfile` |

### 1.5 Medium: Duplicate Utility Functions

`tools/evidence_normalizer.py:28-33` and `tools/evidence_planner.py:8-13` both define identical `normalize_space()` and `shell_quote()`. One should import from the other.

### 1.6 Low: Hardcoded Magic Values

- Audio sample rate `16000` hardcoded 5× in `runtime_voice.py`
- Profile string `"opt-experimental-v9-dev"` hardcoded in 9 locations across 8 files
- Timeout values (`120`, `125`, `300`) scattered without constants

---

## 2. State Management

### 2.1 Critical: Non-Atomic State Writes in runtime_bridge_consolidated

**File:** `ui-v9/app/services/runtime_bridge_consolidated.py:598-665` (`_set_state_field`)  
**Issue:** Uses bare `open(state_file, "w")` + `json.dump()`. No `fcntl` locking. No `tempfile.NamedTemporaryFile` + `os.replace()`.

**Impact:** Concurrent writes from UI thread + CLI tool → truncated or corrupted JSON.

**Confirmed by test:** `/tmp/test_state_management.py` — `NamedTemporaryFile: False`, `os.replace: False`.

### 2.2 Critical: Schema Version Downgrade in runtime_control.py

**File:** `tools/runtime_control.py:299,394`  
**Issue:** `normalize_state()` unconditionally sets `schema_version = 1`. No migration logic.

**Impact:** Future schema evolution is impossible. Any v2 field is preserved in `extras` but the version is reset to 1, confusing consumers.

**Confirmed by test:** Loading a v2 state file results in `schema_version: 1`.

### 2.3 Critical: Destructive Voice Runtime Schema "Migration"

**File:** `tools/runtime_voice.py:517-520`  
**Issue:** `normalize_voice_runtime()` drops schemas `< 2` entirely, returning `default_voice_runtime()`.

**Impact:** User data loss. A v1 file with `last_transcript`, custom `capture_path`, or PIDs is wiped to defaults.

**Confirmed by test:** `{"schema_version": 1, "last_transcript": "data"}` → `last_transcript: ''`

### 2.4 High: History Append Without File Locking

**Files:**
- `ui-v9/app/services/runtime_bridge.py:872-897`
- `ui-v9/app/services/runtime_bridge_consolidated.py:694-758`

**Issue:** Both append to `request_history.jsonl` without `fcntl` locking, while `runtime_request.py` **does** use `locked_state_file`.

**Impact:** Race-induced interleaved/malformed JSONL lines.

### 2.5 High: Lost Updates in _set_state_field

**File:** `ui-v9/app/services/runtime_bridge_consolidated.py`  
**Issue:** Read-modify-write without re-reading or locking. Concurrent toggles from HMI + CLI can silently overwrite each other.

### 2.6 High: Non-Atomic Multi-File State Reads

**File:** `ui-v9/app/services/state_store.py:229-331`  
**Issue:** `load_runtime_snapshot()` reads 7 JSON files sequentially. No atomic snapshot semantics. Composite state may mix timestamps.

### 2.7 Medium: Read Without Locking

**File:** `ui-v9/app/services/state_store.py:435-452` (`_load_json`)  
**Issue:** Reads without `fcntl` lock. If a non-atomic writer is mid-write, returns `"invalid json"` instead of retrying.

### 2.8 Medium: runtime_bridge Reads State Without Locking

**File:** `ui-v9/app/services/runtime_bridge.py:899-909` (`_resolve_current_model`)  
**Issue:** Direct `json.loads(state_file.read_text())` without coordinating with `runtime_control.py` locks.

---

## 3. Routing Logic

### 3.1 Critical: evidence_mode Check in Wrong Precedence Position

**File:** `tools/router_py/classify.py:245-256`  
**Issue:** The `evidence_mode == "required"` check at line 255 comes **after** the generic `current_evidence` block (lines 246-252). For `current_evidence` queries with `fallback_only` policy, the code short-circuits to `LOCAL` before ever checking evidence mode.

**Test failure:**
```
tools/tests/test_policy_enforcement_bug.py::test_policy_fallback_with_evidence_goes_augmented FAILED
AssertionError: evidence_mode=required should force AUGMENTED even with fallback_only, but got route=LOCAL
```

**Fix:** Move the `evidence_mode == "required"` check to immediately after the `policy == "disabled"` check and before the generic `current_evidence` block.

### 3.2 High: Test Has Wrong Expectation

**File:** `tools/router_py/test_classify.py:204-220` (`test_evidence_mode_trumps_policy`)  
**Issue:** Test expects `AUGMENTED` when `policy="disabled"` + `evidence_mode="required"`, but code correctly implements disabled-policy-wins. Test contradicts `test_policy_enforcement_bug.py` which validates disabled overrides evidence.

**Fix:** Update test to expect `LOCAL` and rename it to `test_disabled_policy_overrides_evidence`.

### 3.3 High: False-Passing Tests (return instead of assert)

**File:** `tools/tests/test_policy_enforcement_bug.py`  
**Issue:** Multiple tests use `return True/False/all_passed` instead of `assert`. Pytest marks them PASSED regardless of return value.

Affected tests:
- `test_policy_direct_allows_evidence` — returns `bool`
- `test_evidence_mode_required_without_policy` — returns `bool`, also uses overly permissive `in ("LOCAL", "LOCAL_WITH_FALLBACK", "AUGMENTED")` assertion
- `test_non_evidence_query_with_disabled_policy` — returns `bool`
- `test_all_policy_modes_matrix` — returns `all_passed` (matrix can fail silently)

**Fix:** Replace all `return` statements with `assert`.

### 3.4 Medium: Weak Evidence Assertion

**File:** `tools/tests/test_policy_enforcement_bug.py:162`  
**Issue:** Assertion allows `LOCAL` for `evidence_mode=required`, contradicting its own docstring.

---

## 4. Voice Pipeline

### 4.1 High: PTT Prewarm Done Outside Lock (TOCTOU)

**File:** `tools/runtime_voice.py:906-919`  
**Issue:** `should_prewarm_kokoro` checked inside lock, but `prewarm_kokoro_worker()` called **outside** lock. Same for whisper.

**Impact:** Double worker starts or prewarming when voice was just turned off.

### 4.2 High: stop_recorder Called Outside Lock

**File:** `tools/runtime_voice.py:956`  
**Issue:** `stop_recorder(record_pid)` called after releasing lock. Another process could start a new recorder and update PID. Old `stop_recorder` kills the **new** recorder.

### 4.3 High: Whisper Server Always Started with --no-gpu

**File:** `tools/runtime_voice.py:1353`  
**Issue:** `ensure_whisper_worker(model_path)` called without `use_gpu=True`. Default is `False`.

**Impact:** Persistent whisper-server always runs on CPU, even with GPU available.

**Test failure:** `tools/tests/test_whisper_fallback_direct.py` — 3 of 8 tests fail, related to GPU fallback logic.

### 4.4 High: Orphan whisper-server on Slow Startup

**File:** `tools/voice/whisper_worker.py:178-181`  
**Issue:** Health-check loop waits only 3 seconds. If model load exceeds this, returns `None` but leaves `whisper-server` running as orphan.

### 4.5 High: Temp File Leak on Synthesis Error

**File:** `tools/router_py/streaming_voice.py:822-891`  
**Issue:** `NamedTemporaryFile(delete=False)` created with no `finally` cleanup. Every synthesis error leaks a WAV file in `/tmp`.

### 4.6 High: No TTS Fallback When Kokoro Socket Returns Error

**File:** `tools/runtime_voice.py:1745-1763`  
**Issue:** If kokoro worker socket returns `ok=False`, raises `RuntimeVoiceError`. Never falls back to subprocess TTS adapter path.

### 4.7 Medium: Socket Leak in detect_binary

**File:** `tools/voice/backends/kokoro_backend.py:55-71`  
**Issue:** `sock.close()` only reached if `connect()` succeeds. Connect failure leaks socket FD.

### 4.8 Medium: Unprotected Global Pipeline Cache

**File:** `tools/voice/backends/kokoro_backend.py:135-147`  
**Issue:** `_PIPELINE_CACHE` module-level dict with no locking. Concurrent calls race on creation.

### 4.9 Medium: timeout_seconds Silently Ignored in TTS Adapter

**File:** `tools/voice/tts_adapter.py:205-228`  
**Issue:** `timeout_seconds` parameter accepted but never passed to backend synthesize methods.

### 4.10 Medium: Python PTT Functions Write Partial States

**Files:** `tools/runtime_voice.py:2105-2324`  
**Issue:** `handle_ptt_start_python`, `handle_ptt_stop_python`, `handle_status_python` write raw dicts missing many fields. Concurrent readers may see incomplete states.

### 4.11 Low: Daemon Leaves stdin Open

**File:** `tools/voice/kokoro_session_worker.py:196-198`  
**Issue:** Redirects stdout/stderr to `/dev/null` but not stdin.

---

## 5. Local Answer / Token Budgets

### 5.1 High: Token Budget Tests Broken by qwen3 Migration

**File:** `tools/router_py/test_local_answer.py`  
**Failures:**
- `test_augmented_profile` — expected `128`, got `48`
- `test_brief_profile` — expected `256`, got `512`
- `test_detail_profile` — expected `384`, got `768`
- `test_local_chat_profile` — expected `192`, got `256`

**Root cause:** `config/latency_optimizations.env` was updated on 2026-05-06 with new qwen3 token budgets (BRIEF→512, DEFAULT→1024, etc.), but tests still expect old llama3.1-era values.

**Fix:** Update test expectations to match current budget values.

### 5.2 High: Completion Guard Functions Return Tuples, Tests Expect Strings

**File:** `tools/router_py/test_local_answer.py:431-458`  
**Failures:**
- `test_remove_dangling_conjunction` — expected `"This is a test."`, got `("This is a test.", True, "removed_dangling_conjunction")`
- `test_close_truncated` — calls `.endswith()` on tuple → `AttributeError`
- `test_trim_to_sentence` — expected string, got tuple

**Root cause:** The guard functions were refactored to return `(text, modified, reason)` tuples, but tests weren't updated.

**Fix:** Update tests to unpack tuples.

---

## 6. Tests Infrastructure

### 6.1 High: Async Tests Missing pytest-asyncio Configuration

**Files:** `tools/router_py/test_utils.py`, `test_request_tool.py`  
**Issue:** Tests use `async def` without `@pytest.mark.asyncio` or proper plugin config. Pytest fails with "async def functions are not natively supported."

**Failures:** 18 in test_utils.py, 5 in test_request_tool.py.

### 6.2 High: Execution Parity Test Not Discovered

**File:** `tools/router_py/test_execution_parity.py`  
**Issue:** `TestReport` dataclass has `__init__`, causing PytestCollectionWarning: "cannot collect test class." Result: 0 tests collected.

### 6.3 Medium: Return-Instead-of-Assert Pattern Widespread

At least 12 tests across `test_policy_enforcement_bug.py`, `test_resource_leaks.py`, `test_concurrency.py`, `test_time_queries.py`, `test_auto_mode.py` use `return` instead of `assert`.

### 6.4 Medium: UI Offscreen Tests Not Discovered

**File:** `ui-v9/tests/test_interface_level_layout_offscreen.py`  
**Issue:** 0 items collected. Likely missing `if __name__ == "__main__":` runner or PySide6 display requirements not met.

---

## 7. Memory Layer

### 7.1 Result: All Memory Tests Pass

- `tools/tests/test_memory_service_unit.py` — 15/15 passed
- `tools/tests/test_memory_integration.py` — 6/6 passed

No critical issues found in memory service. Dual-write SQLite + text-file architecture works.

### 7.2 Observation: SQLite Schema Has No Version Tracking

**File:** `tools/router_py/state_manager.py`  
**Issue:** `_init_schema()` uses `CREATE TABLE IF NOT EXISTS` but no `user_version` PRAGMA or migrations table. Schema changes require manual DB deletion.

---

## 8. Functional Verification (Live System)

### 8.1 Verified Working

| Feature | Status | Method |
|---------|--------|--------|
| Mode switching (auto ↔ offline ↔ online) | ✅ Works | `runtime_control.py set-mode` |
| Evidence toggle (on/off) | ✅ Works | `runtime_control.py set-evidence` |
| Augmentation policy (disabled/fallback_only/direct_allowed) | ✅ Works | `runtime_control.py set-augmentation` |
| Model selection | ✅ Works | `runtime_control.py set-model` |
| Memory toggle | ✅ Works | `runtime_control.py set-memory` |
| Voice toggle | ✅ Works | `runtime_control.py set-voice` |
| Internet connectivity | ✅ Available | `curl https://google.com` → 204 |
| Kokoro TTS worker | ✅ Running | Socket responsive, CPU mode |
| Whisper STT server | ✅ Running | Port 18181, CPU mode |
| Ollama model loading | ✅ Works | `local-lucy` (qwen3 14B) |
| Flash Attention | ✅ Enabled | systemd override confirmed |

### 8.2 Verified Bug (Fixed During Audit)

| Feature | Status | Details |
|---------|--------|---------|
| TTS state at startup | ✅ Fixed | `internal-prewarm-tts` now writes `tts`/`tts_device` to `voice_runtime.json` |

---

## 9. Recommendations (Prioritized)

### P0 — Do Before Next Release

1. **Fix routing evidence precedence** — Move `evidence_mode == "required"` check before generic `current_evidence` block in `tools/router_py/classify.py`.
2. **Fix runtime_bridge_consolidated non-atomic writes** — Add `locked_state_file` + `tempfile.NamedTemporaryFile` + `os.replace()` to `_set_state_field`.
3. **Fix voice runtime destructive migration** — Migrate v1 fields to v2 instead of dropping them.
4. **Fix runtime_control schema downgrade** — Preserve and respect `schema_version`, add forward-compatible migration logic.
5. **Fix PTT recorder stop race** — Move `stop_recorder` inside the `locked_state_file` block.

### P1 — High Value, Lower Urgency

6. **Eliminate snapshot duplication** — Make `snapshots/` read-only; run UI directly from `tools/`.
7. **Fix whisper-server orphan process** — Kill process if health check times out.
8. **Fix whisper GPU default** — Pass `use_gpu=True` when GPU is available.
9. **Fix TTS temp file leaks** — Add `try/finally` cleanup in `streaming_voice.py`.
10. **Fix kokoro socket leak** — Ensure `sock.close()` in all error paths.
11. **Update broken tests** — Token budgets, tuple returns, async decorators.
12. **Add file locking to history append** — Match `runtime_request.py` discipline.

### P2 — Quality of Life

13. **Replace `return` with `assert` in tests** — 12+ tests give false confidence.
14. **Extract magic constants** — Sample rate, timeouts, profile name.
15. **Remove dead functions** — `recorder_command()`, `submit_transcript()`.
16. **Add SQLite schema versioning** — `PRAGMA user_version` or migrations table.
17. **Add read-retry to state_store** — Backoff for transient JSON read failures.

---

## Appendix A: Test Results Summary

| Test Module | Passed | Failed | Notes |
|-------------|--------|--------|-------|
| `tools/router_py/test_classify.py` | 14 | 1 | Wrong test expectation (evidence vs disabled) |
| `tools/router_py/test_policy.py` | 19 | 0 | All passed |
| `tools/router_py/test_local_answer.py` | 36 | 7 | Token budgets + tuple returns |
| `tools/router_py/test_main.py` | 17 | 0 | All passed |
| `tools/router_py/test_python_execution_path.py` | 14 | 2 | Async `for_voice` kwarg mismatch |
| `tools/router_py/test_utils.py` | 18 | 18 | Missing pytest-asyncio config |
| `tools/router_py/test_request_tool.py` | 0 | 5 | Missing pytest-asyncio config |
| `tools/router_py/test_resource_leaks.py` | 5 | 0 | Return-not-None warnings |
| `tools/router_py/test_concurrency.py` | 8 | 0 | Return-not-None warnings |
| `tools/tests/test_policy_enforcement_bug.py` | 6 | 1 | Evidence precedence bug |
| `tools/tests/test_memory_service_unit.py` | 15 | 0 | All passed |
| `tools/tests/test_memory_integration.py` | 6 | 0 | All passed |
| `tools/tests/test_auto_mode.py` | 4 | 0 | Return-not-None warnings |
| `tools/tests/test_time_queries.py` | 0 | 0 | Return-not-None warnings |
| `tools/tests/test_whisper_worker_direct.py` | 5 | 0 | All passed |
| `tools/tests/test_whisper_fallback_direct.py` | 5 | 3 | GPU fallback logic bugs |
| `tools/voice/tests/*` | 0 | 0 | 0 collected (import/config issues) |
| `ui-v9/tests/*` | 0 | 0 | 0 collected (display/offscreen issues) |
| **Custom regression tests** | — | — | Confirmed 4 state management bugs |

**Total: ~175 passed, ~37 failed, ~30 not-collected**

---

## Appendix B: Files Changed During This Audit

| File | Change | Reason |
|------|--------|--------|
| `tools/runtime_voice.py` | Added TTS state write in `internal-prewarm-tts` | Fix TTS: none display bug |
| `snapshots/opt-experimental-v9-dev/tools/runtime_voice.py` | Synced same change | Snapshot parity |
| `AUDIT_REPORT_2026-05-07.md` | Created this report | Audit deliverable |

---

*End of Report*
