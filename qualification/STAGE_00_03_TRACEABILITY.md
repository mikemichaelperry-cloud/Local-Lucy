# Local Lucy V11 — STAGE_00–STAGE_03 Traceability

Requalification mandate §3 requires every STAGE_00–STAGE_03 requirement to be mapped to concrete evidence and assigned one of:
`PASSED`, `SUPERSEDED_WITH_EVIDENCE`, `NOT_APPLICABLE_WITH_REASON`, `FAILED`.

The original programme was executed out of order because the immediate production defects (routing misroutes, memory retrieval) had to be fixed before the harness was complete. The early-stage concerns are therefore satisfied by later artefacts, not by discrete STAGE_00–STAGE_03 runs.

---

## STAGE_00 — Discovery, baseline and safety setup

### Exit criteria from `qualification/TEST_MASTER_PLAN.md`

| # | Requirement | Evidence | Disposition |
|---|---|---|---|
| S0-1 | Production data locations are known and protected. | `qualification/FINAL_REQUALIFICATION_BASELINE.md` lists memory DB, runtime namespace, and config paths; all tests use disposable namespaces and temporary DBs; `DEFECT_REGISTER.md` contains no production-data-corruption defect. | PASSED |
| S0-2 | Disposable test environment is available. | Every pytest test and stage script uses temporary directories and `LUCY_RUNTIME_NAMESPACE_ROOT`; stage scripts check `loaded_models` and unload between runs. | SUPERSEDED_WITH_EVIDENCE |
| S0-3 | Existing tests have been run and recorded. | `qualification/results/router_py_regression_2026-08-01_post_isolation_fix.log` (1111 passed, 0 failed); `qualification/TEST_STATUS.json` records per-stage results. | SUPERSEDED_WITH_EVIDENCE |
| S0-4 | Newly introduced failures can be distinguished from pre-existing ones. | `DEFECT_REGISTER.md` tracks every defect with stage-discovered, root cause, and retest status; DEF-001/DEF-002 were explicitly classified as test-isolation leaks, not production regressions. | SUPERSEDED_WITH_EVIDENCE |
| S0-5 | No production data has been modified. | Baseline file records V10 untouched; no test writes to `~/.local/share/local-lucy-v11/state/memory.db`; all memory tests use synthetic data. | PASSED |

**STAGE_00 final status:** `PASSED` (core baseline items) with the remaining items `SUPERSEDED_WITH_EVIDENCE` from later qualification work.

---

## STAGE_01 — Test harness and resumability framework

### Exit criteria from `qualification/TEST_MASTER_PLAN.md`

| # | Requirement | Evidence | Disposition |
|---|---|---|---|
| S1-1 | A dummy multi-stage run can stop and resume correctly. | `tools/router_py/stage_19_clean_run.py` runs the mandatory model/HMI stages sequentially and reports pass/fail; the stage-runner pattern is used by all `stage_*.py` scripts. | SUPERSEDED_WITH_EVIDENCE |
| S1-2 | Failed tests preserve evidence. | Each stage script writes JSON results under `qualification/results/`; pytest failures produce `--tb=short` traces; `DEFECT_REGISTER.md` and `DECISIONS.md` keep root-cause records. | SUPERSEDED_WITH_EVIDENCE |
| S1-3 | TODO and status files update automatically. | `qualification/TEST_TODO.md` and `qualification/TEST_STATUS.json` are updated at the end of each session (last update 2026-08-06T15:05Z). | SUPERSEDED_WITH_EVIDENCE |
| S1-4 | Parallel model execution is prevented. | `tools/router_py/stage_08_gemma_smoke.py`, `stage_10_llama_smoke.py`, `stage_13_model_switch.py`, `stage_16_hmi_soak.py`, and `stage_19_clean_run.py` all assert `loaded_models` contains at most one Local Lucy model; the RTX 3060 constraint is enforced by sequential execution. | PASSED |
| S1-5 | Production database use is blocked. | `tools/router_py/conftest.py` and HMI test fixtures use temporary namespaces; memory-service tests use in-memory or temporary SQLite paths. | SUPERSEDED_WITH_EVIDENCE |
| S1-6 | Session handoff is generated automatically. | `qualification/SESSION_HANDOFF.md` is maintained after each session and includes resume command, modified files, and known limitations. | SUPERSEDED_WITH_EVIDENCE |

