# Local Lucy V11 — Routing Improvement Report

**Work package:** 1 — Baseline, guard inventory and failure corpus  
**Date:** 2026-08-01  
**Repository:** `/home/mike/lucy-v11`  
**Branch:** `main`  
**Commit:** `32490923dd607cd4c3da491ce5e4c8ebc0f29773`  

---

## 1. Baseline State

### 1.1 Environment

| Item | Value |
|---|---|
| Python | 3.10.12 |
| sentence-transformers | 5.5.1 |
| torch | 2.11.0+cu130 |
| sklearn | 1.7.2 |
| Active env flags | `LUCY_VOICE_PIPER_VOICE=en_GB-cori-high` |

### 1.2 Production router data checksums

| File | SHA-256 |
|---|---|
| `models/router/comprehensive_examples.json` | `0999af84014b13e5fa0a1ec3d6c2902c70f69061d1aebc39cc9b5cc4641cf828` |
| `models/router/comprehensive_embeddings.npy` | `20a6d4fe9b8c0221f15fecf5d629a4c825f2d308f9c0208ef9ceeadafc27f854` |
| `models/router/finetuned_minilm/model.safetensors` | `d2bfb77b41ab46d1f75cced4c67c17b0226813ca3a5d826b3f301a6d1be4af33` |

### 1.3 Working tree

- Tracked modified files: 19
- Untracked files/directories: 15
- v10 status: untouched (`git -C /home/mike/lucy-v10 status --short` empty)

### 1.4 Test baseline

Command:

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py -q --tb=short
```

Final result after test-isolation fix and diagnostic-trace test:

```text
1112 passed, 7 skipped, 267 deselected, 188 subtests passed in 574.11s (0:09:34)
```

Log: `qualification/results/router_py_regression_2026-08-01_final_post_wp1.log`

Previous runs:

- Before isolation fix: 1108 passed / 3 failed (DEF-001, DEF-002).
- After isolation fix, before diagnostic-trace test: 1111 passed / 0 failed.
- Final after adding diagnostic-trace test: 1112 passed / 0 failed.

Targeted verification after the fix:

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_plan_to_pipeline_characterization.py tools/router_py/test_pipeline_integration_flags.py tools/router_py/test_policy_router.py tools/router_py/test_hmi_real_routing.py tools/router_py/test_location_memory.py tools/router_py/test_search_imperative_anaphora.py tools/router_py/test_voice_request_parity.py -v --tb=short
```

Result: **60 passed, 0 failed**.

Isolated DEF-001/DEF-002 tests under polluted environment:

```bash
cd /home/mike/lucy-v11
LUCY_AUGMENTATION_POLICY=disabled LUCY_AUGMENTED_PROVIDER=wikipedia python3 -m pytest tools/router_py/test_plan_to_pipeline_characterization.py tools/router_py/test_pipeline_integration_flags.py -vv --tb=short
```

Result: **12 passed, 0 failed**.

---

## 2. Routing Guard Inventory

### 2.1 Policy gate execution order

The `PolicyRouter.DEFAULT_GATES` tuple in `tools/router_py/policy_router/router.py` defines the following order:

```text
1.  gate_personal_family
2.  gate_recreational_pet
3.  gate_explicit_assistant_instruction
4.  gate_explicit_capability_restriction
5.  gate_science_fact
6.  gate_medical_vet
7.  gate_garbage_nonsense
8.  gate_finance
9.  gate_restaurant_dining
10. gate_time
11. gate_weather
12. gate_news
13. gate_evidence_request
14. gate_conflict_analysis
15. gate_public_figure_age
16. gate_recipe
17. gate_travel_tourism
18. gate_current_information
19. gate_memory_followup
20. gate_stable_knowledge
21. gate_local_reasoning
22. gate_specific_entity_fact
23. gate_factual_lookup
24. gate_ambiguous_local
25. gate_attachment
```

`PolicyRouter.apply()` returns the **first** non-None decision.

