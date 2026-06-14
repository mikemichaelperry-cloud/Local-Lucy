"""Re-export for backward compatibility — implementation lives in router_py."""
from router_py.main import execute_plan_python, ensure_control_env, RouterOutcome, DEFAULT_TIMEOUT

__all__ = ["execute_plan_python", "ensure_control_env", "RouterOutcome", "DEFAULT_TIMEOUT"]
