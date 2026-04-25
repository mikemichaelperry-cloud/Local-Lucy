# Local Lucy Consolidated Reports

Generated: 2026-03-17T18:30:48+02:00

Purpose: single chronological bundle of unique LOCAL_LUCY markdown reports for external analysis.

Source selection:
- Scope: active-root dev_notes reports plus Desktop-only report artifacts.
- Ordering: chronological by report timestamp in filename.
- Deduplication: identical duplicate copies on Desktop were omitted when the same report also exists in the active root.

## Included Reports

1. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_REPORT_2026-03-14T11-19-40+0200.md
2. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_REPORT_2026-03-16T19-13-12+0200.md
3. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_FULL_REPORT_2026-03-16T19-43-59+0200.md
4. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_GROK_FULL_REPORT_2026-03-16T19-43-59+0200.md
5. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_COMPREHENSIVE_REPORT_2026-03-16T21-17-00+0200.md
6. /home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T21-50-56+0200.md
7. /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_ROUTE_MANIFEST_REPORT_2026-03-16T21-57-31+0200.md
8. /home/mike/Desktop/LOCAL_LUCY_CHATGPT_GROK_STATUS_REPORT_2026-03-16T22-03-05+0200.md
9. /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-50-28+0200.md
10. /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-57-48+0200.md
11. /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-07-43+0200.md
12. /home/mike/Desktop/LOCAL_LUCY_MANIFEST_MIGRATION_REPORT_2026-03-17T18-08-57+0200.md
13. /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-20-46+0200.md
14. /home/mike/Desktop/LOCAL_LUCY_SHARED_STATE_HARDENING_REPORT_2026-03-17T18-22-24+0200.md

---

## LOCAL_LUCY_CHATGPT_REPORT_2026-03-14T11-19-40+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_REPORT_2026-03-14T11-19-40+0200.md

# LOCAL_LUCY_CHATGPT_REPORT
Timestamp: 2026-03-14T11:19:40+0200
Audience: ChatGPT
Active root: /home/mike/lucy/snapshots/opt-experimental-v5-dev
Frozen/stable snapshots: untouched

## Executive Summary
This session applied a low-risk LOCAL performance pass in the active v5 dev snapshot.

The work did not change routing policy, follow-up semantics, or `tools/local_answer.sh` prompt behavior.
It only reduced mechanical overhead in the worker/request envelope above `tools/local_answer.sh`.

The result is a measurable warmed-path improvement, but the dominant remaining LOCAL cost is still orchestration above `tools/local_answer.sh`, especially in the `execute_plan -> lucy_chat -> worker client` envelope.

## What We Changed
- `tools/local_worker_client.sh`
  - replaced many per-request FIFO `ENV` records with one bundled `ENV_SHELL` payload
  - preserved the same effective worker request contract
- `tools/local_worker.py`
  - accepts and forwards the bundled `ENV_SHELL` payload to the persistent `local_answer.sh --worker-stdio` subprocess
  - worker invalidation stamp now covers both `tools/local_answer.sh` and `tools/local_worker.py`
  - this ensures a patched worker protocol actually restarts the real resident worker

## Why This Was Safe
- no router/governor decisions were bypassed
- no contextual follow-up precedence was changed
- no fallback policy was changed
- no prompt-semantic branches were added back into `tools/local_answer.sh`

This was intentionally limited to transport/orchestration mechanics.

## Validation
Passed:
- `bash tools/tests/test_local_worker_basic_roundtrip.sh`
- `bash tools/tests/test_local_worker_repeat_cache.sh`
- `bash tools/tests/test_execute_plan_local_worker_fast_path.sh`
- `bash tools/tests/test_execute_plan_local_direct_repeat_cache.sh`
- `bash -n tools/local_worker_client.sh tools/local_answer.sh tools/router/execute_plan.sh`
- `python3 -m py_compile tools/local_worker.py`

## Benchmark Outcome
Source baseline:
- `/home/mike/Desktop/LOCAL_LUCY_LOCAL_BENCHMARK_REPORT_2026-03-13T22-41-18+0200.md`

Current targeted benchmark:
- `/home/mike/Desktop/LOCAL_LUCY_LOCAL_BENCHMARK_REPORT_2026-03-14T11-11-20+0200.md`

Warmed-path deltas:
- total mean:
  - before: `327.4ms`
  - after: `305.5ms`
  - delta: `-21.9ms`
- local worker roundtrip mean:
  - before: `166.2ms`
  - after: `142.5ms`
  - delta: `-23.7ms`
- worker overhead mean:
  - before: `73.0ms`
  - after: `49.0ms`
  - delta: `-24.0ms`
- run_local_wrapper mean:
  - before: `102.4ms`
  - after: `77.5ms`
  - delta: `-24.9ms`
- orchestration gap mean:
  - before: `47.6ms`
  - after: `50.0ms`
  - delta: `+2.4ms`

## Interpretation
- The low-risk pass worked.
- The worker-envelope tax is lower than before.
- The gain is real but not dramatic: warmed LOCAL improved by about `22ms` overall.
- The main benefit landed in worker/request overhead, not in routing overhead.

## Remaining Dominant Cost
The remaining dominant LOCAL cost is still outside `tools/local_answer.sh`.

Current warmed measurements still show meaningful cost in:
- `tools/router/execute_plan.sh`
- `lucy_chat.sh`
- `tools/local_worker_client.sh`
- `tools/local_worker.py`

The hot path is still best described as:
- `execute_plan -> lucy_chat -> local worker client -> local worker -> local_answer`

`tools/local_answer.sh` itself is no longer the main place to hunt for another easy win.

## Recommended Next Work
If more LOCAL latency work is requested, the next target should be orchestration above `tools/local_answer.sh`, not `local_answer.sh` micro-optimizations.

Most likely next candidates:
- reduce shell/process overhead in `tools/router/execute_plan.sh`
- reduce unnecessary work in `lucy_chat.sh` on clearly local-safe turns
- further simplify worker/client transport only if the contract can remain unchanged

## Related Artifacts
- optimization summary:
  - `/home/mike/Desktop/LOCAL_LUCY_LOCAL_OVERHEAD_OPTIMIZATION_REPORT_2026-03-14T11-11-51+0200.md`
- latest handoff:
  - `/home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/SESSION_HANDOFF_2026-03-14T11-11-51+0200.md`


---

## LOCAL_LUCY_CHATGPT_REPORT_2026-03-16T19-13-12+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_REPORT_2026-03-16T19-13-12+0200.md

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


---

## LOCAL_LUCY_CHATGPT_FULL_REPORT_2026-03-16T19-43-59+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_FULL_REPORT_2026-03-16T19-43-59+0200.md

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


---

## LOCAL_LUCY_GROK_FULL_REPORT_2026-03-16T19-43-59+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_GROK_FULL_REPORT_2026-03-16T19-43-59+0200.md

# LOCAL_LUCY_GROK_FULL_REPORT

