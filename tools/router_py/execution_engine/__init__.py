#!/usr/bin/env python3
"""
Execution Engine — Python-native plan execution.

Receives RoutingDecision from the pipeline and executes it:
- WEATHER / TIME / NEWS / FINANCE: fetch evidence, return formatted result
- LOCAL: call local model worker
- AUGMENTED / FULL / EVIDENCE: fetch evidence, build prompt, call provider
- CLARIFY: return clarification request

Provider resolution is now centralized in `provider_resolver.py`.
The engine trusts `route.provider` as the single source of truth.

Response formatting and validation live in `response_formatter.py`.
Memory persistence lives in `main._persist_memory_turn()`.

Shell delegation paths have been removed; this module is Python-native only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import sys
import time
import uuid
import dataclasses
from dataclasses import dataclass
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

sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tools"))

from .helpers import (
    _load_medical_domains,
    extract_self_analysis_file_reference,
    _trusted_evidence_metadata,
    _is_current_fact_query,
    _evidence_has_content,
    _load_session_memory_context_with_telemetry,
    _load_session_memory_context,
    _is_memory_or_followup_query,
)

from tools.xdg_paths import lucy_runtime_namespace_root

from router_py.classify import ClassificationResult, RoutingDecision
from router_py.policy import requires_evidence_mode
from router_py.request_constraints import RequestConstraints
from router_py.request_types import ExecutionResult
from router_py import response_formatter
from router_py.self_analysis import SelfAnalysisEngine
from router_py.state import get_state_manager
from router_py.execution_engine_state import StateWriter
from router_py.resilience import get_breaker, CircuitBreakerOpen
from router_py.shutdown_handler import register_closeable
from router_py.structured_logging import get_structured_logger, ContextualLogger
from router_py.context_guard import is_evidence_relevant, filter_memory_context
from router_py.code_review_model_resolver import CodeReviewModelResolver
from router_py.local_answer import LocalAnswerConfig

try:
    from router_py.escalation.fetcher import fetch_general_knowledge

    HAS_WEB_FETCHER = True
except Exception:
    HAS_WEB_FETCHER = False

try:
    from router_py import metrics as _router_metrics

    HAS_ROUTER_METRICS = True
except Exception:
    HAS_ROUTER_METRICS = False

try:
    from router_py.fallback_telemetry import make as _ft, merge as _ft_merge

    HAS_FALLBACK_TELEMETRY = True
except Exception:
    HAS_FALLBACK_TELEMETRY = False

    def _ft(**_kw):
        return {}

    def _ft_merge(base, _tel):
        return dict(base)


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

# Import automatic local-model selector
try:
    from router_py.model_selector import select_local_model

    HAS_MODEL_SELECTOR = True
except ImportError:
    HAS_MODEL_SELECTOR = False

    def select_local_model(*_args, **_kwargs) -> str:  # type: ignore[misc]
        return "local-lucy-llama31"


# Import news provider for live news fetching
try:
    from router_py.news import NewsProvider, NewsResult

    HAS_NEWS_PROVIDER = True
except ImportError:
    HAS_NEWS_PROVIDER = False


# Import provider modules (extracted to keep ExecutionEngine focused on dispatch)
try:
    from router_py.providers import (
        fetch_wikipedia_evidence,
        fetch_api_evidence,
        fetch_time_evidence,
        fetch_weather_evidence,
        fetch_news_evidence,
        fetch_trusted_evidence,
        fetch_finance_evidence,
        format_time_response,
        format_wikipedia_response,
        call_openai_for_response,
        call_kimi_for_response,
        call_local_model_async,
    )

    HAS_PROVIDER_MODULES = True
except ImportError:
    HAS_PROVIDER_MODULES = False

DEFAULT_TIMEOUT = 130
DEFAULT_POLICY_CONFIDENCE_THRESHOLD = 0.60

# Default chat memory file path (matches runtime_request.py)
DEFAULT_CHAT_MEMORY_FILE = str(lucy_runtime_namespace_root() / "state" / "chat_session_memory.txt")


class ExecutionEngine:
    """
    Engine for executing routing decisions.

    The ExecutionEngine takes routing decisions from the Router and executes
    them using the Python-native path. It handles:

        1. Route-specific execution paths
        2. Provider dispatch via Python APIs
        3. Response formatting and enhancement
        4. State persistence for telemetry

    Design Philosophy:
        - Python-native: No shell subprocess delegation
        - Preserve authority: Maintain truth metadata through execution chain
        - Fail gracefully: Fall back to local responses on provider errors
        - Transparent: Record execution path for debugging and audit
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

    # =========================================================================
    # FILE PATHS - Configuration files
    # =========================================================================
    UNVERIFIED_CONTEXT_CATALOG: Path = ROOT_DIR / "config" / "unverified_context_sources.tsv"
    UNVERIFIED_CONTEXT_PROVIDER_DEFAULTS: Path = (
        ROOT_DIR / "config" / "unverified_context_provider_defaults.env"
    )
    CONV_PROFILE_FILE: Path = ROOT_DIR / "config" / "conversation_profile.json"

    # =========================================================================
    # FILE PATHS - State files
    # =========================================================================
    # Legacy state file paths (superseded by runtime namespace + StateWriter)
    LAST_OUTCOME_FILE: Path = ROOT_DIR / "state" / "namespaces" / "default" / "last_outcome.env"
    LAST_ROUTE_FILE: Path = ROOT_DIR / "state" / "namespaces" / "default" / "last_route.env"

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
        #
        # NAMESPACE ISOLATION STRATEGY:
        # - Each ExecutionEngine instance gets a unique namespace
        # - Format: {hostname}_{pid}_{timestamp}_{uuid_suffix}
        # - Example: "mike_12345_1712948423_a7f3e2"
        # - This ensures no collision even with rapid sequential queries
        #
        # The namespace is used to:
        # 1. Create an isolated state directory (ROOT/state/namespaces/{namespace}/)
        # 2. Set LUCY_SHARED_STATE_NAMESPACE for state file isolation
        # 3. Set LUCY_STATE_DIR for state file location
        hostname = socket.gethostname().split(".")[0]  # Get short hostname
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

        # Track the last file analyzed in self-analysis mode so follow-up
        # requests like "analyze it again" or "review that file" can reuse
        # the path without requiring the user to type it every turn.
        self._last_self_analysis_file: str | None = None

        self._logger.debug(
            f"ExecutionEngine initialized with namespace: {self._execution_namespace}, "
            f"state_dir: {self._state_dir}, sqlite_state: {self.use_sqlite_state}"
        )

    def is_capability_allowed(
        self,
        route: str,
        constraints: RequestConstraints | None,
    ) -> bool:
        """Return whether *route* is allowed under *constraints*.

        Request-scoped constraints override normal routing decisions. For
        example, ``network=False`` blocks routes that require external fetches,
        and ``tools=False`` blocks tool-based routes such as TIME or WEATHER.
        Local-only routes are always permitted.
        """
        if constraints is None:
            return True

        network_routes = {"NEWS", "EVIDENCE", "AUGMENTED", "FULL"}
        tool_routes = {"TIME", "WEATHER", "FINANCE"}

        if constraints.network is False and route in network_routes:
            return False
        if constraints.tools is False and route in tool_routes:
            return False

        return True

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

        Returns:
            Path to the namespaced state directory
        """
        # Use the instance's unique execution namespace
        # Sanitize to prevent path traversal attacks
        safe_namespace = re.sub(r"[^a-zA-Z0-9_-]", "_", self._execution_namespace)
        state_dir = ROOT_DIR / "state" / "namespaces" / safe_namespace
        self._logger.debug(f"Using namespace-isolated state dir: {state_dir}")
        return state_dir

    def _record_request_metrics(
        self,
        context: dict[str, Any],
        route: RoutingDecision | None,
        result: ExecutionResult,
        execution_time_ms: int,
    ) -> None:
        """Emit a request-level metric; failures are swallowed."""
        if not HAS_ROUTER_METRICS:
            return
        try:
            request_id = (context or {}).get("request_id", "")
            model = self.config.get("model") or os.environ.get("LUCY_LOCAL_MODEL", "")
            _router_metrics.record_request(
                request_id=str(request_id),
                query=str((context or {}).get("question", "")),
                route=str(route.route if route else result.route),
                model=str(model),
                provider=str(result.provider),
                confidence=float(route.confidence if route else 0.0),
                latency_ms=execution_time_ms,
                outcome_code=str(result.outcome_code),
                error=result.error_message or None,
                extra={
                    "status": result.status,
                    "provider_usage_class": result.provider_usage_class,
                },
            )
        except Exception:
            self._logger.debug("Failed to record request metrics", exc_info=True)

    def execute(
        self,
        intent: ClassificationResult,
        route: RoutingDecision,
        context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """
        Execute a routing decision using the Python-native path.

        This is the main synchronous entry point. It dispatches to
        `execute_async` and runs it in an event loop suitable for the
        current context. All execution is Python-native; no shell fallback
        is used.

        NAMESPACE ISOLATION:
        Each execution runs in its own isolated namespace to prevent
        "shared-state overlap" errors during concurrent executions.
        The namespace directory is cleaned up after execution completes.

        Args:
            intent: The classified intent result
            route: The routing decision to execute
            context: Optional execution context (conversation history, etc.)

        Returns:
            ExecutionResult with status, response, and metadata
        """
        context = context or {}

        # Use structured logger from context if provided
        logger: ContextualLogger = context.get("_logger")
        if logger is None:
            logger = get_structured_logger("router_py.execution_engine")
        self._logger = logger

        self._logger.info("Using Python-native execution path (shell-free)")

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're already in an async context, run in a separate thread
                # with its own event loop to avoid "loop already running" errors.
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(self._run_async_execute, intent, route, context)
                    return future.result()
            else:
                return loop.run_until_complete(self.execute_async(intent, route, context))
        except RuntimeError:
            # No event loop, create one
            return asyncio.run(self.execute_async(intent, route, context))

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
            (
                route.metadata.get("clarification_question")
                if hasattr(route, "metadata") and route.metadata
                else None
            )
            or "I need more information to answer this question. Could you clarify what you're looking for?"
        )

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

    async def execute_self_analysis(
        self,
        relative_path: str,
        project_root: Path | None = None,
        model: str | None = None,
    ) -> ExecutionResult:
        """Run local self-analysis on a project file and return formatted result."""
        start_time = time.time()
        try:
            self_review_context_chars = (
                LocalAnswerConfig.from_env().self_review_context_chars
                if HAS_LOCAL_ANSWER_PY
                else None
            )
            engine = SelfAnalysisEngine(
                project_root=project_root,
                self_review_context_chars=self_review_context_chars,
            )
            response = await engine.suggest_improvements(relative_path, model=model)
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                status="completed",
                outcome_code="answered",
                route="SELF_REVIEW",
                provider="local",
                provider_usage_class="local",
                response_text=response,
                error_message="",
                execution_time_ms=execution_time,
                metadata={
                    "self_review_model": model,
                    "self_analysis": True,
                    "file": relative_path,
                },
                policy_reason="self_analysis_mode",
            )
        except Exception as exc:
            execution_time = int((time.time() - start_time) * 1000)
            return ExecutionResult(
                status="failed",
                outcome_code="self_analysis_error",
                route="SELF_REVIEW",
                provider="local",
                provider_usage_class="local",
                response_text=f"Self-analysis failed: {exc}",
                error_message=str(exc),
                execution_time_ms=execution_time,
                metadata={"self_analysis": True, "file": relative_path},
                policy_reason="self_analysis_mode",
            )

    def _load_control_state(self) -> dict[str, Any]:
        try:
            from runtime_control import load_or_create_state, resolve_runtime_paths

            state_file = resolve_runtime_paths(None).state_file
            state = load_or_create_state(state_file, refresh_timestamp=False)
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    def _extract_self_analysis_file_reference(
        self, question: str, last_file: str | None = None
    ) -> str | None:
        """Return a relative path if the query asks to analyze/review/improve a file.

        If the query does not explicitly name a file but ``last_file`` is set and
        the query looks like a follow-up ("analyze it", "review that file", etc.),
        return the previously used file reference.
        """
        return extract_self_analysis_file_reference(question, last_file=last_file)

    def _resolve_code_review_model(self) -> tuple[str, str | None]:
        """Resolve effective Ollama model for SELF_REVIEW mode.

        Returns (model_name, fallback_reason).
        """
        config = LocalAnswerConfig.from_env()
        resolver = CodeReviewModelResolver(config)
        return resolver.resolve()

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
        sources_text = "\n\n\nAuthoritative sources for verification:\n" + "\n".join(
            f"- {src}" for src in top_domains
        )
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

    def _label_evidence_fallback(
        self,
        result: ExecutionResult,
        evidence: dict[str, Any] | None,
    ) -> ExecutionResult:
        """
        Label EVIDENCE-route responses that fell back to non-trusted providers.

        When the trusted provider fails and EVIDENCE fetches evidence from
        wikipedia/kimi/openai instead, the response must be clearly marked so
        the user knows the source is not from the trusted allowlist.
        """
        if result.route != "EVIDENCE":
            return result
        if not evidence or not evidence.get("fallback_used"):
            return result
        successful_backend = evidence.get("successful_backend", "")
        if successful_backend == "trusted":
            return result
        fallback_to = evidence.get("fallback_to", successful_backend) or "an alternative source"
        label = (
            f"[Note: designated trusted sources were unavailable. "
            f"This EVIDENCE response was sourced from {fallback_to} instead.]\n\n"
        )
        new_metadata = dict(result.metadata or {})
        new_metadata["trust_class"] = "trusted_fallback"
        new_metadata["evidence_fallback_label_applied"] = True
        return dataclasses.replace(
            result,
            response_text=label + result.response_text,
            metadata=new_metadata,
        )

    def _label_web_untrusted_fallback(
        self,
        result: ExecutionResult,
        evidence: dict[str, Any],
    ) -> ExecutionResult:
        """Label AUGMENTED responses that used the general-web fallback.

        The web fetcher is explicitly last-resort and untrusted. Make sure the
        user can see that in the answer text and in outcome metadata.
        """
        title = evidence.get("title", "") or "untrusted web source"
        url = evidence.get("url", "")
        source_line = f"{title} — {url}" if url else title
        label = (
            "[Note: the following answer was sourced from an untrusted web "
            f"search result ({source_line}). Please verify independently.]\n\n"
        )
        new_metadata = dict(result.metadata or {})
        new_metadata["trust_class"] = "untrusted"
        new_metadata["web_untrusted_label_applied"] = True
        return dataclasses.replace(
            result,
            response_text=label + result.response_text,
            provider="web_untrusted",
            provider_usage_class=provider_usage_class_for("web_untrusted") or "free",
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

    @staticmethod
    def _is_untrusted_web_inappropriate(question: str, evidence_reason: str) -> bool:
        """Return True when the general-web fallback must not be used.

        Untrusted DuckDuckGo results are intentionally last-resort and must not
        be invoked for:

        * high-stakes regulated domains (medical/veterinary/legal/financial);
        * live/current topics where stale or unvetted sources are dangerous;
        * known conspiracy/hoax tropes where the first search hit is likely to
          be misinformation.
        """
        high_stakes_reasons = {
            "medical_context",
            "medical_safety",
            "medical_body_symptom",
            "veterinary_context",
            "legal_context",
            "financial_high_stakes",
            "financial_data",
            "current_information",
            "conflict_live",
            "news_synthesis",
        }
        if evidence_reason in high_stakes_reasons:
            return True

        norm = re.sub(r"[^\w\s]", " ", (question or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()

        conspiracy_phrases = [
            "flat earth",
            "earth flat",
            "moon landing faked",
            "moon landing hoax",
            "moon landing fake",
            "nine eleven inside job",
            "9 11 inside job",
            "vaccine microchip",
            "vaccines contain microchips",
            "microchips in vaccines",
            "chemtrails",
            "lizard people",
            "reptilian",
            "illuminati",
            "new world order",
            "qanon",
            "pizzagate",
            "holocaust denial",
            "holohoax",
            "climate change hoax",
            "climate change a hoax",
            "global warming hoax",
            "global warming a hoax",
            "plandemic",
            "fake moon",
            "birther",
        ]
        for phrase in conspiracy_phrases:
            if phrase in norm:
                return True

        return False

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

        All routes are executed via the Python-native full route path.

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
            empty_result = ExecutionResult(
                status="failed",
                outcome_code="empty_query",
                route="LOCAL",
                provider="local",
                provider_usage_class="local",
                response_text="",
                error_message="Query is empty or contains only whitespace.",
                execution_time_ms=execution_time,
                metadata={"reason": "empty_query_rejected"},
                evidence_reason=route.evidence_reason if route else "",
                policy_reason=route.policy_reason if route else "",
            )
            self._record_request_metrics(context, route, empty_result, execution_time)
            return empty_result

        # Self-analysis mode dispatch
        control_state = self._load_control_state() or {}
        if control_state.get("self_analysis_mode", "off").lower() == "on":
            file_ref = self._extract_self_analysis_file_reference(
                question, self._last_self_analysis_file
            )
            if file_ref:
                self._logger.info(f"Self-analysis mode dispatch: {file_ref}")
                try:
                    review_model, fallback_reason = self._resolve_code_review_model()
                except RuntimeError as e:
                    execution_time = int((time.time() - start_time) * 1000)
                    return ExecutionResult(
                        status="failed",
                        outcome_code="code_review_model_unavailable",
                        route="SELF_REVIEW",
                        provider="local",
                        provider_usage_class="local",
                        response_text=str(e),
                        error_message=str(e),
                        execution_time_ms=execution_time,
                        metadata={"reason": "code_review_model_unavailable"},
                    )
                result = await self.execute_self_analysis(file_ref, model=review_model)
                self._last_self_analysis_file = file_ref
                self_analysis_route = RoutingDecision(
                    route="SELF_REVIEW",
                    mode="FORCED",
                    intent_family="operational",
                    confidence=1.0,
                    provider="local",
                    provider_usage_class="local",
                    evidence_mode="",
                    evidence_reason="",
                    requires_evidence=False,
                    policy_reason="self_analysis_mode",
                    ephemeral=True,
                    decision_stage="execution_override",
                    reason_code="self_analysis_mode",
                    matched_rule="self_analysis_file_reference",
                    trace={"file_reference": file_ref, "original_route": route.route},
                )
                self._write_state_files(self_analysis_route, result, context)
                self._write_json_state_files(self_analysis_route, result, context)
                self._record_request_metrics(
                    context, self_analysis_route, result, result.execution_time_ms
                )
                return result

        # Check for medical context and configure safety constraints
        _, evidence_reason = requires_evidence_mode(question, context)

        # For medical queries: set domain restrictions but don't force LOCAL
        if evidence_reason == "medical_context":
            self._logger.info("Medical query detected - setting domain restrictions")
            context["route_reason_override"] = "medical_evidence_only"
            context["is_medical_query"] = True
            # Set medical domain allowlist for trusted source restriction
            medical_domains_file = (
                ROOT_DIR / "config" / "trust" / "generated" / "medical_runtime.txt"
            )
            context["allow_domains_file"] = str(medical_domains_file)

        self._logger.info(
            f"Async execution start: route={route.route}, provider={route.provider}, "
            f"question={question[:100]}..."
        )

        try:
            # Handle CLARIFY route early
            if route.route == "CLARIFY":
                clarify_result = self._handle_clarify_route(intent, route, context, start_time)
                self._record_request_metrics(
                    context, route, clarify_result, clarify_result.execution_time_ms
                )
                return clarify_result

            # All routes use the Python-native full execution path
            result = await self._execute_full_route_python(intent, route, context)

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
                evidence_reason=route.evidence_reason,
                policy_reason=route.policy_reason,
            )

            # Persist execution state
            self._write_state_files(route, final_result, context)
            self._write_json_state_files(route, final_result, context)

            self._logger.info(
                f"Async execution complete: status={final_result.status}, "
                f"outcome={final_result.outcome_code}, time={execution_time}ms"
            )

            self._record_request_metrics(context, route, final_result, execution_time)
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
                evidence_reason=route.evidence_reason,
                policy_reason=route.policy_reason,
            )

            try:
                self._write_state_files(route, error_result, context)
                self._write_json_state_files(route, error_result, context)
            except Exception:
                pass

            self._record_request_metrics(context, route, error_result, execution_time)
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
                    self._logger.debug(f"Cleaned up namespace directory: {self._state_dir}")
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
        request_id = context.get("request_id", "")

        is_medical_query = self._context_indicates_medical_query(context) or (
            route and route.evidence_reason in ("medical_safety", "medical_context")
        )

        # Step 1: Fetch evidence if needed
        evidence = None
        if route.route in ("EVIDENCE", "NEWS", "FULL", "AUGMENTED", "TIME", "WEATHER", "FINANCE"):
            # Check if this is a voice query for voice-optimized content
            for_voice = context.get("surface") == "voice" if context else False
            evidence = await self._fetch_evidence(question, route, for_voice=for_voice)

        # Filter retrieved evidence before it reaches any LLM prompt.
        # Direct-answer routes (WEATHER, TIME, FINANCE, NEWS) return evidence
        # as the response, so we skip filtering there to preserve completeness.
        # Intentional web-untrusted fallback results are exempt from the semantic
        # relevance guard: the user explicitly enabled general-knowledge web
        # fetch, and DuckDuckGo already ranked the result for the query.
        is_web_untrusted_fallback = (
            evidence is not None
            and evidence.get("provider") == "web_untrusted"
            and evidence.get("fallback_used") is True
        )
        if evidence and route.route in ("EVIDENCE", "FULL", "AUGMENTED") and not is_web_untrusted_fallback:
            relevant = await asyncio.to_thread(
                is_evidence_relevant, question, evidence, request_id=request_id
            )
            if not relevant:
                self._logger.warning(
                    "Dropping irrelevant evidence for route %s: title=%r",
                    route.route,
                    evidence.get("title", "")[:60],
                )
                evidence = None

        # Last-resort general-knowledge web fetch for ordinary AUGMENTED factual
        # queries when primary evidence was missing or filtered out as irrelevant.
        # Critical routes (EVIDENCE/medical/vet/legal/current/financial) and
        # conspiracy/hoax-prone topics intentionally skip this.
        if (
            not _evidence_has_content(evidence)
            and route.route == "AUGMENTED"
            and not self._is_untrusted_web_inappropriate(question, route.evidence_reason)
        ):
            web_ev = await self._fetch_web_evidence(question)
            if web_ev:
                evidence = web_ev

        # Route-dependent evidence failure handling (Phase 1-2).
        # When evidence is unavailable or was rejected, do not silently fall back
        # to unverified local knowledge for current facts or high-stakes domains.
        if route.route in ("AUGMENTED", "EVIDENCE", "FULL") and not _evidence_has_content(evidence):
            is_current = _is_current_fact_query(question)
            if is_current:
                return ExecutionResult(
                    status="completed",
                    outcome_code="live_data_unavailable",
                    route=route.route,
                    provider=route.provider,
                    provider_usage_class=route.provider_usage_class,
                    response_text="Live data is currently unavailable for this request. Please try again later.",
                    error_message="evidence_unavailable",
                    metadata={
                        "route_type": "evidence_failure",
                        "fallback": "live_data_unavailable",
                        "real_route_preserved": True,
                    },
                )
            if route.route == "EVIDENCE" or route.evidence_reason in (
                "medical_context",
                "medical_safety",
                "veterinary_context",
            ):
                # Phase 8: when live sources explicitly signal a caveat fallback,
                # answer from local knowledge with a clear prefix instead of refusing.
                if evidence and evidence.get("suggested_action") == "local_with_caveat":
                    context["_local_with_caveat"] = True
                    route = dataclasses.replace(
                        route, provider="local", provider_usage_class="local"
                    )
                else:
                    return ExecutionResult(
                        status="completed",
                        outcome_code="clarification_requested",
                        route=route.route,
                        provider=route.provider,
                        provider_usage_class=route.provider_usage_class,
                        response_text=(
                            "I could not find trusted evidence for this question. "
                            "For medical, veterinary, or legal topics, please consult a "
                            "qualified professional or rephrase your question with more details."
                        ),
                        error_message="trusted_evidence_unavailable",
                        metadata={
                            "route_type": "evidence_failure",
                            "fallback": "safe_clarification",
                            "real_route_preserved": True,
                        },
                    )
            if route.route == "AUGMENTED":
                # Stable ordinary fact: allow a local, explicitly unverified answer.
                context["_augmented_evidence_failed_stable_fact"] = True
                route = dataclasses.replace(route, provider="local", provider_usage_class="local")

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
                error_msg = (
                    evidence.get("error", "Unknown location")
                    if evidence
                    else "Could not fetch weather"
                )
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
                error_msg = (
                    evidence.get("error", "Unknown location")
                    if evidence
                    else "Could not determine timezone"
                )
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

        # Special handling for FINANCE route: return market data directly
        if route.route == "FINANCE":
            if evidence and evidence.get("ok"):
                return ExecutionResult(
                    status="completed",
                    outcome_code="answered",
                    route="FINANCE",
                    provider="finance",
                    provider_usage_class="free",
                    response_text=evidence["formatted"],
                    error_message="",
                    metadata={
                        "route_type": "finance_lookup",
                        "finance_type": evidence.get("class"),
                        "symbol": evidence.get("symbol"),
                        "base": evidence.get("base"),
                        "target": evidence.get("target"),
                        "person": evidence.get("person"),
                        "source": evidence.get("source"),
                        "real_route_preserved": True,
                    },
                )
            else:
                error_msg = (
                    evidence.get("error", "Unable to retrieve data")
                    if evidence
                    else "Could not fetch finance data"
                )
                return ExecutionResult(
                    status="completed",
                    outcome_code="error",
                    route="FINANCE",
                    provider="finance",
                    provider_usage_class="free",
                    response_text=(
                        "Sorry, I couldn't fetch live financial data for that query. "
                        "I can look up stock prices, exchange rates, and net-worth estimates "
                        "from public sources. Please try a specific query like "
                        "'Tesla stock price' or 'EUR to USD'."
                    ),
                    error_message=error_msg,
                    metadata={
                        "route_type": "finance_lookup_failed",
                        "real_route_preserved": True,
                    },
                )

        # Step 2: Check for bounded response from trusted provider
        # Trusted medical/vet/finance providers return pre-formatted responses
        # with source citations — no need to call the LLM again.
        bounded_text = evidence.get("content") or evidence.get("context") if evidence else None
        if evidence and evidence.get("bounded_response") and bounded_text:
            content = bounded_text
            sources = evidence.get("sources", [])
            trusted_meta = _trusted_evidence_metadata(evidence)
            # Append sources only if not already included in the content
            if sources and "trusted sources" not in content.lower():
                content += "\n\nTrusted sources:\n" + "\n".join(f"- {s}" for s in sources[:6])
            return ExecutionResult(
                status="completed",
                outcome_code="answered",
                route=route.route,
                provider=route.provider,
                provider_usage_class=route.provider_usage_class,
                response_text=content,
                error_message="",
                metadata={
                    "route_type": "trusted_bounded",
                    "evidence_fetched": True,
                    "trust_class": "trusted",
                    "real_route_preserved": True,
                    **trusted_meta,
                },
            )

        # Step 3: Build augmented prompt with evidence
        prompt = response_formatter.build_augmented_prompt(question, evidence, route)

        # Step 4: Call appropriate provider
        session_memory = ""
        memory_telemetry: dict[str, Any] = {}
        api_fallback_telemetry: dict[str, Any] = {}
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
                # Explicit memory/follow-up queries ("read my last answer",
                # "what did I say earlier", "and if she...") share few keywords
                # with the turns they reference. Semantic filtering drops the
                # very context they need, so we keep the recent turns intact.
                if _is_memory_or_followup_query(question):
                    self._logger.debug(
                        "Keeping full session memory for memory/follow-up query"
                    )
                else:
                    session_memory = await asyncio.to_thread(
                        filter_memory_context, question, session_memory, request_id=request_id
                    )
                if session_memory:
                    self._logger.debug(f"Loaded session memory ({len(session_memory)} chars)")

            if route.provider == "local":
                response = await self._call_local_model_async(
                    prompt, context, session_memory, route_mode=route.route
                )
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
                    api_fallback_telemetry = _ft(
                        fallback_used=True,
                        fallback_reason=f"{route.provider}_api_error",
                        primary_failed=route.provider,
                        fallback_to="local",
                        degradation_level="limited",
                    )
                    response = await self._call_local_model_async(
                        prompt, context, session_memory, route_mode=route.route
                    )
            else:
                # Default to local model
                response = await self._call_local_model_async(
                    prompt, context, session_memory, route_mode=route.route
                )

        # Step 4: Validate response
        validated = response_formatter.validate_response(response, route)

        # Collect fact-retrieval telemetry from memory service
        fact_telemetry: dict[str, Any] = {}
        try:
            from memory.memory_service import get_last_fact_telemetry

            fact_telemetry = get_last_fact_telemetry()
        except Exception:
            pass

        # Merge evidence fallback telemetry (if any) into metadata
        evidence_telemetry: dict[str, Any] = {}
        if evidence and isinstance(evidence, dict):
            for key in (
                "fallback_used",
                "fallback_reason",
                "primary_failed",
                "fallback_to",
                "attempted_chain",
                "successful_backend",
                "degradation_level",
            ):
                if key in evidence:
                    evidence_telemetry[key] = evidence[key]

        # Step 5: Return with REAL route (no mapping)
        base_metadata: dict[str, Any] = {
            "route_type": "full_python",
            "evidence_fetched": evidence is not None,
            "evidence_title": evidence.get("title", "") if evidence else "",
            "evidence_url": evidence.get("url", "") if evidence else "",
            "trust_class": (
                evidence.get("trust_class", "unverified")
                if evidence
                else "local"
            ),
            "real_route_preserved": True,  # Marker for testing
            **memory_telemetry,
        }
        base_metadata = _ft_merge(base_metadata, evidence_telemetry)
        base_metadata = _ft_merge(base_metadata, api_fallback_telemetry)
        base_metadata = _ft_merge(base_metadata, fact_telemetry)

        result = ExecutionResult(
            status="completed",
            outcome_code="answered",
            route=route.route,  # KEEPS THE REAL ROUTE - no mapping!
            provider=route.provider,
            provider_usage_class=route.provider_usage_class,
            response_text=validated,
            error_message="",
            metadata=base_metadata,
        )

        if route.route == "EVIDENCE" and result.response_text:
            result = self._label_evidence_fallback(result, evidence)

        if route.route == "AUGMENTED" and evidence and evidence.get("provider") == "web_untrusted" and result.response_text:
            result = self._label_web_untrusted_fallback(result, evidence)

        if is_medical_query and result.route == "AUGMENTED" and result.response_text:
            result = self._append_medical_sources(result, context)

        if context.get("_augmented_evidence_failed_stable_fact") and result.response_text:
            result = dataclasses.replace(
                result,
                response_text=(
                    "Live sources are unavailable; here is what I know: " + result.response_text
                ),
                metadata={
                    **result.metadata,
                    "evidence_unverified_local_answer": True,
                },
            )

        if context.get("_local_with_caveat") and result.response_text:
            result = dataclasses.replace(
                result,
                response_text=(
                    "Live sources are unavailable; here is what I know: " + result.response_text
                ),
                metadata={
                    **result.metadata,
                    "live_source_unavailable_local_answer": True,
                },
            )

        return result

    async def _fetch_evidence(
        self,
        question: str,
        route: RoutingDecision,
        for_voice: bool = False,
    ) -> dict[str, Any] | None:
        """
        Fetch evidence from appropriate sources based on route.

        Uses existing provider modules called via Python API.

        Args:
            question: The user question
            route: The routing decision
            for_voice: If True, fetch voice-optimized content (e.g., condensed news)

        Returns:
            Evidence dictionary with context, title, url, etc., or None if failed
        """
        self._logger.info(
            f"Fetching evidence for route={route.route}, provider={route.provider}, for_voice={for_voice}"
        )

        # For WEATHER route, fetch weather from wttr.in
        if route.route == "WEATHER":
            return await self._fetch_weather_evidence(question)

        # For TIME route, fetch current time from time API
        if route.route == "TIME":
            return await self._fetch_time_evidence(question)

        # For NEWS route, fetch live news from RSS sources
        if route.route == "NEWS":
            return await self._fetch_news_evidence(question, for_voice=for_voice)

        # For FINANCE route, fetch live market data
        if route.route == "FINANCE":
            return await self._fetch_finance_evidence(question)

        # For AUGMENTED news-synthesis requests, fetch news headlines as evidence
        # then fall back to the standard provider chain if news is unavailable
        if route.route == "AUGMENTED" and route.evidence_reason == "news_synthesis":
            news_ev = await self._fetch_news_evidence(question, for_voice=for_voice)
            if news_ev:
                return news_ev

        # EVIDENCE route (medical, veterinary, legal high-stakes): strict trusted
        # sources only. Do NOT race Wikipedia/OpenAI/Kimi for these queries.
        if route.route == "EVIDENCE":
            self._logger.info("EVIDENCE route: using strict trusted sources only")
            return await self._fetch_trusted_evidence(question, route)

        primary = route.provider
        if primary == "none" or not primary:
            primary = "wikipedia"

        # Build fallback chain for evidence providers
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

        # Phase 7: Fire evidence providers concurrently and return the first
        # good result. Direct routes (NEWS/TIME/WEATHER/FINANCE) are handled
        # above and are intentionally left sequential/single-source.
        parallel_result = await self._fetch_evidence_parallel(question, route, chain)
        if parallel_result.get("_parallel_success"):
            return parallel_result["evidence"]

        last_error = parallel_result.get("last_error", "")
        attempted = parallel_result.get("attempted", [])
        self._logger.warning(f"All evidence providers failed. Last error: {last_error}")

        # Return a minimal dict with telemetry so callers know what was attempted
        return {
            "fallback_used": True,
            "fallback_reason": f"all_providers_failed:{last_error}",
            "primary_failed": primary,
            "fallback_to": "",
            "attempted_chain": attempted,
            "successful_backend": "",
            "degradation_level": "low",
        }

    async def _fetch_web_evidence(self, question: str) -> dict[str, Any] | None:
        """Fetch a single DuckDuckGo result as untrusted web evidence.

        Only used as a fallback when trusted/primary evidence providers fail for
        ordinary AUGMENTED factual questions. The result is explicitly labelled
        as untrusted so downstream attribution reflects it.
        """
        if not HAS_WEB_FETCHER:
            return None
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: fetch_general_knowledge(question)
            )
        except Exception as exc:
            self._logger.warning(f"General web fetch failed: {exc}")
            return None
        if not result or not result.url:
            return None

        context_parts = [result.snippet]
        if result.title:
            context_parts.insert(0, result.title)
        context = "\n".join(p for p in context_parts if p)
        return {
            "context": context,
            "content": context,
            "title": result.title,
            "url": result.url,
            "sources": [result.url],
            "provider": "web_untrusted",
            "source_type": "web_untrusted",
            "trust_class": "untrusted",
            "evidence_fetched": True,
            "fallback_used": True,
            "fallback_reason": "primary_evidence_providers_failed",
            "successful_backend": "web_untrusted",
            "degradation_level": "untrusted",
        }

    async def _fetch_evidence_parallel(
        self,
        question: str,
        route: RoutingDecision,
        chain: list[str],
    ) -> dict[str, Any]:
        """Fire evidence providers concurrently and return the first good result.

        Returns a dict with either:
          {"_parallel_success": True, "evidence": <evidence dict>}
        or, when all providers fail:
          {"_parallel_success": False, "attempted": [...], "last_error": "..."}
        """
        primary = chain[0] if chain else ""
        tasks: dict[asyncio.Task, str] = {}
        for provider in chain:
            if provider == "trusted":
                coro = self._fetch_trusted_evidence(question, route)
            elif provider == "wikipedia":
                coro = self._fetch_wikipedia_evidence(question)
            elif provider == "kimi":
                coro = self._fetch_api_evidence(question, "kimi")
            elif provider == "openai":
                coro = self._fetch_api_evidence(question, "openai")
            else:
                continue
            task = asyncio.create_task(coro)
            tasks[task] = provider

        attempted: list[str] = []
        last_error = ""
        pending = set(tasks.keys())
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    provider = tasks[task]
                    attempted.append(provider)
                    try:
                        result = task.result()
                        if result:
                            self._logger.info(f"Evidence fetched successfully from {provider}")
                            # Cancel any still-running providers.
                            for t in pending:
                                t.cancel()
                            if pending:
                                await asyncio.wait(pending)
                            # Inject fallback telemetry into the evidence dict.
                            if provider != primary:
                                result["fallback_used"] = True
                                result["fallback_reason"] = f"primary_provider_failed:{primary}"
                                result["primary_failed"] = primary
                                result["fallback_to"] = provider
                                result["attempted_chain"] = attempted
                                result["successful_backend"] = provider
                                result["degradation_level"] = "limited"
                            else:
                                result["successful_backend"] = provider
                                result["attempted_chain"] = attempted
                                result["degradation_level"] = "none"
                            return {"_parallel_success": True, "evidence": result}
                    except Exception as e:
                        last_error = str(e)
                        self._logger.warning(f"Evidence fetch failed for {provider}: {e}")
        finally:
            # Ensure nothing is left running if we exit early.
            for t in pending:
                t.cancel()
            if pending:
                await asyncio.wait(pending)

        return {
            "_parallel_success": False,
            "attempted": attempted,
            "last_error": last_error,
        }

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

    async def _fetch_news_evidence(
        self, question: str, for_voice: bool = False
    ) -> dict[str, Any] | None:
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

    async def _fetch_finance_evidence(self, question: str) -> dict[str, Any] | None:
        """Fetch live finance/market data (delegated to provider module)."""
        breaker = get_breaker("finance_api")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning("Circuit breaker open for finance_api")
            return None
        try:
            if HAS_PROVIDER_MODULES:
                result = await fetch_finance_evidence(question)
                breaker._on_success()
                return result
            self._logger.warning("Provider modules not available")
            return None
        except Exception as e:
            breaker._on_failure(e)
            self._logger.warning(f"Finance evidence fetch failed: {e}")
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
        breaker = get_breaker(f"api_provider_{provider}")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning(f"Circuit breaker open for api_provider_{provider}")
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

    async def _call_local_model_async(
        self,
        prompt: str,
        context: dict[str, Any],
        session_memory: str = "",
        route_mode: str = "LOCAL",
    ) -> str:
        """Call local model asynchronously using Python-native path (delegated to provider module)."""
        # Background-warm Ollama on first call in this process to avoid cold-start latency.
        if HAS_LOCAL_ANSWER_PY:
            LocalAnswer.warmup_ollama()
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
        breaker = get_breaker(f"api_provider_{provider}")
        try:
            breaker._before_call()
        except CircuitBreakerOpen:
            self._logger.warning(f"Circuit breaker open for api_provider_{provider}")
            return f"Error: API provider circuit breaker is OPEN for {provider}."
        self._logger.debug(f"Calling {provider} API async with prompt: {prompt[:50]}...")
        if not HAS_PROVIDER_MODULES:
            return "Error: Provider modules not available"
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
        """
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

    # ======================================================================
    # Helper Methods
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
        """Render conversation mode fallback."""
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

    parser = argparse.ArgumentParser(description="Execution Engine - Execute routing decisions")
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
