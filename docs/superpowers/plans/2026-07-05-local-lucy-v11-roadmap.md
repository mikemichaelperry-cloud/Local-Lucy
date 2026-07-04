# Local Lucy v11 Roadmap

> Next-session implementation plan for moving from v10 to a leaner, faster, more accurate Local Lucy v11.

## Goal

Transform Local Lucy v10 into v11: an autonomous assistant that picks the right mode, model, and source without user-facing toggles, returns factual answers with verified context, and runs efficiently on the current RTX 3060 12 GB / 31 GB RAM hardware.

## Hardware Constraints

- GPU: NVIDIA RTX 3060 12 GB
- RAM: 31 GB system RAM
- Ollama runs locally; VRAM is the bottleneck
- Current working models:
  - `local-lucy` / `local-lucy-fast`: qwen3:14b (~9 GB VRAM, 2048 ctx)
  - `local-lucy-llama31`: llama3.1:8b (8192 ctx)
  - `local-lucy-mistral`: mistral-nemo 12B
- One model loaded at a time; switching models incurs unload/load latency
- Voice: Whisper STT + Kokoro TTS (cuda where possible)

## v11 Design Principles

1. **Zero user-facing switches.** The HMI should not require the user to pick mode, model, provider, or persona. The system decides.
2. **Context is guilty until proven innocent.** Every injected source (memory, Wikipedia, news, augmented provider output) must pass a relevance gate before it enters the LLM prompt.
3. **Fail up, not down.** If the local model is uncertain, route to augmented/news/evidence automatically. No more "I don't know" when external sources are available.
4. **One canonical prompt.** One system prompt / Modelfile that knows the architecture and capabilities, not per-model/persona variants.
5. **Measure before optimizing.** Every change must be covered by the routing barrage and HMI inspection; latency must be measured before/after.

---

## Task 1: HMI Simplification — Remove the Switch Farm

**Why:** The current engineering interface exposes mode, memory, evidence, voice, augmentation policy, provider, learner, model, and persona selectors. The persona toggle already jumps back to Auto. This conflicts with the "one ring" goal.

**Files:**
- `ui-v10/app/panels/control_panel.py`
- `ui-v10/app/main_window.py`
- `ui-v10/app/services/runtime_bridge.py`

**Steps:**
- [ ] Audit every selector in `control_panel.py` and decide: automatic | user preference | debug-only.
- [ ] Keep only two user-facing toggles:
  - **Memory** (on/off) — user owns whether session turns are remembered
  - **Voice** (on/off) — user owns input/output modality
- [ ] Move everything else (mode, evidence, augmentation policy, provider, learner, model, persona) behind an "Engineering" collapsible panel or remove the widgets entirely.
- [ ] Fix the persona selector jump-back-to-Auto bug.
- [ ] Make the default view an operator-level panel: input, output, route indicator, trust indicator.
- [ ] Update HMI comprehensive inspection test expectations to match the simplified layout.

**Acceptance:**
- `python3 ui-v10/tests/test_comprehensive_hmi_inspection.py` passes with the new layout.
- A non-technical user can launch Lucy and ask a question without touching a selector.

---

## Task 2: Automatic Model Selection

**Why:** The user wants the model chosen by the classified query. Right now the HMI exposes four models and the runtime defaults to one.

**Files:**
- `tools/router_py/classify.py`
- `tools/router_py/policy_router.py`
- `ui-v10/app/services/runtime_bridge.py`
- `ui-v10/app/panels/control_panel.py`

**Steps:**
- [ ] Define a model-selection policy keyed off router output:
  - Factual/current-time queries where accuracy matters → `local-lucy-llama31` (8192 ctx, lower hallucination)
  - Coding/reasoning/translation → `local-lucy-fast` / qwen3:14b
  - Creative writing, short chat, low-latency → `local-lucy` / qwen3:14b with shorter budget
  - Medical/vet/finance evidence → `local-lucy-llama31` for careful reasoning
