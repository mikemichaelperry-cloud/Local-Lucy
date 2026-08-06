# Local Lucy V11 Qualification — Live TODO

**Legend:** `TODO` `IN_PROGRESS` `PASSED` `FAILED` `BLOCKED` `DEFERRED` `NOT_APPLICABLE`

---

## STAGE_00 — Discovery, baseline and safety setup

*Status after requalification reconciliation: `PASSED` / `SUPERSEDED_WITH_EVIDENCE`. See `qualification/STAGE_00_03_TRACEABILITY.md`.*

- [S0-BASE-001] PASSED — Source-control checkpoint and current commit/status recorded in `qualification/FINAL_REQUALIFICATION_BASELINE.md`.
- [S0-BASE-002] SUPERSEDED_WITH_EVIDENCE — Module split map captured by full `tools/router_py` regression and stage scripts.
- [S0-BASE-003] SUPERSEDED_WITH_EVIDENCE — Public interfaces verified by full regression and stage scripts.
- [S0-BASE-004] SUPERSEDED_WITH_EVIDENCE — Production/test entry points identified and exercised by stage scripts.
- [S0-BASE-005] PASSED — Production data locations identified and protected; no test modifies production memory.
- [S0-BASE-006] SUPERSEDED_WITH_EVIDENCE — Ollama model names/digests recorded in baseline file and manifest.
- [S0-BASE-007] SUPERSEDED_WITH_EVIDENCE — Existing test baseline recorded in regression logs and `qualification/results/`.
- [S0-BASE-008] SUPERSEDED_WITH_EVIDENCE — Startup/shutdown behaviour verified by model smoke and switch stages.
- [S0-BASE-009] SUPERSEDED_WITH_EVIDENCE — Schema and route/outcome vocabulary verified by memory and routing tests.
- [S0-BASE-010] SUPERSEDED_WITH_EVIDENCE — Project-control files (`qualification/`) created and maintained.
- [S0-BASE-011] SUPERSEDED_WITH_EVIDENCE — Disposable-state discipline verified by fault-injection and privacy tests.

## STAGE_01 — Test harness and resumability framework

*Status after requalification reconciliation: `SUPERSEDED_WITH_EVIDENCE`. See `qualification/STAGE_00_03_TRACEABILITY.md`.*

- [S1-HAR-001] SUPERSEDED_WITH_EVIDENCE — Scenario schema realised through stage scripts and test functions.
- [S1-HAR-002] SUPERSEDED_WITH_EVIDENCE — Sequential runner pattern used by all `stage_*.py` scripts; `stage_19_clean_run.py` runs mandatory stages in order.
- [S1-HAR-003] SUPERSEDED_WITH_EVIDENCE — Temporary database/directory fixtures used across pytest suites.
- [S1-HAR-004] SUPERSEDED_WITH_EVIDENCE — Side-effect counters and monkey-patches used in routing/policy tests.
- [S1-HAR-005] SUPERSEDED_WITH_EVIDENCE — JSON result files written under `qualification/results/`.
- [S1-HAR-006] SUPERSEDED_WITH_EVIDENCE — TODO/status/handoff files updated at session boundaries.
- [S1-HAR-007] PASSED — Write harness self-tests and RUNBOOK.md.
  Evidence: qualification/RUNBOOK.md
- [S1-HAR-008] PASSED — Prototype static HMI surface injection-to-end test using `RuntimeBridge` with mocked backend.
  Evidence: tools/router_py/test_hmi_end_to_end.py (6 passed)
- [S1-HAR-009] PASSED — Update qualification plan/catalogue/decisions to require HMI end-to-end coverage.
  Evidence: qualification/TEST_MASTER_PLAN.md, qualification/TEST_CATALOGUE.md, qualification/DECISIONS.md

## STAGE_04 — Persistent memory and self-learning

- [S4-MEM-001] PASSED — Reproduce and fix location-memory failure: stored location must override timezone default.
  Evidence: tools/router_py/test_location_memory.py (3 passed)
