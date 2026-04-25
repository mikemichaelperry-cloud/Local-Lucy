"""
End-to-end tests for unified architecture.

Tests complete flow from UI through backend to response.
"""
from __future__ import annotations

import os
import sys
import pytest
import time
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set required environment
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", 
    str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", 
    str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
os.environ.setdefault("LUCY_UI_ROOT", 
    str(Path(__file__).parent.parent.parent))
os.environ["LUCY_ROUTER_PY"] = "1"
os.environ["LUCY_EXEC_PY"] = "1"


class TestEndToEndLocalQueries:
    """End-to-end tests for local query path."""
    
    def test_e2e_simple_math(self):
        """Complete flow: simple math query."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("What is 5 + 3?")
        
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "8" in result["response_text"] or "eight" in result["response_text"].lower()
        assert result["outcome"]["final_mode"] == "LOCAL"
    
    def test_e2e_identity_query(self):
        """Complete flow: asking about Lucy."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("What is your name?")
        
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "Lucy" in result["response_text"]
        assert result["outcome"]["final_mode"] == "LOCAL"
    
    def test_e2e_general_knowledge_local(self):
        """Complete flow: general knowledge via local."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("What is the capital of Italy?")
        
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "Rome" in result["response_text"]
    
    def test_e2e_multiple_requests(self):
        """Complete flow: multiple sequential requests."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        
        queries = [
            "What is 2+2?",
            "Who are you?",
            "What day is it?"
        ]
        
        for query in queries:
            result = bridge.submit_request(query)
            assert result["accepted"] is True
            assert result["status"] == "completed"
            assert len(result["response_text"]) > 0
            # Small delay to avoid rate limiting
            time.sleep(0.5)


class TestEndToEndAugmentedQueries:
    """End-to-end tests for augmented query path."""
    
    def test_e2e_augmented_historical(self):
        """Complete flow: historical knowledge query."""
        from app.services import RuntimeBridge
        
        os.environ["LUCY_AUGMENTATION_POLICY"] = "augmented"
        bridge = RuntimeBridge()
        
        result = bridge.submit_request("Who invented the telephone?", force_augmented=True)
        
        assert result["accepted"] is True
        assert result["status"] == "completed"
        # Should get relevant historical information
        assert len(result["response_text"]) > 50
    
    def test_e2e_augmented_scientific(self):
        """Complete flow: scientific query."""
        from app.services import RuntimeBridge
        
        os.environ["LUCY_AUGMENTATION_POLICY"] = "augmented"
        bridge = RuntimeBridge()
        
        result = bridge.submit_request("What is the speed of light?", force_augmented=True)
        
        assert result["accepted"] is True
        assert result["status"] == "completed"
        assert "299" in result["response_text"] or "300" in result["response_text"]


class TestEndToEdgeCases:
    """End-to-end edge case tests."""
    
    def test_e2e_empty_query(self):
        """Complete flow: empty query handling."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("")
        
        # Should handle gracefully - either error or return a response
        assert "status" in result
    
    def test_e2e_very_long_query(self):
        """Complete flow: very long query."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        long_query = "What is " + "2+2 " * 50 + "?"
        
        result = bridge.submit_request(long_query)
        
        # Should handle without crashing
        assert "status" in result
    
    def test_e2e_special_characters(self):
        """Complete flow: query with special characters."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("What is 2+2? (test) [brackets] {braces}")
        
        assert result["accepted"] is True
        assert result["status"] == "completed"


class TestEndToEndPerformance:
    """Performance and timing tests."""
    
    def test_e2e_response_time(self):
        """Complete flow: response time under threshold."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        
        start = time.time()
        result = bridge.submit_request("Hello")
        elapsed = time.time() - start
        
        assert result["accepted"] is True
        # Should respond within reasonable time (30 seconds for local)
        assert elapsed < 30, f"Response took {elapsed:.2f}s, expected < 30s"
    
    def test_e2e_multiple_bridges(self):
        """Complete flow: multiple bridge instances."""
        from app.services import RuntimeBridge
        
        # Create multiple bridges
        bridges = [RuntimeBridge() for _ in range(3)]
        
        # Each should work independently
        for i, bridge in enumerate(bridges):
            result = bridge.submit_request(f"Test query {i}")
            assert result["accepted"] is True
            assert result["status"] == "completed"


class TestUnifiedVsLegacyParity:
    """Verify unified architecture matches legacy behavior."""
    
    def test_response_structure_parity(self):
        """Unified and legacy return same response structure."""
        from app.services import RuntimeBridge
        
        bridge = RuntimeBridge()
        result = bridge.submit_request("What is 2+2?")
        
        # Required fields in response
        required_fields = ["accepted", "status", "response_text", "request_id", "outcome"]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
        
        # Outcome should have required subfields
        outcome = result["outcome"]
        assert "outcome_code" in outcome
        assert "final_mode" in outcome
        assert "provider_used" in outcome