### 2.2 Guard classification

| # | Gate | Category | Justification | Notes |
|---|---|---|---|---|
| 1 | `gate_personal_family` | Safety/capability | Enforces local-only handling of user family/pet facts | High precision; memory-based |
| 2 | `gate_recreational_pet` | Semantic compensation | Distinguishes casual pet queries from veterinary symptoms | Could be classifier-learned with better data |
| 3 | `gate_explicit_assistant_instruction` | Explicit command | Meta-instructions to assistant (self-model, diagnostic) | High precision; keep |
| 4 | `gate_explicit_capability_restriction` | Capability enforcement | "Do not store", "no network" etc. | High precision; keep |
| 5 | `gate_science_fact` | Semantic compensation | Stable science facts stay local | Could be classifier-learned; conflicts with weather |
| 6 | `gate_medical_vet` | Safety-critical | Medical/vet queries require trusted evidence | Keep; safety-critical |
| 7 | `gate_garbage_nonsense` | Structured high-precision | Symbol-only, keyboard-mash, placeholder input | Keep; prevents noise escape |
| 8 | `gate_finance` | Explicit/structured | Live market data patterns | Keep; clear domain |
| 9 | `gate_restaurant_dining` | Semantic compensation | Newly added; prevents time/weather misrouting | Candidate for classifier replacement after data improvement |
| 10 | `gate_time` | Explicit/structured | Time-of-day queries | Keep; clear domain |
| 11 | `gate_weather` | Explicit/structured | Weather queries | Keep; clear domain |
| 12 | `gate_news` | Explicit/structured | News phrasing | Keep; clear domain |
| 13 | `gate_evidence_request` | Explicit command | User asks for sources/verification | Keep; explicit command |
| 14 | `gate_conflict_analysis` | Semantic compensation | Prediction/analysis about live conflicts | Could be classifier-learned |
| 15 | `gate_public_figure_age` | Semantic compensation | Age of public figures needs current date | Could be classifier-learned |
| 16 | `gate_recipe` | Semantic compensation | Cooking queries benefit from web | Could be classifier-learned |
| 17 | `gate_travel_tourism` | Semantic compensation | Travel destination queries | Could be classifier-learned |
| 18 | `gate_current_information` | Semantic compensation | Umbrella for current/changing non-financial facts | Broad; candidate for classifier replacement |
| 19 | `gate_memory_followup` | Capability enforcement | Explicit references to prior conversation stay local | Keep |
| 20 | `gate_stable_knowledge` | Semantic compensation | Stable educational/scientific/technical knowledge | Overlaps with science_fact; review |
| 21 | `gate_local_reasoning` | Semantic compensation | Opinion, speculation, conspiracy | Broad; candidate for classifier + better data |
| 22 | `gate_specific_entity_fact` | Semantic compensation | Named entity facts -> AUGMENTED | Could be classifier-learned |
| 23 | `gate_factual_lookup` | Semantic compensation | Broad factual lookups -> AUGMENTED | Very broad; highest replacement priority |
| 24 | `gate_ambiguous_local` | Semantic compensation | Known adversarial misroutings -> LOCAL | Diagnostic; should shrink as classifier improves |
| 25 | `gate_attachment` | Capability/structured | File/image/document present | Keep |

### 2.3 Candidate guards for eventual reduction

These are classified as **semantic compensation** and are candidates to be narrowed or removed once the classifier and dataset improve:

- `gate_recreational_pet`
- `gate_science_fact`
- `gate_restaurant_dining`
- `gate_conflict_analysis`
- `gate_public_figure_age`
- `gate_recipe`
- `gate_travel_tourism`
- `gate_current_information`
- `gate_stable_knowledge` (overlap with `gate_science_fact`)
- `gate_local_reasoning`
- `gate_specific_entity_fact`
- `gate_factual_lookup`
- `gate_ambiguous_local`

**Safety-critical and explicit-command guards must remain:**