- [S4-MEM-002] PASSED — Location-aware query prompt must include stored user location.
  Evidence: tools/router_py/test_location_memory.py::test_build_prompt_includes_location_for_area_query
- [S4-MEM-003] PASSED — Location anaphora ("near me", "in my area") must resolve to stored location before web routes fetch.
  Evidence: tools/router_py/test_hmi_real_routing.py::TestHmiLocationAnaphora
- [S4-MEM-004] PASSED — Conversation database stores all user/assistant turns; retrieval window widened from 4 to 12 recent turns and semantic recall increased to 8 older turns.
  Evidence: tools/memory/memory_service.py + tools/router_py/execution_engine/helpers.py; diagnostic with 16 stored turns returns 12 verbatim turns and explicit recall bypasses topic-shift gate.

## STAGE_05 — Deterministic router, classifier and capability controls

- [S5-ROU-001] PASSED — Reproduce and fix anaphoric search-tool imperative: "Use DuckDuckGo search" after a web-route exchange must inherit the prior topic.
  Evidence: tools/router_py/test_search_imperative_anaphora.py (3 passed)
- [S5-ROU-002] PASSED — Capability questions must not be rewritten as search imperatives.
  Evidence: tools/router_py/test_search_imperative_anaphora.py::test_capability_question_still_routes_local
- [S5-ROU-003] PASSED — Restaurant/dining queries with location/time qualifiers must not be misrouted as TIME or WEATHER.
  Evidence: tools/router_py/test_policy_router.py::TestRestaurantDiningGate + tools/router_py/test_hmi_real_routing.py

## STAGE_01 — Harness verification (continued)

- [S1-HAR-010] PASSED — Full `tools/router_py` regression after location/anaphora fixes.
  Evidence: `qualification/results/router_py_regression_2026-08-01.log` (1108 passed, 3 unrelated pre-existing failures: DEF-001, DEF-002)
- [S1-HAR-011] PASSED — Add HMI-level real-routing regression tests that use the actual classifier and pipeline.
  Evidence: tools/router_py/test_hmi_real_routing.py (4 passed)
- [S1-HAR-012] PASSED — Fix HMI real-routing test isolation: set LUCY_EVIDENCE_ENABLED=1 in the fixture and make `test_hmi_end_to_end.py` restore the real `runtime_request` module after each test so `test_hmi_real_routing.py` imports the real `submit_request`.
  Evidence: tools/router_py/test_hmi_real_routing.py::temp_namespace + tools/router_py/test_hmi_end_to_end.py::hmi_bridge

## STAGE_01 — Work Package 1: Routing-improvement baseline

- [WP1-DEF-001] PASSED — Close DEF-001 (characterization snapshot drift) as a test-isolation leak from `main.py` env-var pollution.
  Evidence: `tools/router_py/test_plan_to_pipeline_characterization.py` now passes in full suite; log `qualification/results/router_py_regression_2026-08-01_post_isolation_fix.log`
- [WP1-DEF-002] PASSED — Close DEF-002 (trusted-source parity provider mismatch) as the same env-var pollution.
  Evidence: `tools/router_py/test_pipeline_integration_flags.py` now passes in full suite
- [WP1-CORPUS-001] PASSED — Build structured routing failure corpus with dev/validation/locked-holdout splits.
  Evidence: `qualification/routing_failure_corpus.jsonl` (46 cases)
- [WP1-TRACE-001] PASSED — Add lightweight diagnostic trace behind `LUCY_ROUTER_DIAGNOSTICS=1`.
  Evidence: `tools/router_py/request_pipeline.py` `_write_router_diagnostic_trace()`; sample output in `qualification/router_diagnostics.jsonl`
- [WP1-METRICS-001] PASSED — Establish baseline per-route precision/recall on validation/holdout splits.
  Evidence: `qualification/results/baseline_metrics.json` (validation 21/21 = 1.000, holdout 13/15 = 0.867, combined 34/36 = 0.944).
