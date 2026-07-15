import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from router_py.execution_engine import ExecutionEngine
from router_py.request_types import ClassificationResult, RoutingDecision
from router_py.self_analysis import FileAnalysis, SelfAnalysisEngine
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
        engine, "_extract_self_analysis_file_reference", lambda question: "sample.py"
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
