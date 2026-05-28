#!/usr/bin/env python3
"""
Execution Engine — Python-native plan execution.

Receives RoutingDecision from the pipeline and executes it:
- WEATHER / TIME / NEWS: fetch evidence, return formatted result
- LOCAL: call local model worker
- AUGMENTED / FULL / EVIDENCE: fetch evidence, build prompt, call provider
- CLARIFY: return clarification request

Provider resolution is now centralized in `provider_resolver.py`.
The engine trusts `route.provider` as the single source of truth.

Response formatting and validation live in `response_formatter.py`.
Memory persistence lives in `main._persist_memory_turn()`.

This module no longer contains shell delegation paths (removed in Stage 9).
"""

from __future__ import annotations

import asyncio
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
import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Async HTTP support for provider calls
try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

# Medical domains cache (Phase 3E) — file changes rarely, avoid per-query I/O
_MEDICAL_DOMAINS_CACHE: list[str] | None = None
_MEDICAL_DOMAINS_MTIME: float = 0.0
_MEDICAL_DEFAULT_DOMAINS = [
    "pubmed.ncbi.nlm.nih.gov",
    "medlineplus.gov",
    "dailymed.nlm.nih.gov",
    "cochranelibrary.com",
]


def _load_medical_domains(path: Path) -> list[str]:
    """Load medical domains with mtime-based caching."""
    global _MEDICAL_DOMAINS_CACHE, _MEDICAL_DOMAINS_MTIME
    try:
        mtime = path.stat().st_mtime
    except Exception:
        _MEDICAL_DOMAINS_CACHE = None
        _MEDICAL_DOMAINS_MTIME = 0.0
        return list(_MEDICAL_DEFAULT_DOMAINS)
    if _MEDICAL_DOMAINS_CACHE is not None and mtime == _MEDICAL_DOMAINS_MTIME:
        return _MEDICAL_DOMAINS_CACHE
    try:
        with open(path) as f:
            domains = [line.strip() for line in f if line.strip()]
        _MEDICAL_DOMAINS_CACHE = domains if domains else list(_MEDICAL_DEFAULT_DOMAINS)
        _MEDICAL_DOMAINS_MTIME = mtime
        return _MEDICAL_DOMAINS_CACHE
    except Exception:
        return list(_MEDICAL_DEFAULT_DOMAINS)


sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.classify import ClassificationResult, RoutingDecision
from router_py.policy import requires_evidence_mode
from router_py.request_types import ExecutionResult
from router_py import response_formatter
from router_py.state_manager import get_state_manager
from router_py.execution_engine_state import StateWriter
from router_py.resilience import get_breaker, CircuitBreakerOpen
from router_py.shutdown_handler import register_closeable
from router_py.structured_logging import get_structured_logger, ContextualLogger
from router_py.execution_engine_utils import (
    is_truthy,
    sha256_text,
    deterministic_pick_index,
    provider_usage_class_for,
    is_category_specific_query,
    normalize_augmentation_policy,
    local_fast_guard_normalize,
)

# Ensure models/router is on sys.path before importing router modules
sys.path.insert(0, str(ROOT_DIR / "models" / "router"))

# Import auto-feedback for answer quality analysis
try:
    from auto_feedback import analyze_answer_quality, log_auto_feedback
    HAS_AUTO_FEEDBACK = True
except ImportError:
    HAS_AUTO_FEEDBACK = False

# Import response cache for repeated query short-circuit
try:
    from response_cache import get_cached, set_cached
    HAS_RESPONSE_CACHE = True
except ImportError:
    HAS_RESPONSE_CACHE = False

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

# Import provider modules (extracted to keep ExecutionEngine focused on dispatch)
try:
    from router_py.providers import (
        fetch_wikipedia_evidence,
        fetch_api_evidence,
        fetch_time_evidence,
        fetch_weather_evidence,
        fetch_news_evidence,
        fetch_trusted_evidence,
        format_time_response,
        format_wikipedia_response,
        call_openai_for_response,
        call_openai_subprocess,
        call_kimi_for_response,
        call_kimi_subprocess,
        call_local_model_async,
    )
    HAS_PROVIDER_MODULES = True
