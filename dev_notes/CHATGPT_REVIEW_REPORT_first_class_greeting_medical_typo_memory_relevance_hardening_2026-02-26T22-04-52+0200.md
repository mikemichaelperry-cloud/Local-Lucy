# ChatGPT Review Report: First-Class Greeting Fix + Medical Typo Routing + Memory Relevance Hardening (with Regression Coverage)
Date: February 26, 2026
Time: 22:04:52 +0200
Project: `/home/mike/lucy/snapshots/opt-experimental-v2-dev`

## Executive Summary
This session focused on converting recent UX/safety fixes from wrapper-only mitigations into more first-class, test-backed behavior in shared paths, while preserving compatibility with voice mode and session memory modes.

Primary outcomes:
- Greeting empty-output issue is now fixed at the producer boundary (`tools/local_answer.sh`), not only by `lucy_chat.sh` wrapper fallback.
- `Tadalifil` typo no longer bypasses medical routing; typo-normalized medical queries route to validated/evidence behavior.
- Vague prompts like `Hmm.` no longer inappropriately inject stale session memory context into local answers.
- Wrapper safety net for marker-only local output remains in place and is now explicitly regression-tested.
- All targeted regressions and relevant voice/memory/routing suites passed after fixes.
- Live launcher PTY retests confirmed the exact user-reported problematic sequences are now behaving safely and more coherently.

## Context / Why This Session Was Needed
A live v2-dev launcher transcript exposed two important remaining issues after earlier fixes:
1. Medical typo bypass:
- `What is Tadalifil?` returned a local answer (unsafe routing outcome for a high-risk domain), while subsequent related queries (`interactions`, `side effects`) correctly routed to medical validated insufficiency.
- This inconsistency pointed to a routing/classifier typo normalization gap.

2. Memory relevance failure for vague prompt:
- `Hmm.` produced an Oscar-related memory callback that was contextually inappropriate.
- This showed over-eager memory injection in local-answer prompt construction.

Additionally, the session included a deliberate move toward first-class fixes and new regression coverage, with explicit caution to avoid breaking existing behavior.

## Scope of Work Completed
1. Implemented first-class greeting fix in `tools/local_answer.sh` (producer-level, before model invocation).
2. Added new regressions for recent UX fixes (greeting, Israel-news no-warning leak/key specificity, tube fallback formatting).
3. Fixed a missed patch target in `lucy_chat.sh` news path (warning suppression applied to correct `run_news()` call site).
4. Added and validated a wrapper-level safety-net regression for marker-only local output.
5. Detected and fixed a regression introduced during wrapper detector implementation (valid local outputs were incorrectly treated as empty).
6. Hardened typo medical routing (`Tadalifil`) in router classifier.
7. Added defense-in-depth medical guard in `tools/local_answer.sh`.
8. Added memory relevance gating in `tools/local_answer.sh` for vague backchannel prompts.
9. Added/updated regressions for typo-medical classification and memory relevance behavior.
10. Performed live PTY launcher retests for identity prompts and the exact typo-medical + `Hmm.` sequence.

## Detailed Changes and Intent
### 1) First-Class Greeting Fix in Local Producer
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/local_answer.sh`

What changed:
- Added deterministic greeting short-circuit for greeting-only prompts such as:
  - `hi`
  - `hello`
  - `hey`
  - `good morning`
  - `good afternoon`
  - `good evening`
  - optional `Lucy` suffix
- This runs before `ollama` invocation and before requiring `ollama` to exist.

Why (intent):
- Fix the empty greeting response problem at the source, not only in the wrapper.
- Eliminate unnecessary model calls and reduce nondeterminism for simple salutations.
- Make greeting behavior testable in isolation without local model runtime dependency.

### 2) Wrapper Safety Net Retained and Regression-Tested
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/lucy_chat.sh`

What changed (this session):
- No removal of the wrapper safety net; kept as intentional backup.
- Fixed the implementation of `local_output_effectively_empty()` to use stdin-safe `awk`.