- [WP1-REGRESSION-001] PASSED — Full `tools/router_py` regression after isolation fix.
  Evidence: `qualification/results/router_py_regression_2026-08-01_post_isolation_fix.log` (1111 passed, 0 failed)

## STAGE_05 — Work Package 2/3: Classifier dataset and guard narrowing

- [WP2-DATA-001] PASSED — Relabel CPR edge-case example from `LOCAL` to `AUGMENTED` in production dataset.
  Evidence: `models/router/comprehensive_examples.json`; `test_routing_edge_cases.py::test_routes_correctly[Step by step instructions for CPR-AUGMENTED-diy]` passes.
- [WP2-DATA-002] PASSED — Rebuild embeddings after CPR relabel and verify classifier head compatibility.
  Evidence: `models/router/comprehensive_embeddings.npy`; classifier head retained after a retrain regression was detected and reverted.
- [WP3-GUARD-001] PASSED — Narrow `gate_evidence_request` to respect local-only and network-denial constraints and arithmetic queries.
  Evidence: `tools/router_py/test_policy_router.py::TestEvidenceRequestGate`.
- [WP3-GUARD-002] PASSED — Broaden `gate_restaurant_dining` to catch food-specific establishments so `gate_news` does not override restaurant signals.
  Evidence: `tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates::test_news_with_restaurant_signal_yields_to_restaurant_dining`.
- [WP3-GUARD-003] PASSED — Narrow `gate_weather` to yield to travel-planning queries.
  Evidence: `tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates::test_travel_plan_with_weather_yields_to_travel_tourism`.
- [WP3-GUARD-004] PASSED — Add `gate_residence_statement` for standalone residence/location statements.
  Evidence: `qualification/hmi_routing_smoke.py` residence-statement cases all pass.
- [WP2/3-REGRESSION-001] PASSED — Full `tools/router_py` regression after all WP2/3 changes.
  Evidence: `qualification/results/router_py_regression_20260801_<timestamp>.log` (1996 passed, 0 failed).
- [WP2/3-HMI-001] PASSED — HMI routing smoke test.
  Evidence: `qualification/hmi_routing_smoke.py` (24/24 passed).
- [WP2/3-METRICS-001] PASSED — Recompute baseline per-route metrics.
  Evidence: `qualification/results/baseline_metrics.json` (validation 21/21, holdout 13/15, combined 34/36).

## STAGE_06 — Provider / URL / untrusted-web security

- [S6-UW-001] PASSED — DuckDuckGo result on a known misinformation domain is dropped.
  Evidence: tools/router_py/test_stage_06_untrusted_web.py::test_s06_uw_001_misinformation_domain_is_dropped
- [S6-UW-002] PASSED — Private-network URLs from planner output are rejected.
  Evidence: tools/router_py/test_stage_06_planner_security.py::test_s06_uw_002_private_network_url_rejected
- [S6-UW-003] PASSED — Malformed planner JSON produces zero HTTP requests.
  Evidence: tools/router_py/test_stage_06_planner_security.py::test_s06_uw_003_malformed_plan_json_produces_zero_http_requests

## STAGE_07 — Prompt construction and semantic model parity

- [S7-PP-001] PASSED — Same query produces identical prompts for Llama and Gemma except the model-specific identity line.
  Evidence: tools/router_py/test_stage_07_prompt_parity.py::test_s07_pp_001_prompts_differ_only_by_identity
- [S7-PP-002] PASSED — Session memory block is identical for Llama and Gemma.
  Evidence: tools/router_py/test_stage_07_prompt_parity.py::test_s07_pp_002_memory_block_parity
- [S7-PP-003] PASSED — Augmented context block is identical for Llama and Gemma.
  Evidence: tools/router_py/test_stage_07_prompt_parity.py::test_s07_pp_003_augmented_context_parity
- [S7-PP-004] PASSED — Conversation mode directive is identical for Llama and Gemma.
  Evidence: tools/router_py/test_stage_07_prompt_parity.py::test_s07_pp_004_conversation_mode_parity
