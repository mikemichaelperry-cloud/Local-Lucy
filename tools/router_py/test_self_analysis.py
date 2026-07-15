import asyncio
import sys
from pathlib import Path

import pytest

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