Timestamp: 2026-03-16T19-43-59+0200
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`
Audience: Grok / external systems reviewer

## Executive Summary

Local Lucy completed a full routing stabilization pass on the active dev snapshot.

The most dangerous failure classes from the earlier broad sweep were repaired:

- non-local prompts incorrectly answered from `LOCAL`
- ambiguous short followups answered without clarification
- original-query provenance being overwritten by rewritten execution prompts

A second pass then added explicit signal-level routing telemetry and normalized the temporal/geopolitics routing logic into a shared signal layer.

Final verified state on the current 156-prompt edge corpus:

- rule-consistent cases: `156/156`
- provenance preserved: `156/156`
- authority-boundary violations: `0`
- anomalies: `0`

The system now looks operationally stable on the current regression corpus.

## Architecture Status

The intended architecture remains intact:

- governor/router owns route and execution-contract decisions
- execution remains policy-blind in the architectural sense
- trusted evidence/news/doc paths remain authoritative
- `LOCAL` remains bounded
- `CLARIFY` remains governor-owned and deterministic

No new policy ownership was moved into execution.

## Main Engineering Changes

### 1. Boundary leak repair

Prompts that had previously leaked into `LOCAL` no longer do so, including:

- South China Sea tensions
- Gaza ceasefire
- current-year tax deadline changes
- shorthand freshness prompts using `rn`

### 2. Ambiguity handling repair

Short referent-missing prompts now clarify instead of speculating, including:

- `Tell me more about it.`
- `Is it safe?`
- `How about now?`
- `Which one is better?`
- `Can you continue?`

### 3. Medical context carryover repair

High-stakes followups like:

- `Is Lipitor safe with grapefruit?`
- `And grapefruit?`

now stay on an evidence-gated medical path.

### 4. Conceptual vs live split repair

Examples:

- `What is inflation?` -> conceptual / local
- `Tell me what RAM is and recommend a current laptop.` -> live commercial mixed intent / non-local

### 5. Provenance repair

The runtime now preserves:

- literal original prompt as top-level `QUERY`
- immutable `original_query`
- separate `resolved_execution_query`

This closes an important traceability flaw.

### 6. Shared routing-signal layer added

Routing signals are now centralized in:

- `tools/router/core/routing_signals.py`

This layer explicitly exposes signals such as:

- temporal
- news
- conflict
- geopolitics
- Israel-region
- source-request
- URL
- ambiguity-followup
- medical-context
- current-product recommendation

Those signals are now visible in routing/output telemetry instead of being hidden behind only aggregate labels.

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

## Validation

Targeted checks passed:

- classifier routing tests
- policy-engine routing tests
- clarify-path tests
- contextual carryover tests
- conflict/news routing tests
- provenance preservation tests
- semantic-trace preservation tests
- routing-signal telemetry tests

Latest full sweep artifact:

- report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T19-33-54+0200.md`
- raw results: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T19-33-54+0200/results.jsonl`

Full sweep summary:

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

## Important Operational Observation

The latest sweep shows:

- semantic interpreter activation rate: `0/156`

That is not necessarily wrong, but it is notable.

Interpretation options:

- deterministic routing is now sufficient for this corpus
- or the semantic-interpreter path is effectively dormant on this harness

This should be treated as a review item, not ignored.

## Remaining Known Issues

The main stability goal is now achieved, but some lower-priority work remains:

- URL prompts are still not always routed through the preferred doc path
- medication-detector trace output still carries some candidate noise when detector does not fire

## Recommended Next Work

1. Review semantic interpreter activity
   - determine whether `0/156` activation is intended or accidental

2. Tighten URL/doc routing
   - make URL surface handling land consistently on doc-style non-local paths

3. Clean detector trace noise
   - clear non-fired medication candidate fields for cleaner diagnostics

4. Keep the 156-prompt sweep as a required regression gate
   - rerun after any router, interpreter, or followup-context changes

## Overall Assessment

Before this pass:

- architecture was sound
- routing correctness was still unstable

After this pass:

- architecture remains sound
- routing correctness is stable on the full current edge corpus

Most important invariant:

- `LOCAL` no longer answers non-local prompts on the validated sweep corpus

That is the key systems result.


---

## LOCAL_LUCY_CHATGPT_COMPREHENSIVE_REPORT_2026-03-16T21-17-00+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_CHATGPT_COMPREHENSIVE_REPORT_2026-03-16T21-17-00+0200.md

# LOCAL_LUCY_CHATGPT_COMPREHENSIVE_REPORT
Timestamp: 2026-03-16T21:17:00+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Executive summary
This evening's work was a controlled router stabilization pass followed by cleanup and observability hardening.

The high-risk failures from the original edge sweep have been fixed and remain fixed on the latest full 156-prompt corpus:

- authority-boundary leaks: fixed
- ambiguous short followups being answered locally: fixed
- original-query provenance corruption: fixed
- signal precedence drift: reduced via centralized precedence and explicit winning-signal telemetry
- geopolitics over-routing risk: reduced via conceptual-vs-live separation
- URL/doc routing inconsistency: fixed for explicit URL/doc prompts
- semantic-interpreter "0/156" ambiguity: explained operationally, not by guesswork
- trace/harness stderr noise: fixed
- medication detector non-fired trace noise: fixed

Current measured state on the latest full sweep:

- prompts tested: `156`
- rule-consistent cases: `156/156`
- provenance preserved: `156/156`
- anomalies: `0`
- authority-boundary violations: `0`

Latest clean sweep report:

- `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T20-49-25+0200.md`

Note:

- the latest full 156-prompt sweep was run immediately before the final medication trace-noise cleanup
- that last patch was observability-only, and was validated with targeted medication and trace regressions rather than another full sweep

## Starting point
The initial failing sweep from 2026-03-15 showed three dangerous classes of failure:

1. non-local prompts routed to `LOCAL`
2. ambiguous prompts answered without clarification
3. rewritten queries corrupting original-query provenance

Those were addressed first before any tuning or expansion.

## What changed

### 1. Authority boundary stabilization
Live/current prompts that previously leaked into `LOCAL` now route non-locally.

Examples repaired:

- `What are the current tensions in the South China Sea?`
- `Is there currently a ceasefire in Gaza?`
- `Has the filing deadline for US taxes changed this year?`
- `what happening south china sea rn`

Effect:

- `LOCAL` no longer answers prompts that require `NEWS` or `EVIDENCE`
- the governor/router remains the sole routing owner
- execution remains policy-blind

### 2. Ambiguity and short-followup handling
Short unanchored prompts no longer default to local answers.

Examples repaired:

- `Tell me more about it.`
- `Is it safe?`
- `Explain it again.`
- `Which one is better?`
- `Can you continue?`

The behavior is now:

- resolve from context only when referent confidence is high
- otherwise route to `CLARIFY`

Two deterministic context-resolution cases were added:

- exact two-item comparison carryover
- single-subject explanation carryover

Domain-specific carryover remains in place for medical, travel, media reliability, and similar known-safe contexts.

### 3. Medical carryover and evidence gating
Medical prompts and followups remain evidence-gated.

Example repaired:

- `What does Lipitor do?` -> followup `And grapefruit?`

This no longer falls back to `LOCAL`.

### 4. Provenance preservation
Top-level query provenance is now structurally separated from execution rewrites.

Current pattern:

- `QUERY` / `original_query`: immutable literal user text
- `resolved_execution_query`: mutable execution-time rewrite

This was validated in both semantic and execution traces.

### 5. Explicit routing precedence and telemetry
Routing precedence was made explicit and centralized instead of relying on incidental `if/elif` order.

Signals now expose:

- temporal
- news
- conflict
- geopolitics
- Israel-region live escalation
- source/doc
- ambiguity followup
- medical context
- current product recommendation

Telemetry now includes:

- `WINNING_SIGNAL`
- `PRECEDENCE_VERSION`
- per-signal boolean exports in `execute_plan`

This reduces the chance of future silent precedence drift.

### 6. Geopolitics conceptual vs live split
Geopolitical entities alone no longer imply live/news escalation.

Desired and current behavior:

- `What is Hamas?` -> conceptual/local-eligible
- `Explain Hezbollah ideology.` -> conceptual/local-eligible
- `History of the Gaza conflict.` -> conceptual/local-eligible
- `What is the South China Sea dispute?` -> conceptual/local-eligible
- `Is there currently a ceasefire in Gaza?` -> non-local
- `Latest updates on Hezbollah activity.` -> non-local
- `What is happening in Lebanon right now?` -> non-local

Operational rule:

- geopolitics alone is insufficient
- geopolitics plus temporal/current/news/source cue escalates

### 7. URL/doc routing
Explicit URL/doc prompts now stay on the doc/evidence path even when phrased with temporal wording.

Example repaired:

- `Latest updates from https://example.com/report`

