# ChatGPT Review Report: Runtime-Governor Validation + Follow-up Routing Fixes
Date: March 14, 2026
Time: 10:36:13 +0200
Project: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Executive Summary
This session started as a no-patch validation pass for the runtime-governor migration in `opt-experimental-v5-dev`, then moved into targeted fixes after the live session exposed real follow-up regressions.

Final state at the end of the session:
- requested fast regression subset passed
- sandbox prompt matrix matched the governor contract after correcting follow-up ordering
- live environment separated sandbox-only source/backend artifacts from real failures
- real follow-up regressions were fixed:
  - medical follow-up now prefers fresher route context over stale launcher memory
  - travel follow-up now keeps `travel_advisory` semantics through execute-plan post-processing
- forced-offline medical UX/contract wording in the launcher/help text was aligned with the already-existing runtime behavior

## Original Problems Observed

### 1. Launcher/live follow-up context could prefer stale safe-turn memory over fresher route state
Observed symptom:
- after an unsafe turn that was intentionally not stored in launcher memory, a follow-up could still receive a stale `LUCY_CHAT_MEMORY_FILE`
- contextual follow-up resolution then read the stale memory turn first and ignored the fresher `state/last_route.env`

Real user-facing failures caused by that:
- `Is tadalafil a good treatment for erectile dysfunction?` -> `what about for blood pressure?`
  - expected: rewritten to `What about tadalafil for blood pressure?` and stay evidence-routed
  - actual before fix: fell into a wrong local path and produced a mixed general-information reply
- `Is it safe now to travel to Iran?` -> `What about Jordan?`
  - expected: rewritten to `Is it safe now to travel to Jordan?`
  - actual before fix: travel follow-up handling was inconsistent in live use

Root cause:
- `tools/router/core/contextual_policy.py` returned the latest memory-file user turn whenever a memory file existed, even when `last_route.env` had the fresher and more relevant immediate prior query

### 2. Contextual travel follow-ups could lose `travel_advisory` fallback behavior
Observed symptom:
- even when `What about Jordan?` was rewritten to `Is it safe now to travel to Jordan?`, the final post-processing path could still miss the decisive travel fallback

Root cause:
- `tools/router/execute_plan.sh` was carrying `category` from the original phase-1 plan instead of the resolved `effective_plan.category`
- contextual follow-up output could therefore be routed as `EVIDENCE` but miss the travel-specific fallback gate that checks `category == travel_advisory`

### 3. Forced-offline medical UX text was inconsistent with runtime behavior
Observed symptom:
- launcher/help text said offline mode meant web/medical "require evidence mode"
- actual runtime behavior for forced-offline medical was already `validated_insufficient`, not a `requires_evidence` block

Root cause:
- user-facing launcher/help copy had drifted from the router/policy contract

## Review Findings From The Validation Pass
- worker stale-process risk remained:
  - worker freshness was keyed to `local_answer.sh`, not worker/client code
- LOCAL_DIRECT risk remained:
  - LOCAL_DIRECT eligibility still suppresses fast-path use broadly when session memory is active
- those two were identified in review but were not changed in this session

## Files Changed

