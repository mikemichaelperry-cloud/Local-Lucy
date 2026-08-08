# Local Lucy V11 Qualification — Decision Log

## Template

```text
[DEC-NNN] YYYY-MM-DD — Title
Context:
Decision:
Alternatives considered:
Consequences:
```

---

## DEC-001 — 2026-07-30 — Scope the programme into bounded stages

**Context:** The full staged qualification programme is large. Attempting it in one uninterrupted session would be risky and would produce shallow results.

**Decision:** Run the programme stage by stage, completing each stage's exit criteria before entering the next. Stage 00 (baseline and control files) is being completed first.

**Alternatives considered:**
- Implementing the entire harness and all stages at once — rejected because it would be hard to debug and validate.
- Skipping the formal programme and relying on existing tests — rejected because the user explicitly requested an independent qualification after the module splits.

**Consequences:** Progress is slower but each increment is verifiable. Session handoffs will carry the exact resume state.

---

## DEC-008 — 2026-08-01 — Treat DEF-001/DEF-002 as test-isolation leaks, not production defects

**Context:** After the router-data swap, `test_plan_to_pipeline_characterization.py` and `test_pipeline_integration_flags.py::test_trusted_sources_only_critical_preserves_parity_decision` passed in isolation but failed in the full `tools/router_py` suite. Investigation showed that `main.py::ensure_control_env()` writes `LUCY_AUGMENTATION_POLICY=disabled` and `LUCY_AUGMENTED_PROVIDER=wikipedia` into `os.environ` when no state file exists. An earlier test that imports `main.py` pollutes the parent pytest process, and the failing tests inherit those values.

**Decision:**

1. Close DEF-001 and DEF-002 as test-isolation issues, not router/planner defects.
2. Fix `test_plan_to_pipeline_characterization.py` by giving the CLI subprocess a controlled environment (`LUCY_AUGMENTATION_POLICY=fallback_only`, no `LUCY_AUGMENTED_PROVIDER`).
3. Fix `test_pipeline_integration_flags.py` by deleting `LUCY_AUGMENTED_PROVIDER` and `LUCY_AUGMENTATION_POLICY` in the `_set_flags` helper so provider resolution uses query-type defaults.
4. Do not change `main.py` production behavior; the env-var mutation is intentional for runtime state propagation.

**Alternatives considered:**

- Updating the snapshots to match the `disabled` policy output — rejected because the snapshots represent the intended default CLI behavior, and the pollution is accidental.
- Fixing the polluter test to restore env vars — rejected because multiple tests import `main.py`; making every consumer defensive is fragile. The tests that are sensitive to the env vars should control their own environment.
- Refactoring `main.py` to avoid global env mutation — rejected because it is a larger architectural change outside the current routing-improvement scope and could break production state propagation.

**Consequences:** The full `tools/router_py` regression now passes with 1111 passed / 0 failed. The characterization and parity tests are robust against parent-process env pollution.

---

## DEC-007 — 2026-08-01 — Promote the data-only router candidate to production

**Context:** A candidate router dataset with 320 additional examples targeting restaurant/dining, location anaphora, and search-imperative cases improved holdout accuracy from 73.20% to 81.44% with zero regressions. A fine-tuned variant achieved 79.38% and introduced 3 weather/ephemeral regressions.

**Decision:** Promote the data-only candidate by replacing `models/router/comprehensive_examples.json` and `models/router/comprehensive_embeddings.npy` with the candidate versions. Keep the original production files as `.production_backup_20260801`. Do not promote the fine-tuned checkpoint.

**Alternatives considered:**

- Promoting the fine-tuned checkpoint — rejected because it regressed on weather/ephemeral boundaries.
- Keeping the production data unchanged — rejected because the data-only candidate was strictly better on the holdout and passed the full regression with no new failures.
- Running more live HMI tests before swapping — acceptable but not necessary because the full deterministic regression already validated the swap.

**Consequences:** The production router now uses 1,694 examples including explicit coverage for the previously-failing restaurant/dining and anaphora patterns. The change is reversible by restoring the backup files.

---

## DEC-006 — 2026-08-01 — Add a narrow deterministic restaurant/dining guard before time/weather gates