- `gate_medical_vet`
- `gate_explicit_assistant_instruction`
- `gate_explicit_capability_restriction`
- `gate_memory_followup`
- `gate_attachment`
- `gate_garbage_nonsense`
- `gate_finance`
- `gate_time`
- `gate_weather`
- `gate_news`
- `gate_evidence_request`
- `gate_personal_family`

---

## 3. Defect Resolution

### DEF-001 — Characterization snapshot drift

- **Status:** CLOSED
- **Severity:** MEDIUM
- **Tests:** `test_plan_to_pipeline_characterization.py::test_local_knowledge`, `test_pet_food`
- **Root cause:** Test isolation leak, not a contract drift. When the full `tools/router_py` suite runs, an earlier test loads `main.py`, whose `ensure_control_env()` sets `LUCY_AUGMENTATION_POLICY=disabled` and `LUCY_AUGMENTED_PROVIDER=wikipedia` in the parent pytest process. The CLI subprocess in the characterization test inherited these values, causing `winning_signal` to become `legacy_policy` and `intent_family` to be dropped from reason codes.
- **Fix:** `test_plan_to_pipeline_characterization.py::_run()` now invokes the CLI with an explicit `LUCY_AUGMENTATION_POLICY=fallback_only` and without `LUCY_AUGMENTED_PROVIDER`, so the subprocess runs in a known default state regardless of parent-process pollution.
- **Verification:** `python3 -m pytest tools/router_py/test_plan_to_pipeline_characterization.py -v` passes both in isolation and when the parent environment is pre-polluted with `LUCY_AUGMENTATION_POLICY=disabled LUCY_AUGMENTED_PROVIDER=wikipedia`.

### DEF-002 — Trusted-source parity provider mismatch

- **Status:** CLOSED
- **Severity:** MEDIUM
- **Test:** `test_pipeline_integration_flags.py::test_trusted_sources_only_critical_preserves_parity_decision`
- **Root cause:** Same parent-process pollution as DEF-001. `LUCY_AUGMENTED_PROVIDER=wikipedia` caused `provider_resolver.resolve_provider()` to return `wikipedia` instead of the query-type default `kimi` for a safety/general classification.
- **Fix:** `test_pipeline_integration_flags.py::_set_flags()` now deletes `LUCY_AUGMENTED_PROVIDER` and `LUCY_AUGMENTATION_POLICY` so provider resolution uses the intended query-type defaults in this suite.
- **Verification:** `python3 -m pytest tools/router_py/test_pipeline_integration_flags.py -v` passes in isolation and under the polluted environment.

---

## 4. Provider Semantics — Initial Clarification

The failing test `test_trusted_sources_only_critical_preserves_parity_decision` expects `final_decision.provider == "kimi"` but receives `"wikipedia"`.

Before fixing the value, the architectural roles must be separated conceptually:

| Role | Meaning | Current carrier |
|---|---|---|
| `route` | High-level routing decision (LOCAL, AUGMENTED, EVIDENCE, NEWS, WEATHER, TIME, FINANCE) | `RouterOutcome.route` |
| `execution_provider` | The service that actually fetches/executes the request | Often `RouterOutcome.provider` |
| `evidence_sources` | Trusted sources used for evidence (Wikipedia, official APIs) | Implicit in route/attribution |
| `synthesis_provider` | Model/service that synthesises final answer (Kimi, OpenAI, local Ollama) | Sometimes `RouterOutcome.provider` |
| `verification_provider` | Optional verifier for uncertain claims | Not clearly separated |
| `policy_decision` | Why a particular trust level was chosen | `evidence_reason`, `policy_reason` |

The immediate task for DEF-002 is to determine what the test intended `kimi` to mean in this context, and whether the current `wikipedia` value represents a behavioural defect, a naming defect, or an overloaded-field defect. A broad refactor is deferred.

---

## 5. Failure Corpus

Created `qualification/routing_failure_corpus.jsonl` with 53 cases split into:

| Split | Count | Purpose |
|---|---|---|
| `development` | 17 | Iterate dataset/classifier improvements |
| `validation` | 21 | Tune thresholds and measure candidate progress |
| `locked_holdout` | 15 | Independent final evaluation; includes all real HMI failures |

Fields per case:

```text
case_id
source                      # real_hmi_failure | real_hmi_success | synthetic_regression | adversarial | boundary | negative_control
conversation_context
original_query
expected_primary_route
acceptable_alternative_routes
forbidden_routes
expected_capabilities
expected_evidence_policy
expected_context_resolution
risk_level
notes
split
```

Real HMI failures preserved from 2026-08-01 live use:

- `HMI-REST-001/002/003` — restaurant/dining queries misrouted to TIME/WEATHER.
- `HMI-ANAPH-001` — bare "Use DuckDuckGo search" imperative not inheriting prior web topic.
- `HMI-LOC-001/002` — location anaphora ("this area", "area code") not resolved to stored Kibbutz Magal fact.
- `HMI-AUG-001` — explicit location mention correctly routed to AUGMENTED (success case).
- `HMI-LOC-003/004` — location-awareness and residence-statement handling (success cases).

---

## 6. Lightweight Diagnostic Trace

Implemented in `tools/router_py/request_pipeline.py`.

- Enabled when `LUCY_ROUTER_DIAGNOSTICS=1` (or `true`/`yes`).
- Output path defaults to `qualification/router_diagnostics.jsonl`; overridable with `LUCY_ROUTER_DIAGNOSTICS_PATH`.
- Emits one JSONL entry per request, **only** on the successful execution path, with fields:

```text
timestamp
request_id
original_query
resolved_query
classifier_intent
classifier_confidence
classifier_intent_family
candidate_routes
pre_guard_route
pre_guard_provider
final_route
final_provider
execution_provider
evidence_policy
evidence_reason
policy_reason
reason_code
matched_rule
capability_flags
outcome_code
```

This is a diagnostic/instrumentation path only; it does not alter user-visible output.

---

## 7. Baseline Per-Route Metrics

Computed by `qualification/compute_baseline_metrics.py` using the current production router (data-only candidate, commit `3249092`).

> **Scope note:** These metrics measure `classify_question` + `select_route_for_question` only. Anaphora resolution, location rewriting, and search-imperative inheritance are handled in `main.py` and are not included in this baseline.

| Split | Cases | Accuracy |
|---|---|---|
| Validation | 21 | 0.857 (18/21) |
| Locked holdout | 15 | 0.867 (13/15) |
| Combined | 36 | 0.861 (31/36) |

> **Note:** This table reflects the baseline *before* Work Package 2/3 guard and dataset changes. The current, qualified baseline is in section 9.2 and in `qualification/results/baseline_metrics.json`.

Per-route F1 (combined):

| Route | Precision | Recall | F1 |
|---|---|---|---|
| AUGMENTED | 0.867 | 0.722 | 0.788 |
| EVIDENCE | 1.000 | 0.750 | 0.857 |
| FINANCE | 1.000 | 1.000 | 1.000 |
| LOCAL | 0.750 | 0.600 | 0.667 |
| NEWS | 1.000 | 1.000 | 1.000 |
| WEATHER | 0.500 | 1.000 | 0.667 |

Detailed results: `qualification/results/baseline_metrics.json`.

Key observations:

- AUGMENTED recall is the weakest point (0.722). Many failures are restaurant/location cases that still need either better classifier coverage or the existing `gate_restaurant_dining` deterministic guard.
- LOCAL recall is also low (0.600) because several negative-control/hypothetical-location cases are misclassified as AUGMENTED.
- The baseline gives Work Package 2 a quantitative target: improve AUGMENTED recall and LOCAL precision without degrading the strong EVIDENCE/NEWS/FINANCE boundaries.

---

## 8. Next Steps

