#!/usr/bin/env python3
"""Base class for tool wrappers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional
import asyncio
import logging
from tenacity import retry, stop_after_attempt, wait_exponential


@dataclass
class ToolConfig:
    """Configuration for tool wrappers."""
    timeout: float = 30.0
    max_retries: int = 3
    backoff_base: float = 1.0
    connection_pool_size: int = 10


@dataclass
class ToolResult:
    """Result from a tool execution."""
    success: bool
    data: Any
    error_message: str = ""
    duration_ms: int = 0


class BaseToolWrapper(ABC):
    """Abstract base class for all tool wrappers.
    
    Provides common functionality like:
    - Configuration management
    - Retry logic with exponential backoff
    - Health checking
    - Logging
    """
    
    def __init__(self, config: Optional[ToolConfig] = None):
        self.config = config or ToolConfig()
        self.logger = logging.getLogger(self.__class__.__name__)
    
    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Must be implemented by subclasses."""
        pass
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True
    )
    async def execute_with_retry(self, **kwargs) -> ToolResult:
        """Execute with retry logic."""
        return await self.execute(**kwargs)
    
    async def health_check(self) -> bool:
        """Check if tool is available. Override in subclass."""
        return True