**Context:** Live HMI logs showed restaurant/dining questions being misrouted to `TIME` (`"Search for restaurants in my area that are open today"`) or `WEATHER` (`"I am looking for a good restaurant open today near kibbutz Magal"`). The embedding-based classifier and existing policy gates did not have a specific restaurant/dining concept, so location/time qualifiers in the query were captured by the stronger time/weather gates.

**Decision:**

1. Add a narrow deterministic `gate_restaurant_dining` in `tools/router_py/policy_router/gates.py`.
2. Register it before `gate_time` and `gate_weather` in `tools/router_py/policy_router/router.py`.
3. Route matched queries to `AUGMENTED` (general-knowledge web lookup) so location-aware restaurant hours and recommendations can use current data.
4. Keep the gate intentionally conservative: it requires both restaurant/dining keywords and a location/time qualifier, and it does not match pet food, recipes, or stable culinary facts.
5. Add policy-router and HMI real-routing regression tests for the new gate.

**Alternatives considered:**

- Relying on the embedding classifier to learn the restaurant/dining concept from examples — rejected because the live failures proved the classifier alone was not reliable for this niche, and deterministic guards are cheaper to reason about.
- Routing restaurant queries to `EVIDENCE` — rejected because restaurant recommendations and hours are not high-stakes medical/legal/financial evidence; `AUGMENTED` web lookup is the appropriate trust level.
- Adding a broad "food/dining" gate that matches any recipe or ingredient query — rejected because stable culinary knowledge should remain `LOCAL`.

**Consequences:** Restaurant/dining queries with location/time qualifiers now route to `AUGMENTED` consistently, and the deterministic guard prevents the time/weather gates from misclassifying them.

---

## DEC-005 — 2026-08-01 — HMI real-routing tests must explicitly enable evidence

**Context:** HMI-level routing tests that exercise the real pipeline need to verify that restaurant/location queries reach `AUGMENTED`. In the full test suite, `tools/router_py/test_hmi_end_to_end.py` replaced `sys.modules["runtime_request"]` with a fake module and did not restore it, so the HMI real-routing tests imported the fake `submit_request` and received a hardcoded `LOCAL` payload. In addition, the `temp_namespace` fixture only set `LUCY_ENABLE_INTERNET=0`, so when the tests ran in isolation `ensure_control_env()` defaulted evidence to on and masked the fake-module leak.

**Decision:**

1. Set both `LUCY_EVIDENCE_ENABLED=1` and `LUCY_ENABLE_INTERNET=1` in the `test_hmi_real_routing.py` fixture.
2. Continue blocking outbound HTTP with a monkeypatched `urllib.request.urlopen` so the tests remain hermetic.
3. Treat this as a test-isolation fix, not a production routing change.

**Alternatives considered:**
- Asserting `LOCAL` when evidence is disabled — rejected because it would not verify the restaurant/dining gate.
- Running the HMI tests in a subprocess with a clean environment — rejected because it adds overhead and hides real isolation gaps.
- Resetting the entire `os.environ` in the fixture — rejected because it would break module-level paths and XDG resolution.

**Consequences:** The HMI real-routing tests now pass both in isolation and in the full suite, and they document that the restaurant gate routes to `AUGMENTED` under normal (evidence-enabled) runtime conditions.

---

## DEC-009 — 2026-08-01 — Restore the previous classifier head after a retrain regression

**Context:** After relabelling the CPR example, a full retrain of `classifier_head.pt` produced a model that passed the CPR edge case but dropped AUGMENTED recall on the frozen validation corpus below the baseline (`0.3226 < 0.35`) and caused finance/adversarial regressions.

**Decision:**

1. Restore `models/router_classifier_head.pt` to the git HEAD checkpoint (trained on the pre-CPR-relabel dataset).
2. Keep the relabelled dataset and rebuilt embeddings.
3. Verify that the restored head routes CPR correctly and meets all per-route recall thresholds on the frozen validation corpus.
4. Document that future classifier retrains must be validated against the frozen validation corpus before promotion.

**Alternatives considered:**

- Iterating the training hyperparameters until the new head passed — rejected because it would be a random search and could introduce other regressions.
- Adding more training examples to compensate for the new head's weakness — rejected because it would risk overfitting to the validation corpus and the previous head was already a known-good production baseline.
- Lowering the AUGMENTED recall threshold in the test — rejected because the threshold represents an accepted Phase-4 baseline and should not be relaxed to hide a model change.

