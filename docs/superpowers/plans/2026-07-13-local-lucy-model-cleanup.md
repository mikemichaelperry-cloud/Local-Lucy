# Local Lucy Model Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all models except `gemma4:12b-it-qat` and `local-lucy-llama31` from Local Lucy's selectable/routing universe, while leaving every installed Ollama tag available to the chess program.

**Architecture:** Hard-coded surgical cleanup. The HMI selector, runtime CLI choices, auto-selector defaults, identity map, and environment defaults are trimmed to the allowed set. Removed Modelfiles are moved to `config/quarantined/` for reversibility. No dynamic allowlist is introduced.

**Tech Stack:** Python 3.10+, PySide6, Ollama HTTP API, pytest.

## Global Constraints

- Branch: `v10-dev` at `/home/mike/lucy-v10`.
- Do **not** run `ollama rm`; Ollama tags must remain installed for chess.
- Allowed Local Lucy backend tags: `auto`, `gemma4:12b-it-qat`, `local-lucy-llama31`.
- Gemma 4 smart-routing bypass must continue to work unchanged.
- Every code-changing task ends with a targeted test or verification command.
- Commit after each task.

---

## Task 1: Quarantine removed Modelfiles

**Files:**
- Create directory: `config/quarantined/`
- Move: `config/Modelfile.local-lucy`
- Move: `config/Modelfile.local-lucy-fast`
- Move: `config/Modelfile.local-lucy-stable`
- Move: `config/Modelfile.local-lucy-mem`
- Move: `config/Modelfile.local-lucy-qwen3`
- Move: `config/Modelfile.local-lucy-mistral`
- Move: `config/Modelfile.local-lucy-michael`
- Move: `config/Modelfile.local-lucy-mistral-michael`
- Move: `config/Modelfile.local-lucy-fast-michael`
- Move: `config/Modelfile.local-lucy-llama31-michael`
- Keep: `config/Modelfile.local-lucy-llama31`

**Interfaces:**
- Consumes: none.
- Produces: `config/quarantined/` directory with removed Modelfiles.

- [ ] **Step 1: Create quarantine directory**

```bash
mkdir -p /home/mike/lucy-v10/config/quarantined
```

- [ ] **Step 2: Move removed Modelfiles**

```bash
cd /home/mike/lucy-v10/config
mv Modelfile.local-lucy \
   Modelfile.local-lucy-fast \
   Modelfile.local-lucy-stable \
   Modelfile.local-lucy-mem \
   Modelfile.local-lucy-qwen3 \
   Modelfile.local-lucy-mistral \
   Modelfile.local-lucy-michael \
   Modelfile.local-lucy-mistral-michael \
   Modelfile.local-lucy-fast-michael \
   Modelfile.local-lucy-llama31-michael \
   quarantined/
```

- [ ] **Step 3: Verify only allowed Modelfiles remain in `config/`**

Run:

```bash
cd /home/mike/lucy-v10/config
ls -1 Modelfile*
```

Expected output (order may vary):

```text
Modelfile.local-lucy-llama31
```

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add config/quarantined/ config/Modelfile.local-lucy-llama31
git status --short
git commit -m "chore(config): quarantine non-Llama/non-Gemma Modelfiles

Move removed wrapper Modelfiles to config/quarantined/ so they cannot
be accidentally rebuilt, while keeping them available for restoration.
Keep only Modelfile.local-lucy-llama31 active."
```

---

## Task 2: Trim HMI model selector

**Files:**
- Modify: `ui-v10/app/panels/control_panel.py`

**Interfaces:**
- Consumes: none.
- Produces: `ControlPanel._MODEL_LABELS` with exactly three backend tags.

- [ ] **Step 1: Open the file and locate `_MODEL_LABELS`**

Read `/home/mike/lucy-v10/ui-v10/app/panels/control_panel.py` lines 53-61.

- [ ] **Step 2: Replace `_MODEL_LABELS`**

Old:

```python
    _MODEL_LABELS: dict[str, str] = {
        "auto": "Auto (Lucy chooses per query)",
        "local-lucy-llama31": "local-lucy-llama31 (llama3.1 8B)",
        "local-lucy": "local-lucy (qwen3 14B)",
        "local-lucy-fast": "local-lucy-fast (qwen3 14B)",
        "local-lucy-mistral": "local-lucy-mistral (mistral-nemo 12B)",
        "gemma4:12b-it-qat": "gemma4:12b-it-qat (gemma4 12B reasoning/multimodal)",
    }
