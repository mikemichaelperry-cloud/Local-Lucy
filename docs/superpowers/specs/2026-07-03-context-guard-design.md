# Context-Injection Guard — Semantic Relevance Layer

**Date:** 2026-07-03
**Status:** Approved
**Scope:** `tools/router_py/context_guard.py` and its callers

## Problem

Local Lucy V10 injects two kinds of external context into the LLM prompt:

1. **Retrieved evidence** (Wikipedia, news, augmented providers).
2. **Session-memory turns** (previous user/assistant exchanges).

The current guard in `tools/router_py/context_guard.py` is pure keyword/entity matching. It fails when:

- Evidence is about the wrong entity (e.g. "Tourism in China" for a Japan query).
- Memory turns use pronouns or paraphrases (e.g. "How does it work?" referring to quantum computing).
- The query uses different words than the stored text (synonyms, abbreviations).

These failures cause the LLM to cite wrong sources or repeat stale, incorrect answers.

## Goals

- Reject obviously irrelevant evidence before it reaches the LLM prompt.
- Keep relevant memory turns even when they don't share keywords with the current query.
- Stay fully local: no API key, no cloud call.
- Keep latency low enough for interactive use.
- Not re-introduce Hebrew/multilingual support, which was removed from V10 to reduce complexity.

## Non-goals

- Replacing the router's embedding model.
- Adding new languages (especially Hebrew).
- Rewriting `execution_engine.py` or `local_answer.py` beyond the guard call sites.

## Decision: English-only semantic scoring

Benchmarks on this machine showed:

| Model | Use case | Japan-vs-China | Pronoun memory | Hebrew | Latency |
|---|---|---|---|---|---|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | evidence | 0.968 vs 0.001 | poor | 0.000 / 0.000 | ~16 ms/pair |
| `all-MiniLM-L6-v2` (bi-encoder) | memory | moderate | good | poor | ~12 ms/pair |
| `paraphrase-multilingual-MiniLM-L12-v2` | both | 0.816 vs 0.454 | good | good | ~6 ms/pair |

The multilingual model handles Hebrew but is heavier and conflicts with the V10 decision to remove Hebrew support. The English-only hybrid gives the highest accuracy for English content and reuses an existing model.

**Selected approach:** English-only hybrid.

- **Evidence:** `cross-encoder/ms-marco-MiniLM-L-6-v2` with sigmoid-normalized score.
- **Memory:** existing `sentence-transformers/all-MiniLM-L6-v2` bi-encoder with cosine similarity.

## Architecture

### Components

All components live in `tools/router_py/context_guard.py`.

#### 1. `EvidenceScorer`

- Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~91 MB on disk).
- Loads lazily on first use via a module-level singleton.
- Input: `(question: str, evidence: dict)`.
- Evidence text assembled from `title` + (`context` or `content`).
- Output: `float` in `[0.0, 1.0]`, computed as `sigmoid(raw_logit)`.
- Threshold: **0.50**.

#### 2. `MemoryScorer`

- Model: `sentence-transformers/all-MiniLM-L6-v2` (~80 MB), already used by `models/router/hybrid_router_v2.py`.
- Loads lazily on first use via a module-level singleton.
- Input: `(question: str, turn: str)`.
- Output: `float` in `[0.0, 1.0]`, cosine similarity between question and turn embeddings.
- Threshold: **0.20**.

#### 3. `KeywordFallbackScorer`

- Keeps the current keyword/entity logic from `context_guard.py`.
- Activates automatically when:
  - `sentence-transformers` is not installed.
  - A model fails to load (network, disk, incompatible environment).
  - A single inference call raises an exception.
- Guarantees the guard never crashes a request.

### Data flow

```
question
   ├─► EvidenceScorer ──► sigmoid(logit) ──► >= 0.50 ? keep : drop
   └─► MemoryScorer ────► cosine sim ──────► >= 0.20 ? keep : drop
```

- Evidence is filtered per-item before being added to the prompt.
- Memory text is split into turns (blank-line separated), scored individually, and rejoined.
- If no evidence or no memory turns survive filtering, the caller receives an empty result and skips injection.

## Integration points

1. **`execution_engine.py`**
   - Before injecting Wikipedia/news/augmented evidence, call `is_evidence_relevant(question, evidence)`.
   - Drop evidence that scores below 0.50.

2. **`local_answer.py`**
   - Before injecting session memory, call `filter_memory_context(question, memory_text)`.
   - Use the returned string only if non-empty.

## Error handling

| Failure | Behavior |
|---|---|
| `sentence-transformers` not installed | Module imports; all scoring falls back to keyword logic. |
| Model download fails on first use | Log warning; that scorer falls back to keyword logic. |
| Inference exception on one item | Score that item with keyword fallback; continue with others. |
| Empty evidence / empty turn | Score 0.0; item is dropped. |
| Very short/generic question | Keyword fallback handles it if semantic score is borderline. |

## Threshold rationale

- **Evidence 0.50:** Midpoint of the sigmoid scale. Empirically keeps correct evidence and drops wrong-entity evidence.
- **Memory 0.20:** Memory turns are short and may use pronouns. This threshold keeps paraphrased references while dropping unrelated topics.

Both thresholds are module-level constants so they can be tuned without changing call sites.

## Dependencies

- `sentence-transformers` — already installed in `ui-v10/.venv` (version 5.5.1).
- `torch` — already installed in `ui-v10/.venv`.
- Model weights downloaded from Hugging Face on first use, cached under `~/.cache/huggingface`, no API key.

## Testing plan

Update `tools/router_py/test_context_guard.py` to cover:

1. Evidence relevance
   - Japan tourism query rejects China evidence.
   - Japan tourism query accepts Japan evidence.
   - Quantum computing query accepts quantum evidence.
   - Unrelated evidence is dropped.

2. Memory relevance
   - Pronoun reference ("How does it work?") keeps the right prior turn.
   - Paraphrase ("Tell me more about Japan") keeps the Japan turn.
   - Stale China turn is dropped for a Tokyo follow-up.
   - Topic shift drops unrelated memory.

3. Fallback
   - Simulated missing model falls back to keyword logic.
   - Empty evidence returns 0.0.
   - Empty memory text returns empty string.

4. Regression
   - Existing keyword-guard tests still pass via the fallback path or equivalent behavior.

## Risks and mitigation

| Risk | Mitigation |
|---|---|
| First model load adds latency (~12 s cross-encoder) | Lazy load on first guard call, not at startup. |
| Model download requires internet once | Cache in `~/.cache/huggingface`; no re-download. |
| Cross-encoder negative scores confuse threshold | Sigmoid normalization maps everything to [0, 1]. |
| Threshold too aggressive drops valid memory | Threshold is a module constant; tune with tests. |

## Open questions

None at design time. Implementation plan to follow.
