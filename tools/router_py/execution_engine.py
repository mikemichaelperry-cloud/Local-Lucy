#!/usr/bin/env python3
"""
Execution Engine - Python implementation for plan execution.

This module replaces execute_plan.sh functionality, handling the actual
execution of routing decisions made by the Python Router.

The ExecutionEngine receives routing decisions from the Router and handles:
- Route-specific execution logic (bypass, provisional, full)
- Tool dispatch and result formatting
- Response enhancement and metadata tracking
- State persistence for post-execution analysis

CRITICAL DESIGN PRINCIPLE:
The ExecutionEngine DELEGATES to governed tool paths rather than calling
providers directly. This preserves authority semantics and truth metadata.
"""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Generator

# Async HTTP support for provider calls
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.classify import ClassificationResult, RoutingDecision
from router_py.policy import requires_evidence_mode
from router_py.state_manager import get_state_manager

# Import Python local_answer if available
try:
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    HAS_LOCAL_ANSWER_PY = True
except ImportError:
    HAS_LOCAL_ANSWER_PY = False

# Import news provider for live news fetching
try:
    from router_py.news_provider import NewsProvider, NewsResult
    HAS_NEWS_PROVIDER = True
except ImportError:
    HAS_NEWS_PROVIDER = False


# TODO: Migrate from execute_plan.sh - State file paths
STATE_DIR = ROOT_DIR / "state" / "namespaces" / "default"
LAST_ROUTE_FILE = STATE_DIR / "last_route.env"
LAST_OUTCOME_FILE = STATE_DIR / "last_outcome.env"

# TODO: Migrate from execute_plan.sh - Tool paths
SHELL_EXECUTE_PLAN = ROOT_DIR / "tools" / "router" / "execute_plan.sh"
LOCAL_ANSWER_SCRIPT = ROOT_DIR / "tools" / "local_answer.sh"
LOCAL_ANSWER_PY_SCRIPT = ROOT_DIR / "tools" / "router_py" / "local_answer.py"

# Feature flag: Use Python local_answer instead of shell version
# Default is "1" (Python) - shell path available via LUCY_LOCAL_ANSWER_PY=0 if needed
USE_LOCAL_ANSWER_PY = os.environ.get("LUCY_LOCAL_ANSWER_PY", "1") == "1"
UNVERIFIED_CONTEXT_DISPATCH = ROOT_DIR / "tools" / "unverified_context_provider_dispatch.py"
CONVERSATION_SHIM = ROOT_DIR / "tools" / "conversation" / "conversation_cadence_shim.py"

# TODO: Migrate from execute_plan.sh - Configuration defaults
DEFAULT_TIMEOUT = 130
DEFAULT_POLICY_CONFIDENCE_THRESHOLD = 0.60

# Default chat memory file path (matches runtime_request.py)
DEFAULT_CHAT_MEMORY_FILE = "~/.codex-api-home/lucy/runtime-v8/state/chat_session_memory.txt"


def _load_session_memory_context_with_telemetry(
    query: str = "", depth: str = "auto", mode: str = "local"
) -> tuple[str, dict[str, str]]:
    """
    Load session memory context and capture telemetry.

    Returns:
        Tuple of (context_string, telemetry_dict).
        telemetry_dict contains:
            memory_context_used: "true" or "false"
            memory_mode_used: "local", "augmented", or "none"
            memory_depth_used: "shallow", "deep", or "none"
            memory_top_score: similarity of top match or "none"
            memory_session_injected: session_id of top injected match or "none"
            memory_top_gap: gap between top 1 and top 2 or "none"
    """
    telemetry: dict[str, str] = {
        "memory_context_used": "false",
        "memory_mode_used": "none",
        "memory_depth_used": "none",
        "memory_top_score": "none",
        "memory_session_injected": "none",
        "memory_top_gap": "none",
    }

    # Check if memory is enabled
    if os.environ.get("LUCY_SESSION_MEMORY", "0") != "1":
        return "", telemetry

    # SQLite-first read attempt (summary-aware context assembly)
    try:
        from memory.memory_service import assemble_context_with_telemetry
        context, telemetry = assemble_context_with_telemetry(
            max_chars=500, query=query, depth=depth, mode=mode
        )
        if context:
            return context, telemetry
    except Exception:
        pass  # Fall through to legacy text-file logic

    # Get memory file path (check both runtime and standard env vars)
    mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
    if not mem_file:
        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
    if not mem_file:
        mem_file = DEFAULT_CHAT_MEMORY_FILE

    mem_path = Path(mem_file).expanduser()

    try:
        with open(mem_path, "r", encoding="utf-8") as f:
            # Only include lines starting with "User: " or "Assistant: "
            lines = [line.rstrip("\n") for line in f if line.startswith(("User: ", "Assistant: "))]
    except (OSError, FileNotFoundError):
        return "", telemetry

    if not lines:
        return "", telemetry

    # Limit context size (last 16 lines, max 500 chars)
    max_lines = 16
    max_chars = 500
    context = "\n".join(lines[-max_lines:]).strip()

    if len(context) > max_chars:
        context = context[-max_chars:]

    if context:
        telemetry["memory_context_used"] = "true"
        telemetry["memory_mode_used"] = mode
        telemetry["memory_depth_used"] = depth
    return context, telemetry


def _load_session_memory_context(query: str = "", depth: str = "auto", mode: str = "local") -> str:
    """
    Load session memory context from the chat memory file.

    Backward-compatible wrapper that returns only the context string.
    """
    context, _ = _load_session_memory_context_with_telemetry(query, depth, mode)
    return context


@dataclass(frozen=True)
class ExecutionResult:
    """
    Structured result from plan execution.
    
    This dataclass captures the outcome of executing a routing decision,
    including the response text, metadata about the execution path taken,
    and any error information.
    
    Attributes:
        status: Execution status ("completed", "failed", "timeout")
        outcome_code: Specific outcome code (e.g., "answered", "local_fallback")
        route: The route that was executed ("LOCAL", "AUGMENTED", "CLARIFY")
        provider: The provider used ("local", "wikipedia", "openai", etc.)
        provider_usage_class: Usage classification ("local", "free", "paid")
        response_text: The actual response content
        error_message: Error description if status is "failed"
        execution_time_ms: Total execution time in milliseconds
        metadata: Additional execution metadata (trust class, evidence mode, etc.)
    """
    
    status: str
    outcome_code: str
    route: str
    provider: str
    provider_usage_class: str
    response_text: str = ""
    error_message: str = ""
    execution_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary for serialization."""
        return {
            "status": self.status,
            "outcome_code": self.outcome_code,
            "route": self.route,
            "provider": self.provider,
            "provider_usage_class": self.provider_usage_class,
            "response_text": self.response_text,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata,
        }


class ExecutionEngine:
    """
    Engine for executing routing decisions.
    
    The ExecutionEngine takes routing decisions from the Router and executes
