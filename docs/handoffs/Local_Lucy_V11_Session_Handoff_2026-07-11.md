# Local Lucy V11 — Session Handoff

**Date:** 2026-07-11 (updated 2026-07-12)
**Branch:** `v10-dev`
**Latest commit:** `357ce55`
**Repo:** `/home/mike/lucy-v10`

---

## What was done this session

- Fixed the Grok top-priority issues plus the related state/voice bugs discovered while verifying them:
  1. **Control toggles ↔ live state:** `ensure_control_env()` and `_apply_state_to_env()` now overwrite process env from `current_state.json` on every HMI action and router submit.
  2. **HMI shutdown crash:** `RuntimeActionTask.cancel()` stops the worker cooperatively and prevents the shutdown `AttributeError`.
  3. **Learner fail-closed:** high-stakes feedback gate treats any policy exception as high-stakes; `LUCY_AUTO_LEARN` defaults off.
  4. **Memory DB path:** resolves via `xdg_paths.lucy_memory_db_path()` with `LUCY_MEMORY_DB_PATH` override.
  5. **Voice PTT workspace root:** `tools/lucy_voice_ptt.sh` now uses the correct `LUCY_WORKSPACE_ROOT`.
  6. **State file resolution:** `load_state_from_file()` reads the HMI's actual namespace state file, not the legacy project-root path.
  7. **Model unload on switch:** heartbeat and warmup threads restart when the selected model changes so the previous model is not kept warm.
  8. **Test cleanup:** removed stale shell-router comparison tests from `tools/router_py/test_utils.py`.

- Raised the Kimi turn limit to `max_steps_per_turn = 1000` in `/home/mike/.kimi-code/config.toml`.

## Post-handoff fixes (2026-07-12)

- **Memory context for short affirmations:** `Yes, please.`, `Sure.`, `Go ahead.`, etc. were incorrectly treated as topic shifts, so the prior turn was dropped. `_is_vague_followup()` now recognizes short affirmations, and the topic-shift gate bypasses them.
- **XDG data dir double-app-name bug:** `tools/xdg_paths.py` was building `~/.local/share/local-lucy/local-lucy/...`; it now correctly resolves to `~/.local/share/local-lucy/...`.
- **Per-model semantic-regression goldens:** `tests/golden_semantic_responses.json` now stores responses per model. Goldens exist for `local-lucy-llama31` and `local-lucy`; the 10 previously-skipped tests now pass for both models.

## Gemma 4 12B integration (2026-07-12)

- Upgraded Ollama to 0.31.2 and pulled `gemma4:12b-it-qat` (~7.2 GB).
- Registered `gemma4:12b-it-qat` as an optional local model in:
  - `ui-v10/app/panels/control_panel.py`
  - `ui-v10/app/services/runtime_bridge.py`
- Fixed empty-response issue: Gemma 4 emits internal reasoning tokens via `/api/generate`, so `local_answer.py` now treats `gemma4` as a thinking model and applies the 4× `num_predict` multiplier.
- Recorded per-model semantic-regression goldens for Gemma 4.
- Relaxed the `honesty_uncertainty` structural gate so valid paraphrases of "I don't know" are not rejected.
- **Gemma 4 smart-routing bypass:** added an HMI toggle that, when on, skips `classify_intent()` and `select_route()` for Gemma 4 and routes ordinary queries straight to `LOCAL`. Explicit `news:`/`evidence:`/`augmented:` prefixes and existing news/evidence pattern fast paths are preserved.
- **Low-VRAM warning:** the HMI now warns when Gemma 4 is selected on a GPU with <12 GB free VRAM, noting that Ollama can fall back to system RAM.
- **VRAM helper:** `tools/router_py/local_answer.py:get_gpu_free_vram_mb()` probes free VRAM via `pynvml` or `nvidia-smi`.

---

## Current state

- All changes are committed locally on `v10-dev`.
- Working tree is clean except for untracked files:
  - `count_inotify_watches.py` (diagnostic script from the inotify investigation)
  - `memory.db`, `memory.db-shm`, `memory.db-wal` (runtime SQLite artifacts from test runs)

### Verification evidence

| Suite | Result |
|---|---|
| `LUCY_LOCAL_MODEL=gemma4:12b-it-qat LUCY_TEST_LIVE_APIS=1 make test` | **1095 passed, 1 deselected, 6 warnings** |
| `tools/router_py/test_e2e_hmi_voice.py` (Gemma 4) | **15/15 passed** |
| `tools/router_py/test_semantic_regression.py` (Gemma 4) | **10/10 passed** |
| `tools/router_py/test_request_pipeline.py` | **9/9 passed** |
| `tools/router_py/test_local_answer.py::TestVramHelper` | **1/1 passed** |