- [ ] Add a `_select_model(query, route, intent_family)` helper in `tools/router_py/classify.py`.
- [ ] Plumb the selected model through the routing decision so `runtime_bridge.py` uses it instead of the HMI selector.
- [ ] Add model-switch cooldown/unload logic in `runtime_bridge.py` so rapid-fire queries do not thrash Ollama.
- [ ] Remove the model selector from the default HMI view (keep it in engineering debug view if useful).
- [ ] Add tests: `test_model_selection.py` covering each policy case.

**Acceptance:**
- `python3 tools/router_py/run_routing_barrage.py` passes.
- A query like "Write a Python function" routes LOCAL and selects qwen3.
- A query like "What are the main tourist attractions in Japan?" routes AUGMENTED and selects llama3.1.

---

## Task 3: Context-Injection Guard Layer

**Why:** The most embarrassing failures come from injecting irrelevant context (Tourism in China for a Japan query) or stale memory turns.

**Files:**
- `tools/router_py/context_guard.py` (new)
- `tools/router_py/classify.py`
- `tools/router_py/local_answer.py`
- `tools/router_py/providers/` (augmented, news, evidence)

**Steps:**
- [ ] Create `ContextGuard` class with scoring methods:
  - `score_memory_turn(query, turn_text)` — semantic similarity using MiniLM
  - `score_source(query, source_title, source_snippet)` — title + snippet overlap
  - `score_evidence(query, evidence_pack)` — keyword + embedding relevance
- [ ] Set thresholds:
  - Memory turn: >= 0.30 similarity (current threshold, validated)
  - External source: >= 0.45 similarity or explicit keyword overlap
- [ ] Integrate the guard into `classify.py` before the final `RoutingDecision`:
  - Drop memory turns below threshold from the prompt context
  - Reject Wikipedia/news snippets below threshold and fall back to next provider or local knowledge
- [ ] Update prompt instruction: "Use the following context only if it directly answers the current query; otherwise answer from your own knowledge."
- [ ] Add unit tests for the guard in `tools/router_py/test_context_guard.py`.

**Acceptance:**
- The Japan tourist query no longer cites Tourism in China.
- Stale memory turns are filtered out.
- Barrage and HMI tests pass.

---

## Task 4: Classifier Hardening

**Why:** 81.3% router accuracy is too low for an autonomous system. Too many queries need overrides.

**Files:**
- `models/router/train_classifier_head.py`
- `models/router/finetune_minilm.py`
- `tools/router_py/append_*_examples.py`
- `tools/router_py/classify.py`

**Steps:**
- [ ] Audit current misrouted cases in the barrage and synthetic adversarial tests.
- [ ] Generate hard-negative training examples for the weakest classes (AUGMENTED, EPHEMERAL, NEWS vs LOCAL).
- [ ] Re-train the MiniLM embedding + classifier head with the expanded data.
- [ ] Add a confidence-triggered LLM arbiter:
  - When embedding confidence < 0.60 and margin < 0.15, call a lightweight LLM judge (qwen3 fast path) to pick the route.
  - Cache arbiter decisions to avoid repeated LLM calls.
- [ ] Add a regression test that locks in barrage pass rate; fail CI if it drops.

**Acceptance:**
- Combined validation accuracy > 85%.
- Routing barrage 38/38 PASS.
- No regression in HMI inspection.

---

## Task 5: Test Suite Cleanup

**Why:** Pre-existing failures in synthetic adversarial and environment tests erode trust.

**Files:**
- `tools/router_py/test_synthetic_adversarial.py`
- `ui-v10/tests/test_changes_verification.py`
- `pyproject.toml`
- `run_all_tests.py`

**Steps:**
- [ ] Fix `test_changes_verification.py::test_fail_loud_no_env_vars` so the subprocess uses the project venv python instead of system `python3`.
- [ ] For `test_synthetic_adversarial.py`, either:
  - Update expectations to match current routing behavior, or
  - Move it to an optional `tools/router_py/adversarial/` directory and run it as a diagnostic, not a CI gate.
- [ ] Make `run_all_tests.py` respect `pyproject.toml` ignore patterns.
- [ ] Add a fast pre-commit test target: barrage + HMI + memory gate + context guard.

**Acceptance:**
- `python run_all_tests.py` exits green in the project venv.

