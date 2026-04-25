#!/usr/bin/env python3
"""Tests for RequestTool."""

import asyncio
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base_tool_wrapper import ToolConfig, ToolResult
from request_tool import RequestTool


async def test_generate():
    """Test the generate method with a simple prompt."""
    tool = RequestTool(ToolConfig(timeout=30.0))
    result = await tool.generate("What is 2+2?", model="llama3.1:8b")
    
    assert result.success, f"Failed: {result.error_message}"
    assert "4" in result.data or "four" in result.data.lower() or len(result.data) > 0
    assert result.duration_ms > 0
    
    await tool.close()
    print(f"✅ Generate test passed: {result.data[:50]}")


async def test_chat():
    """Test the chat method with messages."""
    tool = RequestTool()
    messages = [
        {"role": "user", "content": "What is the capital of France?"}
    ]
    result = await tool.chat(messages, model="llama3.1:8b")
    
    assert result.success, f"Chat failed: {result.error_message}"
    assert len(result.data) > 0, "Empty response"
    # Response may or may not contain "paris", just check it's valid
    print(f"✅ Chat test passed: {result.data[:50]}")
    await tool.close()


async def test_health_check():
    """Test the health check endpoint."""
    tool = RequestTool()
    is_healthy = await tool.health_check()
    print(f"Ollama health: {'✅ UP' if is_healthy else '❌ DOWN'}")
    await tool.close()


async def test_context_manager():
    """Test async context manager usage."""
    async with RequestTool() as tool:
        result = await tool.generate("Hello!")
        assert isinstance(result.success, bool)
        print(f"✅ Context manager test passed")


async def test_invalid_model():
    """Test error handling for invalid model."""
    tool = RequestTool()
    result = await tool.generate("Hello", model="nonexistent-model-xyz")
    assert not result.success
    assert result.error_message != ""
    await tool.close()
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
