"""Re-export for backward compatibility — implementation lives in router_py."""

from router_py.execution_engine import ExecutionEngine, ExecutionResult

__all__ = ["ExecutionEngine", "ExecutionResult"]
