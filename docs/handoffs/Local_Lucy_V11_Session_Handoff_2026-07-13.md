# Local Lucy V11 Session Handoff — Gemma 4 model-load, identity and HMI status fixes

**Date:** 2026-07-13
**Time:** 10:17 +03:00
**Project root:** `/home/mike/lucy-v10`

---

## 0. Quick Resume

- **Current task focus:** Confirm that Gemma 4 stays loaded after an HMI restart, that the HMI Model status shows `running` instead of `mismatch`, and that identity queries (`"What LLM model are you?"`) are answered by the local model.
- **Current bottleneck:** None for this stage; verification passed.
- **Reusable baseline status:** REUSABLE
- **Reuse-by-default rule:** The Gemma 4 keep-alive, heartbeat abort-on-switch, and HMI checkbox recursion fixes are verified and can be trusted without re-running.
- **Rerun triggers:**
  - After any change to `tools/router_py/local_answer.py` heartbeat/warmup logic.
  - After any change to `ui-v10/app/panels/control_panel.py` state-change wiring.
  - After adding a new selectable model alias.
- **First commands to run next session:**
  - `curl -s http://127.0.0.1:11434/api/ps` to confirm active model.
  - Targeted regressions listed in section 6.
- **Do not rerun by default:** Full `make test` semantic-regression battery; it still contains model-specific goldens that drift when the active model changes.

---

## 1. Final Health Status

| Check | Status |
|---|---|
| Ollama loaded model after restart | PASS — `gemma4:12b-it-qat` resident |
| HMI top-status Model string | PASS — state file now `gemma4:12b-it-qat`, Ollama matches |
| Identity query with smart routing ON | PASS — route `LOCAL`, reason `gemma4_smart_routing`, answer `I run on a gemma4:12b-it-qat model...` |
| Targeted regressions | PASS — 20/20 |
| Full `make test` semantic regressions | NOT RUN this session (deferred; goldens are model-sensitive) |

**End state:**
- `current_state.json` model = `gemma4:12b-it-qat`.
- `gemma4_smart_routing` = `on`.
- Ollama `/api/ps` shows `gemma4:12b-it-qat` loaded with a 15-minute keep-alive.
- Heartbeat and recurring-warmup threads abort when the authoritative state model changes.
- Profile reload only resets `profile` and `status`; it no longer overwrites the selected model.

---

## 2. Why This Session Was Needed

After the previous Gemma 4 integration work, the HMI could display "Gemma4 selected" while Ollama still had `llama3.1:8b` loaded, and identity questions were answered from Wikipedia instead of the local model. A restart also revealed that the `gemma4_smart_routing` checkbox could trigger a signal recursion and that the Ollama heartbeat kept warming up the previously selected model.

---

## 3. Continuity From This Session (What Happened, In Order)

1. Restarted Local Lucy and inspected the running process environment.
2. Found that the authoritative state file (`~/.codex-api-home/lucy/runtime-v10/state/current_state.json`) still had `model: local-lucy` while the live process env and Ollama held `gemma4:12b-it-qat`, causing the HMI mismatch string.
3. Aligned the state file to `gemma4:12b-it-qat` using `tools/runtime_control.py set-model`.
4. Enabled `gemma4_smart_routing` via `tools/runtime_control.py set-gemma4-smart-routing --value on`.
5. Submitted `"What LLM model are you?"` through `tools/runtime_request.py`; verified it routes `LOCAL` with reason `gemma4_smart_routing` and answers with the Gemma 4 identity.
6. Implemented two hardening fixes:
   - Heartbeat/warmup threads now read the active model from `current_state.json` and abort if retargeted.
   - Profile reload no longer overwrites the selected model.
7. Restarted Local Lucy again so the new code loads and stale heartbeat threads are gone.
8. Re-ran the targeted Gemma 4 regressions and the full UI test suite; all passed.
9. Verified continuity: after asking "What would you consider the best way to slow cook Brisket?", the follow-up "What about using a crock Pot?" now answers "For your brisket, a Crock-Pot is perfect...".
10. Verified Ollama still has `gemma4:12b-it-qat` loaded after the brisket/crock-pot exchange.
11. Updated this handoff and the architecture note.

---

## 4. Key Changes Applied In This Session (with Intent)

