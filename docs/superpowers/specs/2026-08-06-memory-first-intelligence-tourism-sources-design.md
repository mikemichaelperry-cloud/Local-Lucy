# Local Lucy V11 — Memory-First Intelligence & Tourism Sources Design

**Date:** 2026-08-06  
**Project:** Local Lucy V11 (`/home/mike/lucy-v11`)  
**Status:** Design spec awaiting approval  
**Prepared for:** ChatGPT / future Kimi sessions / user review  

---

## 1. Objective

Make Local Lucy V11 the most accurate, coherent, and useful local AI assistant it can be by fixing the three biggest user-visible gaps observed in production logs:

1. **Memory/continuity failures** — truncated stories, ignored prior answers, “repeat this,” and model-switch context loss.
2. **Travel/tourism dead-ends** — queries like “recommend places to visit in Israel” are blocked by trusted-sources-only policy with no usable source.
3. **Cross-model inconsistency** — Gemma and Llama behave differently on the same memory and routing tasks.

This design treats the three gaps as one integrated upgrade: a **memory-first conversational core** with a **tourism source layer** on top, verified for **both models**.

---

## 2. Success Criteria

| # | Criterion | How verified |
|---|---|---|
| 1 | Every request reads the full conversation database, not just the last N turns. | Unit test + HMI scenario: 16-turn conversation, query references turn 3. |
| 2 | “Continue the story,” “repeat that,” and “what did I say earlier” work for both Gemma and Llama. | Shared scenario suite on both models. |
| 3 | Model switch Gemma → Llama → Gemma preserves conversation context and answers consistently. | `stage_13_model_switch.py` extended with memory continuity case. |
| 4 | Travel/tourism queries for Israel return useful, sourced answers. | Live HMI test + `stage_17_live_network.py` travel cases. |
| 5 | Travel/tourism generalises to arbitrary countries via Wikivoyage. | Unit tests for destination extraction and fetch mocking. |
| 6 | No dual-model residency at any point. | Every model stage asserts `loaded_models_after` has ≤1 Local Lucy model. |
| 7 | Full deterministic regression still passes. | `pytest tools/router_py` and memory-service test suite. |
| 8 | Reports are updated as work progresses. | `qualification/TEST_STATUS.json`, `TEST_TODO.md`, `SESSION_HANDOFF.md`, completion report. |

---

## 3. Current Pain Points (from logs)

| Symptom | Root cause | Design fix |
|---|---|---|
| Gemma truncated the 500-word dog story; “continue” failed. | Model context/budget handling + lack of robust continuation recall. | §4.2 continuation budget splitting + §4.3 re-generation prompt. |
| “Read my last answer please” → “I don’t have access to read external files.” | Explicit recall worked but model ignored memory in prompt. | §4.4 memory-priority prompt instruction + §4.5 model-specific prompt tuning. |
| “Repeat this story” → “I don’t see a story.” | Prior answer not stored/retrieved correctly after truncation. | §4.1 store assistant answers verbatim even when truncated by token budget. |
| Model mismatch / both models loaded in HMI during tests. | Test/stage orchestration not enforcing sequential unload. | §6.2 strict sequential model contract + §6.3 HMI surface assertions. |
| “Recommend places to visit in Israel” → blocked by trusted-sources-only. | No usable trusted travel source. | §5.1 Israel Ministry of Tourism + §5.2 Wikivoyage generalisation. |
| Llama vs Gemma answer quality diverges on memory tasks. | Same prompt assembly, but model-specific headroom/template differences not exploited. | §4.5 model-aware prompt shaping. |

---

## 4. Component 1 — Memory-First Conversational Core

### 4.1 Store every assistant turn

**Current state:** `tools/router_py/main.py:_persist_memory_turn()` stores the assistant text returned to the user. If the local model truncates mid-sentence, the truncated text is what gets stored.

**Change:**
- Continue storing the user-visible text (this is what the user saw).
- Also store a `full_text` column when the model returns a `finish_reason` of `length` (truncated). The `full_text` is the untruncated output from Ollama when available, or a marker that the turn was truncated.
- On “continue” / “repeat” / “tell me more,” prefer `full_text` if present, else reconstruct from context.

**Files:**
- `tools/memory/memory_service.py` — schema + `store_turn`.
- `tools/router_py/local_answer_core/engine.py` — return truncation signal.
- `tools/router_py/main.py` — persist `full_text`.

### 4.2 Split memory budget for long outputs

**Current state:** `LUCY_MEMORY_MAX_CHARS` default 2000, execution engine uses 2400. This includes all recent turns + semantic turns + persistent facts.

**Change:**
- Reserve a separate **continuation budget** of 800 chars for the most recent assistant turn when the prior turn was truncated or when the query is a continuation.
- The remaining budget still carries conversation history and facts.
- This ensures “continue the story” has the truncated text available plus room to generate the next segment.