This now classifies and maps consistently through the doc/evidence route rather than being misread as generic news/current-fact.

### 8. Semantic interpreter investigation
The semantic interpreter did not become a routing decision-maker again, but its state is now explainable.

Important finding:

- the gate is not dead
- on the original corpus, many prompts are eligible for interpreter invocation
- in this environment, the local model backend was unavailable during live runs

Telemetry added:

- `SEMANTIC_INTERPRETER_GATE_REASON`
- `SEMANTIC_INTERPRETER_INVOCATION_ATTEMPTED`
- `SEMANTIC_INTERPRETER_RESULT_STATUS`
- `SEMANTIC_INTERPRETER_USE_REASON`

Current operational explanation for the full sweep:

- `1` eligible case reached a real backend failure -> `model_unavailable`
- subsequent eligible cases were suppressed by cached backend-unavailable state -> `backend_unavailable_cached`
- deterministic cases remained deterministic skips

This prevented repeated backend thrashing during the full run.

### 9. Harness and trace cleanup
Shared-state and stderr noise in `execute_plan` telemetry syncing were fixed.

Examples removed:

- `grep ... last_outcome.env: No such file or directory`
- temp-file replace noise from outcome syncing

This made trace-bearing tests materially more reliable.

### 10. Medication detector trace cleanup
The latest cleanup pass removed a remaining observability defect:

- non-fired medication detector traces were still carrying candidate-like fields

Current behavior when the medication detector does **not** fire:

- `candidate_medication` is blank
- `normalized_candidate` is blank
- `normalized_query` is blank
- `pattern_family` is blank

This keeps traces from implying medication handling when none actually occurred.

## Validation performed

### Full sweep
Latest full run:

- report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T20-49-25+0200.md`
- artifacts: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T20-49-25+0200_full_safe`

Headline results:

- `156/156` rule-consistent
- `156/156` provenance preserved
- `0` anomalies
- `0` authority-boundary violations
- semantic interpreter activation rate: `0/156`
- medication detector activation rate: `31/156`
- evidence planner activation rate: `3/156`
- normalization observed: `34/156`

Scope note:

- these full-sweep numbers predate the final medication trace-noise cleanup by one small patch
- the medication cleanup was then validated with targeted tests, without rerunning the full corpus to avoid unnecessary backend churn

Pipeline distribution:

- `CLARIFY`: `12`
- `EVIDENCE`: `66`
- `LOCAL`: `62`
- `NEWS`: `16`

The full sweep was run in a low-thrash configuration:

- all sweep workspaces shared one semantic-interpreter backend-state file
- once backend unavailability was detected, later eligible cases were cached out instead of repeatedly hitting the local model endpoint

### Targeted regression tests
Key tests run across the stabilization sequence included:

- `test_phase1_classifier_output.sh`
- `test_policy_engine_auto_routing.sh`
- `test_execute_plan_phase1_clarify.sh`
- `test_execute_plan_routing_signal_telemetry.sh`
- `test_router_current_conflict_news_routing.sh`
- `test_execute_plan_context_followup_carryover.sh`
- `test_execute_plan_media_followup_context.sh`
- `test_execute_plan_medication_detector_trace.sh`
- `test_medication_detector_broader_coverage.sh`
- `test_execute_plan_preserves_original_query_after_news_rewrite.sh`
- `test_execute_plan_semantic_interpreter_routing.sh`
- `test_execute_plan_semantic_interpreter_trace_and_fallback.sh`
- `test_execute_plan_preserves_semantic_interpreter_selection.sh`
- `test_semantic_interpreter_gate_telemetry.sh`
- `test_semantic_trace_preserves_literal_original_query.sh`

## Current assessment
Current router status:

- architecture: correct
- routing: stable on the edge corpus
- observability: materially improved
- policy ownership: intact
- authority boundaries: intact

This is no longer an emergency routing repair situation.

The system appears to have moved from:

- architectural stabilization

to:

- conservative tuning
- operational hardening
- regression maintenance

## What remains problematical
These are the remaining meaningful issues, ordered by importance.

### 1. Semantic interpreter backend availability
This is now an operational issue, not a hidden routing mystery.

What is known:

- the interpreter gate opens for eligible prompts
- the latest full sweep hit backend unavailability in live mode
- caching now prevents repeated hammering of the local model endpoint

What remains unresolved:

- whether the local semantic backend should be restored for routine use
- whether the interpreter should remain advisory-only and effectively optional

Recommended next step:

- diagnose local model availability outside the router sweep
- do not change routing authority based on this subsystem

### 2. Corpus limits
The current 156-prompt corpus is now clean, but finite.

Still worth expanding:

- harder pronoun-heavy followups
- longer mixed-intent prompts
- more URL/doc phrasing variants
- more conceptual geopolitics vs live-news border cases
- more adversarial context-carryover prompts

### 3. CI / regression gating
The sweep is now valuable enough to become a protected regression suite.

Recommended next step:

- add the 156-prompt sweep, or a fast representative subset, to CI for router changes

### 4. Mixed-intent depth
Mixed-intent handling is safer than before, but still coarse.

Example shape:

- conceptual explanation plus current recommendation

Current behavior:

- escalates non-locally as a whole when warranted

