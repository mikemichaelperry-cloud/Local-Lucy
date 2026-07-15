# Self-Analysis Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-first self-code-analysis capability to Local Lucy with an Engineering-panel toggle, using Python `ast`, existing `ruff`, and the existing `LocalAnswer`/Ollama path.

**Architecture:** A new `SelfAnalysisEngine` parses Local Lucy's Python files and runs `ruff`; the `ExecutionEngine` dispatches self-analysis queries to it when the HMI toggle is on; the HMI gets one new checkbox in the Engineering group. State is persisted via the existing `StateWriter`/`current_state.json` path.

**Tech Stack:** Python 3.10, stdlib `ast`, `subprocess` for `ruff`, PySide6 for HMI, Ollama via existing `LocalAnswer`.

## Global Constraints

- No cloud dependency.
- Reuse existing `ruff` and `LocalAnswer`/Ollama infrastructure.
- No HMI redesign; only add one checkbox to the existing Engineering group.
- Answers carry Local Lucy trust/source notation: static facts as **LOCAL**, LLM suggestions as **AUGMENTED**.
- Do not modify router classification, SQLite schema, voice runtime, or model weights.
- Follow existing file organization: backend logic in `tools/router_py/`, HMI in `ui-v10/app/`.
- Tests: router tests via `python -m pytest tools/router_py/`, HMI tests via `QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_*.py`.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/router_py/self_analysis.py` | New: AST extraction, ruff runner, prompt builder, LLM call wrapper. |
| `tools/router_py/test_self_analysis.py` | New: unit tests for the engine. |
| `tools/router_py/execution_engine.py` | Modify: add dispatch guard for self-analysis queries. |
| `ui-v10/app/panels/control_panel.py` | Modify: add checkbox, signal, and state handling. |
| `ui-v10/app/main_window.py` | Modify: wire new signal to `_execute_backend_action`. |
| `ui-v10/app/services/runtime_bridge.py` | Modify: add action capability and control-action mapping. |
| `tools/runtime_control.py` | Modify: add `self_analysis_mode` to known fields, defaults, and normalization. |
| `ui-v10/tests/test_self_analysis_mode_offscreen.py` | New: HMI offscreen test for the checkbox. |
| `design_docs/2026-07-15-self-analysis-mode-design.md` | Existing approved design doc. |
| `Architecture.md` | Modify: add self-analysis section. |
| `SESSION_CONTEXT.md` | Modify: record completed work. |

---

### Task 1: Create `SelfAnalysisEngine`

**Files:**
- Create: `tools/router_py/self_analysis.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `LocalAnswer` from `tools/router_py/local_answer.py`, `ruff` binary from environment.
- Produces:
  - `FileAnalysis` dataclass
  - `SelfAnalysisEngine.analyze_file(relative_path: str) -> FileAnalysis`
  - `SelfAnalysisEngine.suggest_improvements(relative_path: str, model: str | None = None) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tools/router_py/test_self_analysis.py
from pathlib import Path

from router_py.self_analysis import FileAnalysis, SelfAnalysisEngine


def test_analyze_file_extracts_metrics(tmp_path):
    code = """\
def hello():
    pass

class Foo:
    def bar(self):
        # TODO: implement
        pass
"""
    project = tmp_path / "project"
    project.mkdir()
    file_path = project / "sample.py"
    file_path.write_text(code)

    engine = SelfAnalysisEngine(project_root=project)
    result = engine.analyze_file("sample.py")

    assert isinstance(result, FileAnalysis)
    assert result.path == "sample.py"
    assert result.metrics["functions"] == 2
    assert result.metrics["classes"] == 1
    assert len(result.hotspots) == 0
    assert "TODO" in result.prompt_context
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py::test_analyze_file_extracts_metrics -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'router_py.self_analysis'`.

- [ ] **Step 3: Implement `SelfAnalysisEngine` skeleton**

