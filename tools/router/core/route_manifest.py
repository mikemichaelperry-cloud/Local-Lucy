#!/usr/bin/env python3
"""Frozen manifest contract for route authority.

Behavior in this module is frozen except for demonstrated defect fixes.
New heuristics require targeted test coverage first.
Authority boundaries must not be weakened, and execution must stay manifest-led.

The live AUTO path now treats AUGMENTED as a governed first-class route for a
narrow conceptual band. Provider selection remains downstream and manifest-led.
"""

from typing import Any, Dict, List, Tuple


MANIFEST_VERSION = "v1"
KNOWN_ROUTES: Tuple[str, ...] = ("LOCAL", "NEWS", "EVIDENCE", "AUGMENTED", "CLARIFY")
KNOWN_INTENT_FAMILIES = {"", "self_review", "current_evidence", "background_overview", "synthesis_explanation", "local_answer"}
EVIDENCE_ROUTES = {"NEWS", "EVIDENCE"}
EVIDENCE_MODES = {"LIGHT", "FULL"}
EVIDENCE_MODE_REASON_DEFAULT = "default_light"
EVIDENCE_MODE_REASON_SOURCE = "explicit_source_request"
EVIDENCE_MODE_REASON_MEDICAL = "policy_medical_high_risk"
EVIDENCE_MODE_REASON_CONFLICT = "policy_conflict_live"
EVIDENCE_MODE_REASON_GEO = "policy_geopolitics_high_risk"
EVIDENCE_MODE_REASON_NON_EVIDENCE = "not_evidence_route"
EVIDENCE_MODE_REASON_ALIASES = {
    "current_fact": EVIDENCE_MODE_REASON_DEFAULT,
    "source_request": EVIDENCE_MODE_REASON_SOURCE,
    "medical_context": EVIDENCE_MODE_REASON_MEDICAL,
    "conflict_live": EVIDENCE_MODE_REASON_CONFLICT,
    "geopolitics": EVIDENCE_MODE_REASON_GEO,
}
EVIDENCE_MODE_REASONS = {
    EVIDENCE_MODE_REASON_DEFAULT,
    EVIDENCE_MODE_REASON_SOURCE,
    EVIDENCE_MODE_REASON_MEDICAL,
    EVIDENCE_MODE_REASON_CONFLICT,
    EVIDENCE_MODE_REASON_GEO,
    EVIDENCE_MODE_REASON_NON_EVIDENCE,
}


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return _text(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_route(value: Any) -> str:
    route = _text(value).strip().upper()
    if route in KNOWN_ROUTES:
        return route
    return ""


def _normalize_route_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    out: List[str] = []
    seen = set()
    for raw in values:
        route = _normalize_route(raw)
        if not route or route in seen:
            continue
        seen.add(route)
        out.append(route)
    return out


def _canonical_signals(signal_flags: Dict[str, Any]) -> Dict[str, bool]:
    source = signal_flags if isinstance(signal_flags, dict) else {}
    return {
        "temporal": _bool(source.get("temporal")),
        "news": _bool(source.get("news")),
        "conflict": _bool(source.get("conflict")),
        "geopolitics": _bool(source.get("geopolitics")),
        "israel_region_live": _bool(source.get("israel_region")),
        "source_request": _bool(source.get("source_request")),
        "url": _bool(source.get("url")),
        "ambiguity_followup": _bool(source.get("ambiguity_followup")),
        "medical_context": _bool(source.get("medical_context")),
        "current_product": _bool(source.get("current_product_recommendation")),
    }

def _choose_evidence_mode(route: str, signals: Dict[str, bool]) -> Tuple[str, str]:
    if route not in EVIDENCE_ROUTES:
        return "", EVIDENCE_MODE_REASON_NON_EVIDENCE
    if signals.get("source_request") or signals.get("url"):
        return "FULL", EVIDENCE_MODE_REASON_SOURCE
    if signals.get("medical_context"):
        return "FULL", EVIDENCE_MODE_REASON_MEDICAL
    if signals.get("geopolitics") and (signals.get("temporal") or signals.get("news")):
        return "FULL", EVIDENCE_MODE_REASON_GEO
    if signals.get("conflict") and (signals.get("temporal") or signals.get("news")):
        return "FULL", EVIDENCE_MODE_REASON_CONFLICT
    return "LIGHT", EVIDENCE_MODE_REASON_DEFAULT


def canonical_evidence_mode_reason(evidence_mode: Any, evidence_reason: Any) -> str:
    mode = _text(evidence_mode).strip().upper()
    reason = _text(evidence_reason).strip()
    if reason in EVIDENCE_MODE_REASON_ALIASES:
        reason = EVIDENCE_MODE_REASON_ALIASES[reason]
    if not mode:
        return reason
    return reason


def _authority_basis(
    *,
    selected_route: str,
    clarify_required: bool,
    signals: Dict[str, bool],
    context_resolution_used: bool,
    contextual_followup_kind: str,
    local_response_selected: bool,
) -> str:
    if clarify_required or selected_route == "CLARIFY":
        return "clarify_required"
    if local_response_selected:
        return "governor_local_response"
    if context_resolution_used:
        kind = _text(contextual_followup_kind).strip().lower() or "resolved"
        return f"contextual_followup:{kind}"
    if signals.get("url") or signals.get("source_request"):
        return "doc_source_prompt"
    if signals.get("medical_context"):
        return "medical_high_stakes"
    if signals.get("current_product"):
        return "current_product_request"
    if signals.get("temporal") or signals.get("news") or signals.get("conflict") or signals.get("israel_region_live"):
        return "live_current_prompt"
    if selected_route == "AUGMENTED":
        return "conceptual_augmented_prompt"
    if selected_route == "LOCAL":
        return "conceptual_local_prompt"
    return "policy_selected_route"


def _context_referent_confidence(context_resolution_used: bool, contextual_followup_kind: str) -> str:
    if not context_resolution_used:
        return ""
    kind = _text(contextual_followup_kind).strip().lower()
    if kind in {"comparison", "single_subject", "medical", "travel_advisory", "news", "media_reliability"}:
        return "high"
    return "medium"


def build_route_manifest(
    *,
    original_query: str,
    resolved_execution_query: str,
    selected_route: str,
    candidate_routes: Any,
    winning_signal: str,
    precedence_version: str,
    clarify_required: bool,
    signal_flags: Dict[str, Any],
    context_resolution_used: bool,
    contextual_followup_kind: str,
    intent_family: str = "",
    route_prefix: str = "",
    local_response_selected: bool = False,
) -> Dict[str, Any]:
    route = _normalize_route(selected_route)
    if not route:
        raise ValueError(f"invalid selected_route: {selected_route!r}")
    clarify_required = _bool(clarify_required) or route == "CLARIFY"
    if clarify_required:
        route = "CLARIFY"

    prefix = _text(route_prefix).strip().lower()
    allowed_routes = _normalize_route_list(candidate_routes)
    if prefix in {"local", "news", "evidence"} or local_response_selected or not allowed_routes:
        allowed_routes = [route]
    elif route not in allowed_routes:
        allowed_routes = [route] + [item for item in allowed_routes if item != route]

    forbidden_routes = [item for item in KNOWN_ROUTES if item not in allowed_routes]
    signals = _canonical_signals(signal_flags)
    context_used = _bool(context_resolution_used)
    evidence_mode, evidence_mode_reason = _choose_evidence_mode(route, signals)
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "precedence_version": _text(precedence_version).strip() or "unknown",
        "original_query": original_query,
        "resolved_execution_query": resolved_execution_query,
        "selected_route": route,
        "allowed_routes": allowed_routes,
        "forbidden_routes": forbidden_routes,
        "winning_signal": _text(winning_signal).strip() or "legacy_policy",
        "intent_family": _text(intent_family).strip(),
        "evidence_mode": evidence_mode,
        "evidence_mode_reason": evidence_mode_reason,
        "clarify_required": clarify_required,
        "authority_basis": _authority_basis(
            selected_route=route,
            clarify_required=clarify_required,
            signals=signals,
            context_resolution_used=context_used,
            contextual_followup_kind=contextual_followup_kind,
            local_response_selected=local_response_selected,
        ),
        "signals": signals,
        "context_resolution_used": context_used,
        "context_referent_confidence": _context_referent_confidence(context_used, contextual_followup_kind),
    }
    validate_route_manifest(manifest)
    return manifest