- inotify usage is **499/524,288 watches** — no current pressure.

---

## Known limitations / next session

1. **Bloat cleanup is the next priority.** The repo has accumulated large, repetitive files from earlier agents. The next session should audit and trim them without changing runtime behavior.
2. `run_barrage.py` has no `--count` option; it always runs the fixed pilot list.

---

## Gemma 4 shadow-router assessment (no code changes)

### Suitability as reasoning / multimodal specialist

Yes. On the RTX 3090 24 GB, `gemma4:12b-it-qat` loads comfortably (~7 GB weights + projector) and leaves plenty of VRAM for Whisper, TTS, and embeddings. The regression suite passes end-to-end. Initial observations:

- **Reasoning:** noticeably stronger structured reasoning than the older 12B models; the `reasoning_structured` test produced a clean step-by-step argument.
- **Instruction following:** good first-person framing and self-knowledge accuracy.
- **Paraphrase variance:** Gemma 4 rephrases uncertainty admissions more freely than Llama 3.1, so rigid exact-match or narrow regex gates need to be relaxed.
- **Thinking tokens:** must be budgeted via the existing thinking-model multiplier; otherwise Ollama `/api/generate` returns an empty response when reasoning consumes the token limit.
- **Multimodality:** not exercised by the current suite. Native image/audio input would need new test cases and adapter work.

### What would need to change for a shadow routing pass

A minimal shadow router would run Gemma 4 in parallel with the existing router, log its proposal, and return the existing router's decision unchanged.

Likely touch points:

1. **Model registration**
   - `tools/router_py/model_selector.py`: add Gemma 4 to capability/latency buckets.
   - `tools/router_py/local_answer.py`: add Gemma 4 self-knowledge string if it becomes a primary model.

2. **Shadow invocation point**
   - `tools/router_py/request_pipeline.py:process()`, after `select_route()` and before `apply_provider()`.
   - New function/class (e.g., `Gemma4ShadowRouter`) builds a constrained JSON prompt asking for:
     - `intent`, `domain`, `freshness_required`, `memory_required`, `tools_required`
     - `preferred_model`, `fallback_model`, `response_mode`, `reason`
   - Call Gemma 4 with `temperature=0`, parse the JSON, validate schema.

3. **Logging / comparison**
   - Extend `tools/router_py/metrics.py` with `record_routing_shadow()`.
   - Emit: shadow route, primary route, agreement, latency, parse errors.
   - Reuse existing `router_decisions.jsonl` or add a dedicated `shadow_routes.jsonl`.

4. **Configuration toggle**
   - Env var `LUCY_GEMMA4_SHADOW_ENABLED=1`.
   - Optional mode: shadow-only for ambiguous routes (low margin / low confidence).

### What must stay deterministic

Do not let Gemma 4 decide or override:

- Medical / veterinary evidence requirements.
- Personal / family facts (authoritative in SQLite/templates).
- Keel / hard policy rules (`config/keel.yaml`, `config/trust/policy.yaml`).
- Tool execution authorization and filesystem permissions.
- Model availability and VRAM limits.
- Cache invalidation, logging, rollback, kill switches.

The right boundary is: **Gemma 4 interprets; Local Lucy authorizes.**

### Recommended next steps and effort estimate

1. **Run a shadow-model selection evaluation first** (low effort, ~1 hour): route 50–100 real or adversarial requests through Gemma 4 offline and compare against the current router's decisions. This reveals whether the gains justify the latency cost.
2. **Add a gated shadow pass** (medium effort, ~2–3 hours): implement `Gemma4ShadowRouter` behind `LUCY_GEMMA4_SHADOW_ENABLED`, log disagreements, do not affect production routing.
3. **Add multimodal smoke tests** (medium effort, ~3–4 hours): image + PDF understanding via the existing HMI/execution pipeline.
4. **Promote to production router only after** shadow agreement is high (>90% on golden + adversarial sets) and dangerous false negatives are near zero.

Estimate for a safe, observable shadow integration: **half a day**. Promoting it to primary routing is a separate, larger decision that should wait until shadow data proves it reduces misroutes without adding latency the user notices.

---

## Resume commands

```bash
cd /home/mike/lucy-v10
git status
git log --oneline -5
make test
```

End of handoff.
