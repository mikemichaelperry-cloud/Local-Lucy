:# Local Lucy V10 — Current State Summary (2026-06-16)

## Architecture

**Embedding-first router** (`models/router/hybrid_router_v2.py`, MiniLM-L6-v2 k-NN) is the sole authority.
Legacy keyword router is preserved only for emergency rollback via `LUCY_ROUTER_LEGACY_PRIMARY=1`.

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
| Legacy Router | `tools/router_py/classify.py` | ROLLBACK ONLY — `LUCY_ROUTER_LEGACY_PRIMARY=1` |
| Background Learner | `models/router/background_learner.py` | ACTIVE — user-feedback only |
| Auto-Feedback | `models/router/auto_feedback.py` | TELEMETRY ONLY |
| Execution Engine | `tools/router_py/execution_engine.py` | STABLE — Python-native path |
| Local LLM | `local-lucy-llama31` (llama3.1:8b) via Ollama | DEFAULT |
| Web Adapter | `web_adapter/server.py` | OPTIONAL — disabled by default |

---

## Test Suite

```
942 passed, 19 skipped, 4 warnings, 177 subtests passed
```

`make lint` passes (`ruff` + `mypy`).

---

## Environment

- **LLM:** `local-lucy-llama31` (llama3.1:8b) on Ollama
- **Router:** MiniLM-L6-v2 embedding k-NN
- **System:** Python 3.10.12, PySide6 HMI
- **State:** XDG-compliant runtime under `~/.local/share/local-lucy`

---

## Rollback & Safety

| Mechanism | How |
|-----------|-----|
| Legacy rollback | `LUCY_ROUTER_LEGACY_PRIMARY=1` restores keyword router |
| High-stakes review | Medical/vet/finance/legal/conflicting feedback → `models/router/pending_review.jsonl` |
| Evidence policy | `tools/router_py/policy.py` forces evidence routes for high-risk queries |
| Web security | Loopback-only by default; auth required for LAN/Tailscale binds |

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
