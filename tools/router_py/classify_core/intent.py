"""Intent classification wrapper around the core classifier model."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

try:
    from router_py.policy import requires_evidence_mode
except ImportError:
    from policy import requires_evidence_mode
from router_py.request_types import ClassificationResult

from router_py.classify_core.guards import (
    _is_clear_news_query,
    _is_creative_writing,
    _is_news_query_typos,
)

_LOGGER = logging.getLogger(__name__)

classify_question = None
try:
    from router_py.core.intent_classifier import classify_question
except Exception as _exc:
    _LOGGER.warning(f"Intent classifier not available: {_exc}")
    try:
        from core.intent_classifier import classify_question
    except Exception:
        classify_question = None


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
        # Financial queries need real-time data
        "FINANCIAL_DATA": "current_evidence",
        # Legal queries need accurate statutory info
        "LEGAL_QUERY": "current_evidence",
    }

    # Check explicit family
    if intent in family_mappings:
        return family_mappings[intent]

    # Infer from category
    if category == "medical":
        return "current_evidence"  # Medical needs trusted sources

    if category in ("financial", "market"):
        return "current_evidence"  # Financial needs real-time data

    if category in ("legal", "regulatory"):
        return "current_evidence"  # Legal needs accurate sources

    if category in ("informational", "factual"):
        return "background_overview"

    if category == "procedural":
        return "local_answer"

    if category == "analytical":
        return "synthesis_explanation"

    # Infer from intent class if category is generic
    if intent_class in ("news_query", "weather_query", "time_query"):
        return "current_evidence"

    if intent_class in ("how_to", "recipe", "coding"):
        return "local_answer"

    if intent_class in ("explain", "compare", "analyze"):
        return "synthesis_explanation"

    return "local_answer"


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
    clarify_required = output.get("clarify_required", False) or output.get(
        "needs_clarification", False
    )

    # Check evidence mode from policy
    requires_evidence, evidence_reason = requires_evidence_mode(query)
    evidence_mode = "required" if requires_evidence else ""

    # Augmentation recommended for web-needing queries without evidence
    augmentation_recommended = needs_web and not requires_evidence

    # Check for force_local flag (creative writing, privacy requests)
    force_local = output.get("force_local", False)

    # Creative writing override: force LOCAL for stories, poems, fiction
    # regardless of topic keywords (prevents medical/financial evidence mode
    # from overriding creative intent)
    if _is_creative_writing(query):
        force_local = True

    # Typos-tolerant news detection — catches queries like "wats teh latest newz"
    # that the classifier misses due to heavy typos.
    if _is_news_query_typos(query):
        needs_web = True
        intent_family = "current_evidence"
        category = "news_world"

    # Clear-news-phrase detection — catches unambiguous news phrasing that the
    # embedding router may miss (e.g. "Show me today's top stories").
    if _is_clear_news_query(query):
        needs_web = True
        intent_family = "current_evidence"
        category = "news_world"

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
