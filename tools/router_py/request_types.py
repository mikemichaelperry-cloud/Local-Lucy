#!/usr/bin/env python3
"""
Centralized request pipeline types.

Stage 2 of the Kimi Architecture Refactor. All cross-cutting dataclasses
that flow through the pipeline live here to prevent circular imports
and provide a single source of truth.

Migration plan:
- classify.py: ClassificationResult, RoutingDecision → import from here
- execution_engine.py: ExecutionResult → import from here
- main.py: RouterOutcome → import from here
- Do NOT move yet — keep backward compatibility until Stage 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Enumerated literals (self-documenting, enables IDE autocomplete)
# ---------------------------------------------------------------------------

RouteType = Literal[
    "LOCAL",
    "AUGMENTED",
    "CLARIFY",
    "SELF_REVIEW",
    "NEWS",
    "WEATHER",
    "TIME",
    "EVIDENCE",
    "MEMORY_RECALL",
]

ModeType = Literal["AUTO", "FORCED_OFFLINE", "FORCED_ONLINE", "FORCED"]

ProviderType = Literal["local", "wikipedia", "openai", "kimi", "news", "weather", "time"]

ProviderUsageClass = Literal["local", "free", "paid"]

SurfaceType = Literal["cli", "hmi", "voice", "api"]

StatusType = Literal["completed", "failed", "timeout"]

OutcomeCodeType = Literal[
    "answered",
    "local_fallback",
    "augmented_answer",
    "clarification_requested",
    "feedback_acknowledged",
    "execution_error",
    "router_error",
    "timeout",
    "unknown",
]

IntentFamily = Literal[
    "factual",
    "creative",
    "technical",
    "conversational",
    "operational",
    "feedback",
    "memory",
    "unknown",
]

EvidenceModeType = Literal["", "required", "optional", "disabled"]

# ---------------------------------------------------------------------------
# Pipeline stage dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    """Structured result from intent classification (Stage 1: classify)."""

    # Core classification
    intent: str
    intent_family: str
    intent_class: str = ""
    category: str = ""
    confidence: float = 0.0

    # Routing signals
    needs_web: bool = False
    needs_memory: bool = False
    needs_synthesis: bool = False
    clarify_required: bool = False

    # Evidence and augmentation
    evidence_mode: str = ""
    evidence_reason: str = ""
    augmentation_recommended: bool = False

    # Force local mode (creative writing, privacy-sensitive requests)
    force_local: bool = False

    # Manifest fields (from plan mapper)
    manifest_version: str = ""
    selected_route: str = ""
    allowed_routes: list[str] = field(default_factory=list)
    forbidden_routes: list[str] = field(default_factory=list)

    # Surface that originated the request
    surface: str = "cli"

    # Raw output for debugging
    raw_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Final routing decision combining classification + policy (Stage 2: route)."""

    # Primary decision
    route: str  # RouteType
    mode: str  # ModeType

    # Intent info
    intent_family: str
    confidence: float

    # Provider selection
    provider: str  # ProviderType
    provider_usage_class: str  # ProviderUsageClass

    # Evidence
    evidence_mode: str  # EvidenceModeType
    evidence_reason: str = ""

    # Policy checks
    requires_evidence: bool = False
    policy_reason: str = ""

    # Ephemeral queries (weather, real-time prices) — exclude from memory
    ephemeral: bool = False


@dataclass(frozen=True)
class ExecutionResult:
    """Structured result from plan execution (Stage 3: execute)."""

    status: str  # StatusType
    outcome_code: str  # OutcomeCodeType
    route: str  # RouteType
    provider: str  # ProviderType
    provider_usage_class: str  # ProviderUsageClass
    response_text: str = ""
    error_message: str = ""
    execution_time_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # Policy-layer provenance (propagated from RoutingDecision so HMI
    # can display WHY this route was chosen without re-deriving it)
    evidence_reason: str = ""
    policy_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
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
            "evidence_reason": self.evidence_reason,
            "policy_reason": self.policy_reason,
        }