```

New:

```python
    _MODEL_LABELS: dict[str, str] = {
        "auto": "Auto (Lucy chooses per query)",
        "local-lucy-llama31": "local-lucy-llama31 (llama3.1 8B)",
        "gemma4:12b-it-qat": "gemma4:12b-it-qat (gemma4 12B reasoning/multimodal)",
    }
```

- [ ] **Step 3: Run HMI off-screen test for model selector**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest ui-v10/tests/test_model_selector_offscreen.py -v
```

Expected: Tests pass; if they assert the old model count, update them in Task 8.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add ui-v10/app/panels/control_panel.py
git commit -m "feat(hmi): trim model selector to Gemma 4 and Llama 3.1

ControlPanel._MODEL_LABELS now exposes only auto, gemma4:12b-it-qat,
and local-lucy-llama31."
```

---

## Task 3: Trim runtime control CLI model choices

**Files:**
- Modify: `tools/runtime_control.py`

**Interfaces:**
- Consumes: none.
- Produces: `set-model --value` choices restricted to allowed tags.

- [ ] **Step 1: Open the file and locate the model choices**

Read `/home/mike/lucy-v10/tools/runtime_control.py` lines 164-176.

- [ ] **Step 2: Replace the `set-model` choices tuple**

Old:

```python
    model_parser.add_argument(
        "--value",
        required=True,
        choices=(
            "auto",
            "local-lucy-llama31",
            "local-lucy",
            "local-lucy-fast",
            "local-lucy-mistral",
            "gemma4:12b-it-qat",
        ),
    )
```

New:

```python
    model_parser.add_argument(
        "--value",
        required=True,
        choices=(
            "auto",
            "local-lucy-llama31",
            "gemma4:12b-it-qat",
        ),
    )
```

- [ ] **Step 3: Verify CLI rejects removed models**

Run:

```bash
cd /home/mike/lucy-v10
python3 tools/runtime_control.py set-model --value local-lucy-qwen3
```

Expected: `error: argument --value: invalid choice: 'local-lucy-qwen3'`

Run:

```bash
python3 tools/runtime_control.py set-model --value local-lucy-llama31
```

Expected: Success JSON output.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/runtime_control.py
git commit -m "feat(runtime_control): restrict set-model to allowed tags

set-model now accepts only auto, local-lucy-llama31, and gemma4:12b-it-qat."
```

---

## Task 4: Refactor automatic model selector

**Files:**
- Modify: `tools/router_py/model_selector.py`

**Interfaces:**
- Consumes: none.
- Produces: `select_model()` and `select_local_model()` return only allowed tags.

- [ ] **Step 1: Replace `_CAPABILITY_DEFAULTS`**

Old:

```python
_CAPABILITY_DEFAULTS: dict[str, str] = {
    "general": "local-lucy-llama31",
    "fast": "local-lucy-fast",
    "memory": "local-lucy-memory",
    "reasoning": "local-lucy-stable",
    "deep_thought": "qwen3:30b",
    "coding": "local-lucy-qwen3",
    "creative": "local-lucy-mistral",
}
```

New:

```python
_CAPABILITY_DEFAULTS: dict[str, str] = {
    "general": "local-lucy-llama31",
    "fast": "local-lucy-llama31",
    "memory": "local-lucy-llama31",
    "reasoning": "local-lucy-llama31",
    "deep_thought": "gemma4:12b-it-qat",
    "coding": "local-lucy-llama31",
    "creative": "local-lucy-llama31",
}
```

- [ ] **Step 2: Replace `_available_models` static fallback**

Old:

```python
    # Fallback static list for environments where ollama is not reachable.
    return {
        "local-lucy-llama31",
        "local-lucy",
        "local-lucy-fast",
        "local-lucy-stable",
        "local-lucy-qwen3",
        "local-lucy-mistral",
        "local-lucy-memory",
    }
```

New:

```python
    # Fallback static list for environments where ollama is not reachable.
    return {
        "local-lucy-llama31",
        "gemma4:12b-it-qat",
    }
```

- [ ] **Step 3: Simplify `select_model()` body**

Replace the entire conditional tree in `select_model()` (approximately lines 438-491) with:

```python
    recommended: str
    reason: str

    if bucket == "deep_thought":
        recommended = (
            _resolve_installed_tag("gemma4:12b-it-qat", installed) or "gemma4:12b-it-qat"
        )
        reason = "Deep-thought pattern; using Gemma 4"
    elif route_name in _FACTUAL_ROUTES:
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = f"{route_name} route requires factual accuracy; defaulting to Llama 3.1"
    elif _is_factual_current_query(query):
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = "Query asks for factual/current information; using Llama 3.1"
    else:
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = "General query; defaulting to Llama 3.1"
```

- [ ] **Step 4: Replace `_competing_model()` body**

Old:

```python
def _competing_model(recommended: str, installed: set[str]) -> str:
    """Pick a sensible competing model for shadow A/B comparisons."""
    base = _base_name(recommended)
    candidates: list[str] = []
    if base == "local-lucy-llama31":
        candidates = ["local-lucy-qwen3", "local-lucy-stable", "local-lucy-fast"]
    elif base in ("local-lucy-qwen3", "local-lucy"):
        candidates = ["local-lucy-llama31", "local-lucy-fast"]
    elif base == "local-lucy-fast":
        candidates = ["local-lucy", "local-lucy-llama31"]
    elif base == "local-lucy-memory":
        candidates = ["local-lucy-llama31"]
    elif base == "qwen3:30b":
        candidates = ["local-lucy-stable", "local-lucy-llama31"]
    elif base == "local-lucy-stable":
        candidates = ["qwen3:30b", "local-lucy-llama31"]
    else:
        candidates = ["local-lucy-llama31", "local-lucy-fast"]

    for cand in candidates:
        resolved = _resolve_installed_tag(cand, installed)
        if resolved:
            return resolved
    # Final fallback to the first installed model, or Llama 3.1.
    return next(iter(installed), "local-lucy-llama31")
```

New:

```python
def _competing_model(recommended: str, installed: set[str]) -> str:
    """Pick a sensible competing model for shadow A/B comparisons."""
    base = _base_name(recommended)
    candidates: list[str]
    if base == "gemma4:12b-it-qat":
        candidates = ["local-lucy-llama31"]
    else:
        candidates = ["gemma4:12b-it-qat"]

    for cand in candidates:
        resolved = _resolve_installed_tag(cand, installed)
        if resolved:
            return resolved
    # Final fallback to the first installed allowed model, or Llama 3.1.
    return next(iter(installed), "local-lucy-llama31")
```

- [ ] **Step 5: Trim `_LATENCY_BUDGETS_MS`**

Old:

```python
_LATENCY_BUDGETS_MS: dict[str, int] = {
    "local-lucy-fast": 3000,
    "local-lucy": 8000,
    "local-lucy-qwen3": 8000,
    "local-lucy-llama31": 5000,
    "local-lucy-stable": 8000,
    "local-lucy-memory": 5000,
    "local-lucy-mistral": 8000,
    "qwen3:30b": 25000,
}
```

New:

```python
_LATENCY_BUDGETS_MS: dict[str, int] = {
    "local-lucy-llama31": 5000,
    "gemma4:12b-it-qat": 12000,
}
```

- [ ] **Step 6: Update persona resolution fallback**

In `_resolve_persona_model()`, ensure that if the persona variant is not installed or not allowed, it falls back to the base model. The current code already falls back to `base_model` if the variant is not found. No change is required unless `_resolve_persona_model` is called with a removed base. Add an explicit allowed-base guard:

Old:

```python
def _resolve_persona_model(base_model: str, persona: str, available: set[str]) -> str:
    """Prefer a persona-tuned variant when one exists and is installed."""
    if not persona:
        return base_model
    persona = persona.strip().lower()
    candidate = f"{base_model}-{persona}"
    resolved = _resolve_installed_tag(candidate, available)
    if resolved:
        return resolved
    # Some older naming used the persona as a suffix on the root tag.
    resolved = _resolve_installed_tag(f"{base_model}-{persona}", available)
    if resolved:
        return resolved
    return base_model
```

