import pytest

from router_py import model_residency
from router_py.model_residency import (
    LOCAL_LUCY_MODEL_PREFIXES,
    assert_single_local_lucy_model,
    get_local_lucy_loaded_models,
    list_loaded_ollama_models,
)


class FakeCompletedProcess:
    def __init__(self, stdout: str):
        self.stdout = stdout


def test_list_loaded_ollama_models_parses_subprocess_output(monkeypatch):
    output = (
        "NAME\tID\tSIZE\tPROCESSOR\tUNTIL\n"
        "local-lucy-gemma4:latest\tabcd1234\t4.9GB\t100% GPU\t2 hours from now\n"
        "local-lucy-llama31:latest\tefgh5678\t6.2GB\t100% GPU\t1 hour from now\n"
    )

    def fake_run(*args, **kwargs):
        return FakeCompletedProcess(stdout=output)

    monkeypatch.setattr(model_residency.subprocess, "run", fake_run)
    assert list_loaded_ollama_models() == [
        "local-lucy-gemma4:latest",
        "local-lucy-llama31:latest",
    ]


def test_list_loaded_ollama_models_returns_empty_on_exception(monkeypatch):
    def fake_run(*args, **kwargs):
        raise RuntimeError("ollama not installed")

    monkeypatch.setattr(model_residency.subprocess, "run", fake_run)
    assert list_loaded_ollama_models() == []


def test_residency_helper_detects_multiple(monkeypatch):
    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: ["local-lucy-gemma4:latest", "local-lucy-llama31:latest"],
    )
    assert len(get_local_lucy_loaded_models()) == 2


def test_get_local_lucy_loaded_models_filters_prefix(monkeypatch):
    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: [
            "local-lucy-gemma4:latest",
            "some-other-model:latest",
            "local-lucy-llama31:latest",
        ],
    )
    models = get_local_lucy_loaded_models()
    assert models == ["local-lucy-gemma4:latest", "local-lucy-llama31:latest"]
    assert all(any(m.startswith(p) for p in LOCAL_LUCY_MODEL_PREFIXES) for m in models)


def test_assert_single_local_lucy_model_passes_with_zero_or_one(monkeypatch):
    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: ["local-lucy-gemma4:latest"],
    )
    assert assert_single_local_lucy_model(label="test") is None

    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: [],
    )
    assert assert_single_local_lucy_model(label="test-empty") is None


def test_assert_single_local_lucy_model_raises_when_multiple(monkeypatch):
    monkeypatch.setattr(
        "router_py.model_residency.list_loaded_ollama_models",
        lambda: ["local-lucy-gemma4:latest", "local-lucy-llama31:latest"],
    )
    with pytest.raises(RuntimeError) as exc_info:
        assert_single_local_lucy_model(label="stage-check")
    assert "stage-check: more than one Local Lucy model loaded" in str(exc_info.value)
