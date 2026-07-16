import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from router_py.execution_engine import ExecutionEngine
from router_py.request_types import ClassificationResult, RoutingDecision
from router_py.self_analysis import FileAnalysis, SelfAnalysisEngine, _MAX_FILE_SIZE_BYTES
from runtime_control import (
    build_parser,
    build_self_check_payload,
    load_or_create_state,
    render_env,
    ResolvedRuntimePaths,
)


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


def test_analyze_file_includes_source_code_in_prompt(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def hello():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)
    result = engine.analyze_file("sample.py")

    assert "Source code:" in result.prompt_context
    assert "def hello():" in result.prompt_context


def test_path_traversal_raises(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    sibling = tmp_path / "project2"
    sibling.mkdir()
    (sibling / "secret.py").write_text("x = 1\n")

    engine = SelfAnalysisEngine(project_root=project)

    with pytest.raises(ValueError, match="escapes project root"):
        engine.analyze_file("../project2/secret.py")

    with pytest.raises(ValueError, match="escapes project root"):
        engine.analyze_file("../etc/passwd")


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
    huge.write_text("x" * (_MAX_FILE_SIZE_BYTES + 1))

    engine = SelfAnalysisEngine(project_root=project)
    with pytest.raises(ValueError, match="File too large"):
        engine.analyze_file("huge.py")


def test_analyze_file_accepts_exact_max_size(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    boundary = project / "boundary.py"
    boundary.write_text("x" * _MAX_FILE_SIZE_BYTES)

    engine = SelfAnalysisEngine(project_root=project)
    result = engine.analyze_file("boundary.py")

    assert isinstance(result, FileAnalysis)
    assert result.path == "boundary.py"


def test_suggest_improvements_local_when_import_missing(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)

    class FakeModule:
        def __getattr__(self, name):
            raise ImportError("local_answer unavailable")

    monkeypatch.setitem(sys.modules, "router_py.local_answer", FakeModule())
    result = asyncio.run(engine.suggest_improvements("sample.py"))

    assert "LOCAL analysis:" in result
    assert "AUGMENTED suggestions: unavailable" in result
    assert "LocalAnswer not importable" in result


@pytest.mark.asyncio
async def test_execution_engine_self_analysis_route(tmp_path, monkeypatch):
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
    monkeypatch.setattr(engine, "_load_control_state", lambda: {"self_analysis_mode": "on"})
    monkeypatch.setattr(
        engine,
        "_extract_self_analysis_file_reference",
        lambda question, last_file=None: "sample.py",
    )
    monkeypatch.setenv("LUCY_ROOT", str(project))

    # Mock LocalAnswer to avoid a real Ollama call.
    fake_answer_result = types.SimpleNamespace(text="mocked suggestion")
    fake_local_answer = MagicMock()
    fake_local_answer.generate_answer = MagicMock(return_value=asyncio.Future())
    fake_local_answer.generate_answer.return_value.set_result(fake_answer_result)
    fake_local_answer.close = MagicMock(return_value=asyncio.Future())
    fake_local_answer.close.return_value.set_result(None)

    fake_config = MagicMock()
    fake_config.model = "local-lucy-llama31"
    fake_config_class = MagicMock(return_value=fake_config)

    fake_module = types.ModuleType("router_py.local_answer")
    fake_module.LocalAnswer = MagicMock(return_value=fake_local_answer)
    fake_module.LocalAnswerConfig = fake_config_class
    monkeypatch.setitem(sys.modules, "router_py.local_answer", fake_module)

    # Track state writes.
    written_state = []
    written_json_state = []
    monkeypatch.setattr(
        engine.state_writer,
        "write_state",
        lambda route, result, context: written_state.append((route, result, context)),
    )
    monkeypatch.setattr(
        engine.state_writer,
        "write_json_state_files",
        lambda route, result, context: written_json_state.append((route, result, context)),
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

    assert result.route == "SELF_REVIEW"
    assert result.outcome_code == "answered"
    assert "LOCAL analysis" in result.response_text
    assert "mocked suggestion" in result.response_text
    assert len(written_state) == 1
    assert written_state[0][0].route == "SELF_REVIEW"
    assert len(written_json_state) == 1
    assert written_json_state[0][0].route == "SELF_REVIEW"


def _make_self_analysis_root(tmp_path, monkeypatch) -> Path:
    """Create a temporary project root and point execution_engine.ROOT_DIR at it."""
    root = tmp_path / "lucy_root"
    root.mkdir()
    monkeypatch.setattr("router_py.execution_engine.ROOT_DIR", root)
    return root


def test_extract_self_analysis_file_reference_ignores_non_self_analysis_questions(
    tmp_path, monkeypatch
):
    root = _make_self_analysis_root(tmp_path, monkeypatch)
    (root / "sample.py").write_text("x = 1\n")
    engine = ExecutionEngine()
    assert engine._extract_self_analysis_file_reference("what is sample.py") is None
    assert (
        engine._extract_self_analysis_file_reference("analyze sample.py", last_file="sample.py")
        == "sample.py"
    )


def test_extract_self_analysis_followup_reuses_last_file(tmp_path, monkeypatch):
    root = _make_self_analysis_root(tmp_path, monkeypatch)
    (root / "first.py").write_text("x = 1\n")
    (root / "second.py").write_text("y = 2\n")
    engine = ExecutionEngine()

    # First turn: explicit path is stored mentally by the caller.
    assert engine._extract_self_analysis_file_reference("analyze first.py") == "first.py"

    # Follow-up without a path reuses the last file.
    assert (
        engine._extract_self_analysis_file_reference("analyze it again", last_file="first.py")
        == "first.py"
    )
    assert (
        engine._extract_self_analysis_file_reference("review that file", last_file="first.py")
        == "first.py"
    )
    assert (
        engine._extract_self_analysis_file_reference("improve this file", last_file="first.py")
        == "first.py"
    )
    assert (
        engine._extract_self_analysis_file_reference("inspect the file", last_file="first.py")
        == "first.py"
    )
    assert (
        engine._extract_self_analysis_file_reference("review same file", last_file="first.py")
        == "first.py"
    )


def test_extract_self_analysis_explicit_path_overrides_last_file(tmp_path, monkeypatch):
    root = _make_self_analysis_root(tmp_path, monkeypatch)
    (root / "first.py").write_text("x = 1\n")
    (root / "second.py").write_text("y = 2\n")
    engine = ExecutionEngine()

    assert (
        engine._extract_self_analysis_file_reference("analyze second.py", last_file="first.py")
        == "second.py"
    )


@pytest.mark.asyncio
async def test_execution_engine_remembers_last_self_analysis_file(tmp_path, monkeypatch):
    """The engine stores the last successfully dispatched self-analysis file."""
    root = _make_self_analysis_root(tmp_path, monkeypatch)
    (root / "sample.py").write_text("def foo():\n    pass\n")

    engine = ExecutionEngine()
    monkeypatch.setattr(engine, "_load_control_state", lambda: {"self_analysis_mode": "on"})

    # Mock execute_self_analysis to avoid real Ollama calls and to capture calls.
    calls = []

    async def fake_execute_self_analysis(relative_path, project_root=None, model=None):
        calls.append(relative_path)
        return MagicMock()

    monkeypatch.setattr(engine, "execute_self_analysis", fake_execute_self_analysis)

    # Mock the state writers so execute_async can complete cleanly.
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

    # First turn: explicit file path.
    await engine.execute_async(
        intent,
        route,
        context={"question": "analyze sample.py"},
    )
    assert engine._last_self_analysis_file == "sample.py"
    assert calls == ["sample.py"]

    # Second turn: follow-up without a path reuses the remembered file.
    await engine.execute_async(
        intent,
        route,
        context={"question": "review it again"},
    )
    assert engine._last_self_analysis_file == "sample.py"
    assert calls == ["sample.py", "sample.py"]


def test_runtime_control_cli_supports_set_self_analysis_mode(tmp_path, monkeypatch, capsys):
    state_file = tmp_path / "state.json"
    state_file.write_text('{"self_analysis_mode": "off"}')

    argv = [
        "runtime_control",
        "--state-file",
        str(state_file),
        "set-self-analysis-mode",
        "--value",
        "on",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    monkeypatch.setattr("runtime_control.enforce_authority_contract", lambda **kwargs: None)

    from runtime_control import main

    assert main() == 0
    state = load_or_create_state(state_file, refresh_timestamp=False)
    assert state["self_analysis_mode"] == "on"


def test_render_env_exports_self_analysis_mode():
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
        "self_analysis_mode": "on",
    }
    env = render_env(state)
    assert "LUCY_SELF_ANALYSIS_MODE=1" in env


def test_self_check_payload_includes_self_analysis_mode(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text('{"self_analysis_mode": "on"}')
    namespace_root = tmp_path / "namespace"
    namespace_root.mkdir()
    resolved = ResolvedRuntimePaths(
        state_file=state_file,
        namespace_root=namespace_root,
        resolution_source="test",
        warning_codes=(),
        warnings=(),
    )
    payload = build_self_check_payload(resolved)
    assert payload["control_state"]["self_analysis_mode"] == "on"


def test_self_review_route_gets_large_budget():
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig.from_env()
    answer = LocalAnswer(config)
    profile, num_predict, instruction = answer._set_generation_profile(
        "SELF_REVIEW", "CHAT", "review this file"
    )

    assert profile == "self_review"
    assert num_predict == config.self_review_max_tokens
    assert num_predict >= 4096
    assert "thorough" in instruction.lower()


@pytest.mark.asyncio
async def test_suggest_improvements_uses_self_review_route(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    (project / "sample.py").write_text("def foo():\n    pass\n")

    engine = SelfAnalysisEngine(project_root=project)

    class FakeAnswerResult:
        text = "mocked suggestion"

    created_instances = []

    class FakeLocalAnswer:
        def __init__(self, config):
            self.config = config
            self.last_kwargs = None
            created_instances.append(self)

        async def generate_answer(self, **kwargs):
            self.last_kwargs = kwargs
            return FakeAnswerResult()

        async def close(self):
            pass

    fake_config = MagicMock()
    fake_config.model = "local-lucy-llama31"
    fake_config_class = MagicMock(return_value=fake_config)

    fake_module = types.ModuleType("router_py.local_answer")
    fake_module.LocalAnswer = FakeLocalAnswer
    fake_module.LocalAnswerConfig = fake_config_class
    monkeypatch.setitem(sys.modules, "router_py.local_answer", fake_module)

    result = await engine.suggest_improvements("sample.py")
    assert "LOCAL analysis" in result
    assert "mocked suggestion" in result
    assert len(created_instances) == 1
    assert created_instances[0].last_kwargs.get("route_mode") == "SELF_REVIEW"


def test_analyze_file_truncates_very_long_source(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    source = "x = 1\n" * 50000  # ~300k chars
    (project / "long.py").write_text(source)

    engine = SelfAnalysisEngine(project_root=project, self_review_context_chars=100)
    result = engine.analyze_file("long.py")

    assert (
        "[truncated at 100 characters; consider reviewing a smaller module]"
        in result.prompt_context
    )
    assert len(result.prompt_context) < len(source) + 500


def test_self_review_context_chars_must_be_positive():
    with pytest.raises(ValueError, match="self_review_context_chars must be positive"):
        SelfAnalysisEngine(project_root=Path("."), self_review_context_chars=0)

    with pytest.raises(ValueError, match="self_review_context_chars must be positive"):
        SelfAnalysisEngine(project_root=Path("."), self_review_context_chars=-1)


def test_cache_helpers_no_op_when_disabled(tmp_path):
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig.from_env()
    config.cache_dir = tmp_path
    answer = LocalAnswer(config)

    # Helpers do not accept a cache_bypass flag; the caller guards access.
    answer._cache_store("q1", "v1", "cached text")
    assert answer._cache_load("q1", "v1") is not None

    # When disabled at the config level, load/store are no-ops.
    config.cache_enabled = False
    assert answer._cache_load("q1", "v1") is None
    answer._cache_store("q2", "v2", "ignored text")
    assert answer._cache_load("q2", "v2") is None


@pytest.mark.asyncio
async def test_self_review_generate_answer_bypasses_cache(tmp_path, monkeypatch):
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig.from_env()
    config.cache_dir = tmp_path
    answer = LocalAnswer(config)

    def fail_if_called(name):
        def _fail(*args, **kwargs):
            raise AssertionError(f"{name} should not be called for SELF_REVIEW")

        return _fail

    monkeypatch.setattr(answer, "_cache_load", fail_if_called("_cache_load"))
    monkeypatch.setattr(answer, "_cache_store", fail_if_called("_cache_store"))

    async def fake_call_ollama(prompt, num_predict, temp_override=None, route_mode="LOCAL"):
        return "mocked self-review", 1

    monkeypatch.setattr(answer, "_call_ollama", fake_call_ollama)

    result = await answer.generate_answer(query="review sample.py", route_mode="SELF_REVIEW")

    assert result.text == "mocked self-review"
    assert result.from_cache is False
    assert not any(tmp_path.iterdir())


@pytest.mark.asyncio
async def test_self_review_short_circuit_bypass(monkeypatch):
    """A SELF_REVIEW query containing 807/tube triggers must return the model answer."""
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig()
    config.model = "local-lucy-llama31"
    answer = LocalAnswer(config)

    async def fake_call_ollama(prompt, num_predict, temp_override=None, route_mode="LOCAL"):
        return "model generated review text", 1

    monkeypatch.setattr(answer, "_call_ollama", fake_call_ollama)

    # Query matches every term in the 807 short-circuit regex guard.
    triggering_query = "review amplifier.py: a pair of 807s in push-pull class AB1 power output"
    result = await answer.generate_answer(query=triggering_query, route_mode="SELF_REVIEW")

    assert result.text == "model generated review text"
    assert "pair total" not in result.text
    assert "25-35 W" not in result.text


@pytest.mark.asyncio
async def test_self_review_ollama_payload_uses_self_review_budget(monkeypatch):
    """The SELF_REVIEW budget must reach the Ollama payload unchanged via generate_answer."""
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig()
    config.self_review_max_tokens = 4096
    config.num_predict_long = 1536
    config.model = "local-lucy-llama31"
    answer = LocalAnswer(config)

    captured = {}

    async def fake_call_ollama(prompt, num_predict, temp_override=None, route_mode="LOCAL"):
        captured["num_predict"] = num_predict
        return "mocked self-review", 1

    monkeypatch.setattr(answer, "_call_ollama", fake_call_ollama)

    result = await answer.generate_answer(query="review sample.py", route_mode="SELF_REVIEW")
    assert result.text == "mocked self-review"
    assert captured["num_predict"] == config.self_review_max_tokens


@pytest.mark.asyncio
async def test_self_review_ollama_payload_includes_self_review_budget(monkeypatch):
    """The actual JSON body sent to Ollama uses the SELF_REVIEW token budget."""
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig

    config = LocalAnswerConfig()
    config.self_review_max_tokens = 4096
    config.num_predict_long = 1536
    config.model = "local-lucy-llama31"
    answer = LocalAnswer(config)

    captured_payload = {}

    class FakeResponse:
        async def json(self):
            return {"response": "mocked payload self-review"}

        def raise_for_status(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FakeSession:
        def post(self, url, json):
            captured_payload["url"] = url
            captured_payload["json"] = json
            return FakeResponse()

    async def fake_get_session():
        return FakeSession()

    monkeypatch.setattr(answer, "_get_session", fake_get_session)

    result = await answer.generate_answer(query="review sample.py", route_mode="SELF_REVIEW")

    assert result.text == "mocked payload self-review"
    assert captured_payload["url"] == config.ollama_url
    assert captured_payload["json"]["options"]["num_predict"] == config.self_review_max_tokens


def test_analyze_file_handles_invalid_utf8(tmp_path):
    """Invalid UTF-8 bytes are replaced rather than crashing analysis."""
    project = tmp_path / "project"
    project.mkdir()
    file_path = project / "bad.py"
    file_path.write_bytes(b"# invalid bytes: \xff\xfe\nx = 1\n")

    engine = SelfAnalysisEngine(project_root=project)
    result = engine.analyze_file("bad.py")

    assert isinstance(result, FileAnalysis)
    assert "\ufffd" in result.prompt_context
    assert "x = 1" in result.prompt_context


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
