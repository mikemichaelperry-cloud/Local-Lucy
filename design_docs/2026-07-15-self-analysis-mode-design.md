# Self-Analysis Mode Design

**Date:** 2026-07-15
**Status:** Approved (Option A)
**Scope:** Add a local-first, privacy-first self-code-analysis capability to Local Lucy with an HMI toggle in the Engineering panel. Option B (`code-review-graph`) is deferred as a future enhancement.

## 1. Purpose

Give Local Lucy the ability to parse its own Python source, identify structural/lint signals, and use a local LLM to suggest improvements. The feature is opt-in via an Engineering-panel switch so it does not change normal operation when off.

## 2. Constraints

- No cloud dependency.
- Reuse existing infrastructure: `ruff`, `LocalAnswer`/Ollama, Engineering panel.
- No HMI redesign; only add one checkbox to the existing Engineering group.
- Answers must carry Local Lucy's trust/source notation: static facts as **LOCAL**, LLM suggestions as **AUGMENTED**.
- Do not modify router classification, SQLite schema, voice runtime, or model weights.

## 3. Architecture

```
User query ("analyze control_panel.py")
        │
        ▼
[ExecutionEngine] detects self_analysis_mode == "on"
        │
        ▼
[SelfAnalysisEngine]
   ├─ AST extractor (stdlib ast)
   ├─ Ruff runner (subprocess, existing ruff binary)
   └─ Context builder (file summary + lint summary + selected snippets)
        │
        ▼
[LocalAnswer / Ollama]
   model = configured model (gemma4:12b-it-qat with smart routing, or local-lucy-llama31)
        │
        ▼
[Response formatter]
   LOCAL facts + AUGMENTED suggestions
```

## 4. Components

### 4.1 `tools/router_py/self_analysis.py`

A new module with no external dependencies beyond the Python stdlib and `ruff`.

Responsibilities:
- Discover Python files under `LUCY_ROOT` (default `~/lucy-v10`), excluding `.git`, `.venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `state`, `cache`.
- Parse a target file with `ast.parse` and extract:
  - line count, function count, class count, import count
  - top-level definitions
  - TODO / FIXME / XXX comments
  - functions/classes over a configurable line threshold (default 100)
- Run `ruff check --output-format=json <file>` and collect diagnostics.
- Build a compact prompt context for the LLM.
- Call `LocalAnswer` with a structured system prompt asking for improvement suggestions.

Public API (tentative):

```python
@dataclass
class FileAnalysis:
    path: str
    metrics: dict[str, int]
    lint_diagnostics: list[dict[str, Any]]
    hotspots: list[str]
    prompt_context: str

class SelfAnalysisEngine:
    def __init__(self, project_root: Path | None = None) -> None: ...
    def analyze_file(self, relative_path: str) -> FileAnalysis: ...
    async def suggest_improvements(self, relative_path: str, model: str | None = None) -> str: ...
```

### 4.2 Router integration

In `tools/router_py/execution_engine.py`, add a lightweight guard near the existing route decision point:

- If `control_state.gemma4_smart_routing == "on"` and model is Gemma 4, Gemma 4 handles routing internally as today.
- Else if `control_state.self_analysis_mode == "on"` and the query matches a self-analysis intent (e.g. mentions "analyze", "review", "improve" plus a file or module), dispatch to `SelfAnalysisEngine`.
- Otherwise use the normal routing path.

The self-analysis route writes state via the existing `StateWriter` so the HMI can display the active route.

### 4.3 HMI changes

`ui-v10/app/panels/control_panel.py`:
- Add a signal `self_analysis_change_requested = Signal(str)`.
- Add a checkbox `self_analysis_selector` below the Gemma 4 Smart Routing checkbox in the Engineering group:
  - Label: `Self-Analysis Mode`
  - Tooltip: `"When on, Lucy can parse her own code and suggest improvements."`
- Add `_handle_self_analysis_changed` to emit `"on"`/`"off"`.
- Add `self_analysis` to `_current_values` and update it in `update_control_state`.

`ui-v10/app/main_window.py` / bridge:
- Wire the new signal to the backend state update path, analogous to `gemma4_smart_routing_change_requested`.

### 4.4 State persistence

Add `self_analysis_mode` to `current_state.json` alongside existing keys like `gemma4_smart_routing`. `execution_engine_state.py` already persists these; no schema migration is required because state is loaded as a dict.

## 5. Data Flow Example

1. User enables **Self-Analysis Mode** in Engineering panel.
2. User asks: *"analyze control_panel.py"*.
3. ExecutionEngine sees `self_analysis_mode == "on"` and a file reference in the query.
4. `SelfAnalysisEngine.analyze_file("ui-v10/app/panels/control_panel.py")`:
   - Returns metrics: 1113 lines, ~50 functions/classes, 0 lint errors, hotspots: `update_trace_summary`, `update_control_state`, `_build_engineering_group`.
5. Context is sent to Ollama via `LocalAnswer` with system prompt:
   > "You are reviewing Local Lucy's own Python code. Below are static metrics and lint results. Suggest concrete, minimal improvements. Do not rewrite the file."
6. Response is formatted:
   - **LOCAL**: file metrics, lint count, hotspots.
   - **AUGMENTED**: LLM suggestions.

## 6. Error Handling

- If `ruff` is not available, skip lint diagnostics and note it in the context.
- If a file path is invalid, return a clear error message.
- If `ast.parse` fails (syntax error), report the parse error as a LOCAL fact.
- If the LLM call fails, fall back to returning only LOCAL facts.
- All errors are surfaced to the user, never silent.

## 7. Testing

- Unit test: `tools/router_py/test_self_analysis.py`
  - Test AST metrics extraction on a small fixture.
  - Test ruff runner with a known lint.
  - Test prompt context length stays within a budget.
- HMI offscreen test: `ui-v10/tests/test_self_analysis_mode_offscreen.py`
  - Verify the checkbox exists in Engineering panel.
  - Verify toggling emits the correct signal.
- Integration test: run one self-analysis query end-to-end with a mocked `LocalAnswer`.

## 8. Future Work: Option B

When cross-file call graphs, impact radius, or architectural hotspots are needed, integrate `code-review-graph` as a secondary analyzer. It would sit alongside the custom `SelfAnalysisEngine` and be invoked only for queries that need structural relationships. No HMI changes are anticipated for that upgrade.

## 9. Files Likely to Change

- New: `tools/router_py/self_analysis.py`
- New: `tools/router_py/test_self_analysis.py`
- New: `ui-v10/tests/test_self_analysis_mode_offscreen.py`
- Modify: `tools/router_py/execution_engine.py` (add dispatch guard)
- Modify: `ui-v10/app/panels/control_panel.py` (add checkbox and signal)
- Modify: `ui-v10/app/services/runtime_bridge.py` or equivalent wiring
- Update: `Architecture.md`, `SESSION_CONTEXT.md`, `CHANGELOG.md`
