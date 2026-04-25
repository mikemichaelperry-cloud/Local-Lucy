#!/usr/bin/env python3
"""
Intent classification integration - Python API for router classification.

Wraps the existing intent classifier and provides:
- Direct Python-to-Python calls (no subprocess overhead)
- Integration with policy functions
- Structured result objects
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Add router/core to path for intent_classifier
ROOT_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT_DIR / "router" / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

# Import from existing classifier
try:
    from intent_classifier import classify_question
except ImportError:
    # Fallback for testing without full classifier
    classify_question = None

# Import our policy functions
from .policy import requires_evidence_mode, provider_usage_class_for


@dataclass(frozen=True)
class ClassificationResult:
    """Structured result from intent classification."""
    
    # Core classification
    intent: str
    intent_family: str
    intent_class: str
    category: str
    confidence: float
    
    # Routing signals
    needs_web: bool = False
    needs_memory: bool = False
    needs_synthesis: bool = False
    clarify_required: bool = False
    
    # Evidence and augmentation
    evidence_mode: str = ""
    evidence_reason: str = ""
    augmentation_recommended: bool = False
    
    # Force local mode (for creative writing, privacy-sensitive requests)
    force_local: bool = False
    
    # Manifest fields (from plan mapper)
    manifest_version: str = ""
    selected_route: str = ""
    allowed_routes: list[str] = field(default_factory=list)
    forbidden_routes: list[str] = field(default_factory=list)
    
    # Raw output for debugging
    raw_plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class RoutingDecision:
    """Final routing decision combining classification + policy."""
    
    # Primary decision
    route: str  # "LOCAL", "AUGMENTED", "CLARIFY", "SELF_REVIEW"
    mode: str  # "AUTO", "FORCED_OFFLINE", "FORCED_ONLINE"
    
    # Intent info
    intent_family: str
    confidence: float
    
    # Provider selection
    provider: str  # "local", "wikipedia", "openai", "kimi"
    provider_usage_class: str  # "local", "free", "paid"
    
    # Evidence
    evidence_mode: str
    evidence_reason: str
    
    # Policy checks
    requires_evidence: bool
    policy_reason: str


def classify_intent(query: str, surface: str = "cli") -> ClassificationResult:
    """
    Classify user intent and return structured result.
    
    Args:
        query: User query string
        surface: Interface surface (cli, voice, web, etc.)
        
    Returns:
        ClassificationResult with intent, routing signals, and manifest
        
    Example:
        >>> result = classify_intent("Who was Ada Lovelace?")
        >>> result.intent_family
        'background_overview'
        >>> result.needs_web
        True
    """
    if classify_question is None:
        raise RuntimeError("Intent classifier not available")
    
    # Call existing classifier
    output = classify_question(query, surface=surface)
    
    # Extract core fields
    intent = output.get("intent", "unknown")
    category = output.get("category", "unknown")
    confidence = output.get("confidence", 0.0)
    
    # Get intent class (more specific)
    intent_class = output.get("intent_class", intent)
    
    # Map to intent family
    intent_family = _map_to_intent_family(intent, intent_class, category)
    
    # Extract routing signals
    signals = output.get("signals", {})
    # Check both signals dict and top-level (classifier puts needs_web in both places)
    needs_web = signals.get("needs_web", False) or output.get("needs_web", False)
    needs_memory = signals.get("needs_memory", False) or output.get("needs_memory", False)
    needs_synthesis = signals.get("needs_synthesis", False) or output.get("needs_synthesis", False)
    clarify_required = output.get("clarify_required", False) or output.get("needs_clarification", False)
    
    # Check evidence mode from policy
    requires_evidence, evidence_reason = requires_evidence_mode(query)
    evidence_mode = "required" if requires_evidence else ""
    
    # Augmentation recommended for web-needing queries without evidence
    augmentation_recommended = needs_web and not requires_evidence
    
    # Check for force_local flag (creative writing, privacy requests)
    force_local = output.get("force_local", False)
    
    # Extract manifest fields if present
    manifest = output.get("manifest", {})
    
    return ClassificationResult(
        intent=intent,
        intent_family=intent_family,
        intent_class=intent_class,
        category=category,
        confidence=confidence,
        needs_web=needs_web,
        needs_memory=needs_memory,
        needs_synthesis=needs_synthesis,
        clarify_required=clarify_required,
        evidence_mode=evidence_mode,
        evidence_reason=evidence_reason,
        augmentation_recommended=augmentation_recommended,
        force_local=force_local,
        manifest_version=manifest.get("version", ""),
        selected_route=manifest.get("selected_route", ""),
        allowed_routes=manifest.get("allowed_routes", []),
        forbidden_routes=manifest.get("forbidden_routes", []),
        raw_plan=output,
    )


def select_route(
    classification: ClassificationResult,
    policy: str = "fallback_only",
    forced_mode: str | None = None,
) -> RoutingDecision:
    """
    Select final route based on classification and policy.
    
    Args:
        classification: Result from classify_intent()
        policy: Augmentation policy (disabled, fallback_only, direct_allowed)
        forced_mode: Optional forced mode override
        
    Returns:
        RoutingDecision with final route and provider
        
    Example:
        >>> classification = classify_intent("Who was Ada Lovelace?")
        >>> decision = select_route(classification)
        >>> decision.route
        'AUGMENTED'
        >>> decision.provider
        'wikipedia'
    """
    # Handle forced modes
    if forced_mode == "FORCED_OFFLINE":
        return _make_local_decision(classification)
    
    if forced_mode == "FORCED_ONLINE":
        return _make_augmented_decision(classification, prefer_paid=True)
    
    # CREATIVE WRITING: Force local mode for stories, poems, fiction
    # This avoids identity preamble issues ("I'm Local Lucy...") and
    # provides better privacy for personal creative content
    if classification.force_local:
        return _make_local_decision(classification)
    
    # Handle clarify required
    if classification.clarify_required:
        return RoutingDecision(
            route="CLARIFY",
            mode="AUTO",
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            provider="local",
            provider_usage_class="local",
            evidence_mode=classification.evidence_mode,
            evidence_reason=classification.evidence_reason,
            requires_evidence=bool(classification.evidence_mode),
            policy_reason="clarification_required",
        )
    
    # Check policy first - disabled policy overrides everything
    if policy == "disabled":
        return _make_local_decision(classification)
    
    # Check for queries that explicitly need current/web data
    # This includes time queries, current facts - local model cannot answer these
    if classification.needs_web and classification.intent_family == "current_evidence":
        # News-specific queries should use NEWS route for RSS feed fetching
        if classification.category in ("news_world", "news_israel", "news_australia"):
            return _make_news_decision(classification)
        
        # Time queries need real-time data - use dedicated TIME route
        # TIME route calls time API directly (no LLM needed for simple time lookup)
        if classification.category == "time_query":
            if policy == "disabled":
                return _make_local_decision(classification)
            return _make_time_decision(classification)
    
    # Current evidence (news, real-time info) attempts local first with fallback
    if classification.intent_family == "current_evidence":
        if policy == "fallback_only":
            return _make_local_with_fallback(classification)
        elif policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False)
        else:  # disabled
            return _make_local_decision(classification)
    
    # Evidence mode queries go augmented (if policy allows)
    if classification.evidence_mode == "required":
        return _make_augmented_decision(classification, prefer_paid=True)
    
    # Check for web-needing queries (background info, research)
    if classification.needs_web:
        if classification.intent_family in ("background_overview", "synthesis_explanation"):
            if policy == "direct_allowed":
                return _make_augmented_decision(classification, prefer_paid=False)
            else:  # fallback_only
                return _make_local_with_fallback(classification)
        
        # For other intent families that need web
        if policy == "fallback_only":
            return _make_local_with_fallback(classification)
        elif policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False)
    
    # Determine based on intent family
    if classification.intent_family in ("background_overview", "synthesis_explanation"):
        if policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False)
        else:  # fallback_only
            return _make_local_with_fallback(classification)
    
    if classification.intent_family == "local_answer":
        return _make_local_decision(classification)
    
    return _make_local_decision(classification)


def _map_to_intent_family(intent: str, intent_class: str, category: str) -> str:
    """Map classifier output to intent family."""
    # Direct mappings
    family_mappings = {
        "background_overview": "background_overview",
        "synthesis_explanation": "synthesis_explanation",
        "current_evidence": "current_evidence",
        "local_answer": "local_answer",
        "self_review": "self_review",
        # Current info / news queries need direct internet access
        "WEB_NEWS": "current_evidence",
        "WEB_FACT": "current_evidence",
        # Medical queries need trusted source verification
        "MEDICAL_INFO": "current_evidence",
    }
    
    # Check explicit family
    if intent in family_mappings:
        return family_mappings[intent]
    
    # Infer from category
    if category == "medical":
        return "current_evidence"  # Medical needs trusted sources
    
    if category in ("informational", "factual"):
        return "background_overview"
    
    if category == "procedural":
        return "local_answer"
    
    if category == "analytical":
        return "synthesis_explanation"
    
    return "local_answer"


def _make_local_decision(classification: ClassificationResult) -> RoutingDecision:
    """Create a local-only routing decision."""
    return RoutingDecision(
        route="LOCAL",
        mode="AUTO",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        provider="local",
        provider_usage_class="local",
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=bool(classification.evidence_mode),
        policy_reason="local_sufficient",
    )


def _make_augmented_decision(
    classification: ClassificationResult,
    prefer_paid: bool = False,
) -> RoutingDecision:
    """Create an augmented routing decision."""
    # Select provider
    if prefer_paid:
        provider = "openai"  # Default paid provider
    else:
        # Prefer free provider (wikipedia) for background and current info queries
        # News and current facts can often be found in Wikipedia (current events)
        if classification.intent_family in ("background_overview", "current_evidence"):
            provider = "wikipedia"
        else:
            provider = "openai"
    
    usage_class = provider_usage_class_for(provider)
    
    return RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        provider=provider,
        provider_usage_class=usage_class,
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=bool(classification.evidence_mode),
        policy_reason="augmentation_required" if classification.evidence_mode else "background_query",
    )


def _make_local_with_fallback(classification: ClassificationResult) -> RoutingDecision:
    """Create a local-first with fallback routing decision."""
    return RoutingDecision(
        route="LOCAL",  # Start local
        mode="AUTO",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        provider="local",
        provider_usage_class="local",
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=bool(classification.evidence_mode),
        policy_reason="local_first_fallback_allowed",
    )


def _make_news_decision(classification: ClassificationResult) -> RoutingDecision:
    """Create a NEWS route decision for RSS news fetching."""
    return RoutingDecision(
        route="NEWS",
        mode="AUTO",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        provider="news",
        provider_usage_class="local",
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=bool(classification.evidence_mode),
        policy_reason="rss_news_provider",
    )


def _make_time_decision(classification: ClassificationResult) -> RoutingDecision:
    """Create a TIME route decision for current time queries."""
    return RoutingDecision(
        route="TIME",
        mode="AUTO",
        intent_family=classification.intent_family,
        confidence=classification.confidence,
        provider="timeapi",  # TimeAPI.io provider
        provider_usage_class="free",
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=False,
        policy_reason="time_api_provider",
    )


if __name__ == "__main__":
    # CLI interface for testing
    import argparse
    
    parser = argparse.ArgumentParser(description="Classify intent for routing")
    parser.add_argument("query", help="User query to classify")
    parser.add_argument("--surface", default="cli", help="Interface surface")
    parser.add_argument("--policy", default="fallback_only", help="Augmentation policy")
    args = parser.parse_args()
    
    try:
        classification = classify_intent(args.query, surface=args.surface)
        decision = select_route(classification, policy=args.policy)
        
        result = {
            "classification": {
                "intent": classification.intent,
                "intent_family": classification.intent_family,
                "intent_class": classification.intent_class,
                "confidence": classification.confidence,
                "needs_web": classification.needs_web,
            },
            "decision": {
                "route": decision.route,
                "provider": decision.provider,
                "provider_usage_class": decision.provider_usage_class,
                "policy_reason": decision.policy_reason,
            },
        }
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
