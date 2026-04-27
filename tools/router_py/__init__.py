"""
Local Lucy v8 - Python Router Components

Phase 1-5 of router migration: Utility, Policy, Classification, Main Orchestration, and Tool Wrappers.

Usage:
    # Direct Python API (Phase 4)
    from router_py import execute_plan_python, classify_intent, select_route
    
    result = execute_plan_python("Who was Ada Lovelace?")
    print(result.route)  # "AUGMENTED"
    print(result.provider)  # "wikipedia"
    
    # Or use individual components
    classification = classify_intent("What is 2+2?")
    decision = select_route(classification, policy="fallback_only")
    
    # Tool Wrappers (Phase 5)
    from router_py import RequestTool, ToolConfig
    
    tool = RequestTool(ToolConfig(timeout=30.0))
    result = await tool.generate("What is 2+2?")
    
    # Voice Pipeline (Phase 5)
    from router_py import VoicePipeline, quick_voice_interaction
    
    result = await quick_voice_interaction()
    print(f"You said: {result.transcript}")
    print(f"Lucy said: {result.response_text}")
"""

# Phase 1: Utilities
from .utils import (
    sha256_text,
    guard_normalize,
    deterministic_pick_index,
    is_allowed_repeat_body,
)

# Phase 2: Policy
from .policy import (
    normalize_augmentation_policy,
    requires_evidence_mode,
    provider_usage_class_for,
    manifest_evidence_selection_label,
)

# Phase 3: Classification
from .classify import (
    ClassificationResult,
    RoutingDecision,
    classify_intent,
    select_route,
)

# Phase 4: Main Orchestration
from .main import (
    RouterOutcome,
    ShadowComparison,
    execute_plan_python,
    execute_plan_shell,
    execute_plan_shadow,
)

# Tool Wrappers (Phase 5)
from .base_tool_wrapper import (
    ToolConfig,
    ToolResult,
    BaseToolWrapper,
)
from .request_tool import (
    RequestTool,
)

# Voice Pipeline (Phase 5) - optional import for graceful fallback
try:
    from .voice_tool import (
        VoicePipeline,
        AudioBuffer,
        VoiceResult,
        VoiceMetrics,
        VADConfig,
        quick_voice_interaction,
        VoicePipelineError,
        RecordingError,
        TranscriptionError,
        SynthesisError,
        PlaybackError,
    )
    _voice_available = True
except ImportError as _voice_import_err:
    _voice_available = False
    # Define placeholder classes for type hints when voice deps are missing
    class VoicePipeline:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(f"Voice pipeline not available: {_voice_import_err}")

__version__ = "0.6.0"
__all__ = [
    # Phase 1: Utilities
    "sha256_text",
    "guard_normalize",
    "deterministic_pick_index",
    "is_allowed_repeat_body",
    # Phase 2: Policy
    "normalize_augmentation_policy",
    "requires_evidence_mode",
    "provider_usage_class_for",
    "manifest_evidence_selection_label",
    # Phase 3: Classification
    "ClassificationResult",
    "RoutingDecision",
    "classify_intent",
    "select_route",
    # Phase 4: Main Orchestration
    "RouterOutcome",
    "ShadowComparison",
    "execute_plan_python",
    "execute_plan_shell",
    "execute_plan_shadow",
    # Phase 5: Tool Wrappers
    "ToolConfig",
    "ToolResult",
    "BaseToolWrapper",
    "RequestTool",
    # Phase 5: Voice Pipeline (optional)
    "VoicePipeline",
    "AudioBuffer",
    "VoiceResult",
    "VoiceMetrics",
    "VADConfig",
    "quick_voice_interaction",
    "VoicePipelineError",
    "RecordingError",
    "TranscriptionError",
    "SynthesisError",
    "PlaybackError",
]
