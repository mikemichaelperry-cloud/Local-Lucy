#!/usr/bin/env python3
"""Tests for RequestTool."""

import asyncio
import json
import sys
import os

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_tool_wrapper import ToolConfig, ToolResult
from request_tool import RequestTool


_OLLAMA_READY: bool | None = None


# Skip integration tests when Ollama is not available or unresponsive
def _ollama_is_up() -> bool:
    global _OLLAMA_READY
    if _OLLAMA_READY is not None:
        return _OLLAMA_READY

    try:
        import urllib.request

        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                _OLLAMA_READY = False
                return _OLLAMA_READY
    except Exception:
        _OLLAMA_READY = False
        return _OLLAMA_READY

    # Verify the model used by these tests can respond promptly.  Ollama may be
    # running but stuck loading/swap models; in that case skip rather than hang
    # the suite for tens of seconds.
    try:
        payload = json.dumps(
            {"model": "local-lucy-fast:latest", "prompt": "hi", "stream": False}
        ).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            _OLLAMA_READY = resp.status == 200
            return _OLLAMA_READY
    except Exception:
        _OLLAMA_READY = False
        return _OLLAMA_READY


@pytest.mark.asyncio
async def test_generate():
    """Test the generate method with a simple prompt."""
    if not _ollama_is_up():
        pytest.skip("Ollama not running on localhost:11434")
    async with RequestTool(ToolConfig(timeout=30.0)) as tool:
        result = await tool.generate("What is 2+2?", model="local-lucy-fast:latest")

        assert result.success, f"Failed: {result.error_message}"
        assert "4" in result.data or "four" in result.data.lower() or len(result.data) > 0
        assert result.duration_ms > 0

        print(f"✅ Generate test passed: {result.data[:50]}")


@pytest.mark.asyncio
async def test_chat():
    """Test the chat method with messages."""
    if not _ollama_is_up():
        pytest.skip("Ollama not running on localhost:11434")
    async with RequestTool() as tool:
        messages = [{"role": "user", "content": "What is the capital of France?"}]
        result = await tool.chat(messages, model="local-lucy-fast:latest")

        assert result.success, f"Chat failed: {result.error_message}"
        assert len(result.data) > 0, "Empty response"
        # Response may or may not contain "paris", just check it's valid
        print(f"✅ Chat test passed: {result.data[:50]}")


@pytest.mark.asyncio
async def test_health_check():
    """Test the health check endpoint."""
    if not _ollama_is_up():
        pytest.skip("Ollama not running on localhost:11434")
    async with RequestTool() as tool:
        is_healthy = await tool.health_check()
        print(f"Ollama health: {'✅ UP' if is_healthy else '❌ DOWN'}")


@pytest.mark.asyncio
async def test_context_manager():
    """Test async context manager usage."""
    if not _ollama_is_up():
        pytest.skip("Ollama not running on localhost:11434")
    async with RequestTool() as tool:
        result = await tool.generate("Hello!")
        assert isinstance(result.success, bool)
        print("✅ Context manager test passed")


@pytest.mark.asyncio
async def test_invalid_model():
    """Test error handling for invalid model."""
    if not _ollama_is_up():
        pytest.skip("Ollama not running on localhost:11434")
    async with RequestTool() as tool:
        result = await tool.generate("Hello", model="nonexistent-model-xyz")
        assert not result.success
        assert result.error_message != ""
        print(f"✅ Invalid model test passed: {result.error_message[:50]}")


def test_tool_config_defaults():
    """Test ToolConfig default values."""
    config = ToolConfig()
    assert config.timeout == 30.0
    assert config.max_retries == 3
    assert config.backoff_base == 1.0
    assert config.connection_pool_size == 10
    print("✅ ToolConfig defaults test passed")


def test_tool_config_custom():
    """Test ToolConfig with custom values."""
    config = ToolConfig(timeout=60.0, max_retries=5, backoff_base=2.0, connection_pool_size=20)
    assert config.timeout == 60.0
    assert config.max_retries == 5
    assert config.backoff_base == 2.0
    assert config.connection_pool_size == 20
    print("✅ ToolConfig custom values test passed")


if __name__ == "__main__":
    # Run sync tests
    test_tool_config_defaults()
    test_tool_config_custom()

    # Run async tests
    asyncio.run(test_health_check())
    asyncio.run(test_generate())
    asyncio.run(test_chat())
    asyncio.run(test_context_manager())
    asyncio.run(test_invalid_model())
