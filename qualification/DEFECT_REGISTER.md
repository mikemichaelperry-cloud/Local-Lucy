# Local Lucy V11 Qualification — Defect Register

## Severity legend

- `CRITICAL` — test modifies production memory; prompt words become URLs; no-network request performs HTTP; database migration corrupts data; route state leaks across users; failed request reported as successful; file access escapes allowed root.
- `HIGH` — significant boundary or safety failure, but contained.
- `MEDIUM` — incorrect route, misleading error, or missing telemetry.
- `LOW` — formatting, wording, or minor performance issue.
- `OBSERVATION` — not a defect, but worth tracking.

---

## Active defects

No active defects. DEF-001 and DEF-002 were closed in Work Package 1 as test-isolation issues, not production defects.

---

## Resolved / closed defects

### [DEF-001] CLOSED — Characterization snapshot drift in `test_plan_to_pipeline_characterization.py`

**Severity:** MEDIUM

**Stage discovered:** STAGE_01 (harness verification)

**Affected subsystem:** `tools/router_py/test_plan_to_pipeline_characterization.py`

**Root cause:** Test isolation leak. An earlier test in the full suite loads `tools/router_py/main.py`, whose `ensure_control_env()` writes `LUCY_AUGMENTATION_POLICY=disabled` and `LUCY_AUGMENTED_PROVIDER=wikipedia` into `os.environ`. The CLI subprocess in the characterization test inherited these values, causing `winning_signal` to default to `legacy_policy` and removing `intent_family:local_answer` from reason codes. The snapshots themselves were correct; the production code was correct.

**Resolution:** Modified `test_plan_to_pipeline_characterization.py::_run()` to invoke the CLI with a controlled subprocess environment (`LUCY_AUGMENTATION_POLICY=fallback_only`, no `LUCY_AUGMENTED_PROVIDER`).

**Reproduction test (should now pass):**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_plan_to_pipeline_characterization.py -v
```

**Retest status:** PASSED (2026-08-01).

---

### [DEF-002] CLOSED — Trusted-source parity test provider mismatch in `test_pipeline_integration_flags.py`

**Severity:** MEDIUM

**Stage discovered:** STAGE_01 (harness verification)

**Affected subsystem:** `tools/router_py/test_pipeline_integration_flags.py`

**Root cause:** Same parent-process pollution as DEF-001. `LUCY_AUGMENTED_PROVIDER=wikipedia` caused `provider_resolver.resolve_provider()` to return `wikipedia` (env-var precedence) instead of the query-type default `kimi` for a safety/general classification. Production provider resolution is working as designed.

**Resolution:** Modified `test_pipeline_integration_flags.py::_set_flags()` to delete `LUCY_AUGMENTED_PROVIDER` and `LUCY_AUGMENTATION_POLICY` so the suite evaluates capability-flag behavior against clean provider defaults.

**Reproduction test (should now pass):**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_pipeline_integration_flags.py::test_trusted_sources_only_critical_preserves_parity_decision -v
```

**Retest status:** PASSED (2026-08-01).

---

## Resolved / closed defects

### [DEF-003] CLOSED — `NameError: name '_get_relevant_persistent_facts' is not defined` after module split

**Severity:** HIGH

**Stage discovered:** STAGE_01 (runtime smoke)

**Affected subsystem:** `tools/router_py/local_answer_core/engine.py`, `tools/router_py/local_answer_core/utils.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 tools/router_py/main.py --question "Where do I live?"
```

**Expected behaviour:** Local Lucy loads persistent facts and builds the prompt without an unhandled exception.

**Actual behaviour (before fix):** Traceback reported `NameError: name '_get_relevant_persistent_facts' is not defined` and a similar error for `_get_active_model_from_state` in the Ollama warmup thread.

**First known failing stage:** STAGE_01

**Relevant trace:** Terminal output from `tools/router_py/main.py`; missing imports after large-file split.

**Production impact:** Local Lucy V11 was non-functional for any query that touched persistent facts or model warmup.

**Workaround:** None.