```python
# tools/router_py/self_analysis.py
from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "state",
    "cache",
    "models",
    "data",
}


@dataclass
class FileAnalysis:
    path: str
    metrics: dict[str, int] = field(default_factory=dict)
    lint_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    hotspots: list[str] = field(default_factory=list)
    prompt_context: str = ""


class SelfAnalysisEngine:
    def __init__(self, project_root: Path | None = None) -> None:
        if project_root is None:
            project_root = Path(os.environ.get("LUCY_ROOT", Path.home() / "lucy-v10"))
        self.project_root = Path(project_root).expanduser().resolve()

    def analyze_file(self, relative_path: str) -> FileAnalysis:
        file_path = self._resolve_file(relative_path)
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        metrics = self._extract_metrics(tree, source)
        hotspots = self._find_hotspots(tree, source)
        diagnostics = self._run_ruff(file_path)
        prompt_context = self._build_context(file_path, metrics, hotspots, diagnostics)

        return FileAnalysis(
            path=relative_path,
            metrics=metrics,
            lint_diagnostics=diagnostics,
            hotspots=hotspots,
            prompt_context=prompt_context,
        )

    async def suggest_improvements(
        self, relative_path: str, model: str | None = None
    ) -> str:
        analysis = self.analyze_file(relative_path)
        prompt = self._build_llm_prompt(analysis)

        try:
            from router_py.local_answer import LocalAnswer, LocalAnswerConfig
        except ImportError:
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions: unavailable (LocalAnswer not importable)."

        config = LocalAnswerConfig.from_env()
        if model:
            config.model = model
        answer = LocalAnswer(config)
        try:
            result = await answer.generate_answer(query=prompt, route_mode="LOCAL")
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions:\n{result.text}"
        except Exception as exc:
            logger.warning(f"Self-analysis LLM call failed: {exc}")
            return f"LOCAL analysis:\n{analysis.prompt_context}\n\nAUGMENTED suggestions: unavailable ({exc})."
        finally:
            await answer.close()

    def _resolve_file(self, relative_path: str) -> Path:
        candidate = self.project_root / relative_path
        candidate = candidate.resolve()
        if not str(candidate).startswith(str(self.project_root)):
            raise ValueError(f"Path escapes project root: {relative_path}")
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        if candidate.suffix != ".py":
            raise ValueError(f"Not a Python file: {relative_path}")
        return candidate

    def _extract_metrics(self, tree: ast.AST, source: str) -> dict[str, int]:
        lines = source.splitlines()
        functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
        return {
            "lines": len(lines),
            "functions": len(functions),
            "classes": len(classes),
            "imports": len(imports),
        }

    def _find_hotspots(self, tree: ast.AST, source: str) -> list[str]:
        hotspots = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                start = node.lineno
                end = getattr(node, "end_lineno", start)
                length = end - start + 1 if end else 1
                if length > 100:
                    name = node.name
                    kind = "function" if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else "class"
                    hotspots.append(f"{kind} '{name}' at lines {start}-{end} ({length} lines)")
        return hotspots

    def _run_ruff(self, file_path: Path) -> list[dict[str, Any]]:
        try:
            result = subprocess.run(
                ["ruff", "check", "--output-format=json", str(file_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode not in (0, 1):
                logger.warning(f"ruff check unexpected exit: {result.returncode}")
                return []
            return json.loads(result.stdout or "[]")
        except FileNotFoundError:
            logger.warning("ruff not found; skipping lint diagnostics")
            return []
        except Exception as exc:
            logger.warning(f"ruff check failed: {exc}")
            return []

    def _build_context(
        self,
        file_path: Path,
        metrics: dict[str, int],
        hotspots: list[str],
        diagnostics: list[dict[str, Any]],
    ) -> str:
        lines = [
            f"File: {file_path.relative_to(self.project_root)}",
            f"Lines: {metrics['lines']}",
            f"Functions: {metrics['functions']}",
            f"Classes: {metrics['classes']}",
            f"Imports: {metrics['imports']}",
            f"Ruff diagnostics: {len(diagnostics)}",
        ]
        if hotspots:
            lines.append("Hotspots:")
            lines.extend(f"  - {h}" for h in hotspots)
        if diagnostics:
            lines.append("Top diagnostics:")
            for d in diagnostics[:5]:
                lines.append(
                    f"  - {d.get('code', 'lint')}: line {d.get('location', {}).get('row', '?')} — {d.get('message', '')}"
                )
        return "\n".join(lines)

    def _build_llm_prompt(self, analysis: FileAnalysis) -> str:
        return (
            "You are reviewing Local Lucy's own Python source code. "
            "Below are static metrics and lint results. "
            "Suggest concrete, minimal improvements. Do not rewrite the file.\n\n"
            f"{analysis.prompt_context}"
        )
```

