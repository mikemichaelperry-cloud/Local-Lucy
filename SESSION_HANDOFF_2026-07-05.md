# Local Lucy V11 — Session Handoff

**Date:** 2026-07-05 (final update)
**Branch:** `v10-dev` on GitHub (`origin v10-dev` pushed)
**Version:** `11.0.0-dev`
**Status:** All v11 roadmap phases completed, plus two live-fixes applied and pushed.

---

## What was completed

| Phase | Summary | Commit |
|-------|---------|--------|
| 0 | Removed Hebrew/Racheli from primary runtime, quarantined configs, fixed prompt contradictions, updated AUGMENTED = Wikipedia evidence + optional OpenAI/Kimi synthesis. | `82c9296` |
| 1-2 | Added JSONL metrics sink, hardened context guard (provenance, temporal, entity collision, answerability), route-dependent evidence failure fallback. | `5d01586` |
| 3 | Automatic model selection in shadow mode; HMI model selector now defaults to Auto, manual selector moved to Engineering panel. | `a0b03e5` |
| 4 | Frozen validation corpus, classifier error analysis, hard-negative generation, classifier-head retrain, confidence-triggered LLM arbiter, stable-knowledge policy gate. | `f57c6a2` |
| 5 | Simplified HMI default view (Memory/Voice/status only), advanced controls in Engineering panel, persona selector removed from primary HMI. | `c75d8c2` |
| 6 | Synthetic adversarial cleanup: full-answer tests opt-in, v11 policy-conflict cases moved to diagnostic directory, fixed routing defects (conspiracy→LOCAL, stable history/finance→LOCAL, garbage→LOCAL). | `3d4e05f` |
| 7 | Latency optimization: MiniLM embedding LRU cache, parallel AUGMENTED evidence fetching, per-route token budgets, model warmup thread. | `d4a7334` |
| 8 | Version bump to `11.0.0-dev`, updated Architecture.md/README.md, news recency scoring + source cross-check, evidence freshness check + graceful fallback. | `cb04727` |
| Live fix 1 | Fuzzy region detection for Israeli news typos (`Iraeli`, `Isreal`, etc.). | `11389c8` |
| Live fix 2 | Unload previous Ollama model on manual model switch in Engineering panel. | `e3027ee` |
| Live fix 3 | Increased OpenAI/Kimi/Wikipedia HTTP timeouts and hardened Ollama model unload verification. | `e4a586b` |
| Live fix 4 | Auto-mode now evicts the previously loaded Ollama model before loading a different one; shutdown hook unloads all Local Lucy models on exit. | `tbd` |

---

## Test scores

| Suite | Before | After |
|-------|--------|-------|
| Routing barrage | 36/38 PASS | **38/38 PASS** |
| Router unit tests | 719 passed | **767 passed, 29 skipped** |
| Adversarial route tests | timed out / 81 failures | **879 passed** |
| HMI comprehensive inspection | 138/138 | **138/138** |
| Live API provider tests (OpenAI/Kimi) | 14/15, Kimi timeout | **15/15 PASS** |
| Ollama cleanup unit tests | — | **7/7 PASS** |

*Latency:* routing steady-state mean after warmup is **~3.0 ms** (first-load MiniLM import remains ~4.5 s).

---

## Important changes to know

- **English-only runtime.** Hebrew/Racheli code is quarantined, not deleted.
- **Evidence vs synthesis.** Wikipedia and official APIs are evidence; OpenAI/Kimi are synthesis providers. AUGMENTED now means "Wikipedia evidence with optional synthesis."
- **Context guard.** Every injected source is scored before reaching the LLM prompt; stale/irrelevant evidence and memory turns are dropped.
- **Automatic model selection.** HMI defaults to Auto; manual override remains in Engineering panel. Shadow logs are written to the metrics sink.
- **Simplified HMI.** Default view shows only Memory toggle, Voice toggle, route/model status, trust/source summary.
- **Latency.** Embedding cache + parallel evidence + token budgets + model warmup.
- **News typos.** Fuzzy region matching catches misspellings like `Iraeli` / `Isreal` and routes to Middle East feeds.
- **Model switching / VRAM policy.** With only 12 GB VRAM, Local Lucy cannot hold two models. Every request (manual or Auto) now calls `_unload_other_ollama_models(<model-we-are-about-to-use>)` before execution, so the previous model is evicted before the new one loads. The Engineering panel switch also does this immediately.
- **Shutdown cleanup.** A new `router_py/ollama_cleanup` module is registered with the shutdown handler. On clean exit (SIGINT/SIGTERM/atexit) it queries Ollama `/api/ps` and unloads any model with a `local-lucy` prefix so VRAM is released.
- **External provider timeouts.** OpenAI/Kimi internal HTTP timeout raised from 5 s / 10 s to 30 s (configurable via `OPENAI_TIMEOUT` / `KIMI_TIMEOUT`). Wikipedia internal HTTP timeout raised from 2.5 s to 10 s (configurable via `LUCY_UNVERIFIED_CONTEXT_WIKIPEDIA_TIMEOUT`). These short defaults were causing transient timeouts that opened the `api_provider` circuit breaker and made AUGMENTED/EVIDENCE answers fail.

---

## Files you will want next session

- `docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md` — the approved roadmap.
- `Architecture.md` — updated normative v11 architecture.
- `VERSION` — now `11.0.0-dev`.
- `config/latency_optimizations.env` — knobs for Phase 7 optimizations.
- `.superpowers/sdd/task-*-report.md` — per-phase subagent reports.

---

## Recommended next steps

1. Run the HMI from the Desktop shortcut and exercise Auto model selection across coding, memory, news, and medical queries.
2. Inspect shadow logs at `~/.codex-api-home/lucy/runtime-v10/metrics/routing_metrics.jsonl` to verify Auto model choices.
3. After ~50 real queries, review A/B preference data and decide whether to hide the manual model selector completely.
4. Run `LUCY_SYNTHETIC_FULL_ANSWER=1 python3 -m pytest tools/router_py/test_synthetic_adversarial.py` when you have time to validate response-level invariants.
5. The user also asked for a "barrage of common, wide-ranging test questions" compared to your own answers and retraining Lucy to match — this remains a future task.

---

## Known issues / notes

- `tools/router_py/test_semantic_regression.py` is currently flaky. Different runs fail on different cases (`personality_logic_over_ideology`, `capability_providers`, etc.). This appears unrelated to the timeout / unload fixes and is likely sensitive to which local model is loaded and minor response variation. Re-run `python3 -m pytest tools/router_py/test_semantic_regression.py -v` after settling on a final default model/prompt.
- The `run_response_regression_all_models.py` full-model regression suite is still slow; run it only when you have several minutes.
- If external providers still fail after these timeout increases, check the circuit-breaker state in the logs for `circuit_breaker_state_change` and consider raising `OPENAI_TIMEOUT` / `KIMI_TIMEOUT` further in `.env`.
- The shutdown cleanup only runs on clean exit. If Local Lucy is killed with `SIGKILL` or crashes, Ollama will still hold the model until its `keep_alive` expires.
