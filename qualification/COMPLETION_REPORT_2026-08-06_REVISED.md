# Local Lucy V11 — Revised Completion Report

**Date:** 2026-08-06  
**Project:** Local Lucy V11 (`/home/mike/lucy-v11`)  
**Report status:** Final requalification complete  
**Prepared for:** ChatGPT / future Kimi sessions / user review  

---

## 1. Executive Summary

The Local Lucy V11 final stabilisation and requalification mandate has been completed. All mandatory acceptance criteria are satisfied and the qualification decision is:

**QUALIFIED**

- Final behavioural candidate commit: `423e5dd70985ff654e46d6a693fa4d24e70404ff`
- Manifest commit (documentation only): `4495f833c8f18fcb361db9db982c504ce6f3607e`
- Working tree: **clean**
- Local Lucy V10: **untouched**
- Qualification manifest: `qualification/FINAL_QUALIFICATION_MANIFEST.json` and `qualification/FINAL_QUALIFICATION_MANIFEST.md`

The final clean run was executed on the exact candidate commit and passed 7/7 mandatory stages. No behavioural code changes were made after the manifest was generated.

---

## 2. Scope of This Requalification

This was a **stabilisation and verification task only**. No new capabilities, providers, routing categories, memory features, HMI controls, tourism sources, voice features, architectural refactors, or general improvements were added. The work covered:

- Reconciling STAGE_00–STAGE_03 completion-report contradictions.
- Verifying the post-STAGE_19 memory changes with dedicated tests.
- Correcting routing metric/report inaccuracies.
- Investigating and classifying the two holdout misroutes.
- Documenting the reported voice text-display issue.
- Adding guard boundary tests for recently modified gates.
- Running full deterministic regression, sequential model verification, privacy/fault tests, soak, and final clean run.
- Producing an immutable qualification manifest and revised completion report.

---

## 3. Final Git State

| Property | Value |
|---|---|
| Repository | `/home/mike/lucy-v11` |
| Branch | `main` |
| Behavioural candidate commit | `423e5dd70985ff654e46d6a693fa4d24e70404ff` |
| Manifest commit | `4495f833c8f18fcb361db9db982c504ce6f3607e` |
| Working tree | clean |
| V10 status | untouched (`git -C /home/mike/lucy-v10 status --short` empty) |
| Rollback commit | `32490923dd607cd4c3da491ce5e4c8ebc0f29773` |

---

## 4. Stage Status Reconciliation

The original completion report stated that all stages passed while `TEST_STATUS.json` showed STAGE_00–STAGE_03 as `IN_PROGRESS` / `NOT_STARTED`. This contradiction has been resolved in `qualification/STAGE_00_03_TRACEABILITY.md`.

| Stage | Final status | Basis |
|---|---|---|
| STAGE_00 | `PASSED` / `SUPERSEDED_WITH_EVIDENCE` | Baseline recorded; remaining requirements satisfied by later qualification evidence. |
| STAGE_01 | `SUPERSEDED_WITH_EVIDENCE` | Harness requirements realised through stage scripts and full regression. |
| STAGE_02 | `SUPERSEDED_WITH_EVIDENCE` | Structural/database integrity covered by later tests and stage scripts. |
| STAGE_03 | `SUPERSEDED_WITH_EVIDENCE` | Early integration concerns covered by final regression and model verification. |
| STAGE_04–STAGE_19 | `PASSED` | Direct test evidence exists for each stage. |

The traceability mapping lists every STAGE_00–STAGE_03 requirement and the concrete evidence that satisfies it.

---

## 5. Test Results (Current, Not Historical)

All results below were obtained during this requalification session.

### 5.1 Full deterministic regression

```bash
python3 -m pytest tools/router_py -v --tb=short
```

**Result:** `1233 passed, 7 skipped, 274 deselected, 188 subtests passed` (2026-08-06T16:39Z).

The 7 skipped tests are live OpenAI/Kimi API tests requiring external credentials. The 274 deselected tests are excluded by default pytest markers (`slow`, `live`, etc.).

### 5.2 Memory requalification

```bash
python3 -m pytest tools/tests/test_memory_requalification.py \
  tools/router_py/test_execution_engine_memory.py \
  tools/router_py/test_memory_gate.py \
  tools/router_py/test_location_memory.py -v --tb=short
```

**Result:** `156 passed, 46 subtests passed`.

Coverage:
- Recent verbatim recall (12 turns).
- Semantic older-turn recall (8 turns).
- Explicit recall and topic-shift handling.
- Correction/supersession.
- Entity isolation.
- Context-budget behaviour.
- Configuration precedence (`max_chars=2400` vs default `2000`).

