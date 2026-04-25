# ChatGPT Review Report: Router De-dup Phase 2 Completion + Full/Live Regression Validation
Date: February 26, 2026
Time: 20:43:37 +0200
Project: `/home/mike/lucy/snapshots/opt-experimental-v2-dev`

## Executive Summary
This session completed router de-dup phase 2 (including phase 2b retirement of legacy fallback heuristics), fixed a classifier parity gap that was preventing safe cutover, and validated the final state with both local/full regression and live internet regression suites.

Final outcome:
- Router fallback in `lucy_chat.sh` now depends on the shared router classifier + shared mapper only (outside explicit router-forced mode).
- Legacy heuristic fallback routing and the temporary kill-switch path were removed after parity was established.
- Explicit URL / web-fetch intent parity was fixed in `tools/router/classify_intent.py`.
- Full regression (`full_regression_v2.sh`) and live internet suites (`internet_e2e_accept.sh`, `all_systems_regression.sh`) passed after manifest refresh.

## Scope Covered In This Report
1. Loaded and used latest dev handoff note.
2. Executed requested next-step sequence (router regressions, shadow compare soak, kill-switch regression, legacy retirement, handoff update).
3. Fixed classifier mismatch discovered during soak.
4. Performed broader regression sweep (local + live internet) on finalized router state.
5. Appended a post-validation addendum to the latest handoff note.

## Starting Context (Latest Handoff Used)
Primary handoff used at start of this work:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-27-00+0200.md`

Key pending item from that handoff:
- Router de-dup phase 2b: switch `lucy_chat.sh` fallback routing from legacy heuristics to classifier + shared mapper, then retire legacy heuristics after soak.

Intermediate handoffs created during this session chain:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-34-58+0200.md` (documented blocker/mismatch and temporary kill-switch regression)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-38-23+0200.md` (documented successful completion of phase 2b)

## Detailed Chronology
### 1. Used latest dev note and executed planned router follow-up
- Loaded latest `SESSION_HANDOFF` note and identified phase-2 de-dup completion as the remaining architectural task.
- Inspected:
  - `lucy_chat.sh`
  - `tools/router/classify_intent.py`
  - `tools/router/plan_to_pipeline.py`
  - routing regressions / shadow compare tests

### 2. Implemented fallback routing cutover in `lucy_chat.sh` (phase 2 setup)
Initial phase-2 change (before final retirement) added a classifier+mapper fallback route path in `lucy_chat.sh` while preserving a temporary legacy kill switch for safety:
- Default fallback path uses `classify_intent.py` + `plan_to_pipeline.py`
- Temporary safety switch (later removed): `LUCY_CHAT_LEGACY_FALLBACK_ROUTING=1`
- Shadow compare telemetry retained
- Offline actions from mapper (`validated_insufficient`, `requires_evidence`) honored directly by `lucy_chat.sh`

This stage was validated with routing-focused tests:
- `tools/tests/test_router_vs_fallback_mode_drift_monitor.sh` PASS
- `tools/tests/test_lucy_chat_router_forced_mode_strict.sh` PASS
- `tools/tests/test_lucy_chat_shadow_compare_smoke.sh` PASS

### 3. Ran shadow compare soak and discovered a real parity mismatch
Controlled shadow soak (forced offline to avoid network latency) revealed:
- `fetch https://example.com` -> `MODE_MISMATCH`
- Final fallback mode was `EVIDENCE`
- Classifier+mapper shadow mode was `LOCAL`

Root cause:
- `tools/router/classify_intent.py` lacked an explicit URL / fetch-web intent rule.
- Explicit URL prompt fell through to `LOCAL_KNOWLEDGE`, so mapper returned `LOCAL`.

Impact:
- Legacy fallback heuristics could not be safely removed yet.
- Temporary kill-switch path remained necessary until parity fix.

