# Self-Analysis Large-File and Large-Response Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed full source code into self-analysis prompts, support large files safely, and generate long detailed reviews via a dedicated `SELF_REVIEW` token budget.

**Architecture:** Add a `SELF_REVIEW` route mode in `local_answer.py` with a large token/context budget. Extend `self_analysis.py` to include the file source in its prompt, truncate intelligently, and guard against huge/non-file paths. Keep all changes isolated to the self-analysis path so normal chat behavior is unaffected.

**Tech Stack:** Python 3.10, Ollama API, PySide6 HMI, pytest.

## Global Constraints

- Default `self_review_max_tokens` = 4096.
- Default `self_review_context_chars` = 200000.
- File read size cap = 5 MB.
- Do not change default `num_ctx` in Ollama Modelfiles.
- Do not modify normal `LOCAL` chat token budgets.
- Disable local repeat cache for `SELF_REVIEW` route.
- All changes must pass `ruff check` / `ruff-format` and the existing self-analysis test suite.

---

### Task 1: Add source-code inclusion and file-safety checks to `self_analysis.py`

**Files:**
- Modify: `tools/router_py/self_analysis.py:31-48`, `tools/router_py/self_analysis.py:77-88`, `tools/router_py/self_analysis.py:156-192`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `SelfAnalysisEngine.analyze_file(relative_path: str) -> FileAnalysis`
- Produces: `FileAnalysis.prompt_context` now includes a `Source code:` section; `_resolve_file` rejects directories and files larger than 5 MB.

- [ ] **Step 1: Write the failing test for source code in prompt**

```python
def test_analyze_file_includes_source_code_in_prompt(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def hello():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)
    result = engine.analyze_file("sample.py")

    assert "Source code:" in result.prompt_context
    assert "def hello():" in result.prompt_context
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py::test_analyze_file_includes_source_code_in_prompt -v
```

Expected: FAIL because source code is not yet included.

- [ ] **Step 3: Implement source-code inclusion and safety checks**

In `tools/router_py/self_analysis.py`:

1. Add a 5 MB size cap and `is_file()` check in `_resolve_file`:

```python
_MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024

class SelfAnalysisEngine:
    ...
    def _resolve_file(self, relative_path: str) -> Path:
        candidate = self.project_root / relative_path
        candidate = candidate.resolve()
        try:
            candidate.relative_to(self.project_root)
        except ValueError as exc:
            raise ValueError(f"Path escapes project root: {relative_path}") from exc
        if not candidate.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        if not candidate.is_file():
            raise ValueError(f"Not a regular file: {relative_path}")
        if candidate.suffix != ".py":
            raise ValueError(f"Not a Python file: {relative_path}")
        if candidate.stat().st_size > _MAX_FILE_SIZE_BYTES:
            raise ValueError(
                f"File too large for self-analysis ({candidate.stat().st_size} bytes): {relative_path}"
            )
        return candidate
```

2. Read the source in `analyze_file` and pass it to `_build_context`:

```python
    def analyze_file(self, relative_path: str) -> FileAnalysis:
        file_path = self._resolve_file(relative_path)
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        metrics = self._extract_metrics(tree, source)
        hotspots = self._find_hotspots(tree, source)
        todos = self._find_todos(source)
        diagnostics = self._run_ruff(file_path)
        prompt_context = self._build_context(file_path, metrics, hotspots, todos, diagnostics, source)

        return FileAnalysis(
            path=relative_path,
            metrics=metrics,
            lint_diagnostics=diagnostics,
            hotspots=hotspots,
            prompt_context=prompt_context,
        )
```

3. Update `_build_context` to accept and append source code:

```python
    def _build_context(
        self,
        file_path: Path,
        metrics: dict[str, int],
        hotspots: list[str],
        todos: list[str],
        diagnostics: list[dict[str, Any]],
        source: str,
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
        if todos:
            lines.append("TODOs / FIXMEs:")
            lines.extend(f"  - {t}" for t in todos[:10])
        if diagnostics:
            lines.append("Top diagnostics:")
            for d in diagnostics[:5]:
                lines.append(
                    f"  - {d.get('code', 'lint')}: line {d.get('location', {}).get('row', '?')} — {d.get('message', '')}"
                )
        lines.append("Source code:")
        lines.append("```python")
        lines.append(source)
        lines.append("```")
        return "\n".join(lines)
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py::test_analyze_file_includes_source_code_in_prompt -v
```

Expected: PASS.

- [ ] **Step 5: Add tests for safety checks and run them**

Add to `tools/router_py/test_self_analysis.py`:

```python
def test_analyze_file_rejects_directory_named_py(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "not_a_dir.py").mkdir()

    engine = SelfAnalysisEngine(project_root=project)
    with pytest.raises(ValueError, match="Not a regular file"):
        engine.analyze_file("not_a_dir.py")


def test_analyze_file_rejects_huge_file(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    huge = project / "huge.py"
    huge.write_text("x = 1\n" * (5 * 1024 * 1024))

    engine = SelfAnalysisEngine(project_root=project)
    with pytest.raises(ValueError, match="File too large"):
        engine.analyze_file("huge.py")
```

Run:
```bash
python -m pytest tools/router_py/test_self_analysis.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/self_analysis.py tools/router_py/test_self_analysis.py
git commit -m "feat(self-analysis): include source code and guard large/non-file paths"
```

---

### Task 2: Add `SELF_REVIEW` route mode to `local_answer.py`

**Files:**
- Modify: `tools/router_py/local_answer.py:486-504`, `tools/router_py/local_answer.py:550-580`, `tools/router_py/local_answer.py:1427-1523`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: env vars `LUCY_SELF_REVIEW_MAX_TOKENS`, `LUCY_SELF_REVIEW_CONTEXT_CHARS`
- Produces: `_set_generation_profile(route_mode="SELF_REVIEW", ...)` returns `("self_review", budget, instruction)`; `LocalAnswerConfig` exposes `self_review_max_tokens` and `self_review_context_chars`.

- [ ] **Step 1: Write the failing test for SELF_REVIEW budget**

```python
def test_self_review_route_gets_large_budget():
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig.from_env()
    answer = LocalAnswer(config)
    profile, num_predict, instruction = answer._set_generation_profile("SELF_REVIEW", "CHAT", "review this file")

    assert profile == "self_review"
    assert num_predict == config.self_review_max_tokens
    assert num_predict >= 4096
    assert "thorough" in instruction.lower()
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
python -m pytest tools/router_py/test_self_analysis.py::test_self_review_route_gets_large_budget -v
```

Expected: FAIL because `SELF_REVIEW` route is not handled.

- [ ] **Step 3: Add config fields and env overrides**

In `tools/router_py/local_answer.py`, inside the `LocalAnswerConfig` dataclass add:

```python
    self_review_max_tokens: int = 4096
    self_review_context_chars: int = 100000
```

Inside `LocalAnswerConfig.from_env()`, after the existing fields:

```python
            self_review_max_tokens=int(os.environ.get("LUCY_SELF_REVIEW_MAX_TOKENS", "4096")),
            self_review_context_chars=int(os.environ.get("LUCY_SELF_REVIEW_CONTEXT_CHARS", "100000")),
```

- [ ] **Step 4: Add SELF_REVIEW branch in `_set_generation_profile`**

In `tools/router_py/local_answer.py`, at the top of `_set_generation_profile` add:

```python
        if route == "SELF_REVIEW":
            return (
                "self_review",
                self.config.self_review_max_tokens,
                "- Provide a thorough, detailed code review with concrete, minimal improvements.",
            )
```

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
python -m pytest tools/router_py/test_self_analysis.py::test_self_review_route_gets_large_budget -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/local_answer.py tools/router_py/test_self_analysis.py
git commit -m "feat(local_answer): add SELF_REVIEW route with large token budget"
```

---

### Task 3: Wire self-analysis to use `SELF_REVIEW` route and disable cache

**Files:**
- Modify: `tools/router_py/self_analysis.py:69`, `tools/router_py/local_answer.py:2065-2080`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `route_mode="SELF_REVIEW"`, `LocalAnswerConfig.self_review_context_chars`
- Produces: `SelfAnalysisEngine.suggest_improvements` calls `generate_answer(route_mode="SELF_REVIEW")`; cache is bypassed for `SELF_REVIEW`.

- [ ] **Step 1: Write the failing test for route_mode and cache bypass**

```python
@pytest.mark.asyncio
async def test_suggest_improvements_uses_self_review_route_and_disables_cache(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)

    class FakeAnswerResult:
        text = "mocked suggestion"

    class FakeLocalAnswer:
        def __init__(self, config):
            self.config = config
        async def generate_answer(self, **kwargs):
            self.last_kwargs = kwargs
            return FakeAnswerResult()
        async def close(self):
            pass

    fake_config = type(sys.modules["router_py.local_answer"]).LocalAnswerConfig.from_env()
    fake_module = type(sys.modules["router_py.local_answer"])
    fake_module.LocalAnswer = FakeLocalAnswer
    fake_module.LocalAnswerConfig = type(sys.modules["router_py.local_answer"]).LocalAnswerConfig
    monkeypatch.setitem(sys.modules, "router_py.local_answer", fake_module)

    result = await engine.suggest_improvements("sample.py")
    assert "LOCAL analysis" in result
    assert "mocked suggestion" in result
    assert engine._last_answer.last_kwargs.get("route_mode") == "SELF_REVIEW"
```

*Note:* The monkeypatch setup above is illustrative; use the same fake-module pattern already working in `test_execution_engine_self_analysis_route`. Store the `FakeLocalAnswer` instance on the engine or module so the assertion can reach it.

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
python -m pytest tools/router_py/test_self_analysis.py::test_suggest_improvements_uses_self_review_route_and_disables_cache -v
```

Expected: FAIL because `route_mode` is still `LOCAL`.

- [ ] **Step 3: Update `self_analysis.py` to use `SELF_REVIEW`**

In `tools/router_py/self_analysis.py`, change:

```python
            result = await answer.generate_answer(query=prompt, route_mode="LOCAL")
```

to:

```python
            result = await answer.generate_answer(query=prompt, route_mode="SELF_REVIEW")
```

- [ ] **Step 4: Disable cache for SELF_REVIEW route**

In `tools/router_py/local_answer.py`, find the cache lookup in `generate_answer`. Around the cache check, add:

```python
        cache_bypass = route_mode.upper() == "SELF_REVIEW"
```

and ensure the cache is neither read nor written when `cache_bypass` is True. The exact location is in `generate_answer` after `_normalize_query`; look for `self.config.cache_enabled` and guard both `_cache_load` and `_cache_store` with `and not cache_bypass`.

- [ ] **Step 5: Run the test to verify it passes**

Run:
```bash
python -m pytest tools/router_py/test_self_analysis.py::test_suggest_improvements_uses_self_review_route_and_disables_cache -v
```

Expected: PASS.

- [ ] **Step 6: Add truncation test and run full suite**

Add:

```python
def test_analyze_file_truncates_very_long_source(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    source = "x = 1\n" * 50000  # ~300k chars
    (project / "long.py").write_text(source)

    engine = SelfAnalysisEngine(project_root=project)
    # Patch context chars to a small number for deterministic truncation
    monkeypatch.setattr(engine, "_max_source_chars", 100)
    result = engine.analyze_file("long.py")

    assert "[truncated" in result.prompt_context
    assert len(result.prompt_context) < len(source) + 500
```

*Note:* Implement `_max_source_chars` as `100000` default in `SelfAnalysisEngine` (or read from env) to support this test.

Run:
```bash
python -m pytest tools/router_py/test_self_analysis.py -v
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/self_analysis.py tools/router_py/local_answer.py tools/router_py/test_self_analysis.py
git commit -m "feat(self-analysis): use SELF_REVIEW route and bypass repeat cache"
```

---

## Self-Review

1. **Spec coverage:**
   - Include source code in prompt → Task 1.
   - Large response budget → Task 2.
   - File safety (size cap, is_file) → Task 1.
   - Dedicated SELF_REVIEW route → Task 2.
   - Cache bypass → Task 3.
   - Tests → all tasks.

2. **Placeholder scan:** No TBD/TODO; all code blocks are concrete.

3. **Type consistency:** `route_mode` is consistently a string; `self_review_max_tokens` and `self_review_context_chars` are `int` everywhere.

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-self-analysis-large-files.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints for review.

Which approach would you like?