**Consequences:** The production router now uses the original classifier head with the updated embeddings. CPR routes correctly and all frozen-corpus thresholds are satisfied.

---

## DEC-010 — 2026-08-01 — Narrow the evidence-request guard for local-only and arithmetic queries

**Context:** `gate_evidence_request` forced `AUGMENTED` whenever it saw phrases like `search the web`, `verify this`, or `cite sources`, even when the user had explicitly denied network access or the query was purely arithmetic.

**Decision:**

1. Check `extract_request_constraints(query)` inside `gate_evidence_request`; return `None` if `network=False` or `local_only=True`.
2. Return `None` if the query contains arithmetic operators, because the broad `factual_lookup` gate already excludes math and the result should stay `LOCAL`.
3. Add `do not search the web` to the network-denial patterns in `request_constraints.py`.

**Alternatives considered:**

- Removing the evidence-request guard entirely — rejected because explicit source requests are still a high-value signal for routing.
- Building a separate "local capability" classifier — rejected as over-engineering; the arithmetic regex is a narrow, deterministic check that matches the existing math exclusion.

**Consequences:** Users can append "do not search the web" or ask math questions without the router forcing an external lookup.

---

## DEC-011 — 2026-08-01 — Add a narrow residence-statement guard before weather

**Context:** Standalone residence statements such as "Actually I live in Kibbutz Magal in Israel." were misrouted to `WEATHER` because the k-NN embedding fallback associated place names with weather queries.

**Decision:**

1. Add `gate_residence_statement` before `gate_weather` in `PolicyRouter.DEFAULT_GATES`.
2. Match standalone patterns: "I live in ...", "Actually I live in ...", "I no longer live in ...", "I used to live in ...", "I am staying in ...", "My X lives in ...", "If I lived in ...", and quoted residence ("The article says, 'I live in ...'").
3. Require no question mark and no weather terms in the query, so genuine weather requests about the user's location are not suppressed.

**Alternatives considered:**

- Adding many residence-statement examples to the training set — considered but insufficient on its own; the guard provides deterministic, explainable behaviour for a clear semantic class.
- Matching any sentence containing "I live in" anywhere — rejected because it would suppress compound sentences like "I live in X. Search for restaurants...".

**Consequences:** Residence and hypothetical-location statements route to `LOCAL` reliably, and the location-memory subsystem can process them without weather misrouting.

---

## DEC-012 — 2026-08-01 — Broaden the restaurant/dining guard for food-specific establishments

**Context:** `gate_news` forced `NEWS` for "News about the best pizza place near me" because `gate_restaurant_dining` did not recognise "pizza place" as a dining signal.

**Decision:**

1. Add a separate `_FOOD_ESTABLISHMENT_RE` pattern covering common food-type + establishment forms (`pizza place`, `burger joint`, `sushi spot`, etc.).
2. Include it in `gate_restaurant_dining` alongside the existing `_RESTAURANT_DINING_RE`, still requiring a location/time qualifier.
3. Keep recipe and stable-food queries unaffected because they lack the qualifier.

**Alternatives considered:**

- Adding a special-case check in `gate_news` to yield to restaurant signals — rejected because it would duplicate the restaurant decision and produce a non-restaurant reason code.
- Adding individual food words to `_RESTAURANT_DINING_RE` — rejected because bare words like "pizza" would match recipe queries; pairing with establishment terms keeps precision high.

**Consequences:** Food-specific dining lookups with location/time qualifiers route to `AUGMENTED` instead of being hijacked by the news guard.

---

## DEC-002 — 2026-07-30 — Keep qualification artefacts in `qualification/`

**Context:** The programme requires many control files, reports, traces, fixtures, scenarios and results.

**Decision:** Store all qualification artefacts under `lucy-v11/qualification/`, separate from production code and data.

**Alternatives considered:**
- Scattering files across the repo root — rejected because it would clutter the project.
- Placing files under `tools/router_py/` — rejected because qualification is cross-cutting, not a router feature.

**Consequences:** The directory is self-contained and can be archived or removed without affecting production.

