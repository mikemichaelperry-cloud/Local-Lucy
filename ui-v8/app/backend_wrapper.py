"""
Backend Wrapper - Consolidated Single Source of Truth

Re-exports backend functionality from the unified backend.
All implementation is in:
  /home/mike/lucy-v8/tools/router_py/

This ensures both text and voice paths use IDENTICAL code.
"""

# Import from the consolidated backend (which imports from project root)
from backend import (
    # Main entry points
    execute_plan_python,
    execute_plan_shell,
    execute_plan_parity,
    ensure_control_env,
    RouterOutcome,
    DEFAULT_TIMEOUT,

    # Classification
    classify_intent,
    select_route,
    ClassificationResult,
    RoutingDecision,

    # Execution
    ExecutionEngine,
    ExecutionResult,
    _load_session_memory_context,
    DEFAULT_CHAT_MEMORY_FILE,

    # Local answer
    LocalAnswer,
    LocalAnswerConfig,

    # Policy
    normalize_augmentation_policy,
    requires_evidence_mode,
    provider_usage_class_for,

    # Voice
    VoicePipeline,
    VoiceResult,
    VADConfig,
    AudioBuffer,

    # Utilities
    sha256_text,

    # Availability
    BACKEND_AVAILABLE,

    # Path info
    SNAPSHOT_ROOT,
    ROUTER_PY_PATH,
)

__all__ = [
    'execute_plan_python',
    'execute_plan_shell',
    'execute_plan_parity',
    'ensure_control_env',
    'RouterOutcome',
    'DEFAULT_TIMEOUT',
    'classify_intent',
    'select_route',
    'ClassificationResult',
    'RoutingDecision',
    'ExecutionEngine',
    'ExecutionResult',
    '_load_session_memory_context',
    'DEFAULT_CHAT_MEMORY_FILE',
    'LocalAnswer',
    'LocalAnswerConfig',
    'normalize_augmentation_policy',
    'requires_evidence_mode',
    'provider_usage_class_for',
    'VoicePipeline',
    'VoiceResult',
    'VADConfig',
    'AudioBuffer',
    'sha256_text',
    'BACKEND_AVAILABLE',
    'SNAPSHOT_ROOT',
    'ROUTER_PY_PATH',
]

# Debug info
if __name__ == "__main__":
    print(f"Backend source: {ROUTER_PY_PATH}")
    print(f"Backend available: {BACKEND_AVAILABLE}")
