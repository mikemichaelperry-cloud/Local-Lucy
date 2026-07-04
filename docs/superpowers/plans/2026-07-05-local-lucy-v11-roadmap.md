# Local Lucy v11 Roadmap — Revised 2026-07-04

> Next-session implementation plan for moving from v10 to a leaner, faster, more accurate Local Lucy v11.
> This revision incorporates the review feedback from 2026-07-04.

## Goal

Transform Local Lucy v10 into v11: an **English-only**, autonomous assistant that picks the right mode, model, and source without user-facing toggles, returns factual answers with verified context, and runs efficiently on the current RTX 3060 12 GB / 31 GB RAM hardware.

## Hardware Constraints

- GPU: NVIDIA RTX 3060 12 GB
- RAM: 31 GB system RAM
- Ollama runs locally; VRAM is the bottleneck
- Current working models:
  - `local-lucy` / `local-lucy-fast`: qwen3:14b (~9 GB VRAM, 2048 ctx)
  - `local-lucy-llama31`: llama3.1:8b (8192 ctx)
  - `local-lucy-mistral`: mistral-nemo 12B
- One model loaded at a time; switching models incurs unload/load latency
- Voice: Whisper STT + Kokoro TTS. Current configuration must be confirmed before v11 implementation: earlier docs disagreed on whether Kokoro runs on CPU or CUDA. On RTX 3060 12 GB, a 9 GB Qwen model plus CUDA TTS may cause VRAM contention. Document one source of truth and measure GPU memory before changing defaults.

## v11 Design Principles

1. **English-only runtime.** Hebrew and Racheli persona work is removed from Local Lucy and treated as a separate system.
2. **Zero default switches.** The normal HMI should not require the user to pick mode, model, provider, or persona. The system decides.
3. **External LLMs synthesize, they do not verify.** Wikipedia, official APIs, and trusted domains are evidence sources. OpenAI and Kimi may synthesize evidence, but their outputs are not evidence themselves.
4. **Context is guilty until proven innocent.** Every injected source must pass entity, intent, temporal, lexical, provenance, and relevance checks before it enters the LLM prompt.
5. **Measure before hiding controls.** Automatic model selection runs in shadow mode with full logging before manual selectors are removed from the default view.
6. **Canonical policy, not one brittle prompt.** One shared Lucy policy plus route-specific instructions plus thin per-model adapters.
7. **Local-first routing.** Stable basic facts, recipes, opinion, coding, and creative writing stay LOCAL unless the user asks for verification or live data.
8. **Measure before optimizing.** Every change must be covered by the routing barrage and HMI inspection; latency must be measured before/after.

---

## Phase 0: Correct the Roadmap and Scope

**Why:** The previous plan still carried Hebrew and Racheli assumptions and treated OpenAI/Kimi as evidence sources.

**Actions:**
- [ ] Remove `HEBREW_QUERY` routing and Hebrew-specific provider logic from Local Lucy.
- [ ] Archive or quarantine the Racheli persona Modelfile from the primary runtime.
- [ ] Document that Hebrew/Racheli is a separate service.
- [ ] Change augmented-provider chain description from "Wikipedia → OpenAI → Kimi" to "Wikipedia evidence → optional synthesis by OpenAI/Kimi if evidence exists."
- [ ] Fix system-prompt contradictions: replace "never hedge/disclaim" + "facts only" with "answer directly, distinguish facts/inferences/uncertainty, never invent."

**Success criteria:**
- No `HEBREW_QUERY` or Racheli-specific code is reachable from, loaded by, or maintained as part of the primary Local Lucy runtime.
- Shared utilities or archived modules may remain if they are isolated and do not add runtime complexity. The aim is separation, not deletion for its own sake.
- Augmented route documentation clearly separates evidence sources from synthesis providers.

---

## Phase 1: Establish Measurements

**Why:** You cannot improve what you do not measure. The 81% accuracy number is too coarse.

**Actions:**
- [ ] Freeze a real-query routing corpus for validation (not the training set, not synthetic adversarial prompts).
- [ ] Compute and log a confusion matrix, per-route precision/recall, and high-stakes false negatives.
- [ ] Establish per-route latency baselines: LOCAL, AUGMENTED, NEWS, TIME, WEATHER, FINANCE, EVIDENCE.
- [ ] Build a model-selection comparison set and a context-contamination test set (Japan/China tourism, similar medications, etc.).
- [ ] Add a `metrics/` module that records router decisions, model selections, context accept/reject, and provider outcomes.