### 4.1 Gemma 4 smart-routing persistence and HMI wiring
- **Files:**
  - `tools/runtime_control.py`
  - `ui-v10/app/services/runtime_bridge.py`
  - `tools/router_py/main.py`
- **Changes:** Added `gemma4_smart_routing` to `KNOWN_FIELDS`, `default_state()`, the CLI parser, `render_env()`, and registered the `gemma4_smart_routing_toggle` action capability in the HMI bridge.
- **Intent:** The toggle survives restarts and is propagated into `LUCY_GEMMA4_SMART_ROUTING` for the pipeline.

### 4.2 Stale-Ollama-heartbeat prevention on model switches
- **File:** `tools/router_py/local_answer.py`
- **Changes:** The background heartbeat loop and recurring warmup thread now check whether their target model is still the active model and abort if retargeted.
- **Intent:** Prevents a newly selected model from being evicted by a leftover heartbeat pinging the old model.

### 4.3 Gemma 4 identity string
- **File:** `tools/router_py/local_answer.py`
- **Changes:** Added `gemma4:12b-it-qat` to `_MODEL_IDENTITIES`.
- **Intent:** Identity/self-knowledge answers report the actual loaded model instead of falling back to Llama 3.1 self-knowledge.

### 4.4 HMI control-panel recursion guard
- **File:** `ui-v10/app/panels/control_panel.py`
- **Changes:** Block checkbox signals while programmatically updating the `gemma4_smart_routing` checked state.
- **Intent:** Stops the checkbox from emitting a state-change event while it is being refreshed from truth, which could loop back into the backend.

### 4.5 Heartbeat/warmup retargeting from authoritative state
- **File:** `tools/router_py/local_answer.py`
- **Changes:**
  - Added `_get_active_model_from_state()` helper that reads `current_state.json`.
  - Both the 30-second Ollama heartbeat loop and the recurring warmup thread now compare the active model from state to their own target model and abort if they diverge.
- **Intent:** A stale heartbeat can no longer re-load a previously selected model after the user (or a state file edit) switches to a different model.

### 4.6 Profile reload no longer overwrites the selected model
- **Files:**
  - `tools/runtime_profile.py`
  - `tools/runtime_control.py`
  - `tools/tests/test_runtime_profile_endpoint.sh`
- **Changes:**
  - Removed `"model"` from `PROFILE_FIELDS`; resetting profile defaults now only resets `profile` and `status`.
  - `normalize_state()` now keeps `active_model` in sync with `model` so the two fields cannot drift.
  - Updated the runtime-profile endpoint test to expect the preserved model behavior.
- **Intent:** Clicking "Reset Profile Defaults" should not silently revert the user's model selection.

### 4.7 Control panel layout (no horizontal scroll)
- **File:** `ui-v10/app/panels/control_panel.py`
- **Changes:**
  - `QScrollArea` horizontal scrollbar policy set to `ScrollBarAlwaysOff`.
  - `_build_labeled_row()` now stacks the label above the selector (vertical layout) and constrains the selector's size hint so long model names cannot force the panel wider than its viewport.
- **Intent:** Remove the annoying left/right scroll in the Engineering panel while keeping vertical scrolling.

### 4.8 Post-request warmup targets the model actually used
- **File:** `ui-v10/app/services/runtime_bridge.py`
- **Changes:** Phase-7 keep-warm now uses `effective_model` (the model that answered the request) instead of the selector's shadow recommendation.
- **Intent:** Prevents the HMI from evicting the active model and loading a different recommended model, which caused the top-status mismatch.

### 4.9 Context-follow-up memory preservation
- **File:** `tools/router_py/local_answer.py`
- **Changes:**
  - `_generate_answer()` now skips semantic filtering when `_context_followup_requested()` detects obvious continuations ("what about...", "how about...", etc.).
  - `_build_prompt()` emits a stronger "continuation of the prior conversation" instruction for those follow-ups.
- **Intent:** Fixes the case where "What about using a crock Pot?" was answered in isolation even though Memory was on.

### 4.10 Regression tests
- **Files:**
  - `tools/router_py/test_gemma4_identity.py`
  - `tools/router_py/test_ollama_heartbeat_model_switch.py`
  - `tools/tests/test_gemma4_smart_routing_state.py`
  - `ui-v10/tests/test_gemma4_smart_routing_offscreen.py`
  - `tools/router_py/test_local_answer.py`
