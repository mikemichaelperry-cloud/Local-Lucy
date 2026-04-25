"""
Local Lucy v8 - Consolidated Backend (Single Source of Truth)

This module provides a unified interface to the backend by importing
from the authoritative snapshot location:
  snapshots/opt-experimental-v8-dev/tools/router_py/

This ensures both text and voice paths use the exact same code.

Last Updated: 2026-04-20
Architecture: Single Source of Truth
"""

from __future__ import annotations

import sys
from pathlib import Path

# -----------------------------------------------------------------------------
# CRITICAL: Set up path to import from authoritative snapshot location
# -----------------------------------------------------------------------------

# V8 ISOLATION: Use environment variable or authority root, not hardcoded home path
import os
AUTHORITY_ROOT = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "").strip()
if AUTHORITY_ROOT:
    SNAPSHOT_ROOT = Path(AUTHORITY_ROOT).expanduser()
else:
    # Fallback: derive from current file location or home
    SNAPSHOT_ROOT = Path(__file__).resolve().parents[3] / "snapshots" / "opt-experimental-v8-dev"
TOOLS_PATH = SNAPSHOT_ROOT / "tools"
ROUTER_PY_PATH = TOOLS_PATH / "router_py"

# Add tools to path (needed for router_py imports)
if str(TOOLS_PATH) not in sys.path:
    sys.path.insert(0, str(TOOLS_PATH))

# -----------------------------------------------------------------------------
# Import all backend components from single source of truth
# We import from router_py package directly
# -----------------------------------------------------------------------------

try:
    # Import the router_py package
    import router_py
    
    # Main entry points
    from router_py.main import (
        execute_plan_python,
        execute_plan_shell,
        execute_plan_shadow,
        _delegate_execution,
        _delegate_execution_to_python,
        _delegate_execution_to_shell,
        ensure_control_env,
        RouterOutcome,
        DEFAULT_TIMEOUT,
    )
    
    # Classification
    from router_py.classify import (
        classify_intent,
        select_route,
        ClassificationResult,
        RoutingDecision,
    )
    
    # Execution
    from router_py.execution_engine import (
        ExecutionEngine,
        ExecutionResult,
        _load_session_memory_context,
        DEFAULT_CHAT_MEMORY_FILE,
    )
    
    # Local answer
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    
    # Policy
    from router_py.policy import (
        normalize_augmentation_policy,
        requires_evidence_mode,
        provider_usage_class_for,
    )
    
    # Voice tools
    from router_py.voice_tool import (
        VoicePipeline,
        VoiceResult,
        VADConfig,
        AudioBuffer,
    )
    
    # Utilities
    from router_py.utils import sha256_text
    
    BACKEND_AVAILABLE = True
    
except ImportError as e:
    print(f"[Backend] CRITICAL ERROR: Failed to import from snapshot: {e}", file=sys.stderr)
    print(f"[Backend] Path attempted: {ROUTER_PY_PATH}", file=sys.stderr)
    BACKEND_AVAILABLE = False
    raise

# -----------------------------------------------------------------------------
# Re-export for backward compatibility
# -----------------------------------------------------------------------------

__all__ = [
    # Main entry points
    "execute_plan_python",
    "execute_plan_shell", 
    "execute_plan_shadow",
    "_delegate_execution",
    "_delegate_execution_to_python",
    "_delegate_execution_to_shell",
    "ensure_control_env",
    "RouterOutcome",
    "DEFAULT_TIMEOUT",
    
    # Classification
    "classify_intent",
    "select_route",
    "ClassificationResult",
    "RoutingDecision",
    
    # Execution
    "ExecutionEngine",
    "ExecutionResult",
    "_load_session_memory_context",
    "DEFAULT_CHAT_MEMORY_FILE",
    
    # Local answer
    "LocalAnswer",
    "LocalAnswerConfig",
    
    # Policy
    "normalize_augmentation_policy",
    "requires_evidence_mode",
    "provider_usage_class_for",
    
    # Voice
    "VoicePipeline",
    "VoiceResult",
    "VADConfig",
    "AudioBuffer",
    
    # Utilities
    "sha256_text",
    
    # Backend availability
    "BACKEND_AVAILABLE",
    
    # Path info
    "SNAPSHOT_ROOT",
    "ROUTER_PY_PATH",
]

# Version info
__backend_source__ = str(ROUTER_PY_PATH)
__backend_available__ = BACKEND_AVAILABLE
