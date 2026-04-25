# Local Lucy ChatGPT Report

Date: 2026-03-16 19:13:12 +0200
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Current State

This pass addressed the highest-priority routing failures from the edge prompt sweep:

- authority-boundary leaks where clearly non-local prompts were routed to `LOCAL`
- ambiguous short followups being answered locally instead of clarified
- provenance loss when news prompts were rewritten before execution

The architecture still appears intact:

- governor/router remains the owner of routing and contract decisions
- execution remains policy-blind in the architectural sense
- local generation is still non-authoritative for news/evidence/doc/high-stakes prompts
- evidence/news/doc authority boundaries are now tighter than in the previous sweep

## What Changed In This Pass

### 1. Current/live routing was hardened

Broadened freshness and conflict/news detection so these families no longer fall through to `LOCAL`:

- `What are the current tensions in the South China Sea?`
- `Is there currently a ceasefire in Gaza?`
- `what happening south china sea rn`
- `Has the filing deadline for US taxes changed this year?`

The changes include:

- recognition of `currently`, `this year`, and `rn` as freshness cues
- recognition of `tensions` and `standoff` as current-conflict/news signals
- broader Israel-region hinting for Gaza / Hamas / Hezbollah / Iran / Lebanon-related conflict prompts

### 2. Ambiguous followups now clarify instead of speculating

Short unanchored prompts that previously slipped into `LOCAL` now request clarification:

- `Tell me more about it.`
- `Is it safe?`
- `What do you mean?`
- `And the other one?`
- `Which one is better?`
- `How about now?`
- `Explain it again.`
- `What should I do then?`
- `Is that still true?`

### 3. Medical followup carryover was tightened

Contextual medical followups now stay evidence-gated for cases like:

- previous question: `Is Lipitor safe with grapefruit?`
- followup: `And grapefruit?`

This now resolves into an explicit medical query instead of falling back to `LOCAL`.

### 4. Conceptual vs live/commercial prompts were separated better

Two report anomalies were addressed directly:

- `What is inflation?` now stays on a conceptual local path
- `Tell me what RAM is and recommend a current laptop.` now routes non-locally instead of leaking into `LOCAL`

### 5. Original-query provenance is preserved across rewritten news execution

`execute_plan.sh` was writing state telemetry with the rewritten execution prompt instead of the literal user prompt on some news paths.

This is now fixed so:

- top-level `QUERY` keeps the original user text
- semantic trace keeps `original_query`
- semantic trace separately exposes `resolved_execution_query`

## Files Changed

- `tools/router/core/intent_classifier.py`
- `tools/router/policy_engine.py`
- `tools/router/plan_to_pipeline.py`
- `tools/router/core/contextual_policy.py`
- `tools/router/execute_plan.sh`
- `tools/tests/test_phase1_classifier_output.sh`
- `tools/tests/test_router_current_conflict_news_routing.sh`
- `tools/tests/test_execute_plan_phase1_clarify.sh`
- `tools/tests/test_execute_plan_context_followup_carryover.sh`
- `tools/tests/test_policy_engine_auto_routing.sh`
- `tools/tests/test_execute_plan_preserves_original_query_after_news_rewrite.sh`

## Validation Summary

Targeted tests passed after the fixes:

- `bash tools/tests/test_phase1_classifier_output.sh`
- `bash tools/tests/test_router_current_conflict_news_routing.sh`
- `bash tools/tests/test_policy_engine_auto_routing.sh`
- `bash tools/tests/test_execute_plan_phase1_clarify.sh`
- `bash tools/tests/test_execute_plan_context_followup_carryover.sh`
- `bash tools/tests/test_execute_plan_preserves_original_query_after_news_rewrite.sh`
- `bash tools/tests/test_semantic_trace_preserves_literal_original_query.sh`
- `bash tools/tests/test_execute_plan_preserves_semantic_interpreter_selection.sh`

Focused edge-sweep reruns after the fixes:

- `current_events` subset, limit 6
  - anomalies: `0`
  - boundary violations: `0`
  - report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-10-32+0200.md`

- `ambiguous` subset, limit 9
  - anomalies: `0`
  - boundary violations: `0`
  - report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-11-20+0200.md`

## Remaining Limitations

- the full 156-prompt edge sweep was not rerun in this pass
- URL/doc routing issues noted in the earlier sweep were not addressed yet
- medication-detector trace noise when the detector does not fire was not cleaned up yet

## Suggested ChatGPT Review Focus

Please review these changes specifically for:

- unintended regressions where conceptual prompts are now over-escalated to evidence/news
- false positives in the expanded ambiguous-followup matcher
- over-broad Israel-region mapping for geopolitics/news prompts
- provenance correctness in `execute_plan.sh` for any path that rewrites execution queries
- whether the mixed-intent handling for current product recommendations should remain `EVIDENCE`-first or become a dedicated clarify flow

## Related Artifacts

- original sweep report:
  - `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-15T20-34-57+0200.md`

- current-events subset rerun:
  - `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-10-32+0200.md`

- ambiguous subset rerun:
  - `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-11-20+0200.md`