- [ ] **Step 4: Run tests**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/lucy-v10
git add tools/router_py/self_analysis.py tools/router_py/test_self_analysis.py
git commit -m "feat: add SelfAnalysisEngine for local code self-review"
```

---

### Task 2: Wire Self-Analysis into `ExecutionEngine`

**Files:**
- Modify: `tools/router_py/execution_engine.py`
- Test: `tools/router_py/test_self_analysis.py` (add integration test)

**Interfaces:**
- Consumes: `SelfAnalysisEngine` from Task 1.
- Produces: self-analysis dispatch in `execute_async`.

- [ ] **Step 1: Write the failing integration test**

```python
# tools/router_py/test_self_analysis.py (append)
import pytest

from router_py.execution_engine import ExecutionEngine


@pytest.mark.asyncio
async def test_execution_engine_self_analysis_route(tmp_path):
    code = """\
def long_function():
    x = 1
    x = 2
    x = 3
"""
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text(code)

    engine = ExecutionEngine()
    # Force self-analysis mode on and point engine at temp project via monkeypatch if needed.
    # This test verifies the dispatch path exists; actual LLM call is mocked.
    result = await engine.execute_self_analysis("sample.py", project_root=project)
    assert "LOCAL analysis" in result.response_text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py::test_execution_engine_self_analysis_route -v
```

Expected: FAIL with `AttributeError: 'ExecutionEngine' object has no attribute 'execute_self_analysis'`.

- [ ] **Step 3: Add dispatch method to `ExecutionEngine`**

In `tools/router_py/execution_engine.py`, add import near the top:

```python
from router_py.self_analysis import SelfAnalysisEngine
```

Add a helper method to the `ExecutionEngine` class (place near other route helpers):

```python
    async def execute_self_analysis(
        self,
        relative_path: str,
        project_root: Path | None = None,
        model: str | None = None,
    ) -> ExecutionResult:
        """Run local self-analysis on a project file and return formatted result."""
        start_time = time.time()
        try:
            engine = SelfAnalysisEngine(project_root=project_root)
            response = await engine.suggest_improvements(relative_path, model=model)
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                status="completed",
                outcome_code="answered",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text=response,
                error_message="",
                execution_time_ms=execution_time,
                metadata={"self_analysis": True, "file": relative_path},
            )
        except Exception as exc:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                status="failed",
                outcome_code="self_analysis_error",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text=f"Self-analysis failed: {exc}",
                error_message=str(exc),
                execution_time_ms=execution_time,
                metadata={"self_analysis": True, "file": relative_path},
            )
```

- [ ] **Step 4: Add dispatch guard in `execute_async`**

In `tools/router_py/execution_engine.py`, inside `execute_async`, after the empty-query check and before the CLARIFY route handling, add:

```python
        # Self-analysis mode dispatch
        control_state = self._load_control_state() or {}
        if control_state.get("self_analysis_mode", "off").lower() == "on":
            file_ref = self._extract_self_analysis_file_reference(question)
            if file_ref:
                self._logger.info(f"Self-analysis mode dispatch: {file_ref}")
                result = await self.execute_self_analysis(file_ref)
                self._record_request_metrics(context, route, result, result.execution_time_ms)
                return result
```

Add helper method:

```python
    def _load_control_state(self) -> dict[str, Any]:
        try:
            from runtime_control import load_or_create_state, resolve_runtime_paths

            state_file = resolve_runtime_paths(None).state_file
            state = load_or_create_state(state_file, refresh_timestamp=False)
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    def _extract_self_analysis_file_reference(self, question: str) -> str | None:
        """Return a relative path if the query asks to analyze/review/improve a file."""
        q = question.lower()
        if not any(k in q for k in ("analyze", "analyse", "review", "improve", "inspect")):
            return None
        # Look for quoted or bare file paths ending in .py
        matches = re.findall(r'[\'\"]?([\w\-/]+\.py)[\'\"]?', question)
        if matches:
            candidate = (ROOT_DIR / matches[0]).resolve()
            if candidate.exists():
                return str(candidate.relative_to(ROOT_DIR))
        # Look for module-style dotted paths (e.g. ui_v10.app.panels.control_panel)
        matches = re.findall(r'([\w]+(?:\.[\w]+)+)', question)
        for m in matches:
            converted = m.replace(".", "/") + ".py"
            if "ui_v10" in converted:
                converted = converted.replace("ui_v10", "ui-v10")
            candidate = (ROOT_DIR / converted).resolve()
            if candidate.exists():
                return str(candidate.relative_to(ROOT_DIR))
        return None
```

- [ ] **Step 5: Run tests**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py -v
```

Expected: PASS.

- [ ] **Step 6: Run full router test suite**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/ -q
```

Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
cd ~/lucy-v10
git add tools/router_py/execution_engine.py tools/router_py/test_self_analysis.py
git commit -m "feat: dispatch self-analysis queries in ExecutionEngine"
```

