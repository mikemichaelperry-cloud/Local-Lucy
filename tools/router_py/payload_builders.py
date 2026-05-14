#!/usr/bin/env python3
"""Shared payload builders used by both shell and Python routers.

Extracted in Stream 5 to eliminate duplication between:
- runtime_request.py (shell router)
- execution_engine_state.py (Python router)

These functions are pure (no side effects) and operate only on dict inputs.
"""
from __future__ import annotations

from typing import Any


def build_route_snapshot_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Build last_route.json snapshot from a full request payload."""
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    outcome = payload.get("outcome") if isinstance(payload.get("outcome"), dict) else {}
    authority = payload.get("authority") if isinstance(payload.get("authority"), dict) else {}
    current_route = _stringify(
        route.get("selected_route") or route.get("mode") or route.get("final_mode") or route.get("requested_mode")
    )
    provider_used = _stringify(
        outcome.get("augmented_provider_used")
        or outcome.get("augmented_provider")
        or outcome.get("augmented_provider_selected")
    )
    trust_class = _stringify(outcome.get("trust_class"))
    source_type = determine_route_source_type(
        current_route=current_route, provider_used=provider_used, trust_class=trust_class
    )
    return {
        "current_route": current_route,
        "final_mode": _stringify(route.get("final_mode")),
        "intent_family": _stringify(route.get("intent_family")),
        "mode": _stringify(route.get("mode")),
        "outcome_code": _stringify(outcome.get("outcome_code")),
        "provider_used": provider_used or "none",
        "request_id": _stringify(payload.get("request_id")),
        "route": current_route,
        "route_reason": _stringify(route.get("reason")),
        "selected_route": _stringify(route.get("selected_route")),
        "source": source_type,
        "source_type": source_type,
        "status": _stringify(payload.get("status")),
        "answer_class": _stringify(outcome.get("answer_class")),
        "provider_authorization": _stringify(outcome.get("provider_authorization")),
        "operator_trust_label": _stringify(outcome.get("operator_trust_label")),
        "operator_answer_path": _stringify(outcome.get("operator_answer_path")),
        "trust_class": trust_class,
        "updated_at": _stringify(payload.get("completed_at")),
        "authority": authority if isinstance(authority, dict) else {},
    }


def determine_route_source_type(*, current_route: str, provider_used: str, trust_class: str) -> str:
    """Determine the source type label for a route."""
    route_label = current_route.strip().upper()
    provider_label = provider_used.strip().lower()
    trust_label = trust_class.strip().lower()
    if provider_label in {"openai", "grok", "wikipedia"}:
        return provider_label
    if route_label == "LOCAL":
        return "local"
    if route_label == "EVIDENCE":
        return "evidence"
    if route_label == "SELF_REVIEW":
        return "self_review"
    if trust_label:
        return trust_label
    return "unknown"


def build_history_entry(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a history entry from a full request payload."""
    control_state = payload.get("control_state")
    return {
        "authority": payload.get("authority", {}) if isinstance(payload.get("authority"), dict) else {},
        "completed_at": payload.get("completed_at", ""),
        "control_state": control_state if isinstance(control_state, dict) else {},
        "error": payload.get("error", ""),
        "outcome": payload.get("outcome", {}) if isinstance(payload.get("outcome"), dict) else {},
        "request_id": payload.get("request_id", ""),
        "request_text": payload.get("request_text", ""),
        "response_text": payload.get("response_text", ""),
        "route": payload.get("route", {}) if isinstance(payload.get("route"), dict) else {},
        "status": payload.get("status", ""),
    }


def _stringify(value: Any) -> str:
    """Coerce a value to a string, defaulting to empty string."""
    if value is None:
        return ""
    return str(value).strip()