**Resolution:** Missing functions were restored/aliased in the appropriate modules. Full `tools/router_py` regression now passes the affected tests.

**Retest status:** PASSED — full `tools/router_py` regression (2026-07-30).

---

### [DEF-004] CLOSED — Stored user location did not override timezone-derived default

**Severity:** MEDIUM

**Stage discovered:** STAGE_04 (persistent memory)

**Affected subsystem:** `tools/router_py/local_answer_core/self_knowledge.py`, `tools/router_py/local_answer_core/engine.py`, `tools/router_py/main.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_location_memory.py -v
```

**Expected behaviour:** After the user says "I live in Kibbutz Magal", a follow-up "restaurant in this area" should inject the stored location fact and route correctly.

**Actual behaviour (before fix):** The prompt builder only loaded personal/family facts and did not recognize "this area" as a location-aware query; the timezone default was used instead of the stored location.

**First known failing stage:** STAGE_04

**Relevant trace:** `tools/router_py/test_location_memory.py`

**Production impact:** Location-aware follow-ups gave wrong or generic answers.

**Workaround:** None.

**Resolution:**

- Added `_load_location_facts_direct()` in `self_knowledge.py` to read the most recent `category='location'` fact from SQLite.
- Added `_is_location_aware_query()` heuristic for phrases like "this area", "near me", "around here".
- In `engine.py::_build_prompt()`, location-aware queries now load the stored location fact when no personal facts are present.
- In `main.py`, `_extract_location_fact()` persists "I live in ..." statements as `category='location'` facts.

**Retest status:** PASSED — `tools/router_py/test_location_memory.py` (3 passed, 2026-07-30).

---

### [DEF-005] CLOSED — Bare search-tool imperative denied browsing instead of inheriting prior web topic

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (deterministic routing)

**Affected subsystem:** `tools/router_py/main.py`, `tools/router_py/feedback_buffer.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_search_imperative_anaphora.py -v
```

**Expected behaviour:** After an AUGMENTED/EVIDENCE/NEWS/WEATHER/TIME/FINANCE exchange, "Use DuckDuckGo search" should resolve to the prior user query and route to the web fallback on the same topic.

**Actual behaviour (before fix):** The bare imperative routed `LOCAL` and denied the capability, because the router had no topic to search.

**First known failing stage:** STAGE_05

**Relevant trace:** `tools/router_py/test_search_imperative_anaphora.py`

**Production impact:** User could not ask Lucy to "search again" or "use DuckDuckGo" in a web-thread without restating the topic.

**Workaround:** Restate the topic explicitly.

**Resolution:**

- Added `_SEARCH_TOOL_IMPERATIVE_PATTERN` and `_maybe_resolve_search_imperative()` in `main.py`.
- The resolver checks the last feedback-buffer entry; if its route was web/external and the prior query is not itself a search imperative, the current query is replaced by the prior query.
- Capability questions ("Can you search the web?") are not matched and still route `LOCAL`.

**Retest status:** PASSED — `tools/router_py/test_search_imperative_anaphora.py` (3 passed, 2026-07-30).

---

### [DEF-006] CLOSED — Restaurant/dining queries misrouted to TIME or WEATHER

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (HMI live use)

**Affected subsystem:** `tools/router_py/core/intent_classifier.py` (embedding router), `tools/router_py/policy_router/gates.py`, `tools/router_py/policy_router/router.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_hmi_real_routing.py tools/router_py/test_policy_router.py::TestRestaurantDiningGate -v
```

**Expected behaviour:**

- "I am looking for a good restaurant open today near kibbutz Magal" should route to `AUGMENTED` for current, location-aware information.
- "Search for restaurants in my area that are open today" should route to `AUGMENTED`, not `TIME`.

**Actual behaviour (before fix):**

- "Search for restaurants in my area that are open today" routed `TIME` and returned the current time.
- "I am looking for a good restaurant open today near kibbutz Magal" routed `WEATHER` and returned a weather error.

**First known failing stage:** STAGE_05