Possible future improvement:

- split execution or clarification instead of whole-prompt escalation

This is a quality optimization, not a correctness bug.

## Explicit non-problems
These issues were reviewed and do **not** currently look like urgent bugs:

- authority boundaries
- original-query provenance
- URL/doc routing for explicit URLs
- ambiguity leakage into local speculative answers
- conceptual geopolitics being forcibly escalated by entity presence alone

## Suggested review questions for ChatGPT

1. Does the current precedence and signal model look stable enough to freeze for a while?
2. Is there any remaining architecture risk in the current context-resolution rules for short followups?
3. Should the semantic interpreter remain operationally optional as long as it is non-authoritative and fully traced?
4. Is the current mixed-intent behavior acceptable, or should split execution become the next design target?
5. Are there any high-value corpus additions that would most likely catch the next real regression?

## Bottom line
The router/governor layer now appears stable, auditable, and compliant with the core architecture invariants on the current regression surface.

The main routing chapter is effectively stabilized.

What remains is not "routing is broken" work. It is:

- semantic backend operational clarity
- broader corpus hardening
- CI enforcement
- selective quality improvements


---

## LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T21-50-56+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T21-50-56+0200.md

# LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT
Timestamp: 2026-03-16T21:57:23+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Artifacts
- prompt corpus: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T21-50-56+0200_manifest_full/prompt_corpus.jsonl`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T21-50-56+0200_manifest_full/results.jsonl`
- case logs root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/edge_prompt_sweep/2026-03-16T21-50-56+0200_manifest_full/cases`

## Summary statistics
- prompts tested: 156
- rule-consistent cases: 156/156
- provenance preserved: 156/156
- semantic interpreter activation rate: 0/156 (0.0%)
- medication detector activation rate: 31/156 (19.9%)
- evidence planner activation rate: 3/156 (1.9%)
- normalization observed: 34/156 (21.8%)
- LOCAL_DIRECT used: 62/156

Pipeline distribution:
- CLARIFY: 12
- EVIDENCE: 66
- LOCAL: 62
- NEWS: 16

Response classification distribution:
- clarify: 12
- doc_result: 13
- evidence_answer: 24
- evidence_insufficiency: 29
- local_answer: 62
- news_result: 16

## Notable successes
- [medication_health] `What are the side effects of ibuprofen?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Does tadalafil interact with alcohol?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Is Lipitor safe with grapefruit?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `What is Tadalifil?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `What does amoxycillin do?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Can sildenafil interact with nitrates?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Side effects of metformin?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Is Panadol the same as acetaminophen?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Dose of Panadol?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [medication_health] `Can ibuprofen affect blood pressure?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false

## Potential routing anomalies
- No rule mismatches were detected in this sweep.

## Authority boundary violations
- None detected.

## Interesting edge cases
- [medication_health] `What are the side effects of ibuprofen?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What are the side effects of ibuprofen?`
- [medication_health] `Does tadalafil interact with alcohol?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Does tadalafil interact with alcohol?`
- [medication_health] `Is Lipitor safe with grapefruit?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is Lipitor safe with grapefruit?`
- [medication_health] `What is Tadalifil?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What is Tadalifil?`
- [medication_health] `What does amoxycillin do?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What does amoxycillin do?`
- [medication_health] `Can sildenafil interact with nitrates?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Can sildenafil interact with nitrates?`
- [medication_health] `Side effects of metformin?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Side effects of metformin?`
- [medication_health] `Is Panadol the same as acetaminophen?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is Panadol the same as acetaminophen?`

## Suggestions
- Keep this sweep in the regression toolbox and rerun it after major router/interpreter changes.

## Boundary confirmation
- governor/router remained the owner of routing decisions
- execution remained policy-blind; the sweep only observed existing behavior
- evidence/news/doc authority boundaries were preserved unless explicitly listed above
- original query provenance was checked against structured traces



---

## LOCAL_LUCY_ROUTE_MANIFEST_REPORT_2026-03-16T21-57-31+0200.md

Source: /home/mike/lucy/snapshots/opt-experimental-v5-dev/dev_notes/LOCAL_LUCY_ROUTE_MANIFEST_REPORT_2026-03-16T21-57-31+0200.md

# LOCAL_LUCY_ROUTE_MANIFEST_REPORT
Timestamp: 2026-03-16T21:57:31+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## What changed
A canonical immutable `route_manifest` is now emitted by the router/governor seam in `plan_to_pipeline.py` and consumed by `execute_plan.sh` as the sole routing authority.

The manifest now carries:

- `manifest_version`
- `precedence_version`
- `original_query`
- `resolved_execution_query`
- `selected_route`
- `allowed_routes`
- `forbidden_routes`
- `winning_signal`
- `clarify_required`
- `authority_basis`
- `signals`
- `context_resolution_used`
- `context_referent_confidence`

Execution no longer reconstructs route authority from scattered legacy fields. It validates the manifest, uses it for:

- route selection
- clarify gating
- signal telemetry
- resolved execution query
- authority-basis telemetry

If the manifest is missing or contradictory, execution now fails closed.

## Why
Before this change, the effective route emerged from a combination of:

- `route_decision`
- `execution_contract`
- shell-level fallback/default logic
- scattered signal exports

That was workable, but structurally weaker than a single explicit contract object.

The manifest migration turns routing into a first-class contract:

- deterministic
- explicit
- auditable
- harder to accidentally bypass

## Migration impact
Compatibility was preserved by deriving legacy execution/env telemetry from the manifest during migration rather than deleting legacy fields outright.

Notable impact:

- `execute_plan.sh` now refuses missing or malformed route manifests instead of silently defaulting
- `execution_contract.route` is now expected to match `route_manifest.selected_route`
- dry-run and outcome telemetry now expose manifest-backed fields such as:
  - `MANIFEST_VERSION`
  - `MANIFEST_SELECTED_ROUTE`
  - `MANIFEST_ALLOWED_ROUTES`
  - `MANIFEST_FORBIDDEN_ROUTES`
  - `MANIFEST_AUTHORITY_BASIS`
  - `MANIFEST_CONTEXT_RESOLUTION_USED`
  - `MANIFEST_CONTEXT_REFERENT_CONFIDENCE`

## Legacy-path status
Current status:

- legacy route/env fields still exist
- they are no longer authoritative in execution
- execution consumes the manifest and treats legacy disagreement as an error

So the migration is not yet a complete removal of legacy fields, but there is no longer a known execution path that may legitimately bypass the manifest.

## Validation
Targeted contract and regression tests passed, including:

- `test_router_contract_schema.sh`
- `test_plan_to_pipeline_mapping.sh`
- `test_runtime_governor_contract.sh`
- `test_execute_plan_routing_signal_telemetry.sh`
- `test_execute_plan_context_followup_carryover.sh`
- `test_execute_plan_phase1_clarify.sh`
- `test_execute_plan_governor_contract.sh`
- `test_execute_plan_local_response_contract_passthrough.sh`
- `test_execute_plan_route_manifest_enforcement.sh`
- `test_execute_plan_preserves_original_query_after_news_rewrite.sh`
- `test_execute_plan_preserves_semantic_interpreter_selection.sh`
- `test_router_current_conflict_news_routing.sh`

Full edge sweep rerun:

- prompts tested: `156`
- anomalies: `0`
- boundary violations: `0`
- report: `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T21-50-56+0200.md`

The full sweep was run in the same low-thrash semantic-backend mode used earlier:

- shared semantic backend-state file
- cached backend-unavailable handling to avoid repeated local-model hammering

## Residual risks
The main residual risks are now maintenance-oriented, not architectural breakage:

1. Some older fake `plan_to_pipeline.py` test fixtures outside the targeted regression set may still need explicit `route_manifest` fields if those tests are reactivated.
2. Legacy route fields still exist in mapper output and shell telemetry; they are now derived/validated against the manifest, but not yet deleted.
3. The semantic interpreter remains operationally optional because backend availability is still external to this routing contract work.
4. Parallel `execute_plan` tests can still create shared-state noise if run against the same root simultaneously; sequential execution remains safer for those tests.

## Bottom line
This migration achieved the intended architecture step:

- routing is now represented as a canonical manifest
- execution consumes that manifest as the route authority
- malformed or contradictory route state fails closed
- current stabilized routing behavior remained intact on the full edge corpus


---

## LOCAL_LUCY_CHATGPT_GROK_STATUS_REPORT_2026-03-16T22-03-05+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_CHATGPT_GROK_STATUS_REPORT_2026-03-16T22-03-05+0200.md

# LOCAL_LUCY_CHATGPT_GROK_STATUS_REPORT
Timestamp: 2026-03-16T22:03:05+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Purpose
This report summarizes the full Local Lucy router stabilization and contract-hardening work completed this evening, the measured results, and the remaining issues that appear real rather than hypothetical.

## Executive summary
Local Lucy's router is materially more stable than it was at the start of the evening.

The original dangerous failures were:

1. non-local prompts leaking into `LOCAL`
2. ambiguous short followups being answered locally instead of clarifying
3. original-query provenance being overwritten by execution rewrites

Those issues were fixed first. After that, the work moved into controlled hardening:

- explicit routing precedence
- conceptual-vs-live geopolitics separation
- narrow deterministic context resolution
- URL/doc routing consistency
- semantic-interpreter observability and backend-thrash control
- trace and harness cleanup
- medication detector trace cleanup
- canonical immutable route manifest between governor/router and execution

Current measured state on the latest full manifest-backed edge sweep:

- prompts tested: `156`
- rule-consistent cases: `156/156`
- provenance preserved: `156/156`
- anomalies: `0`
- authority-boundary violations: `0`

Latest full sweep report:

- `/home/mike/Desktop/LOCAL_LUCY_EDGE_PROMPT_SWEEP_REPORT_2026-03-16T21-50-56+0200.md`

## What was fixed

### 1. Authority-boundary leaks
Prompts that require current external knowledge no longer leak into `LOCAL`.

Examples repaired:

- `What are the current tensions in the South China Sea?`
- `Is there currently a ceasefire in Gaza?`
- `Has the filing deadline for US taxes changed this year?`
- `what happening south china sea rn`

Result:

- `LOCAL` no longer answers these non-local prompt families
- governor/router remains the sole owner of route authority
- execution remains policy-blind

### 2. Ambiguous short followups
Short followups no longer default to speculative local answers.

Examples repaired:

- `Tell me more about it.`
- `Is it safe?`
- `Explain it again.`
- `Which one is better?`
- `Can you continue?`

Current behavior:

- if context resolution is high-confidence, resolve deterministically
- otherwise, route to `CLARIFY`

### 3. Context-resolution balance
Context resolution was added carefully instead of broadly.

High-confidence cases currently supported:

- exact two-item comparison carryover
- single-subject explanation carryover
- existing domain-specific carryover such as medical followups

Example:

- `What does Lipitor do?` -> followup `And grapefruit?` stays evidence-gated instead of falling back to `LOCAL`

### 4. Provenance preservation
Top-level provenance is now structurally separated from execution rewrite logic.

Current contract:

- `original_query` / `QUERY`: immutable literal user text
- `resolved_execution_query`: rewriteable execution-facing text

This was tested in both ordinary execution paths and semantic traces.

### 5. Explicit routing precedence
Routing precedence is now explicit and centralized rather than relying on incidental code order.

Signals now include:

- temporal
- news
- conflict
- geopolitics
- Israel-region live escalation
- source/doc
- URL
- ambiguity followup
- medical context
- current product recommendation

Telemetry now records:

- `WINNING_SIGNAL`
- `PRECEDENCE_VERSION`
- per-signal booleans

### 6. Geopolitics conceptual vs live separation
Geopolitical entities alone do not force `NEWS` or `EVIDENCE`.

Current behavior:

- conceptual prompts like `What is Hamas?` and `Explain Hezbollah ideology.` remain local-eligible
- live prompts like `Is there currently a ceasefire in Gaza?` and `Latest updates on Hezbollah activity.` escalate non-locally

Operational rule:

- geopolitics alone is insufficient
- geopolitics plus temporal/current/news/source cue escalates

### 7. URL/doc routing
Explicit URL/doc prompts now stay on doc/evidence-style paths consistently, even when phrased with temporal wording.

### 8. Semantic interpreter observability and anti-thrash behavior
The semantic interpreter is no longer a mystery box in traces.

Important finding:

- the gate can open
- the latest full-run `0/156` activation rate is not explained by silent bypass alone
- the local model backend was unavailable during live invocation

Current behavior:

- first real backend failure is recorded explicitly
- later eligible cases are short-circuited as cached backend-unavailable
- repeated backend hammering is avoided

This reduced API/backend thrashing during sweeps.

### 9. Harness and trace cleanup
Noisy trace-sync warnings and temp-file errors in the test harness were cleaned up, which made regression tests more trustworthy.

### 10. Medication trace cleanup
When the medication detector does not fire, candidate-like trace fields are now blank rather than misleadingly populated.

## Route manifest migration
The largest architecture step after stabilization was introducing a canonical immutable `route_manifest`.

Manifest fields now include:

- `manifest_version`
- `precedence_version`
- `original_query`
- `resolved_execution_query`
- `selected_route`
- `allowed_routes`
- `forbidden_routes`
- `winning_signal`
- `clarify_required`
- `authority_basis`
- `signals`
- `context_resolution_used`
- `context_referent_confidence`

Current design:

- router/governor emits the manifest
- execution consumes it as the sole routing authority
- malformed or contradictory manifest state fails closed
- execution no longer legitimately bypasses manifest route authority

This materially improved contract clarity between the governor/router and execution.

Manifest report:

- `/home/mike/Desktop/LOCAL_LUCY_ROUTE_MANIFEST_REPORT_2026-03-16T21-57-31+0200.md`

## Current measured state

From the latest full manifest-backed edge sweep:

- prompts tested: `156`
- rule-consistent: `156/156`
- provenance preserved: `156/156`
- semantic interpreter activation rate: `0/156`
- medication detector activation rate: `31/156`
- evidence planner activation rate: `3/156`
- normalization observed: `34/156`
- `LOCAL_DIRECT` used: `62/156`

Pipeline distribution:

- `CLARIFY`: `12`
- `EVIDENCE`: `66`
- `LOCAL`: `62`
- `NEWS`: `16`

Response distribution:

- `clarify`: `12`
- `doc_result`: `13`
- `evidence_answer`: `24`
- `evidence_insufficiency`: `29`
- `local_answer`: `62`
- `news_result`: `16`

Most important result:

- no rule mismatches
- no authority-boundary violations
- no provenance failures

## What remains problematical
The remaining issues are no longer emergency routing failures, but there are still a few real items worth scrutiny.

### 1. Semantic interpreter availability is still operationally unresolved
The router now explains why the semantic interpreter did not contribute on the full sweep, but the subsystem itself was not restored to healthy live use.

Current status:

- eligible cases exist
- backend invocation can still return `model_unavailable`
- later cases then use `backend_unavailable_cached`

Interpretation:

- this is no longer a routing-governance bug
- it is still an operational/model-availability issue

### 2. Legacy compatibility fields still exist
The manifest is authoritative, but some legacy route/env fields still remain for compatibility.

Current status:

- execution validates them against the manifest
- they are no longer authoritative
- they have not been fully removed yet

This is not a correctness failure, but it is still maintenance surface.

### 3. Some dormant fixtures may need manifest updates
The actively used regression suite was updated, but older dormant fixtures outside that exercised set may still require explicit `route_manifest` data if reactivated later.

### 4. Parallel execute-plan tests are still less safe than sequential ones
Shared-state interactions are improved, but sequential execution is still safer for some trace-heavy tests.

### 5. The final medication-trace cleanup was validated by targeted tests, not another full sweep
This last patch was observability-only and did not intentionally change routing behavior, but strictly speaking the very latest full sweep predates that final trace-only cleanup.

## Validation performed
The work was validated incrementally to avoid backend thrash.

Representative test families covered:

- classifier output
- policy auto-routing
- clarify handling
- current-conflict news routing
- context followup carryover
- media followup context
- routing telemetry
- semantic interpreter gate telemetry
- semantic interpreter trace/fallback behavior
- original-query preservation
- route manifest schema and enforcement
- governor contract enforcement
- local response contract passthrough
- medication detector trace cleanup

Full edge sweep status:

- latest full sweep passed cleanly
- the sweep was run in low-thrash mode with cached semantic backend-unavailable handling

## Current overall assessment
The router is now in a fundamentally healthier state than it was at the start of the evening.

Before this work:

- architecture was mostly correct
- routing behavior was unstable

After this work:

- architecture is stronger
- route authority is explicit
- execution is more constrained
- routing behavior is stable on the current edge corpus

This is no longer an emergency stabilization situation.

## Questions worth asking in review
If reviewing this system externally, the most useful questions are now:

1. Is the semantic interpreter operationally acceptable as an optional/non-authoritative subsystem, or should backend availability be treated as a separate reliability project?
2. Should the remaining legacy route/env compatibility fields now be removed completely, or kept for one more migration window?
3. Are there any hidden code paths that could still synthesize route-like behavior outside the manifest contract?
4. Is the current context-resolution scope appropriately narrow, or should it expand carefully into more non-medical conversational cases?
5. Should the 156-prompt edge sweep become a required regression gate for future router changes?

## Bottom line
Local Lucy's router/governor layer appears stable and contract-driven on the current corpus.

The core safety invariants are holding:

- governor/router owns routing
- execution is policy-blind
- `LOCAL` does not answer non-local prompts
- `original_query` remains immutable
- route decisions are explicit, testable, and auditable

The main remaining concerns are operational and maintenance-oriented, not evidence of current routing breakage.


---

## LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-50-28+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-50-28+0200.md

# LOCAL_LUCY_ROUTER_REGRESSION_GATE_REPORT
Timestamp: 2026-03-17T17:51:09+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Gate summary
- profile: `fast`
- gate status: `FAIL`
- prompts tested: 13
- rule-consistent count: 11
- provenance preserved count: 13
- anomalies: 2
- authority-boundary violations: 0
- route mismatches: 0
- manifest failures: 2

## Artifacts
- prompt corpus: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-50-28+0200/prompt_corpus.jsonl`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-50-28+0200/results.jsonl`
- case logs root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-50-28+0200/cases`

