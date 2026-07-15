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