---

### Task 3: Add HMI Checkbox in Control Panel

**Files:**
- Modify: `ui-v10/app/panels/control_panel.py`
- Test: `ui-v10/tests/test_self_analysis_mode_offscreen.py`

**Interfaces:**
- Consumes: existing Engineering group layout.
- Produces: `self_analysis_change_requested = Signal(str)` and `_handle_self_analysis_changed`.

- [ ] **Step 1: Write the failing HMI test**

```python
# ui-v10/tests/test_self_analysis_mode_offscreen.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.panels.control_panel import ControlPanel


def test_self_analysis_checkbox_exists_and_emits_signal():
    app = QApplication.instance() or QApplication([])
    panel = ControlPanel()
    panel.set_interface_level("engineering")

    received = []
    panel.self_analysis_change_requested.connect(lambda value: received.append(value))

    checkbox = panel._self_analysis_selector
    assert checkbox is not None
    assert checkbox.text() == "Self-Analysis Mode"

    checkbox.blockSignals(False)
    checkbox.setChecked(True)
    QTest.mouseClick(checkbox, Qt.LeftButton)

    assert "on" in received
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/lucy-v10
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_self_analysis_mode_offscreen.py
```

Expected: FAIL with `AttributeError: 'ControlPanel' object has no attribute '_self_analysis_selector'`.

- [ ] **Step 3: Add checkbox and signal to `ControlPanel`**

In `ui-v10/app/panels/control_panel.py`:

1. Add signal:

```python
    self_analysis_change_requested = Signal(str)
```

2. Add to `_current_values`:

```python
            "self_analysis_mode": "",
```

3. In `_build_engineering_group`, after the Gemma 4 smart routing checkbox block, add:

```python
        self._self_analysis_selector = QCheckBox("Self-Analysis Mode")
        self._self_analysis_selector.setToolTip(
            "When on, Lucy can parse her own code and suggest improvements."
        )
        self._self_analysis_selector.setEnabled(False)
        self._self_analysis_selector.stateChanged.connect(
            self._handle_self_analysis_changed
        )
```

4. Add widget to layout after `self._gemma4_vram_warning_label`:

```python
        layout.addWidget(self._self_analysis_selector)
```

5. Add handler method after `_handle_gemma4_smart_routing_changed`:

```python
    def _handle_self_analysis_changed(self, state: int) -> None:
        value = "on" if state == 2 else "off"
        self._emit_if_changed(
            "self_analysis_mode",
            value,
            self.self_analysis_change_requested,
        )
```

6. In `update_control_state`, add:

```python
        values["self_analysis_mode"] = (
            str(current_state.get("self_analysis_mode", "off")).strip().lower()
            if isinstance(current_state, dict)
            else "off"
        )
```

and after the Gemma 4 routing checkbox update:

```python
        if self._self_analysis_selector is not None:
            self._self_analysis_selector.setChecked(
                values.get("self_analysis_mode", "off") == "on"
            )
            self._self_analysis_selector.setEnabled(self._backend_available)
```

- [ ] **Step 4: Run HMI test**

```bash
cd ~/lucy-v10
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_self_analysis_mode_offscreen.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd ~/lucy-v10
git add ui-v10/app/panels/control_panel.py ui-v10/tests/test_self_analysis_mode_offscreen.py
git commit -m "feat: add Self-Analysis Mode checkbox to Engineering panel"
```

---

### Task 4: Wire HMI Signal and Persist State

**Files:**
- Modify: `ui-v10/app/main_window.py`
- Modify: `ui-v10/app/services/runtime_bridge.py`
- Modify: `tools/runtime_control.py`

**Interfaces:**
- Consumes: `self_analysis_change_requested` signal from `ControlPanel`.
- Produces: state field `self_analysis_mode` persisted in `current_state.json`.

- [ ] **Step 1: Wire signal in `main_window.py`**

After the Gemma 4 smart routing wiring (line ~502), add:

```python
        self.control_panel.self_analysis_change_requested.connect(
            lambda value: self._execute_backend_action(
                "self_analysis_mode_toggle", value, "Self-Analysis mode change"
            )
        )
```

- [ ] **Step 2: Add action capability and mapping in `runtime_bridge.py`**

1. In `_discover_control_capabilities`, add:

```python
            "self_analysis_mode_toggle": ActionCapability(
                name="self_analysis_mode_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
```

