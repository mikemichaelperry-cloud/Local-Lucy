# Phase 5 — Remove Confirmed Dead Routing Code

**Date:** 2026-07-20  
**Project:** Local Lucy V11 Standalone Migration  
**Scope:** `tools/router/` extraction and deletion  

## Context

The V11 standalone migration (`/home/mike/lucy-v11`) cloned V10 and established independent runtime paths. Phase 5 removes the legacy `tools/router/` directory. An audit showed that four of the five files under `tools/router/` are thin wrappers around `tools/router_py/core/`; only `extract_validated.py` contains unique parsing logic with no duplicate in `tools/router_py/`.

The approved approach is to keep thin compatibility wrappers under `tools/router_py/` so the 25+ affected shell tests keep working with minimal changes.

## Constraints

- Do not modify `/home/mike/lucy-v10`.
- Do not change application behaviour during structural cleanup.
- Make small, reversible commits; run relevant tests after each.
- Delete `tools/router/` only when no valid reference remains and all relevant tests pass.
- Confirm V10 source checksums remain unchanged after each commit.

## Goal

1. Migrate the unique `extract_validated.py` parser into `tools/router_py/core/`.
2. Provide thin CLI wrappers under `tools/router_py/` that expose the same interfaces as the legacy `tools/router/` scripts.
3. Update affected shell tests to invoke the new wrapper paths.
4. Clean up stale references to non-existent `tools/router/` files.
5. Update `SHA256SUMS` and documentation.
6. Delete `tools/router/`.

## New and migrated files

| Legacy path | New path | Role |
|---|---|---|
| `tools/router/extract_validated.py` | `tools/router_py/core/extract_validated.py` | Canonical `parse()` and `clean()` implementation. |
| — | `tools/router_py/extract_validated_cli.py` | Stdin → `parse()` → JSON CLI; preserves the old pipe invocation. |
| `tools/router/classify_intent.py` | `tools/router_py/classify_intent_cli.py` | Wraps `router_py.core.intent_classifier.classify_question`. |
| `tools/router/plan_to_pipeline.py` | `tools/router_py/plan_to_pipeline_cli.py` | Wraps `router_py.request_pipeline` / `execution_engine`; preserves `--plan-json` interface. |
| `tools/router/extract_medical_fact.py` | `tools/router_py/extract_medical_fact_cli.py` | Wraps `router_py.core.medical_fact_extractor.main`. |
| `tools/router/medical_query_heuristics.py` | `tools/router_py/medical_query_heuristics_cli.py` | Preserves `--is-human-medication-high-risk` and `--detect-human-medication` flags. |

### Wrapper requirements

Each wrapper:
- Lives directly under `tools/router_py/`.
- Is executable (`chmod +x`).
- Reads the same arguments / stdin as the legacy script.
- Emits the same JSON field set and exit codes.
- Imports canonical implementations from `tools/router_py/core/` using the existing `sys.path` pattern.

## Shell test updates

Update the 25+ shell tests listed in `/home/mike/lucy-v11-prep/task-5-audit-report.md` §6 to point at the new wrapper paths. Example replacements:

- `CLASSIFIER="${ROOT}/tools/router/classify_intent.py"` → `CLASSIFIER="${ROOT}/tools/router_py/classify_intent_cli.py"`
- `MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"` → `MAPPER="${ROOT}/tools/router_py/plan_to_pipeline_cli.py"`
- `python3 "${ROOT}/tools/router/extract_validated.py"` → `python3 "${ROOT}/tools/router_py/extract_validated_cli.py"`
- `python3 "${ROOT}/tools/router/medical_query_heuristics.py" --detect-human-medication …` → `python3 "${ROOT}/tools/router_py/medical_query_heuristics_cli.py" --detect-human-medication …`
- `python3 "${ROOT}/tools/router/extract_medical_fact.py"` → `python3 "${ROOT}/tools/router_py/extract_medical_fact_cli.py"`

No test assertions change.

## Stale reference cleanup

These references point to files that do not exist:

| Missing file | Referrer | Action |
|---|---|---|
| `tools/router/latency_profile.sh` | `tools/build_evidence_pack.sh` | Remove `LATPROF_LIB` lookup; keep the no-op fallback stub. |
| `tools/router/latency_profile.sh` | `tools/fetch_key.sh` | Remove `LATPROF_LIB` lookup; keep the no-op fallback stub. |
| `tools/router/execute_plan.sh` | `tools/trust/medical_tier3_corroboration_regression.sh` | Remove the `if [[ -x … ]]` branch; rely on the existing `lucy_chat.sh` fallback. |
| `tools/router_regression.sh` | `tools/health_battery.sh` | Remove the broken `router` step or redirect it to the Python-native test suite (`pytest tools/router_py/`). |

## Deletion criteria for `tools/router/`

`tools/router/` may be deleted only after:

1. `tools/router_py/core/extract_validated.py` and its CLI wrapper exist and pass `test_extract_validated_proposal_noise.sh`.
2. All four wrapper CLIs exist and pass their respective affected shell tests.
3. All stale references listed above are cleaned up.
4. `grep -R "tools/router/" tools/ docs/ dev_notes/ packaging/ --include="*.py" --include="*.sh" --include="*.md"` returns no runtime references (historical notes may remain if explicitly marked as historical).
5. `SHA256SUMS` is regenerated or updated to remove hashes for deleted files.
6. V10 checksums remain unchanged.

## Verification

Per-commit checks:

- Run the affected shell test(s) for the changed wrapper(s).
- Run `cd /home/mike/lucy-v10 && sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"` and confirm no unexpected changes.

Final checks before declaring Phase 5 complete:

- Run all 25+ affected shell tests.
- Run `pytest tools/router_py/` if available.
- Regenerate `SHA256SUMS`.
- Sweep `Architecture.md`, `AGENTS.md`, `docs/handoffs/`, and `dev_notes/` for stale `tools/router/` references and update them.

## Risks and mitigations

| Risk | Level | Mitigation |
|---|---|---|
| `extract_validated.py` parser logic is lost | High | Migrate it first into `tools/router_py/core/` and preserve its CLI before deleting `tools/router/`. |
| Shell tests break due to path or output mismatch | Medium | Update one test/wrapper at a time; run the test immediately after the change. |
| `health_battery.sh` fails on missing `router_regression.sh` | Low | Already broken; remove or redirect the step during cleanup. |
| Documentation becomes misleading | Low | Sweep docs after code deletion and update references to migrated paths. |

## Out of scope

- Refactoring the internals of `tools/router_py/core/` modules.
- Changing routing behaviour, model selection, or policy rules.
- Renaming `ui-v10` or other versioned directories.
- Phase 6–8 work (module cleanup, testing unification, packaging corrections).
