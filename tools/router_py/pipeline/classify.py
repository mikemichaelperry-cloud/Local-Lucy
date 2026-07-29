#!/usr/bin/env python3
"""Intent classification wrapper for the request pipeline.

This module holds the classification-related helpers and the classification
step that used to live inline in ``request_pipeline.process()``. It is
responsible for:

* Engineering / self-analysis mode detection
* Gemma 4 smart-routing bypass
* Legacy env-bypass helpers (``LUCY_ROUTER_BYPASS`` / ``LUCY_CHAT_FORCE_MODE``)
* Keyword heuristics used by smart routing
* Calling ``classify_intent`` and wrapping classification errors
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

from router_py.request_types import (
    ClassificationResult,
    RouterOutcome,
    RoutingDecision,
)
from router_py.classify import classify_intent
from router_py.core.medical_query_heuristics import detect_human_medication_query
from router_py.policy import provider_usage_class_for
from router_py.execution_engine import extract_self_analysis_file_reference

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Self-analysis pre-check (must run before Gemma 4 smart-routing bypass)
# ---------------------------------------------------------------------------


def _self_analysis_state_path() -> Path:
    """Resolve current_state.json using the active runtime namespace."""
    namespace = os.environ.get(
        "LUCY_RUNTIME_NAMESPACE_ROOT",
        str(lucy_runtime_namespace_root()),
    )
    return Path(namespace) / "state" / "current_state.json"


def _self_analysis_mode_enabled() -> bool:
    """Return True if Engineering / self-analysis mode is on in state."""
    try:
        state = json.loads(_self_analysis_state_path().read_text(encoding="utf-8"))
        return str(state.get("self_analysis_mode", "off")).lower() == "on"
    except Exception:
        return False


def _self_analysis_file_reference(question: str) -> str | None:
    """Return a file reference if the question is a self-analysis request."""
    if not _self_analysis_mode_enabled():
        return None
    return extract_self_analysis_file_reference(question)


# ---------------------------------------------------------------------------
# Gemma 4 smart-routing helpers
# ---------------------------------------------------------------------------

_NEWS_RE = re.compile(r"\b(news|headlines|latest|breaking)\b", re.IGNORECASE)
_EVIDENCE_RE = re.compile(r"\b(research|study|evidence|paper|source|according to)\b", re.IGNORECASE)


def _is_gemma4_smart_routing_enabled(model: str) -> bool:
    """Return True if Gemma 4 smart routing is enabled for the given model."""
    if not model:
        return False
    name = model.lower()
    if not (name.startswith("gemma4") or name.startswith("local-lucy-gemma4")):
        return False
    return os.environ.get("LUCY_GEMMA4_SMART_ROUTING", "").lower() in ("1", "true", "on")


def _gemma4_bypass_decision(question: str) -> tuple[ClassificationResult, RoutingDecision]:
    """Create minimal classification + LOCAL routing decision for Gemma 4 bypass."""
    classification = ClassificationResult(
        intent="general",
        intent_family="general",
        intent_class="general",
        confidence=1.0,
        force_local=True,
    )
    decision = RoutingDecision(
        route="LOCAL",
        mode="SMART",
        intent_family="general",
        confidence=1.0,
        provider="local",
        provider_usage_class="local",
        evidence_mode="none",
        policy_reason="gemma4_smart_routing",
    )
    return classification, decision


# ---------------------------------------------------------------------------
# Legacy shell-bypass env-var support (LUCY_ROUTER_BYPASS / LUCY_CHAT_FORCE_MODE)
# ---------------------------------------------------------------------------


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "on", "yes")


def _forced_route_from_env(question: str) -> str | None:
    """Return the route forced by LUCY_CHAT_FORCE_MODE, or None if not bypassed."""
    if not _is_truthy_env("LUCY_ROUTER_BYPASS"):
        return None
    forced = os.environ.get("LUCY_CHAT_FORCE_MODE", "").strip().upper()
    if forced in (
        "LOCAL",
        "NEWS",
        "EVIDENCE",
        "AUGMENTED",
        "FULL",
        "TIME",
        "WEATHER",
        "FINANCE",
        "CLARIFY",
    ):
        return forced
    # Infer from query when bypass is requested without an explicit mode.
    q = (question or "").lower()
    if re.search(r"\b(news|headlines|latest news|breaking news)\b", q):
        return "NEWS"
    return None


def _bypass_classification_decision(
    question: str, route: str
) -> tuple[ClassificationResult, RoutingDecision]:
    """Create classification + routing decision for a bypass/forced route."""
    q = (question or "").lower()
    route_providers = {
        "LOCAL": "local",
        "NEWS": "news",
        "EVIDENCE": "trusted",
        "AUGMENTED": os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia").strip().lower()
        or "wikipedia",
        "FULL": os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia").strip().lower()
        or "wikipedia",
        "TIME": "time",
        "WEATHER": "weather",
        "FINANCE": "finance",
        "CLARIFY": "local",
    }
    provider = route_providers.get(route, "local")

    if route == "NEWS":
        intent_family = "current_fact"
        evidence_reason = "news_query"
    elif route in ("WEATHER",):
        intent_family = "current_fact"
        evidence_reason = "weather_query"
    elif route in ("TIME",):
        intent_family = "current_fact"
        evidence_reason = "time_query"
    elif route == "FINANCE":
        intent_family = "current_fact"
        evidence_reason = "financial_data"
    elif route == "EVIDENCE":
        med_detector = detect_human_medication_query(q)
        if med_detector.get("detector_fired") or re.search(
            r"\b(medical|medication|medicine|drug|dose|dosage|side effect|interaction|contraindication)\b",
            q,
        ):
            intent_family = "evidence_check"
            evidence_reason = "medical_context"
        elif re.search(r"\b(stock|finance|currency|exchange rate|market|economy)\b", q):
            intent_family = "current_fact"
            evidence_reason = "financial_data"
        else:
            intent_family = "evidence_check"
            evidence_reason = "source_request"
    elif route == "AUGMENTED":
        intent_family = "background_overview"
        evidence_reason = "source_request"
    elif route == "FULL":
        intent_family = "background_overview"
        evidence_reason = "source_request"
    else:
        intent_family = "local_knowledge"
        evidence_reason = ""

    classification = ClassificationResult(
        intent=intent_family,
        intent_family=intent_family,
        intent_class="bypass",
        confidence=1.0,
        evidence_reason=evidence_reason,
        needs_web=route not in ("LOCAL", "CLARIFY"),
    )
    decision = RoutingDecision(
        route=route,
        mode="FORCED",
        intent_family=intent_family,
        confidence=1.0,
        provider=provider,
        provider_usage_class=provider_usage_class_for(provider),
        evidence_mode="required" if route not in ("LOCAL", "CLARIFY") else "",
        evidence_reason=evidence_reason,
        requires_evidence=route not in ("LOCAL", "CLARIFY"),
        policy_reason="env_bypass",
        decision_stage="env_override",
        reason_code="LUCY_ROUTER_BYPASS",
    )
    return classification, decision


def _looks_like_news(query: str) -> bool:
    return bool(_NEWS_RE.search(query))


def _looks_like_evidence(query: str) -> bool:
    return bool(_EVIDENCE_RE.search(query))


# ---------------------------------------------------------------------------
# Pipeline classification step
# ---------------------------------------------------------------------------


def classify_question(
    question: str,
    surface: str,
    model: str | None,
    route_prefix: str,
    context: dict[str, Any] | None,
) -> tuple[ClassificationResult | RouterOutcome, str, RoutingDecision | None]:
    """
    Classify the question and apply smart-routing short-circuits.

    Args:
        question: The user's query text.
        surface: Origin surface (cli, hmi, voice, api).
        model: Optional model override. When omitted, env vars are consulted.
        route_prefix: Pre-parsed route prefix from the caller. May be updated
            by Gemma 4 smart-routing keyword heuristics.
        context: Extra execution context from caller (reserved for future use).

    Returns:
        A tuple of (classification_or_error, updated_route_prefix, bypass_decision).
        * classification_or_error is normally a ``ClassificationResult``; on
          classification failure it is a ``RouterOutcome`` and the caller should
          return it immediately.
        * bypass_decision is set only when Gemma 4 smart-routing bypass decides
          the query is general/local; in that case route selection should be
          skipped and this decision used directly.
    """
    import time as _time

    start_time = _time.time()
    active_model = (
        model or os.environ.get("LUCY_MODEL", "") or os.environ.get("LUCY_LOCAL_MODEL", "")
    )

    # Engineering / self-analysis mode must not be bypassed, even by smart routing.
    _self_analysis_ref = _self_analysis_file_reference(question)

    if (
        _is_gemma4_smart_routing_enabled(active_model)
        and not route_prefix
        and _self_analysis_ref is None
    ):
        if _looks_like_news(question):
            route_prefix = "NEWS"
        elif _looks_like_evidence(question):
            route_prefix = "EVIDENCE"
        else:
            classification, bypass_decision = _gemma4_bypass_decision(question)
            return classification, route_prefix, bypass_decision

    try:
        classification = classify_intent(question, surface=surface)
    except Exception as exc:
        logger.exception("Classification failed")
        execution_time = int((_time.time() - start_time) * 1000)
        outcome = RouterOutcome(
            status="failed",
            outcome_code="classification_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message=f"Classification failed: {exc}",
            execution_time_ms=execution_time,
            evidence_reason="",
            policy_reason="classification_failed",
        )
        return outcome, route_prefix, None

    return classification, route_prefix, None