### 4. Added temporary kill-switch regression (then used it as a safety lock)
Added (temporary) regression test:
- `tools/tests/test_lucy_chat_legacy_fallback_routing_killswitch.sh`

Purpose:
- Prove default path used classifier+mapper metadata
- Preserve rollback guarantee that kill-switch path still routed explicit fetch URL prompts via legacy internet-intent heuristic (`EVIDENCE`)

This test passed during the parity-fix staging period.

### 5. Fixed classifier parity in `tools/router/classify_intent.py`
Implemented explicit web/internet intent detection for:
- `http(s)://...`
- `fetch`
- `browse web`
- `search web`
- `internet`
- `website`
- `web search`

Classifier behavior after fix:
- `python3 tools/router/classify_intent.py 'fetch https://example.com'`
  -> `intent=WEB_FACT`, `needs_web=true`, `needs_citations=true`, `output_mode=LIGHT_EVIDENCE`

Effect:
- Shared mapper now returns `EVIDENCE` for explicit fetch URL prompts.
- Shadow compare mismatch resolved.

### 6. Revalidated parity and completed phase 2b (legacy heuristic retirement)
After classifier fix:
- `tools/tests/test_router_vs_fallback_mode_drift_monitor.sh` PASS
- Updated temporary kill-switch regression expectations to reflect new default parity and reran: PASS
- Controlled shadow soak produced `status=MATCH` for all sampled prompts including `fetch https://example.com`

Then phase 2b was completed:
- Removed `legacy_classify_mode` / `legacy_classify_reason` from `lucy_chat.sh`
- Removed `LUCY_CHAT_LEGACY_FALLBACK_ROUTING` kill-switch path from `lucy_chat.sh`
- `lucy_chat.sh` fallback now requires classifier+mapper (deterministic failure if unavailable)

### 7. Updated fake-root routing tests for architecture change
Removing legacy fallback caused expected failures in fake-root tests because the isolated test roots did not contain router scripts.

Fixed by updating fake-root test harnesses to copy router scripts into fake root:
- `tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `tools/tests/test_lucy_chat_router_forced_mode_strict.sh`

Added copies of:
- `tools/router/classify_intent.py`
- `tools/router/plan_to_pipeline.py`

Retested:
- `test_router_vs_fallback_mode_drift_monitor.sh` PASS
- `test_lucy_chat_router_forced_mode_strict.sh` PASS
- `test_lucy_chat_shadow_compare_smoke.sh` PASS
- `tools/router/router_regression.sh` PASS

Temporary kill-switch test then removed (feature retired).

## Files Changed (Final State)
### Core routing / classifier
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/lucy_chat.sh`
  - fallback now uses classifier+mapper only
  - legacy heuristic fallback functions removed
  - temporary kill-switch path removed
  - mapper offline actions handled directly
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/router/classify_intent.py`
  - explicit URL / fetch-web intent detection added (`WEB_FACT`)

### Test harness updates
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
  - fake root now copies router classifier/mapper scripts
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_lucy_chat_router_forced_mode_strict.sh`
  - fake root now copies router classifier/mapper scripts

### Session documentation
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-34-58+0200.md`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-38-23+0200.md`

### Temporary test created and retired (not in final tree)
- `tools/tests/test_lucy_chat_legacy_fallback_routing_killswitch.sh` (created for transitional safety; removed after parity + cutover completion)

## Validation Matrix (Router / De-dup Work)
### Routing correctness and drift checks
- `bash -n /home/mike/lucy/snapshots/opt-experimental-v2-dev/lucy_chat.sh` -> PASS
- `./tools/tests/test_router_vs_fallback_mode_drift_monitor.sh` -> PASS
- `./tools/tests/test_lucy_chat_router_forced_mode_strict.sh` -> PASS
- `./tools/tests/test_lucy_chat_shadow_compare_smoke.sh` -> PASS
- `./tools/router/router_regression.sh` -> PASS