New:

```python
_ALLOWED_PERSONA_BASES: frozenset[str] = frozenset({"local-lucy-llama31", "gemma4:12b-it-qat"})


def _resolve_persona_model(base_model: str, persona: str, available: set[str]) -> str:
    """Prefer a persona-tuned variant when one exists and is installed.

    Only the allowed base models may have active persona variants; otherwise
    fall back to the base model.
    """
    if not persona:
        return base_model
    base_model = _base_name(base_model)
    if base_model not in _ALLOWED_PERSONA_BASES:
        return base_model
    persona = persona.strip().lower()
    candidate = f"{base_model}-{persona}"
    resolved = _resolve_installed_tag(candidate, available)
    if resolved:
        return resolved
    return base_model
```

- [ ] **Step 7: Run model selector tests**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest tools/router_py/test_model_selector.py -v
```

Expected: Some tests fail because they assert removed-model outputs; note failures for Task 8.

- [ ] **Step 8: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/model_selector.py
git commit -m "feat(model_selector): restrict auto-selection to Gemma 4 and Llama 3.1

All capability buckets now resolve to local-lucy-llama31 except deep_thought,
which uses gemma4:12b-it-qat. Removed Qwen3/Mistral branches and budgets."
```

---

## Task 5: Update local answer identity map and defaults

**Files:**
- Modify: `tools/router_py/local_answer.py`

**Interfaces:**
- Consumes: none.
- Produces: `_MODEL_IDENTITIES` and heartbeat defaults use only allowed tags.

- [ ] **Step 1: Locate `_MODEL_IDENTITIES` and heartbeat defaults**

Use grep:

```bash
cd /home/mike/lucy-v10
grep -n "_MODEL_IDENTITIES\|start_ollama_heartbeat\|def _ollama_heartbeat_ping\|def _heartbeat_loop" tools/router_py/local_answer.py
```

- [ ] **Step 2: Trim `_MODEL_IDENTITIES` to allowed tags**

Old (representative):

```python
_MODEL_IDENTITIES: dict[str, tuple[str, str]] = {
    "local-lucy-llama31": ("Llama 3.1 8B", "8B"),
    "local-lucy": ("Qwen3 14B", "14B"),
    "local-lucy-fast": ("Qwen3 14B fast", "14B"),
    "gemma4:12b-it-qat": ("Gemma 4 12B", "12B"),
    # ... etc
}
```

New:

```python
_MODEL_IDENTITIES: dict[str, tuple[str, str]] = {
    "local-lucy-llama31": ("Llama 3.1 8B", "8B"),
    "local-lucy-llama31:latest": ("Llama 3.1 8B", "8B"),
    "gemma4:12b-it-qat": ("Gemma 4 12B", "12B"),
}
```

- [ ] **Step 3: Update heartbeat defaults**

Locate `start_ollama_heartbeat` default argument and `_ollama_heartbeat_ping` default argument. If they default to `local-lucy-llama31`, no change needed. If they default to any removed tag, change to `local-lucy-llama31`.

- [ ] **Step 4: Run local answer tests**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest tools/router_py/test_local_answer.py -v
```

Expected: Some tests may fail due to removed-model expectations; note for Task 8.

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/local_answer.py
git commit -m "feat(local_answer): trim identity map to allowed models

_MODEL_IDENTITIES now only maps local-lucy-llama31 and gemma4:12b-it-qat."
```

---

## Task 6: Update runtime bridge environment defaults

**Files:**
- Modify: `ui-v10/app/services/runtime_bridge.py`

**Interfaces:**
- Consumes: none.
- Produces: Default `LUCY_MODEL`, `LUCY_LOCAL_MODEL`, and `LUCY_OLLAMA_MODEL` env values use `local-lucy-llama31`.

- [ ] **Step 1: Locate default env setdefault calls**

Read `/home/mike/lucy-v10/ui-v10/app/services/runtime_bridge.py` lines 280-287.

- [ ] **Step 2: Update defaults**

Old:

```python
        env.setdefault("LUCY_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31"))
        env.setdefault("LUCY_LOCAL_MODEL", os.environ.get("LUCY_LOCAL_MODEL", "local-lucy-llama31"))
        # Ollama model used by the memory service for summarization/embedding fallback
        env.setdefault(
            "LUCY_OLLAMA_MODEL",
            os.environ.get("LUCY_OLLAMA_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31")),
        )
```

New (same values, but add a comment documenting the constraint):

```python
        # Default to the single allowed fast Llama wrapper.
        env.setdefault("LUCY_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31"))
        env.setdefault("LUCY_LOCAL_MODEL", os.environ.get("LUCY_LOCAL_MODEL", "local-lucy-llama31"))
        # Ollama model used by the memory service for summarization/embedding fallback
        env.setdefault(
            "LUCY_OLLAMA_MODEL",
            os.environ.get("LUCY_OLLAMA_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31")),
        )
```

If any default in the file references a removed tag (e.g., `local-lucy`, `local-lucy-fast`), change it to `local-lucy-llama31`.

- [ ] **Step 3: Grep for removed tags in runtime_bridge**

Run:

```bash
cd /home/mike/lucy-v10
grep -nE "local-lucy-fast|local-lucy-stable|local-lucy-mem|local-lucy-qwen3|local-lucy-mistral|qwen3:30b|mistral-nemo" ui-v10/app/services/runtime_bridge.py || true
```

Expected: No matches. If any remain, update them.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add ui-v10/app/services/runtime_bridge.py
git commit -m "feat(runtime_bridge): default env to allowed Llama wrapper

Ensure LUCY_MODEL, LUCY_LOCAL_MODEL, and LUCY_OLLAMA_MODEL default to
local-lucy-llama31, the single allowed fast Llama wrapper."
```

---

## Task 7: Audit and update pipeline defaults

**Files:**
- Modify: `tools/router_py/main.py`
- Modify: `tools/router_py/request_pipeline.py`
- Modify: any other file with hard-coded removed-model defaults

**Interfaces:**
- Consumes: none.
- Produces: Pipeline defaults and fallback strings use only allowed tags.

- [ ] **Step 1: Grep for removed tags across router_py**

Run:

```bash
cd /home/mike/lucy-v10
grep -rnE "local-lucy-fast|local-lucy-stable|local-lucy-mem|local-lucy-qwen3|local-lucy-mistral|qwen3:30b|mistral-nemo" tools/router_py/ || true
```

- [ ] **Step 2: Update any hard-coded defaults**

For each match, decide whether it is a default model string or a reference in a test/golden file. Update defaults to `local-lucy-llama31` or `gemma4:12b-it-qat` as appropriate. Do not modify test files in this task (handled in Task 8).

Common patterns to fix:

```python
# Old
DEFAULT_MODEL = "local-lucy"
# New
DEFAULT_MODEL = "local-lucy-llama31"
```

```python
# Old
fallback_model = "local-lucy-stable"
# New
fallback_model = "local-lucy-llama31"
```

- [ ] **Step 3: Verify no stray defaults remain**

Run the grep again:

```bash
cd /home/mike/lucy-v10
grep -rnE "local-lucy-fast|local-lucy-stable|local-lucy-mem|local-lucy-qwen3|local-lucy-mistral|qwen3:30b|mistral-nemo" tools/router_py/main.py tools/router_py/request_pipeline.py || true
```

Expected: No matches in production files.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/main.py tools/router_py/request_pipeline.py
git commit -m "feat(router): remove stray defaults to removed models

Audit main.py and request_pipeline.py for hard-coded references to
Qwen3/Mistral/legacy wrappers and redirect defaults to the allowed set."
```

---

## Task 8: Update existing tests and add regression test

**Files:**
- Modify: `tools/router_py/test_model_selector.py`
- Modify: `tools/router_py/test_local_answer.py`
- Modify: `ui-v10/tests/test_model_selector_offscreen.py`
- Create: `tools/router_py/test_allowed_models_only.py`

**Interfaces:**
- Consumes: `ControlPanel._MODEL_LABELS`, `runtime_control.build_parser`, `model_selector.select_model`.
- Produces: Passing tests that enforce the allowed model universe.

- [ ] **Step 1: Update `test_model_selector.py` expectations**