## Summary statistics
- prompts tested: 13
- rule-consistent cases: 11/13
- provenance preserved: 13/13
- semantic interpreter activation rate: 0/13 (0.0%)
- medication detector activation rate: 2/13 (15.4%)
- evidence planner activation rate: 0/13 (0.0%)
- normalization observed: 5/13 (38.5%)
- LOCAL_DIRECT used: 1/13

Pipeline distribution:
- CLARIFY: 2
- EVIDENCE: 6
- LOCAL: 1
- NEWS: 4

Response classification distribution:
- clarify: 2
- doc_result: 1
- evidence_answer: 3
- evidence_insufficiency: 2
- local_answer: 1
- news_result: 4

## Notable successes
- [mixed_intent] `Tell me what RAM is and recommend a current laptop.` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [mixed_intent] `What is Reuters and show me today's Reuters headlines.` -> NEWS / news_result | semantic=false medication=false planner=false
- [context_followup] `Is there a travel advisory for Egypt right now?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What about Jordan?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What does Lipitor do?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [context_followup] `And grapefruit?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false

## Potential routing anomalies
- [ambiguous] `Tell me more about it.` expected=CLARIFY actual=CLARIFY response=clarify reason=dryrun_manifest_missing_block
- [ambiguous] `Is it safe?` expected=CLARIFY actual=CLARIFY response=clarify reason=dryrun_manifest_missing_block