Why (intent):
- Retain defense-in-depth while local producer output remains probabilistic in other cases.
- Ensure the safety net does not corrupt valid local responses.

### 3) Medical Typo Routing Hardening (`Tadalifil`)
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/router/classify_intent.py`

What changed:
- Extended typo normalization to handle `tadalifil -> tadalafil` with a punctuation-safe regex pass.

Why (intent):
- Prevent typo-spelled medical prompts from slipping into LOCAL_KNOWLEDGE routing.
- Preserve consistent medical safety routing despite common misspellings.

### 4) Defense-in-Depth Local Medical Guard
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/local_answer.sh`

What changed:
- Added a pre-model medical high-risk guard using:
  - `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/query_policy.sh is-medical-high-risk`
- Includes fallback regex if `query_policy.sh` is unavailable.
- Returns deterministic local refusal to online mode:
  - `This requires evidence mode.`
  - `Run: run online: <query>`

Why (intent):
- Defense in depth in case router classification misses a high-risk medical prompt.
- Keep local producer from answering medical high-risk prompts offline.

### 5) Memory Relevance Hardening for Vague Backchannels
File:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/local_answer.sh`

What changed:
- Added `memory_context_allowed_for_query()` to suppress session memory injection for vague/affect-only prompts including examples like:
  - `hmm`
  - `ok` / `okay`
  - `thanks`
  - `useless`
  - `meh`
- Clears injected session-memory context before prompt construction for such turns.

Why (intent):
- Avoid irrelevant memory anchoring on vague prompts (`Hmm.` should not revive stale Oscar topic).
- Preserve memory use for genuinely referential prompts.

### 6) New and Updated Regression Coverage
New tests:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_local_answer_greeting_nonempty.sh`
  - Producer-level greeting determinism/non-empty behavior
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_news_israel_specificity_no_warning_leak.sh`
  - No user-facing leakage of `WARN:` / `FETCH_META`
  - Israel-news key specificity prevents generic `news_world_*` contamination
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_tube_primary_doc_fallback_urls.sh`
  - Tube fallback URLs are tube-specific, no IC-vendor spillover
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_lucy_chat_local_empty_output_safety_net.sh`
  - Wrapper safety-net recovery for marker-only local output
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_local_answer_memory_relevance_vague_prompt.sh`
  - Vague prompt suppresses memory injection
  - Referential prompt still includes memory injection

Updated regression:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/router/router_regression.sh`
  - Added classifier assertions for `What is Tadalifil?` -> `MEDICAL_INFO` / `VALIDATED`

Why (intent):
- Convert fragile user-facing fixes into stable, automated expectations.
- Protect against regressions during future router/memory/local-answer refactors.

## Deviations / Unexpected Outcomes During This Session (and Resolutions)
### A. Regression introduced by wrapper empty-output detector (fixed in-session)
Observed:
- Valid local responses (identity prompts like `Who am I?`, `Who is Oscar?`, `Who is Racheli?`) were replaced by the generic fallback:
  - `I'm here. Please ask your question again.`

Root cause:
- The wrapper helper `local_output_effectively_empty()` used a heredoc-fed Python helper and failed to read piped local output correctly, causing false "empty" detection.

Resolution:
- Replaced helper with stdin-safe `awk` implementation in `lucy_chat.sh`.
- Reran safety-net/greeting regressions and live PTY identity prompt checks.

Status:
- Fixed and verified live.

### B. Missed patch target for news warning suppression (fixed in-session)
Observed:
- New no-warning-leak test still saw `WARN:` and `FETCH_META` in output.

Root cause:
- Earlier stderr suppression had been applied to `run_evidence()` call site, not the actual `run_news()` pack-build call site.

Resolution:
- Patched correct `run_news()` `build_evidence_pack.sh` invocation in `lucy_chat.sh`.
- Reran regression and live launcher Israel-news prompt verification.

Status:
- Fixed and verified.