For each test that asserts a removed model (e.g., `local-lucy-qwen3`, `local-lucy-stable`, `qwen3:30b`, `local-lucy-mistral`), change the expected model to either `local-lucy-llama31` or `gemma4:12b-it-qat` based on the query bucket described in the test name.

Example rewrite:

```python
# Old
def test_coding_query_uses_qwen3():
    result = select_model("Write a Python function", route="LOCAL")
    assert result["recommended"] == "local-lucy-qwen3"

# New
def test_coding_query_uses_llama31():
    result = select_model("Write a Python function", route="LOCAL")
    assert result["recommended"] == "local-lucy-llama31"
```

- [ ] **Step 2: Update `test_local_answer.py` expectations**

Similarly update any test in `tools/router_py/test_local_answer.py` that asserts identity strings or model names for removed tags.

- [ ] **Step 3: Update `test_model_selector_offscreen.py` expectations**

Update the off-screen HMI test to expect only three model options in the selector.

- [ ] **Step 4: Create `tools/router_py/test_allowed_models_only.py`**

Create the file with the following content:

```python
"""Regression tests ensuring Local Lucy's active model universe is locked
to the allowed set."""

from __future__ import annotations

import sys
from pathlib import Path

# Make tools/router_py importable.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from router_py import model_selector
from router_py.request_types import RoutingDecision


def test_hmi_model_labels_limited_to_allowed_set():
    # Import the control panel from the HMI tree.
    ui_root = Path(__file__).resolve().parents[2] / "ui-v10"
    sys.path.insert(0, str(ui_root))
    from app.panels.control_panel import ControlPanel

    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert set(ControlPanel._MODEL_LABELS.keys()) == allowed


def test_runtime_control_model_choices_limited_to_allowed_set():
    # Import runtime_control from the tools tree.
    tools_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(tools_root))
    import importlib

    runtime_control = importlib.import_module("runtime_control")
    parser = runtime_control.build_parser()
    model_parser = [a for a in parser._subparsers._actions if hasattr(a, "choices")][0]
    choices = model_parser.choices["set-model"]._actions[1].choices
    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert set(choices) == allowed


@pytest.mark.parametrize(
    "query,route_name,intent_family",
    [
        ("What is the capital of France?", "AUGMENTED", "factual"),
        ("Write a Python function", "LOCAL", ""),
        ("What did we discuss earlier?", "LOCAL", ""),
        ("Solve 2+2", "LOCAL", ""),
        ("Explain step by step", "LOCAL", ""),
        ("Give me a deep analysis of climate change", "LOCAL", ""),
    ],
)
def test_select_model_never_recommends_removed_tag(query, route_name, intent_family):
    route = RoutingDecision(route=route_name, intent_family=intent_family)
    result = model_selector.select_model(query, route=route)
    allowed = {"auto", "gemma4:12b-it-qat", "local-lucy-llama31"}
    assert result["recommended"] in allowed
    assert result["competing"] in allowed


def test_select_local_model_respects_pinned_allowed_model():
    result = model_selector.select_local_model(
        "hello",
        context={"local_model": "gemma4:12b-it-qat"},
        available=["local-lucy-llama31", "gemma4:12b-it-qat"],
    )
    assert result == "gemma4:12b-it-qat"
```

- [ ] **Step 5: Run the new regression test**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest tools/router_py/test_allowed_models_only.py -v
```

Expected: PASS.

- [ ] **Step 6: Run updated model selector tests**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest tools/router_py/test_model_selector.py -v
```

Expected: PASS after updates.

- [ ] **Step 7: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/test_model_selector.py \
        tools/router_py/test_local_answer.py \
        ui-v10/tests/test_model_selector_offscreen.py \
        tools/router_py/test_allowed_models_only.py
git commit -m "test(model_cleanup): update expectations and add allowed-model regression

