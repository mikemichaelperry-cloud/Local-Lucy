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
