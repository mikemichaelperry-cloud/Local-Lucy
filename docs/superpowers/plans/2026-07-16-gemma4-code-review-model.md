# Gemma 4 Code-Review Specialist Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the specialist model `hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M` into Local Lucy’s existing Code Review / Analysis (`SELF_REVIEW`) mode behind a feature flag, with safe fallback, staged review prompts, Kokoro TTS suppression, and full regression coverage.

**Architecture:** Extend the existing `ExecutionEngine.execute_self_analysis` → `SelfAnalysisEngine.suggest_improvements` path. Add a model resolver that probes Ollama and falls back through a configured chain. Add code-review-specific generation parameters. Replace the single review prompt with a hybrid two-call staged review (code map + broad audit + coverage ledger, then optional deep investigation). Suppress Kokoro TTS output in the HMI only for `SELF_REVIEW` responses.

**Tech Stack:** Python 3.10+, Ollama HTTP API, pytest, existing Local Lucy runtime (`tools/router_py`, `ui-v10`, `tools/runtime_control.py`).

## Global Constraints

- Specialist model identifier: `hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M`
- Backend alias: `gemma4_code_review_agentic`
- Default context target: 16K (configurable to 24K later)
- Default generation params: temperature 1.0, top_p 0.95, top_k 64
- Read-only by default; no file edits, patches, commands, installs, deletes, commits, or pushes unless explicit user action.
- Fallback chain: specialist → `gemma4:12b-it-qat` → configured local model → error.
- Do not auto-download the specialist model during ordinary user requests.
- Preserve all existing model definitions and installed models.
- Voice bypass: do not load Whisper/Kokoro for inference; suppress Kokoro TTS on output.
- Run existing regression tests after implementation.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `tools/router_py/local_answer.py` | Model identity map, code-review config fields, apply code-review generation params for `SELF_REVIEW`. |
| `tools/router_py/self_analysis.py` | Staged prompt builder, deep-dive orchestration, truncation detection, read-only instruction enforcement. |
| `tools/router_py/execution_engine.py` | Model resolver, Ollama availability probe, fallback chain, pass resolved model into self-analysis. |
| `tools/runtime_control.py` | State/env fields `code_review_model` and `code_review_specialist_enabled`. |
| `ui-v10/app/panels/control_panel.py` | Expose Engineering mode toggle (reuse/extend `self_analysis_mode` checkbox). |
| `ui-v10/app/main_window.py` | Skip `_speak_response_text` when response route is `SELF_REVIEW`. |
| `tools/router_py/test_self_analysis.py` | Unit tests for model resolver, fallback, staged prompt, read-only guard, truncation. |
| `ui-v10/tests/test_self_analysis_mode_offscreen.py` | Offscreen HMI test for TTS suppression flag. |

---

## Task 1: Register the specialist model and add code-review config fields

**Files:**
- Modify: `tools/router_py/local_answer.py:305-310`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: none
- Produces: `_MODEL_IDENTITIES["gemma4_code_review_agentic"]`, new `LocalAnswerConfig` fields (`code_review_*`), env var parsing in `from_env()`.

- [ ] **Step 1: Write the failing test**

```python
def test_code_review_config_fields_have_defaults():
    from router_py.local_answer import LocalAnswerConfig
    config = LocalAnswerConfig()
    assert config.code_review_model == "gemma4_code_review_agentic"
    assert config.code_review_specialist_enabled is True
    assert config.code_review_temperature == 1.0
    assert config.code_review_top_p == 0.95
    assert config.code_review_top_k == 64
    assert config.code_review_context_target == 16384
    assert config.code_review_max_tokens == 4096
    assert config.code_review_context_chars == 200000


def test_code_review_config_fields_read_from_env(monkeypatch):
    from router_py.local_answer import LocalAnswerConfig
    monkeypatch.setenv("LUCY_CODE_REVIEW_MODEL", "custom_model")
    monkeypatch.setenv("LUCY_CODE_REVIEW_SPECIALIST_ENABLED", "0")
    monkeypatch.setenv("LUCY_CODE_REVIEW_TEMPERATURE", "0.7")
    monkeypatch.setenv("LUCY_CODE_REVIEW_TOP_P", "0.9")
    monkeypatch.setenv("LUCY_CODE_REVIEW_TOP_K", "32")
    monkeypatch.setenv("LUCY_CODE_REVIEW_CONTEXT_TARGET", "24576")
    monkeypatch.setenv("LUCY_CODE_REVIEW_MAX_TOKENS", "8192")
    monkeypatch.setenv("LUCY_CODE_REVIEW_CONTEXT_CHARS", "150000")
    config = LocalAnswerConfig.from_env()
    assert config.code_review_model == "custom_model"
    assert config.code_review_specialist_enabled is False
    assert config.code_review_temperature == 0.7
    assert config.code_review_top_p == 0.9
    assert config.code_review_top_k == 32
    assert config.code_review_context_target == 24576
    assert config.code_review_max_tokens == 8192
    assert config.code_review_context_chars == 150000


def test_specialist_model_identity_exists():
    from router_py.local_answer import get_self_knowledge
    text = get_self_knowledge("gemma4_code_review_agentic")
    assert "gemma-4-12B-agentic" in text or "12B" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_code_review_config_fields_have_defaults -v`