### Classifier parity verification
- `python3 tools/router/classify_intent.py 'fetch https://example.com'` -> PASS (`intent=WEB_FACT`)

### Controlled shadow soak (post-removal)
Log:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/logs/router_shadow_compare.log`

Sample prompts (all `status=MATCH`):
- `what is lm317?`
- `latest Israeli news`
- `Does tadalafil react with alcohol?`
- `Who is considered the latest Shah of Iran?`
- `fetch https://example.com`

Interpretation:
- Classifier+mapper parity now covers the explicit fetch URL case that previously blocked cutover.
- Legacy drift issue that motivated the temporary kill switch is resolved for the sampled prompt set.

## Broader Regression Sweep (Post-Finalization)
### Important note: manifest refresh was required
Initial `./tools/full_regression_v2.sh` run failed at immutable manifest check due to expected code changes (stale `SHA256SUMS`).

Observed failure (expected after local edits):
- `ERR: immutable manifest check failed`
- `sha256sum: WARNING: 7 computed checksums did NOT match`

Resolution:
- `./tools/sha_manifest.sh regen`
- `./tools/sha_manifest.sh check` -> PASS

### Full local regression
- `./tools/full_regression_v2.sh` -> PASS

Highlights from the passing run:
- immutable manifest check: PASS
- deterministic evidence-only behavior checks: PASS
- fetch allowlisted URL basic fetch: PASS
- router regression + plan/executor regression: PASS
- output shaping, medical evidence-only, primary-doc single-source regressions: PASS
- local/news answer regressions: PASS
- trust list verification: PASS
- verification sweep: PASS
- final summary: `OK: full_regression_v2 completed`

Generated verification sweep log:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tmp/logs/verify_all_dev_evidence_tools_v1.2026-02-26T20_40_07+02_00.log`

### Live internet regression suite (escalated permissions/network)
Ran with user-approved escalated permissions / internet access:
- `./tools/internet/searxng_ensure_up.sh` -> PASS
- `./tools/internet/internet_e2e_accept.sh` -> PASS (`Internet E2E: PASS`)
- `./tools/internet/all_systems_regression.sh` -> PASS (`OK: ALL SYSTEMS GREEN`)

Highlights from `all_systems_regression.sh`:
- internet limit tests: PASS
- `fetch_evidence` RFC_7231 path: PASS
- artifact meta/sha verification: PASS
- `validate_answer` positive/negative checks: PASS
- `print_validated --force` citation enforcement checks: PASS
- dev REPL wiring/header check: PASS

## Risk Assessment (Post-Completion)
### Resolved risks
- Router/fallback drift for explicit URL fetch intent (`fetch https://...`) is resolved.
- Legacy heuristic duplication in `lucy_chat.sh` fallback routing has been removed.
- Fake-root routing tests now model the actual architecture dependency on router classifier/mapper.

### Remaining considerations (non-blocking)
- `shadow_compare_route_log` remains as telemetry but no longer compares against legacy heuristic routing. It now primarily checks internal consistency / execution-path invariants.
- If desired, future cleanup can repurpose or simplify shadow compare logging to reflect the new single-path routing design.

## Artifacts / Notes for Continuity
Primary final handoff (now with appended addendum in this session):
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-38-23+0200.md`

Supporting handoff documenting transitional mismatch + temporary test:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T20-34-58+0200.md`

This report:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_router_dedup_phase2_completion_and_full_live_regression_2026-02-26T20-43-37+0200.md`

## Recommended Next Steps (Optional)
1. Run `tools/trust/probe_trust_sites.py` again (live) to reconfirm trust probe remains green after router/classifier finalization (expected low risk, but good evidence continuity).
2. Consider documenting the new hard dependency of `lucy_chat.sh` fallback on router classifier/mapper in any operator notes or test harness guidelines.
3. Evaluate whether `shadow_compare_route_log` should be simplified or redefined now that legacy fallback heuristics are retired.
