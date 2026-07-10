# Local Lucy V11 — Session Handoff

**Date:** 2026-07-10
**Branch:** `v10-dev`
**Latest commits:**
- `87208d0` — chore: purge remaining Racheli/Hebrew artifacts from primary runtime
- `dd82304` — chore: apply pre-commit cleanup and minor corrections

**Repo:** `/home/mike/lucy-v10`
**Status:** All changes committed and pushed to `origin v10-dev`. Working tree is clean.

---

## What was done this session

1. **Completed Racheli/Hebrew purge from primary runtime**
   - Removed quarantined Racheli Modelfiles, mode config (`config/modes/racheli.yaml`), and persona text.
   - Removed the unused Hebrew query gate from `tools/router_py/policy_router.py`.
   - Removed Hebrew Wikipedia fallback from `tools/unverified_context_wikipedia.py` and the corresponding tests.
   - Deleted `models/router/append_hebrew_examples.py`.
   - Removed Racheli cases from `tests/golden_persona_cases.jsonl`.
   - Updated `AGENTS.md`, `README.md`, and `docs/runbooks/PERSONAS.md` to describe a single Michael persona.
   - Removed Hebrew script from system prompts and dropped Hebrew translation deps/comments from `ui-v10/requirements.txt`.
   - Updated `SHA256SUMS` to remove the stale `racheli.yaml` line.

2. **Committed pre-existing unstaged changes**
   - Reviewed 97 modified files that were sitting unstaged in the working tree.
   - The bulk were import reordering, unused-import removal, f-string simplification, and whitespace fixes applied by pre-commit hooks.
   - Restored the provider import smoke-test in `tools/thrash_test_fast.py` with a `noqa` guard so its "13 symbols" log remains truthful.
   - Kept one substantive route-correction entry in `models/router/comprehensive_examples.json` (London weather query marked as user feedback).
   - Committed and pushed after `make test` passed.

3. **Updated architecture documentation**
   - Refreshed `Architecture.md` and `ARCHITECTURE.md` in-repo (date 2026-07-10, purge-complete note, updated directory layout and system prompt snippet).
   - Copied the current architecture to the desktop as `Local_Lucy_V11_Architecture_2026-07-10.md`.

---

## Current state

- **Runtime scope:** English-only primary assistant. The standalone Hebrew assistant was archived separately; it is no longer reachable from Local Lucy.
- **Persona:** Single user persona (Michael). LoRA adapter `local-lucy-llama31-michael` is archived in `backups/v10-dev-cleanup/2026-07-04/lora/`; prompt-level fallback is active.
- **Test suite:** `make test` passes — **1065 passed, 29 skipped, 1 deselected**.
- **Lint:** 87 pre-existing ruff warnings remain (mostly E402 imports-not-at-top, F841 unused variables, E722 bare excepts in test/standalone scripts). These do not block runtime or tests.
- **Working tree:** Clean.

---

## Known limitations and risks

1. **`tools/router_py/execution_engine.py` is still large (~2,195 lines).** Shell fallback has been removed, but the file still mixes orchestration, provider dispatch, context loading, formatting, and state writing. Future work should extract:
   - `context_builder.py`
   - `provider_executor.py`
   - `response_pipeline.py`

2. **Automatic model selection is still in shadow/recommendation mode.** The HMI defaults to Auto, but manual override remains available and should stay visible until shadow logs prove the policy across enough real queries.

3. **Context guard exists but thresholds need real-world tuning.** Entity collision, temporal checks, and answerability scoring are implemented but may need adjustment as failures appear in use.

4. **Voice latency remains high.** Whisper STT and Kokoro TTS run on CPU on the RTX 3060 12 GB. A 3090-class upgrade would help, but the voice stack should also be reviewed for lighter models and load/unload behavior.

5. **Model unload on switch.** Ensure Ollama unloads the previous model before loading a new one. A previous fix added polling of `/api/ps` and `keep_alive=0`; verify this remains reliable in Auto mode.

---

## Next recommended work

Per the approved v11 roadmap, the next implementer should begin with **measurement**, not more features:

1. **Routing calibration**
   - Expand `run_barrage.py` to a 50–100 query validation corpus.
   - Record expected vs actual route, provider, model, latency, fallback chain, and pass/fail.
   - Prioritise stable-knowledge routing (capitals, basic science, historical facts should route `LOCAL`).

2. **Context provenance hardening**
   - Add telemetry for accepted/rejected/unused context.
   - Log entity collision, temporal mismatch, and source disagreement cases.

3. **Model selector shadow validation**
   - Keep manual model selector visible.
   - Log Auto recommendations vs manual choices vs blind A/B answer preference.
   - Set a 50-query gate before making Auto the non-overridable default.

4. **Test cleanup**
   - Categorise the ~90 synthetic adversarial routing expectations that still fail.
   - Decide which are obsolete, unsupported, ambiguous, or genuine defects.

5. **HMI simplification (only after 1–4 are stable)**
   - Default view: conversation, input, memory/voice toggles, status.
   - Engineering panel: route trace, model, confidence, context accepted/rejected, latency breakdown, manual overrides.

---

## Files the next agent should read

- `Architecture.md` (in-repo, current)
- `docs/runbooks/PERSONAS.md`
- `tools/router_py/run_barrage.py`
- `tools/router_py/policy_router.py`
- `tools/router_py/execution_engine.py`
- `tools/router_py/context_guard.py`
- `tools/router_py/model_selector.py`
- `AGENTS.md`

---

## How to resume

```bash
cd /home/mike/lucy-v10
git status                        # should be clean
git log --oneline -5
make test                         # verify baseline
```

End of handoff.
