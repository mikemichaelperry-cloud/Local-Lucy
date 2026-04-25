# Session Handover: v6 Authority Freeze and Evidence-Mode Discipline

Date: 2026-03-27
Snapshot root: `/home/mike/lucy/snapshots/opt-experimental-v6-dev`

## Scope completed

Two narrow hardening passes were completed in the active v6 dev snapshot:

1. Architectural authority freeze
2. Evidence-mode discipline cleanup

No broad refactor or unrelated cleanup was done.

## Authority freeze status

The active v6 authority chain is now explicit and pinned to the snapshot by default:

- Launcher: `tools/start_local_lucy_opt_experimental_v6_dev.sh`
- HMI bridge: `/home/mike/lucy/ui/app/services/runtime_bridge.py`
- Runtime request: `tools/runtime_request.py`
- Backend entrypoint: `lucy_chat.sh`
- Router execution: `tools/router/execute_plan.sh`
- Manifest source: `tools/router/core/route_manifest.py`

Authority behavior:

- Snapshot-local authority is the default.
- Ambient `LUCY_ROOT` no longer silently pulls execution outside the active snapshot on the hardened runtime path.
- Non-default authority root selection requires explicit `LUCY_RUNTIME_AUTHORITY_ROOT`.
- `runtime_bridge.py` is explicitly classified as a permitted global control-plane exception, not as a runtime authority root.

Direct backend entrypoints hardened:

- `lucy_chat.sh`
- `tools/router/execute_plan.sh`
- `tools/local_answer.sh`
- `tools/router/plan_to_pipeline.py`

Authority inspection utility added:

- `tools/diag/print_runtime_authority_chain.py`

Operator check:

```bash
python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/diag/print_runtime_authority_chain.py
```

## Evidence-mode discipline status

Manifest authority remains upstream and intact:

- `MANIFEST_EVIDENCE_MODE` and `MANIFEST_EVIDENCE_MODE_REASON` remain the single source of truth once selected.
- Execution does not reinterpret or override the manifest-selected evidence mode.

Selection behavior now:

- `LIGHT` is the default for ordinary evidence-backed `NEWS` and `EVIDENCE` answers.
- `FULL` is reserved for:
  - explicit source/citation/source-comparison requests
  - URL/doc-source prompts
  - medical high-risk prompts
  - live geopolitics
  - live conflict prompts
- Bare `conflict` without live/news context no longer escalates to `FULL`.

Canonical evidence-mode reasons now used upstream:

- `default_light`
- `explicit_source_request`
- `policy_medical_high_risk`
- `policy_geopolitics_high_risk`
- `policy_conflict_live`
- `not_evidence_route`

Operator legibility added:

- `/why` now shows:
  - evidence mode
  - evidence mode reason
  - evidence mode selection class
- `runtime_request.py` now returns additive telemetry fields:
  - `evidence_mode_reason`
  - `evidence_mode_selection`

Selection classes exposed to operators:

- `default-light`
- `explicit-user-triggered`
- `policy-triggered`
- `not_applicable`

## Main files changed in this session

Authority hardening:

- `tools/start_local_lucy_opt_experimental_v6_dev.sh`
- `tools/runtime_request.py`
- `tools/runtime_voice.py`
- `lucy_chat.sh`
- `tools/router/execute_plan.sh`
- `tools/local_answer.sh`
- `tools/router/plan_to_pipeline.py`
- `tools/diag/print_runtime_authority_chain.py`
- `tools/launcher/README.md`
- `/home/mike/lucy/ui/app/services/runtime_bridge.py`

Evidence-mode discipline:

- `tools/router/core/route_manifest.py`
- `tools/router/execute_plan.sh`
- `tools/start_local_lucy_opt_experimental_v6_dev.sh`
- `tools/runtime_request.py`

Focused tests added or updated:

- `tools/tests/test_router_evidence_mode_selection.sh`
- `tools/tests/test_execute_plan_routing_signal_telemetry.sh`
- `tools/tests/test_launcher_why_augmented_truth_reflection.sh`
- `tools/tests/test_runtime_request_augmented_truth_metadata.sh`
- `tools/tests/test_runtime_request_schema_additive_compat.sh`
- `tools/tests/test_execute_plan_preserves_semantic_interpreter_selection.sh`
- `tools/tests/test_execute_plan_offline_preserves_manifest_evidence_mode.sh`
- Authority tests from earlier in the session, including:
  - `test_runtime_request_authority_resolution.sh`
  - `test_runtime_authority_chain_inspection.sh`
  - `test_manifest_authority_import.sh`
  - `test_launcher_authority_root_pin.sh`
  - `test_lucy_chat_authority_root_pin.sh`
  - `test_execute_plan_authority_root_pin.sh`

Snapshot integrity files refreshed:

- `SHA256SUMS`
- `SHA256SUMS.clean`

## Validation completed

Compile and syntax checks:

- `python3 -m py_compile` passed for touched Python files in the evidence-mode pass and authority utilities.
- `bash -n` passed for touched shell entrypoints and targeted shell tests.

Targeted authority checks passed:

- `test_runtime_request_authority_resolution`
- `test_runtime_authority_chain_inspection`
- `test_manifest_authority_import`
- `test_launcher_authority_root_pin`
- `test_lucy_chat_authority_root_pin`
- `test_execute_plan_authority_root_pin`

Targeted evidence-mode checks passed:

- `test_router_evidence_mode_selection`
- `test_execute_plan_routing_signal_telemetry`
- `test_launcher_why_augmented_truth_reflection`
- `test_runtime_request_augmented_truth_metadata`
- `test_runtime_request_schema_additive_compat`
- `test_execute_plan_offline_preserves_manifest_evidence_mode`
- `test_execute_plan_preserves_semantic_interpreter_selection`

Snapshot manifest refresh:

- `./tools/sha_manifest.sh regen`

## Manual verification commands

Authority:

```bash
python3 /home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/diag/print_runtime_authority_chain.py
```

Launcher `/why`:

```bash
/home/mike/lucy/snapshots/opt-experimental-v6-dev/tools/start_local_lucy_opt_experimental_v6_dev.sh
```

Suggested prompts:

- LIGHT path: `What are the latest space headlines?`
- FULL path: `Compare the sources and cite them for the latest space headlines.`
- Then run: `/why`

## Remaining risks

- Some subordinate helper tools outside the direct entrypoint chain still accept caller-provided `LUCY_ROOT` if invoked ad hoc. On the hardened path they inherit pinned authority from their parent entrypoints.
- `runtime_bridge.py` remains intentionally outside the snapshot and is still a cross-tree dependency, though it is now explicitly classified and checked.
- Telemetry display class for evidence mode depends on canonical `MANIFEST_EVIDENCE_MODE_REASON`. Legacy or handcrafted non-canonical reasons will display as generic manifest-selected metadata rather than one of the disciplined labels.

## Recommended next step if work continues

If another narrow pass is needed, the most natural next target is sealing any remaining ad hoc helper-tool `LUCY_ROOT` seams that can still be reached outside the launcher/request path, without changing routing or governor semantics.
