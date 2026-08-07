# Local Lucy V11 — Completion Report: Memory-First Intelligence & Tourism Sources Upgrade

**Date:** 2026-08-07  
**Project:** Local Lucy V11 (`/home/mike/lucy-v11`)  
**Report status:** Final qualification complete  
**Prepared for:** ChatGPT / future Kimi sessions / user review  

---

## 1. Executive Summary

The Local Lucy V11 Memory-First Intelligence & Tourism Sources upgrade has been completed. All mandatory acceptance criteria are satisfied and the qualification decision is:

**QUALIFIED**

- Final verified candidate commit: `ed26695b7bf647a0096c0a0a4c62eb92f5a991c6`
- Memory-continuity fix commit: `5591c1a fix(memory): continuation detection, cache key, reserve protection, session isolation`
- Previous manifest commit (documentation only): `4495f833c8f18fcb361db9db982c504ce6f3607e`
- Previous behavioural candidate commit: `423e5dd70985ff654e46d6a693fa4d24e70404ff`
- Working tree: **clean**
- Local Lucy V10: **untouched**
- Qualification manifest: `qualification/FINAL_QUALIFICATION_MANIFEST.json` and `qualification/FINAL_QUALIFICATION_MANIFEST.md`

The final clean run was executed on commit `ed26695` and passed **7/7** mandatory stages with no dual-model residency. Task 18 fixed the two session-memory continuity failures discovered in the previous clean run, and Task 19 produced the final reports and handoff.

---

## 2. Scope of This Upgrade

This upgrade covered four phases:

1. **Phase 1 — Memory-First Intelligence Core:** full assistant output storage, continuation budget/reserve, authoritative memory preamble, model-family-aware prompt shaping.
2. **Phase 2 — Tourism Sources:** Israel destination extraction, Israel Ministry of Tourism fetcher with cache, Wikivoyage generalisation, trusted-source routing for tourism recommendations.
3. **Phase 3 — Verification & Cross-Model Guarantees:** single-model residency helper and assertions, cross-model memory continuity scenarios, HMI real-routing residency checks.
4. **Phase 4 — Reporting & Handoff:** final status updates, completion report, session handoff, desktop copies, archive.

---

## 3. Final Git State

| Property | Value |
|---|---|
| Repository | `/home/mike/lucy-v11` |
| Branch | `main` |
| Final verified candidate commit | `ed26695b7bf647a0096c0a0a4c62eb92f5a991c6` |
| Memory-continuity fix commit | `5591c1a fix(memory): continuation detection, cache key, reserve protection, session isolation` |
| Previous manifest commit | `4495f833c8f18fcb361db9db982c504ce6f3607e` |
| Previous behavioural candidate commit | `423e5dd70985ff654e46d6a693fa4d24e70404ff` |
| Working tree | clean |
| V10 status | untouched (`git -C /home/mike/lucy-v10 status --short` empty) |

---

## 4. Phase Summaries

### 4.1 Phase 1 — Memory-First Intelligence Core

| Task | Summary | Evidence |
|---|---|---|
| PH1-MEM-001 | Store full assistant output for truncated turns. | `tools/router_py/test_memory_continuation.py` |
| PH1-MEM-002 | Reserve continuation budget and detect continuation queries. | `tools/router_py/test_execution_engine_memory.py` |
| PH1-MEM-003 | Add continuation re-generation instruction to prompt. | `tools/router_py/test_memory_continuation.py` |
| PH1-MEM-004 | Strengthen memory-priority prompt instruction in local and augmented paths. | `tools/router_py/test_local_answer.py`, `tools/router_py/test_execution_engine_memory.py` |
| PH1-MEM-005 | Add model-family-aware prompt shaper for memory preamble. | `tools/router_py/test_stage_07_prompt_parity.py` |

### 4.2 Phase 2 — Tourism Sources

| Task | Summary | Evidence |
|---|---|---|
| PH2-TOUR-001 | Improve Israel destination extraction. | `tools/unverified_context_trusted.py`, `tools/router_py/test_travel_israel.py` |
| PH2-TOUR-002 | Add Israel Ministry of Tourism fetcher with 24-hour file cache. | `tools/unverified_context_trusted.py::_fetch_israel_travel_summary`, `tools/router_py/test_travel_israel.py` |
| PH2-TOUR-003 | Generalise travel fetcher to Wikivoyage for arbitrary destinations. | `tools/unverified_context_trusted.py::_fetch_wikivoyage_summary`, `config/trust/generated/travel_runtime.txt`, `tools/router_py/test_travel_general.py` |
| PH2-TOUR-004 | Route tourism recommendations to `AUGMENTED/trusted`; keep safety/advisory travel queries on `EVIDENCE/trusted`. | `tools/router_py/policy_router/gates.py`, `tools/router_py/pipeline/route.py`, `tools/router_py/test_travel_routing.py`, `tools/router_py/test_policy_router.py` |