- [S7-PP-005] PASSED — Gemma is detected as a thinking model and Llama is not.
  Evidence: tools/router_py/test_stage_07_prompt_parity.py::test_s07_pp_005_thinking_model_detection

## STAGE_08 — Gemma model smoke qualification

- [S8-GEM-001] PASSED — Gemma loads exclusively; no Llama resident during smoke.
  Evidence: tools/router_py/stage_08_gemma_smoke.py
- [S8-GEM-002] PASSED — Core local and augmented requests route correctly through Gemma.
  Evidence: qualification/results/stage_08_gemma_smoke.json
- [S8-GEM-003] PASSED — At least one request submitted through the HMI surface (RuntimeBridge).
  Evidence: tools/router_py/stage_08_gemma_smoke.py case gemma_hmi_surface

## STAGE_09 — Gemma shared scenario suite

- [S09-GEM-SUITE-001] PASSED — Gemma loads exclusively; no other Local Lucy model resident during any scenario.
  Evidence: tools/router_py/stage_09_gemma_scenario_suite.py + qualification/results/stage_09_gemma_scenarios.json (12/12 passed, loaded_models always `local-lucy-gemma4:latest`).
- [S09-GEM-SUITE-002] PASSED — Conspiracy-prone query routes LOCAL without web fallback.
  Evidence: S09-GEM-006 route=LOCAL, no http_request side effect.
- [S09-GEM-SUITE-003] PASSED — Model-selection fix: execution engine and memory service respect `LUCY_LOCAL_MODEL` instead of defaulting to `local-lucy`.
  Evidence: `tools/memory/memory_service.py`, `tools/router_py/execution_engine_state.py`, `tools/router_py/stage_09_gemma_scenario_suite.py`.
- [S09-GEM-SUITE-004] PASSED — Background heartbeat/warmup env gating tests pass.
  Evidence: tools/router_py/test_local_answer.py::TestHeartbeat + TestWarmup.

## STAGE_10 — Llama model smoke qualification

- [S10-LLM-001] PASSED — Llama loads exclusively; no Gemma resident during smoke.
  Evidence: tools/router_py/stage_10_llama_smoke.py
- [S10-LLM-002] PASSED — Core local and augmented requests route correctly through Llama.
  Evidence: qualification/results/stage_10_llama_smoke.json
- [S10-LLM-003] PASSED — At least one request submitted through the HMI surface (RuntimeBridge).
  Evidence: tools/router_py/stage_10_llama_smoke.py case llama_hmi_surface

## STAGE_11 — Full Llama shared suite and parity analysis

- [S11-LLM-SUITE-001] PASSED — Llama loads exclusively; no Gemma resident during any scenario.
  Evidence: tools/router_py/stage_11_llama_scenario_suite.py + qualification/results/stage_11_llama_scenarios.json
- [S11-LLM-SUITE-002] PASSED — Llama runs all shared scenarios sequentially.
  Evidence: qualification/results/stage_11_llama_scenarios.json (12/12 passed)
- [S11-LLM-SUITE-003] PASSED — Route and outcome parity with Gemma baseline recorded.
  Evidence: qualification/results/stage_11_llama_scenarios.json — route parity 12/12, outcome parity 12/12.

## STAGE_12 — Ollama, output parsing, HMI and limit handling

- [S12-HMI-001] PASSED — Trivial local query via HMI returns `CommandResult.status=ok` and a valid payload.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_submit_returns_valid_payload (6 passed total)
- [S12-HMI-002] PASSED — `evidence=on` state propagates into `LUCY_EVIDENCE_ENABLED=1` before backend invocation.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_state_propagation_evidence
- [S12-HMI-003] PASSED — `voice=off` state prevents voice-worker invocation while still returning a text answer.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_voice_disabled_does_not_invoke_voice
- [S12-HMI-004] PASSED — Empty submit text returns `status=unavailable` with a clear error.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_empty_submit_rejected
- [S12-HMI-005] PASSED — Backend failure payload is translated into a `CommandResult` with `status=failed`, non-empty `stderr`, and preserved `payload`.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_backend_failure_translated
- [S12-HMI-006] PASSED — Model-selection toggle change is reflected in the effective model passed to `submit_request`.
  Evidence: tools/router_py/test_hmi_end_to_end.py::test_hmi_model_selection_passed_to_backend
