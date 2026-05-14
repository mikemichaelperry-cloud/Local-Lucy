# Router Embedding Model Benchmark Report

**Date:** 2026-05-14  
**Benchmark script:** `models/router/evaluate_embedding_models.py` (read-only, no retraining)  
**Models compared:** ModernBERT-base [CLS] vs sentence-transformers all-MiniLM-L6-v2

---

## 1. Dataset Used

- **Source:** `models/router/comprehensive_examples.json`
- **Format:** Hand-labeled query → {route, intent_family, confidence} examples
- **Domain coverage:** Medical, financial, legal, news, time, weather, creative/local, evidence, edge cases
- **Split:** 90/10 train/test, random seed 42

---

## 2. Number of Prompts

| Split | Count |
|-------|-------|
| Total dataset | **645** |
| Training | **580** |
| Test | **65** |

Test set route distribution:

| Route | Count |
|-------|-------|
| LOCAL | 43 |
| AUGMENTED | 14 |
| EPHEMERAL | 5 |
| WEATHER | 2 |
| NEWS | 1 |
| TIME | 0 |

*Note: TIME had zero test examples due to random split; accuracy for TIME is unmeasured in this run.*

---

## 3. Accuracy by Route

### ModernBERT-base [CLS]

| Route | Correct / Total | Accuracy |
|-------|-----------------|----------|
| LOCAL | 39 / 43 | **90.7%** |
| AUGMENTED | 8 / 14 | **57.1%** |
| EPHEMERAL | 0 / 5 | **0.0%** |
| NEWS | 0 / 1 | **0.0%** |
| WEATHER | 0 / 2 | **0.0%** |
| **Overall** | 47 / 65 | **72.3%** |

### all-MiniLM-L6-v2

| Route | Correct / Total | Accuracy |
|-------|-----------------|----------|
| LOCAL | 36 / 43 | **83.7%** |
| AUGMENTED | 10 / 14 | **71.4%** |
| EPHEMERAL | 2 / 5 | **40.0%** |
| NEWS | 1 / 1 | **100.0%** |
| WEATHER | 0 / 2 | **0.0%** |
| **Overall** | 49 / 65 | **75.4%** |

### Intent Accuracy (finer-grained)

| Model | Intent Accuracy |
|-------|-----------------|
| ModernBERT-base [CLS] | **67.7%** |
| all-MiniLM-L6-v2 | **72.3%** |

### Short-Query Accuracy (< 5 words)

Both models: **77.8%** (28/36 correct)

---

## 4. Confusion Matrix

### ModernBERT-base [CLS]

| True \\ Pred | AUG | EPH | LOC | NEWS | TIME | WEATHER |
|-------------|:---:|:---:|:---:|:----:|:----:|:-------:|
| **AUGMENTED** | 8 | 1 | 4 | 0 | 1 | 0 |
| **EPHEMERAL** | 4 | 0 | 0 | 0 | 1 | 0 |
| **LOCAL** | 3 | 0 | 39 | 1 | 0 | 0 |
| **NEWS** | 1 | 0 | 0 | 0 | 0 | 0 |
| **TIME** | 0 | 0 | 0 | 0 | 0 | 0 |
| **WEATHER** | 1 | 0 | 1 | 0 | 0 | 0 |

### all-MiniLM-L6-v2

| True \\ Pred | AUG | EPH | LOC | NEWS | TIME | WEATHER |
|-------------|:---:|:---:|:---:|:----:|:----:|:-------:|
| **AUGMENTED** | 10 | 1 | 3 | 0 | 0 | 0 |
| **EPHEMERAL** | 0 | 2 | 2 | 1 | 0 | 0 |
| **LOCAL** | 4 | 0 | 36 | 2 | 1 | 0 |
| **NEWS** | 0 | 0 | 0 | 1 | 0 | 0 |
| **TIME** | 0 | 0 | 0 | 0 | 0 | 0 |
| **WEATHER** | 0 | 0 | 1 | 0 | 1 | 0 |

**Observations:**
- ModernBERT struggles with EPHEMERAL (0% accuracy) — it collapses EPHEMERAL queries into AUGMENTED.
- all-MiniLM shows better AUGMENTED recall (10/14 vs 8/14) and better EPHEMERAL recall (2/5 vs 0/5).
- Both models struggle with WEATHER (0/2 each), but this is a small sample.
- LOCAL is the strongest class for both models.

---

## 5. Latency

| Model | Train Encode (580 ex) | Test Encode (65 ex) | Per-Example Latency |
|-------|----------------------|---------------------|---------------------|
| ModernBERT-base [CLS] | 5.91s | 0.43s | **9.8 ms** |
| all-MiniLM-L6-v2 | 0.31s | 0.02s | **0.5 ms** |

**all-MiniLM is ~20× faster per example.** ModernBERT pays a significant latency penalty for its deeper transformer architecture.

