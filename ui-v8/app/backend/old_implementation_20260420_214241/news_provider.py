"""News provider module - wrapper to single source of truth."""
import sys
from pathlib import Path

SNAPSHOT_ROOT = Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"
ROUTER_PY_PATH = SNAPSHOT_ROOT / "tools" / "router_py"

if str(ROUTER_PY_PATH) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_PATH))

from news_provider import NewsProvider, NewsResult
__all__ = ['NewsProvider', 'NewsResult']