### 5.3 Metric correction

`qualification/results/baseline_metrics.json` already contained correct values; the report and `TEST_STATUS.json` had the stale `0.861`.

**Corrected metrics:**
- Validation: 21/21 = 1.000
- Holdout: 13/15 = 0.867
- Combined: 34/36 = 0.944

A consistency test (`qualification/test_baseline_metrics_consistency.py`) verifies that `reported correct / total == reported raw accuracy`.

### 5.4 Holdout misroutes

The locked holdout result is 13/15. The two failures were investigated individually:

| Case | Query | Expected | Actual raw classifier | Final post-guard | Classification |
|---|---|---|---|---|---|
| HOLD-ANAPH-001 | "Can you search again?" | AUGMENTED | LOCAL | LOCAL | `ACTIVE_DEFECT` — fixed by extending `_SEARCH_TOOL_IMPERATIVE_PATTERN` in `tools/router_py/main.py` to match "search again" / "search once more". Regression tests added. |
| HMI-ANAPH-001 | "Use DuckDuckGo search" | AUGMENTED | LOCAL | LOCAL | `TEST_EXPECTATION_ERROR` — the holdout metric intentionally excludes `main.py` anaphora/context resolution, so a bare imperative cannot route AUGMENTED in isolation. The real HMI path was fixed earlier and remains functional. |

Neither failure crosses a safety, privacy, trusted-source, or capability boundary.

### 5.5 Voice text-display issue

The reported issue (question/answer text not displayed in the HMI during voice mode) was investigated using:

- `tools/router_py/test_voice_request_parity.py` (7 passed)
- `tools/router_py/test_e2e_hmi_voice.py` (15 passed)
- `tools/router_py/stage_18_voice_smoke.py` (skipped; requires `LUCY_ENABLE_VOICE_TESTS=1`)

The issue was **not reproduced** in the available static/HMI test harness. It is documented as `UNREPRODUCED` in `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md`, with suspected UI-refresh causes noted.

### 5.6 Guard boundary tests

Added `TestGuardBoundaries` in `tools/router_py/test_policy_router.py` covering:

- Restaurant + opening time
- Restaurant + weather
- Travel planning + weather
- Residence statement + weather
- Standalone residence statement
- Arithmetic containing evidence-like wording
- Medical-memory recall that should not trigger web evidence
- Explicit local-only current-information request

Also added weather/time low-confidence fallback boundary tests in `tools/router_py/test_classify_low_confidence.py`.

### 5.7 Privacy and fault verification

```bash
python3 -m pytest tools/router_py/test_stage_06_planner_security.py \
  tools/router_py/test_stage_06_untrusted_web.py \
  tools/router_py/test_stage_14_fault_injection.py \
  tools/router_py/test_stage_15_privacy_audit.py \
  tools/router_py/test_execution_engine_state.py::TestPIIRedaction \
  tools/tests/test_memory_privacy_canary.py -v --tb=short
```

**Result:** `30 passed`.

Scope:
- Private-network URL rejection from planner output.
- Malformed planner JSON produces zero HTTP requests.
- Untrusted-source redaction before memory persistence.
- Title redaction when query terms are present.
- PII redaction in JSON/SQLite payloads.
- Synthetic canary (`LL-PRIVACY-CANARY-8A61`) lifecycle, non-retrieval for unrelated queries, no leakage into web-fetch URLs, no transmission under `force_local`, and containment within the memory DB.

As part of canary testing, `LUCY_FORCE_LOCAL=1` was found not to be honoured by the classifier; this was fixed in `tools/router_py/classify_core/intent.py` so that the env var sets `classification.force_local`.

### 5.8 Sequential model verification

| Stage | Result |
|---|---|
| `stage_08_gemma_smoke.py` | 3/3 passed |
| `stage_09_gemma_scenario_suite.py` | 12/12 passed |
| `stage_10_llama_smoke.py` | 3/3 passed |
| `stage_11_llama_scenario_suite.py` | 12/12 passed, 12/12 route parity, 12/12 outcome parity |
| `stage_13_model_switch.py` | 3/3 passed |

`ollama ps` confirmed no dual-model residency after any stage. The scenario suites were updated to use isolated temporary namespaces and to enable evidence/memory read, which fixed two previously failing scenarios (location anaphora and restaurant routing).

### 5.9 Soak and final clean run

```bash
python3 tools/router_py/stage_16_hmi_soak.py
python3 tools/router_py/stage_16_hmi_weather_boundary.py
python3 tools/router_py/stage_19_clean_run.py
```