**Files:**
- `tools/router_py/metrics.py` (new)
- `tools/router_py/barrage_test.py` or `run_routing_barrage.py`
- `tools/router_py/evaluate_router.py` (new or extend existing)

**Success criteria:**
- Running `python3 tools/router_py/evaluate_router.py` prints confusion matrix, per-route recall, and latency baseline.
- Validation corpus is saved to `data/evaluation/routing_validation_corpus.jsonl` and committed.

---

## Phase 2: Context Provenance and Guard

**Why:** The most embarrassing failures come from injecting irrelevant context.

**Files:**
- `tools/router_py/context_guard.py` (new)
- `tools/router_py/classify.py`
- `tools/router_py/local_answer.py`
- `tools/router_py/providers/`
- `tools/router_py/context_builder.py` (start extracting from `execution_engine.py`)

**Actions:**
- [ ] Create `ContextGuard` with scoring methods:
  - `entity_match(query, context)` — NER/keyword overlap for people, places, products, medications.
  - `intent_compatible(query_route, context_route)` — e.g., news context should not satisfy a personal-memory query.
  - `temporal_compatible(query, context)` — current queries need fresh material; historical queries accept older context.
  - `lexical_overlap(query, context)` — simple word/phrase overlap as a guard against similar-but-wrong entities.
  - `embedding_score(query, context)` — MiniLM similarity, used as one signal, not the judge.
  - `provenance(context)` — label as memory, wikipedia, news, official_api, or generated_text.
  - `answerability(query, context)` — does the context actually contain information capable of answering the question?
- [ ] Set combined thresholds per source type:
  - Memory turn: entity or lexical signal + embedding ≥ 0.30
  - Wikipedia/news snippet: entity or lexical signal + embedding ≥ 0.45 + temporal check
  - Generated text (OpenAI/Kimi): never injected as evidence; only used as synthesis if evidence is present
- [ ] Add strict fallback rules when evidence retrieval fails:
  - Stable ordinary fact → LOCAL answer allowed, labelled as unverified if appropriate.
  - Current fact/news/price/weather/time → do not silently answer from local knowledge; ask for clarification or report unavailability.
  - Medical/veterinary/legal high-stakes → do not replace failed evidence with confident local generation.
  - Opinion or analysis → LOCAL reasoning acceptable, but distinguish from verified fact.
- [ ] Integrate the guard into `classify.py` before the final `RoutingDecision`.
- [ ] Update prompt instruction: "Use the following context only if it directly answers the current query; otherwise answer from your own knowledge."
- [ ] Begin extracting context-building logic from `execution_engine.py` into `context_builder.py`.
- [ ] Log context-guard telemetry:
  - accepted context,
  - rejected context,
  - unused accepted context (passed guard but answer did not rely on it),
  - answer citation coverage (major factual claims supported by evidence),
  - context disagreement (two accepted sources contradict each other),
  - entity collision (similar names but different people, places, products).

**Success criteria:**
- Japan tourism query no longer cites China tourism.
- Context-contamination tests pass.
- Failed evidence retrieval follows route-dependent fallback rules.
- Barrage and HMI tests pass.

---

## Phase 3: Automatic Model Selection in Shadow Mode

**Why:** The user wants the model chosen automatically, but hiding mistakes too early is dangerous.

**Files:**
- `tools/router_py/classify.py`
- `tools/router_py/policy_router.py`
- `ui-v10/app/services/runtime_bridge.py`
- `ui-v10/app/panels/control_panel.py`
- `tools/router_py/metrics.py`

**Actions:**
- [ ] Define a draft model-selection policy keyed off router output:
  - Factual/current-time queries where accuracy matters → `local-lucy-llama31`
  - Coding/reasoning/translation → candidate: `local-lucy-fast` / qwen3:14b, but only if testing confirms it is better than llama3.1 for these classes
  - Creative writing, short chat, low-latency → `local-lucy` / qwen3:14b with shorter budget
  - Medical/vet/finance evidence → `local-lucy-llama31`
