# Local Lucy V11 Session Handoff

**Date:** 2026-07-09
**Branch:** `v10-dev`
**Latest commit:** `538bc35` — refactor(runtime): replace critical shell/subprocess calls with Python
**Written for:** Next Kimi / Codex / Grok session
**Primary runtime:** English-only

---

## 1. State at Handoff

We are continuing the V11 consolidation/release. The big cleanup of the day is complete and committed: the execution engine is now Python-native only.

- **Repository is clean** on `v10-dev`.
- **Tests pass:** `make test` → 1,062 passed, 34 skipped, 1 deselected (1 unrelated flaky whisper CLI test; passes in isolation).
- **Barrage stable:** 56 queries, 44 passed, 12 failed — same as before the cleanup.
- **HMI/backend sync verified:** the UI calls the same canonical `ExecutionEngine` as the router tests.

---

## 2. What Was Just Done

- Removed all shell-based fallback paths from `tools/router_py/execution_engine.py`.
- Removed the `use_python_path` toggle; Python-native execution is now the only path.
- Deleted `tools/router_py/test_escalation_trigger.py` (shell-only test).
- Updated callers/tests that passed `use_python_path=True`.
- Replaced critical runtime shell/subprocess calls with Python:
  - `timedatectl` → Python timezone detection.
  - `nvidia-smi` / `curl` → `nvidia-ml-py` / `urllib`.
  - `ollama list` / `ollama stop` → Ollama HTTP API.
  - Provider subprocess hops (`current_time_tool`, `unverified_context_kimi/openai`, `search_web`) → direct imports.
  - `runtime_request.py` shell fallbacks → direct `router_py.main.run()` calls.
  - HMI `runtime_bridge.py` Python-on-Python subprocess hops → direct function calls.
  - `run_fetch_with_gate.sh` → new `tools/internet/fetch_gate.py` (shell kept as thin wrapper).
- Reverted an accidental background-learning mutation in `models/router/comprehensive_examples.json`.
- Archived stale V11 handoffs/reports on the desktop.

---

## 3. Read-First Files

Before making changes, read these:

1. `/home/mike/lucy-v10/Architecture.md`
2. `/home/mike/lucy-v10/Desktop/Local_Lucy_V11_Status_Report_2026-07-09.md`
3. `/home/mike/lucy-v10/tools/router_py/run_barrage_validation.py`
4. `/home/mike/lucy-v10/tools/router_py/policy_router.py`
5. `/home/mike/lucy-v10/tools/router_py/classify.py`
6. `/home/mike/lucy-v10/tools/router_py/execution_engine.py` (now ~2,216 lines)

---

## 4. Next Task Queue

Pick from the top. Do **not** start broad refactors or HMI redesigns until routing calibration is done.

### 4.1 Routing calibration (priority)

Fix the 12 failing barrage cases. The failures are documented in `/tmp/lucy_barrage_validation_report.md` and summarised in the desktop status report.

Key examples:

- Stable knowledge routed to AUGMENTED/EVIDENCE:
  - "What is the capital of France?" → expected LOCAL
  - "What is the capital of Japan?" → expected LOCAL
  - "At what temperature does water boil at sea level?" → expected LOCAL
  - "What does DNA stand for?" → expected LOCAL
- Coding/reasoning routed to EVIDENCE:
  - "How do you sort a list of dictionaries by a key in Python?" → expected LOCAL
  - "A farmer needs to cross a river..." → expected LOCAL
  - "Is 17 a prime number?" → expected LOCAL
- Medical/vet/legal not using evidence:
  - "What is a normal blood pressure range?" → expected EVIDENCE
  - "What are my rights as a tenant in California?" → expected EVIDENCE
- Adversarial:
  - "Is it snowing in Helsinki?" → expected WEATHER
  - "What was the price of gold during the Roman Empire?" → expected LOCAL
  - "What is your opinion on the latest political scandal?" → expected LOCAL

Approach:

- Change `policy_router.py` gates and thresholds.
- Avoid changing `execution_engine.py` unless a concrete bug is found.
- Re-run `run_barrage_validation.py` after every change and check for regressions.
- Do not tune prompts blindly; use barrage results as evidence.

### 4.2 HMI persona/model selector bug

In the Engineering Interface, selecting the Michael persona toggle jumps back to Auto. Investigate `ui-v10/app/panels/control_panel.py` and related state logic.

### 4.3 Shadow model selection data collection

The Auto selector is in shadow mode. Collect 50–100 real queries, log:

- Auto recommendation
- Manual choice
- End-to-end latency
- Answer preference in blind A/B

Do not make Auto the default until shadow data is strong.

### 4.4 Latency optimisation

Only after routing is stable. Targets:

- Reduce Ollama unload/reload cycles on the RTX 3060.
- Investigate voice-stack latency (Whisper CPU, TTS CPU/CUDA).
- Profile `execution_engine.py` and `local_answer.py`.

---

## 5. Constraints

- **English-only primary runtime.** Hebrew / Racheli work is a separate system.
- **No broad refactors** of `execution_engine.py`.
- **No HMI simplification beyond the current two-view design** until routing calibration is >90% green with no high-stakes misses.
- **Manual model selector remains the default.** Auto selection stays in shadow mode.
- **OpenAI/Kimi are synthesis providers, not evidence sources.**
- **All changes must pass `make test` and the barrage** before committing.

---

## 6. Verification Commands

```bash
cd /home/mike/lucy-v10

# Full constrained suite
make test

# Routing barrage
python3 tools/router_py/run_barrage_validation.py \
  --output-jsonl /tmp/lucy_barrage_validation.jsonl \
  --output-report /tmp/lucy_barrage_validation_report.md

# HMI/backend sync smoke test
ui-v10/.venv/bin/python3 -m pytest -q tools/router_py/test_hmi_backend_sync.py

# End-to-end single query through HMI backend
ui-v10/.venv/bin/python3 - <<'PY'
import os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "app"))
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v10"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"))
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")
from app.backend import execute_plan_python
result = execute_plan_python("What is 2+2?")
print(result.route, result.status, result.response_text[:60])
assert result.status == "completed" and "4" in result.response_text
PY
```

---

## 7. Useful Context

- Hardware: RTX 3060 12 GB, 32 GB RAM.
- Ollama models: `local-lucy` (Llama 3.1 8B default), Qwen3, Mistral NeMo, fast variants.
- `OLLAMA_KEEP_ALIVE=0` is set in the test environment to reduce VRAM contention.
- The desktop has a fresh `Local_Lucy_V11_Status_Report_2026-07-09.md` and `Local_Lucy_V11_Architecture_2026-07-09.md`.

---

*End of handoff.*