## Authority boundary violations
- None detected.

## Interesting edge cases
- [context_followup] `Is there a travel advisory for Egypt right now?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is there a travel advisory for Egypt right now?`
- [context_followup] `What about Jordan?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is it safe now to travel to Jordan?`
- [context_followup] `What does Lipitor do?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What does Lipitor do?`
- [context_followup] `And grapefruit?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is lipitor safe with grapefruit?`

## Suggestions
- No urgent behavioral issues were discovered in this sweep; focus next on adding this corpus to a repeatable nightly validation pass.

## Boundary confirmation
- governor/router remained the owner of routing decisions
- execution remained policy-blind; the sweep only observed existing behavior
- evidence/news/doc authority boundaries were preserved unless explicitly listed above
- original query provenance was checked against structured traces



---

## LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-57-48+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T17-57-48+0200.md

# LOCAL_LUCY_ROUTER_REGRESSION_GATE_REPORT
Timestamp: 2026-03-17T17:58:30+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Gate summary
- profile: `fast`
- gate status: `PASS`
- prompts tested: 13
- rule-consistent count: 13
- provenance preserved count: 13
- anomalies: 0
- authority-boundary violations: 0
- route mismatches: 0
- manifest failures: 0

## Artifacts
- prompt corpus: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-57-48+0200/prompt_corpus.jsonl`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-57-48+0200/results.jsonl`
- case logs root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T17-57-48+0200/cases`

## Summary statistics
- prompts tested: 13
- rule-consistent cases: 13/13
- provenance preserved: 13/13
- semantic interpreter activation rate: 0/13 (0.0%)
- medication detector activation rate: 2/13 (15.4%)
- evidence planner activation rate: 0/13 (0.0%)
- normalization observed: 5/13 (38.5%)
- LOCAL_DIRECT used: 1/13

Pipeline distribution:
- CLARIFY: 2
- EVIDENCE: 6
- LOCAL: 1
- NEWS: 4

Response classification distribution:
- clarify: 2
- doc_result: 1
- evidence_answer: 3
- evidence_insufficiency: 2
- local_answer: 1
- news_result: 4

## Notable successes
- [mixed_intent] `Tell me what RAM is and recommend a current laptop.` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [mixed_intent] `What is Reuters and show me today's Reuters headlines.` -> NEWS / news_result | semantic=false medication=false planner=false
- [context_followup] `Is there a travel advisory for Egypt right now?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What about Jordan?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What does Lipitor do?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [context_followup] `And grapefruit?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false

