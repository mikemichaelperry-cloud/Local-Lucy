# Local Lucy v10 — Session Handoff

**Date:** 2026-06-22
**Repository:** `~/lucy-v10`
**Branch:** `v10-dev`
**Latest commit (current):** `7fafa0b docs: update SESSION_CONTEXT.md after FINANCE training-data augmentation`
**Pushed to origin:** ⚠️ Not pushed this session (working-tree changes only)

---

## What was done this session

1. **Router GPU support**
   - Updated `models/router/hybrid_router_v2.py` to auto-detect CUDA and load `SentenceTransformer` on GPU.
   - Added a safe CPU fallback when CUDA OOM occurs, so Ollama + MiniLM coexist on the RTX 3060 12 GB card.

2. **Llama 3.1 context window doubled**
   - Raised `num_ctx` from `4096` to `8192` in `config/Modelfile.local-lucy-llama31`.
   - Updated the model identity string in `tools/router_py/local_answer.py`.
   - Recreated the Ollama model: `ollama create local-lucy-llama31 -f config/Modelfile.local-lucy-llama31`.

3. **Light RAG before AUGMENTED escalation**
   - Added `tools/router_py/execution_engine.py::_try_light_rag_local_fallback()`.
   - Before escalating a failed/insufficient `LOCAL` result to the paid/open `AUGMENTED` provider, the engine now fetches up to 3 web snippets and asks the local model again with the snippets as background context.
   - RAG is skipped for medical/veterinary queries (they go straight to `EVIDENCE`) and for personal/family/pet keywords to avoid leaking private queries to the web.
   - Added focused unit tests in `tools/router_py/test_escalation_trigger.py`.

4. **Environment checker fix**
   - Fixed `scripts/check_environment.py` so `make check-env` correctly recognizes Ollama model names that include a `:latest` tag (e.g. `local-lucy-llama31:latest`).
   - `make check-env` now reports all checks green.

5. **Fine-tuning / model-swap exploration**
   - Improved `models/router/finetune_minilm.py` to support `MultipleNegativesRankingLoss` and `BatchHardTripletLoss`, plus `--epochs`, `--batch-size`, `--from-base`, and `--base-model`.
   - Retrained MiniLM-L6 from base with 2 epochs of batch-hard triplet loss on the current 1,362 examples.
   - Active checkpoint: fine-tuned MiniLM-L6, 90/10 split route **81.0%**, intent **78.1%**, short-query **80.4%**.
   - Attempted hard-negative data curation using a 10-fold CV miner (`models/router/find_hard_negatives.py`). Generated 34 synthetic boundary candidates, but adding them caused regressions; the additions were reverted and the miner script was kept.
   - Attempted to replace MiniLM with `BAAI/bge-small-en-v1.5` (base and fine-tuned). Base BGE-small was comparable but not better; fine-tuned BGE-small caused regressions on personal-finance reasoning and current-facts routing. Reverted to the fine-tuned MiniLM checkpoint.
   - Detailed report written: `docs/reports/ROUTER_MINILM_REPLACEMENT_ATTEMPT_2026-06-21.md` and copied to the Desktop.

6. **Validation**
   - `make lint`: passes.
   - `make test`: `950 passed, 19 skipped`. The 3 failures are pre-existing environment issues:
     - `tools/router_py/test_request_tool.py::test_generate` / `test_chat` (assertion failures on live Ollama responses for `local-lucy-fast`).
     - `tools/tests/test_whisper_worker_integration.py::test_fallback_to_whisper_cli` (missing Whisper model file).

---

## Current state

- `git status`: modified (see file list below); no commits made this session.
- `origin/v10-dev`: latest pushed commit is still `7fafa0b`.
- `make lint`: passes.
- `make test`: passes (`950 passed, 19 skipped`; 3 pre-existing failures).
- `make check-env`: all checks green.

---

## Entry points

| Surface | Command |
|---------|---------|
| Desktop HMI | `bash START_LUCY.sh` or `make run` |
| CLI chat | `bash lucy_chat.sh "your question"` |
| Optional web UI | `LUCY_WEB_ENABLED=1 python -m web_adapter` |
| Health check | `python -m tools.router_py.health` |
| Full tests | `make test` |
| Lint | `make lint` |

---

## Files changed this session (key)

- `config/Modelfile.local-lucy-llama31`
- `models/router/hybrid_router_v2.py`
- `models/router/finetune_minilm.py`
- `models/router/finetuned_minilm/README.md`
- `models/router/finetuned_minilm/config.json`
- `models/router/finetuned_minilm/config_sentence_transformers.json`
- `models/router/finetuned_minilm/model.safetensors`
- `models/router/find_hard_negatives.py` (new)
- `scripts/check_environment.py`
- `tools/router_py/execution_engine.py`
- `tools/router_py/local_answer.py`
- `tools/router_py/test_escalation_trigger.py`
- `docs/reports/ROUTER_MINILM_REPLACEMENT_ATTEMPT_2026-06-21.md` (new)
- `docs/handoffs/Local_Lucy_v10_Session_Handoff_2026-06-22.md` (new)

---

## Next session notes

- The routing model is at a practical ceiling for a small embedding model + k-NN approach on 1,362 examples. The most promising next experiments are:
  1. A **classifier head** trained end-to-end on route labels over the fine-tuned MiniLM embeddings.
  2. **Manual hard-negative curation** using `find_hard_negatives.py` to identify weak classes, followed by adding only a few carefully validated counter-examples.
- If either experiment is attempted, run the targeted routing tests (`test_personal_finance_reasoning.py`, `test_routing_edge_cases.py`, `test_hybrid_router_v2_validation.py`, `test_escalation_trigger.py`) before the full suite to catch regressions quickly.
- The new light-RAG feature has not been exercised against live DuckDuckGo/SearXNG queries under load; consider a manual smoke test with a recent factual question.