Existing tests now expect local-lucy-llama31 or gemma4:12b-it-qat.
New test_allowed_models_only.py enforces the HMI, CLI, and selector
never expose removed models."
```

---

## Task 9: Sweep remaining references

**Files:**
- Audit: entire `lucy-v10/` tree (excluding `.git`, backups, archived docs)

**Interfaces:**
- Consumes: none.
- Produces: No production references to removed tags remain.

- [ ] **Step 1: Grep for removed model names**

Run:

```bash
cd /home/mike/lucy-v10
grep -rnE "local-lucy-fast|local-lucy-stable|local-lucy-mem[^o]|local-lucy-qwen3|local-lucy-mistral" \
  --include="*.py" --include="*.sh" --include="*.md" --include="*.yaml" --include="*.json" \
  --exclude-dir=.git --exclude-dir=backups --exclude-dir=docs/handoffs/archive --exclude-dir=docs/superpowers/specs \
  . || true
```

- [ ] **Step 2: Triage each match**

For each match:
- If it is in a production Python/Shell/config file, update it.
- If it is in an archived handoff or spec, leave it.
- If it is in a quarantined Modelfile, leave it.
- If it is in a test that should now expect an allowed model, update it.

- [ ] **Step 3: Run broad test suite**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest tools/router_py/ -q
```

Expected: All tests pass except possibly semantic-regression goldens that are model-sensitive (per handoff note); those should be reviewed, not blindly fixed.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "chore(cleanup): sweep remaining references to removed models

Grep-based audit of production files; update stragglers to the allowed
model universe."
```

---

## Task 10: Final verification

**Files:**
- Verify: HMI, runtime CLI, Ollama inventory, targeted regression battery.

**Interfaces:**
- Consumes: all previous tasks.
- Produces: Verification report.

- [ ] **Step 1: Confirm Ollama inventory is unchanged**

Run:

```bash
ollama list
```

Expected: All previous tags still present (including `local-lucy`, `qwen3:*`, `mistral-nemo`, etc.).

- [ ] **Step 2: Confirm runtime CLI accepts only allowed tags**

Run:

```bash
cd /home/mike/lucy-v10
python3 tools/runtime_control.py set-model --value local-lucy-qwen3 2>&1 | grep -q "invalid choice"
echo "Rejected removed tag: OK"
python3 tools/runtime_control.py set-model --value gemma4:12b-it-qat >/dev/null
echo "Accepted Gemma 4: OK"
python3 tools/runtime_control.py set-model --value local-lucy-llama31 >/dev/null
echo "Accepted Llama 3.1: OK"
```

Expected: All three checks report OK.

- [ ] **Step 3: Run targeted regression battery**

Run:

```bash
cd /home/mike/lucy-v10
python3 -m pytest \
  tools/router_py/test_gemma4_identity.py \
  tools/router_py/test_ollama_heartbeat_model_switch.py \
  tools/tests/test_gemma4_smart_routing_state.py \
  ui-v10/tests/test_gemma4_smart_routing_offscreen.py \
  tools/router_py/test_request_pipeline.py \
  tools/router_py/test_allowed_models_only.py -q
```

Expected: PASS.

- [ ] **Step 4: HMI smoke test (optional but recommended)**

Start Local Lucy:

```bash
cd /home/mike/lucy-v10
bash START_LUCY.sh
```

Open the Engineering panel, confirm the model selector contains only:
- Auto (Lucy chooses per query)
- local-lucy-llama31 (llama3.1 8B)
- gemma4:12b-it-qat (gemma4 12B reasoning/multimodal)

Submit a test query and confirm a response is generated.

- [ ] **Step 5: Final commit and handoff note**

If the smoke test passes:

```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "feat(model_cleanup): finalize Local Lucy model universe to Gemma 4 + Llama 3.1

HMI, runtime CLI, auto-selector, identity map, env defaults, and tests
now restrict Local Lucy to auto, gemma4:12b-it-qat, and local-lucy-llama31.
Removed Modelfiles moved to config/quarantined/. Ollama inventory left
untouched so chess retains access to all installed tags."
```

---

## Self-Review Checklist

- [ ] Spec coverage: every section of `2026-07-13-local-lucy-model-cleanup-design.md` maps to at least one task.
- [ ] No placeholders: every step has exact commands or code.
- [ ] Type consistency: `RoutingDecision`, `select_model`, `_MODEL_LABELS`, and `set-model` choices all use the same allowed tag strings.
- [ ] Chess isolation: no task runs `ollama rm`.
- [ ] Gemma 4 smart routing: Tasks 4 and 5 preserve it.