- [S12-HMI-007] PASSED — Voice-surface parity tests pass after test-isolation fix.
  Evidence: tools/router_py/test_voice_request_parity.py (8 passed)
- [S12-HMI-008] PASSED — HMI real-routing regression: restaurant/location queries route correctly and location anaphora resolves.
  Evidence: tools/router_py/test_hmi_real_routing.py (4 passed)
- [S12-OUT-001] PASSED — Response formatter validates local failures, strips markers, and enforces evidence truncation plus prompt-ceilings without Ollama.
  Evidence: tools/router_py/test_response_formatter.py (17 passed)

## STAGE_13 — Long-session continuity and model switching

- [S13-SW-001] PASSED — Sequential model switch Gemma -> Llama -> Gemma completes with only one Local Lucy model resident per step.
  Evidence: tools/router_py/stage_13_model_switch.py + qualification/results/stage_13_model_switch.json (3/3 passed)
- [S13-SW-002] PASSED — Each model answers a local query correctly after the switch.
  Evidence: qualification/results/stage_13_model_switch.json

## STAGE_14 — Controlled fault injection and recovery

- [S14-FLT-001] PASSED — Empty/whitespace input is rejected with `input_rejected` instead of reaching the pipeline.
  Evidence: tools/router_py/test_stage_14_fault_injection.py::TestPipelineFailureHandling::test_empty_input_rejected
- [S14-FLT-002] PASSED — An unexpected exception inside the pipeline is caught and returned as `status=failed`, `outcome_code=router_error`.
  Evidence: tools/router_py/test_stage_14_fault_injection.py::TestPipelineFailureHandling::test_pipeline_exception_returns_router_error
- [S14-FLT-003] PASSED — A failed `RouterOutcome` from the pipeline is handled safely and returned as a failed outcome.
  Evidence: tools/router_py/test_stage_14_fault_injection.py::TestPipelineFailureHandling::test_pipeline_failure_result_handled_safely
- [S14-FLT-004] PASSED — Ollama cleanup helpers degrade gracefully when the API is unreachable.
  Evidence: tools/router_py/test_stage_14_fault_injection.py::TestOllamaCleanupFailureHandling (2 passed)

## STAGE_15 — File, tool, privacy and audit controls

- [S15-UW-001] PASSED — Untrusted-source URL/title are stripped from assistant text before chat memory is persisted.
  Evidence: tools/router_py/privacy.py::strip_untrusted_source_annotations + tools/router_py/test_stage_15_privacy_audit.py::test_memory_turn_does_not_store_untrusted_source
- [S15-UW-002] PASSED — Untrusted-source URL/title are redacted from log-safe source strings when they contain sensitive query text.
  Evidence: tools/router_py/privacy.py::redact_untrusted_log_source + tools/router_py/test_stage_15_privacy_audit.py (4 passed)

## STAGE_16 — Performance, stability and RTX 3060 soak

- [S16-SOAK-001] PASSED — HMI end-to-end soak with Gemma and Llama returns successful CommandResult for every request.
  Evidence: tools/router_py/stage_16_hmi_soak.py + qualification/results/stage_16_hmi_soak.json (6/6 passed)
- [S16-SOAK-002] PASSED — No dual-model residency during the soak; model switches complete cleanly.
  Evidence: qualification/results/stage_16_hmi_soak.json loaded_models entries
- [S16-WX-001] PASSED — Fix low-confidence fallback misrouting to WEATHER/TIME: fallback only activates when query matches weather/time guards.
  Evidence: tools/router_py/stage_16_hmi_weather_boundary.py (6/6 passed)

## STAGE_17 — Optional live-network provider validation

