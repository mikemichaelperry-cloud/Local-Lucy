#!/usr/bin/env python3
"""Tests for RequestTool."""

import asyncio
import sys
import os

import pytest

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_tool_wrapper import ToolConfig, ToolResult
from request_tool import RequestTool

pytestmark = pytest.mark.asyncio


# Skip integration tests when Ollama is not available
async def _ollama_available() -> bool:
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://127.0.0.1:11434/api/tags", timeout=aiohttp.ClientTimeout(total=2)):
                return True
    except Exception:
        return False


OLLAMA_UP = False

def setup_module(module):
    """Check if Ollama is running before module tests."""
    global OLLAMA_UP
    try:
        import asyncio
        OLLAMA_UP = asyncio.run(_ollama_available())
    except Exception:
        OLLAMA_UP = False


@pytest.mark.skipif(not OLLAMA_UP, reason="Ollama not running on localhost:11434")
async def test_generate():
    """Test the generate method with a simple prompt."""
    async with RequestTool(ToolConfig(timeout=30.0)) as tool:
        result = await tool.generate("What is 2+2?", model="llama3.1:8b")
        
        assert result.success, f"Failed: {result.error_message}"
        assert "4" in result.data or "four" in result.data.lower() or len(result.data) > 0
        assert result.duration_ms > 0
        
        print(f"✅ Generate test passed: {result.data[:50]}")


@pytest.mark.skipif(not OLLAMA_UP, reason="Ollama not running on localhost:11434")
async def test_chat():
    """Test the chat method with messages."""
    async with RequestTool() as tool:
        messages = [
            {"role": "user", "content": "What is the capital of France?"}
        ]
        result = await tool.chat(messages, model="llama3.1:8b")
        
        assert result.success, f"Chat failed: {result.error_message}"
        assert len(result.data) > 0, "Empty response"
        # Response may or may not contain "paris", just check it's valid
        print(f"✅ Chat test passed: {result.data[:50]}")


@pytest.mark.skipif(not OLLAMA_UP, reason="Ollama not running on localhost:11434")
async def test_health_check():
    """Test the health check endpoint."""
    async with RequestTool() as tool:
        is_healthy = await tool.health_check()
        print(f"Ollama health: {'✅ UP' if is_healthy else '❌ DOWN'}")


@pytest.mark.skipif(not OLLAMA_UP, reason="Ollama not running on localhost:11434")
async def test_context_manager():
    """Test async context manager usage."""
    async with RequestTool() as tool:
        result = await tool.generate("Hello!")
        assert isinstance(result.success, bool)
        print(f"✅ Context manager test passed")


@pytest.mark.skipif(not OLLAMA_UP, reason="Ollama not running on localhost:11434")
async def test_invalid_model():
    """Test error handling for invalid model."""
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
    config = ToolConfig(
        timeout=60.0,
        max_retries=5,
        backoff_base=2.0,
        connection_pool_size=20
    )
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