Expected: FAIL with `AttributeError: 'LocalAnswerConfig' object has no attribute 'code_review_model'`

- [ ] **Step 3: Add model identity and config fields**

In `tools/router_py/local_answer.py` around line 305, add the identity entry:

```python
_MODEL_IDENTITIES: dict[str, tuple[str, str]] = {
    # backend_name -> (ollama_model_name, parameter_description)
    "local-lucy-llama31": ("llama3.1:8b", "~8B parameters, 4096-token context"),
    "local-lucy-llama31:latest": ("llama3.1:8b", "~8B parameters, 4096-token context"),
    "gemma4:12b-it-qat": ("gemma4:12b-it-qat", "~12B parameters, 128k-token context"),
    "gemma4_code_review_agentic": (
        "hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M",
        "~12B parameters, 128k-token context, code-review specialist",
    ),
}
```

In the `LocalAnswerConfig` dataclass (around line 476), add fields:

```python
    # Code-review specialist model settings
    code_review_model: str = "gemma4_code_review_agentic"
    code_review_specialist_enabled: bool = True
    code_review_temperature: float = 1.0
    code_review_top_p: float = 0.95
    code_review_top_k: int = 64
    code_review_context_target: int = 16384
    code_review_max_tokens: int = 4096
    code_review_context_chars: int = 200000
```

In `LocalAnswerConfig.from_env()` (around line 553), parse the env vars:

```python
            code_review_model=os.environ.get("LUCY_CODE_REVIEW_MODEL", "gemma4_code_review_agentic"),
            code_review_specialist_enabled=os.environ.get(
                "LUCY_CODE_REVIEW_SPECIALIST_ENABLED", "1"
            ).lower()
            in ("1", "true", "yes", "on"),
            code_review_temperature=float(
                os.environ.get("LUCY_CODE_REVIEW_TEMPERATURE", "1.0")
            ),
            code_review_top_p=float(os.environ.get("LUCY_CODE_REVIEW_TOP_P", "0.95")),
            code_review_top_k=int(os.environ.get("LUCY_CODE_REVIEW_TOP_K", "64")),
            code_review_context_target=int(
                os.environ.get("LUCY_CODE_REVIEW_CONTEXT_TARGET", "16384")
            ),
            code_review_max_tokens=int(
                os.environ.get("LUCY_CODE_REVIEW_MAX_TOKENS", "4096")
            ),
            code_review_context_chars=int(
                os.environ.get("LUCY_CODE_REVIEW_CONTEXT_CHARS", "200000")
            ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_code_review_config_fields_have_defaults tools/router_py/test_self_analysis.py::test_code_review_config_fields_read_from_env tools/router_py/test_self_analysis.py::test_specialist_model_identity_exists -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/local_answer.py tools/router_py/test_self_analysis.py
git commit -m "feat(local_answer): add code-review specialist model config and identity"
```

---

## Task 2: Add runtime state fields for code-review model and enable flag

**Files:**
- Modify: `tools/runtime_control.py:38-39`, `tools/runtime_control.py:341`, `tools/runtime_control.py:420`, `tools/runtime_control.py:496`, `tools/runtime_control.py:660`, `tools/runtime_control.py:572`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: none
- Produces: `KNOWN_FIELDS` includes `code_review_model` and `code_review_specialist_enabled`; env exports `LUCY_CODE_REVIEW_MODEL` and `LUCY_CODE_REVIEW_SPECIALIST_ENABLED`; CLI commands `set-code-review-model` and `set-code-review-specialist-enabled`.

- [ ] **Step 1: Write the failing test**

```python
def test_render_env_exports_code_review_fields():
    from runtime_control import render_env
    state = {
        "mode": "offline",
        "conversation": "off",
        "memory": "on",
        "evidence": "off",
        "voice": "off",
        "augmentation_policy": "fallback_only",
        "augmented_provider": "wikipedia",
        "status": "ready",
        "profile": "default",
        "model": "local-lucy-llama31",
        "learner": "off",
        "gemma4_smart_routing": "off",
        "self_analysis_mode": "off",
        "code_review_model": "gemma4_code_review_agentic",
        "code_review_specialist_enabled": "on",
    }
    env = render_env(state)
    assert "LUCY_CODE_REVIEW_MODEL=gemma4_code_review_agentic" in env
    assert "LUCY_CODE_REVIEW_SPECIALIST_ENABLED=1" in env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_render_env_exports_code_review_fields -v`
Expected: FAIL because the env strings are not emitted.

- [ ] **Step 3: Add state fields and CLI commands**

In `tools/runtime_control.py`:

1. Add to `KNOWN_FIELDS` (around line 38):

```python
    "code_review_model",
    "code_review_specialist_enabled",
```

2. Add defaults in `default_state` (around line 341):

```python
        "code_review_model": "gemma4_code_review_agentic",
        "code_review_specialist_enabled": "on",
```

3. Add to the action list if present (around line 420), near `self_analysis_mode`:

```python
            "code_review_model",
            "code_review_specialist_enabled",
```

4. Add CLI command handlers in the main argparse dispatch (around line 109):

```python
        elif args.command == "set-code-review-model":
            result = update_state_field(state_file, "code_review_model", args.value)
        elif args.command == "set-code-review-specialist-enabled":
            result = update_state_field(
                state_file, "code_review_specialist_enabled", coerce_toggle(args.value)
            )
```

5. Add argument parsers near the other `set-*` parsers:

```python
    set_code_review_model = subparsers.add_parser(
        "set-code-review-model", help="Set the code-review specialist model alias"
    )
    set_code_review_model.add_argument("--value", required=True)

    set_code_review_specialist_enabled = subparsers.add_parser(
        "set-code-review-specialist-enabled",
        help="Enable/disable the code-review specialist model",
    )
    set_code_review_specialist_enabled.add_argument(
        "--value", required=True, choices=["on", "off", "1", "0", "true", "false"]
    )
```

6. Add env exports in `render_env` (around line 660):

```python
        f"LUCY_CODE_REVIEW_MODEL={state.get('code_review_model', 'gemma4_code_review_agentic')}",
        f"LUCY_CODE_REVIEW_SPECIALIST_ENABLED={_toggle_to_env(state.get('code_review_specialist_enabled', 'on'))}",
```

7. Add to `build_self_check_payload` (around line 572):

```python
                "code_review_model": state.get("code_review_model", "gemma4_code_review_agentic"),
                "code_review_specialist_enabled": state.get(
                    "code_review_specialist_enabled", "on"
                ),
```

If a `_toggle_to_env` helper does not exist, use inline logic:

```python
        enabled = state.get("code_review_specialist_enabled", "on").lower()
        enabled_flag = "1" if enabled in ("1", "true", "yes", "on") else "0"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_render_env_exports_code_review_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/runtime_control.py tools/router_py/test_self_analysis.py
git commit -m "feat(runtime_control): add code-review model state fields and CLI commands"
```

---

## Task 3: Implement model resolver and Ollama availability probe

**Files:**
- Create: `tools/router_py/code_review_model_resolver.py`
- Test: `tools/router_py/test_code_review_model_resolver.py`

**Interfaces:**
- Consumes: `LocalAnswerConfig` (code_review_model, code_review_specialist_enabled)
- Produces: `CodeReviewModelResolver.resolve()` → `(model_name: str, fallback_reason: str | None)`

- [ ] **Step 1: Write the failing test**

```python
import json
from unittest.mock import MagicMock

import pytest

from router_py.code_review_model_resolver import CodeReviewModelResolver


def test_resolver_uses_specialist_when_available_and_enabled():
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(
        return_value=["gemma4_code_review_agentic", "gemma4:12b-it-qat", "local-lucy-llama31"]
    )

    model, reason = resolver.resolve()
    assert model == "gemma4_code_review_agentic"
    assert reason is None


def test_resolver_falls_back_to_stock_gemma4_when_specialist_missing():
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=["gemma4:12b-it-qat", "local-lucy-llama31"])

    model, reason = resolver.resolve()
    assert model == "gemma4:12b-it-qat"
    assert reason == "specialist_model_not_installed"


def test_resolver_falls_back_to_default_when_specialist_disabled():
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = False
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=["gemma4_code_review_agentic"])

    model, reason = resolver.resolve()
    assert model == "local-lucy-llama31"
    assert reason == "specialist_disabled"


def test_resolver_errors_when_nothing_available():
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "missing-model"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=[])

    with pytest.raises(RuntimeError, match="No code-review model available"):
        resolver.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_code_review_model_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'router_py.code_review_model_resolver'`

- [ ] **Step 3: Implement the resolver**

Create `tools/router_py/code_review_model_resolver.py`:

```python
"""Resolve the effective Ollama model for Code Review / SELF_REVIEW mode."""

import json
import logging
import urllib.request
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class CodeReviewModelResolver:
    """Pick a code-review model from the configured fallback chain."""

    config: object  # LocalAnswerConfig-compatible
    ollama_url: str = "http://127.0.0.1:11434/api/tags"

    def resolve(self) -> tuple[str, Optional[str]]:
        """Return (model_name, fallback_reason).

        Fallback chain:
        1. Configured specialist model if enabled and installed.
        2. Existing stock Gemma 4 12B model (gemma4:12b-it-qat).
        3. Normally configured local model.
        4. RuntimeError if nothing is available.
        """
        installed = self._list_installed_models()

        if self.config.code_review_specialist_enabled:
            specialist = self.config.code_review_model
            if specialist and specialist in installed:
                logger.info(f"Code-review model selected: {specialist}")
                return specialist, None
            if specialist:
                logger.warning(
                    f"Code-review specialist model {specialist} not installed; "
                    "falling back to stock Gemma 4"
                )

        stock = "gemma4:12b-it-qat"
        if stock in installed:
            return stock, "specialist_model_not_installed"

        default = self.config.model
        if default and default in installed:
            return default, "stock_gemma4_not_installed"

        logger.error(
            "No code-review model available. Tried: %s",
            ", ".join(filter(None, [specialist if self.config.code_review_specialist_enabled else None, stock, default])),
        )
        raise RuntimeError(
            "No code-review model available. Install one of: "
            f"{specialist or ''}, {stock}, {default or ''}"
        )

    def _list_installed_models(self) -> list[str]:
        """Return installed Ollama model names."""
        try:
            req = urllib.request.Request(self.ollama_url, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            models = [m.get("name", "") for m in data.get("models", [])]
            # Ollama sometimes returns the name without tag; include both forms.
            expanded = set(models)
            for name in models:
                if ":" in name:
                    expanded.add(name.split(":")[0])
                else:
                    expanded.add(name + ":latest")
            return sorted(expanded)
        except Exception as e:
            logger.warning(f"Failed to list Ollama models: {e}")
            return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_code_review_model_resolver.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/code_review_model_resolver.py tools/router_py/test_code_review_model_resolver.py
git commit -m "feat(router): add code-review model resolver with fallback chain"
```