- [ ] Add `_select_model(query, route, intent_family)` helper that returns a recommendation.
- [ ] **Keep the manual model selector.** Add an "Auto" option at the top.
- [ ] In shadow mode, log for every query:
  - recommended model,
  - reason,
  - competing model,
  - confidence,
  - actual latency,
  - user correction (if any).
- [ ] Run shadow mode during normal use and compare recommendations with manual selections.
- [ ] Run blind A/B comparisons: for a subset of queries, generate answers from both the recommended model and the competing model without revealing which is which. Record the user's preferred answer. Answer preference is a stronger label than manual model selection.
- [ ] Continue collecting shadow logs and A/B results after the initial gate; 50 queries is enough to enable Auto, not enough to lock the policy permanently.
- [ ] Only after the shadow logs show reliable recommendations, make Auto the default and move manual control into the Engineering panel.

**Success criteria:**
- Shadow logs show ≥ 90% agreement with sensible manual choices over at least 50 diverse queries.
- The recommended model equals or exceeds the competing model in blind A/B preference, with no significant class where it consistently underperforms.
- Qwen is not chosen for a class unless it demonstrably outperforms llama3.1 on that class, including in A/B answer quality.

---

## Phase 4: Classifier Hardening

**Why:** 81% global accuracy is too coarse and too low.

**Files:**
- `models/router/train_classifier_head.py`
- `models/router/finetune_minilm.py`
- `tools/router_py/append_*_examples.py`
- `tools/router_py/classify.py`
- `data/evaluation/routing_validation_corpus.jsonl`

**Actions:**
- [ ] Use the frozen validation corpus from Phase 1.
- [ ] Categorize failures from the corpus and barrage:
  - AUGMENTED vs LOCAL confusion
  - NEWS vs LOCAL confusion
  - EVIDENCE false negatives
  - EPHEMERAL misclassification
- [ ] Generate hard-negative training examples for the worst classes.
- [ ] Re-train the MiniLM embedding + classifier head with the expanded data.
- [ ] Track per-route precision/recall and high-stakes false negatives, not just global accuracy.
- [ ] Add a confidence-triggered LLM arbiter for low-confidence cases (embedding confidence < 0.60 and margin < 0.15).
- [ ] Add a regression test that fails if any per-route recall drops below its current value.

**Success criteria:**
- Per-route recall on the frozen validation corpus improves.
- High-stakes false negatives (medical, vet, finance) approach zero.
- Routing barrage 38/38 PASS.

---

## Phase 5: Simplify the HMI

**Why:** The current engineering interface exposes too many toggles.

**Files:**
- `ui-v10/app/panels/control_panel.py`
- `ui-v10/app/main_window.py`
- `ui-v10/app/services/runtime_bridge.py`

**Actions:**
- [ ] **Only after Phase 3 shadow mode is reliable:** make Auto the default for mode and model.
- [ ] Default view keeps only:
  - **Memory** (on/off)
  - **Voice** (on/off)
  - **Route/model status indicator**
  - **Trust/source summary**
- [ ] Move mode, evidence, augmentation policy, provider, learner, model, and persona selectors into a collapsible "Engineering" panel.
- [ ] Fix the persona selector jump-back-to-Auto bug or remove the persona selector from Local Lucy entirely (persona is not part of v11 scope).
- [ ] Engineering panel preserves observability:
  - selected route,
  - selected model,
  - confidence and margin,
  - context items accepted/rejected,
  - provider chain,
  - source freshness,
  - latency breakdown,
  - manual model override.
- [ ] Update HMI comprehensive inspection test expectations.

**Success criteria:**
- A non-technical user can launch Lucy and ask a question without touching a selector.
- Engineering panel shows full decision trace.
- HMI inspection passes.

---

## Phase 6: Test Suite Cleanup

**Why:** Pre-existing failures in synthetic adversarial and environment tests erode trust.

**Files:**
- `tools/router_py/test_synthetic_adversarial.py`
- `ui-v10/tests/test_changes_verification.py`
- `pyproject.toml`
- `run_all_tests.py`

**Actions:**
- [ ] Fix `test_changes_verification.py::test_fail_loud_no_env_vars` so the subprocess uses the project venv python instead of system `python3`.
- [ ] Categorize adversarial failures:
  - obsolete expectation,
  - deliberately unsupported behaviour,
  - ambiguous query,
  - genuine routing defect,
  - test infrastructure problem.
