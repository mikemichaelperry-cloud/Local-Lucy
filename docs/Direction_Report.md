# Local Lucy V11 — Direction Report

**Date:** 2026-08-01  
**Scope:** `/home/mike/lucy-v11` only — v10 is untouched.

---

## 1. Where we were

At the start of this session Local Lucy V11 was in the middle of a major qualification push after two big changes:

1. **Large Python modules were split** (`main.py`, `request_pipeline.py`, `plan_to_pipeline_cli.py`) into smaller responsibility-focused modules. This was worthwhile — the code is now organised by function (classify, routing, execution, attribution, policy, escalation, voice, memory) and is easier to debug and test in isolation.
2. **New "truth-first" / escalation features were enabled.** These include:
   - automatic/web-triggered `AUGMENTED` and `EVIDENCE` routes,
   - untrusted DuckDuckGo fallback with explicit source labelling,
   - OpenAI / Kimi synthesis for verification of uncertain claims,
   - source attribution in answers,
   - streaming voice output via Kokoro.

There were also three active problems you reported:

- A `NameError` for `_get_relevant_persistent_facts` / `_get_active_model_from_state` after the split.
- Storing a location ("I live in Kibbutz Magal") did not make "restaurant in this area" use the stored location.
- A bare imperative like "Use DuckDuckGo search" in a web-thread was denied instead of inheriting the prior topic.

The deterministic test suite was already large (1,000+ tests in `tools/router_py`) but still had a small set of pre-existing failures.

---

## 2. Where we are now

### 2.1 Fixes completed today

| Issue | Status | Evidence |
|---|---|---|
| `NameError` after module split | Fixed & verified | Full `tools/router_py` regression passes except 3 unrelated pre-existing failures |
| Stored location not used for "this area" queries | Fixed & verified | `tools/router_py/test_location_memory.py` (3 passed) |
| "Use DuckDuckGo search" denied in web-thread | Fixed & verified | `tools/router_py/test_search_imperative_anaphora.py` (3 passed) |
| Voice-parity test isolation leak | Fixed & verified | `tools/router_py/test_voice_request_parity.py` (8 passed) |

The fixes are conservative and local:

- **Location facts:** `_extract_location_fact()` in `main.py` stores "I live in ..." as `category='location'`. `_load_location_facts_direct()` in `self_knowledge.py` reads the most recent location fact and `_is_location_aware_query()` detects phrases like "this area" / "near me". The prompt builder now injects the stored location for those queries.
- **Search imperatives:** `_maybe_resolve_search_imperative()` in `main.py` rewrites bare search-tool imperatives to the prior user query when the last exchange was a web/external route (`AUGMENTED`, `EVIDENCE`, `NEWS`, `WEATHER`, `TIME`, `FINANCE`). Capability questions are not matched.

### 2.2 Test state

- Targeted tests for the above fixes pass.
- Full `tools/router_py` regression completed:
  - **1100 passed, 3 failed, 7 skipped, 267 deselected, 188 subtests passed in 535.86s**
- The 3 failures are the same pre-existing defects:
  - `test_pipeline_integration_flags.py::test_trusted_sources_only_critical_preserves_parity_decision` (DEF-002)
  - `test_plan_to_pipeline_characterization.py::test_local_knowledge` (DEF-001)
  - `test_plan_to_pipeline_characterization.py::test_pet_food` (DEF-001)
- The location/anaphora changes did **not** introduce new failures.

### 2.3 Architecture documentation

- `Architecture.md` updated with new sections on location-fact extraction and search-imperative anaphora resolution.
- Qualification control files (`TEST_TODO.md`, `TEST_STATUS.json`, `DEFECT_REGISTER.md`) updated.

---

## 3. Assessment of the current direction

### 3.1 The large-file split was worthwhile

Yes. The split makes debugging faster because a failure usually points to one small module, and the test suite can target that module directly. The price was a short period of stale imports (the `NameError` above), but that is now resolved.

### 3.2 The staged qualification programme is sound but oversized

The programme you inherited from ChatGPT is thorough, but much of it is not yet implemented and some parts are now slightly out of date because of the new escalation/web features. The important parts for v11 right now are:

1. Static/import integrity (Stage 02).
2. Database/schema/memory integrity (Stages 03–04).
3. Deterministic router/capability controls (Stage 05).
4. HMI end-to-end injection-to-output tests (added to Stage 12).
5. Sequential model smoke tests (Stages 08–10) before trusting full shared suites.

The full 19-stage programme should be treated as a long-term goal, not a single-session deliverable.

### 3.3 Risks I see

