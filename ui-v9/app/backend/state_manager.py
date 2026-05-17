"""State manager module - wrapper to single source of truth."""
import os
import sys
from pathlib import Path

# Resolve project root from env or derive from file location
AUTHORITY_ROOT = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "").strip()
if AUTHORITY_ROOT:
    PROJECT_ROOT = Path(AUTHORITY_ROOT).expanduser()
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
ROUTER_PY_PATH = PROJECT_ROOT / "tools" / "router_py"

if str(ROUTER_PY_PATH) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_PATH))

from state_manager import get_state_manager, StateManager
__all__ = ['get_state_manager', 'StateManager']
