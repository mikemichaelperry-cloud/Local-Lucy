"""Live smoke test: Gemma and Llama must never be loaded simultaneously.

This test loads one model, verifies it, unloads it, then loads the other.
It requires a running Ollama instance with both Local Lucy models installed.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

import pytest

pytestmark = [pytest.mark.slow, pytest.mark.live]

DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")


def _api_ps() -> list[str]:
    try:
        with urllib.request.urlopen(f"{DEFAULT_OLLAMA_URL}/api/ps", timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", m.get("model", "")) for m in data.get("models", [])]
    except Exception as exc:
        pytest.skip(f"Ollama /api/ps unreachable: {exc}")


def _is_loaded(name: str) -> bool:
    return any(name in loaded for loaded in _api_ps())


def _load_model(name: str) -> None:
    """Send a minimal generate request to force Ollama to load the model."""
    body = json.dumps(
        {
            "model": name,
            "prompt": "",
            "stream": False,
            "keep_alive": "10m",
            "options": {"num_predict": 0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            resp.read()
    except Exception as exc:
        pytest.skip(f"Could not load {name}: {exc}")


def _unload_model(name: str) -> None:
    """Ask Ollama to unload the model immediately."""
    from router_py.ollama_cleanup import unload_model

    # Use env override so the helper talks to the same Ollama instance.
    old = os.environ.get("LUCY_OLLAMA_API_URL")
    os.environ["LUCY_OLLAMA_API_URL"] = DEFAULT_OLLAMA_URL
    try:
        unload_model(name)
    finally:
        if old is None:
            os.environ.pop("LUCY_OLLAMA_API_URL", None)
        else:
            os.environ["LUCY_OLLAMA_API_URL"] = old


def _wait_for_unload(name: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not _is_loaded(name):
            return True
        time.sleep(0.5)
    return False


def _lucy_models_loaded() -> list[str]:
    from router_py.ollama_cleanup import is_lucy_model

    return [m for m in _api_ps() if is_lucy_model(m)]


def test_sequential_model_load_never_loads_both():
    """Gemma and Llama must never both be resident in Ollama at the same time."""
    # Start clean.
    for m in _lucy_models_loaded():
        _unload_model(m)
    time.sleep(1.0)

    # Load Gemma.
    _load_model(GEMMA_MODEL)
    assert _is_loaded(GEMMA_MODEL), f"{GEMMA_MODEL} should be loaded after warmup"

    # Fully unload Gemma before loading Llama.
    _unload_model(GEMMA_MODEL)
    assert _wait_for_unload(GEMMA_MODEL), f"{GEMMA_MODEL} should unload before switching"

    # Load Llama.
    _load_model(LLAMA_MODEL)
    assert _is_loaded(LLAMA_MODEL), f"{LLAMA_MODEL} should be loaded after warmup"
    assert not _is_loaded(GEMMA_MODEL), (
        f"{GEMMA_MODEL} must NOT still be loaded when {LLAMA_MODEL} is loaded"
    )

    # Clean up.
    _unload_model(LLAMA_MODEL)
    _wait_for_unload(LLAMA_MODEL)


def test_unload_all_lucy_models_clears_vram():
    """shutdown_cleanup must remove all Local Lucy models from Ollama."""
    from router_py.ollama_cleanup import shutdown_cleanup

    # Ensure at least one model is loaded.
    _load_model(LLAMA_MODEL)
    assert _is_loaded(LLAMA_MODEL)

    shutdown_cleanup()

    # Give Ollama a moment to actually release the model.
    assert _wait_for_unload(LLAMA_MODEL), (
        f"{LLAMA_MODEL} should be unloaded by shutdown_cleanup"
    )
    assert not _lucy_models_loaded(), f"No Local Lucy models should remain loaded: {_api_ps()}"
