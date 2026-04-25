# Local Lucy ChatGPT Full Report

Date: 2026-03-16 19:43:59 +0200
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`
Audience: ChatGPT review

## Executive Summary

This pass completed a full routing stabilization cycle on the active dev snapshot.

The highest-priority failures from the earlier edge sweep were fixed first:

- authority-boundary leaks where non-local prompts were answered via `LOCAL`
- ambiguous short followups being answered locally instead of clarified
- original-query provenance corruption on rewritten `NEWS` execution paths

After those fixes, a second pass added explicit routing-signal telemetry and tightened the temporal/geopolitics ladder without breaking the authority boundaries.

Latest full edge sweep result:

- prompts tested: `156`
- rule-consistent cases: `156/156`
- provenance preserved: `156/156`
- anomalies: `0`
- authority-boundary violations: `0`

Primary conclusion:

- architecture remains intact
- routing is now stable on the current sweep corpus
- the next work should move from emergency boundary repair to targeted tuning

## Architecture Status

The intended architecture still appears to hold:

- governor/router owns route and contract decisions
- execution remains policy-blind in the architectural sense
- `EVIDENCE`, `NEWS`, and doc-style non-local paths remain authoritative
- `LOCAL` is bounded to safe local knowledge / conversation only
- `CLARIFY` is deterministic and governor-owned

This pass did not move policy decisions into execution.

## What Changed In This Pass

### 1. High-priority boundary leaks were fixed

Previously leaking prompts such as the following no longer hit `LOCAL`:

- `What are the current tensions in the South China Sea?`
- `Is there currently a ceasefire in Gaza?`
- `Has the filing deadline for US taxes changed this year?`
- `what happening south china sea rn`

Changes included:

- broader temporal/freshness recognition
- broader current-conflict/news detection
- better Israel-region hinting for time-sensitive conflict/news prompts

### 2. Ambiguous short followups now clarify

The router now clarifies instead of speculating for prompts like:

- `Tell me more about it.`
- `Is it safe?`
- `How about now?`
- `Which one is better?`
- `Can you continue?`

### 3. Medical contextual carryover was fixed

Followups such as:

- previous: `Is Lipitor safe with grapefruit?`
- followup: `And grapefruit?`

now resolve into explicit medical followups and remain evidence-gated instead of falling into `LOCAL`.

### 4. Conceptual vs live/commercial prompts were separated better

These cases now behave correctly:

- `What is inflation?`
  - conceptual
  - `LOCAL`

- `Tell me what RAM is and recommend a current laptop.`
  - live/commercial mixed intent
  - non-local route

### 5. Original-query provenance was repaired

`execute_plan.sh` now preserves:

- top-level `QUERY` as the literal original user prompt
- `original_query` as immutable trace data
- `resolved_execution_query` as the rewritten execution form when rewrite occurs

### 6. Explicit routing-signal telemetry was added

New explicit telemetry now surfaces the signal layer directly rather than only aggregate reason strings.

Examples now exposed in dry-run / outcome telemetry:

- `ROUTING_SIGNAL_TEMPORAL`
- `ROUTING_SIGNAL_NEWS`
- `ROUTING_SIGNAL_CONFLICT`
- `ROUTING_SIGNAL_GEOPOLITICS`
- `ROUTING_SIGNAL_ISRAEL_REGION`
- `ROUTING_SIGNAL_SOURCE_REQUEST`
- `ROUTING_SIGNAL_URL`
- `ROUTING_SIGNAL_AMBIGUITY_FOLLOWUP`
- `ROUTING_SIGNAL_MEDICAL_CONTEXT`
- `ROUTING_SIGNAL_CURRENT_PRODUCT`

Shared signal logic now lives in:

- `tools/router/core/routing_signals.py`

## Files Changed

- `tools/router/core/routing_signals.py`
- `tools/router/core/intent_classifier.py`
- `tools/router/policy_engine.py`
- `tools/router/core/policy_router.py`
- `tools/router/plan_to_pipeline.py`
- `tools/router/core/contextual_policy.py`
- `tools/router/execute_plan.sh`
- `tools/tests/test_phase1_classifier_output.sh`
- `tools/tests/test_router_current_conflict_news_routing.sh`
- `tools/tests/test_execute_plan_phase1_clarify.sh`
- `tools/tests/test_execute_plan_context_followup_carryover.sh`
- `tools/tests/test_policy_engine_auto_routing.sh`
- `tools/tests/test_execute_plan_preserves_original_query_after_news_rewrite.sh`
- `tools/tests/test_execute_plan_routing_signal_telemetry.sh`

## Validation Summary

Targeted tests passed:

- `bash tools/tests/test_phase1_classifier_output.sh`
- `bash tools/tests/test_policy_engine_auto_routing.sh`
- `bash tools/tests/test_execute_plan_phase1_clarify.sh`
- `bash tools/tests/test_execute_plan_context_followup_carryover.sh`
- `bash tools/tests/test_router_current_conflict_news_routing.sh`
- `bash tools/tests/test_execute_plan_preserves_original_query_after_news_rewrite.sh`
- `bash tools/tests/test_semantic_trace_preserves_literal_original_query.sh`
- `bash tools/tests/test_execute_plan_routing_signal_telemetry.sh`

Latest full sweep:

- report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-33-54+0200.md`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T19-33-54+0200/results.jsonl`

Sweep summary:

- prompts tested: `156`
- rule-consistent: `156/156`
- provenance preserved: `156/156`
- anomalies: `0`
- authority-boundary violations: `0`
- pipeline distribution:
  - `CLARIFY=12`
  - `EVIDENCE=65`
  - `LOCAL=62`
  - `NEWS=17`

## Important Observations

### Semantic interpreter activation dropped to zero in the final sweep

Latest sweep reported:

- semantic interpreter activation rate: `0/156`

This may be acceptable if the current deterministic router now handles the entire corpus without help, but it is also a possible signal that the interpreter is effectively dormant on this harness.

This should be reviewed rather than assumed safe.

### Remaining known issues

The full sweep no longer shows rule mismatches, but two lower-priority issues remain open:

- some URL prompts still do not land on the preferred doc-style path
- medication-detector trace noise still appears when detector does not fire

## Requested ChatGPT Review Focus

Please review these changes for:

1. Over-escalation risk
   - especially whether shared temporal/geopolitics signals now over-route conceptual prompts

2. Clarify-vs-context behavior
   - especially whether ambiguous short prompts should still clarify when prior context is rich enough to resolve safely

3. Israel-region hinting
   - whether the current signal logic is broad enough to help routing but still narrow enough to avoid conceptual overreach

4. Provenance integrity
   - especially any remaining path where rewritten execution text could overwrite literal user query state

5. Semantic interpreter dormancy
   - whether the `0/156` activation rate looks expected or suspicious on the latest harness

## Related Artifacts

- earlier baseline sweep with failures:
  - `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-15T20-34-57+0200.md`

- clean final sweep:
  - `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-33-54+0200.md`