---

## Task 4: Wire the resolver into ExecutionEngine

**Files:**
- Modify: `tools/router_py/execution_engine.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `CodeReviewModelResolver`
- Produces: `ExecutionEngine._resolve_code_review_model()`, resolved model passed to `execute_self_analysis()` and stored in result metadata.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_execution_engine_selects_specialist_model_when_available(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = ExecutionEngine()
    monkeypatch.setattr(engine, "_load_control_state", lambda: {"self_analysis_mode": "on"})
    monkeypatch.setenv("LUCY_ROOT", str(project))

    # Mock resolver to return specialist.
    from router_py.code_review_model_resolver import CodeReviewModelResolver

    original_resolver = CodeReviewModelResolver

    class FakeResolver:
        def __init__(self, config):
            pass

        def resolve(self):
            return "gemma4_code_review_agentic", None

    monkeypatch.setattr(
        "router_py.execution_engine.CodeReviewModelResolver", FakeResolver
    )

    captured_model = []

    async def fake_execute_self_analysis(relative_path, project_root=None, model=None):
        captured_model.append(model)
        return MagicMock()

    monkeypatch.setattr(engine, "execute_self_analysis", fake_execute_self_analysis)
    monkeypatch.setattr(engine.state_writer, "write_state", lambda route, result, context: None)
    monkeypatch.setattr(
        engine.state_writer, "write_json_state_files", lambda route, result, context: None
    )

    intent = ClassificationResult(intent="analyze", intent_family="operational")
    route = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="operational",
        confidence=0.9,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    await engine.execute_async(
        intent,
        route,
        context={"question": "analyze sample.py"},
    )
    assert captured_model == ["gemma4_code_review_agentic"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_execution_engine_selects_specialist_model_when_available -v`
Expected: FAIL because `execute_self_analysis` receives `model=None`.

- [ ] **Step 3: Wire resolver into ExecutionEngine**

In `tools/router_py/execution_engine.py`:

1. Add import near the top (after existing router_py imports):

```python
from router_py.code_review_model_resolver import CodeReviewModelResolver
from router_py.local_answer import LocalAnswerConfig
```

2. Add a helper method (near `_extract_self_analysis_file_reference`):

```python
    def _resolve_code_review_model(self) -> tuple[str, str | None]:
        """Resolve effective Ollama model for SELF_REVIEW mode.

        Returns (model_name, fallback_reason).
        """
        config = LocalAnswerConfig.from_env()
        resolver = CodeReviewModelResolver(config)
        return resolver.resolve()
```

3. Modify `execute_self_analysis` signature and metadata (around line 829):

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
            ...
            response = await engine.suggest_improvements(relative_path, model=model)
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                ...
                metadata={
                    "self_review_model": model,
                    ...
                },
            )
```

4. Modify the dispatch in `execute_async` (around line 1095) to resolve the model:

```python
        # Self-analysis mode dispatch
        control_state = self._load_control_state() or {}
        if control_state.get("self_analysis_mode", "off").lower() == "on":
            file_ref = self._extract_self_analysis_file_reference(
                question, self._last_self_analysis_file
            )
            if file_ref:
                self._logger.info(f"Self-analysis mode dispatch: {file_ref}")
                try:
                    review_model, fallback_reason = self._resolve_code_review_model()
                except RuntimeError as e:
                    execution_time = int((time.time() - start_time) * 1000)
                    return ExecutionResult(
                        status="failed",
                        outcome_code="code_review_model_unavailable",
                        route="SELF_REVIEW",
                        provider="local",
                        provider_usage_class="local",
                        response_text=str(e),
                        error_message=str(e),
                        execution_time_ms=execution_time,
                        metadata={"reason": "code_review_model_unavailable"},
                    )
                result = await self.execute_self_analysis(
                    file_ref, model=review_model
                )
                self._last_self_analysis_file = file_ref
                ...
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_execution_engine_selects_specialist_model_when_available -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/execution_engine.py tools/router_py/test_self_analysis.py
git commit -m "feat(router): wire code-review model resolver into ExecutionEngine"
```

---

## Task 5: Apply code-review generation parameters in LocalAnswer

**Files:**
- Modify: `tools/router_py/local_answer.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `LocalAnswerConfig.code_review_*`
- Produces: `_set_generation_profile` returns code-review params for `SELF_REVIEW`; `_call_ollama` includes top_k when configured.

