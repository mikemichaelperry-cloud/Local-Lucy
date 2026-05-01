"""Execution engine module - wrapper to single source of truth."""
from backend import (
    ExecutionEngine,
    ExecutionResult,
    _load_session_memory_context,
    DEFAULT_CHAT_MEMORY_FILE,
)
HAS_DIRECT_PROVIDERS = True
__all__ = ['ExecutionEngine', 'ExecutionResult', '_load_session_memory_context', 'DEFAULT_CHAT_MEMORY_FILE', 'HAS_DIRECT_PROVIDERS']
