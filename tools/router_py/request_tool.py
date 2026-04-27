#!/usr/bin/env python3
"""Ollama API tool wrapper."""

import aiohttp
import json
import time
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    from .base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult
except ImportError:
    from base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult


class RequestTool(BaseToolWrapper):
    """Wrapper for Ollama API requests.
    
    Replaces: local_answer.sh, local_runtime.sh shell calls
    Features:
    - Async/await throughout
    - Connection pooling
    - Streaming support
    - Proper timeout handling
    """
    
    def __init__(
        self,
        config: Optional[ToolConfig] = None,
        base_url: str = "http://127.0.0.1:11434",
        default_model: str = "llama3.2"
    ):
        super().__init__(config)
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self._session: Optional[aiohttp.ClientSession] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with connection pooling."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=self.config.connection_pool_size,
                ttl_dns_cache=300,
                use_dns_cache=True,
            )
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
            )
        return self._session
    
    async def execute(self, **kwargs) -> ToolResult:
        """Execute tool - delegates to generate() for compatibility with BaseToolWrapper."""
        prompt = kwargs.get("prompt", "")
        model = kwargs.get("model", None)
        stream = kwargs.get("stream", False)
        options = {k: v for k, v in kwargs.items() if k not in ("prompt", "model", "stream")}
        return await self.generate(prompt, model, stream, **options)
    
    async def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        stream: bool = False,
        **options: Any
    ) -> ToolResult:
        """Generate text using Ollama generate endpoint.
        
        Args:
            prompt: The prompt text
            model: Model name (default: self.default_model)
            stream: Whether to stream response
            **options: Additional options (temperature, etc.)
        
        Returns:
            ToolResult with generated text
        """
        model = model or self.default_model
        url = f"{self.base_url}/api/generate"
        
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            **options
        }
        
        start_time = time.time()
        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                
                if stream:
                    # Handle streaming response
                    chunks: List[str] = []
                    async for line in response.content:
                        if line:
                            data = json.loads(line)
                            if "response" in data:
                                chunks.append(data["response"])
                    text = "".join(chunks)
                else:
                    # Handle single response
                    data = await response.json()
                    text = data.get("response", "")
                
                duration_ms = int((time.time() - start_time) * 1000)
                
                return ToolResult(
                    success=True,
                    data=text,
                    duration_ms=duration_ms
                )
                
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            self.logger.error(f"Ollama generate failed: {e}")
            return ToolResult(
                success=False,
                data=None,
                error_message=str(e),
                duration_ms=duration_ms
            )
    
    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        **options: Any
    ) -> ToolResult:
        """Chat using Ollama chat endpoint.
        
        Args:
            messages: List of {role: str, content: str}
            model: Model name
            **options: Additional options
        
        Returns:
            ToolResult with assistant's response
        """
        model = model or self.default_model
        url = f"{self.base_url}/api/chat"
        
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            **options
        }
        
        start_time = time.time()
        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                text = data.get("message", {}).get("content", "")
                duration_ms = int((time.time() - start_time) * 1000)
                
                return ToolResult(
                    success=True,
                    data=text,
                    duration_ms=duration_ms
                )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=False,
                data=None,
                error_message=str(e),
                duration_ms=duration_ms
            )
    
    async def health_check(self) -> bool:
        """Check if Ollama is available."""
        try:
            session = await self._get_session()
            async with session.get(f"{self.base_url}/api/tags") as response:
                return response.status == 200
        except Exception:
            return False
    
    async def close(self) -> None:
        """Close session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self) -> "RequestTool":
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Async context manager exit."""
        await self.close()