---

## 6. RAM Usage

| Model | Peak RAM (50-example sample) | On-Disk Size |
|-------|------------------------------|--------------|
| ModernBERT-base [CLS] | ~0.2 MB (runtime working set) | **1,146 MB** |
| all-MiniLM-L6-v2 | ~0.1 MB (runtime working set) | **175 MB** |

**all-MiniLM is ~6.5× smaller on disk.** Both have negligible runtime RAM overhead during encoding; the dominant cost is model weights in GPU/CPU memory.

---

## 7. Failure Cases

### ModernBERT-base [CLS] — 18 failures (of 65)

Notable systematic errors:
- **EPHEMERAL → AUGMENTED/TIME:** "Is Apple trading up or down today?", "Current gold price per ounce", "Storm warning update", "Vote count update" all misclassified. ModernBERT collapses ephemeral/time-sensitive queries into AUGMENTED or TIME.
- **AUGMENTED → LOCAL:** "is it ilegal to park on teh sidewalk?" (typo-heavy legal query) and "How do I deal with burnout?" misrouted to LOCAL.
- **LOCAL → AUGMENTED:** "How do I change a tire?" and "Tips for improving focus" misrouted.
- **NEWS → AUGMENTED:** "Sports headlines today" misrouted.

### all-MiniLM-L6-v2 — 16 failures (of 65)

Notable systematic errors:
- **EPHEMERAL → LOCAL:** "Is Apple trading up or down today?" and "Current gold price per ounce" misrouted to LOCAL.
- **LOCAL → AUGMENTED:** "What is the CAP theorem?", "What is cryptocurrency?", "What does eGFR measure?" — factual/educational local queries misrouted.
- **WEATHER → LOCAL/TIME:** Both weather queries fail on both models.
- **AUGMENTED → LOCAL:** "How do I deal with burnout?" and "Systematic review of sleep and memory" misrouted.
- **LOCAL → NEWS:** "What is happening in Gaza right now?" and "Breaking news about my lunch" misrouted (news-keyword contamination).

### Shared weakness
Both models fail on:
- **Weather queries** (insufficient weather examples in training data)
- **"What is happening in Gaza right now?"** — misclassified as NEWS by both (arguably correct semantically, but labeled LOCAL in ground truth)
- **"Hello how are you?"** — labeled WEATHER in test set (suspicious ground truth; both models correctly route to LOCAL)

---

## 8. Recommendation

### Quantitative comparison

| Factor | ModernBERT | all-MiniLM | Winner |
|--------|-----------|------------|--------|
| Route accuracy | 72.3% | **75.4%** | all-MiniLM (+3.1pp) |
| Intent accuracy | 67.7% | **72.3%** | all-MiniLM (+4.6pp) |
| Short-query accuracy | 77.8% | 77.8% | Tie |
| Latency | 9.8 ms | **0.5 ms** | all-MiniLM (20× faster) |
| Disk size | 1,146 MB | **175 MB** | all-MiniLM (6.5× smaller) |
| AUGMENTED recall | 57.1% | **71.4%** | all-MiniLM |
| LOCAL recall | **90.7%** | 83.7% | ModernBERT |
| EPHEMERAL recall | 0.0% | **40.0%** | all-MiniLM |

### Verdict

**Do not switch yet.**

While all-MiniLM is faster, smaller, and slightly more accurate on this 90/10 split, the improvement is marginal (+3.1pp route accuracy) and comes with a regression on LOCAL recall (90.7% → 83.7%). The test set is small (65 examples), and the confidence intervals on these estimates are wide. A 3pp difference on 65 samples is not statistically significant.

More importantly, the production router uses **ModernBERT with keyword guards and hybrid routing logic** (see `hybrid_router.py`). The embedding model is only one component. The real-world accuracy of the full hybrid router is higher than the raw embedding accuracy reported here because keyword guards catch many edge cases (medical, legal, news triggers) that pure embeddings miss.

### Suggested next steps

1. **Collect more data for under-represented routes:** EPHEMERAL (5 test ex), WEATHER (2 test ex), TIME (0 test ex). The benchmark is starved of these classes.
2. **Re-run with stratified k-fold CV** (e.g., 5-fold) to get tighter confidence intervals instead of a single 90/10 split.
3. **Evaluate the full hybrid router** (ModernBERT + keyword guards) vs an all-MiniLM + same keyword guards hybrid to measure the *model-specific* delta in production conditions.
4. **Consider model distillation** if latency becomes critical: all-MiniLM is 20× faster, which may matter for high-throughput deployments.

---

## Appendix: Probe Set Results (14 known edge-case queries)

Both models: **92.9%** (13/14 correct)

Shared failure: **"Weather forecast"** → routed to LOCAL (ModernBERT) and AUGMENTED (all-MiniLM) instead of WEATHER. This is consistent with the test-set finding that weather queries are the weakest class.
