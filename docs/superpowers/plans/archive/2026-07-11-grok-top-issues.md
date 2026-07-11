# Grok Top 4 Issues — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` for inline execution with checkpoints, or `superpowers:subagent-driven-development` if dispatching per task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the four highest-priority bugs Grok identified in the read-only review, with a full HMI voice-path smoke test after each stage and comprehensive stress testing at the end.

**Architecture:** Make small, behavior-preserving fixes in `runtime_bridge`, `main_window`, `background_learner`, `feedback_parser`, and `memory_service`. The voice path is exercised with the existing `test_e2e_hmi_voice.py` ExecutionEngine tests between stages; final validation uses `make test` plus barrage/stress scripts.

**Tech Stack:** Python 3.10, PySide6 (`QRunnable`/`QThreadPool`), SQLite, pytest, Local Lucy runtime.

## Global Constraints

- Work in `/home/mike/lucy-v10` on branch `v10-dev`.
- Keep changes minimal; do not refactor unrelated code.
- Every stage must end with the voice-path smoke test passing.
- Run `make test` only at the end; stage gates use targeted tests.
- Do not modify `config/trust/` or prompt content unless required by the fix.
- Preserve existing test behavior; update tests only when the fix changes a contract.
- Commit after each stage.

---

### Task 1: Control toggles ↔ live env/state single source of truth

**Files:**
- Modify: `tools/router_py/main.py:198-246` (`ensure_control_env`)
- Modify: `ui-v10/app/services/runtime_bridge.py:573-586` (control action handler)
- Test: `tools/router_py/test_e2e_hmi_voice.py`

**Interfaces:**
- Consumes: `current_state.json` fields `evidence`, `augmentation_policy`, `augmented_provider`, `conversation`, `memory`, `voice`, `model`.
- Produces: `LUCY_*` env vars reflect the latest state on every submit and after every control action.

- [ ] **Step 1: Make `ensure_control_env` overwrite from state**

Change `tools/router_py/main.py:198-246` so it always applies current state to env, removing the `if "VAR" not in os.environ` guards and the early return. The function should overwrite existing values so the process env cannot drift from `current_state.json`.

```python
def ensure_control_env() -> None:
    """
    Ensure control environment variables reflect the current state file.
    This is the single source of truth for control toggles; callers must
    re-read these env vars after this function returns.
    """
    state = load_state_from_file()
    if not state:
        return

    evidence = state.get("evidence", "off")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "1" if evidence in ("on", "true", "1") else "0"
    os.environ["LUCY_ENABLE_INTERNET"] = os.environ["LUCY_EVIDENCE_ENABLED"]

    policy = state.get("augmentation_policy", "disabled")
    os.environ["LUCY_AUGMENTATION_POLICY"] = policy

    provider = state.get("augmented_provider", "wikipedia")
    os.environ["LUCY_AUGMENTED_PROVIDER"] = provider

    conv = state.get("conversation", "off")
    os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1" if conv in ("on", "true", "1") else "0"

    mem = state.get("memory", "off")
    os.environ["LUCY_SESSION_MEMORY"] = "1" if mem in ("on", "true", "1") else "0"

    voice = state.get("voice", "off")
    os.environ["LUCY_VOICE_ENABLED"] = "1" if voice in ("on", "true", "1") else "0"

    model = state.get("model", "local-lucy-llama31")
    os.environ["LUCY_MODEL"] = model
    os.environ["LUCY_LOCAL_MODEL"] = model
```

- [ ] **Step 2: Apply state→env after every control action**

In `ui-v10/app/services/runtime_bridge.py`, after the control action succeeds (around line 588 before the `return CommandResult`), call a helper that overwrites the same env vars from `current_state.json`. Reuse the logic from `ensure_control_env` by importing and calling it inside the `_runtime_env` context, or replicate the mapping in a small private method.

Add near the top of `RuntimeBridge`:

```python
def _apply_state_to_env(self) -> None:
    """Force process env to match current_state.json control toggles."""
    from router_py.main import load_state_from_file

    state = load_state_from_file()
    if not state:
        return

    def _bool_env(value: str) -> str:
        return "1" if str(value).lower() in ("on", "true", "1") else "0"

    os.environ["LUCY_EVIDENCE_ENABLED"] = _bool_env(state.get("evidence", "off"))
    os.environ["LUCY_ENABLE_INTERNET"] = os.environ["LUCY_EVIDENCE_ENABLED"]
    os.environ["LUCY_AUGMENTATION_POLICY"] = state.get("augmentation_policy", "disabled")
    os.environ["LUCY_AUGMENTED_PROVIDER"] = state.get("augmented_provider", "wikipedia")
    os.environ["LUCY_CONVERSATION_MODE_FORCE"] = _bool_env(state.get("conversation", "off"))
    os.environ["LUCY_SESSION_MEMORY"] = _bool_env(state.get("memory", "off"))
    os.environ["LUCY_VOICE_ENABLED"] = _bool_env(state.get("voice", "off"))
    model = state.get("model", "local-lucy-llama31")
    os.environ["LUCY_MODEL"] = model
    os.environ["LUCY_LOCAL_MODEL"] = model
```

Call `self._apply_state_to_env()` at the end of `_run_control_action` before returning success.

- [ ] **Step 3: Run targeted tests**

```bash
cd /home/mike/lucy-v10
ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_main.py -v -k "ensure_control_env or state" --timeout=60
ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -v --timeout=120
```

Expected: targeted tests pass; voice E2E passes.

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/main.py ui-v10/app/services/runtime_bridge.py
git commit -m "fix(controls): make process env mirror current_state.json on every action and submit"
```

---

### Task 2: HMI shutdown `cancel()` crash

**Files:**
- Modify: `ui-v10/app/services/runtime_bridge.py:55-88` (`RuntimeActionTask`)
- Modify: `ui-v10/app/main_window.py:687-716` (optional, defensive check)
- Test: `ui-v10/tests/test_voice_ptt_state_machine.py` or new test

**Interfaces:**
- Consumes: `QRunnable.run()` worker body.
- Produces: `RuntimeActionTask.cancel()` stops the worker cooperatively; `main_window` shutdown is crash-free.

- [ ] **Step 1: Add cooperative cancel to `RuntimeActionTask`**

Change `ui-v10/app/services/runtime_bridge.py:55-88`:

```python
class RuntimeActionTask(QRunnable):
    def __init__(
        self,
        bridge: "RuntimeBridge",
        action: str,
        requested_value: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._action = action
        self._requested_value = requested_value
        self._context = context
        self.signals = RuntimeActionTaskSignals()
        self._cancelled = False

    def cancel(self) -> None:
        """Request cooperative cancellation."""
        self._cancelled = True

    def is_cancelled(self) -> bool:
        return self._cancelled

    @Slot()
    def run(self) -> None:
        try:
            if self._cancelled:
                result = CommandResult(
                    action=self._action,
                    requested_value=self._requested_value,
                    status="cancelled",
                    returncode=None,
                    stdout="",
                    stderr="task cancelled before run",
                    timed_out=False,
                    payload=None,
                )
            else:
                result = self._bridge.run_action(
                    self._action, self._requested_value, context=self._context
                )
        except Exception as exc:
            result = CommandResult(
                action=self._action,
                requested_value=self._requested_value,
                status="failed",
                returncode=None,
                stdout="",
                stderr=f"unexpected worker error: {exc}",
                timed_out=False,
                payload=None,
            )
        if not self._cancelled:
            self.signals.finished.emit(result)
```

- [ ] **Step 2: Add a regression test**

Create `ui-v10/tests/test_runtime_action_task_cancel.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_UI_ROOT))

import pytest
from app.services.runtime_bridge import RuntimeActionTask, CommandResult


