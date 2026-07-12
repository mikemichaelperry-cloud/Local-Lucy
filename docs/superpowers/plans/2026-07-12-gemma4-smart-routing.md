# Gemma 4 Smart Routing + Low-VRAM Warning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional HMI toggle that lets Gemma 4 bypass Local Lucy’s classifier/router layers while preserving news/evidence fast paths, plus a low-VRAM warning when Gemma 4 is selected.

**Architecture:** A new `gemma4_smart_routing` boolean is stored in `current_state.json`, propagated through `runtime_bridge.py` to env, and consumed by `request_pipeline.py`. When the active model is a Gemma 4 tag and the flag is on, the pipeline constructs a minimal `ClassificationResult` + `RoutingDecision` for `LOCAL` instead of calling the full classifier/router, unless an explicit route prefix or deterministic fast path matches. A reusable VRAM helper in `local_answer.py` reports free GPU memory for the HMI warning.

**Tech Stack:** Python 3.10, PySide6, Ollama API, `subprocess` / `pynvml` for VRAM probing.

## Global Constraints

- Toggle default is **off**; existing behavior must be unchanged when off.
- Only applies when the selected local model matches `gemma4:*`.
- Explicit prefixes (`news:`, `evidence:`, `augmented:`) always win.
- Existing news/evidence pattern fast paths remain active.
- CPU/RAM fallback must not be blocked; Ollama handles offloading automatically.
- No GPU-only options may be forced for Gemma 4.

---

## File map

| File | Responsibility |
|---|---|
| `tools/router_py/local_answer.py` | Reusable VRAM detection helper (`_get_gpu_free_vram_mb`). |
| `ui-v10/app/panels/control_panel.py` | New `gemma4_smart_routing` checkbox + VRAM warning label. |
| `ui-v10/app/services/runtime_bridge.py` | Persist/read `gemma4_smart_routing` in `current_state.json` + env var. |
| `tools/router_py/request_pipeline.py` | Bypass classifier/router when toggle is on and model is Gemma 4. |
| `tools/router_py/test_request_pipeline.py` | Unit tests for bypass logic. |

---

## Task 1: VRAM detection helper

**Files:**
- Modify: `tools/router_py/local_answer.py:1840-1850` (near `_is_thinking_model`)
- Test: `tools/router_py/test_local_answer.py` (existing)

**Interfaces:**
- Produces: `get_gpu_free_vram_mb() -> int | None` — returns free VRAM in MB or `None` if detection fails.

- [ ] **Step 1: Write the failing test**

```python
def test_get_gpu_free_vram_mb_returns_int_or_none():
    result = get_gpu_free_vram_mb()
    assert result is None or isinstance(result, int)
    if result is not None:
        assert result >= 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_local_answer.py::test_get_gpu_free_vram_mb_returns_int_or_none -v`
Expected: FAIL with `NameError: name 'get_gpu_free_vram_mb' is not defined`

- [ ] **Step 3: Write minimal implementation**

Add near `_is_thinking_model` in `tools/router_py/local_answer.py`:

```python
def get_gpu_free_vram_mb() -> int | None:
    """Return free NVIDIA VRAM in MB, or None if not detectable."""
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        return int(info.free // (1024 * 1024))
    except Exception:
        pass
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            return int(out.stdout.strip().split("\n")[0].strip())
    except Exception:
        pass
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_local_answer.py::test_get_gpu_free_vram_mb_returns_int_or_none -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/local_answer.py tools/router_py/test_local_answer.py
git commit -m "feat(gpu): reusable free-VRAM helper for HMI warnings"
```

---

## Task 2: HMI checkbox + VRAM warning

**Files:**
- Modify: `ui-v10/app/panels/control_panel.py:234-296`, `:640-680`, `:940-960`

**Interfaces:**
- Consumes: `get_gpu_free_vram_mb()` from `tools/router_py/local_answer.py`
- Produces: `gemma4_smart_routing_change_requested = Signal(str)`
- Produces: `_gemma4_smart_routing_selector: QCheckBox`
- Produces: `_gemma4_vram_warning_label: QLabel`

- [ ] **Step 1: Add signal and UI widgets**

In `ControlPanel` signal block (around line 38), add:

```python
gemma4_smart_routing_change_requested = Signal(str)
```

In `__init__` `_current_values` (around line 94), add:

```python
"gemma4_smart_routing": "",
```

After `_model_selector` creation (around line 236), add:

```python
from PySide6.QtWidgets import QCheckBox

self._gemma4_smart_routing_selector = QCheckBox("Gemma 4 Smart Routing")
self._gemma4_smart_routing_selector.setToolTip(
    "When on and Gemma 4 is selected, bypass the classifier/router and let Gemma 4 route internally."
)
self._gemma4_smart_routing_selector.stateChanged.connect(
    self._handle_gemma4_smart_routing_changed
)

self._gemma4_vram_warning_label = QLabel("")
self._gemma4_vram_warning_label.setWordWrap(True)
self._gemma4_vram_warning_label.setObjectName("cardValue")
```

Add to engineering layout after model selector (around line 287):

```python
layout.addWidget(self._build_labeled_row("model", self._model_selector))
layout.addWidget(self._gemma4_smart_routing_selector)
layout.addWidget(self._gemma4_vram_warning_label)
```

- [ ] **Step 2: Add handler and warning update logic**

Add methods near `_handle_model_activated`:

```python
def _handle_gemma4_smart_routing_changed(self, state: int) -> None:
    value = "on" if state == 2 else "off"
    self._emit_if_changed(
        "gemma4_smart_routing",
        value,
        self.gemma4_smart_routing_change_requested,
    )

def _update_gemma4_smart_routing_visibility(self, model: str) -> None:
    is_gemma = bool(model) and model.lower().startswith("gemma4")
    self._gemma4_smart_routing_selector.setEnabled(is_gemma)
    if not is_gemma:
        self._gemma4_vram_warning_label.setText("")
        self._gemma4_vram_warning_label.setVisible(False)
        return
    free_vram_mb = get_gpu_free_vram_mb()
    if free_vram_mb is not None and free_vram_mb < 12 * 1024:
        self._gemma4_vram_warning_label.setText(
            "Warning: Gemma 4 12B may be tight on this GPU. "
            "Short conversations are fine; long context or concurrent models may hit VRAM limits. "
            "Ollama can fall back to system RAM, but responses will be slower."
        )
        self._gemma4_vram_warning_label.setVisible(True)
    else:
        self._gemma4_vram_warning_label.setText("")
        self._gemma4_vram_warning_label.setVisible(False)
```

- [ ] **Step 3: Wire into existing refresh/update paths**

In `update_control_state` around line 676, after setting model selector value, add:

```python
smart_routing = values.get("gemma4_smart_routing", "off")
if self._gemma4_smart_routing_selector is not None:
    self._gemma4_smart_routing_selector.setChecked(smart_routing == "on")
self._update_gemma4_smart_routing_visibility(values.get("model", ""))
```

In `_handle_model_activated`, after emitting, call:

```python
self._update_gemma4_smart_routing_visibility(model_value)
```