- [ ] **Step 1: Write the failing test**

```python
def test_self_review_uses_code_review_generation_params():
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig.from_env()
    config.code_review_temperature = 0.9
    config.code_review_top_p = 0.88
    config.code_review_top_k = 48
    config.code_review_max_tokens = 6000

    answer = LocalAnswer(config)
    profile, num_predict, instruction = answer._set_generation_profile(
        "SELF_REVIEW", "CHAT", "review this file"
    )
    assert profile == "self_review"
    assert num_predict == 6000
    assert "thorough" in instruction.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_self_review_uses_code_review_generation_params -v`
Expected: FAIL because `_set_generation_profile` ignores code-review params.

- [ ] **Step 3: Update generation profile for SELF_REVIEW**

In `tools/router_py/local_answer.py` `_set_generation_profile` (around line 1439), change the `SELF_REVIEW` branch:

```python
        if route == "SELF_REVIEW":
            return (
                "self_review",
                self.config.code_review_max_tokens,
                "- Provide a thorough, broad, balanced code review. "
                "Coverage before depth. Identify components, audit broadly, "
                "then investigate the most consequential findings.",
            )
```

In `_call_ollama` (around line 1977), add `top_k` when present and override temperature/top_p for SELF_REVIEW:

```python
        options = {
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "seed": self.config.seed,
            "num_predict": effective_num_predict,
            "keep_alive": self.config.keep_alive,
            "stop": ["\nUser:", "\nAssistant:", "\nUSER QUESTION:", "\nBACKGROUND CONTEXT:"],
        }
        if route_mode.upper() == "SELF_REVIEW":
            options["temperature"] = self.config.code_review_temperature
            options["top_p"] = self.config.code_review_top_p
            options["top_k"] = self.config.code_review_top_k
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_self_review_uses_code_review_generation_params -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/local_answer.py tools/router_py/test_self_analysis.py
git commit -m "feat(local_answer): apply code-review generation parameters for SELF_REVIEW"
```

---

## Task 6: Implement staged review prompt (Call 1)

