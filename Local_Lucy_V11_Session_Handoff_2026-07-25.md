# Local Lucy V11 — Session Handoff

**Date:** 2026-07-25 (evening)  
**Branch:** `v11-routing-parity-2026-07-25` in `/home/mike/lucy-v11`  
**V10 preserved at:** `/home/mike/lucy-v10` (verified clean, unchanged)  
**Supersedes:** `/home/mike/Desktop/archived_handoffs/Local_Lucy_V11_Session_Handoff_2026-07-23.md`

---

## Current checkpoint

Local Lucy V11 is a **provisional runnable checkpoint**. This session completed the Gemma/Llama request-parity repair and hardened model-agnostic routing.

- Branch `v11-routing-parity-2026-07-25` is active with uncommitted changes.
- **Gemma/Llama request-parity repair complete**:
  - Reference self-model consistency request now routes `LOCAL` for both Gemma 4 12B Reasoning and Llama 3.1 8B.
  - Zero HTTP requests, zero tool calls, zero file operations, zero memory writes for the reference request on both models.
  - Llama no longer fabricates MedlinePlus URLs from individual prompt words.
  - Explicit user restrictions (no network, no tools, no files, no memory writes, local-only) are enforced deterministically before routing.
  - Medical routing now distinguishes software-memory terminology from genuine human cognitive symptoms.
- **Full router regression suite passes**: 909 passed, 12 skipped, 178 subtests passed.
- **Live-model parity harness passes**: 16/16 cases for both `local-lucy-gemma4` and `local-lucy-llama31`.
- Detailed repair report saved to `/home/mike/lucy-v11/PARITY_REPAIR_REPORT.md`.
- V10 untouched and source-checksum-valid.

### Repository heads

```text
V11: 299c601e1da76e98c6fbd1763792728afe4b5fbb (with uncommitted changes listed below)
V10: ec5dcbb3ddb0f67f6c020a1c162190ad2ca89a21
```

### Uncommitted V11 changes (this session)

```text
 M tools/router_py/policy.py
 M tools/router_py/policy_router.py
 M tools/router_py/request_pipeline.py
 M tools/router_py/request_types.py
 M tools/router_py/main.py
 M tools/router_py/execution_engine.py
 M tools/unverified_context_trusted.py
?? tools/router_py/request_constraints.py
?? tools/router_py/url_provenance.py
?? tools/router_py/planner_validator.py
?? tools/router_py/test_request_parity.py
?? tools/router_py/model_parity_harness.py
?? PARITY_REPAIR_REPORT.md
```

(Pre-existing uncommitted changes in other files are unrelated to this session and were not touched. The `state/` directory is runtime-generated and fully gitignored.)

---

## Absolute rules (carry forward)

