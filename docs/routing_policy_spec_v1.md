# Routing Policy Specification v1

## Scope
This specification defines the centralized routing policy for Local Lucy stage: Routing Policy Consolidation.

## Canonical rule
- `auto` is the canonical routing behavior.
- All routing decisions are produced by a single policy engine: `tools/router/policy_engine.py`.
- Surfaces (CLI, conversation, voice) may change UX behavior only, not route policy.

## Policy inputs
- `intent`
- `category`
- `needs_web`
- `needs_citations`
- `output_mode`
- `question` (normalized)
- `route_control_mode` (`AUTO`, `FORCED_ONLINE`, `FORCED_OFFLINE`)
- `route_prefix` (`local`, `news`, `evidence`, or empty)
- `surface`
- `POLICY_CONFIDENCE_THRESHOLD` (default `0.60`)

## Derived policy variables
- `freshness_requirement`: `low|medium|high`
- `risk_level`: `low|high`
- `source_criticality`: `low|high`
- `policy_confidence`: float
- `policy_confidence_threshold`: float

## Route outputs
Policy engine emits:
- `route`: `local|news|evidence`
- `policy_recommended_route`
- `base_recommended_route`
- `offline_action`: `allow|requires_evidence|validated_insufficient`
- `operator_override`
- `reason_codes[]`

Mapper converts route to pipeline:
- `local -> LOCAL`
- `news -> NEWS`
- `evidence -> EVIDENCE`

## Mandatory rules
- If `policy_confidence < POLICY_CONFIDENCE_THRESHOLD` and candidate route is local, escalate to evidence.
- High-risk, freshness-sensitive, or source-critical prompts must not return unsupported local answers.
- `FORCED_OFFLINE` keeps offline behavior but returns deterministic guidance for evidence-required prompts.
- `FORCED_ONLINE` is an operator override; policy recommended route is still logged.
- Query prefixes (`local:`, `news:`, `evidence:`) are treated as explicit operator overrides.

## Surface contract
- CLI: consumes policy output.
- Conversation: may alter tone/cadence only.
- Voice: may normalize spoken commands and manage PTT only.
- None of the above may alter policy routing criteria.

## Telemetry contract
`execute_plan.sh` records policy metadata into `state/last_outcome.env`:
- `POLICY_RECOMMENDED_ROUTE`
- `POLICY_ACTUAL_ROUTE`
- `POLICY_CONFIDENCE`
- `POLICY_CONFIDENCE_THRESHOLD`
- `POLICY_FRESHNESS_REQUIREMENT`
- `POLICY_RISK_LEVEL`
- `POLICY_SOURCE_CRITICALITY`
- `POLICY_OPERATOR_OVERRIDE`
- `POLICY_REASON_CODES`

## Non-goals preserved
This stage does not change:
- model configuration
- STT/TTS pipeline
- launcher boundaries
- manifest integrity flow
- identity deterministic responses
- travel advisory risk-first fallback
- voice auto-evidence escalation
