import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from router_py.code_review_model_resolver import CodeReviewModelResolver


def test_resolver_uses_specialist_when_available_and_enabled():
    """Specialist model is installed and enabled → it is selected with no fallback reason."""
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
    """Specialist is enabled but not installed → fall back to stock Gemma 4."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(
        return_value=["gemma4:12b-it-qat", "local-lucy-llama31"]
    )

    model, reason = resolver.resolve()
    assert model == "gemma4:12b-it-qat"
    assert reason == "specialist_model_not_installed"


def test_resolver_disabled_skips_specialist_and_uses_stock_when_available():
    """Specialist is disabled and stock Gemma 4 is installed → use stock model."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = False
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(
        return_value=["gemma4:12b-it-qat", "local-lucy-llama31"]
    )

    model, reason = resolver.resolve()
    assert model == "gemma4:12b-it-qat"
    assert reason == "specialist_disabled"


def test_resolver_disabled_falls_back_to_default_when_stock_missing():
    """Specialist is disabled and stock Gemma 4 is missing → fall back to default model."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = False
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=["local-lucy-llama31"])

    model, reason = resolver.resolve()
    assert model == "local-lucy-llama31"
    assert reason == "specialist_disabled"


def test_resolver_disabled_errors_when_nothing_available():
    """Specialist disabled and no stock/default model installed → clear RuntimeError."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = False
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=[])

    with pytest.raises(RuntimeError, match="No code-review model available"):
        resolver.resolve()


def test_resolver_errors_when_nothing_available():
    """Specialist enabled but neither specialist, stock, nor default model installed → RuntimeError."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "missing-model"

    resolver = CodeReviewModelResolver(config)
    resolver._list_installed_models = MagicMock(return_value=[])

    with pytest.raises(RuntimeError, match="No code-review model available"):
        resolver.resolve()


def test_resolver_errors_when_ollama_unreachable():
    """Ollama is unreachable → installed list is empty → resolve() raises RuntimeError."""
    config = MagicMock()
    config.code_review_model = "gemma4_code_review_agentic"
    config.code_review_specialist_enabled = True
    config.model = "local-lucy-llama31"

    resolver = CodeReviewModelResolver(config)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        with pytest.raises(RuntimeError, match="No code-review model available"):
            resolver.resolve()


def test_list_installed_models_returns_names_and_tag_aliases():
    """Ollama tag response is parsed and expanded with tag aliases."""
    payload = json.dumps(
        {"models": [{"name": "gemma4:12b-it-qat"}, {"name": "local-lucy-llama31"}]}
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = payload

    config = MagicMock()
    resolver = CodeReviewModelResolver(config)
    with patch("urllib.request.urlopen", return_value=mock_response):
        models = resolver._list_installed_models()

    assert "gemma4:12b-it-qat" in models
    assert "gemma4" in models
    assert "local-lucy-llama31" in models
    assert "local-lucy-llama31:latest" in models


def test_list_installed_models_returns_empty_when_ollama_unreachable():
    """Ollama network failure is swallowed and returns an empty model list."""
    config = MagicMock()
    resolver = CodeReviewModelResolver(config)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
        models = resolver._list_installed_models()

    assert models == []