### C. Test harness bugs while adding new regressions (all fixed)
Encountered and fixed:
- `awk` quoting bug parsing `SESSION_ID` in news regression
- fake `evidence_session.sh` key serialization bug in same test
- wrong env var (`SESSION_MEMORY_CONTEXT` instead of `LUCY_SESSION_MEMORY_CONTEXT`) in memory relevance test
- referential test prompt accidentally matched identity logic (`what are you ...`) and bypassed memory path

Status:
- All test harness issues corrected; final tests pass.

## Validation and Test Results
### New/updated targeted regressions (all PASS)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_local_answer_greeting_nonempty.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_news_israel_specificity_no_warning_leak.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_tube_primary_doc_fallback_urls.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_lucy_chat_local_empty_output_safety_net.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_local_answer_memory_relevance_vague_prompt.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/router/router_regression.sh` (with `Tadalifil` assertion)

### Existing no-break / compatibility regressions (all PASS)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_query_policy_shared_heuristics.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_voice_online_heuristic_routing.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_launcher_memory_isolation.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_nl_chat_memory_isolation.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_router_vs_fallback_mode_drift_monitor.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/tests/test_lucy_chat_router_forced_mode_strict.sh`

### Syntax check
- `bash -n /home/mike/lucy/snapshots/opt-experimental-v2-dev/lucy_chat.sh` -> PASS

## Live Launcher PTY Retests (User-Facing Validation)
Launcher used:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/tools/start_local_lucy_opt_experimental_v2_dev.sh`

### Identity regression retest after wrapper-detector fix
Confirmed restored behavior (no generic fallback hijack):
- `Who am I?` -> correct Michael profile answer
- `Who is Oscar?` -> normal local response (model-variable content, but no wrapper corruption)
- `Who is Racheli?` -> correct relationship-aware response

### Typo-medical + follow-up + vague prompt sequence retest
Sequence tested live:
- `What is Tadalifil?`
- `What are it interactions?`
- `What are side effects?`
- `What are Tadalifil side effects?`
- `Hmm.`

Observed results:
- `What is Tadalifil?` -> `BEGIN_VALIDATED ... Insufficient evidence from trusted sources. ... END_VALIDATED`
- Follow-up medical prompts -> same validated insufficiency behavior (consistent medical routing)
- `Hmm.` -> generic reflective response (no Oscar memory hijack)

Interpretation:
- Medical typo routing bypass is fixed.
- Vague-prompt memory overreach is reduced as intended.

## Residual Risks / Notes
1. `Who is Oscar?` remains model-variable in local mode
- Behavior is no longer corrupted by wrapper fallback, but answer content can vary (e.g., Oscar Wilde vs “need more context”).
- This is a determinism issue, not a routing/safety issue.

2. Wrapper empty-output safety net remains in place intentionally
- Producer-level greeting fix is first-class now, but wrapper safety net is retained as a tested backup layer.
- This is deliberate defense-in-depth while local producer outputs remain nondeterministic in some cases.

3. Local medical guard is defense-in-depth, not a substitute for routing correctness
- Primary expected behavior should still come from correct router classification (`MEDICAL_INFO` -> validated/evidence path).
- The local guard reduces risk if routing ever misses a high-risk prompt.

## Artifacts / Continuity Notes
Primary handoff for this session’s changes:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T22-02-15+0200.md`

Prior related handoff (same evening):
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T21-18-27+0200.md`

Prior broader review report (same evening):
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_router_dedup_phase2_completion_and_full_live_regression_2026-02-26T20-43-37+0200.md`

This report:
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_first_class_greeting_medical_typo_memory_relevance_hardening_2026-02-26T22-04-52+0200.md`

## Recommended Next Steps (Optional)
1. Add a repeatable live-launcher smoke harness (if practical) for the exact typo-medical + `Hmm.` sequence to complement the unit/fake-root tests.
2. If local proper-name determinism matters, add constrained handling or tests for person-name lookups (`Who is Oscar?`) to reduce model variability.
3. After more soak time, consider narrowing/removing the wrapper empty-output safety net if producer-level fixes and regression coverage prove sufficient.