**Files:**
- Modify: `tools/router_py/self_analysis.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: `FileAnalysis` metrics, source code, ruff output
- Produces: `SelfAnalysisEngine._build_staged_review_prompt()` returns the Call 1 prompt string.

- [ ] **Step 1: Write the failing test**

```python
def test_build_staged_review_prompt_contains_all_stages(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)
    analysis = engine.analyze_file("sample.py")
    prompt = engine._build_staged_review_prompt(analysis)

    assert "## Stage A: Code map" in prompt
    assert "## Stage B: Broad audit" in prompt
    assert "## Stage C: Coverage ledger" in prompt
    assert "Do not allow the first significant issue found" in prompt
    assert "No material issue identified" in prompt
    assert "Source code:" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_build_staged_review_prompt_contains_all_stages -v`
Expected: FAIL because `_build_staged_review_prompt` does not exist.

- [ ] **Step 3: Add staged prompt builder**

In `tools/router_py/self_analysis.py`, add a new method `_build_staged_review_prompt` next to `_build_llm_prompt`. Keep `_build_llm_prompt` for fallback/rollback.

```python
    def _build_staged_review_prompt(self, analysis: FileAnalysis) -> str:
        """Build the first staged-review prompt: map + broad audit + coverage ledger."""
        context = self._build_context(analysis)
        return f"""You are a careful code-review assistant. The user has supplied code for review.
This is a READ-ONLY review. Do not edit files, apply patches, run commands, install dependencies, delete files, commit, or push changes unless the user explicitly asks for implementation afterwards.

Follow the staged review below. Coverage must come before depth. Do not allow the first significant issue found to redefine the scope of the review. Complete the broad survey before performing deep analysis.

## Stage A: Code map

Identify the following WITHOUT proposing fixes:
- Major modules or sections
- Classes
- Important functions
- Entry points
- Data flow
- State ownership
- External dependencies
- Security boundaries
- Routing and fallback paths
- Error-handling paths

## Stage B: Broad audit

Inspect the complete supplied scope for:
- Functional correctness
- Logic errors
- Edge cases
- Error handling
- State consistency
- Concurrency or race conditions
- Routing and classifier behaviour
- Security and unsafe execution
- Resource management
- Performance
- Dead or duplicated logic
- Maintainability
- Logging and observability
- Test gaps

## Stage C: Coverage ledger

Produce a structured coverage record. For each major component, state:
- Component name
- Coverage status: complete, partial, or not reviewed
- Reason if partial or not reviewed
- Candidate concerns (or "No material issue identified")

Use conservative confidence labels only: confirmed, high confidence, moderate confidence, low confidence. Do not fabricate numerical confidence values.

## Output format

1. Scope received
2. Architecture summary
3. Coverage ledger
4. Confirmed findings
5. Probable findings requiring verification
6. Rejected or unconfirmed concerns
7. Severity and confidence
8. Recommended corrections
9. Required tests
10. Components not adequately reviewed

Every finding should include: location/component, description, evidence, consequence, triggering conditions, severity, confidence, recommended correction, validation test.

{context}

Begin the staged review.
"""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_build_staged_review_prompt_contains_all_stages -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/self_analysis.py tools/router_py/test_self_analysis.py
git commit -m "feat(self_analysis): add staged code-review prompt builder"
```

---

## Task 7: Implement conditional deep-dive call (Call 2)

**Files:**
- Modify: `tools/router_py/self_analysis.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: output of Call 1
- Produces: `SelfAnalysisEngine.suggest_improvements` returns combined report; new helper `_should_run_deep_dive()` and `_build_deep_dive_prompt()`.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_suggest_improvements_runs_staged_review(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)

    class FakeAnswerResult:
        text = "STAGE 1 REPORT\n\nCoverage ledger:\n- foo: complete\n\nConfirmed findings: none"

    calls = []

    class FakeLocalAnswer:
        async def generate_answer(self, **kwargs):
            calls.append(kwargs.get("query", ""))
            return FakeAnswerResult()

        async def close(self):
            pass

    fake_config = MagicMock()
    fake_config.model = "gemma4_code_review_agentic"
    fake_config_class = MagicMock(return_value=fake_config)

    fake_module = types.ModuleType("router_py.local_answer")
    fake_module.LocalAnswer = FakeLocalAnswer
    fake_module.LocalAnswerConfig = fake_config_class
    monkeypatch.setitem(sys.modules, "router_py.local_answer", fake_module)

    result = await engine.suggest_improvements("sample.py")
    assert "STAGE 1 REPORT" in result
    assert len(calls) == 1  # no deep dive when no findings
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_suggest_improvements_runs_staged_review -v`
Expected: FAIL because `suggest_improvements` still uses the old single prompt.

- [ ] **Step 3: Refactor suggest_improvements to use staged review**

In `tools/router_py/self_analysis.py`, modify `suggest_improvements`:

```python
    async def suggest_improvements(
        self, relative_path: str, model: str | None = None
    ) -> str:
        """Generate staged code-review suggestions for the given file."""
        analysis = self.analyze_file(relative_path)
        context = self._build_context(analysis)

        local_analysis = self._local_analysis_summary(analysis)

        # Stage 1: code map + broad audit + coverage ledger
        stage1_prompt = self._build_staged_review_prompt(analysis)
        stage1_result = await self._run_llm(
            stage1_prompt,
            route_mode="SELF_REVIEW",
            model=model,
        )

        # Stage 2: deep investigation only if warranted
        if self._should_run_deep_dive(stage1_result):
            stage2_prompt = self._build_deep_dive_prompt(analysis, stage1_result)
            stage2_result = await self._run_llm(
                stage2_prompt,
                route_mode="SELF_REVIEW",
                model=model,
            )
            return f"LOCAL analysis:\n{local_analysis}\n\nAUGMENTED suggestions:\n{stage1_result}\n\nDEEP INVESTIGATION:\n{stage2_result}"

        return f"LOCAL analysis:\n{local_analysis}\n\nAUGMENTED suggestions:\n{stage1_result}"
```

Add helper methods:

```python
    def _should_run_deep_dive(self, stage1_result: str) -> bool:
        """Run deep dive if the first stage reported candidate findings."""
        text = stage1_result.lower()
        # Simple heuristic: presence of confirmed or moderate+ confidence findings.
        confidence_markers = [
            "confidence: confirmed",
            "confidence: high confidence",
            "confidence: moderate confidence",
        ]
        return any(marker in text for marker in confidence_markers)

    def _build_deep_dive_prompt(self, analysis: FileAnalysis, stage1_result: str) -> str:
        context = self._build_context(analysis)
        return f"""You previously reviewed the following code and produced a coverage ledger with candidate findings. Now perform deep investigation and fix planning.

This remains READ-ONLY. Do not edit files or run commands.

## Stage D: Deep investigation

For each candidate finding in the previous report:
- Trace the finding through the relevant call path.
- Identify supporting evidence.
- Distinguish confirmed defects from suspicions.
- Check whether another component already prevents the apparent defect.
- Consider interactions between findings.
- Reject false positives before recommending changes.

## Stage E: Fix planning

For validated findings:
- Rank by severity and likelihood.
- Explain the smallest safe correction.
- Identify possible regressions.
- Recommend targeted tests.
- Do not modify code unless explicitly asked.

{context}

Previous findings:
{stage1_result}

Begin deep investigation and fix planning.
"""

    def _local_analysis_summary(self, analysis: FileAnalysis) -> str:
        parts = [
            f"File: {analysis.path}",
            f"Lines: {analysis.metrics.get('lines', 0)}",
            f"Functions: {analysis.metrics.get('functions', 0)}",
            f"Classes: {analysis.metrics.get('classes', 0)}",
        ]
        if analysis.hotspots:
            parts.append("Hotspots: " + ", ".join(analysis.hotspots))
        if analysis.todos:
            parts.append("TODOs: " + ", ".join(analysis.todos))
        return "\n".join(parts)
