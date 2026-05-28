"""Execution engine module - wrapper to single source of truth.

⚠️  WARNING: This file is a RE-EXPORT WRAPPER ONLY.
Do NOT add logic here. The real implementation lives in:
    tools/router_py/execution_engine.py

If you need to change execution, evidence fetching, or provider
calling behaviour, edit tools/router_py/execution_engine.py and
let this wrapper pick it up automatically via backend/__init__.py.
"""
from backend import (
    ExecutionEngine,
    ExecutionResult,
    _load_session_memory_context,
    DEFAULT_CHAT_MEMORY_FILE,
)
HAS_DIRECT_PROVIDERS = True
__all__ = ['ExecutionEngine', 'ExecutionResult', '_load_session_memory_context', 'DEFAULT_CHAT_MEMORY_FILE', 'HAS_DIRECT_PROVIDERS']