## Potential routing anomalies
- No rule mismatches were detected in this sweep.

## Authority boundary violations
- None detected.

## Interesting edge cases
- [context_followup] `Is there a travel advisory for Egypt right now?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is there a travel advisory for Egypt right now?`
- [context_followup] `What about Jordan?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is it safe now to travel to Jordan?`
- [context_followup] `What does Lipitor do?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What does Lipitor do?`
- [context_followup] `And grapefruit?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is lipitor safe with grapefruit?`

## Suggestions
- Keep this sweep in the regression toolbox and rerun it after major router/interpreter changes.

## Boundary confirmation
- governor/router remained the owner of routing decisions
- execution remained policy-blind; the sweep only observed existing behavior
- evidence/news/doc authority boundaries were preserved unless explicitly listed above
- original query provenance was checked against structured traces



---

## LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-07-43+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-07-43+0200.md

# LOCAL_LUCY_ROUTER_REGRESSION_GATE_REPORT
Timestamp: 2026-03-17T18:08:24+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Gate summary
- profile: `fast`
- gate status: `PASS`
- prompts tested: 13
- rule-consistent count: 13
- provenance preserved count: 13
- anomalies: 0
- authority-boundary violations: 0
- route mismatches: 0
- manifest failures: 0

## Artifacts
- prompt corpus: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-07-43+0200/prompt_corpus.jsonl`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-07-43+0200/results.jsonl`
- case logs root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-07-43+0200/cases`

## Summary statistics
- prompts tested: 13
- rule-consistent cases: 13/13
- provenance preserved: 13/13
- semantic interpreter activation rate: 0/13 (0.0%)
- medication detector activation rate: 2/13 (15.4%)
- evidence planner activation rate: 0/13 (0.0%)
- normalization observed: 5/13 (38.5%)
- LOCAL_DIRECT used: 1/13

Pipeline distribution:
- CLARIFY: 2
- EVIDENCE: 6
- LOCAL: 1
- NEWS: 4

Response classification distribution:
- clarify: 2
- doc_result: 1
- evidence_answer: 3
- evidence_insufficiency: 2
- local_answer: 1
- news_result: 4

## Notable successes
- [mixed_intent] `Tell me what RAM is and recommend a current laptop.` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [mixed_intent] `What is Reuters and show me today's Reuters headlines.` -> NEWS / news_result | semantic=false medication=false planner=false
- [context_followup] `Is there a travel advisory for Egypt right now?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What about Jordan?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What does Lipitor do?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [context_followup] `And grapefruit?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false

## Potential routing anomalies
- No rule mismatches were detected in this sweep.

## Authority boundary violations
- None detected.

## Interesting edge cases
- [context_followup] `Is there a travel advisory for Egypt right now?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is there a travel advisory for Egypt right now?`
- [context_followup] `What about Jordan?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is it safe now to travel to Jordan?`
- [context_followup] `What does Lipitor do?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What does Lipitor do?`
- [context_followup] `And grapefruit?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is lipitor safe with grapefruit?`

## Suggestions
- Keep this sweep in the regression toolbox and rerun it after major router/interpreter changes.

## Boundary confirmation
- governor/router remained the owner of routing decisions
- execution remained policy-blind; the sweep only observed existing behavior
- evidence/news/doc authority boundaries were preserved unless explicitly listed above
- original query provenance was checked against structured traces



---

## LOCAL_LUCY_MANIFEST_MIGRATION_REPORT_2026-03-17T18-08-57+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_MANIFEST_MIGRATION_REPORT_2026-03-17T18-08-57+0200.md

# LOCAL_LUCY_MANIFEST_MIGRATION_REPORT
Timestamp: 2026-03-17T18:08:57+0200

## Scope

- Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`
- Task: reduce manifest migration debt and make the route decision manifest the only true routing authority
- Scope guard respected:
  - only `/home/mike/lucy/snapshots/opt-experimental-v5-dev` was edited
  - frozen/stable snapshots were not edited

## Outcome

- `route_manifest.selected_route` is now the only route authority consumed by the runtime governor.
- Mapper top-level compatibility aliases now derive from the manifest instead of independent policy route fields.
- `execute_plan.sh` now:
  - rejects top-level legacy alias drift when a mapper emits mismatched compatibility fields
  - re-derives exported compatibility aliases from `MANIFEST_SELECTED_ROUTE`
  - asserts persisted/exported aliases cannot drift from the manifest
- No route precedence, policy surface, or semantic-interpreter authority was expanded.

## Files Changed

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/runtime_governor.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/plan_to_pipeline.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_plan_to_pipeline_mapping.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_manifest_compat_aliases.sh`

## Validation

- `bash -n /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh` -> PASS
- `python3 -m py_compile /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/runtime_governor.py /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/plan_to_pipeline.py` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_plan_to_pipeline_mapping.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_router_contract_schema.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_route_manifest_enforcement.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_governor_contract.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_manifest_compat_aliases.sh` -> PASS
- `cd /home/mike/lucy/snapshots/opt-experimental-v5-dev && ./tools/tests/run_router_regression_gate_fast.sh` -> PASS

## Latest Gate Artifact

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-07-43+0200/summary.json`
- `/home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-07-43+0200.md`

## Remaining Debt

- Nested `route_decision.force_mode`, `route_mode`, and `policy_*route` fields still exist as diagnostic/policy-engine output and are not yet removed.
- `last_outcome.env`, dryrun output, and trace exports still publish legacy compatibility aliases for downstream consumers; they are now manifest-derived but still part of the compatibility surface.
- Some dormant fake-mapper tests outside the targeted regression set still model pre-manifest contracts and may need cleanup if those suites are reactivated.