### 4.3 Phase 3 — Verification & Cross-Model Guarantees

| Task | Summary | Evidence |
|---|---|---|
| PH3-T12-001 | Add model residency helper with tests. | `tools/router_py/model_residency.py`, `tools/router_py/test_model_residency.py` |
| PH3-T13-001 | Enforce single-model residency assertions in all model stages. | `stage_08`, `stage_09`, `stage_10`, `stage_11`, `stage_13`, `stage_16` |
| PH3-T14-001 | Extend shared scenario suites with cross-model memory continuity cases. | `stage_09_gemma_scenario_suite.py`, `stage_11_llama_scenario_suite.py` |
| PH3-T15-001 | Extend model switch stage with memory continuity. | `stage_13_model_switch.py` |
| PH3-T16-001 | Assert single-model residency in HMI real-routing tests. | `tools/router_py/test_hmi_real_routing.py` |
| PH3-T17-001 | Phase 3 regression gate passed. | `stage_08`, `stage_10`, `stage_13` |

### 4.4 Phase 4 — Reporting & Handoff

| Task | Summary | Evidence |
|---|---|---|
| PH4-RPT-001 | Update qualification status files with final state. | `qualification/TEST_STATUS.json`, `qualification/TEST_TODO.md` |
| PH4-RPT-002 | Write final completion report. | This file |
| PH4-RPT-003 | Update session handoff. | `qualification/SESSION_HANDOFF.md` |
| PH4-RPT-004 | Copy report/handoff to desktop and archive stale copies. | `~/Desktop/Local Lucy V11/`, `Local_Lucy_V11_Archive/` |

---

## 5. Test Results (Current)

All results below were obtained during the final qualification session.

### 5.1 Full deterministic regression

```bash
python3 -m pytest tools/router_py -v --tb=short
```

**Result:** `1314 passed, 7 skipped, 275 deselected, 188 subtests passed` (2026-08-07T07:54Z).

The 7 skipped tests are live OpenAI/Kimi API tests requiring external credentials. The 275 deselected tests are excluded by default pytest markers (`slow`, `live`, etc.).

### 5.2 Memory-service and memory-continuation tests

```bash
python3 -m pytest tools/tests/test_memory_service_unit.py \
  tools/tests/test_memory_requalification.py \
  tools/router_py/test_execution_engine_memory.py \
  tools/router_py/test_memory_continuation.py \
  tools/router_py/test_memory_gate.py \
  tools/router_py/test_location_memory.py -v --tb=short
```

**Result:** all targeted memory tests pass.

Coverage:
- Recent verbatim recall (12 turns).
- Semantic older-turn recall (8 turns).
- Explicit recall and topic-shift handling.
- Correction/supersession.
- Entity isolation.
- Context-budget behaviour.
- Continuation detection, budget reserve, and re-generation instruction.
- Full-text storage for truncated turns.

### 5.3 Memory continuity integration stages

| Stage | Result |
|---|---|
| `stage_09_gemma_scenario_suite.py` | 16/16 passed; `S09-MEM-001` mentions `Spark` |
| `stage_11_llama_scenario_suite.py` | 16/16 passed; 16/16 route parity, 16/16 outcome parity, 4/4 entity parity |
| `stage_13_model_switch.py` | 4/4 passed; cross-model continuation mentions `Oscar` and continues narrative |

### 5.4 Tourism/travel regression gate

```bash
python3 -m pytest tools/router_py/test_travel_routing.py \
  tools/router_py/test_travel_israel.py \
  tools/router_py/test_travel_general.py \
  tools/router_py/test_policy_router.py -v --tb=short
```

**Result:** `95 passed, 0 failed` (2026-08-07T10:00:51Z).

### 5.5 Metric correction

`qualification/results/baseline_metrics.json` contains correct values.

**Corrected metrics:**
- Validation: 21/21 = 1.000
- Holdout: 13/15 = 0.867
- Combined: 34/36 = 0.944

A consistency test (`qualification/test_baseline_metrics_consistency.py`) verifies that `reported correct / total == reported raw accuracy`.

### 5.6 Holdout misroutes

The locked holdout result is 13/15. The two failures were investigated individually:

| Case | Query | Expected | Actual raw classifier | Final post-guard | Classification |
|---|---|---|---|---|---|
| HOLD-ANAPH-001 | "Can you search again?" | AUGMENTED | LOCAL | LOCAL | `ACTIVE_DEFECT` — fixed by extending `_SEARCH_TOOL_IMPERATIVE_PATTERN` in `tools/router_py/main.py` to match "search again" / "search once more". Regression tests added. |
| HMI-ANAPH-001 | "Use DuckDuckGo search" | AUGMENTED | LOCAL | LOCAL | `TEST_EXPECTATION_ERROR` — the holdout metric intentionally excludes `main.py` anaphora/context resolution, so a bare imperative cannot route AUGMENTED in isolation. The real HMI path was fixed earlier and remains functional. |

Neither failure crosses a safety, privacy, trusted-source, or capability boundary.

### 5.7 Voice text-display issue

The reported issue (question/answer text not displayed in the HMI during voice mode) was investigated using:

- `tools/router_py/test_voice_request_parity.py` (7 passed)
- `tools/router_py/test_e2e_hmi_voice.py` (15 passed)
- `tools/router_py/stage_18_voice_smoke.py` (requires `LUCY_ENABLE_VOICE_TESTS=1`)

The issue was **not reproduced** in the available static/HMI test harness. It is documented as `UNREPRODUCED` in `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md`, with suspected UI-refresh causes noted.

### 5.8 Guard boundary tests

`TestGuardBoundaries` in `tools/router_py/test_policy_router.py` covers:

- Restaurant + opening time
- Restaurant + weather
- Travel planning + weather
- Residence statement + weather
- Standalone residence statement
- Arithmetic containing evidence-like wording
- Medical-memory recall that should not trigger web evidence
- Explicit local-only current-information request

Weather/time low-confidence fallback boundary tests are in `tools/router_py/test_classify_low_confidence.py`.

### 5.9 Privacy and fault verification

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

`LUCY_FORCE_LOCAL=1` was found not to be honoured by the classifier; this was fixed in `tools/router_py/classify_core/intent.py` so that the env var sets `classification.force_local`.

### 5.10 Sequential model verification

| Stage | Result |
|---|---|
| `stage_08_gemma_smoke.py` | 3/3 passed |
| `stage_09_gemma_scenario_suite.py` | 16/16 passed |
| `stage_10_llama_smoke.py` | 3/3 passed |
| `stage_11_llama_scenario_suite.py` | 16/16 passed, 16/16 route parity, 16/16 outcome parity, 4/4 entity parity |
| `stage_13_model_switch.py` | 4/4 passed |

`ollama ps` confirmed no dual-model residency after any stage.

### 5.11 Soak and final clean run

```bash
python3 tools/router_py/stage_16_hmi_soak.py
python3 tools/router_py/stage_16_hmi_weather_boundary.py
python3 tools/router_py/stage_19_clean_run.py
```

- HMI soak: 6/6 passed
- Weather/time boundary: 6/6 passed
- Final clean run: **7/7 stages passed** on commit `ed26695` (2026-08-07T13:40Z)

---

## 6. Task 18 Memory-Continuity Fixes

The first Task 18 clean run (commit `b432b7a`) failed two memory-continuity cases:

- `S09-MEM-001`: Gemma story continuation did not mention `Spark`.
- `stage_13_model_switch`: Llama continuation did not mention `Oscar` or continue the narrative.

Root causes fixed in commit `5591c1a`:

1. Story-continuation queries were treated as generic chat, receiving the "two short sentences" budget.
2. The continuation reserve at the end of `session_memory` was sliced off by `LocalAnswer.generate_answer`'s `max_context_chars` truncation.
3. The continuation instruction was too generic.
4. The response cache key ignored `session_memory`, allowing a cached continuation from one context to be reused in another.
5. The text-file fallback in `helpers.py` was used whenever SQLite returned empty context, leaking memory across sessions.
6. `stage_13_model_switch.py` reused the same memory namespace across runs.
7. The memory service's topic-shift detector classified "Continue the story." as a topic shift, returning an empty context string.

Files changed:
- `tools/router_py/local_answer_core/engine.py`
- `tools/router_py/execution_engine/helpers.py`
- `tools/memory/memory_service.py`
- `tools/router_py/stage_13_model_switch.py`

After the fixes, the clean run passed 7/7 and both continuity cases (`Spark`, `Oscar`) passed.

---

## 7. Known Limitations and Active Defects

### Active defects

None.

### Accepted limitations