---

## DEC-003 — 2026-07-30 — Adapt the qualification programme for the new untrusted-web source path

**Context:** The staged qualification programme was written before the new DuckDuckGo fallback was added inside `execution_engine`. The programme therefore does not explicitly cover an untrusted-web source route, source-quality filtering, or the "untrusted" trust label. Some of its assumptions (e.g. "external routes" equals NEWS/WEATHER/TIME/FINANCE/EVIDENCE/AUGMENTED) are now incomplete.

**Decision:** Update `TEST_MASTER_PLAN.md` and `TEST_CATALOGUE.md` to include explicit coverage of:

- when the untrusted-web fallback is allowed and when it is blocked;
- correct `provider=web_untrusted` and `trust_label=untrusted` attribution;
- answer prefix/caveat labelling;
- source-quality controls (domain allowlist/blocklist, known misinformation tropes);
- interaction with critical-source policy and capability restrictions.

Keep the original stage structure; add the new concerns as explicit tasks inside Stage 05, Stage 06, Stage 15, and Stage 17 rather than creating a whole new stage.

**Alternatives considered:**
- Treating the untrusted fallback as part of the existing AUGMENTED tests only — rejected because it hides a distinct trust boundary.
- Creating a brand-new stage just for untrusted sources — rejected because it would fragment the programme; the existing stages already cover routing, provider security, privacy/audit, and live-network validation.

**Consequences:** The qualification programme remains staged and manageable, but it now explicitly verifies the new source layer instead of assuming it is covered implicitly.

---

## DEC-013 — 2026-08-06 — Reconcile STAGE_00–STAGE_03 statuses during final requalification

**Context:** The completion report claimed all stages passed, but `TEST_STATUS.json` showed STAGE_00 and STAGE_01 as `IN_PROGRESS` and STAGE_02/STAGE_03 as `NOT_STARTED`. This contradicted the report and the mandate's requirement that every STAGE_00–STAGE_03 requirement be mapped to evidence.

**Decision:**

1. Treat STAGE_00 as `PASSED` for its core baseline/production-data-protection requirements and `SUPERSEDED_WITH_EVIDENCE` for items realised through later qualification work.
2. Treat STAGE_01, STAGE_02, and STAGE_03 as `SUPERSEDED_WITH_EVIDENCE` because their exit criteria are satisfied by the full regression, stage scripts, memory tests, fault-injection tests, and privacy tests rather than by discrete early-stage runs.
3. Record the mapping in `qualification/STAGE_00_03_TRACEABILITY.md`.
4. Update `qualification/TEST_STATUS.json` and `qualification/TEST_TODO.md` to reflect the reconciled statuses.

**Alternatives considered:**

- Re-running STAGE_00–STAGE_03 as originally written — rejected because the original programme was executed opportunistically to fix urgent production defects, and the later stage evidence already covers these concerns.
- Marking all four stages `PASSED` without a traceability mapping — rejected because it would hide the fact that the evidence comes from later stages.

**Consequences:** The completion report, status file, and TODO file now agree. `QUALIFIED` cannot be claimed solely on "all stages passed"; it must reference the traceability document.

---

## DEC-014 — 2026-08-06 — Classify the two holdout misroutes and fix the "search again" gap

**Context:** The locked holdout remained 13/15. Both failures were anaphoric search imperatives: HMI-ANAPH-001 ("Use DuckDuckGo search") and HOLD-ANAPH-001 ("Can you search again?"). The final requalification mandate requires each to be classified as `ACTIVE_DEFECT`, `ACCEPTED_LIMITATION`, or `TEST_EXPECTATION_ERROR`.

**Decision:**

1. Classify HOLD-ANAPH-001 as an `ACTIVE_DEFECT` in the search-imperative resolver and fix it by extending `_SEARCH_TOOL_IMPERATIVE_PATTERN` to cover `(?:can you\s+)?search\s+(?:again|once\s+more)` with optional trailing "please".
2. Classify HMI-ANAPH-001 as a `TEST_EXPECTATION_ERROR` of the holdout metric: the metric intentionally excludes `main.py` anaphora/context resolution, so a bare imperative cannot be expected to route `AUGMENTED` in isolation. The real HMI path was fixed in DEF-005 and still works.
3. Document both cases in `qualification/KNOWN_LIMITATIONS.md` and add DEF-012 to `qualification/DEFECT_REGISTER.md`.
4. Add regression tests for "search again" variants in `tools/router_py/test_search_imperative_anaphora.py`.

