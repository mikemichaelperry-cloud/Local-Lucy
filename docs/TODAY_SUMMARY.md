# Local Lucy V10 — Current State Summary (2026-07-16)

## Architecture

**Embedding-first router** (`models/router/hybrid_router_v2.py`, MiniLM-L6-v2 k-NN) is the sole authority.
The legacy keyword-router rollback option (`LUCY_ROUTER_LEGACY_PRIMARY=1`) is deprecated and no longer functional in V10.

**Feedback loop:** Only explicit user corrections are ingested by the background learner.
Auto-feedback and router logs are telemetry-only and never mutate the model unsupervised.

**Interfaces:**
- PySide6 desktop HMI (`ui-v10/app/`) — primary local interface
- CLI chat (`lucy_chat.sh`)
- Optional HTTP web interface (`web_adapter/`) — stateless, request-scoped model selection, token auth
- Direct Python API (`tools/router_py/main.py::execute_plan_python`)

**Philosophy:** *Facts only, no evasion, no political correctness. The AI does what the user asks.*

---

## Key Components

| Component | File | Status |
|-----------|------|--------|
| Embedding Router | `models/router/hybrid_router_v2.py` | PRIMARY — ~1,019 examples |
| Safety Guards | `tools/router_py/classify.py` | ACTIVE — safety-critical keyword guards only |
| Background Learner | `models/router/background_learner.py` | ACTIVE — user-feedback only |
| Auto-Feedback | `models/router/auto_feedback.py` | TELEMETRY ONLY |
| Execution Engine | `tools/router_py/execution_engine.py` | STABLE — Python-native path |
| Local LLM | `local-lucy-llama31` (llama3.1:8b) via Ollama | DEFAULT |
| Self-Analysis Engine | `tools/router_py/self_analysis.py` | ACTIVE — large-file / large-response support added |
| Web Adapter | `web_adapter/server.py` | OPTIONAL — disabled by default |

---

## Test Suite

```
79 passed (tools/router_py/test_self_analysis.py + tools/router_py/test_local_answer.py)
```

`make lint` passes (`ruff` + `mypy`).

---

## Environment

- **LLM:** `local-lucy-llama31` (llama3.1:8b) on Ollama
- **Router:** MiniLM-L6-v2 embedding k-NN
- **System:** Python 3.10.12, PySide6 HMI
- **State:** XDG-compliant runtime under `~/.local/share/local-lucy`
- **Self-review env vars:** `LUCY_SELF_REVIEW_MAX_TOKENS` (default 4096), `LUCY_SELF_REVIEW_CONTEXT_CHARS` (default 100000)

---

## Rollback & Safety

| Mechanism | How |
|-----------|-----|
| Deprecated rollback | `LUCY_ROUTER_LEGACY_PRIMARY=1` is deprecated; embedding router is the sole authority |
| High-stakes review | Medical/vet/finance/legal/conflicting feedback → `models/router/pending_review.jsonl` |
| Evidence policy | `tools/router_py/policy.py` forces evidence routes for high-risk queries |
| Web security | Loopback-only by default; auth required for LAN/Tailscale binds |
| Self-analysis file safety | 5 MB read cap, directory rejection, path-traversal guard, TOCTOU-safe bounded read |

---

## How to Rebuild the Router Index

```bash
cd /home/mike/lucy-v10/models/router
python3 background_learner.py --process
```

---

## Repo

- **GitHub:** `mikemichaelperry-cloud/Local-Lucy`
- **Branch:** `v10-dev` (default)
- **Latest tag:** `v10.0.0-beta.1`
- **Latest commit:** `b3c84b5 docs: update SESSION_CONTEXT.md after self-analysis large-file support`
