# Local Lucy V8 — Current State Summary (2026-05-08)

## Architecture

**Single-path embedding router** (ModernBERT-base k-NN on CPU) is the sole primary.
Legacy keyword router preserved only for emergency rollback via `LUCY_ROUTER_LEGACY_PRIMARY=1`.

**Auto-feedback loop:** Execution engine analyzes answer quality after every query,
detects obvious misroutes heuristically, and feeds corrections to the background
learner for automatic index rebuild.

**Philosophy:** *Correct answer > locality. The end justifies the means.*

## Key Components

| Component | File | Status |
|-----------|------|--------|
| Embedding Router | `models/router/hybrid_router.py` | PRIMARY — 346 examples, 100% adversarial accuracy |
| Legacy Router | `tools/router_py/classify.py` | ROLLBACK ONLY — `LUCY_ROUTER_LEGACY_PRIMARY=1` |
| Auto-Feedback | `models/router/auto_feedback.py` | ACTIVE — detects misroutes from answer quality |
| Background Learner | `models/router/background_learner.py` | ACTIVE — rebuilds index from feedback + logs |
| Execution Engine | `tools/router_py/execution_engine.py` | STABLE — shell-free Python path |
| LLM | qwen3 14B via Ollama | ~9.8GB VRAM, Flash Attention, 2048 ctx |

## Test Suite

```
161 passed, 19 skipped, 0 failed
```

## Environment

- **Router:** ModernBERT-base on CPU (30–80ms/query, ~500MB RAM)
- **LLM:** qwen3 14B on RTX 3060 12GB
- **System:** 31GB RAM, Python 3.10.12
- **State:** Controlled dogfood, not production-ready

## Rollback & Safety

| Mechanism | How |
|-----------|-----|
| Legacy rollback | `LUCY_ROUTER_LEGACY_PRIMARY=1` restores keyword router |
| Legacy audit | Computed on every call (~1μs), logged, never returned |
| Router logs | `logs/router/router_decisions.jsonl` — full diagnostics |
| Auto-feedback | `models/router/auto_feedback.jsonl` — detected misroutes |
| User feedback | `models/router/user_feedback.jsonl` — explicit corrections |

## How to Rebuild Index

```bash
cd /home/mike/lucy-v9/models/router
python3 background_learner.py --process
```

## Repo

- **GitHub:** `mikemichaelperry-cloud/Local-Lucy`
- **Branch:** `main`
- **Snapshot:** `snapshots/opt-experimental-v9-dev/`