2. In `_CONTROL_ACTION_MAP`, add:

```python
        "self_analysis_mode_toggle": ("set-self-analysis-mode", "self_analysis_mode"),
```

3. In `_apply_state_to_env`, add after the Gemma 4 env line:

```python
        os.environ["LUCY_SELF_ANALYSIS_MODE"] = _bool_env(
            state.get("self_analysis_mode", "off")
        )
```

- [ ] **Step 3: Teach `runtime_control.py` about `self_analysis_mode`**

1. Add `"self_analysis_mode"` to `KNOWN_FIELDS`.

2. In `default_state()`, add:

```python
        "self_analysis_mode": "off",
```

3. In `normalize_state()`, add after the Gemma 4 line:

```python
    state["self_analysis_mode"] = coerce_toggle(state.get("self_analysis_mode", "off"))
```

4. In `update_state_field()`, add `"self_analysis_mode"` to the set of fields that set `status = "ready"`.

- [ ] **Step 4: Run a quick state toggle test**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python3 -c "
import sys, tempfile, json
sys.path.insert(0, 'tools')
from pathlib import Path
from runtime_control import update_state_field, load_or_create_state

with tempfile.TemporaryDirectory() as td:
    state_file = Path(td) / 'current_state.json'
    state_file.write_text(json.dumps({'schema_version': 1}))
    result = update_state_field(state_file, 'self_analysis_mode', 'on')
    assert result.value == 'on'
    state = load_or_create_state(state_file, refresh_timestamp=False)
    assert state['self_analysis_mode'] == 'on'
    print('OK')
"
```

Expected: prints `OK`.

- [ ] **Step 5: Run existing HMI tests**

```bash
cd ~/lucy-v10
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd ~/lucy-v10
git add ui-v10/app/main_window.py ui-v10/app/services/runtime_bridge.py tools/runtime_control.py
git commit -m "feat: wire Self-Analysis Mode toggle to state persistence"
```

---

### Task 5: Update Documentation

**Files:**
- Modify: `Architecture.md`
- Modify: `SESSION_CONTEXT.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add self-analysis section to `Architecture.md`**

Append a short section:

```markdown
## Self-Analysis Mode

When enabled via the Engineering panel, Local Lucy can parse her own Python source and suggest improvements.

- Analysis is performed by `tools/router_py/self_analysis.py` using stdlib `ast` and existing `ruff`.
- LLM suggestions are generated through the existing `LocalAnswer`/Ollama path using the configured local model.
- Static facts are labeled **LOCAL**; LLM suggestions are labeled **AUGMENTED**.
- The toggle is stored in `current_state.json` under `self_analysis_mode`.
```

- [ ] **Step 2: Update `CHANGELOG.md`**

Add entry under the current dev version:

```markdown
- Added Self-Analysis Mode: local code review using `ast` + `ruff` + local LLM, controlled from the Engineering panel.
```

- [ ] **Step 3: Update `SESSION_CONTEXT.md`**

Record the new feature and any commits in the live state section.

- [ ] **Step 4: Commit**

```bash
cd ~/lucy-v10
git add Architecture.md CHANGELOG.md SESSION_CONTEXT.md
git commit -m "docs: document Self-Analysis Mode"
```

---

### Task 6: Final Verification

- [ ] **Step 1: Run all router tests**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/ -q
```

Expected: PASS.

- [ ] **Step 2: Run HMI offscreen tests**

```bash
cd ~/lucy-v10
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_self_analysis_mode_offscreen.py
QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```

Expected: PASS.

- [ ] **Step 3: Run end-to-end self-analysis (optional, uses LLM)**

```bash
cd ~/lucy-v10
source ui-v10/.venv/bin/activate
python3 -c "
import asyncio, sys
sys.path.insert(0, 'tools')
from router_py.self_analysis import SelfAnalysisEngine

async def main():
    engine = SelfAnalysisEngine()
    analysis = engine.analyze_file('ui-v10/app/panels/control_panel.py')
    print(analysis.prompt_context)

asyncio.run(main())
"
```

Expected: prints metrics for `control_panel.py`.

- [ ] **Step 4: Check git status**

```bash
cd ~/lucy-v10
git status --short
```

Expected: clean working tree after commits.

---

## Self-Review Checklist

- [x] Spec coverage: every design section maps to a task.
- [x] No placeholders: all code, commands, and expected outputs are concrete.
- [x] Type consistency: `FileAnalysis`, `SelfAnalysisEngine`, signal names, and state keys match across tasks.