except ImportError:
    HAS_PROVIDER_MODULES = False

# Feature flag: Use Python local_answer instead of shell version
# Default is "1" (Python) - shell path available via LUCY_LOCAL_ANSWER_PY=0 if needed
USE_LOCAL_ANSWER_PY = os.environ.get("LUCY_LOCAL_ANSWER_PY", "1") == "1"
UNVERIFIED_CONTEXT_DISPATCH = ROOT_DIR / "tools" / "unverified_context_provider_dispatch.py"
CONVERSATION_SHIM = ROOT_DIR / "tools" / "conversation" / "conversation_cadence_shim.py"

# TODO: Migrate from execute_plan.sh - Configuration defaults
DEFAULT_TIMEOUT = 130
DEFAULT_POLICY_CONFIDENCE_THRESHOLD = 0.60

# Default chat memory file path (matches runtime_request.py)
DEFAULT_CHAT_MEMORY_FILE = "~/.codex-api-home/lucy/runtime-v9/state/chat_session_memory.txt"


def _load_session_memory_context_with_telemetry(
    query: str = "", depth: str = "auto", mode: str = "local", session_id: str = "default"
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
            current_session_id=session_id, max_chars=1200, query=query, depth=depth, mode=mode
        )
        if context:
            return context, telemetry
    except Exception:
        logging.warning("SQLite memory read failed, falling back to text file", exc_info=True)

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