- [ ] Move unsupported/ambiguous cases to an optional diagnostic directory.
- [ ] Fix genuine routing defects.
- [ ] Make `run_all_tests.py` respect `pyproject.toml` ignore patterns.
- [ ] Add a fast pre-commit test target: barrage + HMI + memory gate + context guard.

**Success criteria:**
- `python run_all_tests.py` exits green in the project venv.

---

## Phase 7: Latency Optimization

**Why:** v11 should feel faster than v10.

**Files:**
- `config/latency_optimizations.env`
- `tools/router_py/classify.py`
- `ui-v10/app/services/runtime_bridge.py`
- `tools/router_py/providers/`

**Actions:**
- [ ] Use the latency baselines from Phase 1.
- [ ] Fire AUGMENTED evidence sources in parallel with early exit on first good result.
- [ ] Cache MiniLM embeddings for repeated queries.
- [ ] Set per-route token budgets:
  - LOCAL simple Q&A: 256 tokens
  - AUGMENTED: 512 tokens
  - EVIDENCE: 768 tokens
  - Creative: 512 tokens default
- [ ] Keep the most-likely-next model warm.
- [ ] Measure and report before/after latency for 10 representative queries.

**Success criteria:**
- Average LOCAL response latency improves by >= 20%.
- AUGMENTED route latency improves by >= 15%.

---

## Phase 8: Evidence/News Improvements, Documentation, and Version Bump

**Why:** The user wants more reliable news and evidence, and v11 needs a version marker.

**Files:**
- `tools/router_py/providers/news_provider.py`
- `tools/router_py/providers/evidence_provider.py`
- `tools/internet/`
- `VERSION`
- `Architecture.md`
- `README.md`

**Actions:**
- [ ] Add source cross-check: fetch 2-3 news sources and merge/disagree in the answer.
- [ ] Add recency scoring for news: penalize articles older than 7 days unless query asks for history.
- [ ] Add evidence source freshness check for medical/vet/finance domains.
- [ ] Add a "no live source available" graceful fallback to local knowledge with a clear caveat.
- [ ] Bump `VERSION` to `11.0.0-dev`.
- [ ] Update `Architecture.md` to reflect simplified HMI, automatic model selection, context guard, and English-only scope.
- [ ] Update `README.md` quick-start.
- [ ] Sync Architecture.md to Desktop.

**Success criteria:**
- Factual queries cite at least one source; conflicting sources are flagged.
- `cat VERSION` returns `11.0.0-dev`.
- Desktop has a current `Local_Lucy_V11_Architecture_YYYY-MM-DD.md`.

---

## Modularization Target

Gradually extract four clear modules from `execution_engine.py` (~3,700 lines):

- `execution_engine.py` — orchestration only
- `context_builder.py` — memory and external-context assembly + guard integration
- `provider_executor.py` — provider invocation, fallback chains, and synthesis
- `response_pipeline.py` — synthesis, formatting, and state writing

Do not perform a big-bang rewrite. Move logic incrementally as you touch each area.

---

## More Local-First Routing Policy

Revise the policy gates so that:

- Stable basic fact → LOCAL
- Stable fact + requested citations → AUGMENTED
- Current office-holder/status → AUGMENTED
- Travel logistics/recommendations → AUGMENTED
- Ordinary recipe → LOCAL
- Coding, opinion, creative writing → LOCAL
- Medical/vet/legal high-stakes → EVIDENCE
- Latest news/weather/finance/time → dedicated live provider

This better matches the "local-first" goal and reduces latency/API dependence.

---

## Verification Commands

Run after every task:
```bash
cd /home/mike/lucy-v10
python3 tools/router_py/run_routing_barrage.py
python3 -m pytest tools/router_py -q
python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```

Run once at phase boundaries:
```bash
python3 tools/router_py/evaluate_router.py
python run_all_tests.py
```

## Notes for ChatGPT/Codex Handoff

- Local Lucy v11 is **English-only**. Racheli/Hebrew is a separate service.
- External LLMs (OpenAI, Kimi) synthesize evidence; they are not evidence sources themselves.
- Context must pass entity, intent, temporal, lexical, provenance, and answerability checks.
- Automatic model selection starts in shadow mode. Do not remove manual controls until shadow logs prove reliability.
- Do not add new models or LoRAs until the classifier and HMI are fixed.
- Preserve the routing barrage as the regression safety net.