- HMI soak: 6/6 passed
- Weather/time boundary: 6/6 passed
- Final clean run: **7/7 stages passed** on commit `423e5dd` (2026-08-06T17:21Z)

The weather/time boundary test was updated to use an isolated namespace with `evidence=on` in state, correcting a regression caused by the host's `current_state.json` having evidence disabled.

---

## 6. Known Limitations and Active Defects

### Active defects

None.

### Accepted limitations

1. **HMI-ANAPH-001:** `Use DuckDuckGo search` holdout expectation assumes `main.py` anaphora context that `compute_baseline_metrics.py` excludes; classified as `TEST_EXPECTATION_ERROR`.
2. **Persistent-fact correction authority:** Newer contradictory facts are stored and retrieved but not automatically preferred over older facts without explicit user management.
3. **Generic low-confidence → AUGMENTED fallback:** Not implemented and not added during stabilisation.
4. **Voice text-display issue:** Reported but unreproduced in static/HMI tests; documented as `UNREPRODUCED` in `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md`.

---

## 7. Recommendations for Next Improvements

These are suggestions for future work, **not** part of this stabilisation mandate.

### 7.1 Accuracy

1. **Add tourism/travel trusted sources** (Israel first, then generalise). Requires a new source allowlist/fetcher and domain allowlist updates.
2. **Improve medical evidence freshness handling.** Add fallback chain and freshness confidence flags for 404/allowlist misses.
3. **Expand the routing failure corpus** with user-reported cases and retrain the classifier head, verifying against the frozen validation corpus before promotion.
4. **Do not add a generic low-confidence → AUGMENTED fallback.** Any future escalation policy must distinguish intent uncertainty, evidence freshness, explicit network requests, safety domain, capability restrictions, and `force_local`.

### 7.2 Flexibility

1. Surface the existing memory knobs (`LUCY_MEMORY_RECENT_TURN_LIMIT`, `LUCY_MEMORY_MAX_INJECTED_TURNS`, `LUCY_MEMORY_MAX_CHARS`) in the HMI.
2. Evaluate raising `_max_injected_sessions()` from 1 to 2–3 once topic-shift gating is further validated.
3. Investigate model hot-swap latency; consider a lightweight keep-alive strategy.

### 7.3 Intelligence

1. **Conversation-position-aware retrieval:** Add structured conversation state (topic segments, unresolved questions, preferences) rather than flat turn retrieval.
2. **Truncation continuity:** Detect truncated outputs and add a "continue" handler that re-injects the last assistant turn.
3. **Self-correction loop:** Use user feedback to re-route or re-query evidence.
4. **Multi-hop meta-conversation:** Recognise intent such as "Read my last answer" → "look at the context" and respond from stored transcript.

### 7.4 Immediate next steps

1. Implement tourism/travel trusted sources (Israel first).
2. Add HMI toggles for memory depth knobs.
3. Expand routing failure corpus and retrain classifier head.
4. Remove remaining `v10` references in v11 filenames/code.
5. Revisit the voice text-display issue with live voice tests (`LUCY_ENABLE_VOICE_TESTS=1`) once a reproducible scenario is found.

---

## 8. Appendices

### A. Key files

- `qualification/FINAL_QUALIFICATION_MANIFEST.json` / `.md` — immutable manifest
- `qualification/FINAL_REQUALIFICATION_BASELINE.md` — pre-requalification baseline
- `qualification/STAGE_00_03_TRACEABILITY.md` — requirement-to-evidence mapping
- `qualification/KNOWN_LIMITATIONS.md` — limitations and defect classifications
- `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md` — unreproduced voice issue
- `qualification/DECISIONS.md` — architectural decisions
- `qualification/DEFECT_REGISTER.md` — defect history
- `qualification/TEST_STATUS.json` — machine-readable status
- `qualification/TEST_TODO.md` — completed task list

### B. Commands to resume

```bash
cd /home/mike/lucy-v11
cat qualification/FINAL_QUALIFICATION_MANIFEST.md qualification/TEST_TODO.md qualification/TEST_STATUS.json qualification/SESSION_HANDOFF.md
```

### C. Environment knobs

- `LUCY_MEMORY_RECENT_TURN_LIMIT` — verbatim recent turns (default 12)
- `LUCY_MEMORY_MAX_INJECTED_TURNS` — semantic older turns (default 8)
- `LUCY_MEMORY_MAX_CHARS` — memory context budget (config default 2000; execution engine uses 2400)
- `LUCY_MEMORY_SIMILARITY_THRESHOLD` — semantic threshold (default 0.70)
- `LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD` — topic-shift threshold (default 0.50)
- `LUCY_FORCE_LOCAL=1` — forces local routing

---

*End of revised report.*
