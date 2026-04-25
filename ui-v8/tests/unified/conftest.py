"""
Pytest configuration for unified architecture tests.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set test environment
os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(
    Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"
)
os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(
    Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"
)
os.environ["LUCY_UI_ROOT"] = str(Path(__file__).parent.parent.parent)
os.environ["LUCY_ROUTER_PY"] = "1"
os.environ["LUCY_EXEC_PY"] = "1"
os.environ["LUCY_USE_CONSOLIDATED_BRIDGE"] = "1"


def pytest_configure(config):
    """Configure pytest for unified tests."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "e2e: marks tests as end-to-end tests"
    )