**Alternatives considered:**

- Adding the holdout cases to the training/development corpus — rejected because the mandate forbids copying or relabelling locked holdout cases.
- Implementing a generic low-confidence AUGMENTED fallback — rejected because low confidence does not prove external information is required (mandate §8).

**Consequences:** The actual user-visible path now resolves "Can you search again?" correctly when prior web context exists. The holdout metric remains 13/15 because it bypasses `main.py`; this is explicitly documented as a metric-scope limitation.

---

## DEC-015 — 2026-08-06 — Align auto-web escalation-suggestion tests with STAGE_15 privacy redaction

**Context:** During the final full deterministic regression, four tests failed because they expected the raw untrusted URL (`example.com/found`) or raw title (`Rarest Element`) in `escalation_suggestion`. The STAGE_15 privacy helpers (`tools/router_py/privacy.py`) intentionally reduce untrusted URLs to their registered domain and redact titles that contain significant query terms. The failing tests pre-dated that redaction.

**Decision:**

1. Treat the failures as stale test expectations, not as code defects.
2. Update `tools/router_py/test_web_fetcher.py`, `tools/router_py/test_pipeline_integration_flags.py`, and `tools/router_py/test_new_features_demo.py` to assert the redacted format: domain-only URL, redacted title when query terms overlap, and the continued presence of the "untrusted" marker.
3. Add negative assertions proving that full paths and query-bearing titles do **not** leak into the suggestion.

**Alternatives considered:**

- Reverting the redaction so that URLs/paths remain visible in suggestions — rejected because it would undo STAGE_15 privacy controls and could leak sensitive query text into logs and UI.
- Adding the redaction logic only for logs and keeping the raw suggestion — rejected because the escalation suggestion is user-visible and log-persisted; the same redaction policy must apply.

**Consequences:** The full deterministic regression now passes (1233 passed, 7 skipped). The privacy redaction behavior is consistently tested by both `test_stage_15_privacy_audit.py` and the auto-web suggestion tests.

---

## DEC-017 — 2026-08-08 — Auto-learn defaults to opt-in

**Context:** Auto-learn had conflicting defaults: `tools/runtime_control.py` resolved the initial learner state to ON when `LUCY_AUTO_LEARN` was unset, while `models/router/background_learner.py` defaulted to OFF. The runtime_control default meant a fresh install could silently self-modify (embedding rebuilds triggered by conversational feedback) without the operator opting in.

**Decision:**

1. Flip `tools/runtime_control.py` (`_resolve_initial_learner_state`) to opt-in: the learner resolves to `"on"` only when `LUCY_AUTO_LEARN` is explicitly set to a truthy value (`1`, `true`, `yes`, `on`); unset means `"off"`, matching `background_learner.py`.
2. The `.learner_disable` flag continues to force `"off"` regardless of the environment.

**Alternatives considered:**

- Keeping the runtime_control default ON — rejected because it allows silent embedding rebuilds from conversational feedback on fresh installs.

**Consequences:** Fresh installs ship with the learner off; it is enabled via the HMI toggle or `LUCY_AUTO_LEARN=1`. Existing feedback/learner tests set `LUCY_AUTO_LEARN=1` explicitly and are unaffected.

---

## DEC-018 — 2026-08-08 — Shared scenario evaluation and any-of concept checks

**Context:** The STAGE_09 (Gemma) and STAGE_11 (Llama) scenario suites each carried their own copy of the response-evaluation logic (literal-substring concept checks), and the two copies had already drifted: the S09-MEM-003 flake on 2026-08-07 (model-wording variance on the required concept "Local Lucy") had to be diagnosed against two near-identical implementations, and the DEC-016 relaxation for S09-GEM-007 existed only as a hardcoded per-scenario special case in code.

**Decision:**

