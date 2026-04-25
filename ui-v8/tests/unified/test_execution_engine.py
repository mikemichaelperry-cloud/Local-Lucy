"""
Tests for the Python ExecutionEngine.

Verifies pure Python execution without shell dependency.
"""
from __future__ import annotations

import os
import sys
import pytest
from pathlib import Path

# Ensure app is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Set required environment
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", 
    str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", 
    str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))

from backend.execution_engine import ExecutionEngine, ExecutionResult


class TestExecutionEngineInitialization:
    """Test ExecutionEngine initialization and configuration."""
    
    def test_engine_initialization(self):
        """Engine initializes with default config."""
        engine = ExecutionEngine()
        
        assert engine is not None
        assert engine.timeout > 0
        assert engine._state_dir.exists()
    
    def test_engine_with_custom_config(self):
        """Engine accepts custom configuration."""
        engine = ExecutionEngine(config={
            "timeout": 60,
            "policy_confidence_threshold": 0.75
        })
        
        assert engine.timeout == 60
        assert engine.policy_confidence_threshold == 0.75
    
    def test_namespace_isolation(self):
        """Engine creates unique namespace per instance."""
        engine1 = ExecutionEngine()
        engine2 = ExecutionEngine()
        
        # Each engine should have unique namespace
        assert engine1._execution_namespace != engine2._execution_namespace
    
    def test_state_directory_creation(self):
        """Engine creates state directory if needed."""
        engine = ExecutionEngine()
        
        assert engine._state_dir.exists()
        assert engine._state_dir.is_dir()


class TestExecutionResult:
    """Test ExecutionResult dataclass."""
    
    def test_result_creation(self):
        """Can create ExecutionResult with required fields."""
        result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="Test response",
            execution_time_ms=100
        )
        
        assert result.status == "completed"
        assert result.response_text == "Test response"
        assert result.execution_time_ms == 100
    
    def test_result_to_dict(self):
        """Result can be converted to dictionary."""
        result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="Test",
            metadata={"key": "value"}
        )
        
        d = result.to_dict()
        
        assert isinstance(d, dict)
        assert d["status"] == "completed"
        assert d["response_text"] == "Test"
        assert d["metadata"]["key"] == "value"
    
    def test_result_defaults(self):
        """Result has sensible defaults."""
        result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="LOCAL",
            provider="local",
            provider_usage_class="local"
        )
        
        assert result.response_text == ""
        assert result.error_message == ""
        assert result.execution_time_ms == 0
        assert result.metadata == {}


class TestEnvironmentPreparation:
    """Test subprocess environment preparation."""
    
    def test_prepare_subprocess_env(self):
        """Environment preparation sets required variables."""
        engine = ExecutionEngine()
        
        env = engine._prepare_subprocess_env()
        
        # Should set namespace variables
        assert "STATE_NAMESPACE_RAW" in env
        assert "LUCY_SHARED_STATE_NAMESPACE" in env
        assert "LUCY_STATE_DIR" in env
    
    def test_environment_isolation(self):
        """Each engine instance has isolated environment."""
        engine1 = ExecutionEngine()
        engine2 = ExecutionEngine()
        
        env1 = engine1._prepare_subprocess_env()
        env2 = engine2._prepare_subprocess_env()
        
        # Namespaces should differ
        assert env1["STATE_NAMESPACE_RAW"] != env2["STATE_NAMESPACE_RAW"]


class TestDirectProviders:
    """Test direct Python provider implementations."""
    
    def test_providers_import(self):
        """Direct providers module imports."""
        from backend.providers import OpenAIProvider, GrokProvider, WikipediaProvider
        
        assert OpenAIProvider is not None
        assert GrokProvider is not None
        assert WikipediaProvider is not None
    
    def test_wikipedia_provider_with_evidence(self):
        """Wikipedia provider formats evidence correctly."""
        from backend.providers import WikipediaProvider
        
        evidence = {
            "context": "Python is a programming language.",
            "title": "Python (programming language)",
            "url": "https://en.wikipedia.org/wiki/Python_(programming_language)"
        }
        
        result = WikipediaProvider.call("What is Python?", evidence=evidence)
        
        assert result.ok is True
        assert "Python is a programming language" in result.text
        assert "Wikipedia" in result.text
    
    def test_wikipedia_provider_no_evidence(self):
        """Wikipedia provider handles missing evidence."""
        from backend.providers import WikipediaProvider
        
        result = WikipediaProvider.call("What is Python?", evidence=None)
        
        assert result.ok is True
        assert "No Wikipedia information" in result.text