1. `/home/mike/lucy-v10` is read-only.
2. Do not commit, tag, format, test-write, migrate, clean, or modify anything inside V10.
3. Do not copy files back into V10.
4. Do not share writable databases, state, configuration, logs, caches, sockets, PID files, lock files or virtual environments between V10 and V11.
5. Do not begin large module splitting until namespace, regression and migration gates pass.
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
```

Confirm V10 is clean, then proceed from the first incomplete phase below.

---

## Agreed execution plan

The plan follows ChatGPT’s ordering: stabilize the source installation first, inventory/test before deleting code, then preserve functionality (mandatory migration), then improve architecture.

### Block 1 — Stabilize the running source installation

Goal: V11 is a clean standalone source-tree installation.

1. **Phase 0 — Freeze the checkpoint** ✅
2. **Phase 1 — Centralize V11 namespace** ✅
3. **Phase 2 — Inventory and baseline the complete inherited test surface** ✅
4. **Phase 4 — Remove unsafe runtime fallbacks** ✅
5. **Phase 5 — Complete isolation verification** ✅
6. **Phase 6 — Secret and repository integrity audit** ✅

### Block 2 — Preserve functionality and user continuity

Goal: V11 can reasonably be considered a standalone functional successor to V10. State migration is mandatory before V11 becomes primary.

- **Phase 3 — Explicit V10-to-V11 state migration (mandatory)** ✅
- Complete full test-parity reconciliation ✅
- Test deterministic personal/family memory after migration ✅
- **Gemma 4 creative-writing truncation** ✅
- **HMI model-switch unload ordering** ✅
- **Gemma/Llama request-parity and deterministic routing** ✅
- **Phase 10 — Packaging and installation identity** (pending)
- **Phase 11 — Voice robustness testing** (pending)
- **Phase 7 — Remove remaining compatibility wrappers** only after regression mapping (pending)

### Block 3 — Improve architecture and intelligence

Goal: Cleaner code and measured accuracy improvement.

- **Phase 8** — incremental module splitting, one module at a time, with characterization tests (pending).
- **Phase 9** — routing traces and policy/classification clarity; correct subject-aware self-capability routing (partially addressed by parity repair; continue with structured traces).
- **Phase 12** — initial 25–40-case accuracy/intuition suite; compare V10 vs V11; expand based on real failures (pending).

---

## Tomorrow's immediate work

Start **Block 2 Phase 10 — packaging and installation identity**.

### Phase 10 tasks

1. Audit current AppImage, Debian, and desktop launcher configurations for V10 references.
2. Correct package names and desktop application IDs so V10 and V11 are distinct.
3. Verify AppImage launch target points to V11 entry points.
4. Verify Debian install/uninstall cannot affect the other version.
5. Update packaging metadata (control files, .desktop files, AppImage recipe).
6. Build or dry-run packages and verify identities.
7. Document results in `/home/mike/lucy-v11-prep/reports/phase10_packaging_report_2026-07-26.md`.

### Phase 10 gate

Proceed only when:

- V11 package identity is distinct from V10;
- Install/removal of V11 cannot modify V10;
- Desktop files use V11 application IDs;
- AppImage launches V11 correctly.

---

## Revised TODO list

### Block 1 — Stabilize

- [x] Phase 0: tag V11 provisional checkpoint and regenerate clean V10 inventories.
- [x] Phase 0 gate: confirm V10 and V11 git status clean; record HEADs.
- [x] Phase 1: centralize V11 runtime/config/cache/state path resolver.
- [x] Phase 1: update all legacy fallback paths in runtime_control, runtime_voice, router_py, db_launcher.
- [x] Phase 1 gate: prove every V11 entry point resolves same canonical namespace.
- [x] Phase 2: inventory complete V11 test suite and run baseline.
- [x] Phase 2: record failures, skips, missing V10-equivalent tests.
- [x] Phase 2 gate: baseline recorded before any further deletion/restructuring.
- [x] Phase 4: remove silent mock/test backend fallback in runtime_request.
- [x] Phase 4: verify stale route/outcome files cannot be reused.
- [x] Phase 4: verify empty backend output becomes explicit failure.
- [x] Phase 4: verify direct CLI and HMI use one canonical request contract.
- [x] Phase 4: verify history has no duplicate entries.
- [x] Fix database viewer truncation in `tools/db_launcher.sh`.
- [x] Phase 5: prove source/runtime isolation across HMI, launcher, CLI, clean HOME, arbitrary cwd, concurrent V10/V11.
- [x] Phase 6: audit secrets, Git state, symlinks, hardlinks.
- [x] Phase 6 gate: all integrity checks pass.

### Block 2 — Preserve functionality

- [x] Phase 3 (mandatory): explicit V10→V11 database discovery, dry-run, migration, verification.
- [x] Phase 3 gate: V10 state inventoried; dry-run reviewed; migration idempotent; personal/family memory deterministic; V10 checksum-valid.
- [x] Complete full test-parity reconciliation (pytest 0 failed; shell tests 0 failed).
- [x] Fix Gemma 4 creative-writing truncation.
- [x] Fix HMI model-switch unload ordering.
- [x] Gemma/Llama request-parity repair and deterministic routing.
- [ ] Phase 10 packaging: AppImage, Debian identity, desktop IDs, uninstall isolation.
- [ ] Phase 11: voice robustness testing.
- [ ] Phase 7: remove remaining compatibility wrappers only after regression mapping.

### Block 3 — Improve

- [ ] Phase 8: split oversized modules one at a time.
- [ ] Phase 9: routing traces and subject-aware self-capability routing.
- [ ] Phase 12: initial 25–40-case accuracy/intuition suite and V10 vs V11 comparison.

---

## Known unresolved issues

- Packaging (AppImage, Debian) is not yet corrected for V11 identity.
- Voice robustness is proven only by basic text and voice prompts.
- `PlannerValidator` is wired and unit-tested but the current evidence planner is deterministic; any future LLM planner must call it before execution.
- MedlinePlus search endpoint currently returns HTTP 404 in this environment; the code falls through to DailyMed, but the 404 traffic is still logged.
- Session-memory summarisation occasionally times out (unrelated to routing).

---

## Test baseline

- **pytest (this session, full router suite):**
  - `tools/router_py/test_request_parity.py`: 25 passed
  - `tools/router_py/test_policy.py`: passed
  - `tools/router_py/test_policy_router.py`: passed
  - `tools/router_py/test_classifier_regression.py`: passed
  - Combined focused run: passed
  - Full `tools/router_py/` suite: **909 passed, 12 skipped, 178 subtests passed**
- **Live-model parity harness (`tools/router_py/model_parity_harness.py`):**
  - `local-lucy-gemma4`: **16/16 passed**
  - `local-lucy-llama31`: **16/16 passed**
- **ruff:** clean on all touched files.

---

## Changes this session

| File | Change |
|------|--------|
| `tools/router_py/request_constraints.py` | New: typed `RequestConstraints` + deterministic extraction of explicit user denials. |
| `tools/router_py/url_provenance.py` | New: `SearchQuery`/`FetchURL` typed separation + `validate_fetch_url()`. |
| `tools/router_py/planner_validator.py` | New: strict schema validator for model-generated plans. |
| `tools/router_py/test_request_parity.py` | New: 25 regression tests covering reference self-model, architecture, memory denial, software consistency, medical contrast, evidence, malformed planner, route isolation, model-switch isolation, no-network enforcement. |
| `tools/router_py/model_parity_harness.py` | New: live-model side-by-side comparison harness for Gemma and Llama. |
| `tools/router_py/main.py` | Extract or accept caller-supplied request constraints and thread them through the pipeline; skip memory persistence when denied. |
| `tools/router_py/request_pipeline.py` | Degrade `EVIDENCE/AUGMENTED/NEWS/FULL` to `LOCAL` when `network=False`; degrade `TIME/WEATHER/FINANCE` to `LOCAL` when `tools=False`. |
| `tools/router_py/request_types.py` | Add `PipelineContext.with_constraints()`. |
| `tools/router_py/execution_engine.py` | Add `is_capability_allowed()` helper. |
| `tools/router_py/policy_router.py` | Add `gate_explicit_capability_restriction()` and capability-restriction detection; force `LOCAL` for short restriction messages. |
| `tools/router_py/policy.py` | Add cognitive/neurological symptoms; switch medical keyword matching to word-boundary `_phrase_in_text()`; add `vomiting`/`coughing`/`sneezing`; add `side effect`/`statin`; add `self-defense`; word-boundary programming-language guard. |
| `tools/unverified_context_trusted.py` | Label keyword-derived URLs `INVENTED_KEYWORD` and reject them before HTTP fetch. |
| `PARITY_REPAIR_REPORT.md` | New: complete technical repair report. |

---

## Reference files

- `/home/mike/Desktop/archived_handoffs/Local_Lucy_V11_Session_Handoff_2026-07-23.md`
- `/home/mike/lucy-v11/PARITY_REPAIR_REPORT.md`
- `/home/mike/lucy-v11-prep/reports/phase3_migration_report_2026-07-23.md`
- `/home/mike/lucy-v11-prep/reports/test_parity_reconciliation_2026-07-23.md`
- `/home/mike/lucy-v11-prep/reports/v11_shell_test_baseline_2026-07-23.log`
- `/home/mike/lucy-v11-prep/reports/phase5_isolation_report_2026-07-22.md`
- `/home/mike/lucy-v11-prep/reports/phase6_integrity_audit.md`

---

*Next session starts with Block 2 Phase 10 (packaging and installation identity) pending approval.*