---

## LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-20-46+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-20-46+0200.md

# LOCAL_LUCY_ROUTER_REGRESSION_GATE_REPORT
Timestamp: 2026-03-17T18:21:26+02:00
Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`

## Gate summary
- profile: `fast`
- gate status: `PASS`
- prompts tested: 13
- rule-consistent count: 13
- provenance preserved count: 13
- anomalies: 0
- authority-boundary violations: 0
- route mismatches: 0
- manifest failures: 0

## Artifacts
- prompt corpus: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-20-46+0200/prompt_corpus.jsonl`
- results jsonl: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-20-46+0200/results.jsonl`
- case logs root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-20-46+0200/cases`

## Summary statistics
- prompts tested: 13
- rule-consistent cases: 13/13
- provenance preserved: 13/13
- semantic interpreter activation rate: 0/13 (0.0%)
- medication detector activation rate: 2/13 (15.4%)
- evidence planner activation rate: 0/13 (0.0%)
- normalization observed: 5/13 (38.5%)
- LOCAL_DIRECT used: 1/13

Pipeline distribution:
- CLARIFY: 2
- EVIDENCE: 6
- LOCAL: 1
- NEWS: 4

Response classification distribution:
- clarify: 2
- doc_result: 1
- evidence_answer: 3
- evidence_insufficiency: 2
- local_answer: 1
- news_result: 4

## Notable successes
- [mixed_intent] `Tell me what RAM is and recommend a current laptop.` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [mixed_intent] `What is Reuters and show me today's Reuters headlines.` -> NEWS / news_result | semantic=false medication=false planner=false
- [context_followup] `Is there a travel advisory for Egypt right now?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What about Jordan?` -> EVIDENCE / evidence_answer | semantic=false medication=false planner=false
- [context_followup] `What does Lipitor do?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false
- [context_followup] `And grapefruit?` -> EVIDENCE / evidence_insufficiency | semantic=false medication=true planner=false

## Potential routing anomalies
- No rule mismatches were detected in this sweep.

## Authority boundary violations
- None detected.

## Interesting edge cases
- [context_followup] `Is there a travel advisory for Egypt right now?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is there a travel advisory for Egypt right now?`
- [context_followup] `What about Jordan?` -> pipeline=EVIDENCE output_mode=LIGHT_EVIDENCE resolved=`Is it safe now to travel to Jordan?`
- [context_followup] `What does Lipitor do?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`What does Lipitor do?`
- [context_followup] `And grapefruit?` -> pipeline=EVIDENCE output_mode=VALIDATED resolved=`Is lipitor safe with grapefruit?`

## Suggestions
- Keep this sweep in the regression toolbox and rerun it after major router/interpreter changes.

## Boundary confirmation
- governor/router remained the owner of routing decisions
- execution remained policy-blind; the sweep only observed existing behavior
- evidence/news/doc authority boundaries were preserved unless explicitly listed above
- original query provenance was checked against structured traces



---

## LOCAL_LUCY_SHARED_STATE_HARDENING_REPORT_2026-03-17T18-22-24+0200.md

Source: /home/mike/Desktop/LOCAL_LUCY_SHARED_STATE_HARDENING_REPORT_2026-03-17T18-22-24+0200.md

# LOCAL_LUCY_SHARED_STATE_HARDENING_REPORT
Timestamp: 2026-03-17T18:22:24+0200

## Scope

- Active root: `/home/mike/lucy/snapshots/opt-experimental-v5-dev`
- Task: harden Local Lucy shared-state behavior for parallel/overlapping execution
- Scope guard respected:
  - only `/home/mike/lucy/snapshots/opt-experimental-v5-dev` was edited
  - frozen/stable snapshots were not edited

## Findings

- `run_edge_prompt_sweep.py` is already workspace-isolated by `SessionContext.workspace_root` and is safe for sequential use because each session gets its own `state/`, `tmp/`, `cache/`, and `evidence/` tree.
- `execute_plan.sh` had the main overlap risk:
  - default root-global `state/last_outcome.env`
  - default root-global `state/last_route.env`
  - default root-global repetition-guard TSV files
  - trap-driven telemetry syncing with many per-field updates
- `semantic_interpreter.py` cached backend-unavailable state in one root-global JSON by default, which could smear outage suppression across unrelated overlapping runs sharing the same root.
- Sequential stability had been hiding two different classes of risk:
  - byte-level file corruption/interleaving during concurrent writes
  - logical state smear when multiple executions shared the same default root-global state namespace

## Hardening Added

- `execute_plan.sh`
  - added optional `LUCY_SHARED_STATE_NAMESPACE` support for namespaced state files under `state/namespaces/<ns>/`
  - added a fail-fast overlap guard for the default unnamespaced state path
  - added lock-based writes for route/outcome metadata and telemetry sync
  - redirected repetition-guard files to the active state namespace
- `semantic_interpreter.py`
  - added namespace-aware backend outage cache paths
  - added lock-based reads/writes and atomic replace for backend outage cache state

## Files Changed

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/semantic_interpreter.py`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_shared_state_overlap.sh`
- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_semantic_interpreter_backend_cache_scope.sh`

## Validation

- `bash -n /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/execute_plan.sh` -> PASS
- `python3 -m py_compile /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/router/core/semantic_interpreter.py` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_shared_state_overlap.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_semantic_interpreter_backend_cache_scope.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_governor_contract.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_manifest_compat_aliases.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_semantic_interpreter_gate_telemetry.sh` -> PASS
- `bash /home/mike/lucy/snapshots/opt-experimental-v5-dev/tools/tests/test_execute_plan_medication_detector_trace.sh` -> PASS
- `cd /home/mike/lucy/snapshots/opt-experimental-v5-dev && ./tools/tests/run_router_regression_gate_fast.sh` -> PASS

## Latest Gate Artifact

- `/home/mike/lucy/snapshots/opt-experimental-v5-dev/tmp/router_regression_gate/fast_2026-03-17T18-20-46+0200/summary.json`
- `/home/mike/Desktop/LOCAL_LUCY_ROUTER_REGRESSION_GATE_FAST_2026-03-17T18-20-46+0200.md`

## Residual Risks

- `last_outcome.env` and `last_route.env` still represent “last writer wins” state inside a single namespace; they are safe for sequential reuse, but same-namespace overlap can still produce logical state smear even though writes are now locked.
- repetition-guard TSV files are namespace-scoped now, but the repetition heuristic is still logically shared inside a namespace and can influence concurrent same-namespace runs.
- direct trace file paths like `LUCY_ROUTER_TRACE_FILE` and `LUCY_EXECUTION_CONTRACT_TRACE_FILE` are still caller-managed; reusing the same path across parallel runs will still smear traces.
- evidence/session artifacts under `evidence/<SESSION_ID>/...` still depend on session-id uniqueness rather than an added lock layer.


---