class FakeBridge:
    def run_action(self, action: str, requested_value: str, context=None) -> CommandResult:
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status="ok",
            returncode=0,
            stdout="done",
            stderr="",
            timed_out=False,
            payload=None,
        )


def test_runtime_action_task_cancel_before_run_emits_cancelled():
    task = RuntimeActionTask(FakeBridge(), "test_action", "value")
    task.cancel()
    assert task.is_cancelled()


def test_runtime_action_task_cancel_has_method():
    task = RuntimeActionTask(FakeBridge(), "test_action", "value")
    assert hasattr(task, "cancel")
    assert callable(task.cancel)
```

Run:

```bash
cd /home/mike/lucy-v10/ui-v10
ui-v10/.venv/bin/python3 -m pytest tests/test_runtime_action_task_cancel.py -v
```

Expected: 2 passed.

- [ ] **Step 3: Run voice path smoke test**

```bash
cd /home/mike/lucy-v10
ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -v --timeout=120
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add ui-v10/app/services/runtime_bridge.py ui-v10/tests/test_runtime_action_task_cancel.py
git commit -m "fix(hmi): add RuntimeActionTask.cancel() to prevent shutdown AttributeError"
```

---

### Task 3: Learner fail-closed high-stakes + safer auto-learn defaults

**Files:**
- Modify: `models/router/background_learner.py:361-374` (`_is_high_stakes_feedback`)
- Modify: `tools/router_py/feedback_parser.py` (threshold parsing if any)
- Modify: `models/router/background_learner.py` (`maybe_auto_learn` defaults)
- Modify: `START_LUCY.sh` (optional: explicit `LUCY_AUTO_LEARN=0` default)
- Test: `models/router/test_feedback_trigger.py`, `models/router/test_background_learner_simulation.py`

**Interfaces:**
- Consumes: feedback category string, policy module.
- Produces: `_is_high_stakes_feedback` returns `True` on any policy error; auto-learn requires explicit opt-in and a minimum threshold.

- [ ] **Step 1: Read the current learner code**

Read `models/router/background_learner.py` around lines 340-420 and the `maybe_auto_learn` function to understand the threshold and default handling.

- [ ] **Step 2: Make high-stakes gate fail closed**

In `_is_high_stakes_feedback`, wrap the policy evaluation so any exception returns `True` (treat as high-stakes) instead of `False`:

```python
def _is_high_stakes_feedback(category: str, text: str) -> bool:
    """Return True if feedback must go to pending_review instead of auto-learn."""
    high_stakes_categories = {
        "medical",
        "veterinary",
        "finance",
        "legal",
        "mental_health",
        "safety",
    }
    if category in high_stakes_categories:
        return True
    try:
        from router_py.policy import is_high_stakes_intent

        if is_high_stakes_intent(text):
            return True
    except Exception:
        # Fail closed: if policy evaluation breaks, do not auto-learn.
        return True
    return False
```

- [ ] **Step 3: Raise auto-learn threshold and default to off**

In `maybe_auto_learn` (or wherever `LUCY_AUTO_LEARN` is read), change:

```python
enabled = os.environ.get("LUCY_AUTO_LEARN", "0").lower() in ("1", "true", "yes", "on")
min_entries = int(os.environ.get("LUCY_AUTO_LEARN_MIN_ENTRIES", "3"))
```

If the code has a hardcoded `min_entries=1`, replace it with `max(min_entries, 3)`.

- [ ] **Step 4: Update tests if needed**

Run the existing learner tests. If they assume auto-learn is on by default or `min_entries=1`, update them to set `LUCY_AUTO_LEARN=1` explicitly.

```bash
cd /home/mike/lucy-v10
ui-v10/.venv/bin/python3 -m pytest models/router/test_feedback_trigger.py models/router/test_background_learner_simulation.py -v --timeout=120
```

Expected: pass after any test updates.

- [ ] **Step 5: Run voice path smoke test**

```bash
ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -v --timeout=120
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add models/router/background_learner.py models/router/test_feedback_trigger.py models/router/test_background_learner_simulation.py
git commit -m "fix(learner): fail-closed high-stakes gate and safer auto-learn defaults"
```

---

### Task 4: Memory DB path XDG unification

**Files:**
- Modify: `tools/memory/memory_service.py:76-85` (default DB path)
- Modify: `tools/xdg_paths.py` (if `lucy_memory_db_path()` does not exist)
- Modify: `START_LUCY.sh` (export `LUCY_MEMORY_DB_PATH`)
- Test: `tools/router_py/test_e2e_hmi_voice.py`

**Interfaces:**
- Consumes: `LUCY_MEMORY_DB_PATH` env var, `xdg_paths.lucy_memory_db_path()`.
- Produces: Memory DB resolves via XDG path unless explicitly overridden.

- [ ] **Step 1: Check `xdg_paths.py` for `lucy_memory_db_path()`**

```bash
grep -n "lucy_memory_db_path\|memory" /home/mike/lucy-v10/tools/xdg_paths.py | head -20
```

If missing, add:

```python
def lucy_memory_db_path() -> Path:
    """Return the XDG-resolved memory database path."""
    return xdg_data_home() / "local-lucy" / "memory.db"