1. Wait for full `tools/router_py` regression to confirm 0 failures after the test-isolation fix.
2. Update qualification control files (`TEST_TODO.md`, `TEST_STATUS.json`, `SESSION_HANDOFF.md`, `DEFECT_REGISTER.md`, `DECISIONS.md`).
3. Move to Work Package 2 — dataset/classifier improvement using the development split and validation metrics.

---

---

# 9. Work Package 2/3 — Classifier dataset and guard narrowing

**Date:** 2026-08-01 (continued)  
**Work package:** 2 — Dataset/classifier improvement; 3 — Guard narrowing  
**Commit after changes:** (recorded at end of session)  

## 9.1 Summary of changes

1. **CPR edge-case relabel** — `models/router/comprehensive_examples.json`  
   - Changed `"Step by step instructions for CPR"` from `LOCAL` to `AUGMENTED`.  
   - Embeddings rebuilt (`scripts/rebuild_embeddings.py`).  
   - The existing `classifier_head.pt` was retained; a fresh retrain introduced a validation-corpus AUGMENTED recall regression, so the previous head was restored after confirming it now routes CPR correctly and meets all per-route recall thresholds.

2. **Policy-guard narrowing** — `tools/router_py/policy_router/gates.py` and `router.py`  
   - `gate_evidence_request` now respects explicit network denials (`do not search the web`) and local-only markers (`use only currently available information`).  
   - `gate_evidence_request` also skips arithmetic queries with a trailing evidence imperative (`What is 2+2? Search the web.`).  
   - `gate_weather` yields to travel-planning queries (`Plan a trip to Paris and tell me the weather` → `AUGMENTED` via `gate_travel_tourism`).  
   - `gate_restaurant_dining` now catches common food-specific establishments (`pizza place`, `sushi spot`, etc.), so `News about the best pizza place near me` no longer gets forced to `NEWS`.  
   - New `gate_residence_statement` routes standalone residence/location statements and quoted/hypothetical residence to `LOCAL` before the weather gate can misroute them (`Actually I live in Kibbutz Magal in Israel.`).

3. **Network-denial parser** — `tools/router_py/request_constraints.py`  
   - Added `do not search the web` as a network denial so it can be enforced by routing and execution stages.

4. **Tests added** — `tools/router_py/test_policy_router.py`  
   - Evidence-request local-only/negative-control tests.  
   - News-with-restaurant-signal test.  
   - Travel-planning + weather test.  
   - Pure-weather negative control.

## 9.2 Test results

### Full `tools/router_py` regression

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py -q --tb=short
```

Result: **1996 passed, 0 failed, 129 skipped, 267 deselected, 188 subtests passed in 610.05s**.

Log: `qualification/results/router_py_regression_20260801_<timestamp>.log` (most recent).

### HMI routing smoke test

```bash
cd /home/mike/lucy-v11
python3 qualification/hmi_routing_smoke.py
```

Result: **24/24 passed**.

### Baseline per-route metrics (routing corpus)

```bash
cd /home/mike/lucy-v11
python3 qualification/compute_baseline_metrics.py
```

| Split | Cases | Accuracy |
|---|---|---|
| Validation | 21 | 1.000 (21/21) |
| Locked holdout | 15 | 0.867 (13/15) |
| Combined | 36 | 0.944 (34/36) |

Detailed results: `qualification/results/baseline_metrics.json`.

## 9.3 Remaining risks and next steps

- The AUGMENTED recall target on the frozen validation corpus is now met, but it depends on the original classifier head plus the relabelled CPR embedding. Any future classifier retrain must be verified against the same frozen corpus before promotion.
- Residence-statement guard is intentionally narrow (standalone statements only) so it does not suppress genuine weather queries that mention the user's location.
- The locked-holdout cases that remain misrouted are documented in `qualification/results/baseline_metrics.json` and should be addressed in the next dataset iteration without leaking holdout examples.

---

*End of current work package.*