1. Deduplicate scenario evaluation into a single shared implementation: `tools/router_py/scenario_checks.py` (`evaluate_response`), used by both stage_09 and stage_11 suites.
2. Add a declarative `required_answer_concepts_any` JSON field (any one of the listed concepts satisfies the check), so any-of relaxations are scenario-schema changes, not code special cases. The hardcoded S09-GEM-007 special case is expressed via this field.
3. S09-MEM-003 stays strict: it keeps its all-concepts check on "Local Lucy".

**Alternatives considered:**

- Relaxing S09-MEM-003 to accept "Lucy" as the identity concept — rejected: the identity name is the point of the scenario; a model that answers with the wrong name should fail.

**Consequences:** The flake surface is reduced to one implementation; future assertion relaxations are schema changes recorded in scenario JSON, not code edits. Scenario JSON schemas gain one optional field; existing scenarios are unchanged.

**Related test repair (same closeout):** the 16 carried failures in `tools/router_py/test_local_answer.py` (visible only with markers unrestricted, `-m ""`) were stale `unittest.mock.patch` targets left over from the `local_answer.py` → `local_answer_core/` package split. The attributes had moved, so patches were repointed mechanically to the module namespace that actually consumes each symbol (`router_py.local_answer_core.engine.*` for engine-bound helpers, `router_py.local_answer_core.self_knowledge.*` for persona/identity helpers). No test was deleted; no product behavior was changed to satisfy a test, with two exceptions worth recording: (a) `test_memory_preamble_is_authoritative` was updated to match the deliberate Gemma-only `_PromptShaper` hint (commit `18b8bbb`) and a companion test now covers the Gemma branch; (b) the tests exposed a genuine latent product bug — `local_answer_core/config.py::from_env` called `json.loads` without importing `json`, and the `NameError` was silently swallowed by a blanket `except Exception`, so the `current_state.json` model fallback never worked — fixed by adding the missing import.

---

## DEC-016 — 2026-08-06 — Accept any single reasoning marker for S09-GEM-007 in the STAGE_09/STAGE_11 scenario suites

**Context:** During STAGE_09/STAGE_11, scenario S09-GEM-007 required all three reasoning markers ["because", "since", "therefore"]. Gemma and Llama answers contained valid reasoning markers but not always all three, causing flakes.

**Decision:**

1. Accept any one of the listed markers in `tools/router_py/stage_09_gemma_scenario_suite.py` and `tools/router_py/stage_11_llama_scenario_suite.py`.

**Alternatives considered:**

- Keeping the all-three requirement — rejected because it tests marker vocabulary, not reasoning quality, and produced model-phrasing-dependent flakes.

**Consequences:** Both suites report 12/12 with 12/12 route and outcome parity; the parity criterion is weaker for this one scenario (recorded here for transparency).

---

## DEC-004 — 2026-07-30 — Add HMI injection-to-end tests via `RuntimeBridge` mocking

**Context:** The user observed that tests which call `request_pipeline.process()` directly often pass while the real HMI path (`RuntimeBridge` → `runtime_request.submit_request(surface="hmi")`) is broken. Static `fast` tests are necessary but not sufficient.

**Decision:**

1. Require `model-smoke` and `full-qualification` profiles to include HMI surface injection-to-output scenarios.
2. Implement static HMI tests by instantiating `RuntimeBridge` with a temporary namespace/state file, disabling background warmup, and monkey-patching `runtime_request.submit_request` to return a deterministic payload.
3. Keep the prototype test in `tools/router_py/test_hmi_end_to_end.py` so it can run with the system Python and pytest without requiring the UI venv.
4. For real-model HMI tests, submit at least one request through `RuntimeBridge` and assert on `CommandResult.payload` route/outcome/side effects rather than on raw model prose.

**Alternatives considered:**
- Calling `request_pipeline.process()` directly and adding HMI assertions later — rejected because it would not have caught the user's observed HMI-only failure.
- Running a full PySide6 HMI application under test — rejected because it is heavy, flaky, and unnecessary for the backend surface contract.
- Putting the test inside `ui-v10/app/services/` — rejected to avoid a venv dependency; the system Python already has `PySide6` and can import the bridge.

**Consequences:** The qualification programme now explicitly distinguishes "backend unit tests" from "HMI surface tests". Future regressions in state propagation, model selection, or payload wrapping will be caught before model-smoke runs.