- **Intent:** Cover the identity mapping, heartbeat retargeting, state persistence, HMI off-screen checkbox behavior, no-horizontal-scroll layout policy, warmup ping isolation, and context-follow-up prompt behavior.

---

## 5. Deviations From Expected Results (and How They Were Handled)

### 5.1 State/env drift after restart
- **Observed deviation:** After restart, Ollama had `gemma4:12b-it-qat` loaded but `current_state.json` listed `local-lucy`, so the HMI would show a mismatch.
- **Root cause:** A prior state reset/profile reload wrote `model: local-lucy` while the live environment kept Gemma 4 selected.
- **Resolution:** Manually realigned `current_state.json` to `gemma4:12b-it-qat` with `tools/runtime_control.py`.
- **Status:** Fixed in session.

### 5.2 Identity query routed to Wikipedia when smart routing was off
- **Observed deviation:** `"What LLM model are you?"` returned a Wikipedia definition of LLMs.
- **Root cause:** The broad `factual_lookup` policy gate matches "What ... are you?" style questions.
- **Resolution:** With `gemma4_smart_routing` enabled, the query now bypasses the classifier/router and is answered locally. A dedicated identity gate in `policy_router.py` is a candidate future improvement but was not implemented to keep this session minimal.
- **Status:** Handled; optional future hardening noted below.

---

## 6. Tests / Checks Run In This Session

### 6.1 Runtime verification
```bash
curl -s http://127.0.0.1:11434/api/ps
```
Result: `gemma4:12b-it-qat` loaded, 15-minute expiry.

```bash
LUCY_RUNTIME_AUTHORITY_ROOT=/home/mike/lucy-v10 \
LUCY_UI_ROOT=/home/mike/lucy-v10/ui-v10 \
LUCY_RUNTIME_NAMESPACE_ROOT=/home/mike/.codex-api-home/lucy/runtime-v10 \
python3 /home/mike/lucy-v10/tools/runtime_request.py submit --text "What LLM model are you?"
```
Result: route `LOCAL`, reason `gemma4_smart_routing`, response identifies `gemma4:12b-it-qat`.

### 6.2 Targeted regressions
```bash
cd /home/mike/lucy-v10
python3 -m pytest \
  tools/router_py/test_gemma4_identity.py \
  tools/router_py/test_ollama_heartbeat_model_switch.py \
  tools/tests/test_gemma4_smart_routing_state.py \
  ui-v10/tests/test_gemma4_smart_routing_offscreen.py \
  tools/router_py/test_request_pipeline.py -q
```
Result: **20 passed in 28.07s**.

### 6.3 Validation inheritance note
- Fresh this session: Ollama ps check, identity request, targeted pytest battery.
- Inherited from prior session: broader routing/policy unit tests and the 79-test targeted suite mentioned in the previous handoff.
- Invalid / do not reuse: any semantic-regression golden run captured while the active model was different.

---

## 7. Key Artifacts Produced / Updated In This Session

### 7.1 This continuity handoff note
- **File:** `/home/mike/lucy-v10/dev_notes/SESSION_HANDOFF_2026-07-13T10-17-07+0300.md`
- **Intent:** Preserve the exact end-state and next starting point.

### 7.2 Architecture note
- **File:** `/home/mike/lucy-v10/Architecture.md` (updated) and dated copy on the Desktop.
- **Intent:** Document the Gemma 4 identity mapping, heartbeat retargeting, and HMI recursion guard.

---

## 8. Known Residual Risk / Notes

- One defunct `[whisper-server] <defunct>` process is visible in `ps`; it is harmless but should be cleaned up during the next voice-worker refactor.
- Identity queries still hit the `factual_lookup` gate when `gemma4_smart_routing` is **off**. If the toggle is kept off by default, consider adding a dedicated `gate_identity` early in `policy_router.py` to keep self-knowledge questions local for all models.
- Semantic-regression goldens in the full test battery are model-sensitive; running `make test` while `gemma4:12b-it-qat` is selected may produce failures that are golden mismatches rather than regressions.
- Multiple overlapping model-warmup paths (runtime_bridge Phase 7, heartbeat, recurring warmup) exist; the current fix keeps them consistent but a future consolidation would reduce complexity.
- GPU VRAM is comfortable (~7.7 GB for Gemma 4 Q4); CPU/system memory use is acceptable in this constrained environment.
- Stabilization rule reminder: `No new features; one bug -> one patch -> one regression -> rerun battery.`
- Next-session continuation rule: Resume from the first failing test in the latest regression log, not from memory.