**Relevant trace:** Live HMI logs (2026-08-01T07:43–07:46Z); `tools/router_py/test_hmi_real_routing.py`.

**Production impact:** Location-aware restaurant/dining questions gave irrelevant time/weather answers, making the location-memory and anaphora fixes invisible to the user.

**Workaround:** Prefix the query with `augmented:` to force the correct route.

**Resolution:**

- Added deterministic `gate_restaurant_dining` in `policy_router/gates.py`.
- The gate matches restaurant/dining keywords combined with a location or time qualifier, and runs before the time/weather gates.
- It routes to `AUGMENTED` (provider `wikipedia`) so the query is treated as current factual lookup.
- Added HMI-level regression tests in `test_hmi_real_routing.py` that exercise the real classifier and verify the route.

**Retest status:** PASSED — `tools/router_py/test_hmi_real_routing.py` (4 passed, 2026-08-01).

---

### [DEF-007] CLOSED — HMI real-routing tests failed in full regression due to environment leakage

**Severity:** LOW

**Stage discovered:** STAGE_01 (harness verification)

**Affected subsystem:** `tools/router_py/test_hmi_real_routing.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py -v --tb=short
```

**Expected behaviour:** `tools/router_py/test_hmi_real_routing.py` passes both in isolation and in the full suite.

**Actual behaviour (before fix):** The four HMI real-routing tests failed in the full suite with route `LOCAL`/reason `local_sufficient` because `tools/router_py/test_hmi_end_to_end.py` replaced `sys.modules["runtime_request"]` with a fake module and never restored it. The HMI real-routing tests then imported the fake `submit_request`, which returns a hardcoded `LOCAL` payload regardless of the actual router. The fixture also initially failed to set `LUCY_EVIDENCE_ENABLED=1`, which would have hidden the fake-module leak when running the tests in isolation.

**First known failing stage:** STAGE_01

**Relevant trace:** Full regression log; `tools/router_py/test_hmi_real_routing.py::temp_namespace`

**Production impact:** None. The production routing fix was correct; this was a test-fixture isolation gap.

**Workaround:** Run `test_hmi_real_routing.py` in isolation.

**Resolution:**

1. Use `monkeypatch.setitem(sys.modules, "runtime_request", fake_runtime_request)` in `test_hmi_end_to_end.py` so the fake module is removed and the real module restored after each test.
2. Set both `LUCY_EVIDENCE_ENABLED=1` and `LUCY_ENABLE_INTERNET=1` in the `test_hmi_real_routing.py` fixture. Outbound HTTP is still blocked by the `captured_urls` monkeypatch, so no real network traffic occurs.

**Retest status:** PASSED — `tools/router_py/test_hmi_real_routing.py` (4 passed, 2026-08-01).

---

## Template

### [DEF-008] CLOSED — Evidence-request guard ignored local-only restrictions and arithmetic

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (policy-router unit tests)

**Affected subsystem:** `tools/router_py/policy_router/gates.py`, `tools/router_py/request_constraints.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_policy_router.py::TestEvidenceRequestGate -v
```

**Expected behaviour:**

- "What is 2+2? Do not search the web." should stay `LOCAL`.
- "Verify this using only currently available information." should stay `LOCAL`.
- "What is 2+2? Search the web." should stay `LOCAL` (arithmetic is a local capability).

**Actual behaviour (before fix):** All three were forced to `AUGMENTED` by `gate_evidence_request` because the gate only looked for evidence-imperative phrases.

**Resolution:**

- `gate_evidence_request` now checks `extract_request_constraints(query)` for `network=False` or `local_only=True`.
- It also returns `None` when the query contains arithmetic operators, letting the existing math exclusion keep the query local.
- `request_constraints.py` was updated so that `do not search the web` is recognised as a network denial.

**Retest status:** PASSED — `tools/router_py/test_policy_router.py::TestEvidenceRequestGate` (2026-08-01).

---

### [DEF-009] CLOSED — News guard overrode restaurant/dining signal

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (policy-router unit tests)