def validate_route_manifest(manifest: Dict[str, Any]) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("route_manifest must be an object")
    required_str_fields = (
        "manifest_version",
        "precedence_version",
        "original_query",
        "resolved_execution_query",
        "selected_route",
        "winning_signal",
        "authority_basis",
        "context_referent_confidence",
        "evidence_mode",
        "evidence_mode_reason",
    )
    for field in required_str_fields:
        if not isinstance(manifest.get(field), str):
            raise ValueError(f"route_manifest.{field} must be a string")
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError(f"unsupported route_manifest version: {manifest.get('manifest_version')!r}")

    selected_route = _normalize_route(manifest.get("selected_route"))
    if not selected_route:
        raise ValueError("route_manifest.selected_route must be one of LOCAL/NEWS/EVIDENCE/AUGMENTED/CLARIFY")
    intent_family = _text(manifest.get("intent_family", "")).strip()
    if intent_family not in KNOWN_INTENT_FAMILIES:
        raise ValueError("route_manifest.intent_family must be one of self_review/current_evidence/background_overview/synthesis_explanation/local_answer or empty")

    for field in ("allowed_routes", "forbidden_routes"):
        values = manifest.get(field)
        if not isinstance(values, list):
            raise ValueError(f"route_manifest.{field} must be a list")
        normalized = _normalize_route_list(values)
        if len(normalized) != len(values):
            raise ValueError(f"route_manifest.{field} contains invalid or duplicate routes")

    allowed_routes = _normalize_route_list(manifest.get("allowed_routes"))
    forbidden_routes = _normalize_route_list(manifest.get("forbidden_routes"))
    if not allowed_routes:
        raise ValueError("route_manifest.allowed_routes must not be empty")
    if selected_route not in allowed_routes:
        raise ValueError("route_manifest.selected_route must be included in allowed_routes")
    if selected_route in forbidden_routes:
        raise ValueError("route_manifest.selected_route must not be forbidden")
    if set(allowed_routes) & set(forbidden_routes):
        raise ValueError("route_manifest.allowed_routes and forbidden_routes must be disjoint")

    clarify_required = manifest.get("clarify_required")
    if not isinstance(clarify_required, bool):
        raise ValueError("route_manifest.clarify_required must be a boolean")
    if clarify_required and selected_route != "CLARIFY":
        raise ValueError("route_manifest.clarify_required=true requires selected_route=CLARIFY")
    if selected_route == "CLARIFY" and not clarify_required:
        raise ValueError("route_manifest.selected_route=CLARIFY requires clarify_required=true")

    context_resolution_used = manifest.get("context_resolution_used")
    if not isinstance(context_resolution_used, bool):
        raise ValueError("route_manifest.context_resolution_used must be a boolean")

    signals = manifest.get("signals")
    if not isinstance(signals, dict):
        raise ValueError("route_manifest.signals must be an object")
    for field in (
        "temporal",
        "news",
        "conflict",
        "geopolitics",
        "israel_region_live",
        "source_request",
        "url",
        "ambiguity_followup",
        "medical_context",
        "current_product",
    ):
        if not isinstance(signals.get(field), bool):
            raise ValueError(f"route_manifest.signals.{field} must be a boolean")
    evidence_mode = manifest.get("evidence_mode")
    if not isinstance(evidence_mode, str):
        raise ValueError("route_manifest.evidence_mode must be a string")
    if evidence_mode and evidence_mode not in EVIDENCE_MODES:
        raise ValueError("route_manifest.evidence_mode must be one of LIGHT/FULL or empty")
    evidence_reason = manifest.get("evidence_mode_reason")
    if not isinstance(evidence_reason, str):
        raise ValueError("route_manifest.evidence_mode_reason must be a string")
    normalized_reason = canonical_evidence_mode_reason(evidence_mode, evidence_reason)
    if evidence_mode:
        if normalized_reason not in EVIDENCE_MODE_REASONS - {EVIDENCE_MODE_REASON_NON_EVIDENCE}:
            raise ValueError("route_manifest.evidence_mode_reason must be a canonical evidence reason for LIGHT/FULL routes")
    elif normalized_reason not in {"", EVIDENCE_MODE_REASON_NON_EVIDENCE}:
        raise ValueError("route_manifest.evidence_mode_reason must be empty or not_evidence_route for non-evidence routes")
