# Local Lucy v7 Review Brief for ChatGPT

## Purpose

Review the current Local Lucy v7 state as a local-first operator console and runtime, with emphasis on:

1. routing and fallback coherence
2. operator trust and UI clarity
3. runtime/state authority correctness
4. prompt quality and failure modes in augmented fallback answers
5. likely design risks that are not obvious from happy-path demos

This is a critical review request, not a marketing summary.

## Project Context

Local Lucy v7 is a local-first assistant/runtime with an operator UI. It supports:

- local answers
- evidence mode
- augmented fallback answers
- explicit runtime truth/state surfaces
- operator / advanced / engineering / service interface levels

The current active authority root is:

- `/home/mike/lucy/snapshots/opt-experimental-v7-dev`

The authoritative runtime namespace root is:

- `/home/mike/.codex-api-home/lucy/runtime-v7`

There is also a stale parallel legacy tree that still exists physically:

- `/home/mike/lucy/runtime-v7`

It is intentionally surfaced as stale instead of being silently used.

## Current Intent

The desired behavior is:

- Operator settings should be honored predictably.
- Weak local answers should degrade into a known fallback path.
- `fallback_only` plus explicit provider `openai` should use OpenAI only when needed.
- The UI should explain what happened without exposing backend scaffolding.
- The UI should only appear trustworthy when backed by persisted runtime/state truth.

## What Changed Recently

Recent fixes in this session:

- Unified v7 default runtime namespace resolution around `/home/mike/.codex-api-home/lucy/runtime-v7`.
- Added visibility for stale legacy runtime namespace ambiguity.
- Fixed AUTO-mode local degradation so weak local outputs escalate to configured augmented fallback instead of surfacing canned low-value prompts.
- Ensured fallback paths honor explicit configured augmented provider such as `openai`.
- Improved Operator UI so routing/fallback decisions are visible without switching to Engineering mode.
- Cleaned Operator answer rendering to strip backend scaffolding.
- Tightened augmented fallback prompting for lower token use and more direct answers.
- Added a live augmented-output eval runner and case pack.
- Fixed a real bug where augmented local generation was evaluating evidence guards against the serialized prompt block instead of the extracted user question.
- Added an augmented completion guard so short outputs do not end mid-thought.

## Current Evidence

Latest live augmented-output report:

- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tmp/live_augmented_operator_eval/20260328T230632+0300/summary.md`

Latest live augmented-output status:

- 5/5 pass on the current compact operator-style case pack
- no false `This requires evidence mode.` escalations in augmented fallback path for those cases
- no backend scaffolding leakage in those cases
- bounded brevity on those cases

Important caveat:

- The eval pack is useful but small. It demonstrates progress, not full robustness.

## Relevant Files

Runtime / routing / fallback:

- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/router/execute_plan.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/local_answer.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/unverified_context_provider_dispatch.py`

Runtime truth / namespace handling:

- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/runtime_control.py`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/runtime_request.py`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/runtime_lifecycle.py`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/runtime_voice.py`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/diag/print_runtime_authority_chain.py`

UI:

- `/home/mike/lucy/ui-v7/app/panels/status_panel.py`
- `/home/mike/lucy/ui-v7/app/panels/conversation_panel.py`
- `/home/mike/lucy/ui-v7/app/main_window.py`
- `/home/mike/lucy/ui-v7/app/services/state_store.py`
- `/home/mike/lucy/ui-v7/app/services/log_watcher.py`

Focused tests:

- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_execute_plan_local_degraded_answer_uses_openai_fallback.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_execute_plan_augmented_fallback_openai_provider.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_local_answer_augmented_prompt_contract.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_local_answer_augmented_operator_prompt_pack.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_local_answer_augmented_bypasses_serialized_evidence_guard.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_local_answer_augmented_allows_current_terms.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v7-dev/tools/tests/test_local_answer_augmented_completion_guard.sh`

## What Needs Critical Review

Please review these areas critically:

### 1. Routing Contract

- Is the local -> augmented fallback contract coherent and maintainable?
- Are there hidden cases where explicit provider selection in fallback paths could violate broader AUTO-mode expectations?
- Is the distinction between local answers, evidence answers, and unverified augmented fallback answers clean enough?

### 2. Truth / State Authority

- Is the authority-root approach sound, or overly brittle?
- Does the stale legacy runtime tree create operational risk even when surfaced explicitly?
- Are there cleaner patterns for preventing namespace drift?

### 3. Prompt / Output Quality

- Is the current augmented fallback prompting too brittle or over-tuned to the current case pack?
- What likely failure modes remain for vague operator prompts, person/entity summaries, or “current projects” style asks?
- Is the completion-guard approach a reasonable stopgap, or a sign that generation control is being handled in the wrong layer?

### 4. Operator UI Trustworthiness

- Does the Operator view now expose enough routing truth without leaking backend internals?
- What still feels misleading, overly technical, or too compressed for a real operator?
- Are the current decision-trace and path labels the right abstraction level?

### 5. Test Strategy

- Are the current focused regressions sufficient for this architecture?
- What high-value tests are still missing?
- Is the compact live eval pack likely to create false confidence?

### 6. General Design Risk

- What architectural weaknesses are most likely to cause v7 to regress as complexity increases?
- Which current choices look like pragmatic good debt, and which look like bad debt?

## What I Want Back

Please answer in this structure:

1. Top 5 findings
2. Most important architectural risk
3. Most important operator-trust risk
4. Most important prompt-quality risk
5. Specific recommendations
6. Quick verdict: keep current direction, adjust it, or rethink part of it

Be direct. Prefer identifying weak assumptions, brittle seams, and hidden complexity over praising what works.