- [ ] **Step 4: Run HMI import/smoke test**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -c "from app.panels.control_panel import ControlPanel; print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v10
git add ui-v10/app/panels/control_panel.py
git commit -m "feat(hmi): Gemma 4 smart-routing toggle and low-VRAM warning"
```

---

## Task 3: Persist toggle in runtime_bridge

**Files:**
- Modify: `ui-v10/app/services/runtime_bridge.py:559-587`, `:625-640`

**Interfaces:**
- Consumes: `gemma4_smart_routing_change_requested` signal from `ControlPanel`
- Produces: `LUCY_GEMMA4_SMART_ROUTING` env var set in `_apply_state_to_env()`

- [ ] **Step 1: Map control action**

In `_CONTROL_ACTION_MAP` (around line 559), add:

```python
"gemma4_smart_routing_toggle": ("set-gemma4-smart-routing", "gemma4_smart_routing"),
```

- [ ] **Step 2: Propagate to env**

In `_apply_state_to_env` (around line 587), add:

```python
os.environ["LUCY_GEMMA4_SMART_ROUTING"] = _bool_env(
    state.get("gemma4_smart_routing", "off")
)
```

- [ ] **Step 3: Wire signal in HMI main window**

Find where `control_panel.model_change_requested.connect(...)` is done (likely in `ui-v10/app/windows/main_window.py` or similar). Add alongside it:

```python
control_panel.gemma4_smart_routing_change_requested.connect(
    lambda value: runtime_bridge.run_control_action("gemma4_smart_routing_toggle", value)
)
```

- [ ] **Step 4: Verify env propagation**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -c "from app.services.runtime_bridge import RuntimeBridge; print(RuntimeBridge)"`
Expected: no import errors.

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v10
git add ui-v10/app/services/runtime_bridge.py ui-v10/app/windows/main_window.py
git commit -m "feat(state): persist gemma4_smart_routing toggle and propagate to env"
```

---

## Task 4: Pipeline bypass logic

**Files:**
- Modify: `tools/router_py/request_pipeline.py:70-170`
- Test: `tools/router_py/test_request_pipeline.py` (create if missing)

**Interfaces:**
- Consumes: `LUCY_GEMMA4_SMART_ROUTING` env var
- Consumes: `LUCY_MODEL` / `LUCY_LOCAL_MODEL` env var
- Consumes: `ClassificationResult`, `RoutingDecision` from `request_types.py`
- Produces: `_is_gemma4_smart_routing_enabled(model: str) -> bool`
- Produces: `_gemma4_bypass_decision(question: str) -> tuple[ClassificationResult, RoutingDecision]`

- [ ] **Step 1: Write failing bypass tests**

Create or append to `tools/router_py/test_request_pipeline.py`:

```python
import os

import pytest

from router_py.request_pipeline import _is_gemma4_smart_routing_enabled, _gemma4_bypass_decision


def test_is_gemma4_smart_routing_enabled_only_for_gemma4():
    assert _is_gemma4_smart_routing_enabled("gemma4:12b-it-qat") is True
    assert _is_gemma4_smart_routing_enabled("local-lucy-llama31") is False
    assert _is_gemma4_smart_routing_enabled("") is False


def test_gemma4_bypass_decision_is_local():
    classification, decision = _gemma4_bypass_decision("hello")
    assert decision.route == "LOCAL"
    assert decision.mode == "SMART"
    assert classification.intent_family == "general"
    assert classification.force_local is True
```

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_request_pipeline.py -v`
Expected: two FAILs (functions not defined).

- [ ] **Step 2: Implement helpers**

Add near the top of `request_pipeline.py` after imports:

```python
def _is_gemma4_smart_routing_enabled(model: str) -> bool:
    """Return True if Gemma 4 smart routing is enabled for the given model."""
    if not model or not model.lower().startswith("gemma4"):
        return False
    return os.environ.get("LUCY_GEMMA4_SMART_ROUTING", "").lower() in ("1", "true", "on")


def _gemma4_bypass_decision(question: str) -> tuple[ClassificationResult, RoutingDecision]:
    """Create minimal classification + LOCAL routing decision for Gemma 4 bypass."""
    classification = ClassificationResult(
        intent="general",
        intent_family="general",
        intent_class="general",
        confidence=1.0,
        force_local=True,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="SMART",
        intent_family="general",
        confidence=1.0,
        provider="local",
        provider_usage_class="local",
        evidence_mode="none",
        policy_reason="gemma4_smart_routing",
    )
    return classification, decision
```

- [ ] **Step 3: Insert bypass into process()**

Before the classify block (around line 110), add:

```python
    # ------------------------------------------------------------------
    # 0. Gemma 4 smart-routing bypass
    # ------------------------------------------------------------------
    active_model = model or os.environ.get("LUCY_MODEL", "") or os.environ.get("LUCY_LOCAL_MODEL", "")
    if classification is None and decision is None and _is_gemma4_smart_routing_enabled(active_model):
        # Explicit prefixes and deterministic fast paths are handled by the caller
        # (route_prefix) or by the execution engine's own pattern checks. For
        # everything else, route directly to Gemma 4 LOCAL.
        if not route_prefix:
            classification, decision = _gemma4_bypass_decision(question)
```