### Core fixes
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/contextual_policy.py`
  - `_latest_user_context_query()` now prefers the fresher source between memory and `state/last_route.env`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh`
  - `category` now resolves from `mapped.effective_plan.category` first
  - this preserves `travel_advisory` behavior for contextual travel follow-ups
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/start_local_lucy_opt_experimental_v3_dev.sh`
  - offline-mode banner/help/mode-switch text now says:
    - web requires evidence mode
    - medical returns offline insufficiency

### New regression tests
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_followup_prefers_fresher_route_context.sh`
  - verifies fresher route context beats stale memory for medical and travel follow-ups
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_travel_followup_decisive_fallback.sh`
  - verifies contextual travel follow-up reaches decisive travel fallback after rewrite

## Validation Performed

### Initial validation pass
- requested fast regression subset:
  - `test_runtime_governor_contract.sh`
  - `test_execute_plan_governor_contract.sh`
  - `test_router_contract_schema.sh`
  - `test_execute_plan_nested_contract.sh`
  - `test_execute_plan_local_worker_fast_path.sh`
  - `test_execute_plan_local_direct_non_local_unchanged.sh`
  - `test_execute_plan_local_direct_repeat_cache.sh`
  - `test_execute_plan_context_followup_carryover.sh`
  - `test_execute_plan_media_followup_context.sh`
  - `test_local_answer_truth_guards.sh`
  - `test_travel_advisory_cross_mode_consistency.sh`
  - `test_phase1_classifier_output.sh`
- result:
  - all passed
  - note: several test files were non-executable in the snapshot and had to be invoked with `bash`, but no file changes were needed for that

### Prompt-matrix validation
- sandbox matrix run across:
  - `/mode auto`
  - `/mode online`
  - `/mode offline`
- result:
  - contract/routing behavior matched expected governor behavior after correcting the follow-up ordering in the matrix
- environment-sensitive observations:
  - sandbox news path could fail with no sources
  - sandbox medical path could fail with local backend unavailable

### Minimum outside-sandbox reruns during validation
- reran only:
  - `What are the latest world news headlines?`
  - `Is it safe now to travel to Iran?`
  - `Is tadalafil a good treatment for erectile dysfunction?`
- conclusions:
  - live news worked with real sources
  - live medical evidence worked with real sources/backend
  - live travel to Iran still needed quality attention at that stage

### Focused post-fix validation
- `bash tools/tests/test_execute_plan_context_followup_carryover.sh`
- `bash tools/tests/test_execute_plan_media_followup_context.sh`
- `bash tools/tests/test_execute_plan_followup_prefers_fresher_route_context.sh`
- `bash tools/tests/test_execute_plan_travel_followup_decisive_fallback.sh`
- `bash tools/tests/test_runtime_governor_contract.sh`
- `bash tools/tests/test_execute_plan_governor_contract.sh`
- `bash tools/tests/test_router_contract_schema.sh`
- `bash tools/tests/test_travel_advisory_cross_mode_consistency.sh`
- `bash tools/tests/test_lucy_chat_shadow_compare_smoke.sh`

All passed after the fixes.

## Live/Environment Confirmation After Fixes
- stale-memory medical follow-up rerun outside sandbox:
  - now returns validated tadalafil evidence output with sources
- stale-memory travel follow-up rerun outside sandbox:
  - now returns risk-first travel guidance with sources instead of the previous broken follow-up behavior
- launcher/help text:
  - now accurately describes forced-offline medical behavior

## Problems Fixed vs Not Fixed

### Fixed this session
- medical follow-up carryover regression in live use
- travel follow-up context preservation through execute-plan
- travel follow-up decisive fallback gating
- forced-offline medical launcher/help wording drift

### Explicitly not fixed this session
- worker stale-code-stamp design
- broad LOCAL_DIRECT suppression when session memory is present
- Israeli-news topicality/ranking quality

## Recommended Next Steps
1. Run a fresh live launcher check using the exact prompts that failed before:
   - `Is tadalafil a good treatment for erectile dysfunction?`
   - `what about for blood pressure?`
   - `Is it safe now to travel to Iran?`
   - `What about Jordan?`
2. If those are green, move back to the remaining validation backlog:
   - worker/LOCAL_DIRECT review findings
   - news topicality quality
3. If live Jordan output is still weak, inspect the evidence-pack/domain selection for Jordan-specific travel sources rather than the contextual rewrite path, because the contextual routing path is now fixed.

## Artifacts
- report:
  - `/home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/CHATGPT_REVIEW_REPORT_runtime_governor_validation_and_followup_fixes_2026-03-14T10-36-13+0200.md`
- handoff:
  - `/home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/SESSION_HANDOFF_2026-03-14T10-36-13+0200.md`
