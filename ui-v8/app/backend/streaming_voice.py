"""Streaming voice module - wrapper to single source of truth."""
import sys
from pathlib import Path

# Add paths for imports (needed for streaming_voice which has internal imports)
SNAPSHOT_ROOT = Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"
ROUTER_PY_PATH = SNAPSHOT_ROOT / "tools" / "router_py"

if str(ROUTER_PY_PATH) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_PATH))
if str(ROUTER_PY_PATH.parent) not in sys.path:
    sys.path.insert(0, str(ROUTER_PY_PATH.parent))

# Import the actual implementation
from streaming_voice import StreamingVoicePipeline

__all__ = ['StreamingVoicePipeline']