def _load_session_memory_context(query: str = "", depth: str = "auto", mode: str = "local", session_id: str = "default") -> str:
    """
    Load session memory context from the chat memory file.

    Backward-compatible wrapper that returns only the context string.
    """
    context, _ = _load_session_memory_context_with_telemetry(query, depth, mode, session_id=session_id)
    return context




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
    LOCAL_ANSWER_PY_SCRIPT: Path = ROOT_DIR / "tools" / "router_py" / "local_answer.py"
    LOCAL_WORKER_SCRIPT: Path = ROOT_DIR / "tools" / "local_worker.py"
    LOCAL_WORKER_CLIENT_LIB: Path = ROOT_DIR / "tools" / "local_worker_client.sh"
    CONV_SHIM_SCRIPT: Path = ROOT_DIR / "tools" / "conversation" / "conversation_cadence_shim.py"
    UNVERIFIED_CONTEXT_PROVIDER_DISPATCH_TOOL: Path = ROOT_DIR / "tools" / "unverified_context_provider_dispatch.py"
    LATPROF_LIB: Path = ROOT_DIR / "tools" / "router" / "latency_profile.sh"
    
    # =========================================================================
    # FILE PATHS - Configuration files
    # =========================================================================
    UNVERIFIED_CONTEXT_CATALOG: Path = ROOT_DIR / "config" / "unverified_context_sources.tsv"
    UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS: Path = ROOT_DIR / "config" / "unverified_context_provider_defaults.env"
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
        self.state_writer = StateWriter(
            state_dir=self._state_dir,
            state_manager=self.state_manager,
            logger=self._logger,
            use_sqlite_state=self.use_sqlite_state,
        )
        register_closeable(self.state_writer)
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
        # Propagate the selected model so local_answer uses the right LLM.
        # HMI model selector updates current_state.json; runtime_bridge passes
        # it via config["model"]. Without this, START_LUCY.sh's hardcoded
        # LUCY_LOCAL_MODEL=local-lucy always wins.
        configured_model = self.config.get("model")
        if configured_model:
            env["LUCY_LOCAL_MODEL"] = str(configured_model)
            self._logger.info(f"[MODEL] Subprocess env set to: {configured_model}")
        return env
    
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
        session_id = context.get("session_id", "default") or "default"

        # Use structured logger from context if provided
        logger: ContextualLogger = context.get("_logger")
        if logger is None:
            logger = get_structured_logger("router_py.execution_engine")
        self._logger = logger

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
            self._write_json_state_files(route, result, context)
            return result
        
        # Use Python-native path by default for all routes (shell-free)
        # Following burn-in certification (2,221+ queries, 100% success)
        if use_python_path and route.route in ("FULL", "EVIDENCE", "NEWS", "AUGMENTED", "LOCAL", "TIME", "WEATHER"):
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
        
        # Response cache short-circuit: skip LLM for repeated LOCAL queries
        if HAS_RESPONSE_CACHE and route.route == "LOCAL" and question:
            cached = get_cached(question)
            if cached:
                execution_time = int((time.time() - start_time) * 1000)
                self._logger.info(f"Cache hit: returning cached response ({execution_time}ms)")
                return ExecutionResult(
                    status="completed",
                    outcome_code="local_answer",
                    route="LOCAL",
                    provider="local",
                    provider_usage_class="local",
                    response_text=cached,
                    execution_time_ms=execution_time,
                    metadata={"cache_hit": True, "execution_time_ms": execution_time},
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
            self._write_json_state_files(route, final_result, context)
            
            # Auto-feedback: detect obvious misroutes from answer quality
            if HAS_AUTO_FEEDBACK and question:
                try:
                    suggestion = analyze_answer_quality(
                        query=question,
                        route=route.route,
                        response_text=final_result.response_text or "",
                        error_message=final_result.error_message or "",
                    )
                    if suggestion:
                        log_auto_feedback(suggestion)
                        self._logger.info(
                            f"Auto-feedback: detected {suggestion['reason']} "
                            f"(suggest {suggestion['suggested_route']}, "
                            f"confidence={suggestion['confidence']})"
                        )
                        # Trigger background learning if enough feedback accumulated
                        try:
                            from background_learner import maybe_auto_learn
                            triggered = maybe_auto_learn(min_entries=5)
                            if triggered:
                                self._logger.info("Background learning triggered (auto)")
                        except Exception:
                            pass
                except Exception:
                    pass  # Auto-feedback must never break execution
            
            # Cache LOCAL responses for repeated queries
            if HAS_RESPONSE_CACHE and route.route == "LOCAL" and question and final_result.response_text:
                try:
                    set_cached(question, final_result.response_text, route="LOCAL")
                except Exception:
                    pass  # Cache must never break execution
            
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
                self._write_json_state_files(route, error_result, context)
            except Exception:
                pass

            # Auto-feedback on error cases too
            if HAS_AUTO_FEEDBACK and question:
                try:
                    suggestion = analyze_answer_quality(
                        query=question,
                        route=route.route,
                        response_text="",
                        error_message=str(e),
                    )
                    if suggestion:
                        log_auto_feedback(suggestion)
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
        self._write_json_state_files(route, result, context)
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
        # Load medical domains from the allowlist file (cached by mtime)
        medical_domains_file = ROOT_DIR / "config" / "trust" / "generated" / "medical_runtime.txt"
        domains = _load_medical_domains(medical_domains_file)
        
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
        # Trust the router's final decision. Guards (e.g. social_greeting_override)
        # may have overridden an intent that incorrectly flagged needs_web.
        if intent.needs_web and route.route != "LOCAL":
            return False
        
        # Check output mode
        output_mode = context.get("output_mode", "CHAT")
        if output_mode != "CHAT":
            return False
        
        # Check if local_answer.sh or local_answer.py exists
        if not (self.LOCAL_ANSWER_SCRIPT.exists() or self.LOCAL_ANSWER_PY_SCRIPT.exists()):
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
        session_id = context.get("session_id", "default") or "default"
        
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
        session_memory, memory_telemetry = _load_session_memory_context_with_telemetry(question, session_id=session_id)
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
        if rc == 0 and response_formatter.is_local_generation_failure_output(raw_output):
            guard_trigger = "local_generation_failure_phrase"
            fallback_kind = "deterministic_local_prompt_fallback"
            outcome_code = "local_guard_fallback"
            local_force_plain_fallback = True
            response_text = self._runtime_local_prompt_fallback_text(question, "0")
        else:
            # Render the response
            response_text = response_formatter.render_chat_fast_from_raw(raw_output)
            response_text = self._local_fast_non_empty_guard(
                question, response_text, "CHAT"
            )
            response_text = self._local_fast_repetition_guard(
                question, response_text, "CHAT"
            )
            
            # Check for evidence style text (shouldn't happen in bypass)
            if response_formatter.is_evidence_style_text(response_text):
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
        session_id = context.get("session_id", "default") or "default"
        
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
                response_text = response_formatter.render_chat_fast_from_raw(raw_output)
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
            if route.route in ("FULL", "EVIDENCE", "NEWS", "AUGMENTED", "TIME", "WEATHER"):
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
            self._write_json_state_files(route, final_result, context)
            
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
                self._write_json_state_files(route, error_result, context)
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
        session_id = context.get("session_id", "default") or "default"

        is_medical_query = self._context_indicates_medical_query(context) or (
            route and route.evidence_reason in ("medical_safety", "medical_context")
        )
        
        # Step 1: Fetch evidence if needed
        evidence = None
        if route.route in ("EVIDENCE", "NEWS", "FULL", "AUGMENTED", "TIME", "WEATHER"):
            # Check if this is a voice query for voice-optimized content
            for_voice = context.get("surface") == "voice" if context else False
            evidence = await self._fetch_evidence(question, route, for_voice=for_voice)
        
        # Special handling for WEATHER route: return weather directly
        if route.route == "WEATHER":
            if evidence and evidence.get("ok"):
                return ExecutionResult(
                    status="completed",
                    outcome_code="answered",
                    route="WEATHER",
                    provider="weather",
                    provider_usage_class="free",
                    response_text=evidence["formatted"],
                    error_message="",
                    metadata={
                        "route_type": "weather_lookup",
                        "location": evidence.get("location"),
                        "temp_c": evidence.get("temp_c"),
                        "description": evidence.get("description"),
                        "real_route_preserved": True,
                    },
                )
            else:
                error_msg = evidence.get("error", "Unknown location") if evidence else "Could not fetch weather"
                return ExecutionResult(
                    status="completed",
                    outcome_code="error",
                    route="WEATHER",
                    provider="weather",
                    provider_usage_class="free",
                    response_text=f"Sorry, I couldn't fetch the weather. {error_msg}",
                    error_message=error_msg,
                    metadata={
                        "route_type": "weather_lookup_failed",
                        "real_route_preserved": True,
                    },
                )
        
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
        if route.route == "NEWS":
            if evidence and evidence.get("context"):
                # Use HTML for display (clean "Read more" links); fall back to plain text.
                # voice_text in metadata is used by TTS pipeline only.
                full_text = evidence.get("html_context") or evidence["context"]
                voice_text = ""
                articles = evidence.get("articles")
                if articles:
                    voice_parts = []
                    for a in articles:
                        title = a.get("title", "")
                        source = a.get("source", "")
                        desc = a.get("description", "")
                        part = f"{title}, from {source}."
                        if desc and len(desc) > 20:
                            part += f" {desc}"
                        voice_parts.append(part)
                    voice_text = " ".join(voice_parts)

                return ExecutionResult(
                    status="completed",
                    outcome_code="answered",
                    route="NEWS",
                    provider="news",
                    provider_usage_class="free",
                    response_text=full_text,
                    error_message="",
                    metadata={
                        "route_type": "news_live",
                        "evidence_fetched": True,
                        "evidence_title": "Latest News",
                        "evidence_url": "",
                        "trust_class": "unverified",
                        "real_route_preserved": True,
                        "news_source": evidence.get("provider", "unknown"),
                        "voice_text": voice_text,
                        "news_partial": evidence.get("partial", False),
                        "news_errors": evidence.get("errors"),
                    },
                )
            # News fetch failed — do not fall through to local model
            return ExecutionResult(
                status="failed",
                outcome_code="news_fetch_failed",
                route="NEWS",
                provider="news",
                provider_usage_class="free",
                response_text="Unable to fetch live news at this time. Please check your internet connection or try again later.",
                error_message="News provider returned no articles",
                metadata={
                    "route_type": "news_live_failed",
                    "real_route_preserved": True,
                },
            )
        
        # Step 2: Build augmented prompt with evidence
        prompt = response_formatter.build_augmented_prompt(question, evidence, route)
        
        # Step 3: Call appropriate provider
        session_memory = ""
        memory_telemetry: dict[str, Any] = {}
        if route.provider == "wikipedia":
            # Wikipedia routes do not consume session memory; skip the load
            # to avoid throwing away embedding/DB work.
            response = await self._call_wikipedia_provider_async(prompt, evidence, context)
        else:
            # Load session memory for providers that actually use it
            session_memory, memory_telemetry = _load_session_memory_context_with_telemetry(
                question, session_id=session_id
            )
            if session_memory:
                self._logger.debug(f"Loaded session memory ({len(session_memory)} chars)")

            if route.provider == "local":
                response = await self._call_local_model_async(prompt, context, session_memory, route_mode=route.route)
            elif route.provider in ("openai", "kimi"):
                # Prepend session memory to the prompt so API providers also see it
                api_prompt = prompt
                if session_memory.strip():
                    api_prompt = f"Session memory:\n{session_memory}\n\n{prompt}"
                response = await self._call_api_provider_async(route.provider, api_prompt, context)
                # Fallback to local model if paid provider returns an error
                if isinstance(response, str) and response.strip().lower().startswith("error"):
                    self._logger.warning(
                        f"{route.provider} returned error: {response[:120]}. Falling back to local model."
                    )
                    response = await self._call_local_model_async(prompt, context, session_memory, route_mode=route.route)
            else:
                # Default to local model
                response = await self._call_local_model_async(prompt, context, session_memory, route_mode=route.route)
        
        # Step 4: Validate response
        validated = response_formatter.validate_response(response, route)
        
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
        
        # For WEATHER route, fetch weather from wttr.in
        if route.route == "WEATHER":
            return await self._fetch_weather_evidence(question)
        
        # For TIME route, fetch current time from time API
        if route.route == "TIME":
            return await self._fetch_time_evidence(question)
        
        # For NEWS route, fetch live news from RSS sources
        if route.route == "NEWS":
            return await self._fetch_news_evidence(question, for_voice=for_voice)
        
        # For AUGMENTED news-synthesis requests, fetch news headlines as evidence
        # then fall back to the standard provider chain if news is unavailable
        if route.route == "AUGMENTED" and route.evidence_reason == "news_synthesis":
            news_ev = await self._fetch_news_evidence(question, for_voice=for_voice)
            if news_ev:
                return news_ev
        
        primary = route.provider
        if primary == "none" or not primary:
            primary = "wikipedia"
        
        # Build fallback chain matching _call_augmented_provider logic
        if primary == "wikipedia":
            chain = ["wikipedia", "openai", "kimi"]
        elif primary == "openai":
            chain = ["openai", "kimi", "wikipedia"]
        elif primary == "kimi":
            chain = ["kimi", "openai", "wikipedia"]
        elif primary == "trusted":
            chain = ["trusted", "wikipedia", "openai", "kimi"]
        else:
            chain = [primary, "wikipedia", "openai", "kimi"]
        
        last_error = ""
        for provider in chain:
            try:
                result: dict[str, Any] | None = None
                if provider == "trusted":
                    result = await self._fetch_trusted_evidence(question, route)
                elif provider == "wikipedia":
                    result = await self._fetch_wikipedia_evidence(question)
                elif provider == "kimi":
                    result = await self._fetch_api_evidence(question, "kimi")
                elif provider == "openai":
                    result = await self._fetch_api_evidence(question, "openai")
                
                if result:
                    self._logger.info(f"Evidence fetched successfully from {provider}")
                    return result
            except Exception as e:
                last_error = str(e)
                self._logger.warning(f"Evidence fetch failed for {provider}: {e}")
        
        self._logger.warning(f"All evidence providers failed. Last error: {last_error}")
        return None
    
    async def _fetch_wikipedia_evidence(self, question: str) -> dict[str, Any] | None:
        """Fetch evidence from Wikipedia (delegated to provider module)."""
        breaker = get_breaker("wikipedia")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for wikipedia")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_wikipedia_evidence(question)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"Wikipedia evidence fetch failed: {e}")
            return None
    
    async def _fetch_news_evidence(self, question: str, for_voice: bool = False) -> dict[str, Any] | None:
        """Fetch live news from RSS feeds (delegated to provider module)."""
        breaker = get_breaker("news_api")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for news_api")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_news_evidence(question, for_voice=for_voice)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"News evidence fetch failed: {e}")
            return None
    
    async def _fetch_time_evidence(self, question: str) -> dict[str, Any] | None:
        """Fetch current time from TimeAPI.io (delegated to provider module)."""
        breaker = get_breaker("time_api")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for time_api")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_time_evidence(question)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"Time evidence fetch failed: {e}")
            return None
    
    def _format_time_response(self, data: dict) -> str:
        """Format time API response into human-readable text (delegated to provider module)."""
        if HAS_PROVIDER_MODULES:
            return format_time_response(data)
        return f"Current time: {data.get('time', 'unknown')}"
    
    async def _fetch_weather_evidence(self, question: str) -> dict[str, Any] | None:
        """Fetch weather data from wttr.in (delegated to provider module)."""
        breaker = get_breaker("weather_api")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for weather_api")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_weather_evidence(question)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"Weather evidence fetch failed: {e}")
            return None
    
    async def _fetch_trusted_evidence(
        self,
        question: str,
        route: RoutingDecision,
    ) -> dict[str, Any] | None:
        """Fetch evidence from trusted sources (medical/veterinary domains).
        
        Uses the unverified_context_trusted.py provider with domain restrictions.
        Returns None if no evidence is found, signaling the caller to return
        an evidence-not-found response rather than falling back to general sources.
        """
        breaker = get_breaker("trusted_provider")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for trusted_provider")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_trusted_evidence(question, route)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"Trusted evidence fetch failed: {e}")
            return None
    
    async def _fetch_api_evidence(
        self,
        question: str,
        provider: str,
    ) -> dict[str, Any] | None:
        """Fetch evidence from API provider (Kimi or OpenAI) (delegated to provider module)."""
        breaker = get_breaker("api_provider")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for api_provider")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_api_evidence(question, provider, timeout=self.timeout)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"API evidence fetch failed: {e}")
            return None
    
    def _call_kimi_subprocess(self, question: str) -> dict[str, Any] | None:
        """Call Kimi provider via subprocess (delegated to provider module)."""
        if HAS_PROVIDER_MODULES:
            return call_kimi_subprocess(question, timeout=self.timeout)
        return None
    
    def _call_openai_subprocess(self, question: str) -> dict[str, Any] | None:
        """Call OpenAI provider via subprocess (delegated to provider module)."""
        if HAS_PROVIDER_MODULES:
            return call_openai_subprocess(question, timeout=self.timeout)
        return None
    
    async def _call_local_model_async(
        self,
        prompt: str,
        context: dict[str, Any],
        session_memory: str = "",
        route_mode: str = "LOCAL",
    ) -> str:
        """Call local model asynchronously using Python-native path (delegated to provider module)."""
        breaker = get_breaker("local_model")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for local_model")
            return "Error: Local model circuit breaker is OPEN."
        self._logger.debug(f"Calling local model async with prompt: {prompt[:50]}...")
        try:
            if HAS_PROVIDER_MODULES:
                configured_model = self.config.get("model")
                result = await call_local_model_async(
                    prompt=prompt,
                    context=context,
                    session_memory=session_memory,
                    route_mode=route_mode,
                    model=configured_model,
                )
                breaker._on_success()
                return response_formatter.render_chat_fast_from_raw(result)
            return "Error: Provider modules not available"
        except Exception as e:
            breaker._on_failure(e)
            self._logger.error(f"Local model call failed: {e}")
            raise
    
    async def _call_api_provider_async(
        self,
        provider: str,
        prompt: str,
        context: dict[str, Any],
    ) -> str:
        """Call API provider asynchronously (OpenAI or Kimi) (delegated to provider module)."""
        breaker = get_breaker("api_provider")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for api_provider")
            return f"Error: API provider circuit breaker is OPEN."
        self._logger.debug(f"Calling {provider} API async with prompt: {prompt[:50]}...")
        if not HAS_PROVIDER_MODULES:
            return f"Error: Provider modules not available"
        try:
            loop = asyncio.get_event_loop()
            if provider == "openai":
                result = await loop.run_in_executor(
                    None, call_openai_for_response, prompt, self.timeout
                )
            elif provider == "kimi":
                result = await loop.run_in_executor(
                    None, call_kimi_for_response, prompt, self.timeout
                )
            else:
                result = f"Error: Unknown provider {provider}"
            breaker._on_success()
            return result
        except Exception as e:
            breaker._on_failure(e)
            self._logger.error(f"API provider call failed: {e}")
            raise
    
    def _call_openai_for_response(self, prompt: str) -> str:
        """Call OpenAI for direct response (delegated to provider module)."""
        if HAS_PROVIDER_MODULES:
            return call_openai_for_response(prompt, timeout=self.timeout)
        return "Error: OpenAI tool not found"
    
    def _call_kimi_for_response(self, prompt: str) -> str:
        """Call Kimi for direct response (delegated to provider module)."""
        if HAS_PROVIDER_MODULES:
            return call_kimi_for_response(prompt, timeout=self.timeout)
        return "Error: Kimi tool not found"
    
    async def _call_wikipedia_provider_async(
        self,
        prompt: str,
        evidence: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> str:
        """Call Wikipedia provider asynchronously (delegated to provider module)."""
        self._logger.debug("Formatting Wikipedia response async")
        if HAS_PROVIDER_MODULES:
            return format_wikipedia_response(prompt, evidence, context)
        return "No Wikipedia information available for this query."
    
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
        
        # EVIDENCE route = strict trusted sources only (medical, veterinary)
        if route and route.route == "EVIDENCE":
            self._logger.info("EVIDENCE route: using strict trusted sources only")
            result = self._call_single_provider("trusted", question, intent, route, context)
            if result.status == "completed":
                return result
            # Trusted provider failed or not applicable — return evidence-not-found
            # Do NOT fall back to Wikipedia/OpenAI for EVIDENCE routes
            return ExecutionResult(
                status="completed",
                outcome_code="evidence_not_found",
                route="EVIDENCE",
                provider="trusted",
                provider_usage_class="local",
                response_text=(
                    "I couldn't find evidence from the designated trusted sources for this query.\n\n"
                    "For medical decisions, please consult a healthcare professional and verify "
                    "with authoritative sources such as:\n"
                    "- cochranelibrary.com\n"
                    "- dailymed.nlm.nih.gov\n"
                    "- jamanetwork.com\n"
                    "- medlineplus.gov\n"
                    "- nejm.org\n"
                    "- pubmed.ncbi.nlm.nih.gov"
                ),
                error_message="No evidence found in trusted sources",
                metadata={"providers_attempted": ["trusted"], "strict_evidence": True},
            )
        
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
            provider_chain = ["trusted", "wikipedia", "kimi", "openai"]
            self._logger.info(f"Category-specific query detected, trying trusted sources first")
        elif primary_provider == "wikipedia":
            provider_chain = ["wikipedia", "openai", "kimi"]
        elif primary_provider == "openai":
            provider_chain = ["openai", "kimi", "wikipedia"]
        elif primary_provider == "kimi":
            provider_chain = ["kimi", "openai", "wikipedia"]
        else:
            provider_chain = [primary_provider, "wikipedia", "kimi", "openai"]
        
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
        session_id = context.get("session_id", "default") or "default"
        self._logger.info(f"Trying provider: {provider}")

        # Circuit breaker for augmented provider subprocess
        breaker = get_breaker("augmented_provider")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning(f"Circuit breaker open for provider {provider}")
            return ExecutionResult(
                status="failed",
                outcome_code="circuit_open",
                route="AUGMENTED",
                provider=provider,
                provider_usage_class=self._provider_usage_class_for(provider),
                error_message=f"Circuit breaker open for provider {provider}",
                metadata={"provider": provider, "circuit_breaker": "augmented_provider"},
            )
        
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
                breaker._on_failure(Exception("provider_dispatch_failed"))
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
                breaker._on_failure(Exception("JSONDecodeError"))
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
                breaker._on_failure(Exception("provider_error"))
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
                question, depth="deep", mode="augmented", session_id=session_id
            )
            if session_memory:
                env["LUCY_SESSION_MEMORY_CONTEXT"] = session_memory
                self._logger.debug(f"Added session memory context ({len(session_memory)} chars)")
            
            local_result = self._call_local_worker(question, env)
            
            if local_result.returncode != 0:
                breaker._on_failure(Exception("local_worker_failed"))
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
            response_text = response_formatter.render_chat_fast_from_raw(local_result.stdout)
            
            breaker._on_success()
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
            breaker._on_failure(Exception("timeout"))
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
            breaker._on_failure(e)
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
        normalized = response_formatter.guard_normalize(response_text)
        insufficient_patterns = [
            "i could not generate a reply locally",
            "i don't have enough information",
            "i don't have the specific",
            "i don't have information",
            "i cannot provide",
            "this requires evidence mode",
            "insufficient evidence",
            "you may need to consult",
            "outside my training",
            "simulation tools",
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
    
    # ------------------------------------------------------------------
    # State persistence (delegated to StateWriter)
    # ------------------------------------------------------------------

    def _get_state_file_paths(self) -> tuple[Path, Path]:
        """Return (route_file, outcome_file) for the current namespace."""
        return self.state_writer.get_state_file_paths()

    def _write_state_files(
        self, route: RoutingDecision, result: ExecutionResult, context: dict[str, Any]
    ) -> None:
        """Dual-write execution state to SQLite and/or legacy .env files."""
        self.state_writer.write_state(route, result, context)

    def _write_json_state_files(
        self, route: RoutingDecision, result: ExecutionResult, context: dict[str, Any]
    ) -> None:
        """Write HMI-facing JSON state files (last_request_result, last_route, request_history)."""
        self.state_writer.write_json_state_files(route, result, context)

    def _write_state_to_sqlite(
        self, route: RoutingDecision, result: ExecutionResult, context: dict[str, Any]
    ) -> None:
        """Write state to SQLite via StateManager."""
        self.state_writer._write_state_to_sqlite(route, result, context)

    def _write_state_to_files(
        self, route: RoutingDecision, result: ExecutionResult, context: dict[str, Any]
    ) -> None:
        """Write execution state to file-based storage."""
        self.state_writer._write_state_to_files(route, result, context)

    def read_last_route_from_sqlite(self) -> dict | None:
        """Read last route from SQLite."""
        return self.state_writer.read_last_route()

    def read_last_outcome_from_sqlite(self) -> dict | None:
        """Read last outcome from SQLite."""
        return self.state_writer.read_last_outcome()

    def verify_state_consistency(self) -> bool:
        """Verify SQLite and file-based states match."""
        return self.state_writer.verify_consistency()

    def _record_terminal_outcome(
        self,
        outcome_code: str,
        mode: str,
        error_msg: str | None = None,
        execution_time_ms: int = 0,
    ) -> None:
        """Record terminal outcome for early-exit paths."""
        self.state_writer.record_terminal_outcome(outcome_code, mode, error_msg, execution_time_ms)

    def close(self) -> None:
        """Close the execution engine and cleanup resources."""
        self.state_writer.close()

    def _read_state_field(self, state_file: Path, field: str) -> str | None:
        """Read a field value from a state file."""
        return self.state_writer._read_state_field(state_file, field)
    
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
        qn = response_formatter.guard_normalize(question)
        bn = response_formatter.guard_normalize(body)
        
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
        n = response_formatter.guard_normalize(body)
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
        qn = response_formatter.guard_normalize(question)
        
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
    
    # ======================================================================
    # Utility Functions (delegated to execution_engine_utils)
    # ======================================================================

    _is_truthy = staticmethod(is_truthy)
    _sha256_text = staticmethod(sha256_text)
    _deterministic_pick_index = staticmethod(deterministic_pick_index)
    _provider_usage_class_for = staticmethod(provider_usage_class_for)
    _is_category_specific_query = staticmethod(is_category_specific_query)
    _normalize_augmentation_policy = staticmethod(normalize_augmentation_policy)
    _local_fast_guard_normalize = staticmethod(local_fast_guard_normalize)


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