- [ ] **Step 4: Run tests**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_request_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/request_pipeline.py tools/router_py/test_request_pipeline.py
git commit -m "feat(routing): Gemma 4 smart-routing bypass in request pipeline"
```

---

## Task 5: Preserve news/evidence fast paths under bypass

**Files:**
- Modify: `tools/router_py/request_pipeline.py:170-210`
- Test: `tools/router_py/test_request_pipeline.py`

The route prefix override (3a) and `augmented_direct_once` (3b) already run after the bypass decision. However, if the caller does not pass `route_prefix`, the bypass currently routes everything to LOCAL. We need to also check deterministic fast paths for news and evidence before bypassing.

- [ ] **Step 1: Add deterministic fast-path helpers**

Add in `request_pipeline.py`:

```python
_NEWS_RE = re.compile(r"\b(news|headlines|latest|breaking)\b", re.IGNORECASE)
_EVIDENCE_RE = re.compile(r"\b(research|study|evidence|paper|source|according to)\b", re.IGNORECASE)


def _looks_like_news(query: str) -> bool:
    return bool(_NEWS_RE.search(query))


def _looks_like_evidence(query: str) -> bool:
    return bool(_EVIDENCE_RE.search(query))
```

- [ ] **Step 2: Update bypass block**

Change the bypass block from Step 3 in Task 4 to:

```python
    if classification is None and decision is None and _is_gemma4_smart_routing_enabled(active_model):
        if not route_prefix:
            if _looks_like_news(question):
                route_prefix = "NEWS"
            elif _looks_like_evidence(question):
                route_prefix = "EVIDENCE"
            else:
                classification, decision = _gemma4_bypass_decision(question)
```

- [ ] **Step 3: Add tests**

```python
def test_gemma4_bypass_routes_news_pattern_to_news():
    os.environ["LUCY_GEMMA4_SMART_ROUTING"] = "on"
    os.environ["LUCY_MODEL"] = "gemma4:12b-it-qat"
    outcome, classification, decision = process("latest news about Israel")
    assert decision is not None
    assert decision.route == "NEWS"


def test_gemma4_bypass_routes_evidence_pattern_to_evidence():
    os.environ["LUCY_GEMMA4_SMART_ROUTING"] = "on"
    os.environ["LUCY_MODEL"] = "gemma4:12b-it-qat"
    outcome, classification, decision = process("evidence for climate change")
    assert decision is not None
    assert decision.route == "EVIDENCE"
```

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_request_pipeline.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/request_pipeline.py tools/router_py/test_request_pipeline.py
git commit -m "feat(routing): preserve news/evidence fast paths under Gemma 4 bypass"
```

---

## Task 6: Verification

- [ ] **Step 1: Run targeted pipeline tests**

Run: `cd /home/mike/lucy-v10 && ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_request_pipeline.py -q`
Expected: all PASS

- [ ] **Step 2: Run full regression suite with toggle off**

Run: `cd /home/mike/lucy-v10 && LUCY_TEST_LIVE_APIS=1 make test`
Expected: similar to baseline (1085+ passed)

- [ ] **Step 3: Manual HMI check**

Start the HMI, select `gemma4:12b-it-qat`, enable **Gemma 4 Smart Routing**, and verify:
- Ordinary question → LOCAL route.
- `news: latest Israel` → NEWS route.
- `evidence: ...` → EVIDENCE/AUGMENTED route.
- On a 12 GB GPU the VRAM warning appears; on a 24 GB GPU it does not.

- [ ] **Step 4: Commit handoff update**

Update `docs/handoffs/Local_Lucy_V11_Session_Handoff_2026-07-11.md` with the new toggle and test results, copy to Desktop, and commit.

---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| HMI toggle default off, only enabled for Gemma 4 | Task 2 |
| Persist `gemma4_smart_routing` in `current_state.json` | Task 3 |
| Explicit prefixes win | Already handled by caller + Task 5 |
| Deterministic news/evidence fast paths preserved | Task 5 |
| Skip classifier/router for ordinary queries | Task 4 |
| Low-VRAM warning (<12 GB) | Task 1 + Task 2 |
| CPU/RAM fallback not blocked | No code forces GPU-only; Ollama default behavior |
| Env override `LUCY_GEMMA4_SMART_ROUTING` | Task 3 |

## Placeholder scan

No TBD/TODO placeholders. All steps include concrete code, commands, and expected outputs.

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-12-gemma4-smart-routing.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