**Configuration:**
- `LUCY_MEMORY_CONTINUATION_RESERVE_CHARS=800` (new env var).

### 4.3 Continuation re-generation prompt

When the user asks “continue,” “go on,” “finish the story,” or similar:
1. Load the prior assistant turn.
2. If it was truncated, append a clear instruction:
   ```
   The previous answer was cut off. Continue from exactly where it left off.
   Do not repeat what has already been said.
   ```
3. If the prior turn was complete, treat the request as “elaborate” instead.

This logic lives in `tools/router_py/local_answer_core/engine.py:_build_prompt`.

### 4.4 Memory-priority prompt instruction

**Current state:** Memory is injected with “Use the facts below to answer follow-up questions.” Models sometimes ignore it.

**Change:**
- Strengthen the instruction:
  ```
  The conversation history below is authoritative. Use it to answer the user's question.
  If the user refers to something earlier, look at the history first.
  ```
- Place memory closer to the final user message (after system persona, before the current query).
- A/B test placement with a small prompt-parity test between Gemma and Llama.

### 4.5 Model-aware prompt shaping

**Current state:** Both Llama and Gemma use the same assembled prompt; only the Ollama Modelfile differs.

**Change:**
- Add a thin `PromptShaper` in `tools/router_py/local_answer_core/engine.py` that adjusts:
  - Instruction repetition count (Gemma benefits from slightly more explicit instructions based on observed behaviour).
  - Memory preamble wording.
  - Continuation marker format.
- Initial shaping is rule-based per model family (`llama`, `gemma`), not learned.

### 4.6 Cross-model memory parity

**Current state:** Scenario suites for Gemma and Llama exist but do not explicitly compare memory behaviour.

**Change:**
- Extend `stage_09_gemma_scenario_suite.py` and `stage_11_llama_scenario_suite.py` with shared memory scenarios:
  - Story continuation
  - Explicit recall
  - Correction/supersession
  - Model identity recall
- Require outcome parity: the answer content must convey the same factual points (not word-for-word).

---

## 5. Component 2 — Tourism & Travel Sources

### 5.1 Israel Ministry of Tourism integration

**Current state:** `tools/unverified_context_trusted.py` has a hardcoded Go Israel endpoint, but it is brittle and the allowlist is minimal.

**Change:**
- Add a robust Israel tourism fetcher:
  - Primary: `https://israel.travel` (HTML extract with structured data / OpenGraph).
  - Fallback: Ministry of Tourism REST/API if a stable endpoint is documented.
  - Fallback 2: Wikivoyage Israel page.
- Cache results for 24 hours in `~/.local/share/local-lucy-v11/state/travel_cache.json` keyed by destination.
- Add destination normalisation: “Israel,” “Eretz,” “Tel Aviv area,” “Jerusalem,” etc.

**Files:**
- `tools/unverified_context_trusted.py` — `_format_travel_response`, `_try_direct_fetch`.
- `config/trust/generated/travel_runtime.txt` — add `israel.travel`, `goisrael.com`, `wikivoyage.org`.

### 5.2 Generalise to other countries via Wikivoyage

**Change:**
- Extend `_TRAVEL_DESTINATION_MAP` with major countries and cities.
- Use Wikivoyage REST API `https://en.wikivoyage.org/api/rest_v1/page/summary/{page}` as the primary general source.
- Add per-country tourism ministry allowlist entries where stable English sites exist (e.g., `visitbritain.com`, `france.fr`, `japan.travel`).
- For unknown destinations, fall back to a safe response asking the user to specify the country/region.

### 5.3 Routing changes

**Current state:** Travel queries are forced to `EVIDENCE/trusted` and blocked if no trusted source works.

**Change:**
- Keep the trusted-sources-only policy for travel advisory/safety content.
- For general tourism recommendations, allow `AUGMENTED` with `provider="trusted"` when a trusted tourism source succeeds.
- If trusted source fails, return a clear message explaining that trusted travel sources are unavailable, rather than a generic block.
- Never silently fall back to open web search for travel during this work.

### 5.4 Destination extraction

**Change:**
- Improve `_extract_travel_destination()` to handle:
  - “places to visit in Israel”
  - “what should I see in Jerusalem?”
  - “recommendations for a trip to Japan”
- Use a small rule-based extractor plus the existing `extract_place_tail` helper.

---

## 6. Component 3 — Verification & Cross-Model Guarantees

### 6.1 New and extended tests

