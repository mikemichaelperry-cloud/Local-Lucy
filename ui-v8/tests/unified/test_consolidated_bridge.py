"""
Tests for the ConsolidatedRuntimeBridge.

Verifies API compatibility with legacy bridge and correct delegation to Python backend.
"""
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set required environment before imports
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", 
    str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", 
    str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
os.environ.setdefault("LUCY_UI_ROOT", 
    str(Path(__file__).parent.parent.parent))

from app.services.runtime_bridge_consolidated import (
    ConsolidatedRuntimeBridge,
    ActionCapability,
)
from app.services.runtime_bridge import CommandResult


class TestConsolidatedRuntimeBridge:
    """Test suite for ConsolidatedRuntimeBridge."""
    
    def test_bridge_initialization(self):
        """Bridge initializes without errors."""
        bridge = ConsolidatedRuntimeBridge()
        assert bridge.available is True
        
    def test_capabilities_exist(self):
        """Bridge has required capabilities."""
        bridge = ConsolidatedRuntimeBridge()
        
        # Required capability keys
        required = ["mode_selection", "memory_toggle", "evidence_toggle"]
        for key in required:
            assert key in bridge.capabilities
            assert isinstance(bridge.capabilities[key], ActionCapability)
    
    def test_capability_properties(self):
        """Capability properties are correctly typed."""
        bridge = ConsolidatedRuntimeBridge()
        
        cap = bridge.capabilities["mode_selection"]
        assert cap.name == "mode_selection"
        assert cap.available is True
        assert isinstance(cap.allowed_values, tuple)
        assert "local" in cap.allowed_values
        assert isinstance(cap.reason, str)
    
    def test_request_capability(self):
        """Request capability is available."""
        bridge = ConsolidatedRuntimeBridge()
        
        assert bridge.request_capability.available is True
        assert bridge.request_available() is True
    
    def test_profile_lifecycle_voice_capabilities(self):
        """Profile/lifecycle/voice capabilities exist (may be disabled)."""
        bridge = ConsolidatedRuntimeBridge()
        
        # These exist but may not be implemented yet
        assert hasattr(bridge, 'profile_capability')
        assert hasattr(bridge, 'lifecycle_capability')
        assert hasattr(bridge, 'voice_capability')
    
    def test_capability_notes(self):
        """Capability notes returns dictionary."""
        bridge = ConsolidatedRuntimeBridge()
        
        notes = bridge.capability_notes()
        assert isinstance(notes, dict)
        assert "mode_selection" in notes
    
    def test_submit_request_local(self):
        """Submit request works for local queries."""
        bridge = ConsolidatedRuntimeBridge()
        
        result = bridge.submit_request("What is 2+2?", force_augmented=False)
        
        assert isinstance(result, dict)
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "response_text" in result
        assert len(result["response_text"]) > 0
        assert "outcome" in result
    
    def test_submit_request_augmented(self):
        """Submit request works for augmented queries."""
        bridge = ConsolidatedRuntimeBridge()
        
        # Set policy for augmented
        os.environ["LUCY_AUGMENTATION_POLICY"] = "augmented"
        
        result = bridge.submit_request("Who invented the telephone?", force_augmented=True)
        
        assert isinstance(result, dict)
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "response_text" in result
    
    def test_submit_request_error_handling(self):
        """Submit request handles errors gracefully."""
        bridge = ConsolidatedRuntimeBridge()
        
        # Empty query should still work (backend handles it)
        result = bridge.submit_request("")
        
        assert isinstance(result, dict)
        # Should either succeed or fail gracefully
        assert "status" in result
        assert "error" in result or result["status"] == "completed"
    
    def test_run_action_submit_request(self):
        """run_action with submit_request returns CommandResult."""
        bridge = ConsolidatedRuntimeBridge()
        
        result = bridge.run_action("submit_request", "What is Python?")
        
        assert isinstance(result, CommandResult)
        assert result.action == "submit_request"
        assert result.status in ("success", "failed")
        assert isinstance(result.stdout, str)
    
    def test_run_action_unimplemented(self):
        """run_action for unimplemented actions returns not_implemented."""
        bridge = ConsolidatedRuntimeBridge()
        
        result = bridge.run_action("unknown_action", "value")
        
        assert isinstance(result, CommandResult)
        assert result.status == "not_implemented"
        assert result.returncode == 1
    
    def test_timeout_configuration(self):
        """Bridge has timeout configuration."""
        bridge = ConsolidatedRuntimeBridge()
        
        assert hasattr(bridge, 'request_timeout_seconds')
        assert bridge.request_timeout_seconds > 0
        assert hasattr(bridge, 'control_timeout_seconds')
        assert hasattr(bridge, 'voice_stop_timeout_seconds')


class TestActionCapability:
    """Test suite for ActionCapability dataclass."""
    
    def test_capability_creation(self):
        """Can create capability with all fields."""
        cap = ActionCapability(
            name="test_cap",
            available=True,
            allowed_values=("a", "b", "c"),
            reason="Test reason"
        )
        
        assert cap.name == "test_cap"
        assert cap.available is True
        assert cap.allowed_values == ("a", "b", "c")
        assert cap.reason == "Test reason"
    
    def test_capability_immutability(self):
        """Capabilities are frozen/immutable."""
        cap = ActionCapability(
            name="test",
            available=True,
            allowed_values=(),
            reason=""
        )
        
        with pytest.raises(Exception):
            cap.name = "modified"
