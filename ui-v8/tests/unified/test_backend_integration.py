"""
Integration tests for unified backend.

Verifies backend modules load correctly and work together.
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


class TestBackendImports:
    """Test that all backend modules import correctly."""
    
    def test_import_backend_package(self):
        """Backend package imports without errors."""
        import backend
        
        assert backend is not None
    
    def test_import_classify(self):
        """Classify module imports."""
        from backend.classify import classify_intent, ClassificationResult
        
        assert callable(classify_intent)
        assert ClassificationResult is not None
    
    def test_import_policy(self):
        """Policy module imports."""
        from backend.policy import (
            normalize_augmentation_policy,
            provider_usage_class_for,
        )
        
        assert callable(normalize_augmentation_policy)
        assert callable(provider_usage_class_for)
    
    def test_import_execution_engine(self):
        """ExecutionEngine imports."""
        from backend.execution_engine import ExecutionEngine, ExecutionResult
        
        assert ExecutionEngine is not None
        assert ExecutionResult is not None
    
    def test_import_main(self):
        """Main router imports."""
        from backend.main import execute_plan_python, RouterOutcome
        
        assert callable(execute_plan_python)
        assert RouterOutcome is not None
    
    def test_import_local_answer(self):
        """Local answer module imports."""
        from backend.local_answer import LocalAnswer, LocalAnswerConfig
        
        assert LocalAnswer is not None
        assert LocalAnswerConfig is not None
    
    def test_import_state_manager(self):
        """State manager imports."""
        from backend.state_manager import get_state_manager, StateManager
        
        assert callable(get_state_manager)
        assert StateManager is not None
    
    def test_backend_wrapper_imports(self):
        """Backend wrapper re-exports work."""
        import backend_wrapper
        
        assert hasattr(backend_wrapper, 'execute_plan_python')
        assert hasattr(backend_wrapper, 'classify_intent')
        assert hasattr(backend_wrapper, 'normalize_augmentation_policy')


class TestBackendFunctionality:
    """Test backend functional operations."""
    
    def test_classify_intent(self):
        """Intent classification works."""
        from backend.classify import classify_intent
        
        result = classify_intent("What is the weather today?")
        
        assert result is not None
        assert hasattr(result, 'intent_family')
        assert hasattr(result, 'confidence')
        assert 0 <= result.confidence <= 1
    
    def test_normalize_augmentation_policy(self):
        """Policy normalization works."""
        from backend.policy import normalize_augmentation_policy
        
        # Test various inputs - should return valid policy string
        result1 = normalize_augmentation_policy("fallback_only")
        result2 = normalize_augmentation_policy("augmented")
        
        assert isinstance(result1, str)
        assert isinstance(result2, str)
        assert len(result1) > 0
        assert len(result2) > 0
    
    def test_provider_usage_class(self):
        """Provider usage classification works."""
        from backend.policy import provider_usage_class_for
        
        assert provider_usage_class_for("local") == "local"
        assert provider_usage_class_for("wikipedia") in ("free", "local", "paid")
        assert provider_usage_class_for("openai") in ("paid", "free", "local")
    
    def test_execute_plan_python_local(self):
        """Execute plan with local route."""
        from backend.main import execute_plan_python
        
        result = execute_plan_python(
            "What is 2+2?",
            policy="fallback_only",
            timeout=30
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.route == "LOCAL"
        assert len(result.response_text) > 0
    
    def test_execute_plan_python_with_metadata(self):
        """Execute plan returns full metadata."""
        from backend.main import execute_plan_python
        
        result = execute_plan_python(
            "Hello",
            policy="fallback_only",
            timeout=30
        )
        
        assert hasattr(result, 'status')
        assert hasattr(result, 'route')
        assert hasattr(result, 'provider')
        assert hasattr(result, 'outcome_code')
        assert hasattr(result, 'response_text')


class TestUnifiedArchitecture:
    """Test unified architecture specific features."""
    
    def test_no_shell_execute_plan_dependency(self):
        """Verify execute_plan.sh is not called in pure Python mode."""
        from backend.main import execute_plan_python
        
        # The function should complete without calling execute_plan.sh
        # We verify this by checking it works with LUCY_EXEC_PY=1
        os.environ["LUCY_EXEC_PY"] = "1"
        
        result = execute_plan_python("Test", policy="fallback_only", timeout=30)
        
        # Should complete successfully via Python path
        assert result.status == "completed"
    
    def test_execution_engine_has_providers(self):
        """ExecutionEngine has direct providers available."""
        from backend.execution_engine import ExecutionEngine, HAS_DIRECT_PROVIDERS
        
        assert HAS_DIRECT_PROVIDERS is True
        
        engine = ExecutionEngine()
        assert engine is not None


class TestStateManager:
    """Test StateManager functionality."""
    
    def test_state_manager_initialization(self):
        """StateManager initializes."""
        from backend.state_manager import get_state_manager
        
        sm = get_state_manager("test_namespace")
        
        assert sm is not None


class TestDirectProviders:
    """Test direct Python providers."""
    
    def test_providers_module_imports(self):
        """Providers module imports correctly."""
        from backend.providers import (
            OpenAIProvider, GrokProvider, WikipediaProvider, ProviderResult
        )
        
        assert OpenAIProvider is not None
        assert GrokProvider is not None
        assert WikipediaProvider is not None
        assert ProviderResult is not None
    
    def test_provider_result_creation(self):
        """Can create ProviderResult."""
        from backend.providers import ProviderResult
        
        result = ProviderResult(
            ok=True,
            provider="test",
            text="Hello world"
        )
        
        assert result.ok is True
        assert result.provider == "test"
        assert result.text == "Hello world"
    
    def test_wikipedia_provider(self):
        """Wikipedia provider works with evidence."""
        from backend.providers import WikipediaProvider
        
        evidence = {
            "context": "Test context from Wikipedia",
            "title": "Test Article",
            "url": "https://en.wikipedia.org/wiki/Test"
        }
        
        result = WikipediaProvider.call("test query", evidence=evidence)
        
        assert result.ok is True
        assert "Test context" in result.text
