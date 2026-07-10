"""
Tests for the RuntimeBridge (canonical bridge).

Verifies API compatibility and correct delegation to Python backend.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set required environment before imports
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v10"))
os.environ.setdefault(
    "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)
os.environ.setdefault("LUCY_UI_ROOT", str(Path(__file__).parent.parent.parent))

from app.services import (
    CommandResult,
    RuntimeActionTask,
    RuntimeBridge,
)


class TestRuntimeBridge:
    """Test suite for RuntimeBridge."""

    def test_bridge_initialization(self):
        """Bridge initializes without errors."""
        bridge = RuntimeBridge()
        assert bridge.request_available() is True

    def test_capabilities_exist(self):
        """Bridge has required capabilities."""
        bridge = RuntimeBridge()

        # Required capability keys
        required = ["mode_selection", "memory_toggle", "evidence_toggle"]
        for key in required:
            assert key in bridge.capabilities

    def test_capability_properties(self):
        """Capability properties are correctly typed."""
        bridge = RuntimeBridge()
        cap = bridge.capabilities["mode_selection"]
        assert isinstance(cap.name, str)
        assert isinstance(cap.available, bool)
        assert isinstance(cap.allowed_values, tuple)
        assert isinstance(cap.reason, str)

    def test_request_available(self):
        """Request capability is available."""
        bridge = RuntimeBridge()
        assert bridge.request_available() is True

    def test_profile_available(self):
        """Profile capability is available."""
        bridge = RuntimeBridge()
        assert bridge.profile_available() is True

    def test_lifecycle_available(self):
        """Lifecycle capability is available."""
        bridge = RuntimeBridge()
        assert bridge.lifecycle_available() is True

    def test_capability_notes(self):
        """Capability notes are returned as dict."""
        bridge = RuntimeBridge()
        notes = bridge.capability_notes()
        assert isinstance(notes, dict)
        assert "mode_selection" in notes

    def test_submit_request_rejects_empty(self):
        """Empty request is rejected."""
        bridge = RuntimeBridge()
        result = bridge.run_action("submit_request", "")
        assert result.status == "unavailable"

    def test_command_result_structure(self):
        """CommandResult has expected fields."""
        result = CommandResult(
            action="test",
            requested_value="value",
            status="ok",
            returncode=0,
            stdout="out",
            stderr="err",
            timed_out=False,
            payload=None,
        )
        assert result.action == "test"
        assert result.requested_value == "value"
        assert result.status == "ok"
        assert result.returncode == 0
        assert result.stdout == "out"
        assert result.stderr == "err"
        assert result.timed_out is False
        assert result.payload is None

    def test_runtime_action_task_instantiation(self):
        """RuntimeActionTask can be instantiated."""
        bridge = RuntimeBridge()
        task = RuntimeActionTask(bridge, "submit_request", "hello")
        assert task._bridge is bridge
        assert task._action == "submit_request"
        assert task._requested_value == "hello"