```

Extract the LLM call into `_run_llm`:

```python
    async def _run_llm(
        self,
        prompt: str,
        route_mode: str = "SELF_REVIEW",
        model: str | None = None,
    ) -> str:
        """Call LocalAnswer and return raw text."""
        try:
            from router_py.local_answer import LocalAnswer, LocalAnswerConfig

            config = LocalAnswerConfig.from_env()
            if model:
                config.model = model
            answer = LocalAnswer(config)
            result = await answer.generate_answer(
                query=prompt,
                route_mode=route_mode,
                output_mode="CHAT",
            )
            await answer.close()
            return result.text
        except ImportError:
            return "AUGMENTED suggestions: unavailable (LocalAnswer not importable)"
```

Remove the old inline LocalAnswer logic from `suggest_improvements`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_suggest_improvements_runs_staged_review -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/self_analysis.py tools/router_py/test_self_analysis.py
git commit -m "feat(self_analysis): implement two-call staged review with optional deep dive"
```

---

## Task 8: Detect truncation before inference

**Files:**
- Modify: `tools/router_py/self_analysis.py`
- Test: `tools/router_py/test_self_analysis.py`

**Interfaces:**
- Consumes: source text, `code_review_context_chars`
- Produces: `_build_context` records truncation in `analysis.truncated` and emits a warning.

- [ ] **Step 1: Write the failing test**

```python
def test_build_context_detects_truncation(tmp_path, monkeypatch):
    from router_py.local_answer import LocalAnswerConfig

    project = tmp_path / "project"
    project.mkdir()
    long_source = "x = 1\n" * 10000
    (project / "sample.py").write_text(long_source)

    config = LocalAnswerConfig.from_env()
    config.code_review_context_chars = 100

    engine = SelfAnalysisEngine(project_root=project, self_review_context_chars=100)
    analysis = engine.analyze_file("sample.py")
    context = engine._build_context(analysis)

    assert "[truncated at 100 characters" in context
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_build_context_detects_truncation -v`
Expected: FAIL because truncation detection is not explicit.

- [ ] **Step 3: Add explicit truncation detection**

In `tools/router_py/self_analysis.py` `_build_context` (around line 223), ensure truncation is recorded:

```python
    def _build_context(self, analysis: FileAnalysis) -> str:
        source = analysis.prompt_context
        max_chars = self.self_review_context_chars
        truncated = False
        if len(source) > max_chars:
            source = source[:max_chars]
            # Trim to last newline to avoid cutting a line mid-token.
            last_nl = source.rfind("\n")
            if last_nl > max_chars * 0.9:
                source = source[:last_nl]
            source += f"\n\n[truncated at {max_chars} characters; source exceeded code-review context limit]"
            truncated = True

        context_parts = [
            f"File metrics:\n{metrics_block}",
            ...
        ]
        if truncated:
            context_parts.append("\nWARNING: Source code was truncated before review.")
        return "\n\n".join(context_parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py::test_build_context_detects_truncation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/self_analysis.py tools/router_py/test_self_analysis.py
git commit -m "feat(self_analysis): detect and report source truncation before review"
```

---

## Task 9: Suppress Kokoro TTS output for SELF_REVIEW

**Files:**
- Modify: `ui-v10/app/main_window.py`
- Test: `ui-v10/tests/test_self_analysis_mode_offscreen.py`

**Interfaces:**
- Consumes: `CommandResult` metadata containing `route`
- Produces: `_speak_response_text` skipped when `route == "SELF_REVIEW"`.

- [ ] **Step 1: Write the failing test**

```python
def test_self_review_response_does_not_trigger_tts(qtbot, monkeypatch):
    from ui-v10.app.main_window import MainWindow
    from ui-v10.app.services.runtime_bridge import CommandResult

    window = MainWindow()
    spoken = []
    monkeypatch.setattr(window, "_speak_response_text", lambda text, meta: spoken.append(text))

    result = CommandResult(
        command="submit_request",
        status="success",
        stdout="Review report",
        stderr="",
        metadata={"route": "SELF_REVIEW"},
    )
    window._handle_submit_complete(result)
    assert spoken == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest ui-v10/tests/test_self_analysis_mode_offscreen.py::test_self_review_response_does_not_trigger_tts -v`
Expected: FAIL because `_handle_submit_complete` does not check the route.

- [ ] **Step 3: Add TTS suppression**

In `ui-v10/app/main_window.py` `_handle_submit_complete` (around line 906), before calling `_speak_response_text`:

```python
        # Suppress text-to-speech for self-review / code-review reports.
        is_self_review = result.metadata.get("route") == "SELF_REVIEW" if result.metadata else False
        if not is_self_review:
            self._speak_response_text(stdout, result.metadata)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest ui-v10/tests/test_self_analysis_mode_offscreen.py::test_self_review_response_does_not_trigger_tts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui-v10/app/main_window.py ui-v10/tests/test_self_analysis_mode_offscreen.py
git commit -m "feat(hmi): suppress Kokoro TTS output for SELF_REVIEW responses"
```