1. **HMI-ANAPH-001:** `Use DuckDuckGo search` holdout expectation assumes `main.py` anaphora context that `compute_baseline_metrics.py` excludes; classified as `TEST_EXPECTATION_ERROR`.
2. **Persistent-fact correction authority:** Newer contradictory facts are stored and retrieved but not automatically preferred over older facts without explicit user management.
3. **Generic low-confidence → AUGMENTED fallback:** Not implemented and not added during stabilisation.
4. **Voice text-display issue:** Reported but unreproduced in static/HMI tests; documented as `UNREPRODUCED` in `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md`.

---

## 8. Recommendations for Next Improvements

These are suggestions for future work, **not** part of this upgrade mandate.

### 8.1 Accuracy

1. **Expand tourism/travel trusted sources** beyond Israel and Wikivoyage.
2. **Improve medical evidence freshness handling.** Add fallback chain and freshness confidence flags for 404/allowlist misses.
3. **Expand the routing failure corpus** with user-reported cases and retrain the classifier head, verifying against the frozen validation corpus before promotion.
4. **Do not add a generic low-confidence → AUGMENTED fallback.** Any future escalation policy must distinguish intent uncertainty, evidence freshness, explicit network requests, safety domain, capability restrictions, and `force_local`.

### 8.2 Flexibility

1. Surface the existing memory knobs (`LUCY_MEMORY_RECENT_TURN_LIMIT`, `LUCY_MEMORY_MAX_INJECTED_TURNS`, `LUCY_MEMORY_MAX_CHARS`) in the HMI.
2. Evaluate raising `_max_injected_sessions()` from 1 to 2–3 once topic-shift gating is further validated.
3. Investigate model hot-swap latency; consider a lightweight keep-alive strategy.

### 8.3 Intelligence

1. **Conversation-position-aware retrieval:** Add structured conversation state (topic segments, unresolved questions, preferences) rather than flat turn retrieval.
2. **Truncation continuity:** Detect truncated outputs and add a "continue" handler that re-injects the last assistant turn.
3. **Self-correction loop:** Use user feedback to re-route or re-query evidence.
4. **Multi-hop meta-conversation:** Recognise intent such as "Read my last answer" → "look at the context" and respond from stored transcript.

### 8.4 Immediate next steps

1. Expand tourism/travel trusted sources.
2. Add HMI toggles for memory depth knobs.
3. Expand routing failure corpus and retrain classifier head.
4. Remove remaining `v10` references in v11 filenames/code.
5. Revisit the voice text-display issue with live voice tests (`LUCY_ENABLE_VOICE_TESTS=1`) once a reproducible scenario is found.

---

## 9. Appendices

### A. Key files

- `qualification/FINAL_QUALIFICATION_MANIFEST.json` / `.md` — immutable manifest (references previous candidate `423e5dd`)
- `qualification/FINAL_REQUALIFICATION_BASELINE.md` — pre-requalification baseline
- `qualification/STAGE_00_03_TRACEABILITY.md` — requirement-to-evidence mapping
- `qualification/KNOWN_LIMITATIONS.md` — limitations and defect classifications
- `qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md` — unreproduced voice issue
- `qualification/DECISIONS.md` — architectural decisions
- `qualification/DEFECT_REGISTER.md` — defect history
- `qualification/TEST_STATUS.json` — machine-readable status
- `qualification/TEST_TODO.md` — completed task list
- `qualification/SESSION_HANDOFF.md` — session handoff
- `qualification/COMPLETION_REPORT_2026-08-07_MEMORY_TOURISM.md` — this report

### B. Commands to resume

```bash
cd /home/mike/lucy-v11
cat qualification/COMPLETION_REPORT_2026-08-07_MEMORY_TOURISM.md qualification/TEST_TODO.md qualification/TEST_STATUS.json qualification/SESSION_HANDOFF.md
```

### C. Environment knobs

- `LUCY_MEMORY_RECENT_TURN_LIMIT` — verbatim recent turns (default 12)
- `LUCY_MEMORY_MAX_INJECTED_TURNS` — semantic older turns (default 8)
- `LUCY_MEMORY_MAX_CHARS` — memory context budget (config default 2000; execution engine uses 2400)
- `LUCY_MEMORY_SIMILARITY_THRESHOLD` — semantic threshold (default 0.70)
- `LUCY_MEMORY_TOPIC_SHIFT_THRESHOLD` — topic-shift threshold (default 0.50)
- `LUCY_FORCE_LOCAL=1` — forces local routing

---

*End of report.*