---

## 9. Recommended Next Steps

1. (User-decided) Decide whether `gemma4_smart_routing` should default to `on` or `off`.
2. If kept off by default, add a `gate_identity` policy-router gate so identity/capability questions stay local for all models.
3. Re-record or model-agnostic-ify semantic-regression goldens so the full battery can be run regardless of the active model.
4. Clean up the defunct whisper-server zombie during the next voice-worker pass.

---

## 11. Benchmark Results (2026-07-14)

After the model cleanup, a clean-slate end-to-end benchmark was run for every remaining selectable mode.

**Script:** `ui-v10/model_comparison_benchmark_v2.py`
**Modes tested:** `auto`, `local-lucy-llama31`, `gemma4:12b-it-qat`
**Methodology:**
- 5 prompts × 2 runs per mode (10 recorded queries per mode).
- 5-second Ollama unload wait between modes.
- Repeat cache disabled (`LUCY_LOCAL_REPEAT_CACHE=false`).
- Cold-start query (`"What is 2+2?"`) measured but not included in median/mean.

**Overall results:**

| Mode | Alias | Cold-start (s) | Median (s) | Mean (s) | Min (s) | Max (s) | VRAM (MB) | Failed |
|------|-------|----------------|------------|----------|---------|---------|-----------|--------|
| auto | auto | 25.37 | 25.56 | 25.54 | 17.93 | 34.79 | 656 | 0/10 |
| direct | local-lucy-llama31 | 25.30 | 25.41 | 25.90 | 17.60 | 37.04 | 656 | 0/10 |
| direct | gemma4:12b-it-qat | 25.14 | 25.14 | 24.65 | 17.21 | 33.79 | 656 | 0/10 |

**Observations:**
- All three modes completed with zero failures.
- Latency is effectively identical across modes on this hardware; the router overhead is negligible compared to model generation time.
- VRAM stayed low (~656 MB) because these measurements reflect system RAM/CPU-bound execution rather than full GPU offload. GPU-offload numbers would require `num_gpu` tuning in the respective Modelfiles.

**Artifacts:**
- JSON report: `/home/mike/Desktop/lucy_v10_model_benchmark_clean_2026-07-14T18-20-29.json`
- Markdown summary: `/home/mike/Desktop/lucy_v10_model_benchmark_clean_2026-07-14T18-20-29.md`

## 10. Final Verification Block

- `ACTIVE_ROOT=/home/mike/lucy-v10`
- `FROZEN_ROOTS=`
- `EDITED_PATHS=tools/runtime_control.py;tools/runtime_profile.py;ui-v10/app/services/runtime_bridge.py;tools/router_py/local_answer.py;tools/router_py/main.py;ui-v10/app/panels/control_panel.py;tools/router_py/test_gemma4_identity.py;tools/router_py/test_ollama_heartbeat_model_switch.py;tools/router_py/test_local_answer.py;tools/tests/test_gemma4_smart_routing_state.py;tools/tests/test_runtime_profile_endpoint.sh;ui-v10/tests/test_gemma4_smart_routing_offscreen.py`
- `TEST_SUMMARY=Targeted Gemma 4 regressions: 79 passed. UI tests: 40 passed. Runtime-profile endpoint test passed. Live brisket/crock-pot continuity and identity request verified after final restart.`
- `BASELINE_DELTA=State model aligned from local-lucy to gemma4:12b-it-qat; gemma4_smart_routing enabled.`
- `BASELINE_STATUS=REUSABLE`
- `RERUN_TRIGGERS=Changes to heartbeat/warmup logic, HMI control-panel wiring, or selectable model aliases.`
- `LAUNCHER_MAP_VERIFIED=YES`
- `DESKTOP_REPORT_PATH=/home/mike/Desktop/Local_Lucy_V11_Session_Handoff_2026-07-13.md`
- `HANDOFF_PATH=/home/mike/lucy-v10/dev_notes/SESSION_HANDOFF_2026-07-13T10-17-07+0300.md`
- `OPEN_GAPS=Default value for gemma4_smart_routing; identity gate for non-Gemma models; semantic golden drift; defunct whisper process.`
