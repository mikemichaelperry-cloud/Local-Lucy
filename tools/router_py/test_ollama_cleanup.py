#!/usr/bin/env python3
"""Tests for Ollama cleanup helpers."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

from router_py import ollama_cleanup as oc


def test_is_lucy_model() -> None:
    assert oc.is_lucy_model("local-lucy-llama31:latest")
    assert oc.is_lucy_model("local-lucy-fast")
    assert oc.is_lucy_model("LOCAL-LUCY-MISTRAL")  # case-insensitive
    assert not oc.is_lucy_model("llama3.1:latest")
    assert not oc.is_lucy_model("")


def test_list_loaded_models_parses_api_response() -> None:
    payload = json.dumps(
        {
            "models": [
                {"name": "local-lucy-llama31:latest", "size": 123},
                {"model": "local-lucy-fast:latest", "size": 456},
            ]
        }
    ).encode("utf-8")
    mock_response = MagicMock()
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_response.read.return_value = payload

    with patch("urllib.request.urlopen", return_value=mock_response):
        models = oc.list_loaded_models()

    assert models == ["local-lucy-llama31:latest", "local-lucy-fast:latest"]


def test_list_loaded_models_returns_empty_on_error() -> None:
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        assert oc.list_loaded_models() == []


def test_unload_model_uses_cli_first() -> None:
    with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
        assert oc.unload_model("local-lucy-fast:latest")
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[:2] == ["ollama", "stop"]


def test_unload_model_falls_back_to_api() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError("ollama")):
        mock_response = MagicMock()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            assert oc.unload_model("local-lucy-fast:latest")
    mock_urlopen.assert_called_once()


def test_unload_all_lucy_models_unloads_only_lucy_models() -> None:
    with patch.object(
        oc,
        "list_loaded_models",
        return_value=[
            "local-lucy-llama31:latest",
            "llama3.1:latest",
            "local-lucy-fast:latest",
        ],
    ):
        with patch.object(oc, "unload_model", return_value=True) as mock_unload:
            attempted = oc.unload_all_lucy_models()

    assert sorted(attempted) == sorted(
        [
            "local-lucy-llama31:latest",
            "local-lucy-fast:latest",
        ]
    )
    assert mock_unload.call_count == 2


def test_shutdown_cleanup_logs_unloaded_models() -> None:
    with patch.object(
        oc, "unload_all_lucy_models", return_value=["local-lucy-fast:latest"]
    ) as mock_unload:
        oc.shutdown_cleanup()
    mock_unload.assert_called_once()
