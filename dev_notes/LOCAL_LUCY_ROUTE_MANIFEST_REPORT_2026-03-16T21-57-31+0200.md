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
