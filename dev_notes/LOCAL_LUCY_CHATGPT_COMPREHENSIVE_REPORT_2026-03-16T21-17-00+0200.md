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
