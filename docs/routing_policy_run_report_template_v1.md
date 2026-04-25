# Routing Policy Consolidation - Run Report Template v1

Timestamp:
Root:
Commit/Working state:
Operator:

## 1) Baseline
- Targeted baseline tests run:
- Baseline pass/fail:
- Baseline known gaps:

## 2) Policy engine checks
- `test_policy_engine_auto_routing.sh`:
- `test_policy_cross_surface_consistency.sh`:
- Confidence threshold used (`POLICY_CONFIDENCE_THRESHOLD`):

## 3) Required regression checks
- router_regression:
- test_voice_online_heuristic_routing:
- test_voice_evidence_sources_preserved:
- identity deterministic responses:
- travel advisory fallback:
- manifest integrity checks:
- launcher boundary validation:

## 4) Override telemetry sample
For each sampled prompt:
- prompt:
- policy_recommended_route:
- policy_actual_route:
- operator_override:
- reason_codes:
- confidence:

## 5) Cross-surface consistency sample
Prompt set:
- prompt 1 -> CLI/voice/conversation route
- prompt 2 -> CLI/voice/conversation route
- prompt 3 -> CLI/voice/conversation route

## 6) Regression summary
- total checks:
- failed checks:
- warnings:
- overall:

## 7) Open issues
- 

## 8) Next actions
1.
2.
3.