| Test | Purpose |
|---|---|
| `tools/router_py/test_memory_continuation.py` | Story truncation, continuation, repeat, full-text storage. |
| `tools/router_py/test_travel_israel.py` | Israel destination routing + trusted fetch (mocked + live). |
| `tools/router_py/test_travel_general.py` | Wikivoyage fetch and destination extraction for multiple countries. |
| Extended `stage_09_gemma_scenario_suite.py` | Memory scenarios on Gemma. |
| Extended `stage_11_llama_scenario_suite.py` | Memory scenarios on Llama + parity assertions. |
| Extended `stage_13_model_switch.py` | Memory continuity across model switch. |
| Extended `stage_17_live_network.py` | Live travel queries. |

### 6.2 Strict sequential model contract

**Current state:** Stage scripts check `loaded_models_after`.

**Change:**
- Add `loaded_models_before` check at the start of every model stage.
- If more than one Local Lucy model is resident, fail fast with a clear error.
- Add a helper `_assert_single_model_residency()` in a new `tools/router_py/model_residency.py` module used by all stage scripts.

### 6.3 HMI surface assertions

**Current state:** HMI tests exist but do not assert model residency.

**Change:**
- Add a residency assertion to `tools/router_py/test_hmi_real_routing.py` after each request that uses a local model.
- Ensure the HMI path also respects the sequential model contract.

---

## 7. Integration with Existing Routing

| Existing mechanism | How this design uses it |
|---|---|
| `LUCY_MEMORY_RECENT_TURN_LIMIT=12` | Keep; add full-text storage on top. |
| `LUCY_MEMORY_MAX_INJECTED_TURNS=8` | Keep; use for older-turn recall. |
| `_memory_routing_gate` | Keep; ensure memory follow-ups route LOCAL even after AUGMENTED/EVIDENCE routes. |
| `apply_critical_source_policy` | Keep trusted-sources-only for travel advisory; allow tourism recommendations through trusted provider. |
| `stage_19_clean_run.py` | Extend with new memory and travel stages; keep sequential model execution. |

---

## 8. Phased Implementation Outline

### Phase 1 — Memory core (foundational)
1. Add `full_text` storage for truncated assistant turns.
2. Implement continuation budget splitting.
3. Strengthen memory-priority prompt instruction.
4. Add continuation re-generation prompt.
5. Run memory tests and Gemma/Llama scenario parity.

### Phase 2 — Tourism sources
1. Improve Israel destination extraction and fetch.
2. Add Wikivoyage general-country fetch.
3. Update travel allowlist and routing.
4. Add travel unit tests (mocked + live).

### Phase 3 — Cross-model verification
1. Add residency assertions to all model stages and HMI tests.
2. Extend scenario suites with memory continuity cases.
3. Extend model switch stage with memory continuity.
4. Run full clean-run qualification.

### Phase 4 — Reporting
1. Update `qualification/TEST_STATUS.json`, `TEST_TODO.md`, `SESSION_HANDOFF.md`.
2. Write progress completion report.
3. Copy deliverables to desktop and archive stale versions.

---

## 9. Testing Strategy

- **Unit tests first:** every new function gets a unit test with mocked external calls.
- **Integration tests second:** SQLite + local model stubs.
- **Live tests last:** only in stage scripts with `LUCY_LIVE_TESTS=1` or explicit stage invocation.
- **Regression gates:** full `pytest tools/router_py` and memory-service suite must pass before each phase merges.
- **No dual-residency gate:** every model-touching test asserts single-model residency.

---

## 10. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Larger memory context hurts local model latency. | Keep character budget; only reserve continuation budget when needed. Measure latency in stage scripts. |
| Wikivoyage rate-limiting or API changes. | Cache results; implement graceful fallback to allowlisted ministry sites; unit-test with mocked responses. |
| Gemma/Llama prompt changes break existing scenarios. | Add prompt-parity test; only adjust wording, not structure. |
| Travel routing still misclassifies as weather/time. | Re-run weather/time boundary tests after routing changes. |
| Dual-model residency regression. | Fail-fast residency assertions in every model stage and HMI test. |
| Token/token budget blowout in reports. | Update reports incrementally; final report only after all phases pass. |

---

## 11. Deliverables

- Design spec: `docs/superpowers/specs/2026-08-06-memory-first-intelligence-tourism-sources-design.md`
- Implementation plan: `docs/superpowers/specs/2026-08-06-memory-first-intelligence-tourism-sources-plan.md`
- Code changes under `tools/memory/`, `tools/router_py/`, `tools/unverified_context_trusted.py`, `config/trust/generated/`
- Tests under `tools/router_py/` and `tools/tests/`
- Updated qualification status and reports
- Desktop copies of reports

---

## 12. Open Questions for User

1. Should the Israel Ministry of Tourism fetcher prefer the official `israel.travel` site, or do you have a different preferred source?
2. Is it acceptable to cache travel results for 24 hours, or do you want a shorter/longer TTL?
3. For general-country travel, should Wikivoyage be the primary source, or do you want to maintain a per-country ministry allowlist as the primary?

If you approve this design, the next step is to write the detailed implementation plan and begin Phase 1.