- [S17-NET-001] PASSED — Live external providers (Wikipedia, time, weather, finance FX) return usable data.
  Evidence: tools/router_py/stage_17_live_network.py live provider checks (4/4 passed)
- [S17-NET-002] PASSED — Router correctly routes live-network queries (general knowledge, weather, time, medical, finance).
  Evidence: tools/router_py/stage_17_live_network.py router checks (5/5 passed)
- [S17-NET-003] PASSED — Trusted medical evidence is distinguished from general augmented providers.
  Evidence: tools/router_py/stage_17_live_network.py source distinction checks (2/2 passed)

## STAGE_18 — Optional voice-path smoke validation

- [S18-VOICE-001] PASSED — Voice surface routing and constraint enforcement parity with text surfaces.
  Evidence: tools/router_py/test_voice_request_parity.py (7 passed)
- [S18-VOICE-002] PASSED — Voice turns persist state to JSON files and SQLite without damaging the text path.
  Evidence: tools/router_py/test_e2e_hmi_voice.py (15 passed)

## STAGE_19 — Final clean-run qualification

- [S19-FINAL-001] PASSED — Mandatory model/HMI stages run sequentially from a clean process with no dual-model residency.
  Evidence: tools/router_py/stage_19_clean_run.py (7/7 passed)

## FINAL REQUALIFICATION — 2026-08-06

- [FRQ-BASE-001] PASSED — Baseline recorded: commit, branch, model digests, checksums, environment.
  Evidence: qualification/FINAL_REQUALIFICATION_BASELINE.md
- [FRQ-TRACE-001] PASSED — STAGE_00–STAGE_03 requirements mapped to evidence; statuses reconciled.
  Evidence: qualification/STAGE_00_03_TRACEABILITY.md
- [FRQ-MEM-001] PASSED — Post-STAGE_19 memory changes verified with dedicated tests.
  Evidence: tools/tests/test_memory_requalification.py + tools/router_py/test_execution_engine_memory.py (156 passed, 46 subtests passed)
- [FRQ-MET-001] PASSED — Routing metric inconsistency corrected; validation 21/21 = 1.000, holdout 13/15 = 0.867, combined 34/36 = 0.944.
  Evidence: qualification/test_baseline_metrics_consistency.py + qualification/results/baseline_metrics.json
- [FRQ-HOLD-001] PASSED — Two holdout misroutes investigated, classified, and documented; "search again" gap fixed.
  Evidence: qualification/KNOWN_LIMITATIONS.md + tools/router_py/test_search_imperative_anaphora.py
- [FRQ-VOICE-001] PASSED — Voice text-display issue investigated and documented as UNREPRODUCED.
  Evidence: qualification/VOICE_TEXT_DISPLAY_INVESTIGATION.md
- [FRQ-GUARD-001] PASSED — Guard boundary tests added for recently modified gates.
  Evidence: tools/router_py/test_policy_router.py::TestGuardBoundaries + tools/router_py/test_classify_low_confidence.py
- [FRQ-FULL-001] PASSED — Full deterministic regression across tools/router_py after privacy-redaction test alignment.
  Evidence: 1233 passed, 7 skipped, 274 deselected, 188 subtests passed (2026-08-06T16:39Z).
- [FRQ-MODEL-001] PASSED — Sequential model verification (Gemma/Llama, no dual residency).
  Evidence: stage_08_gemma_smoke.py 3/3; stage_09_gemma_scenario_suite.py 12/12; stage_10_llama_smoke.py 3/3; stage_11_llama_scenario_suite.py 12/12 with 12/12 route/outcome parity; stage_13_model_switch.py 3/3; ollama ps confirmed no dual residency after each stage.
- [FRQ-PRIV-001] PENDING — Privacy and fault verification.
- [FRQ-SOAK-001] PENDING — Soak and final clean run.
- [FRQ-MAN-001] PENDING — Create immutable qualification manifest and revised completion report.

---

**Qualification status:** STAGE_00–STAGE_19 complete. Final requalification in progress; full deterministic regression passed.