**Affected subsystem:** `tools/router_py/policy_router/gates.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates::test_news_with_restaurant_signal_yields_to_restaurant_dining -v
```

**Expected behaviour:** "News about the best pizza place near me" should route to `AUGMENTED` as a restaurant lookup, not `NEWS`.

**Actual behaviour (before fix):** The query routed `NEWS` because `gate_news` matched the word "news" before the restaurant signal could fire.

**Resolution:** Broadened `gate_restaurant_dining` to catch common food-specific establishments (`pizza place`, `burger joint`, `sushi spot`, etc.) so the restaurant gate wins.

**Retest status:** PASSED — `tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates` (2026-08-01).

---

### [DEF-010] CLOSED — Weather guard overrode travel-planning queries

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (policy-router unit tests)

**Affected subsystem:** `tools/router_py/policy_router/gates.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates::test_travel_plan_with_weather_yields_to_travel_tourism -v
```

**Expected behaviour:** "Plan a trip to Paris and tell me the weather" should route to `AUGMENTED` as travel/tourism, not `WEATHER`.

**Actual behaviour (before fix):** The query routed `WEATHER` because `gate_weather` fired before the travel/tourism gate.

**Resolution:** `gate_weather` now returns `None` when `_TRAVEL_PLACE_RE` matches, letting `gate_travel_tourism` route the query to `AUGMENTED`.

**Retest status:** PASSED — `tools/router_py/test_policy_router.py::TestTimeWeatherNewsGates` (2026-08-01).

---

### [DEF-011] CLOSED — Residence/location statements misrouted to WEATHER

**Severity:** MEDIUM

**Stage discovered:** STAGE_05 (HMI smoke test)

**Affected subsystem:** `tools/router_py/policy_router/gates.py`, `tools/router_py/policy_router/router.py`

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 qualification/hmi_routing_smoke.py
```

**Expected behaviour:**

- "Actually I live in Kibbutz Magal in Israel." should route `LOCAL`.
- "I no longer live in Tel Aviv." should route `LOCAL`.
- "The article says, 'I live in London.'" should route `LOCAL`.

**Actual behaviour (before fix):** All three routed `WEATHER` because the embedding router's k-NN fallback associated place names with weather queries.

**Resolution:** Added `gate_residence_statement` before the weather gate. It matches standalone residence/location statements (including negated, quoted, other-person, and hypothetical forms) and routes them `LOCAL`, while preserving genuine weather queries that mention the user's location.

**Retest status:** PASSED — `qualification/hmi_routing_smoke.py` (24/24, 2026-08-01).

---

### [DEF-012] CLOSED — Generic "search again" anaphora not resolved to prior web topic

**Severity:** MEDIUM

**Stage discovered:** Final requalification holdout investigation

**Affected subsystem:** `tools/router_py/main.py` (`_SEARCH_TOOL_IMPERATIVE_PATTERN`)

**Reproduction test:**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_search_imperative_anaphora.py::test_search_again_resolves_to_prior_web_topic -v
```

**Expected behaviour:** After an `AUGMENTED` exchange, "Can you search again?" should inherit the prior web topic and route `AUGMENTED`.

**Actual behaviour (before fix):** The query routed `LOCAL` because the search-imperative resolver did not recognise "search again".

**Production impact:** Users could not ask Lucy to search again using natural follow-up phrasing.

**Resolution:** Extended `_SEARCH_TOOL_IMPERATIVE_PATTERN` to match `(?:can you\s+)?search\s+(?:again|once\s+more)` with optional trailing "please". Added regression tests.

**Retest status:** PASSED — `tools/router_py/test_search_imperative_anaphora.py` (6 passed, 2026-08-06).

---

## Template

```text
[DEF-NNN] STATUS — Title
Severity: CRITICAL / HIGH / MEDIUM / LOW / OBSERVATION
Stage discovered: STAGE_XX
Affected subsystem:
Reproduction test:
Expected behaviour:
Actual behaviour:
First known failing stage:
Relevant trace:
Production impact:
Workaround:
Retest status:
```