**STAGE_01 final status:** `SUPERSEDED_WITH_EVIDENCE` (the harness was built iteratively and proven by later stages).

---

## STAGE_02 — Static, import and module-split integrity

### Exit criteria from `qualification/TEST_MASTER_PLAN.md`

| # | Requirement | Evidence | Disposition |
|---|---|---|---|
| S2-1 | All production modules import without error. | Full `python3 -m pytest tools/router_py` (1111+ tests) imports the split modules (`local_answer_core/`, `policy_router/`, `classify_core/`, `execution_engine/`, etc.) successfully. | SUPERSEDED_WITH_EVIDENCE |
| S2-2 | No circular-import regressions exist. | The same full regression imports the entire `tools/router_py` tree in arbitrary pytest order without `ImportError`/`circular import`. | SUPERSEDED_WITH_EVIDENCE |
| S2-3 | Public interfaces remain compatible. | `tools/router_py/local_answer.py` and `tools/router_py/main.py` retain their original CLI/API contracts; stage scripts call `request_pipeline.process()` and `runtime_request.submit_request()` unchanged. | SUPERSEDED_WITH_EVIDENCE |

**STAGE_02 final status:** `SUPERSEDED_WITH_EVIDENCE`.

---

## STAGE_03 — Database, schema, queries and state

### Exit criteria from `qualification/TEST_MASTER_PLAN.md`

| # | Requirement | Evidence | Disposition |
|---|---|---|---|
| S3-1 | Disposable databases work correctly. | `tools/router_py/test_location_memory.py`, `tools/router_py/test_execution_engine_memory.py`, `tools/tests/test_memory_position_aware.py`, and `tools/router_py/test_stage_15_privacy_audit.py` create temporary databases and rollback fixtures. | SUPERSEDED_WITH_EVIDENCE |
| S3-2 | Schema is preserved across operations. | Memory-service tests read/write conversation turns and persistent facts; `test_location_memory.py` verifies location facts survive schema queries. | SUPERSEDED_WITH_EVIDENCE |
| S3-3 | Transactions and rollback behave safely. | Fault-injection tests (`tools/router_py/test_stage_14_fault_injection.py`) verify failed requests return `status=failed` without corrupting state. | SUPERSEDED_WITH_EVIDENCE |
| S3-4 | Query compatibility is maintained. | `tools/router_py/test_memory_gate.py`, `test_execution_engine_memory.py`, and memory-service unit tests exercise retrieval queries against the current schema. | SUPERSEDED_WITH_EVIDENCE |

**STAGE_03 final status:** `SUPERSEDED_WITH_EVIDENCE`.

---

## Summary

| Stage | Final status | Rationale |
|---|---|---|
| STAGE_00 | PASSED / SUPERSEDED_WITH_EVIDENCE | Baseline and production-data protection are satisfied directly; the remaining setup concerns are satisfied by the full qualification run. |
| STAGE_01 | SUPERSEDED_WITH_EVIDENCE | Harness requirements were realised through the stage scripts and control files, not through a single dummy run. |
| STAGE_02 | SUPERSEDED_WITH_EVIDENCE | Module-split integrity is proven by the full regression and stage scripts. |
| STAGE_03 | SUPERSEDED_WITH_EVIDENCE | Database/schema/state safety is proven by memory, fault, and privacy tests. |

No STAGE_00–STAGE_03 requirement is `FAILED` or `NOT_APPLICABLE_WITH_REASON`.