---

## Task 10: Add fallback and error-handling tests

**Files:**
- Test: `tools/router_py/test_self_analysis.py`, `tools/router_py/test_code_review_model_resolver.py`

- [ ] **Step 1: Add remaining fallback tests**

In `tools/router_py/test_self_analysis.py`:

```python
@pytest.mark.asyncio
async def test_execution_engine_returns_error_when_no_code_review_model_available(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = ExecutionEngine()
    monkeypatch.setattr(engine, "_load_control_state", lambda: {"self_analysis_mode": "on"})
    monkeypatch.setenv("LUCY_ROOT", str(project))
    monkeypatch.setattr(
        engine, "_resolve_code_review_model", lambda: (_ for _ in ()).throw(RuntimeError("No model"))
    )

    intent = ClassificationResult(intent="analyze", intent_family="operational")
    route = RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family="operational",
        confidence=0.9,
        provider="local",
        provider_usage_class="local",
        evidence_mode="",
    )

    result = await engine.execute_async(
        intent,
        route,
        context={"question": "analyze sample.py"},
    )
    assert result.status == "failed"
    assert result.outcome_code == "code_review_model_unavailable"
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tools/router_py/test_self_analysis.py tools/router_py/test_code_review_model_resolver.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/test_self_analysis.py tools/router_py/test_code_review_model_resolver.py
git commit -m "test(router): add code-review model fallback and error cases"
```

---

## Task 11: Add HMI Engineering mode toggle

**Files:**
- Modify: `ui-v10/app/panels/control_panel.py`
- Test: `ui-v10/tests/test_self_analysis_mode_offscreen.py`

**Interfaces:**
- Consumes: state `self_analysis_mode`, `code_review_specialist_enabled`
- Produces: existing checkbox can be relabeled; new signal optional.

- [ ] **Step 1: Update control panel label and tooltip**

In `ui-v10/app/panels/control_panel.py` where `_self_analysis_selector` is created (around line 256):

```python
        self._self_analysis_selector = QCheckBox("Engineering mode")
        self._self_analysis_selector.setToolTip(
            "Enable code review and analysis mode with specialist model support."
        )
```

If the signal name `self_analysis_change_requested` is wired elsewhere, keep it for backward compatibility. Optionally update display text in `_handle_self_analysis_changed`.

- [ ] **Step 2: Add test**

```python
def test_engineering_mode_checkbox_label(qtbot):
    from ui-v10.app.panels.control_panel import ControlPanel

    panel = ControlPanel(current_state={"self_analysis_mode": "off"})
    assert panel._self_analysis_selector.text() == "Engineering mode"
```

- [ ] **Step 3: Run tests**

Run: `python3 -m pytest ui-v10/tests/test_self_analysis_mode_offscreen.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add ui-v10/app/panels/control_panel.py ui-v10/tests/test_self_analysis_mode_offscreen.py
git commit -m "feat(hmi): relabel self-analysis toggle as Engineering mode"
```

---

## Task 12: Run regression suites

- [ ] **Step 1: Run router tests**

```bash
python3 -m pytest tools/router_py/test_self_analysis.py tools/router_py/test_local_answer.py tools/router_py/test_code_review_model_resolver.py -q
```
Expected: all pass

- [ ] **Step 2: Run HMI offscreen tests**

```bash
python3 -m pytest ui-v10/tests/test_self_analysis_mode_offscreen.py -q
```
Expected: all pass

- [ ] **Step 3: Run full regression suite**

```bash
python3 -m pytest tools/router_py ui-v10/tests -q
```
Expected: all pass (or pre-existing failures documented)

- [ ] **Step 4: Run ruff**

```bash
ruff check tools/router_py ui-v10/app ui-v10/tests
ruff format --check tools/router_py ui-v10/app ui-v10/tests
```
Expected: clean

- [ ] **Step 5: Commit any formatting fixes**

```bash
git add -A
git commit -m "style: ruff formatting for code-review specialist feature"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Model registration → Task 1
   - Configuration/state → Task 2
   - Fallback chain/availability → Task 3, Task 10
   - Staged review → Task 6
   - Generation params → Task 5
   - Voice suppression → Task 9
   - Read-only enforcement → Task 6 (prompt instruction)
   - Truncation detection → Task 8
   - Logging → partial (resolver logs); add explicit logging task if required
   - Regression tests → Task 12

2. **Placeholder scan:** No TBD/TODO. All code blocks are concrete.

3. **Type consistency:** `CodeReviewModelResolver.resolve()` returns `(str, Optional[str])`. `ExecutionEngine.execute_self_analysis` accepts `model: str | None`. `LocalAnswerConfig` fields are consistent.

4. **Gap:** Logging observability from Phase 10 is not exhaustively tested. Add per-call logging inside `SelfAnalysisEngine._run_llm` and `ExecutionEngine._resolve_code_review_model` as part of Task 6/4 if required.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-16-gemma4-code-review-model.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using `executing-plans`, batch execution with checkpoints.

Which approach?
