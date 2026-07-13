"""Focused tests for the Local Lucy web adapter.

These tests exercise the HTTP surface and the integration boundary with the
Local Lucy pipeline. They do not duplicate routing, search, memory, or model
logic tests that already exist elsewhere.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import BasicAuth
from aiohttp.test_utils import TestClient, TestServer

# Ensure ``tools`` is on sys.path the same way the server sets it up at
# runtime, so ``import router_py`` resolves to ``tools/router_py``.
REPO_ROOT = __file__.rsplit("/web_adapter/", 1)[0]
if f"{REPO_ROOT}/tools" not in sys.path:
    sys.path.insert(0, f"{REPO_ROOT}/tools")

from web_adapter.server import create_app, main  # noqa: E402


def _ollama_reachable() -> bool:
    url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/tags")
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status == 200
    except Exception:
        return False


@pytest.fixture
def app_no_auth():
    """Application with no authentication for most endpoint tests."""
    return create_app({"auth_token": ""})


@pytest.fixture
def app_with_auth():
    """Application requiring authentication."""
    return create_app({"auth_token": "secret-test-token"})


@pytest.mark.asyncio
async def test_index_returns_html(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.get("/")
        assert resp.status == 200
        text = await resp.text()
        assert "Local Lucy" in text
        assert "<textarea" in text


@pytest.mark.asyncio
async def test_status_endpoint(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.get("/api/status")
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert "active_model" in data
        assert "available" in data


@pytest.mark.asyncio
async def test_models_endpoint(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.get("/api/models")
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert "local-lucy-llama31" in data["models"]
        assert "gemma4:12b-it-qat" in data["models"]
        assert data["active_model"] in data["models"] or data["active_model"] == "unknown"


@pytest.mark.asyncio
async def test_ask_empty_question(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post("/api/ask", json={"question": "   "})
        assert resp.status == 400
        data = await resp.json()
        assert data["ok"] is False


@pytest.mark.asyncio
async def test_ask_question_too_long(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post(
            "/api/ask",
            json={"question": "x" * 10000},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "exceeds" in data["error"].lower()


@pytest.mark.asyncio
async def test_ask_invalid_model(app_no_auth):
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post(
            "/api/ask",
            json={"question": "What is 2+2?", "model": "evil-model ../../etc"},
        )
        assert resp.status == 400
        data = await resp.json()
        assert "unsupported" in data["error"].lower()


@pytest.mark.asyncio
async def test_ask_success_mocked(app_no_auth, monkeypatch):
    def _fake_execute_plan_python(*, question, policy, timeout, surface, context, model=None):
        return SimpleNamespace(
            outcome_code="answered",
            response_text=f"Mocked answer for: {question}",
            route="LOCAL",
            provider="local",
        )

    import web_adapter.server as server_module

    monkeypatch.setattr(server_module, "execute_plan_python", _fake_execute_plan_python)

    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post("/api/ask", json={"question": "Hello?"})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert "Mocked answer" in data["answer"]
        assert data["route"] == "LOCAL"
        assert data["provider"] == "local"
        assert "elapsed_ms" in data


@pytest.mark.asyncio
async def test_ask_with_model_override_mocked(app_no_auth, monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_execute_plan_python(*, question, policy, timeout, surface, context, model=None):
        captured["model"] = model
        return SimpleNamespace(
            outcome_code="answered",
            response_text="Answer",
            route="LOCAL",
            provider="local",
        )

    import web_adapter.server as server_module

    monkeypatch.setattr(server_module, "execute_plan_python", _fake_execute_plan_python)

    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post(
            "/api/ask",
            json={"question": "Hello?", "model": "local-lucy-llama31"},
        )
        assert resp.status == 200
        assert captured["model"] == "local-lucy-llama31"


@pytest.mark.asyncio
async def test_auth_required(app_with_auth):
    async with TestClient(TestServer(app_with_auth)) as client:
        resp = await client.get("/api/status")
        assert resp.status == 401

        # Valid Basic auth password = token
        client.session._default_auth = BasicAuth("lucy", "secret-test-token")
        resp = await client.get("/api/status")
        assert resp.status == 200


@pytest.mark.asyncio
async def test_auth_with_bearer_header(app_with_auth):
    async with TestClient(TestServer(app_with_auth)) as client:
        resp = await client.get(
            "/api/status", headers={"Authorization": "Bearer secret-test-token"}
        )
        assert resp.status == 200


@pytest.mark.skipif(not _ollama_reachable(), reason="Ollama not reachable")
@pytest.mark.asyncio
async def test_ask_integration_local(app_no_auth):
    """Exercise the real Local Lucy pipeline through the web adapter."""
    async with TestClient(TestServer(app_no_auth)) as client:
        resp = await client.post("/api/ask", json={"question": "What is 2+2?"})
        assert resp.status == 200
        data = await resp.json()
        assert data["ok"] is True
        assert len(data["answer"]) > 5
        assert data["route"] in ("LOCAL", "EVIDENCE", "AUGMENTED", "NEWS")


def test_main_exits_when_disabled(monkeypatch, capsys):
    monkeypatch.setenv("LUCY_WEB_ENABLED", "0")
    assert main() == 1
    captured = capsys.readouterr()
    assert "disabled" in captured.err.lower()


def test_main_exits_without_auth_for_non_loopback(monkeypatch, capsys):
    monkeypatch.setenv("LUCY_WEB_ENABLED", "1")
    monkeypatch.setenv("LUCY_WEB_HOST", "0.0.0.0")
    monkeypatch.delenv("LUCY_WEB_AUTH_TOKEN", raising=False)
    assert main() == 1
    captured = capsys.readouterr()
    assert "auth_token" in captured.err.lower() or "authentication" in captured.err.lower()