---

## Task 6: Latency Optimization

**Why:** v11 should feel faster than v10.

**Files:**
- `config/latency_optimizations.env`
- `tools/router_py/classify.py`
- `ui-v10/app/services/runtime_bridge.py`
- `tools/router_py/providers/`

**Steps:**
- [ ] Profile end-to-end latency for LOCAL, AUGMENTED, NEWS, EVIDENCE routes.
- [ ] Add async/concurrent provider calls for AUGMENTED chain (Wikipedia, OpenAI, Kimi can be fired in parallel with early exit on first good result).
- [ ] Cache MiniLM embeddings for repeated queries.
- [ ] Set aggressive `num_predict` and `num_ctx` budgets per route:
  - LOCAL simple Q&A: 256 tokens
  - AUGMENTED: 512 tokens
  - EVIDENCE: 768 tokens
  - Creative: user-controlled, default 512
- [ ] Keep Ollama model warm for the most-likely-next-model to reduce switch latency.
- [ ] Measure and report before/after latency for 10 representative queries.

**Acceptance:**
- Average LOCAL response latency improves by >= 20%.
- AUGMENTED route latency improves by >= 15%.

---

## Task 7: News / Wikipedia / Evidence Reliability

**Why:** User explicitly asked for more reliable and extensive news fetching and better Hebrew Wikipedia access.

**Files:**
- `tools/router_py/providers/wikipedia_provider.py`
- `tools/router_py/providers/news_provider.py`
- `tools/internet/`
- `tools/router_py/policy_router.py`

**Steps:**
- [ ] Add Hebrew Wikipedia support:
  - Try `he.wikipedia.org` first for Hebrew queries
  - Fall back to English Wikipedia and translate summaries if needed
- [ ] Add source cross-check: fetch 2-3 news sources and merge/disagree in the answer.
- [ ] Add recency scoring for news: penalize articles older than 7 days unless query asks for history.
- [ ] Add evidence source freshness check for medical/vet/finance domains.
- [ ] Add a "no live source available" graceful fallback to local knowledge with a clear caveat.

**Acceptance:**
- Hebrew query `מה החדשות בישראל?` returns Hebrew/Israeli news.
- Factual queries cite at least one source; conflicting sources are flagged.

---

## Task 8: Documentation and Version Bump

**Why:** v11 needs clear docs and a version marker.

**Files:**
- `VERSION`
- `Architecture.md`
- `README.md`
- Desktop architecture file

**Steps:**
- [ ] Bump `VERSION` to `11.0.0-dev`.
- [ ] Update `Architecture.md` to reflect the simplified HMI, automatic model selection, and context guard.
- [ ] Update `README.md` quick-start to match the new launcher flow.
- [ ] Sync Architecture.md to Desktop with the new date.

**Acceptance:**
- `cat VERSION` returns `11.0.0-dev`.
- Desktop has a current `Local_Lucy_V11_Architecture_YYYY-MM-DD.md`.

---

## Execution Order

1. Task 1 + Task 2 in parallel (HMI simplification + automatic model selection both touch `control_panel.py` and `runtime_bridge.py`, so coordinate)
2. Task 3 (context guard) — depends on stable routing
3. Task 4 (classifier hardening) — can run in parallel with Task 3 if interfaces are agreed
4. Task 5 (test cleanup) — after Tasks 1-4
5. Task 6 (latency) — after Tasks 1-5
6. Task 7 (news/evidence) — after Task 3
7. Task 8 (docs/version) — last

## Verification Commands

Run after every task:
```bash
cd /home/mike/lucy-v10
python3 tools/router_py/run_routing_barrage.py
python3 -m pytest tools/router_py -q
python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```

Run once at the end:
```bash
python run_all_tests.py
```

## Notes for ChatGPT/Codex Handoff

- The v11 goal is autonomy: fewer toggles, smarter routing, verified context.
- Current weakest points: classifier accuracy, HMI complexity, model-switch robustness.
- Do not add new models or LoRAs until the classifier and HMI are fixed.
- Preserve the existing routing barrage as the regression safety net.