| Risk | Severity | Why |
|---|---|---|
| Too many feature flags interact unpredictably | HIGH | `LUCY_AUTO_WEB_GENERAL_KNOWLEDGE`, `LUCY_TRUSTED_SOURCES_ONLY_CRITICAL`, `LUCY_SUGGEST_WEB_ESCALATION`, smart routing, model bypass, etc. can override each other in surprising ways. |
| Provider/trusted-source fallback drift | MEDIUM | DEF-002 shows parity/critical queries now resolve to `wikipedia` instead of `kimi`. This kind of drift lowers trust for high-stakes answers. |
| "Truth" verification is overconfident | MEDIUM | Cross-source agreement and OpenAI/Kimi verification help, but they do not guarantee truth. They can all agree on a common misconception. |
| Model-specific routing divergences | MEDIUM | Gemma and Llama behave differently on edge cases; routing thresholds tuned for one can mis-route the other. |
| End-to-end coverage gaps | HIGH | Many tests mock the backend. The HMI surface and voice path need real end-to-end validation, as you noted. |
| v11/v10 isolation | LOW so far | You have kept v10 untouched. I will continue to enforce that. |

### 3.4 Is the new direction better than the old?

Yes, with caveats.

- **Better:** Lucy can now answer a wider range of questions correctly by fetching live/trusted sources, and it labels untrusted sources explicitly.
- **Better:** The codebase is more modular and testable.
- **Riskier:** The routing logic is more complex, and the boundary between "local knowledge" and "must fetch" is now dynamic. That boundary needs careful threshold tuning and adversarial testing.

My honest rating, close to yours:

- Refactoring direction: **8/10**
- Automatic escalation concept: **6/10** (useful but needs stricter gates)
- Truthfulness/OpenAI verification design: **4/10** (helpful, not a guarantee)
- Overall risk characterization in the original plan: **too optimistic**

---

## 4. Where we should aim

### Short term (next few sessions)

1. **Close the 3 pre-existing failures** (DEF-001, DEF-002) or formally accept them before declaring a clean baseline.
2. **Finish the static/import stage** — verify no import-time side effects, no stale references, no circular imports after the split.
3. **Expand HMI end-to-end tests** so they exercise real routing decisions, not just mocked payloads.
4. **Run sequential Gemma/Llama smoke tests** on the fixed location and anaphora scenarios.
5. **Document every feature flag** and its interaction with routing — one source of truth in `config/capability_flags.yaml` + `Architecture.md`.

### Medium term

1. **Consolidate the escalation policy.** Decide:
   - When is web fallback automatic vs. suggested vs. disabled?
   - Which topics always require trusted evidence (medical, vet, legal, financial)?
   - How are untrusted sources labelled and when are they acceptable?
2. **Truth pipeline hardening.** Treat OpenAI/Kimi as fallible synthesis, not arbiters. Add source-provenance checks, date checks, and explicit confidence levels.
3. **Adversarial test corpus** beyond the current suite: typos, pronouns, ambiguous follow-ups, current-event vs. stable-knowledge boundaries, and deliberate misinformation attempts.
4. **Voice path:** ensure Kokoro streaming starts as early as possible and does not block on the full answer; verify CUDA usage and model-switch resource release.

### Long term

1. Keep the v11/v10 split absolute until v11 is qualified.
2. Make the qualification programme runnable from a single command (`fast`, then `model-smoke`, then `full-qualification`) with clear pass/fail gates.
3. Keep the architecture document and session handoffs alive so future work does not have to rediscover the routing/escalation rules.

---

## 5. My recommendation

Continue in small, gated stages. Do **not** add more sources or capabilities until:

- the 3 pre-existing failures are resolved or accepted,
- the static/import stage is green,
- Gemma and Llama smoke tests pass on the new location/anaphora scenarios,
- the HMI end-to-end path is exercised with real (not mocked) routing at least once per session.

The project is heading in a good direction, but the current risk is **complexity overload**. The best thing for accuracy and reliability now is to stabilise what exists, not to expand further.

---

## 6. Files touched this session (v11 only)

- `Architecture.md`
- `tools/router_py/main.py`
- `tools/router_py/local_answer_core/self_knowledge.py`
- `tools/router_py/local_answer_core/engine.py`
- `tools/router_py/test_location_memory.py`
- `tools/router_py/test_search_imperative_anaphora.py`
- `qualification/TEST_TODO.md`
- `qualification/TEST_STATUS.json`
- `qualification/DEFECT_REGISTER.md`
- `qualification/SESSION_HANDOFF.md`

Other files in the working tree (`START_LUCY.sh`, escalation, voice, etc.) were modified in earlier sessions and are not changed today.