@dataclass(frozen=True)
class RouterOutcome:
    """Structured outcome from the full pipeline (Stage 4: outcome)."""

    status: str  # StatusType
    outcome_code: str  # OutcomeCodeType
    route: str  # RouteType
    provider: str  # ProviderType
    provider_usage_class: str  # ProviderUsageClass
    intent_family: str = ""
    confidence: float = 0.0
    response_text: str = ""
    error_message: str = ""
    execution_time_ms: int = 0
    request_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # Policy-layer provenance (mirrors RoutingDecision fields so HMI
    # displays the exact reason the router chose this path)
    evidence_reason: str = ""
    policy_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outcome_code": self.outcome_code,
            "route": self.route,
            "provider": self.provider,
            "provider_usage_class": self.provider_usage_class,
            "intent_family": self.intent_family,
            "confidence": self.confidence,
            "response_text": self.response_text,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "request_id": self.request_id,
            "evidence_reason": self.evidence_reason,
            "policy_reason": self.policy_reason,
        }

    def with_execution_time(self, ms: int) -> RouterOutcome:
        """Return a new outcome with updated execution time."""
        return RouterOutcome(
            status=self.status,
            outcome_code=self.outcome_code,
            route=self.route,
            provider=self.provider,
            provider_usage_class=self.provider_usage_class,
            intent_family=self.intent_family,
            confidence=self.confidence,
            response_text=self.response_text,
            error_message=self.error_message,
            execution_time_ms=ms,
            request_id=self.request_id,
            metadata=dict(self.metadata),
            evidence_reason=self.evidence_reason,
            policy_reason=self.policy_reason,
        )

    def with_request_id(self, request_id: str) -> RouterOutcome:
        """Return a new outcome with updated request ID."""
        return RouterOutcome(
            status=self.status,
            outcome_code=self.outcome_code,
            route=self.route,
            provider=self.provider,
            provider_usage_class=self.provider_usage_class,
            intent_family=self.intent_family,
            confidence=self.confidence,
            response_text=self.response_text,
            error_message=self.error_message,
            execution_time_ms=self.execution_time_ms,
            request_id=request_id,
            metadata=dict(self.metadata),
            evidence_reason=self.evidence_reason,
            policy_reason=self.policy_reason,
        )


@dataclass(frozen=True)
class PipelineContext:
    """
    Formalized execution context that flows through the pipeline.

    Previously an ad-hoc dict built in _delegate_execution_to_python().
    Centralizing here makes the contract explicit and testable.
    """

    question: str
    session_id: str = ""
    state_namespace: str = "default"
    augmentation_policy: str = "fallback_only"
    evidence_enabled: bool = False
    conversation_mode_active: bool = False
    augmented_provider: str = "wikipedia"
    surface: str = "cli"  # SurfaceType
    memory_enabled: bool = False
    force_local: bool = False

    # Extra key-value pairs for extensibility (mirrors old dict merge)
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to flat dict for legacy callers (ExecutionEngine, etc)."""
        base = {
            "question": self.question,
            "session_id": self.session_id,
            "state_namespace": self.state_namespace,
            "augmentation_policy": self.augmentation_policy,
            "evidence_enabled": self.evidence_enabled,
            "conversation_mode_active": self.conversation_mode_active,
            "augmented_provider": self.augmented_provider,
            "surface": self.surface,
            "memory_enabled": self.memory_enabled,
            "force_local": self.force_local,
        }
        base.update(self.extras)
        return base

    @classmethod
    def from_env(cls, question: str = "", surface: str = "cli") -> PipelineContext:
        """Build a PipelineContext from current environment variables."""
        import os

        return cls(
            question=question,
            session_id=os.environ.get("LUCY_SESSION_ID", ""),
            state_namespace=os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "default"),
            augmentation_policy=os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only"),
            evidence_enabled=os.environ.get("LUCY_EVIDENCE_ENABLED", "0") == "1",
            conversation_mode_active=os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "0") == "1",
            augmented_provider=os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia"),
            surface=surface,
            memory_enabled=os.environ.get("LUCY_SESSION_MEMORY", "0") == "1",
            force_local=os.environ.get("LUCY_FORCE_LOCAL", "0") == "1",
        )


@dataclass(frozen=True)
class StatePropagationSnapshot:
    """
    Immutable snapshot of what state was present at a pipeline stage.
    Used for debugging, audit, and parity tests.
    """

    stage: str  # e.g. "classify", "route", "execute", "outcome"
    env_vars: dict[str, str] = field(default_factory=dict)
    context: PipelineContext | None = None
    decision: RoutingDecision | None = None
    timestamp_ms: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def provider_usage_class_for(provider: str) -> str:
    """Return usage class for a provider."""
    mapping = {
        "local": "local",
        "wikipedia": "free",
        "openai": "paid",
        "kimi": "paid",
        "news": "free",
        "weather": "free",
        "time": "free",
    }
    return mapping.get(provider, "local")