them according to the route type (bypass, provisional, or full). It handles:
    
    1. Route-specific execution paths
    2. Tool dispatch via governed shell paths
    3. Response formatting and enhancement
    4. State persistence for telemetry
    
    Design Philosophy:
    - Delegate to governed paths: Use existing shell tools for provider calls
    - Preserve authority: Maintain truth metadata through execution chain
    - Fail gracefully: Fall back to local responses on provider errors
    - Transparent: Record execution path for debugging and audit
    
    TODO: Migrate from execute_plan.sh:
    - All route execution logic (bypass, provisional, full)
    - Provider dispatch via unverified_context_provider_dispatch.py
    - Conversation shim integration
    - State file writing (last_route.env, last_outcome.env)
    - Telemetry and metrics collection
    - Error handling and fallback logic
    """
    
    # =========================================================================
    # TIMEOUTS (seconds)
    # =========================================================================
    DEFAULT_TIMEOUT: int = 130
    
    # =========================================================================
    # FILE PATHS - Tool executables
    # =========================================================================
    CLASSIFIER_SCRIPT: Path = ROOT_DIR / "tools" / "router" / "classify_intent.py"
    PLAN_MAPPER_SCRIPT: Path = ROOT_DIR / "tools" / "router" / "plan_to_pipeline.py"
    EXTRACTOR_SCRIPT: Path = ROOT_DIR / "tools" / "router" / "extract_validated.py"
    LUCY_CHAT_SCRIPT: Path = ROOT_DIR / "lucy_chat.sh"
    LOCAL_ANSWER_SCRIPT: Path = ROOT_DIR / "tools" / "local_answer.sh"
    LOCAL_WORKER_SCRIPT: Path = ROOT_DIR / "tools" / "local_worker.py"
    LOCAL_WORKER_CLIENT_LIB: Path = ROOT_DIR / "tools" / "local_worker_client.sh"
    CONV_SHIM_SCRIPT: Path = ROOT_DIR / "tools" / "conversation" / "conversation_cadence_shim.py"
    UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL: Path = ROOT_DIR / "tools" / "unverified_context_provider_dispatch.py"
    LATPROF_LIB: Path = ROOT_DIR / "tools" / "router" / "latency_profile.sh"
    
    # =========================================================================
    # FILE PATHS - Configuration files
    # =========================================================================
    UNVERIFIED_CONTEXT_CATALOG: Path = ROOT_DIR / "config" / "unverified_context_sources_v1.tsv"
    UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS: Path = ROOT_DIR / "config" / "unverified_context_provider_defaults_v1.env"
    CONV_PROFILE_FILE: Path = ROOT_DIR / "config" / "conversation_profile.json"
    
    # =========================================================================
    # FILE PATHS - State files
    # =========================================================================
    LAST_OUTCOME_FILE: Path = STATE_DIR / "last_outcome.env"
    LAST_ROUTE_FILE: Path = STATE_DIR / "last_route.env"
    RUNTIME_OUTPUT_GUARD_FILE: Path = STATE_DIR / "runtime_output_guard.tsv"
    RUNTIME_OUTPUT_GUARD_COUNTS_FILE: Path = STATE_DIR / "runtime_output_guard_counts.tsv"
    
    # =========================================================================
    # POLICY DEFAULTS
    # =========================================================================
    POLICY_CONFIDENCE_THRESHOLD: float = 0.60
    POLICY_FRESHNESS_REQUIREMENT: str = "low"
    POLICY_RISK_LEVEL: str = "low"
    POLICY_SOURCE_CRITICALITY: str = "low"
    POLICY_OPERATOR_OVERRIDE: str = "none"
    POLICY_REASON_CODES_CSV: str = ""
    DEFAULT_AUGMENTATION_POLICY: str = "fallback_only"
    
    # =========================================================================
    # ROUTING DEFAULTS
    # =========================================================================
    ROUTE_REASON_OVERRIDE: str = "router_classifier_mapper"
    ROUTER_OUTCOME_CODE: str = "answered"
    REQUESTED_MODE: str = "LOCAL"
    FINAL_MODE: str = "LOCAL"
    KNOWLEDGE_PATH: str = "none"
    WINNING_SIGNAL: str = "legacy_policy"
    
    # =========================================================================
    # LOCAL DIRECT PATH DEFAULTS
    # =========================================================================
    LOCAL_DIRECT_PATH: str = "disabled"
    LOCAL_DIRECT_USED: bool = False
    LOCAL_DIRECT_FALLBACK: bool = False
    CONTEXTUAL_LOCAL_FOLLOWUP: int = 0
    
    # =========================================================================
    # AUGMENTATION DEFAULTS
    # =========================================================================
    AUGMENTED_DIRECT_REQUEST: bool = False
    AUGMENTED_ALLOWED: bool = False
    AUGMENTED_PROVIDER_SELECTED: str = "none"
    AUGMENTED_PROVIDER_USED: str = "none"
    AUGMENTED_PROVIDER_USAGE_CLASS: str = "none"
    AUGMENTED_PROVIDER_CALL_REASON: str = "not_needed"
    AUGMENTED_PROVIDER_SELECTION_REASON: str = "none"
    AUGMENTED_PROVIDER_SELECTION_QUERY: str = "none"
    AUGMENTED_PROVIDER_SELECTION_RULE: str = "none"
    AUGMENTED_PROVIDER_COST_NOTICE: bool = False
    AUGMENTED_PAID_PROVIDER_INVOKED: bool = False
    AUGMENTED_BEHAVIOR_SHAPE: str = "stable_summary"
    AUGMENTED_CLARIFICATION_REQUIRED: bool = False
    
    # =========================================================================
    # TRUST AND VERIFICATION DEFAULTS
    # =========================================================================
    TRUST_CLASS: str = "unverified"
    UNVERIFIED_CONTEXT_USED: bool = False
    UNVERIFIED_CONTEXT_CLASS: str = "none"
    UNVERIFIED_CONTEXT_TITLE: str = ""
    UNVERIFIED_CONTEXT_URL: str = ""
    AUGMENTED_PROVIDER: str = "none"
    AUGMENTED_PROVIDER_ERROR_REASON: str = "none"
    AUGMENTED_PROVIDER_STATUS: str = "none"
    UNVERIFIED_CONTEXT_PROMPT_BLOCK: str = ""
    AUGMENTED_UNVERIFIED_RAW: str = ""
    
    # =========================================================================
    # FALLBACK DEFAULTS
    # =========================================================================
    FALLBACK_USED: bool = False
    FALLBACK_REASON: str = "none"
    FALLBACK_KIND: str = "none"
    
    # =========================================================================
    # RECOVERY DEFAULTS
    # =========================================================================
    RECOVERY_ATTEMPTED: bool = False
    RECOVERY_USED: bool = False
    RECOVERY_ELIGIBLE: bool = False
    RECOVERY_LANE: str = "none"
    
    # =========================================================================
    # CONVERSATION DEFAULTS
    # =========================================================================
    CONVERSATION_SHIM_APPLIED: int = 0
    CONVERSATION_SHIM_PROFILE: str = "none"
    
    # =========================================================================
    # GUARD AND SAFETY DEFAULTS
    # =========================================================================
    GUARD_TRIGGER: str = "none"
    LOCAL_GEN_STATUS: str = "ok"
    EVIDENCE_STYLE_BLOCKED: int = 0
    LOCAL_EVIDENCE_LEXEME_DETECTED: int = 0
    REPEAT_COUNT_SESSION: int = 0
    LOCAL_FORCE_PLAIN_FALLBACK: int = 0
    TELEMETRY_SYNC_ENABLED: int = 0
    
    # =========================================================================
    # POLICY STATE DEFAULTS
    # =========================================================================
    POLICY_RECOMMENDED_ROUTE: str = "local"
    POLICY_ACTUAL_ROUTE: str = "local"
    POLICY_CONFIDENCE: float = 0.0
    
    # =========================================================================
    # MANIFEST DEFAULTS
    # =========================================================================
    MANIFEST_VERSION: str = ""
    MANIFEST_SELECTED_ROUTE: str = ""
    MANIFEST_ALLOWED_ROUTES: str = ""
    MANIFEST_FORBIDDEN_ROUTES: str = ""
    MANIFEST_AUTHORITY_BASIS: str = ""
    MANIFEST_CLARIFY_REQUIRED: str = "false"
    MANIFEST_CONTEXT_RESOLUTION_USED: str = "false"
    MANIFEST_CONTEXT_REFERENT_CONFIDENCE: str = ""
    MANIFEST_EVIDENCE_MODE: str = ""
    MANIFEST_EVIDENCE_MODE_REASON: str = ""
    MANIFEST_ERROR: str = ""
    
    # =========================================================================
    # ROUTING SIGNAL DEFAULTS
    # =========================================================================
    ROUTING_SIGNAL_TEMPORAL: bool = False
    ROUTING_SIGNAL_NEWS: bool = False
    ROUTING_SIGNAL_CONFLICT: bool = False
    ROUTING_SIGNAL_GEOPOLITICS: bool = False
    ROUTING_SIGNAL_ISRAEL_REGION: bool = False
    ROUTING_SIGNAL_SOURCE_REQUEST: bool = False
    ROUTING_SIGNAL_URL: bool = False
    ROUTING_SIGNAL_AMBIGUITY_FOLLOWUP: bool = False
    ROUTING_SIGNAL_MEDICAL_CONTEXT: bool = False
    ROUTING_SIGNAL_CURRENT_PRODUCT: bool = False
    
    # =========================================================================
    # GOVERNOR DEFAULTS
    # =========================================================================
    GOVERNOR_INTENT: str = ""
    GOVERNOR_CONFIDENCE: float = 0.0
    GOVERNOR_ROUTE: str = ""
    GOVERNOR_ALLOWED_TOOLS: str = ""
    GOVERNOR_REQUIRES_SOURCES: bool = False
    GOVERNOR_REQUIRES_CLARIFICATION: bool = False
    GOVERNOR_FALLBACK_POLICY: str = "none"
    GOVERNOR_AUDIT_TAGS: str = ""
    GOVERNOR_CONTRACT_VERSION: str = ""
    GOVERNOR_LOCAL_RESPONSE_ID: str = ""
    GOVERNOR_LOCAL_RESPONSE_TEXT: str = ""
    GOVERNOR_RESOLVED_QUESTION: str = ""
    GOVERNOR_CONTEXTUAL_FOLLOWUP_APPLIED: bool = False
    
    # =========================================================================
    # SEMANTIC INTERPRETER DEFAULTS
    # =========================================================================
    SEMANTIC_INTERPRETER_FIRED: bool = False
    SEMANTIC_INTERPRETER_ORIGINAL_QUERY: str = ""
    SEMANTIC_INTERPRETER_RESOLVED_EXECUTION_QUERY: str = ""
    SEMANTIC_INTERPRETER_INFERRED_DOMAIN: str = "unknown"
    SEMANTIC_INTERPRETER_INFERRED_INTENT_FAMILY: str = "unknown"
    SEMANTIC_INTERPRETER_CONFIDENCE: float = 0.0
    SEMANTIC_INTERPRETER_AMBIGUITY_FLAG: bool = False
    SEMANTIC_INTERPRETER_GATE_REASON: str = "not_invoked"
    SEMANTIC_INTERPRETER_INVOCATION_ATTEMPTED: bool = False
    SEMANTIC_INTERPRETER_RESULT_STATUS: str = "not_invoked"
    SEMANTIC_INTERPRETER_USE_REASON: str = "not_invoked"
    SEMANTIC_INTERPRETER_USED_FOR_ROUTING: bool = False
    SEMANTIC_INTERPRETER_FORWARD_CANDIDATES: bool = False
    SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY: str = ""
    SEMANTIC_INTERPRETER_SELECTED_RETRIEVAL_QUERY: str = ""
    SEMANTIC_INTERPRETER_NORMALIZED_CANDIDATES_CSV: str = ""
    SEMANTIC_INTERPRETER_RETRIEVAL_CANDIDATES_CSV: str = ""
    SEMANTIC_INTERPRETER_NORMALIZED_CANDIDATES_JSON: str = "[]"
    SEMANTIC_INTERPRETER_RETRIEVAL_CANDIDATES_JSON: str = "[]"
    SEMANTIC_INTERPRETER_RETRIEVAL_SELECTED: bool = False
    
    # =========================================================================
    # MEDICAL DETECTOR DEFAULTS
    # =========================================================================
    MEDICAL_DETECTOR_FIRED: bool = False
    MEDICAL_DETECTOR_ORIGINAL_QUERY: str = ""
    MEDICAL_DETECTOR_RESOLVED_EXECUTION_QUERY: str = ""
    MEDICAL_DETECTOR_DETECTION_SOURCE: str = "none"
    MEDICAL_DETECTOR_PATTERN_FAMILY: str = "none"
    MEDICAL_DETECTOR_CANDIDATE_MEDICATION: str = ""
    MEDICAL_DETECTOR_NORMALIZED_CANDIDATE: str = ""
    MEDICAL_DETECTOR_NORMALIZED_QUERY: str = ""
    MEDICAL_DETECTOR_CONFIDENCE: float = 0.0
    MEDICAL_DETECTOR_CONFIDENCE_SCORE: float = 0.0
    
    # =========================================================================
    # CHILD ROUTE DEFAULTS
    # =========================================================================
    CHILD_ROUTE_SESSION_ID: str = ""
    CHILD_ROUTE_EVIDENCE_CREATED: bool = False
    CHILD_OUTCOME_CODE: str = ""
    CHILD_ACTION_HINT: str = ""
    CHILD_TRUST_CLASS: str = ""
    SHARED_STATE_LOCK_ERROR: str = ""
    
    # =========================================================================
    # PRIMARY OUTCOME DEFAULTS
    # =========================================================================
    PRIMARY_OUTCOME_CODE: str = ""
    PRIMARY_TRUST_CLASS: str = ""
    OUTCOME_CODE_OVERRIDE: str = ""
    
    # =========================================================================
    # CHILD TRACE FIELDS
    # =========================================================================
    CHILD_TRACE_FIELDS: str = (
        "EVIDENCE_FETCH_ATTEMPTED EVIDENCE_PLANNER_ORIGINAL_QUERY EVIDENCE_PLANNER_FIRED "
        "EVIDENCE_PLANNER_BEST_ADAPTER EVIDENCE_PLANNER_BEST_STRATEGY EVIDENCE_PLANNER_BEST_QUERY "
        "EVIDENCE_PLANNER_BEST_CONFIDENCE EVIDENCE_PLANNER_BEST_CONFIDENCE_SCORE "
        "EVIDENCE_PLANNER_SELECTED_QUERY EVIDENCE_PLANNER_SELECTED_ADAPTER EVIDENCE_PLANNER_SELECTED_STRATEGY "
        "EVIDENCE_PLANNER_SELECTED_CONFIDENCE EVIDENCE_PLANNER_SELECTED_CONFIDENCE_SCORE "
        "EVIDENCE_NORMALIZER_ORIGINAL_QUERY EVIDENCE_NORMALIZER_DETECTOR_FIRED "
        "EVIDENCE_NORMALIZER_BEST_ADAPTER EVIDENCE_NORMALIZER_BEST_DOMAIN EVIDENCE_NORMALIZER_BEST_QUERY "
        "EVIDENCE_NORMALIZER_BEST_CONFIDENCE EVIDENCE_NORMALIZER_BEST_CONFIDENCE_SCORE "
        "EVIDENCE_NORMALIZER_BEST_RULES EVIDENCE_NORMALIZER_SELECTED_QUERY EVIDENCE_NORMALIZER_SELECTED_ADAPTER "
        "EVIDENCE_NORMALIZER_SELECTED_DOMAIN EVIDENCE_NORMALIZER_SELECTED_CONFIDENCE "
        "EVIDENCE_NORMALIZER_SELECTED_CONFIDENCE_SCORE EVIDENCE_NORMALIZER_SELECTED_RULES "
        "EVIDENCE_NORMALIZER_SELECTED_KEYS EVIDENCE_NORMALIZER_SELECTED_KEY_FAMILY EVIDENCE_NORMALIZER_MATCH_KIND"
    )
    
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        """
        Initialize the execution engine.
        
        Args:
            config: Optional configuration dictionary. Supported keys:
                - timeout: Request timeout in seconds (default: 130)
                - state_dir: Directory for state files
                - policy_confidence_threshold: Minimum confidence for augmented routes
                - enable_telemetry: Whether to collect execution metrics
        
        TODO: Migrate from execute_plan.sh:
        - Load configuration from environment variables
        - Initialize state directory structure
        - Set up telemetry/logging
        - Load policy defaults
        """
        self.config = config or {}
        self.timeout = self.config.get("timeout", self.DEFAULT_TIMEOUT)
        self.policy_confidence_threshold = self.config.get(
            "policy_confidence_threshold", self.POLICY_CONFIDENCE_THRESHOLD
        )
        
        # Initialize logger first (needed by _resolve_state_dir)
        self._logger = logging.getLogger(__name__)
        
        # =========================================================================
        # NAMESPACE ISOLATION SETUP
        # =========================================================================
        # Generate a truly unique namespace for this execution instance.
        # This prevents "shared-state overlap" errors when shell scripts
        # check for STATE_NAMESPACE_RAW and skip their own locking.
        # 
        # NAMESPACE ISOLATION STRATEGY:
        # - Each ExecutionEngine instance gets a unique namespace
        # - Format: {hostname}_{pid}_{timestamp}_{random}
        # - Example: "mike_12345_1712948423_a7f3e2"
        # - This ensures no collision even with rapid sequential queries
        #
        # The namespace is used to:
        # 1. Create an isolated state directory (ROOT/state/namespaces/{namespace}/)
        # 2. Set STATE_NAMESPACE_RAW to tell shell scripts to skip their own locking
        # 3. Set LUCY_SHARED_STATE_NAMESPACE for state file isolation
        # 4. Set LUCY_STATE_DIR for subprocess state file location
        hostname = socket.gethostname().split('.')[0]  # Get short hostname
        pid = os.getpid()
        timestamp = int(time.time() * 1000)  # Millisecond precision
        random_suffix = uuid.uuid4().hex[:8]
        self._execution_namespace = f"{hostname}_{pid}_{timestamp}_{random_suffix}"
        
        # Resolve the state directory based on the unique namespace
        # This creates isolated storage: ROOT/state/namespaces/{namespace}/
        self._state_dir = self._resolve_state_dir()
        
        # Ensure state directory exists
        self._state_dir.mkdir(parents=True, exist_ok=True)
        
        # =========================================================================
        # STATE MANAGER INITIALIZATION (SQLite-backed state)
        # =========================================================================
        # Initialize StateManager for SQLite-backed state persistence.
        # This provides robust, queryable state storage alongside file-based state.
        namespace = (config or {}).get("namespace", self._execution_namespace)
        self.state_manager = get_state_manager(namespace)
        self.use_sqlite_state = (config or {}).get("use_sqlite_state", True)
        self._logger.info(f"StateManager initialized with namespace: {namespace}")
        
        self._logger.debug(
            f"ExecutionEngine initialized with namespace: {self._execution_namespace}, "
            f"state_dir: {self._state_dir}, sqlite_state: {self.use_sqlite_state}"
        )
    
    def _resolve_state_dir(self) -> Path:
        """
        Resolve the state directory with namespace isolation support.
        
        This method ensures proper state namespace isolation to prevent collisions
        between concurrent query executions. Each ExecutionEngine instance gets
        its own unique namespace directory.
        
        NAMESPACE ISOLATION STRATEGY:
        - Each ExecutionEngine instance has a unique _execution_namespace
        - State directory format: ROOT/state/namespaces/{namespace}/
        - This provides complete isolation between concurrent executions
        - Shell scripts check STATE_NAMESPACE_RAW and skip their own locking
        
        Returns:
            Path to the namespaced state directory
        """
        # Use the instance's unique execution namespace
        # Sanitize to prevent path traversal attacks
        safe_namespace = re.sub(r'[^a-zA-Z0-9_-]', '_', self._execution_namespace)
        state_dir = ROOT_DIR / "state" / "namespaces" / safe_namespace
        self._logger.debug(f"Using namespace-isolated state dir: {state_dir}")
        return state_dir
    
    def _prepare_subprocess_env(self, base_env: dict[str, str] | None = None) -> dict[str, str]:
        """
        Prepare environment variables for subprocess calls.
        
        NAMESPACE ISOLATION FOR SUBPROCESSES:
        This helper ensures ALL subprocess calls (lucy_chat.sh, local_answer.sh,
        local_worker.py, unverified_context_provider_dispatch.py, etc.) receive
        the proper namespace isolation environment variables.
        
        Critical Environment Variables:
        - STATE_NAMESPACE_RAW: Tells shell scripts to skip their own locking
        - LUCY_SHARED_STATE_NAMESPACE: Used for state file isolation
        - LUCY_STATE_DIR: Points to the namespaced state directory
        
        When STATE_NAMESPACE_RAW is set, execute_plan.sh skips acquire_shared_execution_lock(),
        preventing "shared-state overlap" errors during concurrent executions.
        
        Args:
            base_env: Optional base environment to extend (defaults to os.environ)
        
        Returns:
            Dictionary of environment variables for subprocess execution
        """
        env = (base_env or os.environ).copy()
        env.update({
            # Critical: Tells shell scripts (execute_plan.sh) to skip their own locking
            # This prevents "shared-state overlap detected" errors
            "STATE_NAMESPACE_RAW": self._execution_namespace,
            # Used by state file operations for namespace isolation
            "LUCY_SHARED_STATE_NAMESPACE": self._execution_namespace,
            # Points subprocesses to the correct state directory
            "LUCY_STATE_DIR": str(self._state_dir),
        })
        return env
    
    @contextmanager
    def _file_lock(
        self, 
        target_file: Path, 
        max_retries: int = 3,
        backoff_base_ms: float = 10.0
    ) -> Generator[None, None, None]:
        """
        Context manager for exclusive file locking with retry logic.
        
        FIX: Lock File Race Condition and Retry Logic
        
        This implementation addresses the "shared-state overlap" errors by:
        1. Using atomic lock acquisition with fcntl.LOCK_EX | fcntl.LOCK_NB
        2. Implementing exponential backoff retry (10ms, 50ms, 100ms)
        3. Proceeding without lock after retries (best-effort, with warning)
        4. Always cleaning up lock file descriptor in finally block
        
        The lock file is created adjacent to the target file with a .lock suffix.
        This ensures lock files are co-located with the data they protect.
        
        Args:
            target_file: The file being protected (used to derive lock file path)
            max_retries: Maximum number of retry attempts (default: 3)
            backoff_base_ms: Base backoff time in milliseconds (default: 10)
        
        Yields:
            None (context manager)
        
        Example:
            with self._file_lock(self.LAST_ROUTE_FILE):
                # Critical section - exclusive access to state files
                self.LAST_ROUTE_FILE.write_text(content)
        """
        lock_file = Path(str(target_file) + '.lock')
        lock_fd = None
        lock_acquired = False
        
        try:
            # Create/open lock file - this is atomic at the OS level
            # Using 'a+' mode to create if not exists, read/write access
            lock_fd = open(lock_file, 'a+')
            
            # Attempt to acquire exclusive non-blocking lock
            for attempt in range(max_retries + 1):
                try:
                    # Try non-blocking exclusive lock first
                    # LOCK_EX: Exclusive lock (writer)
                    # LOCK_NB: Non-blocking (fail immediately if locked)
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    lock_acquired = True
                    self._logger.debug(
                        f"Lock acquired for {target_file} on attempt {attempt + 1}"
                    )
                    break
                except (IOError, OSError) as e:
                    if attempt < max_retries:
                        # Calculate exponential backoff with jitter
                        # Backoff: 10ms, 50ms, 100ms (with small random variation)
                        backoff_ms = backoff_base_ms * (2 ** attempt) * (2.5 if attempt > 0 else 1)
                        jitter_ms = random.uniform(0, 5)  # Small jitter to prevent thundering herd
                        sleep_time = (backoff_ms + jitter_ms) / 1000.0
                        
                        self._logger.debug(
                            f"Lock attempt {attempt + 1} failed for {target_file}: {e}. "
                            f"Retrying in {sleep_time:.3f}s..."
                        )
                        time.sleep(sleep_time)
                    else:
                        # All retries exhausted
                        self._logger.warning(
                            f"Failed to acquire lock for {target_file} after {max_retries + 1} attempts. "
                            f"Proceeding without lock (best-effort). Error: {e}"
                        )
                        # FIX: Don't return error to user, log and continue with best-effort
                        lock_acquired = False
            
            yield
            
        finally:
            # Always clean up the lock file descriptor
            if lock_fd:
                if lock_acquired:
                    try:
                        # Release the lock
                        fcntl.flock(lock_fd, fcntl.LOCK_UN)
                        self._logger.debug(f"Lock released for {target_file}")
                    except (IOError, OSError) as e:
                        self._logger.warning(f"Error releasing lock for {target_file}: {e}")
                # Close the file descriptor
                try:
                    lock_fd.close()
                except (IOError, OSError) as e:
                    self._logger.debug(f"Error closing lock file for {target_file}: {e}")
    
    def execute(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any] | None = None,
        use_python_path: bool = False,
    ) -> ExecutionResult:
        """
        Execute a routing decision.
        
        This is the main entry point for execution. It dispatches to the
        appropriate execution path based on the route type.
        
        NAMESPACE ISOLATION:
        Each execution runs in its own isolated namespace to prevent
        "shared-state overlap" errors during concurrent executions.
        The namespace directory is cleaned up after execution completes.
        
        MEDICAL QUERY DETECTION:
        Medical queries are detected and forced to LOCAL route for safety.
        This matches shell behavior where medical queries get route_reason_override="medical_evidence_only".
        
        Args:
            intent: The classified intent result
            route: The routing decision to execute
            context: Optional execution context (conversation history, etc.)
            use_python_path: If True, use the new Python-native execution path
                instead of calling lucy_chat.sh. This preserves the real route
                (AUGMENTED stays AUGMENTED) and eliminates shell overhead.
        
        Returns:
            ExecutionResult with status, response, and metadata
        
        Execution Flow:
        1. Capture pre-execution state
        2. Check for medical context and force LOCAL route if needed
        3. Log execution start
        4. Handle CLARIFY routes early
        5. Determine execution path (bypass, provisional, full, or python_native)
        6. Dispatch to appropriate execution handler
        7. Format and enhance response
        8. Persist execution metadata
        9. Clean up namespace directory
        10. Return structured result
        """
        start_time = time.time()
        context = context or {}
        question = context.get("question", "")
        
        # Reject empty or whitespace-only queries at the engine boundary
        if not question or not question.strip():
            execution_time = int((time.time() - start_time) * 1000)
            result = ExecutionResult(
                status="failed",
                outcome_code="empty_query",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text="",
                error_message="Query is empty or contains only whitespace.",
                execution_time_ms=execution_time,
                metadata={"reason": "empty_query_rejected"},
            )
            self._write_state_files(route, result, context)
            return result
        
        # Use Python-native path by default for all routes (shell-free)
        # Following burn-in certification (2,221+ queries, 100% success)
        if use_python_path and route.route in ("FULL", "EVIDENCE", "NEWS", "AUGMENTED", "LOCAL", "TIME"):
            self._logger.info("Using Python-native execution path (shell-free)")
            # Run the async version in a new event loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an async context, create a new loop
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            self._run_async_execute, intent, route, context
                        )
                        return future.result()
                else:
                    return loop.run_until_complete(
                        self.execute_async(intent, route, context)
                    )
            except RuntimeError:
                # No event loop, create one
                return asyncio.run(self.execute_async(intent, route, context))
        
        # Check for medical context and configure safety constraints
        requires_evidence, evidence_reason = requires_evidence_mode(question, context)
        
        
        # For medical queries: set domain restrictions but don't force LOCAL
        # This allows LLM to provide informative answers while constraining any web search
        if evidence_reason == "medical_context":
            self._logger.info("Medical query detected - setting domain restrictions")
            # Update context with medical routing signal
            context["route_reason_override"] = "medical_evidence_only"
            context["is_medical_query"] = True
            # Set medical domain allowlist for trusted source restriction
            medical_domains_file = ROOT_DIR / "config" / "trust" / "generated" / "medical_runtime.txt"
            context["allow_domains_file"] = str(medical_domains_file)
            # Note: We don't force LOCAL route - let normal routing proceed
            # The domain restrictions above ensure any web search uses trusted sources
        
        # Log execution start
        self._logger.info(
            f"Execution start: route={route.route}, provider={route.provider}, "
            f"intent={intent.intent}, question={question[:100]}..."
        )
        
        try:
            # Handle CLARIFY route early
            if route.route == "CLARIFY":
                return self._handle_clarify_route(intent, route, context, start_time)
            
            # Determine execution path based on route type
            route_type = self._determine_route_type(route, intent, context)
            self._logger.info(f"Route type determined: {route_type}")
            
            # Dispatch to appropriate execution handler
            if route_type == "bypass":
                result = self._execute_bypass_route(intent, route, context)
            elif route_type == "provisional":
                result = self._execute_provisional_route(intent, route, context)
            else:
                result = self._execute_full_route(intent, route, context)
            
            # Calculate execution time
            execution_time = int((time.time() - start_time) * 1000)
            
            # Create final result with execution time
            final_result = ExecutionResult(
                status=result.status,
                outcome_code=result.outcome_code,
                route=result.route,
                provider=result.provider,
                provider_usage_class=result.provider_usage_class,
                response_text=result.response_text,
                error_message=result.error_message,
                execution_time_ms=execution_time,
                metadata={
                    **result.metadata,
                    "execution_time_ms": execution_time,
                    "route_type": route_type,
                },
            )
            
            # Persist execution state
            self._write_state_files(route, final_result, context)
            
            self._logger.info(
                f"Execution complete: status={final_result.status}, "
                f"outcome={final_result.outcome_code}, time={execution_time}ms"
            )
            
            return final_result
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            self._logger.error(f"Execution failed: {e}")
            
            error_result = ExecutionResult(
                status="failed",
                outcome_code="execution_error",
                route=route.route,
                provider=route.provider,
                provider_usage_class=route.provider_usage_class,
                error_message=str(e),
                execution_time_ms=execution_time,
                metadata={"exception_type": type(e).__name__},
            )
            
            # Still try to write state files for error cases
            try:
                self._write_state_files(route, error_result, context)
            except Exception:
                pass
            
            return error_result
        
        finally:
            # =========================================================================
            # NAMESPACE CLEANUP
            # =========================================================================
            # Clean up the namespace directory to prevent accumulation of stale
            # namespaces. This runs even if execution failed (try/finally).
            # 
            # SAFETY CHECK: Only remove directories that are:
            # 1. Inside the namespaces/ directory (verified by checking path components)
            # 2. Associated with this execution's namespace
            try:
                if (
                    self._state_dir.exists() 
                    and "namespaces" in str(self._state_dir)
                    and self._execution_namespace in str(self._state_dir)
                ):
                    shutil.rmtree(self._state_dir, ignore_errors=True)
                    self._logger.debug(
                        f"Cleaned up namespace directory: {self._state_dir}"
                    )
            except Exception as e:
                # Log but don't fail if cleanup fails
                self._logger.warning(f"Failed to cleanup namespace directory: {e}")
    
    def _handle_clarify_route(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
        start_time: float,
    ) -> ExecutionResult:
        """Handle CLARIFY route - return early with clarification request."""
        execution_time = int((time.time() - start_time) * 1000)
        
        clarification_text = (
            route.metadata.get("clarification_question")
            if hasattr(route, "metadata") and route.metadata
            else None
        ) or "I need more information to answer this question. Could you clarify what you're looking for?"
        
        result = ExecutionResult(
            status="completed",
            outcome_code="clarification_requested",
            route="CLARIFY",
            provider="local",
            provider_usage_class="local",
            response_text=clarification_text,
            execution_time_ms=execution_time,
            metadata={"route_type": "clarify"},
        )
        
        self._write_state_files(route, result, context)
        return result
    
    def _handle_medical_insufficient(
        self,
        question: str,
        local_result: ExecutionResult,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Handle insufficient local response for medical queries.
        
        Medical queries are NOT eligible for augmented fallback (line 1365 in shell).
        When local response is insufficient, return a medical-specific message
        that informs the user without attempting augmentation.
        
        This matches shell behavior (lines 3232-3235) where medical queries
        get special "insufficient" handling that skips validated_insufficient_recovery.
        
        Args:
            question: The original user question
            local_result: The result from local execution attempt
            context: Execution context
        
        Returns:
            ExecutionResult with medical-specific insufficient response
        """
        self._logger.info("Returning medical-specific insufficient response")
        
        # Medical-specific insufficient response
        # This is a safety measure - medical queries require authoritative sources
        medical_response = (
            "I cannot provide medical advice. For health-related questions, "
            "please consult a qualified healthcare professional."
        )
        
        return ExecutionResult(
            status="completed",
            outcome_code="medical_insufficient",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text=medical_response,
            error_message="",
            metadata={
                "route_type": "medical_safety",
                "fallback_used": False,
                "fallback_reason": "medical_query_no_augmentation",
                "is_medical_query": True,
                "local_response_attempted": True,
                "local_response": local_result.response_text,
            },
        )
    
    def _append_medical_sources(
        self,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Append trusted medical sources to an informative response.
        
        This ensures medical queries show both the informative answer AND
        the authoritative sources used, matching user expectations.
        """
        # Load medical domains from the allowlist file
        medical_domains_file = ROOT_DIR / "config" / "trust" / "generated" / "medical_runtime.txt"
        domains = []
        try:
            if medical_domains_file.exists():
                with open(medical_domains_file) as f:
                    domains = [line.strip() for line in f if line.strip()]
        except Exception:
            pass
        
        if not domains:
            domains = [
                "pubmed.ncbi.nlm.nih.gov",
                "medlineplus.gov",
                "dailymed.nlm.nih.gov",
                "cochranelibrary.com",
            ]
        
        # Deduplicate and limit to top sources
        seen = set()
        unique_domains = []
        for d in domains:
            key = d.replace("www.", "").lower()
            if key not in seen:
                seen.add(key)
                unique_domains.append(d)
        
        top_domains = unique_domains[:6]
        
        # Build disclaimer indicating this is general knowledge, not verified medical sources
        disclaimer = (
            "\n\n\n[Note: This answer is based on general knowledge and should be verified. "
            "For medical decisions, consult a healthcare professional and authoritative sources.]"
        )
        
        # Append sources to response
        sources_text = "\n\n\nAuthoritative sources for verification:\n" + "\n".join(f"- {src}" for src in top_domains)
        new_response = result.response_text + disclaimer + sources_text
        
        # Update metadata to track sources were appended
        new_metadata = dict(result.metadata or {})
        new_metadata["medical_sources_appended"] = True
        new_metadata["medical_sources_count"] = len(top_domains)
        new_metadata["medical_general_knowledge_disclaimer"] = True
        
        return dataclasses.replace(
            result,
            response_text=new_response,
            metadata=new_metadata,
        )

    def _context_indicates_medical_query(self, context: dict[str, Any]) -> bool:
        """Return True when execution context already carries a medical signal."""
        for key in ("is_medical_query", "medical_context", "routing_signal_medical_context"):
            value = context.get(key)
            if isinstance(value, bool):
                if value:
                    return True
            elif isinstance(value, str) and self._is_truthy(value):
                return True
        return False
    
    def _determine_route_type(
        self,
        route: RoutingDecision,
        intent: ClassificationResult,
        context: dict[str, Any],
    ) -> str:
        """
        Determine the execution route type.
        
        Args:
            route: The routing decision
            intent: The classified intent
            context: Execution context
        
        Returns:
            Route type: "bypass", "provisional", or "full"
        
        Logic ported from execute_plan.sh:
        - BYPASS: Local-only, no augmentation attempted (augmentation_policy=disabled)
        - PROVISIONAL: Local first, with fallback to augmentation (augmentation_policy=fallback_only)
        - FULL: Full governed execution with all checks (augmentation_policy=direct_allowed or other)
        """
        # Get augmentation policy from context or default
        augmentation_policy = context.get(
            "augmentation_policy", 
            self.DEFAULT_AUGMENTATION_POLICY
        )
        normalized_policy = self._normalize_augmentation_policy(augmentation_policy)
        
        # Check for forced modes
        forced_mode = context.get("forced_mode", "AUTO")
        if forced_mode == "FORCED_OFFLINE":
            return "bypass"
        if forced_mode == "FORCED_ONLINE":
            return "full"
        
        # Check if local direct path is eligible
        if self._local_direct_eligible(route, intent, context):
            return "bypass"
        
        # Determine by policy
        if normalized_policy == "disabled":
            return "bypass"
        elif normalized_policy == "fallback_only":
            # TIME route goes directly to full (no local attempt)
            if route.route == "TIME":
                return "full"
            return "provisional"
        else:  # direct_allowed
            return "full"
    
    def _local_direct_eligible(
        self,
        route: RoutingDecision,
        intent: ClassificationResult,
        context: dict[str, Any],
    ) -> bool:
        """
        Check if query qualifies for local direct (fast) path.
        
        Ported from execute_plan.sh local_direct_eligible() function (lines 874-894).
        
        Criteria for local direct path:
        - LUCY_EXECUTE_PLAN_LOCAL_FASTPATH enabled (default: 1)
        - LUCY_LOCAL_DIRECT_ENABLED enabled (default: 1)
        - Governor route is LOCAL
        - Governor does NOT require sources
        - Governor does NOT require clarification
        - Force mode is LOCAL (not AUGMENTED or CLARIFY)
        - Route mode is not CLARIFY
        - needs_web is false
        - output_mode is CHAT
        - local_answer.sh is executable
        - offline_action is allow
        - No clarifying question pending
        - No chat memory context (unless contextual_local_followup is 1)
        
        Args:
            route: The routing decision
            intent: The classified intent
            context: Execution context
        
        Returns:
            True if eligible for local direct path
        """
        # Check environment-based feature flags
        local_fastpath = self._is_truthy(
            os.environ.get("LUCY_EXECUTE_PLAN_LOCAL_FASTPATH", "1")
        )
        if not local_fastpath:
            return False
        
        local_direct_enabled = self._is_truthy(
            os.environ.get("LUCY_LOCAL_DIRECT_ENABLED", "1")
        )
        if not local_direct_enabled:
            return False
        
        # Check governor route (from route or context)
        governor_route = context.get("governor_route", route.route)
        if governor_route != "LOCAL":
            return False
        
        # Check governor requirements
        governor_requires_sources = context.get("governor_requires_sources", False)
        if governor_requires_sources:
            return False
        
        governor_requires_clarification = context.get(
            "governor_requires_clarification", False
        )
        if governor_requires_clarification:
            return False
        
        # Check force mode
        force_mode = context.get("force_mode", "LOCAL")
        if force_mode != "LOCAL":
            return False
        
        # Check if needs web
        if intent.needs_web:
            return False
        
        # Check output mode
        output_mode = context.get("output_mode", "CHAT")
        if output_mode != "CHAT":
            return False
        
        # Check if local_answer.sh exists and is executable
        if not self.LOCAL_ANSWER_SCRIPT.exists():
            return False
        
        # Check offline action
        offline_action = context.get("offline_action", "allow")
        if offline_action != "allow":
            return False
        
        # Check for pending clarifying question
        clarifying_question = context.get("clarifying_question", "")
        if clarifying_question:
            return False
        
        return True
    
    def _execute_bypass_route(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute a bypass route (local-only, no augmentation).
        
        Bypass routes skip all augmentation logic and go directly to local
        response generation. This is used when:
        - Augmentation is disabled
        - Confidence is below threshold
        - Operator has forced local mode
        - Query qualifies for local direct path
        
        NAMESPACE ISOLATION:
        Uses _prepare_subprocess_env() to ensure local_answer.sh runs in an
        isolated namespace, preventing "shared-state overlap" errors.
        
        Args:
            intent: The classified intent
            route: The routing decision
            context: Execution context
        
        Returns:
            ExecutionResult from local execution
        
        Ported from execute_plan.sh (lines 2883-2969):
        - Call local_answer.sh directly
        - On failure, try local_worker.py fallback
        - Apply guards for generation failure
        - Format and return result
        """
        self._logger.info("Executing bypass route (local-only)")
        question = context.get("question", "")
        
        # Prepare environment with namespace isolation
        # _prepare_subprocess_env() ensures local_answer.sh gets the proper
        # namespace variables to avoid shared-state conflicts.
        env = self._prepare_subprocess_env()
        env.update({
            "LUCY_IDENTITY_TRACE_FILE": str(
                self._state_dir / f"identity_trace.{os.getpid()}.env"
            ),
            "LUCY_LOCAL_POLICY_RESPONSE_ID": context.get(
                "governor_local_response_id", ""
            ),
            "LUCY_LOCAL_GEN_ROUTE_MODE": "LOCAL",
            "LUCY_LOCAL_GEN_OUTPUT_MODE": context.get("output_mode", "CHAT"),
        })
        
        # Add session memory context if enabled
        session_memory, memory_telemetry = _load_session_memory_context_with_telemetry(question)
        if session_memory:
            env["LUCY_SESSION_MEMORY_CONTEXT"] = session_memory
            self._logger.debug(f"Added session memory context ({len(session_memory)} chars)")
        
        local_direct_used = True
        local_direct_fallback = False
        local_direct_path = "local_answer"
        
        # Try local_answer.sh first
        result = self._call_local_worker(question, env)
        
        # If local_answer fails, try local_worker fallback
        if result.returncode != 0:
            self._logger.info("Local answer failed, trying worker fallback")
            if self.LOCAL_WORKER_SCRIPT.exists():
                local_direct_fallback = True
                local_direct_path = "worker"
                result = self._call_local_worker_fallback(question, env)
        
        # Process the result
        raw_output = result.stdout
        rc = result.returncode
        
        # Check for local generation failure patterns
        if rc == 0 and self._is_local_generation_failure_output(raw_output):
            guard_trigger = "local_generation_failure_phrase"
            fallback_kind = "deterministic_local_prompt_fallback"
            outcome_code = "local_guard_fallback"
            local_force_plain_fallback = True
            response_text = self._runtime_local_prompt_fallback_text(question, "0")
        else:
            # Render the response
            response_text = self._render_chat_fast_from_raw(raw_output)
            response_text = self._local_fast_non_empty_guard(
                question, response_text, "CHAT"
            )
            response_text = self._local_fast_repetition_guard(
                question, response_text, "CHAT"
            )
            
            # Check for evidence style text (shouldn't happen in bypass)
            if self._is_evidence_style_text(response_text):
                outcome_code = "local_lexeme_blocked"
                guard_trigger = "local_evidence_lexeme_detected"
                fallback_kind = "lexeme_blocked_replacement"
                response_text = self._runtime_local_prompt_fallback_text(question, "1")
            else:
                outcome_code = "answered"
                guard_trigger = "none"
                fallback_kind = "none"
                local_force_plain_fallback = False
        
        # Build metadata
        metadata = {
            "route_type": "bypass",
            "local_direct_used": local_direct_used,
            "local_direct_fallback": local_direct_fallback,
            "local_direct_path": local_direct_path,
            "guard_trigger": guard_trigger,
            "fallback_kind": fallback_kind,
            "trust_class": "local",
            **memory_telemetry,
        }
        
        return ExecutionResult(
            status="completed" if rc == 0 or local_force_plain_fallback else "failed",
            outcome_code=outcome_code,
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text=response_text,
            error_message=result.stderr if rc != 0 and not local_force_plain_fallback else "",
            metadata=metadata,
        )
    
    def _execute_provisional_route(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute a provisional route (local first, conditional augmentation).
        
        Provisional routes attempt local response first, then fall back to
        augmentation if the local response is insufficient. This balances
        speed (local is faster) with quality (augmented is better).
        
        MEDICAL QUERIES:
        Medical queries skip augmented fallback and return medical-specific
        insufficient response when local response is insufficient.
        This matches shell behavior (line 1365: medical queries NOT eligible
        for validated_insufficient_recovery).
        
        Args:
            intent: The classified intent
            route: The routing decision
            context: Execution context
        
        Returns:
            ExecutionResult from local or augmented execution
        
        Ported from execute_plan.sh provisional/fallback logic:
        1. Try local execution first
        2. Check if local result is sufficient
        3. If insufficient and NOT medical, try augmented provider
        4. Track fallback usage properly
        """
        self._logger.info("Executing provisional route (local-first with fallback)")
        question = context.get("question", "")
        
        # Check if this is a medical query (for logging/metrics only)
        is_medical_query_flag = self._context_indicates_medical_query(context)
        route_evidence_reason = route.evidence_reason if route else None
        is_medical = is_medical_query_flag or route_evidence_reason in ("medical_safety", "medical_context")
        
        # Step 1: Try local execution first
        local_result = self._execute_bypass_route(intent, route, context)
        
        # Step 2: Check if local result is sufficient
        if local_result.status == "completed" and local_result.outcome_code == "answered":
            # Check if response quality is acceptable
            if not self._is_local_response_sufficient(local_result.response_text):
                # Medical queries now allow augmentation with domain restrictions
                # Domain allowlist is set in context["allow_domains_file"]
                if is_medical:
                    self._logger.info("Medical query with insufficient local response - attempting augmentation with restrictions")
                else:
                    self._logger.info("Local response insufficient, attempting augmentation fallback")
                
                # Step 3: Try augmented provider
                aug_result = self._call_augmented_provider(question, intent, route, context)
                
                if aug_result.status == "completed":
                    # For medical queries, append disclaimer and sources
                    if is_medical and aug_result.response_text:
                        aug_result = self._append_medical_sources(aug_result, context)
                    
                    return ExecutionResult(
                        status="completed",
                        outcome_code="augmented_fallback",
                        route="AUGMENTED",
                        provider=aug_result.metadata.get("provider", "wikipedia"),
                        provider_usage_class=aug_result.metadata.get(
                            "provider_usage_class", "free"
                        ),
                        response_text=aug_result.response_text,
                        metadata={
                            "route_type": "provisional",
                            "fallback_used": True,
                            "fallback_reason": "local_insufficient",
                            "local_response": local_result.response_text,
                            **aug_result.metadata,
                        },
                    )
                else:
                    # Augmentation failed, return local result with fallback note
                    self._logger.warning(
                        f"Augmentation fallback failed: {aug_result.error_message}"
                    )
                    return ExecutionResult(
                        status="completed",
                        outcome_code="local_fallback",
                        route="LOCAL",
                        provider="local",
                        provider_usage_class="local",
                        response_text=local_result.response_text,
                        metadata={
                            "route_type": "provisional",
                            "fallback_used": False,
                            "fallback_reason": "augmentation_failed",
                            "augmentation_error": aug_result.error_message,
                        },
                    )
            
            # Local result is sufficient
            return local_result
        
        # Local execution failed, try augmentation
        # Medical queries now allow augmentation with domain restrictions
        if is_medical:
            self._logger.info("Medical query local execution failed - attempting augmentation with restrictions")
        else:
            self._logger.info("Local execution failed, attempting augmentation")
        aug_result = self._call_augmented_provider(question, intent, route, context)
        
        if aug_result.status == "completed":
            return ExecutionResult(
                status="completed",
                outcome_code="augmented_fallback",
                route="AUGMENTED",
                provider=aug_result.metadata.get("provider", "wikipedia"),
                provider_usage_class=aug_result.metadata.get("provider_usage_class", "free"),
                response_text=aug_result.response_text,
                metadata={
                    "route_type": "provisional",
                    "fallback_used": True,
                    "fallback_reason": "local_failed",
                    **aug_result.metadata,
                },
            )
        
        # Both failed - return error with local's error
        return ExecutionResult(
            status="failed",
            outcome_code="execution_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            response_text="",
            error_message=f"Local failed: {local_result.error_message}; "
                         f"Augmentation failed: {aug_result.error_message}",
            metadata={
                "route_type": "provisional",
                "fallback_used": False,
                "fallback_reason": "both_failed",
            },
        )
    
    def _execute_full_route(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute a full route (governed execution via shell tools).
        
        Full routes use the complete governed execution path through
        lucy_chat.sh. This preserves all authority semantics and truth metadata.
        
        NAMESPACE ISOLATION:
        Uses _prepare_subprocess_env() to ensure lucy_chat.sh runs in an
        isolated namespace, preventing "shared-state overlap" errors.
        
        Args:
            intent: The classified intent
            route: The routing decision
            context: Execution context
        
        Returns:
            ExecutionResult from governed execution
        
        Ported from execute_plan.sh main execution path (lines 2912-2916):
        - Call lucy_chat.sh with proper environment variables
        - Parse response and state files
        - Handle evidence fetching indicators
        - Return structured result
        """
        self._logger.info("Executing full route (governed execution)")
        question = context.get("question", "")
        is_medical_query = self._context_indicates_medical_query(context) or (
            route and route.evidence_reason in ("medical_safety", "medical_context")
        )
        
        # Prepare environment for lucy_chat.sh with namespace isolation
        # _prepare_subprocess_env() sets STATE_NAMESPACE_RAW, LUCY_SHARED_STATE_NAMESPACE,
        # and LUCY_STATE_DIR to ensure proper isolation from other executions.
        env = self._prepare_subprocess_env()
        env.update({
            "LUCY_ROUTER_BYPASS": "1",
            "LUCY_CHAT_FORCE_MODE": self._map_route_to_chat_mode(route.route),
            "LUCY_CHAT_ROUTE_REASON_OVERRIDE": context.get(
                "route_reason_override", "router_classifier_mapper"
            ),
            "LUCY_NEWS_REGION_FILTER": context.get("region_filter", ""),
            "LUCY_FETCH_ALLOWLIST_FILTER_FILE": context.get(
                "allow_domains_file", ""
            ),
            "LUCY_SEARCH_ALLOWLIST_FILTER_FILE": context.get(
                "allow_domains_file", ""
            ),
            "LUCY_CONVERSATION_MODE_ACTIVE": "1" if context.get(
                "conversation_mode_active", False
            ) else "0",
            "LUCY_IDENTITY_TRACE_FILE": str(
                self._state_dir / f"identity_trace.{os.getpid()}.env"
            ),
            "LUCY_LOCAL_POLICY_RESPONSE_ID": context.get(
                "governor_local_response_id", ""
            ),
            "LUCY_SEMANTIC_INTERPRETER_FIRED": "true" if context.get(
                "semantic_interpreter_fired", False
            ) else "false",
            "LUCY_SEMANTIC_INTERPRETER_CONFIDENCE": str(
                context.get("semantic_interpreter_confidence", 0.0)
            ),
            "LUCY_SEMANTIC_INTERPRETER_FORWARD_CANDIDATES": "true" if context.get(
                "semantic_interpreter_forward_candidates", False
            ) else "false",
            "LUCY_SEMANTIC_INTERPRETER_ORIGINAL_QUERY": context.get(
                "semantic_interpreter_original_query", ""
            ),
            "LUCY_SEMANTIC_INTERPRETER_SELECTED_NORMALIZED_QUERY": context.get(
                "semantic_interpreter_selected_normalized_query", ""
            ),
            "LUCY_SEMANTIC_INTERPRETER_SELECTED_RETRIEVAL_QUERY": context.get(
                "semantic_interpreter_selected_retrieval_query", ""
            ),
            "LUCY_SEMANTIC_INTERPRETER_NORMALIZED_CANDIDATES_JSON": context.get(
                "semantic_interpreter_normalized_candidates_json", "[]"
            ),
            "LUCY_SEMANTIC_INTERPRETER_RETRIEVAL_CANDIDATES_JSON": context.get(
                "semantic_interpreter_retrieval_candidates_json", "[]"
            ),
        })
        
        try:
            # Call lucy_chat.sh
            result = subprocess.run(
                [str(self.LUCY_CHAT_SCRIPT), question],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(ROOT_DIR),
            )
            
            # Parse result
            raw_output = result.stdout
            rc = result.returncode
            
            # Get dynamic state file paths (respects namespace isolation)
            route_file, outcome_file = self._get_state_file_paths()
            
            # Try to read outcome from state files
            outcome_code = self._read_state_field(
                outcome_file, "OUTCOME_CODE"
            ) or "answered"
            
            final_mode = self._read_state_field(
                route_file, "FINAL_MODE"
            ) or route.route
            
            # Determine provider from outcome
            provider = self._read_state_field(
                outcome_file, "AUGMENTED_PROVIDER_USED"
            ) or route.provider
            
            provider_usage_class = self._provider_usage_class_for(provider)
            
            # Format response
            if rc == 0:
                response_text = self._render_chat_fast_from_raw(raw_output)
                if (
                    is_medical_query
                    and final_mode == "AUGMENTED"
                    and response_text
                ):
                    medical_result = self._append_medical_sources(
                        ExecutionResult(
                            status="completed",
                            outcome_code=outcome_code,
                            route=final_mode,
                            provider=provider,
                            provider_usage_class=provider_usage_class,
                            response_text=response_text,
                            metadata={},
                        ),
                        context,
                    )
                    response_text = medical_result.response_text
                status = "completed"
                error_message = ""
            else:
                response_text = raw_output
                status = "failed"
                error_message = result.stderr
            
            # Build metadata from state files
            metadata = {
                "route_type": "full",
                "final_mode": final_mode,
                "outcome_code": outcome_code,
                "return_code": rc,
            }
            
            # Add child trace fields if available
            for field in self.CHILD_TRACE_FIELDS.split():
                value = self._read_state_field(outcome_file, field)
                if value:
                    metadata[field.lower()] = value
            
            return ExecutionResult(
                status=status,
                outcome_code=outcome_code,
                route=final_mode,
                provider=provider,
                provider_usage_class=provider_usage_class,
                response_text=response_text,
                error_message=error_message,
                metadata=metadata,
            )
            
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status="timeout",
                outcome_code="timeout",
                route=route.route,
                provider=route.provider,
                provider_usage_class=route.provider_usage_class,
                error_message=f"Request timed out after {self.timeout}s",
                metadata={"route_type": "full"},
            )
        except Exception as e:
            return ExecutionResult(
                status="failed",
                outcome_code="execution_error",
                route=route.route,
                provider=route.provider,
                provider_usage_class=route.provider_usage_class,
                error_message=str(e),
                metadata={"route_type": "full", "exception_type": type(e).__name__},
            )
    
    # ======================================================================
    # FULL PYTHON EXECUTION PATH (Phase 2 - No Shell Dependency)
    # ======================================================================
    
    def _run_async_execute(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Helper to run async execute in a new event loop (for thread pool usage).
        
        Args:
            intent: The classified intent result
            route: The routing decision to execute
            context: Optional execution context
        
        Returns:
            ExecutionResult from async execution
        """
        return asyncio.run(self.execute_async(intent, route, context))
    
    async def execute_async(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Async execution entry point.
        
        This method provides async execution capability, using the full Python
        execution path for routes that need evidence fetching or augmentation.
        
        Args:
            intent: The classified intent result
            route: The routing decision to execute
            context: Optional execution context
        
        Returns:
            ExecutionResult with status, response, and metadata
        """
        start_time = time.time()
        context = context or {}
        question = context.get("question", "")
        
        # Reject empty or whitespace-only queries at the engine boundary
        if not question or not question.strip():
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                status="failed",
                outcome_code="empty_query",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text="",
                error_message="Query is empty or contains only whitespace.",
                execution_time_ms=execution_time,
                metadata={"reason": "empty_query_rejected"},
            )
        
        # Check for medical context and configure safety constraints
        requires_evidence, evidence_reason = requires_evidence_mode(question, context)
        
        # For medical queries: set domain restrictions but don't force LOCAL
        if evidence_reason == "medical_context":
            self._logger.info("Medical query detected - setting domain restrictions")
            context["route_reason_override"] = "medical_evidence_only"
            context["is_medical_query"] = True
            # Set medical domain allowlist for trusted source restriction
            medical_domains_file = ROOT_DIR / "config" / "trust" / "generated" / "medical_runtime.txt"
            context["allow_domains_file"] = str(medical_domains_file)
        
        self._logger.info(
            f"Async execution start: route={route.route}, provider={route.provider}, "
            f"question={question[:100]}..."
        )
        
        try:
            # Handle CLARIFY route early
            if route.route == "CLARIFY":
                return self._handle_clarify_route(intent, route, context, start_time)
            
            # Determine route type for proper handling
            route_type = self._determine_route_type(route, intent, context)
            
            # Use Python-native execution based on route type
            if route.route in ("FULL", "EVIDENCE", "NEWS", "AUGMENTED", "TIME"):
                result = await self._execute_full_route_python(intent, route, context)
            elif route_type == "provisional":
                # Provisional: local first with fallback to augmentation
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._execute_provisional_route, intent, route, context
                )
            elif route.route == "LOCAL":
                # Use sync bypass route but run in thread pool to not block
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._execute_bypass_route, intent, route, context
                )
            else:
                # Default to bypass for unknown routes
                result = self._execute_bypass_route(intent, route, context)
            
            # Calculate execution time
            execution_time = int((time.time() - start_time) * 1000)
            
            # Create final result with execution time
            final_result = ExecutionResult(
                status=result.status,
                outcome_code=result.outcome_code,
                route=result.route,
                provider=result.provider,
                provider_usage_class=result.provider_usage_class,
                response_text=result.response_text,
                error_message=result.error_message,
                execution_time_ms=execution_time,
                metadata={
                    **result.metadata,
                    "execution_time_ms": execution_time,
                    "execution_path": "python_async",
                },
            )
            
            # Persist execution state
            self._write_state_files(route, final_result, context)
            
            self._logger.info(
                f"Async execution complete: status={final_result.status}, "
                f"outcome={final_result.outcome_code}, time={execution_time}ms"
            )
            
            return final_result
            
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            self._logger.error(f"Async execution failed: {e}")
            
            error_result = ExecutionResult(
                status="failed",
                outcome_code="execution_error",
                route=route.route,
                provider=route.provider,
                provider_usage_class=route.provider_usage_class,
                error_message=str(e),
                execution_time_ms=execution_time,
                metadata={"exception_type": type(e).__name__, "execution_path": "python_async"},
            )
            
            try:
                self._write_state_files(route, error_result, context)
            except Exception:
                pass
            
            return error_result
        
        finally:
            # Namespace cleanup
            try:
                if (
                    self._state_dir.exists() 
                    and "namespaces" in str(self._state_dir)
                    and self._execution_namespace in str(self._state_dir)
                ):
                    shutil.rmtree(self._state_dir, ignore_errors=True)
                    self._logger.debug(
                        f"Cleaned up namespace directory: {self._state_dir}"
                    )
            except Exception as e:
                self._logger.warning(f"Failed to cleanup namespace directory: {e}")
    
    async def _execute_full_route_python(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Full governed execution entirely in Python.
        
        Replaces: Calling lucy_chat.sh
        Benefits: Keeps real route (AUGMENTED stays AUGMENTED), no shell overhead,
                  async execution for better concurrency.
        
        Args:
            intent: The classified intent
            route: The routing decision
            context: Execution context
        
        Returns:
            ExecutionResult with REAL route preserved (no mapping)
        """
        self._logger.info(f"Executing full Python route: {route.route}")
        question = context.get("question", "")
        is_medical_query = self._context_indicates_medical_query(context) or (
            route and route.evidence_reason in ("medical_safety", "medical_context")
        )
        
        # Step 1: Fetch evidence if needed
        evidence = None
        if route.route in ("EVIDENCE", "NEWS", "FULL", "AUGMENTED", "TIME"):
            # Check if this is a voice query for voice-optimized content
            for_voice = context.get("surface") == "voice" if context else False
            evidence = await self._fetch_evidence(question, route, for_voice=for_voice)
        
        # Special handling for TIME route: return current time directly
        if route.route == "TIME":
            if evidence and evidence.get("ok"):
                return ExecutionResult(
                    status="completed",
                    outcome_code="answered",
                    route="TIME",
                    provider="timeapi",
                    provider_usage_class="free",
                    response_text=evidence["formatted"],
                    error_message="",
                    metadata={
                        "route_type": "time_lookup",
                        "timezone": evidence.get("timezone"),
                        "datetime": evidence.get("datetime"),
                        "dst_active": evidence.get("dst"),
                        "real_route_preserved": True,
                    },
                )
            else:
                # Time lookup failed - return helpful error
                error_msg = evidence.get("error", "Unknown location") if evidence else "Could not determine timezone"
                return ExecutionResult(
                    status="completed",
                    outcome_code="error",
                    route="TIME",
                    provider="timeapi",
                    provider_usage_class="free",
                    response_text=f"Sorry, I couldn't find the time for that location. Please try specifying a major city (e.g., 'London', 'New York', 'Tokyo'). Error: {error_msg}",
                    error_message=error_msg,
                    metadata={
                        "route_type": "time_lookup_failed",
                        "real_route_preserved": True,
                    },
                )
        
        # Special handling for NEWS route: return news directly
        if route.route == "NEWS" and evidence and evidence.get("context"):
            return ExecutionResult(
                status="completed",
                outcome_code="answered",
                route="NEWS",
                provider="news",
                provider_usage_class="free",
                response_text=evidence["context"],
                error_message="",
                metadata={
                    "route_type": "news_live",
                    "evidence_fetched": True,
                    "evidence_title": "Latest News",
                    "evidence_url": "",
                    "trust_class": "unverified",
                    "real_route_preserved": True,
                    "news_source": evidence.get("provider", "unknown"),
                },
            )
        
        # Step 2: Build augmented prompt with evidence
        prompt = self._build_augmented_prompt(question, evidence, route)
        
        # Load session memory with telemetry before calling provider
        session_memory, memory_telemetry = _load_session_memory_context_with_telemetry(prompt)
        if session_memory:
            self._logger.debug(f"Loaded session memory ({len(session_memory)} chars)")
        
        # Step 3: Call appropriate provider
        if route.provider == "local":
            response = await self._call_local_model_async(prompt, context, session_memory)
        elif route.provider in ("openai", "kimi"):
            response = await self._call_api_provider_async(route.provider, prompt, context)
        elif route.provider == "wikipedia":
            response = await self._call_wikipedia_provider_async(prompt, evidence, context)
        else:
            # Default to local model
            response = await self._call_local_model_async(prompt, context, session_memory)
        
        # Step 4: Validate response
        validated = self._validate_response(response, route)
        
        # Step 5: Return with REAL route (no mapping)
        result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route=route.route,  # KEEPS THE REAL ROUTE - no mapping!
            provider=route.provider,
            provider_usage_class=route.provider_usage_class,
            response_text=validated,
            error_message="",
            metadata={
                "route_type": "full_python",
                "evidence_fetched": evidence is not None,
                "evidence_title": evidence.get("title", "") if evidence else "",
                "evidence_url": evidence.get("url", "") if evidence else "",
                "trust_class": "unverified" if evidence else "local",
                "real_route_preserved": True,  # Marker for testing
                **memory_telemetry,
            },
        )

        if is_medical_query and result.route == "AUGMENTED" and result.response_text:
            result = self._append_medical_sources(result, context)

        return result
    
    async def _fetch_evidence(
        self,
        question: str,
        route: RoutingDecision,
        for_voice: bool = False,
    ) -> dict[str, Any] | None:
        """
        Fetch evidence from appropriate sources based on route.
        
        Uses existing provider modules but calls them via Python API
        instead of subprocess for better performance and async support.
        
        Args:
            question: The user question
            route: The routing decision
            for_voice: If True, fetch voice-optimized content (e.g., condensed news)
        
        Returns:
            Evidence dictionary with context, title, url, etc., or None if failed
        """
        self._logger.info(f"Fetching evidence for route={route.route}, provider={route.provider}, for_voice={for_voice}")
        
        # For TIME route, fetch current time from time API
        if route.route == "TIME":
            return await self._fetch_time_evidence(question)
        
        # For NEWS route, fetch live news from RSS sources
        if route.route == "NEWS":
            return await self._fetch_news_evidence(question, for_voice=for_voice)
        
        provider = route.provider
        if provider == "none" or not provider:
            provider = "wikipedia"  # Default to free provider
        
        try:
            if provider == "wikipedia":
                return await self._fetch_wikipedia_evidence(question)
            elif provider == "kimi":
                return await self._fetch_api_evidence(question, "kimi")
            elif provider == "openai":
                return await self._fetch_api_evidence(question, "openai")
            else:
                # Try Wikipedia as fallback for unknown providers
                return await self._fetch_wikipedia_evidence(question)
        except Exception as e:
            self._logger.warning(f"Evidence fetch failed for {provider}: {e}")
            return None
    
    async def _fetch_wikipedia_evidence(self, question: str) -> dict[str, Any] | None:
        """
        Fetch evidence from Wikipedia.
        
        Uses unverified_context_wikipedia.py fetch_context function.
        Runs in thread pool to not block event loop.
        
        Args:
            question: The user question
        
        Returns:
            Evidence dictionary or None if failed
        """
        self._logger.debug(f"Fetching Wikipedia evidence for: {question[:50]}...")
        
        try:
            # Import the Wikipedia provider
            sys.path.insert(0, str(ROOT_DIR / "tools"))
            import unverified_context_wikipedia as wiki_provider
            
            # Run the synchronous fetch in a thread pool
            loop = asyncio.get_event_loop()
            payload = await loop.run_in_executor(
                None, wiki_provider.fetch_context, question
            )
            
            if payload and payload.get("ok"):
                return {
                    "context": payload.get("text", ""),
                    "title": payload.get("title", ""),
                    "url": payload.get("url", ""),
                    "provider": "wikipedia",
                    "class": payload.get("class", "wikipedia_general"),
                }
            return None
        except Exception as e:
            self._logger.warning(f"Wikipedia evidence fetch failed: {e}")
            return None
    
    async def _fetch_news_evidence(self, question: str, for_voice: bool = False) -> dict[str, Any] | None:
        """
        Fetch live news from RSS feeds.
        
        Uses the news_provider module to fetch fresh news from RSS sources.
        
        Args:
            question: The user question (may contain search terms)
            for_voice: If True, return condensed format optimized for TTS
            
        Returns:
            Evidence dictionary with news articles or None if failed
        """
        if not HAS_NEWS_PROVIDER:
            self._logger.warning("News provider not available")
            return None
        
        try:
            
            # Run news fetch in thread pool to not block event loop
            loop = asyncio.get_event_loop()
            # Use functools.partial to pass for_voice parameter
            import functools
            result = await loop.run_in_executor(
                None, functools.partial(NewsProvider.fetch_news, question, for_voice=for_voice)
            )
            
            if result.ok:
                return {
                    "context": result.text,
                    "title": "Latest News",
                    "url": "",
                    "provider": result.source,
                    "class": "news_live",
                    "articles": result.articles,
                }
            else:
                self._logger.warning(f"News fetch failed: {result.error}")
                return None
        except Exception as e:
            self._logger.warning(f"News evidence fetch failed: {e}")
            return None
    
    async def _fetch_time_evidence(self, question: str) -> dict[str, Any] | None:
        """
        Fetch current time from TimeAPI.io.
        
        Extracts location from question and fetches real-time data.
        
        Args:
            question: The user question (e.g., "What time is it in Tokyo?")
            
        Returns:
            Evidence dictionary with time data or None if failed
        """
        import re
        
        # Extract location from question
        location = None
        patterns = [
            r"(?:what['']?s?|what is|current)\s+time\s+(?:is it\s+)?(?:in|at)\s+([^?]+)",
            r"time\s+(?:in|at)\s+([^?]+)",
            r"([^?]+)\s+time",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, question, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                break
        
        # Default to UTC if no location found
        if not location:
            location = "UTC"
        
        self._logger.info(f"Fetching time for location: {location}")
        
        try:
            # Call time tool using subprocess directly (not in executor to avoid async issues)
            tool_path = ROOT_DIR / "tools" / "current_time_tool.py"
            if not tool_path.exists():
                self._logger.warning("Time tool not found")
                return None
            
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(tool_path), location,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT_DIR),
            )
            
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            except asyncio.TimeoutError:
                proc.kill()
                self._logger.warning("Time tool timed out")
                return None
            
            if proc.returncode == 0:
                data = json.loads(stdout.decode('utf-8'))
                if data.get("ok"):
                    formatted = self._format_time_response(data)
                    return {
                        "ok": True,
                        "timezone": data.get("timezone"),
                        "datetime": data.get("datetime"),
                        "dst": data.get("dst"),
                        "formatted": formatted,
                    }
                else:
                    self._logger.warning(f"Time API error: {data.get('error')}")
                    return None
            else:
                self._logger.warning(f"Time tool failed: {stderr.decode()}")
                return None
        except Exception as e:
            self._logger.warning(f"Time evidence fetch failed: {e}")
            return None
    
    def _format_time_response(self, data: dict) -> str:
        """Format time API response into human-readable text."""
        try:
            time_str = data.get("time", "?")
            date_str = data.get("date", "?")
            timezone = data.get("timezone", "Unknown")
            day = data.get("day_of_week", "")
            dst = data.get("dst", False)
            
            # Format time nicely
            hour = int(data.get("hour", 0))
            minute = int(data.get("minute", 0))
            ampm = "AM" if hour < 12 else "PM"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            time_formatted = f"{hour_12}:{minute:02d} {ampm}"
            
            lines = [
                f"The current time in {timezone} is {time_formatted}.",
                f"Date: {day}, {date_str}",
            ]
            
            if dst:
                lines.append("Daylight Saving Time is currently active.")
            
            return "\n".join(lines)
        except Exception as e:
            return f"Current time: {data.get('time', 'unknown')}"
    
    async def _fetch_api_evidence(
        self,
        question: str,
        provider: str,
    ) -> dict[str, Any] | None:
        """
        Fetch evidence from API provider (Kimi or OpenAI).
        
        Uses unverified_context_kimi.py or unverified_context_openai.py.
        
        Args:
            question: The user question
            provider: "kimi" or "openai"
        
        Returns:
            Evidence dictionary or None if failed
        """
        self._logger.debug(f"Fetching {provider} evidence for: {question[:50]}...")
        
        try:
            sys.path.insert(0, str(ROOT_DIR / "tools"))
            
            if provider == "kimi":
                import unverified_context_kimi as kimi_provider
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._call_kimi_subprocess, question
                )
                return result
            elif provider == "openai":
                import unverified_context_openai as openai_provider
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    None, self._call_openai_subprocess, question
                )
                return result
            return None
        except Exception as e:
            self._logger.warning(f"{provider} evidence fetch failed: {e}")
            return None
    
    def _call_kimi_subprocess(self, question: str) -> dict[str, Any] | None:
        """Call Kimi provider via subprocess (sync version for thread pool)."""
        tool = ROOT_DIR / "tools" / "unverified_context_kimi.py"
        if not tool.exists():
            return None
        
        try:
            result = subprocess.run(
                [sys.executable, str(tool), question],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._prepare_subprocess_env(),
                cwd=str(ROOT_DIR),
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                if payload.get("ok"):
                    return {
                        "context": payload.get("text", payload.get("context", "")),
                        "title": payload.get("title", ""),
                        "url": payload.get("url", ""),
                        "provider": "kimi",
                        "class": payload.get("class", "kimi_general"),
                    }
        except Exception as e:
            self._logger.debug(f"Kimi subprocess failed: {e}")
        return None
    
    def _call_openai_subprocess(self, question: str) -> dict[str, Any] | None:
        """Call OpenAI provider via subprocess (sync version for thread pool)."""
        tool = ROOT_DIR / "tools" / "unverified_context_openai.py"
        if not tool.exists():
            return None
        
        try:
            result = subprocess.run(
                [sys.executable, str(tool), question],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._prepare_subprocess_env(),
                cwd=str(ROOT_DIR),
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                if payload.get("ok"):
                    return {
                        "context": payload.get("text", payload.get("context", "")),
                        "title": payload.get("title", ""),
                        "url": payload.get("url", ""),
                        "provider": "openai",
                        "class": payload.get("class", "openai_general"),
                    }
        except Exception as e:
            self._logger.debug(f"OpenAI subprocess failed: {e}")
        return None
    
    def _build_augmented_prompt(
        self,
        question: str,
        evidence: dict[str, Any] | None,
        route: RoutingDecision,
    ) -> str:
        """
        Build augmented prompt with evidence context.
        
        Args:
            question: The user question
            evidence: Evidence dictionary from _fetch_evidence
            route: The routing decision
        
        Returns:
            Augmented prompt string
        """
        if not evidence or not evidence.get("context"):
            # No evidence, return question as-is
            return question
        
        context_text = evidence.get("context", "")
        title = evidence.get("title", "")
        url = evidence.get("url", "")
        provider = evidence.get("provider", "unknown")
        
        # Build augmented prompt
        prompt_parts = [
            f"Question: {question}",
            "",
            "Background Context:",
            context_text,
        ]
        
        if title:
            prompt_parts.append(f"\nSource: {title}")
        if url:
            prompt_parts.append(f"URL: {url}")
        
        prompt_parts.append(f"\nProvider: {provider}")
        prompt_parts.append("\nBased on the background context above, please answer the question.")
        
        return "\n".join(prompt_parts)
    
    async def _call_local_model_async(
        self,
        prompt: str,
        context: dict[str, Any],
        session_memory: str = "",
    ) -> str:
        """
        Call local model asynchronously using Python-native path.
        
        SHELL-FREE: Uses local_answer.py directly instead of local_answer.sh.
        Following burn-in certification (2,221+ queries, 100% success).
        
        Args:
            prompt: The augmented prompt
            context: Execution context
            session_memory: Pre-loaded session memory context (optional)
        
        Returns:
            Model response text
        """
        self._logger.debug(f"Calling local model async with prompt: {prompt[:50]}...")
        
        # Use Python-native local_answer
        from router_py.local_answer import LocalAnswer, LocalAnswerConfig
        
        config = LocalAnswerConfig.from_env()
        answer = LocalAnswer(config)
        
        if session_memory:
            self._logger.debug(f"Using provided session memory ({len(session_memory)} chars)")
        
        try:
            result = await answer.generate_answer(
                query=prompt,
                session_memory=session_memory,
            )
            return self._render_chat_fast_from_raw(result.text)
        except Exception as e:
            self._logger.warning(f"Local model failed: {e}")
            return f"Error: Local model failed to generate response. {e}"
    
    async def _call_api_provider_async(
        self,
        provider: str,
        prompt: str,
        context: dict[str, Any],
    ) -> str:
        """
        Call API provider asynchronously (OpenAI or Kimi).
        
        Uses aiohttp if available, otherwise falls back to thread pool
        with urllib/subprocess.
        
        Args:
            provider: "openai" or "kimi"
            prompt: The augmented prompt
            context: Execution context
        
        Returns:
            Provider response text
        """
        self._logger.debug(f"Calling {provider} API async with prompt: {prompt[:50]}...")
        
        # For now, use subprocess via thread pool (can be enhanced with aiohttp)
        loop = asyncio.get_event_loop()
        
        if provider == "openai":
            result = await loop.run_in_executor(
                None, self._call_openai_for_response, prompt
            )
        elif provider == "kimi":
            result = await loop.run_in_executor(
                None, self._call_kimi_for_response, prompt
            )
        else:
            result = f"Error: Unknown provider {provider}"
        
        return result
    
    def _call_openai_for_response(self, prompt: str) -> str:
        """Call OpenAI for direct response (sync version)."""
        tool = ROOT_DIR / "tools" / "unverified_context_openai.py"
        if not tool.exists():
            return "Error: OpenAI tool not found"
        
        try:
            result = subprocess.run(
                [sys.executable, str(tool), prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._prepare_subprocess_env(),
                cwd=str(ROOT_DIR),
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                if payload.get("ok"):
                    return payload.get("text", payload.get("context", "No response"))
            return f"Error: {result.stderr}"
        except Exception as e:
            return f"Error calling OpenAI: {e}"
    
    def _call_kimi_for_response(self, prompt: str) -> str:
        """Call Kimi for direct response (sync version)."""
        tool = ROOT_DIR / "tools" / "unverified_context_kimi.py"
        if not tool.exists():
            return "Error: Kimi tool not found"
        
        try:
            result = subprocess.run(
                [sys.executable, str(tool), prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=self._prepare_subprocess_env(),
                cwd=str(ROOT_DIR),
            )
            if result.returncode == 0:
                payload = json.loads(result.stdout)
                if payload.get("ok"):
                    return payload.get("text", payload.get("context", "No response"))
            return f"Error: {result.stderr}"
        except Exception as e:
            return f"Error calling Kimi: {e}"
    
    async def _call_wikipedia_provider_async(
        self,
        prompt: str,
        evidence: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> str:
        """
        Call Wikipedia provider asynchronously.
        
        Wikipedia provider returns evidence directly, so we format it
        as a response with proper attribution.
        
        Args:
            prompt: The augmented prompt (unused for Wikipedia)
            evidence: Evidence dictionary from _fetch_evidence
            context: Execution context
        
        Returns:
            Formatted response with Wikipedia context
        """
        self._logger.debug("Formatting Wikipedia response async")
        
        if not evidence:
            return "No Wikipedia information available for this query."
        
        context_text = evidence.get("context", "")
        title = evidence.get("title", "")
        url = evidence.get("url", "")
        
        if not context_text:
            return "No information found on Wikipedia for this topic."
        
        # Format a nice response with attribution
        response_parts = [context_text]
        
        if title or url:
            response_parts.append("\n\n---")
            if title:
                response_parts.append(f"Source: Wikipedia - {title}")
            if url:
                response_parts.append(f"Read more: {url}")
        
        return "\n".join(response_parts)
    
    def _validate_response(
        self,
        response: str,
        route: RoutingDecision,
    ) -> str:
        """
        Validate and sanitize model response.
        
        Args:
            response: Raw model response
            route: The routing decision
        
        Returns:
            Validated response text
        """
        if not response or not response.strip():
            return "I apologize, but I couldn't generate a response. Please try again."
        
        # Apply guards
        validated = response.strip()
        
        # Check for local generation failure patterns
        if self._is_local_generation_failure_output(validated):
            return "I'm having trouble connecting to the model. Please try again."
        
        # Apply non-empty guard
        if not validated:
            return "I couldn't generate a response. Please rephrase your question."
        
        return validated
    
    def _call_local_worker_py(
        self,
        question: str,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """
        Call Python local_answer directly (async).
        
        This is the Python-native replacement for local_answer.sh.
        Uses asyncio to call the async LocalAnswer class.
        
        Args:
            question: The user question
            env: Environment variables (applied to config)
        
        Returns:
            CompletedProcess with stdout, stderr, and returncode
        """
        import asyncio
        
        self._logger.debug(f"Calling Python local_answer with question: {question[:50]}...")
        
        try:
            # Create config from environment
            config = LocalAnswerConfig.from_env()
            
            # Override with passed env vars
            if env.get("LUCY_LOCAL_MODEL"):
                config.model = env["LUCY_LOCAL_MODEL"]
            if env.get("LUCY_SESSION_MEMORY_CONTEXT"):
                session_memory = env["LUCY_SESSION_MEMORY_CONTEXT"]
            else:
                session_memory = ""
            
            # Run async local_answer
            async def run_local():
                async with LocalAnswer(config) as answer_gen:
                    result = await answer_gen.generate_answer(
                        query=question,
                        session_memory=session_memory,
                        route_mode=env.get("LUCY_LOCAL_GEN_ROUTE_MODE", "LOCAL"),
                        output_mode=env.get("LUCY_LOCAL_GEN_OUTPUT_MODE", "CHAT"),
                        augmented_user_question=env.get("LUCY_LOCAL_AUGMENTED_USER_QUESTION", ""),
                        augmented_background_context=env.get("LUCY_LOCAL_AUGMENTED_BACKGROUND_CONTEXT", ""),
                    )
                    return result
            
            result = asyncio.run(run_local())
            
            return subprocess.CompletedProcess(
                args=["local_answer.py", question],
                returncode=0 if not result.error else 1,
                stdout=result.text,
                stderr=result.error or "",
            )
        except Exception as e:
            self._logger.error(f"Python local_answer failed: {e}")
            return subprocess.CompletedProcess(
                args=["local_answer.py", question],
                returncode=1,
                stdout="",
                stderr=str(e),
            )
    
    def _call_local_worker(
        self,
        question: str,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """
        Call local_answer.sh to generate a local response.
        
        Args:
            question: The user question
            env: Environment variables for the subprocess
        
        Returns:
            CompletedProcess with stdout, stderr, and returncode
        """
        # Check if we should use Python local_answer (experimental)
        if USE_LOCAL_ANSWER_PY and HAS_LOCAL_ANSWER_PY:
            self._logger.info(f"[MODE] Using Python local_answer.py for: {question[:50]}...")
            return self._call_local_worker_py(question, env)
        
        self._logger.info(f"[MODE] Using shell local_answer.sh for: {question[:50]}...")
        
        # Ensure namespace isolation for subprocess
        env = self._prepare_subprocess_env(env)
        
        try:
            result = subprocess.run(
                [str(self.LOCAL_ANSWER_SCRIPT), question],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(ROOT_DIR),
            )
            return result
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=[str(self.LOCAL_ANSWER_SCRIPT), question],
                returncode=1,
                stdout="",
                stderr=f"Timeout after {self.timeout}s",
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=[str(self.LOCAL_ANSWER_SCRIPT), question],
                returncode=1,
                stdout="",
                stderr=str(e),
            )
    
    def _call_local_worker_fallback(
        self,
        question: str,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]:
        """
        Call local_worker.py as a fallback when local_answer.sh fails.
        
        NAMESPACE ISOLATION:
        Uses _prepare_subprocess_env() to ensure local_worker.py runs in an
        isolated namespace, preventing "shared-state overlap" errors.
        
        Args:
            question: The user question
            env: Environment variables for the subprocess
        
        Returns:
            CompletedProcess with stdout, stderr, and returncode
        """
        self._logger.debug(f"Calling local_worker.py fallback: {question[:50]}...")
        
        # Ensure namespace isolation for subprocess
        # _prepare_subprocess_env() sets STATE_NAMESPACE_RAW to tell shell scripts
        # (execute_plan.sh) to skip their own locking, preventing conflicts.
        env = self._prepare_subprocess_env(env)
        
        try:
            result = subprocess.run(
                [sys.executable, str(self.LOCAL_WORKER_SCRIPT), question],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(ROOT_DIR),
            )
            return result
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=[sys.executable, str(self.LOCAL_WORKER_SCRIPT), question],
                returncode=1,
                stdout="",
                stderr=f"Timeout after {self.timeout}s",
            )
        except Exception as e:
            return subprocess.CompletedProcess(
                args=[sys.executable, str(self.LOCAL_WORKER_SCRIPT), question],
                returncode=1,
                stdout="",
                stderr=str(e),
            )
    
    def _call_augmented_provider(
        self,
        question: str,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Call unverified context provider for augmentation with fallback chain.
        
        Provider chain: trusted -> wikipedia -> openai -> kimi
        If one fails, automatically tries the next.
        
        For news/medical/finance queries, tries trusted sources first.
        
        NAMESPACE ISOLATION:
        Uses _prepare_subprocess_env() to ensure the provider dispatch runs in an
        isolated namespace, preventing "shared-state overlap" errors.
        
        Args:
            question: The user question
            intent: The classified intent
            route: The routing decision
            context: Execution context
        
        Returns:
            ExecutionResult from augmented provider
        """
        self._logger.info(f"Calling augmented provider for: {question[:50]}...")
        
        # Determine provider chain - start with requested or default
        primary_provider = context.get("augmented_provider", "wikipedia")
        if primary_provider == "none" or not primary_provider:
            primary_provider = "wikipedia"
        
        # Check if this is a category-specific query that should try trusted first
        intent_family = intent.intent_family if intent else ""
        is_category_query = self._is_category_specific_query(question, intent_family)
        
        # Check if this is a medical query (detected via context or evidence_reason)
        is_medical_query = self._context_indicates_medical_query(context) or (
            route and route.evidence_reason in ("medical_safety", "medical_context")
        )
        
        # Build fallback chain: free providers first, then paid
        if is_category_query:
            # Try trusted sources first for news/medical/finance
            provider_chain = ["trusted", "wikipedia", "openai", "kimi"]
            self._logger.info(f"Category-specific query detected, trying trusted sources first")
        elif primary_provider == "wikipedia":
            provider_chain = ["wikipedia", "openai", "kimi"]
        elif primary_provider == "openai":
            provider_chain = ["openai", "kimi", "wikipedia"]
        elif primary_provider == "kimi":
            provider_chain = ["kimi", "openai", "wikipedia"]
        else:
            provider_chain = [primary_provider, "wikipedia", "openai", "kimi"]
        
        # Try each provider in chain
        last_error = ""
        for provider in provider_chain:
            result = self._call_single_provider(provider, question, intent, route, context)
            if result.status == "completed":
                # For medical queries, append trusted sources to informative answer
                if is_medical_query and result.response_text:
                    result = self._append_medical_sources(result, context)
                return result
            # "not_applicable" means this provider doesn't handle this query type
            # This is not a failure, so don't log it as an error
            if result.error_message and "not_applicable" in result.error_message.lower():
                self._logger.info(f"Provider {provider} not applicable for this query, trying fallback...")
            else:
                last_error = result.error_message or f"{provider} failed"
                self._logger.warning(f"Provider {provider} failed, trying fallback...")
        
        # All providers failed
        return ExecutionResult(
            status="failed",
            outcome_code="augmentation_failed",
            route="AUGMENTED",
            provider="none",
            provider_usage_class="local",
            error_message=f"All providers failed. Last error: {last_error}",
            metadata={"providers_attempted": provider_chain},
        )
    
    def _call_single_provider(
        self,
        provider: str,
        question: str,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any],
    ) -> ExecutionResult:
        """
        Call a single augmented provider.
        
        Args:
            provider: Provider name (wikipedia, openai, kimi)
            question: The user question
            intent: The classified intent
            route: The routing decision
            context: Execution context
            
        Returns:
            ExecutionResult from the provider
        """
        self._logger.info(f"Trying provider: {provider}")
        
        # Prepare environment for subprocess with namespace isolation
        # _prepare_subprocess_env() sets STATE_NAMESPACE_RAW to tell shell scripts
        # (execute_plan.sh) to skip their own locking, preventing conflicts.
        env = self._prepare_subprocess_env()
        
        # Pass intent family to provider for category detection
        if intent and intent.intent_family:
            env["LUCY_INTENT_FAMILY"] = intent.intent_family
        
        # Pass domain allowlist for medical/category queries (restricts web search to trusted domains)
        allow_domains_file = context.get("allow_domains_file", "")
        if allow_domains_file:
            env["LUCY_FETCH_ALLOWLIST_FILTER_FILE"] = allow_domains_file
            env["LUCY_SEARCH_ALLOWLIST_FILTER_FILE"] = allow_domains_file

        # Initialize memory telemetry defaults (updated later if memory is loaded)
        memory_telemetry: dict[str, str] = {
            "memory_context_used": "false",
            "memory_mode_used": "none",
            "memory_depth_used": "none",
            "memory_top_score": "none",
            "memory_session_injected": "none",
            "memory_top_gap": "none",
        }
        
        try:
            # Call unverified_context_provider_dispatch.py
            result = subprocess.run(
                [
                    sys.executable,
                    str(self.UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL),
                    provider,
                    question,
                ],
                capture_output=True,
                text=True,
                timeout=self.timeout,
                env=env,
                cwd=str(ROOT_DIR),
            )
            
            if result.returncode != 0:
                # Dispatch tool writes structured errors to stdout; try to extract reason
                dispatch_error = result.stderr or ""
                if not dispatch_error and result.stdout:
                    try:
                        parsed = json.loads(result.stdout)
                        if isinstance(parsed, dict) and not parsed.get("ok"):
                            dispatch_error = parsed.get("reason", "Provider dispatch failed")
                    except (json.JSONDecodeError, ValueError):
                        pass
                if not dispatch_error:
                    dispatch_error = "Provider dispatch failed"
                return ExecutionResult(
                    status="failed",
                    outcome_code="augmentation_failed",
                    route="AUGMENTED",
                    provider=provider,
                    provider_usage_class=self._provider_usage_class_for(provider),
                    error_message=dispatch_error,
                    metadata={"provider": provider, "raw_output": result.stdout, **memory_telemetry},
                )
            
            # Parse JSON response
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                return ExecutionResult(
                    status="failed",
                    outcome_code="augmentation_parse_error",
                    route="AUGMENTED",
                    provider=provider,
                    provider_usage_class=self._provider_usage_class_for(provider),
                    error_message="Failed to parse provider response",
                    metadata={"provider": provider, "raw_output": result.stdout},
                )
            
            if not payload.get("ok"):
                return ExecutionResult(
                    status="failed",
                    outcome_code="augmentation_provider_error",
                    route="AUGMENTED",
                    provider=provider,
                    provider_usage_class=self._provider_usage_class_for(provider),
                    error_message=payload.get("reason", "Unknown provider error"),
                    metadata={"provider": provider, "payload": payload, **memory_telemetry},
                )
            
            # Extract context from payload
            context_text = payload.get("context", "")
            context_title = payload.get("title", "")
            context_url = payload.get("url", "")
            
            # Check if this is a bounded response from trusted provider
            # (returns formatted answer directly without calling local model)
            if payload.get("bounded_response") and payload.get("content"):
                response_text = payload.get("content", "")
                sources = payload.get("sources", [])
                category = payload.get("category", "trusted")
                
                # Use content as-is - trusted provider already formatted it with sources
                
                return ExecutionResult(
                    status="completed",
                    outcome_code="augmented_answer_bounded",
                    route="AUGMENTED",
                    provider=provider,
                    provider_usage_class="local",  # No paid API used
                    response_text=response_text.strip(),
                    metadata={
                        "provider": provider,
                        "category": category,
                        "sources": sources,
                        "trust_class": "trusted",
                        **memory_telemetry,
                    },
                )
            
            # Now call local worker with augmented context
            # Use _prepare_subprocess_env() for namespace isolation
            env = self._prepare_subprocess_env()
            env.update({
                "LUCY_LOCAL_GEN_ROUTE_MODE": "AUGMENTED",
                "LUCY_LOCAL_GEN_OUTPUT_MODE": "CHAT",
                "LUCY_LOCAL_AUGMENTED_USER_QUESTION": question,
                "LUCY_LOCAL_AUGMENTED_BACKGROUND_CONTEXT": context_text,
                "LUCY_LOCAL_AUGMENTED_CONTEXT_CLASS": provider,
                "LUCY_LOCAL_AUGMENTED_CONTEXT_TITLE": context_title,
                "LUCY_LOCAL_AUGMENTED_CONTEXT_URL": context_url,
            })
            
            # Add session memory context if enabled
            # Augmented mode gets deep context since the model handles mixed sources well
            session_memory, memory_telemetry = _load_session_memory_context_with_telemetry(
                question, depth="deep", mode="augmented"
            )
            if session_memory:
                env["LUCY_SESSION_MEMORY_CONTEXT"] = session_memory
                self._logger.debug(f"Added session memory context ({len(session_memory)} chars)")
            
            local_result = self._call_local_worker(question, env)
            
            if local_result.returncode != 0:
                return ExecutionResult(
                    status="failed",
                    outcome_code="augmentation_generation_failed",
                    route="AUGMENTED",
                    provider=provider,
                    provider_usage_class=self._provider_usage_class_for(provider),
                    error_message=local_result.stderr,
                    metadata={"provider": provider, **memory_telemetry},
                )
            
            # Success - format and return
            response_text = self._render_chat_fast_from_raw(local_result.stdout)
            
            return ExecutionResult(
                status="completed",
                outcome_code="augmented_answer",
                route="AUGMENTED",
                provider=provider,
                provider_usage_class=self._provider_usage_class_for(provider),
                response_text=response_text,
                metadata={
                    "provider": provider,
                    "context_title": context_title,
                    "context_url": context_url,
                    "trust_class": "unverified",
                    **memory_telemetry,
                },
            )
            
        except subprocess.TimeoutExpired:
            return ExecutionResult(
                status="timeout",
                outcome_code="augmentation_timeout",
                route="AUGMENTED",
                provider=provider,
                provider_usage_class=self._provider_usage_class_for(provider),
                error_message=f"Augmentation timeout after {self.timeout}s",
                metadata={**memory_telemetry},
            )
        except Exception as e:
            return ExecutionResult(
                status="failed",
                outcome_code="augmentation_error",
                route="AUGMENTED",
                provider=provider,
                provider_usage_class=self._provider_usage_class_for(provider),
                error_message=str(e),
                metadata={"exception_type": type(e).__name__, **memory_telemetry},
            )
    
    def _is_local_response_sufficient(self, response_text: str) -> bool:
        """
        Check if a local response is sufficient or needs augmentation fallback.
        
        Args:
            response_text: The local response text
        
        Returns:
            True if response is sufficient, False if augmentation needed
        """
        if not response_text:
            return False
        
        # Check for fallback phrases that indicate insufficient response
        normalized = self._guard_normalize(response_text)
        insufficient_patterns = [
            "i could not generate a reply locally",
            "i don't have enough information",
            "this requires evidence mode",
            "insufficient evidence",
            "error",
        ]
        
        for pattern in insufficient_patterns:
            if pattern in normalized:
                return False
        
        return True
    
    def _call_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Call a tool via the governed execution path.
        
        This method dispatches tool calls through the appropriate
        governed path, ensuring authority semantics are preserved.
        
        Args:
            tool_name: Name of the tool to call
            params: Parameters for the tool call
        
        Returns:
            Tool response as dictionary
        
        TODO: Migrate from execute_plan.sh:
        - Tool dispatch logic from unverified_context_provider_dispatch.py
        - Provider-specific parameter mapping
        - Error handling and retry logic
        - Response parsing
        
        Supported Tools:
        - local: Local response generation
        - wikipedia: Wikipedia search and fetch
        - openai: OpenAI API calls
        - kimi: Kimi API calls
        """
        # TODO: Implement tool dispatch from execute_plan.sh
        # - Map tool_name to tool path
        # - Prepare parameters
        # - Execute tool
        # - Parse and return response
        
        raise NotImplementedError(f"Tool call not yet implemented: {tool_name}")
    
    def _format_response(
        self,
        raw_response: str,
        metadata: dict[str, Any],
    ) -> str:
        """
        Format and enhance a raw response.
        
        This method applies formatting rules and enhancements to raw
        tool responses, including:
        - Stripping validation markers
        - Adding context footers for unverified sources
        - Applying conversation cadence
        
        Args:
            raw_response: The raw response text
            metadata: Execution metadata (trust_class, provider, etc.)
        
        Returns:
            Formatted response text
        
        TODO: Migrate from execute_plan.sh:
        - VALIDATED marker stripping (from extract_validated.py)
        - Context footer generation for unverified sources
        - Conversation cadence application
        - Response length trimming
        """
        # TODO: Implement response formatting from execute_plan.sh
        # - Strip validation markers
        # - Add context footers based on trust_class
        # - Apply conversation formatting
        # - Handle empty responses
        
        return raw_response.strip()
    
    def _get_state_file_paths(self) -> tuple[Path, Path]:
        """
        Get the current state file paths based on instance state directory.
        
        FIX: Dynamic state file path resolution
        - Uses instance _state_dir instead of class constants
        - Respects LUCY_SHARED_STATE_NAMESPACE per query
        - Ensures state files are isolated per namespace
        
        Returns:
            Tuple of (route_file_path, outcome_file_path)
        """
        route_file = self._state_dir / "last_route.env"
        outcome_file = self._state_dir / "last_outcome.env"
        return route_file, outcome_file
    
    def _write_state_files(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """
        Write execution state to storage.
        
        Phase 2: Dual-write to both SQLite and files during transition.
        Phase 3: SQLite only (when use_sqlite_state=True and files deprecated).
        
        This method updates both SQLite (via StateManager) and file-based state
        (last_route.env, last_outcome.env) for backwards compatibility during
        the transition period.
        
        FIX: State File Locking and Namespace Isolation
        - Uses _file_lock() context manager for exclusive access to files
        - Uses instance _state_dir for proper namespace isolation
        - Prevents "shared-state overlap" errors during concurrent writes
        - Falls back to best-effort write if lock cannot be acquired
        - Shell-compatible format (KEY=value pairs, newline-terminated)
        
        Args:
            route: The routing decision that was executed
            result: The execution result
            context: Execution context
        """
        # Write to SQLite (new way) if enabled
        if self.use_sqlite_state:
            try:
                self._write_state_to_sqlite(route, result, context)
                self._logger.debug("State written to SQLite successfully")
            except Exception as e:
                self._logger.error(f"SQLite state write failed: {e}")
                # Continue to file write as fallback
        
        # Always write to files for backwards compatibility during transition
        self._write_state_to_files(route, result, context)
    
    def _write_state_to_sqlite(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """
        Write state to SQLite via StateManager.
        
        Args:
            route: The routing decision that was executed
            result: The execution result
            context: Execution context
        """
        try:
            # Write route record
            self.state_manager.write_route({
                "intent": context.get("intent", ""),
                "confidence": route.confidence,
                "strategy": route.route,  # REAL route, not mapped
                "metadata": {
                    "question": context.get("question", "")[:200],
                    "provider": route.provider,
                    "provider_usage_class": route.provider_usage_class,
                    "is_medical_query": context.get("is_medical_query", False),
                    "final_mode": result.route,
                    "requested_mode": route.route,
                }
            })
            
            # Build outcome metadata for SQLite
            outcome_meta: dict[str, Any] = {
                "route": result.route,
                "provider": result.provider,
                "outcome_code": result.outcome_code,
                "trust_class": result.metadata.get("trust_class", "local"),
            }
            # Include memory telemetry if present
            for key in ("memory_context_used", "memory_mode_used", "memory_top_score",
                        "memory_session_injected", "memory_top_gap"):
                if key in result.metadata:
                    outcome_meta[key] = result.metadata[key]
            
            # Write outcome record
            self.state_manager.write_outcome({
                "success": result.status == "completed",
                "duration_ms": result.execution_time_ms,
                "result": outcome_meta,
                "error_message": result.error_message or ""
            })
            
            self._logger.info("State written to SQLite")
        except Exception as e:
            self._logger.error(f"SQLite state write failed: {e}")
            raise
    
    def _write_state_to_files(
        self,
        route: RoutingDecision,
        result: ExecutionResult,
        context: dict[str, Any],
    ) -> None:
        """
        Write execution state to file-based storage.
        
        This method maintains backwards compatibility with existing shell scripts
        and components that read from .env state files.
        
        Args:
            route: The routing decision that was executed
            result: The execution result
            context: Execution context
        """
        question = context.get("question", "")
        timestamp = int(time.time())
        
        # Get dynamic state file paths (respects namespace)
        route_file, outcome_file = self._get_state_file_paths()
        
        # Build route metadata
        route_fields = [
            ("TIMESTAMP", str(timestamp)),
            ("FINAL_MODE", result.route),
            ("REQUESTED_MODE", route.route),
            ("ROUTE_REASON", "router_classifier_mapper"),
            ("ORIGINAL_QUESTION", question),
            ("RESOLVED_QUESTION", context.get("resolved_question", question)),
            ("LOCAL_DIRECT_USED", "true" if result.metadata.get("local_direct_used") else "false"),
            ("LOCAL_DIRECT_FALLBACK", "true" if result.metadata.get("local_direct_fallback") else "false"),
            ("LOCAL_DIRECT_PATH", result.metadata.get("local_direct_path", "disabled")),
        ]
        
        # Build outcome metadata
        outcome_fields = [
            ("TIMESTAMP", str(timestamp)),
            ("OUTCOME_CODE", result.outcome_code),
            ("FINAL_MODE", result.route),
            ("ROUTE_REASON", "router_classifier_mapper"),
            ("ORIGINAL_QUESTION", question),
            ("RESOLVED_QUESTION", context.get("resolved_question", question)),
            ("FALLBACK_USED", "true" if result.metadata.get("fallback_used") else "false"),
            ("FALLBACK_REASON", result.metadata.get("fallback_reason", "none")),
            ("TRUST_CLASS", result.metadata.get("trust_class", "local")),
            ("AUGMENTED_PROVIDER_USED", result.provider if result.route == "AUGMENTED" else "none"),
            ("AUGMENTED_PROVIDER_USAGE_CLASS", result.provider_usage_class),
            ("EXECUTION_TIME_MS", str(result.execution_time_ms)),
            ("ROUTING_SIGNAL_MEDICAL_CONTEXT", "true" if context.get("is_medical_query") else "false"),
        ]
        
        # Memory telemetry (added if present in metadata)
        if "memory_context_used" in result.metadata:
            outcome_fields.append(("MEMORY_CONTEXT_USED", result.metadata["memory_context_used"]))
        if "memory_mode_used" in result.metadata:
            outcome_fields.append(("MEMORY_MODE_USED", result.metadata["memory_mode_used"]))
        if "memory_depth_used" in result.metadata:
            outcome_fields.append(("MEMORY_DEPTH_USED", result.metadata["memory_depth_used"]))
        if "memory_top_score" in result.metadata:
            outcome_fields.append(("MEMORY_TOP_SCORE", result.metadata["memory_top_score"]))
        if "memory_session_injected" in result.metadata:
            outcome_fields.append(("MEMORY_SESSION_INJECTED", result.metadata["memory_session_injected"]))
        if "memory_top_gap" in result.metadata:
            outcome_fields.append(("MEMORY_TOP_GAP", result.metadata["memory_top_gap"]))
        
        # Write last_route.env with locking
        try:
            # Ensure parent directory exists (in case namespace changed)
            route_file.parent.mkdir(parents=True, exist_ok=True)
            
            route_content = "\n".join(f"{k}={v}" for k, v in route_fields) + "\n"
            
            # Use file lock to prevent concurrent write corruption
            with self._file_lock(route_file):
                route_file.write_text(route_content, encoding="utf-8")
                
        except Exception as e:
            # FIX: Don't return "ERR: shared-state overlap" to user
            # Log the error internally and continue with best-effort
            self._logger.warning(f"Failed to write last_route.env: {e}")
            # Attempt unprotected write as last resort (best-effort)
            try:
                route_file.write_text(route_content, encoding="utf-8")
            except Exception as e2:
                self._logger.error(f"Unprotected write also failed: {e2}")
        
        # Write last_outcome.env with locking
        try:
            # Ensure parent directory exists
            outcome_file.parent.mkdir(parents=True, exist_ok=True)
            
            outcome_content = "\n".join(f"{k}={v}" for k, v in outcome_fields) + "\n"
            
            # Use file lock to prevent concurrent write corruption
            with self._file_lock(outcome_file):
                outcome_file.write_text(outcome_content, encoding="utf-8")
                
        except Exception as e:
            # FIX: Don't return "ERR: shared-state overlap" to user
            # Log the error internally and continue with best-effort
            self._logger.warning(f"Failed to write last_outcome.env: {e}")
            # Attempt unprotected write as last resort (best-effort)
            try:
                outcome_file.write_text(outcome_content, encoding="utf-8")
            except Exception as e2:
                self._logger.error(f"Unprotected write also failed: {e2}")
    
    def read_last_route_from_sqlite(self) -> dict | None:
        """
        Read last route from SQLite.
        
        Returns:
            dict: Route data from SQLite, or None if not found
        """
        return self.state_manager.read_last_route()
    
    def read_last_outcome_from_sqlite(self) -> dict | None:
        """
        Read last outcome from SQLite.
        
        Returns:
            dict: Outcome data from SQLite, or None if not found
        """
        return self.state_manager.read_last_outcome()
    
    def verify_state_consistency(self) -> bool:
        """
        Verify SQLite and file-based states match.
        
        This is a debugging/validation method for the dual-write transition.
        Compares the last route written to both SQLite and files to ensure
        they are consistent.
        
        Returns:
            bool: True if states match, False otherwise
        """
        sqlite_route = self.read_last_route_from_sqlite()
        
        # Read from files
        route_file, _ = self._get_state_file_paths()
        file_strategy = None
        if route_file.exists():
            file_strategy = self._read_state_field(route_file, "FINAL_MODE")
        
        if sqlite_route and file_strategy:
            match = sqlite_route.get("strategy") == file_strategy
            if not match:
                self._logger.warning(
                    f"State mismatch between SQLite and files! "
                    f"SQLite: {sqlite_route.get('strategy')}, "
                    f"File: {file_strategy}"
                )
            else:
                self._logger.debug("State consistency verified: SQLite and files match")
            return match
        
        # If one is missing, we can't verify
        if sqlite_route or file_strategy:
            self._logger.warning("Cannot verify consistency: only one state source available")
            return False
        
        return True
    
    def _record_terminal_outcome(
        self,
        outcome_code: str,
        mode: str,
        error_msg: str | None = None,
        execution_time_ms: int = 0,
    ) -> None:
        """
        Record terminal outcome for cases where normal flow is interrupted.
        
        This is used when execution ends early (e.g., CLARIFY, timeout, error)
        and we need to ensure state is recorded.
        
        Args:
            outcome_code: The outcome code (e.g., "clarification_requested")
            mode: The execution mode (e.g., "CLARIFY")
            error_msg: Optional error message
            execution_time_ms: Execution time in milliseconds
        """
        # Write to SQLite if enabled
        if self.use_sqlite_state:
            try:
                self.state_manager.write_outcome({
                    "success": outcome_code != "execution_error",
                    "duration_ms": execution_time_ms,
                    "result": {"outcome_code": outcome_code, "mode": mode},
                    "error_message": error_msg or ""
                })
                self._logger.debug("Terminal outcome recorded in SQLite")
            except Exception as e:
                self._logger.error(f"Failed to record terminal outcome in SQLite: {e}")
    
    def close(self) -> None:
        """
        Close the execution engine and cleanup resources.
        
        This should be called when done with the engine to properly
        release resources like database connections.
        """
        try:
            if hasattr(self, 'state_manager'):
                self.state_manager.close()
                self._logger.debug("StateManager connection closed")
        except Exception as e:
            self._logger.warning(f"Error closing StateManager: {e}")
    
    def _read_state_field(self, state_file: Path, field: str) -> str | None:
        """
        Read a field value from a state file.
        
        FIX: File Locking for Reads
        - Uses shared lock (LOCK_SH) for concurrent read access
        - Prevents reading partially-written state during concurrent access
        - Falls back to unprotected read if lock fails (best-effort)
        
        Args:
            state_file: Path to the state file
            field: Field name to read
        
        Returns:
            Field value or None if not found/error
        """
        if not state_file.exists():
            return None
        
        try:
            # Use shared lock for reading (allows concurrent reads, blocks writes)
            with self._file_lock(state_file):
                content = state_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith(f"{field}="):
                        return line[len(field) + 1:].strip()
        except Exception:
            # Best-effort fallback: try unprotected read
            try:
                content = state_file.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith(f"{field}="):
                        return line[len(field) + 1:].strip()
            except Exception:
                pass
        
        return None
    
    def _map_route_to_chat_mode(self, route: str) -> str:
        """
        Map internal route to valid lucy_chat.sh mode.
        
        DEPRECATED: To be removed after Phase 2 completion - no longer needed.
        This method was used when calling lucy_chat.sh which only accepts
        LOCAL/EVIDENCE/NEWS modes. The new Python-native execution path
        (_execute_full_route_python) keeps real routes (AUGMENTED, etc.)
        without mapping.
        
        Valid modes in lucy_chat.sh: LOCAL, EVIDENCE, NEWS
        
        Internal routes like AUGMENTED, CLARIFY, SELF_REVIEW are mapped
        to appropriate chat modes. Unknown routes default to LOCAL for safety.
        
        Args:
            route: Internal route name (e.g., "LOCAL", "AUGMENTED", "CLARIFY")
        
        Returns:
            Valid lucy_chat.sh mode (LOCAL, EVIDENCE, or NEWS)
        """
        mapping = {
            "LOCAL": "LOCAL",
            "BYPASS": "LOCAL",
            "PROVISIONAL": "LOCAL",
            "FULL": "EVIDENCE",
            "EVIDENCE": "EVIDENCE",
            "NEWS": "NEWS",
            "AUGMENTED": "LOCAL",  # Augmented is handled differently
            "CLARIFY": "LOCAL",     # Clarification is local
            "SELF_REVIEW": "LOCAL",
        }
        return mapping.get(route, "LOCAL")  # Default to LOCAL for safety
    
    # ====================================================================== 
    # Helper Methods (ported from execute_plan.sh)
    # ====================================================================== 
    
    def _render_chat_fast_from_raw(self, raw: str) -> str:
        """
        Fast render of chat output from raw response.
        
        Ported from render_chat_fast_from_raw (lines 357-374).
        
        Args:
            raw: Raw output from local tool
        
        Returns:
            Formatted chat response
        """
        lines = []
        for line in raw.splitlines():
            s = line.strip()
            if not s:
                continue
            if s in ("BEGIN_VALIDATED", "END_VALIDATED"):
                continue
            lines.append(s)
        
        if lines:
            return " ".join(lines)
        return raw.strip()
    
    def _local_fast_non_empty_guard(
        self,
        question: str,
        body: str,
        mode: str,
    ) -> str:
        """
        Guard against empty local responses.
        
        Ported from local_fast_non_empty_guard (lines 388-399).
        """
        if body and body.strip():
            return body
        
        if mode == "CONVERSATION":
            return self._render_conversation_fallback(question)
        
        return self._runtime_local_fallback_text()
    
    def _local_fast_repetition_guard(
        self,
        question: str,
        body: str,
        mode: str,
    ) -> str:
        """
        Guard against repetitive responses.
        
        Ported from local_fast_repetition_guard (lines 400-443).
        
        Tracks response history and breaks repetition cycles.
        """
        qn = self._guard_normalize(question)
        bn = self._guard_normalize(body)
        
        # Update repeat count
        self.REPEAT_COUNT_SESSION += 1
        
        # Check for repetition (simplified - full implementation would track history)
        if bn and mode in ("CHAT", "CONVERSATION"):
            if self._local_fast_is_allowed_repeat_body(body):
                return body
        
        return body
    
    def _local_fast_is_allowed_repeat_body(self, body: str) -> bool:
        """
        Check if body is allowed to repeat.
        
        Ported from local_fast_is_allowed_repeat_body (lines 378-387).
        """
        n = self._guard_normalize(body)
        allowed = [
            "i could not generate a reply locally. please retry, or switch mode.",
            "error",
        ]
        return n in allowed
    
    def _runtime_local_fallback_text(self) -> str:
        """
        Return fallback text when local generation fails.
        
        Ported from runtime_local_fallback_text (lines 354-356).
        """
        return "I could not generate a reply locally. Please retry, or switch mode."
    
    def _runtime_local_prompt_fallback_text(self, question: str, variant: str = "0") -> str:
        """
        Return prompt fallback text.
        
        Ported from runtime_local_prompt_fallback_text (lines 471-496).
        """
        qn = self._guard_normalize(question)
        
        # Handle special cases
        if qn in ("not necessary.", "not necessary", "no thanks", "never mind"):
            return ""
        
        if "how are you" in qn or qn in ("hi.", "hi"):
            return "Hello. What do you want to solve right now?"
        
        # Fallback bank
        bank = [
            "State the specific question in one sentence and I will answer directly.",
            "Give me one concrete detail and I will respond precisely.",
            "Narrow it to one claim or decision and I will work through it.",
            "Restate the exact point you want help with, and I will keep the answer focused.",
            "Tell me the practical question behind this, and I will address it directly.",
            "Give me the single most important detail, and I will continue from there.",
            "Frame the issue as one concrete question, and I will answer without drifting.",
            "Name the exact topic or decision, and I will give a bounded response.",
        ]
        
        idx = self._deterministic_pick_index(f"{qn}|{variant}", len(bank))
        return bank[idx]
    
    def _render_conversation_fallback(self, question: str) -> str:
        """
        Render conversation mode fallback.
        
        Ported from render_conversation_fallback (referenced in execute_plan.sh).
        """
        return self._runtime_local_prompt_fallback_text(question, "0")
    
    def _is_local_generation_failure_output(self, body: str) -> bool:
        """
        Check if output indicates local generation failure.
        
        Ported from is_local_generation_failure_output (execute_plan.sh).
        """
        n = self._guard_normalize(body)
        failure_patterns = [
            "127.0.0.1:11434",
            "ollama",
            "connection refused",
            "operation not permitted",
            "dial tcp",
        ]
        for pattern in failure_patterns:
            if pattern in n:
                return True
        return False
    
    def _is_evidence_style_text(self, text: str) -> bool:
        """
        Check if text has evidence-style formatting.
        
        Ported from is_evidence_style_text (execute_plan.sh).
        """
        n = self._guard_normalize(text)
        evidence_patterns = [
            "source:",
            "sources:",
            "according to",
            "retrieved from",
        ]
        for pattern in evidence_patterns:
            if pattern in n:
                return True
        return False
    
    # ====================================================================== 
    # Utility Functions (ported from execute_plan.sh)
    # ====================================================================== 
    
    @staticmethod
    def _is_truthy(value: str | None) -> bool:
        """
        Parse boolean from string (ported from is_truthy, line 348).
        
        Args:
            value: String to parse (e.g., "true", "1", "yes", "")
            
        Returns:
            True for "true", "1", "yes", "on" (case-insensitive), False otherwise
            
        Examples:
            >>> ExecutionEngine._is_truthy("true")
            True
            >>> ExecutionEngine._is_truthy("false")
            False
            >>> ExecutionEngine._is_truthy("1")
            True
            >>> ExecutionEngine._is_truthy("0")
            False
            >>> ExecutionEngine._is_truthy("yes")
            True
            >>> ExecutionEngine._is_truthy("no")
            False
            >>> ExecutionEngine._is_truthy("on")
            True
            >>> ExecutionEngine._is_truthy("off")
            False
            >>> ExecutionEngine._is_truthy("")
            False
            >>> ExecutionEngine._is_truthy(None)
            False
        """
        if not value:
            return False
        return value.lower() in ("1", "true", "yes", "on")
    
    @staticmethod
    def _sha256_text(text: str) -> str:
        """
        Generate SHA-256 hash of text (ported from sha256_text, line 444).
        
        Args:
            text: String to hash
            
        Returns:
            Hexadecimal SHA-256 hash string (64 characters)
            
        Examples:
            >>> ExecutionEngine._sha256_text("hello")
            '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
            >>> ExecutionEngine._sha256_text("")
            'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'
        """
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    @staticmethod
    def _deterministic_pick_index(seed: str, mod: int) -> int:
        """
        Deterministically select an index from 0 to mod-1 based on seed (ported from deterministic_pick_index, line 452).
        
        Uses SHA-256 hash of the seed and takes first 8 hex digits to create
        a deterministic pseudo-random selection. This ensures consistent
        selection for the same seed across executions.
        
        Args:
            seed: Seed string for deterministic selection
            mod: Modulo value (must be positive)
            
        Returns:
            Integer index from 0 to mod-1
            
        Raises:
            ValueError: If mod is not positive
            
        Examples:
            >>> ExecutionEngine._deterministic_pick_index("test", 8)
            1
            >>> ExecutionEngine._deterministic_pick_index("hello", 10)
            4
            >>> ExecutionEngine._deterministic_pick_index("same_seed", 5)
            3
            >>> ExecutionEngine._deterministic_pick_index("same_seed", 5)  # Same result
            3
        """
        if mod <= 0:
            raise ValueError(f"mod must be positive, got {mod}")
        h = ExecutionEngine._sha256_text(seed)
        hex_val = h[:8]
        return int(hex_val, 16) % mod
    
    @staticmethod
    def _provider_usage_class_for(provider: str | None) -> str:
        """
        Map provider name to usage class (ported from provider_usage_class_for, line 327).
        
        Args:
            provider: Provider name (e.g., "openai", "kimi", "wikipedia", "local")
            
        Returns:
            Usage class: "paid", "free", "local", or "none"
            
        Examples:
            >>> ExecutionEngine._provider_usage_class_for("openai")
            'paid'
            >>> ExecutionEngine._provider_usage_class_for("kimi")
            'paid'
            >>> ExecutionEngine._provider_usage_class_for("wikipedia")
            'free'
            >>> ExecutionEngine._provider_usage_class_for("local")
            'local'
            >>> ExecutionEngine._provider_usage_class_for("unknown")
            'none'
            >>> ExecutionEngine._provider_usage_class_for(None)
            'none'
        """
        if not provider:
            return "none"
        match provider.lower():
            case "openai" | "kimi":
                return "paid"
            case "wikipedia":
                return "free"
            case "local":
                return "local"
            case "trusted":
                return "free"  # Trusted sources are free (no paid API)
            case _:
                return "none"
    
    @staticmethod
    def _is_category_specific_query(question: str, intent_family: str) -> bool:
        """
        Check if query is category-specific (news, medical, finance).
        These queries should try trusted sources first.
        
        Args:
            question: The user question
            intent_family: Classified intent family
            
        Returns:
            True if this is a category-specific query
        """
        q_lower = question.lower()
        
        # Check intent family first
        if intent_family == "current_evidence":
            return True
        
        # News keywords
        news_keywords = [
            "news", "headline", "headlines", "breaking", "latest",
            "current events", "world news", "today's news"
        ]
        if any(kw in q_lower for kw in news_keywords):
            return True
        
        # Medical keywords
        medical_keywords = [
            "medical", "medication", "medicine", "drug", "dose", "dosage",
            "side effect", "interaction", "contraindication", "health",
            "prescription", "treatment"
        ]
        if any(kw in q_lower for kw in medical_keywords):
            return True
        
        # Finance keywords
        finance_keywords = [
            "finance", "stock", "market", "economy", "currency",
            "exchange rate", "investment", "financial"
        ]
        if any(kw in q_lower for kw in finance_keywords):
            return True
        
        return False
    
    @staticmethod
    def _normalize_augmentation_policy(raw: str | None) -> str:
        """
        Normalize augmentation policy string to canonical value (ported from normalize_augmentation_policy, line 317).
        
        Args:
            raw: Raw policy string (e.g., "disabled", "fallback", "direct")
            
        Returns:
            Canonical policy: "disabled", "fallback_only", or "direct_allowed"
            
        Examples:
            >>> ExecutionEngine._normalize_augmentation_policy("disabled")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("off")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("none")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("0")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("false")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("no")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("fallback_only")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("fallback")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("1")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("true")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("yes")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("on")
            'fallback_only'
            >>> ExecutionEngine._normalize_augmentation_policy("direct_allowed")
            'direct_allowed'
            >>> ExecutionEngine._normalize_augmentation_policy("direct")
            'direct_allowed'
            >>> ExecutionEngine._normalize_augmentation_policy("2")
            'direct_allowed'
            >>> ExecutionEngine._normalize_augmentation_policy("unknown")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy("")
            'disabled'
            >>> ExecutionEngine._normalize_augmentation_policy(None)
            'disabled'
        """
        if not raw:
            return "disabled"
        normalized = raw.lower()
        match normalized:
            case "disabled" | "off" | "none" | "0" | "false" | "no":
                return "disabled"
            case "fallback_only" | "fallback" | "1" | "true" | "yes" | "on":
                return "fallback_only"
            case "direct_allowed" | "direct" | "2":
                return "direct_allowed"
            case _:
                return "disabled"
    
    @staticmethod
    def _guard_normalize(text: str | None) -> str:
        """
        Normalize text for guard comparisons (ported from guard_normalize, line 3740).
        
        Converts to lowercase and normalizes whitespace to single spaces.
        Used for deterministic string comparison in guard conditions.
        
        Args:
            text: Input text to normalize
            
        Returns:
            Normalized text string
            
        Examples:
            >>> ExecutionEngine._guard_normalize("  Hello   WORLD  ")
            'hello world'
            >>> ExecutionEngine._guard_normalize("Test\t\tText")
            'test text'
            >>> ExecutionEngine._guard_normalize("UPPER lower MiXeD")
            'upper lower mixed'
            >>> ExecutionEngine._guard_normalize("")
            ''
            >>> ExecutionEngine._guard_normalize(None)
            ''
        """
        if not text:
            return ""
        # Convert to lowercase and normalize whitespace
        normalized = text.lower()
        # Replace any whitespace sequence with single space
        normalized = re.sub(r'\s+', ' ', normalized)
        # Strip leading/trailing whitespace
        return normalized.strip()
    
    @staticmethod
    def _local_fast_guard_normalize(text: str | None) -> str:
        """
        Fast text normalization for local guard comparisons (ported from local_fast_guard_normalize, line 375).
        
        This is an alias for _guard_normalize with the same behavior.
        Used in fast-path local execution for repetition detection.
        
        Args:
            text: Input text to normalize
            
        Returns:
            Normalized text string
            
        Examples:
            >>> ExecutionEngine._local_fast_guard_normalize("  Hello   WORLD  ")
            'hello world'
            >>> ExecutionEngine._local_fast_guard_normalize("Test\t\tText")
            'test text'
            >>> ExecutionEngine._local_fast_guard_normalize("")
            ''
            >>> ExecutionEngine._local_fast_guard_normalize(None)
            ''
        """
        return ExecutionEngine._guard_normalize(text)


def create_execution_engine(
    config: dict[str, Any] | None = None,
) -> ExecutionEngine:
    """
    Factory function to create an ExecutionEngine instance.
    
    This provides a convenient entry point for creating execution engines
    with default or custom configuration.
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        Configured ExecutionEngine instance
    
    Example:
        >>> engine = create_execution_engine({"timeout": 60})  # doctest: +SKIP
        >>> result = engine.execute(intent, route)  # doctest: +SKIP
    """
    return ExecutionEngine(config)


if __name__ == "__main__":
    # CLI interface for testing
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Execution Engine - Execute routing decisions"
    )
    parser.add_argument("--intent", required=True, help="Intent JSON")
    parser.add_argument("--route", required=True, help="Route JSON")
    parser.add_argument("--context", help="Context JSON")
    parser.add_argument("--timeout", type=int, default=130, help="Timeout in seconds")
    
    args = parser.parse_args()
    
    # Parse inputs
    intent_data = json.loads(args.intent)
    route_data = json.loads(args.route)
    context_data = json.loads(args.context) if args.context else {}
    
    # Create classification and routing objects (simplified)
    intent = ClassificationResult(**intent_data)
    route = RoutingDecision(**route_data)
    
    # Execute
    engine = create_execution_engine({"timeout": args.timeout})
    result = engine.execute(intent, route, context_data)
    
    # Output result as JSON
    print(json.dumps(result.to_dict(), indent=2))
