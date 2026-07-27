#!/usr/bin/env python3
"""Regression tests for synchronous Ollama model unload on HMI model switch."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_UI_ROOT = Path(__file__).resolve().parents[1]


def test_model_selection_unloads_other_models_before_returning():
    """Switching models must synchronously evict the previously loaded model."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()

    # Capture every Ollama HTTP request made during the action.
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload_bytes: bytes) -> None:
            self._payload = payload_bytes

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        body = None
        if hasattr(request, "data") and request.data:
            body = json.loads(request.data.decode("utf-8"))
        calls.append({"url": url, "body": body})

        # /api/ps returns llama31 loaded, then empty after the unload.
        if url.endswith("/api/ps"):
            if any(
                c["url"].endswith("/api/generate")
                and c.get("body", {}).get("model") == "local-lucy-llama31:latest"
                for c in calls
            ):
                return FakeResponse(b'{"models": []}')
            return FakeResponse(b'{"models": [{"name": "local-lucy-llama31:latest"}]}')

        # /api/generate unload request
        if url.endswith("/api/generate"):
            return FakeResponse(b'{"done": true}')

        raise RuntimeError(f"Unexpected URL: {url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "current_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "lucy-v11",
                    "mode": "auto",
                    "conversation": "off",
                    "memory": "off",
                    "evidence": "off",
                    "voice": "off",
                    "augmentation_policy": "disabled",
                    "augmented_provider": "wikipedia",
                    "model": "local-lucy-llama31",
                    "approval_required": False,
                    "status": "ready",
                    "last_updated": "2026-01-01T00:00:00Z",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"LUCY_RUNTIME_NAMESPACE_ROOT": tmpdir}):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = bridge.run_action("model_selection", "local-lucy-gemma4")

    assert result.status == "ok", result.stderr

    # The unload request for the old model must have been issued before the
    # action returned.
    generate_calls = [c for c in calls if c["url"].endswith("/api/generate")]
    unload_calls = [
        c
        for c in generate_calls
        if c.get("body", {}).get("keep_alive") == 0
        and c.get("body", {}).get("model") == "local-lucy-llama31:latest"
    ]
    assert len(unload_calls) >= 1, f"expected unload call for llama31, got {calls}"

    # State update should happen after unload because the action is synchronous.
    # We verify by checking that /api/ps was polled after the unload.
    ps_calls = [c for c in calls if c["url"].endswith("/api/ps")]
    assert len(ps_calls) >= 2, f"expected initial ps query and verification poll, got {calls}"


def test_is_same_ollama_model_tolerates_latest_tag():
    """Backend names and :latest-tagged Ollama names must compare as identical."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.runtime_bridge import RuntimeBridge

    assert RuntimeBridge._is_same_ollama_model("local-lucy-gemma4", "local-lucy-gemma4:latest")
    assert RuntimeBridge._is_same_ollama_model("local-lucy-llama31", "local-lucy-llama31:latest")
    assert not RuntimeBridge._is_same_ollama_model("local-lucy-gemma4", "local-lucy-llama31")


def test_model_selection_auto_unloads_previous_manual_model():
    """Switching HMI model selector to Auto must evict the previously selected model."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload_bytes: bytes) -> None:
            self._payload = payload_bytes

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        body = None
        if hasattr(request, "data") and request.data:
            body = json.loads(request.data.decode("utf-8"))
        calls.append({"url": url, "body": body})

        if url.endswith("/api/ps"):
            # Simulate llama31 and gemma4 resident; after unload calls, return empty.
            generate_models = {
                c.get("body", {}).get("model")
                for c in calls
                if c["url"].endswith("/api/generate") and c.get("body", {}).get("keep_alive") == 0
            }
            remaining = [
                {"name": "local-lucy-llama31:latest"},
                {"name": "local-lucy-gemma4:latest"},
            ]
            remaining = [
                m for m in remaining
                if m["name"] not in generate_models
            ]
            return FakeResponse(json.dumps({"models": remaining}).encode("utf-8"))

        if url.endswith("/api/generate"):
            return FakeResponse(b'{"done": true}')

        raise RuntimeError(f"Unexpected URL: {url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        state_file = state_dir / "current_state.json"
        state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "lucy-v11",
                    "mode": "auto",
                    "conversation": "off",
                    "memory": "off",
                    "evidence": "off",
                    "voice": "off",
                    "augmentation_policy": "disabled",
                    "augmented_provider": "wikipedia",
                    "model": "local-lucy-llama31",
                    "approval_required": False,
                    "status": "ready",
                    "last_updated": "2026-01-01T00:00:00Z",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        with patch.dict(os.environ, {"LUCY_RUNTIME_NAMESPACE_ROOT": tmpdir}):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                result = bridge.run_action("model_selection", "auto")

    assert result.status == "ok", result.stderr

    generate_calls = [c for c in calls if c["url"].endswith("/api/generate")]
    unload_calls = [c for c in generate_calls if c.get("body", {}).get("keep_alive") == 0]
    unloaded_models = {c["body"]["model"] for c in unload_calls}
    assert "local-lucy-llama31:latest" in unloaded_models, f"expected llama31 unload, got {calls}"
    assert "local-lucy-gemma4:latest" in unloaded_models, f"expected gemma4 unload, got {calls}"


def test_shutdown_unloads_all_lucy_models():
    """HMI shutdown must unload every Local Lucy model resident in Ollama."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "0")
    sys.path.insert(0, str(REPO_UI_ROOT))

    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, payload_bytes: bytes) -> None:
            self._payload = payload_bytes

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self._payload

    def fake_urlopen(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        body = None
        if hasattr(request, "data") and request.data:
            body = json.loads(request.data.decode("utf-8"))
        calls.append({"url": url, "body": body})

        if url.endswith("/api/ps"):
            generate_models = {
                c.get("body", {}).get("model")
                for c in calls
                if c["url"].endswith("/api/generate") and c.get("body", {}).get("keep_alive") == 0
            }
            remaining = [
                {"name": "local-lucy-llama31:latest"},
                {"name": "local-lucy-gemma4:latest"},
                {"name": "llama3.1:latest"},
            ]
            remaining = [m for m in remaining if m["name"] not in generate_models]
            return FakeResponse(json.dumps({"models": remaining}).encode("utf-8"))

        if url.endswith("/api/generate"):
            return FakeResponse(b'{"done": true}')

        raise RuntimeError(f"Unexpected URL: {url}")

    with patch("urllib.request.urlopen", side_effect=fake_urlopen):
        unloaded = bridge.shutdown()

    unloaded_names = set(unloaded)
    assert "local-lucy-llama31:latest" in unloaded_names, f"expected llama31, got {unloaded}"
    assert "local-lucy-gemma4:latest" in unloaded_names, f"expected gemma4, got {unloaded}"
    assert "llama3.1:latest" not in unloaded_names, f"non-Lucy model must not be unloaded: {unloaded}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
