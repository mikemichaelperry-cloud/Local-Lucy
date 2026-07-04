# Router / MiniLM Improvement Attempt — Report for ChatGPT

**Date:** 2026-06-21
**Hardware:** RTX 3060 12 GB VRAM, 31 GB RAM
**Dataset:** `models/router/comprehensive_examples.json` (1,362 examples)
**Local model:** `local-lucy-llama31` (llama3.1:8b q4)

---

## Executive Summary

This session implemented several requested infrastructure and routing improvements. The non-router changes (GPU routing, larger context window, light RAG) were successful. However, attempts to materially improve routing accuracy by fine-tuning or replacing the MiniLM embedding model did **not** produce a clear win. The best configuration remains a **triplet-loss fine-tuned `all-MiniLM-L6-v2`** on the current 1,362 examples, with 90/10 route accuracy of ~81%.

Swapping to `BAAI/bge-small-en-v1.5` — both base and fine-tuned — caused routing regressions on existing tests. Hard-negative data curation also introduced regressions. The routing task appears to be near the practical ceiling of a small embedding model + k-NN approach on this dataset.

---

## What Was Implemented

### 1. Non-routing improvements (successful)

| Change | File(s) | Status |
|---|---|---|
| Let `HybridRouterV2` use GPU with CPU fallback on OOM | `models/router/hybrid_router_v2.py` | ✅ Merged |
| Raised Llama 3.1 `num_ctx` from 4096 to 8192 | `config/Modelfile.local-lucy-llama31`, `tools/router_py/local_answer.py` | ✅ Merged, model recreated |
| Light RAG before AUGMENTED escalation | `tools/router_py/execution_engine.py`, tests | ✅ Merged |
| Fixed Ollama tag parsing in `make check-env` | `scripts/check_environment.py` | ✅ Merged |

All of the above pass `make lint`, targeted routing tests, and the full test suite (modulo 3 pre-existing environment failures unrelated to these changes).

### 2. Router fine-tuning attempts

#### 2a. Initial retrain from base MiniLM with MultipleNegativesRankingLoss
- Trained for 3 epochs on 1,362 examples.
- Result: routing regressions (e.g. personal-finance reasoning queries started routing to `AUGMENTED`).
- Action: reverted to previous fine-tuned checkpoint.

#### 2b. Continual triplet fine-tuning from existing checkpoint
- Started from the existing `finetuned_minilm/` checkpoint and trained for 2 epochs with `BatchHardTripletLoss`.
- Result: still caused regressions on personal-finance / iPhone / president queries.
- Action: reverted.

#### 2c. Triplet fine-tune from base MiniLM
- Trained `all-MiniLM-L6-v2` from scratch for 2 epochs with `BatchHardTripletLoss` on the 1,362 examples.
- Result: **passed all targeted routing tests**.
- 90/10 split: route **81.0%**, intent **78.1%**, short-query **80.4%**.
- Action: kept as the active checkpoint.

### 3. Hard-negative data curation

- Built a 10-fold CV miner (`models/router/find_hard_negatives.py`). It identified 261/1,362 mistakes; weakest classes: `AUGMENTED` (~52%), `EPHEMERAL` (~10%), `EVIDENCE` (~62%).
- Generated 34 synthetic boundary candidates that the current router misclassified.
- Added them to the dataset and retrained.
- Result: regressions on existing tests (e.g. `Current president of the United States` → `AUGMENTED`, `Latest iPhone release date` → `FINANCE`).
- Action: reverted the data addition. The miner script was kept for future use.

### 4. BGE-small replacement attempt

| Variant | 90/10 route | 90/10 intent | Short-query | Test regressions |
|---|---|---|---|---|
| Base `all-MiniLM-L6-v2` | **83.2%** | 76.6% | 82.6% | — |
| Base `BAAI/bge-small-en-v1.5` | 81.0% | **78.1%** | **84.8%** | — |
| Fine-tuned `BAAI/bge-small-en-v1.5` (2 epochs triplet) | not measured | not measured | not measured | ❌ 6 regressions |
| Fine-tuned `all-MiniLM-L6-v2` (current active) | 81.0% | 78.1% | 80.4% | ✅ none |

Base BGE-small was comparable but not better than base MiniLM on route accuracy. Fine-tuned BGE-small broke personal-finance reasoning and current-facts routing. It was reverted.

---

## Why the improvements were disappointing

1. **The dataset is small and the categories overlap.** 1,362 examples across 8 routes is thin for learning subtle boundaries like `LOCAL` vs `AUGMENTED` vs `NEWS`.
2. **MiniLM-L6 is near its ceiling.** The base model already scores 83.2% on the 90/10 split. Fine-tuning helps some classes but pulls others across boundaries.
3. **k-NN amplifies embedding confusion.** `HybridRouterV2` has no learned decision boundary; if the embedding space is fuzzy, the router is fuzzy.
4. **Policy ambiguity.** Some queries are genuinely on the border between routes (e.g. “Current president of the United States” could be `LOCAL` or `AUGMENTED`). Synthetic examples easily flip these depending on training signal.

---

## Recommendations

### Short term (low risk)
- **Keep the current triplet-fine-tuned MiniLM checkpoint.** It is the best balance of accuracy and test stability found so far.
- **Keep `models/router/find_hard_negatives.py`.** It is a useful diagnostic for finding weak classes. Future data work should be manual/human-curated around its output, not template-generated.
- **Monitor the 3 pre-existing test failures** (`local-lucy-fast` request-tool tests and missing Whisper model) separately; they are environment issues, not routing issues.

### Medium term (higher effort, higher potential)
- **Train a classifier head** on top of the fine-tuned MiniLM (or BGE-small) embeddings. A small `Linear(384, num_routes)` trained with cross-entropy can learn explicit decision boundaries instead of relying on nearest-neighbor similarity. This is the most likely path to a measurable accuracy gain.
- **Curate hard negatives manually.** Use the CV miner to find real mistakes, then add only a handful of carefully-labeled counter-examples per mistake class. Avoid bulk synthetic generation.

### Long term
- **Move to a stronger embedding backbone** only after the router architecture supports a classifier head. A larger model (e.g. `bge-base`, `nomic-embed-text`) may help, but the current k-NN design will still waste that extra capacity.

---

## Conclusion

The infrastructure changes (GPU, 8K context, light RAG) are solid improvements. The routing accuracy, however, is stuck around 80–83% regardless of loss function or small model swaps. The next productive step is either a **classifier head** or **manual hard-negative curation**, not another embedding-model swap.