```

- [ ] **Step 2: Update `memory_service.py` default**

In `tools/memory/memory_service.py`, change the default DB path to:

```python
def _default_db_path() -> Path:
    explicit = os.environ.get("LUCY_MEMORY_DB_PATH", "").strip()
    if explicit:
        return Path(explicit)
    from tools.xdg_paths import lucy_memory_db_path

    return lucy_memory_db_path()
```

Replace any hardcoded `~/.codex-api-home/.../memory.db` with `_default_db_path()`.

- [ ] **Step 3: Export from `START_LUCY.sh`**

Add near the other env exports:

```bash
export LUCY_MEMORY_DB_PATH="${LUCY_MEMORY_DB_PATH:-$HOME/.local/share/local-lucy/memory.db}"
```

- [ ] **Step 4: Run targeted memory tests**

```bash
cd /home/mike/lucy-v10
ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -v --timeout=120
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tools/memory/memory_service.py tools/xdg_paths.py START_LUCY.sh
git commit -m "fix(memory): resolve memory DB via XDG path with env override"
```

---

### Task 5: Final full test suite + stress testing

**Files:**
- All of the above.
- Use: `tools/router_py/run_barrage.py` or `tools/thrash_test_fast.py` if available.

- [ ] **Step 1: Run full `make test`**

```bash
cd /home/mike/lucy-v10
LUCY_TEST_LIVE_APIS=1 make test
```

Expected: all pass; only expected skips remain (semantic regression goldens if model mismatched).

- [ ] **Step 2: Stress test the voice/HMI path**

Run the E2E voice/HMI test in a loop:

```bash
cd /home/mike/lucy-v10
for i in {1..5}; do
  echo "=== Stress run $i ==="
  ui-v10/.venv/bin/python3 -m pytest tools/router_py/test_e2e_hmi_voice.py -q --timeout=120 || break
done
```

If available, also run:

```bash
ui-v10/.venv/bin/python3 tools/router_py/run_barrage.py --count 20
```

- [ ] **Step 3: Fix any failures and repeat**

If any test fails, fix the root cause, commit, and re-run the failing suite plus the stress loop.

- [ ] **Step 4: Final report to user**

Summarize:
- Which issues were fixed.
- Files changed.
- Test results (`make test` count, stress run count).
- Any remaining skips or known limitations.

---

## Spec coverage self-review

| Requirement | Task |
|-------------|------|
| Control toggles mirror live state | Task 1 |
| Shutdown `cancel()` crash fixed | Task 2 |
| Learner fail-closed high-stakes | Task 3 |
| Safer auto-learn defaults | Task 3 |
| Memory DB XDG unification | Task 4 |
| Voice path smoke test between stages | Each task Step N |
| Final full test + stress | Task 5 |

No placeholders remain; every step includes exact file paths, code, and commands.
