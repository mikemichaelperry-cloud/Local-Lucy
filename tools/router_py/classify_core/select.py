"""Route selection orchestration and decision builders."""

# ruff: noqa: E402

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.classify_core.guards import (
    _is_capability_query,
    _is_hostile_override_attempt,
    _is_public_figure_age_query,
    _LOCAL_ALWAYS_SHORT,
)
from router_py.classify_core.memory import (
    _CONTINUATION_FOLLOWUP_RE,
    _LIVE_DATA_KEYWORDS,
    _MEMORY_EXPLICIT_RECALL_RE,
    _MEMORY_FOLLOWUP_STRONG_RE,
    _load_feedback_buffer,
    _memory_routing_gate,
)
from router_py.classify_core.router import _get_router, _log_decision
from router_py.logging_config import get_logger
from router_py.policy_router import PolicyDecision, PolicyRouter
from router_py.provider_resolver import provider_usage_class_for
from router_py.request_types import ClassificationResult, RoutingDecision
from tools.xdg_paths import lucy_runtime_namespace_root
from router_py import provider_resolver

_LOGGER = get_logger("router_py.classify_core.select")

_POLICY_ROUTER = PolicyRouter()

_LLM_ARBITER_ROUTES = (
    "LOCAL",
    "AUGMENTED",
    "NEWS",
    "EVIDENCE",
    "TIME",
    "WEATHER",
    "FINANCE",
    "CLARIFY",
)

def _call_llm_arbiter(query: str) -> str | None:
    """Ask a small local Ollama model to resolve a low-confidence route.

    Returns one of the allowed route names, or None if Ollama is unreachable
    or returns an unparseable answer.  The arbiter is intentionally optional;
    callers must fall back to the router's own decision when this returns None.
    """
    model = os.environ.get("LUCY_ARB_MODEL", "llama3.2")
    base_url = os.environ.get("LUCY_OLLAMA_URL", "http://127.0.0.1:11434")
    prompt = (
        "You are a routing assistant. Choose the single best route for the user query.\n"
        "Valid routes: LOCAL, AUGMENTED, NEWS, EVIDENCE, TIME, WEATHER, FINANCE, CLARIFY.\n"
        "LOCAL = creative, opinion, personal, coding, math, stable knowledge.\n"
        "AUGMENTED = current factual lookup needing external sources.\n"
        "NEWS = news headlines.\n"
        "EVIDENCE = medical, legal, or source-verified facts.\n"
        "TIME = current time.\n"
        "WEATHER = weather forecast.\n"
        "FINANCE = live market data.\n"
        "CLARIFY = ambiguous or missing information.\n\n"
        f"Query: {query}\n"
        "Route:"
    )
    try:
        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0},
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        text = result.get("response", "").strip().upper()
        for route in _LLM_ARBITER_ROUTES:
            if route in text:
                return route
        return None
    except Exception:
        return None

def _routing_decision_from_policy(
    classification: ClassificationResult,
    policy_decision: PolicyDecision,
    query: str = "",
) -> RoutingDecision:
    """Convert a deterministic PolicyDecision into a RoutingDecision."""
    intent_family = classification.intent_family
    if policy_decision.route in ("NEWS", "TIME", "WEATHER", "FINANCE"):
        intent_family = "current_evidence"

    decision = RoutingDecision(
        route=policy_decision.route,
        mode="AUTO",
        intent_family=intent_family,
        confidence=policy_decision.confidence,
        provider=policy_decision.provider,
        provider_usage_class=policy_decision.provider_usage_class,
        evidence_mode=policy_decision.evidence_mode,
        evidence_reason=policy_decision.evidence_reason,
        requires_evidence=policy_decision.requires_evidence,
        policy_reason=policy_decision.policy_reason,
        ephemeral=policy_decision.ephemeral,
        decision_stage="policy",
        reason_code=policy_decision.reason_code,
        matched_rule=policy_decision.matched_rule,
        trace=policy_decision.trace,
    )
    return decision

def _make_local_decision(classification: ClassificationResult, query: str = "") -> RoutingDecision:
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
        ephemeral=False,
    )


def _make_augmented_decision(
    classification: ClassificationResult,
    prefer_paid: bool = False,
    query: str = "",
) -> RoutingDecision:
    """Create an augmented or evidence routing decision."""

    # Medical and veterinary queries route to EVIDENCE (strict trusted sources)
    if classification.evidence_reason in (
        "medical_context",
        "medical_body_symptom",
        "veterinary_context",
    ):
        return RoutingDecision(
            route="EVIDENCE",
            mode="AUTO",
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            provider="trusted",
            provider_usage_class="local",
            evidence_mode=classification.evidence_mode,
            evidence_reason=classification.evidence_reason,
            requires_evidence=bool(classification.evidence_mode),
            policy_reason=f"evidence_required_{classification.evidence_reason}",
            ephemeral=False,
        )

    provider = provider_resolver.resolve_provider(classification, prefer_paid=prefer_paid)

    usage_class = provider_usage_class_for(provider)

    # Determine policy reason
    if classification.evidence_mode:
        policy_reason = f"evidence_required_{classification.evidence_reason}"
    else:
        policy_reason = "background_query"

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
        policy_reason=policy_reason,
        ephemeral=False,
    )


def _make_local_with_fallback(
    classification: ClassificationResult, query: str = ""
) -> RoutingDecision:
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
        ephemeral=False,
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
        ephemeral=True,
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
        ephemeral=True,
    )


def _make_weather_decision(classification: ClassificationResult) -> RoutingDecision:
    """Create a WEATHER route decision for weather queries."""
    return RoutingDecision(
        route="WEATHER",
        mode="AUTO",
        intent_family=classification.intent_family or "ephemeral_query",
        confidence=classification.confidence,
        provider="weather",
        provider_usage_class="free",
        evidence_mode=classification.evidence_mode,
        evidence_reason=classification.evidence_reason,
        requires_evidence=False,
        policy_reason="weather_provider",
        ephemeral=True,
    )

def select_route(
    classification: ClassificationResult,
    policy: str = "fallback_only",
    forced_mode: str | None = None,
    query: str = "",
    session_id: str = "default",
) -> RoutingDecision:
    """
    Select final route using the embedding router.

    Args:
        classification: Result from classify_intent()
        policy: Augmentation policy (disabled, fallback_only, direct_allowed)
        forced_mode: Optional forced mode override
        query: Original query string (required for embedding router)

    Returns:
        RoutingDecision with final route and provider
    """
    # Hard overrides
    if forced_mode == "FORCED_OFFLINE":
        return _make_local_decision(classification, query=query)

    if forced_mode == "FORCED_ONLINE":
        return _make_augmented_decision(classification, prefer_paid=True, query=query)

    if policy == "disabled":
        return _make_local_decision(classification, query=query)

    if classification.force_local:
        return _make_local_decision(classification, query=query)

    # Hostile override guard: jailbreak / authority-bypass attempts must
    # never trigger paid providers or live data sources.
    if query and _is_hostile_override_attempt(query):
        decision = _make_local_decision(classification, query=query)
        _log_decision(
            query or "",
            decision,
            embedding_route="HOSTILE_OVERRIDE",
            guards_fired=["hostile_override"],
        )
        return decision

    # Self-knowledge guard: identity, version, and capability questions must
    # stay LOCAL so the model answers from its injected SELF_KNOWLEDGE prompt.
    # Without this guard the embedding router may send them to AUGMENTED, where
    # they are blocked when evidence is disabled.
    if query and _is_capability_query(query):
        decision = _make_local_decision(classification, query=query)
        _log_decision(
            query or "",
            decision,
            embedding_route="SELF_KNOWLEDGE",
            guards_fired=["self_knowledge"],
        )
        return decision

    # Shared lowercased query for the embedding path — compute once, reuse everywhere
    q_lower = query.lower()

    # Policy router (Phase 1): deterministic gates run before the embedding
    # router so operational routes (finance, time, weather, news, medical/vet,
    # current information, etc.) are explicit, explainable, and testable.
    policy_decision = _POLICY_ROUTER.apply(query, classification)
    if policy_decision is not None:
        decision = _routing_decision_from_policy(classification, policy_decision, query=query)
        _log_decision(
            query or "",
            decision,
            embedding_route=policy_decision.reason_code,
            guards_fired=[policy_decision.matched_rule],
        )
        return decision

    # Short-query guard: very short utterances that look like feedback,
    # confirmations, or follow-ups should stay LOCAL regardless of embedding,
    # UNLESS the prior exchange required evidence AND the current query is an
    # informational follow-up (not feedback or social). Drug-interaction
    # follow-ups like "why?" need AUGMENTED; "thanks" and "wrong" do not.
    if query and len(query.strip()) < 12 and classification.intent_family == "local_answer":
        # Feedback, social, and confirmation utterances always stay LOCAL.
        # Social greetings (including short ones like "What's up?") must never
        # inherit a prior AUGMENTED route.
        q_lower = query.strip().lower().rstrip("?")
        if q_lower not in _LOCAL_ALWAYS_SHORT:
            try:
                # Read buffer directly from disk to avoid module-aliasing issues
                # (classify.py may import feedback_buffer under a different name
                # than main.py, creating separate singleton instances).
                # Cached by mtime to avoid redundant reads (Phase 3D).
                _ns = Path(
                    os.environ.get(
                        "LUCY_RUNTIME_NAMESPACE_ROOT",
                        str(lucy_runtime_namespace_root()),
                    )
                )
                _buf_path = _ns / "feedback_buffer.json"
                if _buf_path.exists():
                    _data = _load_feedback_buffer(_buf_path)
                    _exchanges = _data.get("exchanges", [])
                    if _exchanges:
                        _last_route = str(_exchanges[-1].get("route", "")).upper()
                        if _last_route in (
                            "AUGMENTED",
                            "EVIDENCE",
                            "NEWS",
                            "TIME",
                            "WEATHER",
                            "FINANCE",
                        ):
                            # Informational follow-up to an evidence route: inherit
                            return _make_augmented_decision(
                                classification, prefer_paid=False, query=query
                            )
            except Exception:
                pass
        return _make_local_decision(classification, query=query)

    # Garbage / noise guard: repetitive nonsense, all-caps shouting, or
    # single-word repetition should stay LOCAL instead of trusting the embedding.
    if query:
        q_stripped = query.strip()
        # Single word repeated 3+ times, case-insensitive (e.g. "The the the the")
        words = q_stripped.split()
        if len(words) >= 3 and len(set(w.lower() for w in words)) == 1:
            return _make_local_decision(classification, query=query)
        # All-caps with no lowercase letters and at least 5 chars
        if len(q_stripped) >= 5 and q_stripped.isupper() and q_stripped.isalpha():
            return _make_local_decision(classification, query=query)

    # Fallback when no query provided
    if not query:
        if classification.evidence_mode == "required":
            return _make_augmented_decision(classification, prefer_paid=True, query=query)
        if classification.intent_family == "local_answer":
            return _make_local_decision(classification, query=query)
        if classification.needs_web:
            if policy == "direct_allowed":
                return _make_augmented_decision(classification, prefer_paid=False, query=query)
            else:
                return _make_local_with_fallback(classification, query=query)
        return _make_local_decision(classification, query=query)

    # Medical/veterinary follow-up guard: after an EVIDENCE response to a
    # medical or veterinary query, ambiguous follow-ups ("what about that",
    # "is it safe", "why") must NOT silently fall back to LOCAL via the
    # embedding router. Bias them toward AUGMENTED so cited sources remain
    # available.
    if query and len(query.strip()) <= 30:
        _followup_q = query.strip().lower()
        _followup_pronouns = ("it", "that", "this", "those", "them", "they")
        _followup_stems = (
            "why",
            "what about",
            "how about",
            "side effect",
            "dosage",
            "dose",
            "safe",
            "interact",
            "take with",
            "drink",
            "eat",
            "food",
            "alcohol",
            "should i",
        )
        _is_ambiguous_followup = any(p in _followup_q.split() for p in _followup_pronouns) or any(
            stem in _followup_q for stem in _followup_stems
        )
        if _is_ambiguous_followup:
            try:
                _ns2 = Path(
                    os.environ.get(
                        "LUCY_RUNTIME_NAMESPACE_ROOT",
                        str(lucy_runtime_namespace_root()),
                    )
                )
                _buf_path2 = _ns2 / "feedback_buffer.json"
                if _buf_path2.exists():
                    _data2 = _load_feedback_buffer(_buf_path2)
                    _exchanges2 = _data2.get("exchanges", [])
                    if _exchanges2:
                        _last2 = _exchanges2[-1]
                        _last_route2 = str(_last2.get("route", "")).upper()
                        _last_query2 = str(_last2.get("query", "") or "").lower()
                        # Infer medical/vet context from prior query keywords
                        _medical_keywords = (
                            "side effect",
                            "metformin",
                            "ibuprofen",
                            "aspirin",
                            "warfarin",
                            "amoxicillin",
                            "tadalafil",
                            "diabetes",
                            "hypertension",
                            "medication",
                            "drug",
                            "dosage",
                            "symptom",
                            "chest",
                            "shortness of breath",
                            "headache",
                            "fever",
                            "nausea",
                            "pregnant",
                            "surgery",
                            "treatment",
                            "dog",
                            "cat",
                            "canine",
                            "feline",
                            "veterinary",
                            "vet",
                            "hip dysplasia",
                            "heartworm",
                            "hyperthyroidism",
                            "bloat",
                        )
                        _was_medical = any(kw in _last_query2 for kw in _medical_keywords)
                        if _last_route2 == "EVIDENCE" and _was_medical:
                            decision = _make_augmented_decision(
                                classification, prefer_paid=False, query=query
                            )
                            _log_decision(
                                query or "",
                                decision,
                                embedding_route="MEDICAL_FOLLOWUP_GUARD",
                                guards_fired=["medical_followup_guard"],
                            )
                            return decision
            except Exception:
                pass

    # Primary path: embedding router
    router = _get_router()
    if router and query:
        try:
            result = router.predict(query)
            route = result.get("route", "LOCAL")
            intent_family = result.get("intent_family", classification.intent_family)
            confidence = result.get("confidence", classification.confidence)
            evidence_mode = result.get("evidence_mode", "")
            evidence_reason = result.get("evidence_reason") or classification.evidence_reason
            # Prefer classification evidence_reason for medical/veterinary context
            # (policy layer is more accurate than embedding router for these)
            if classification.evidence_reason in (
                "medical_context",
                "medical_body_symptom",
                "veterinary_context",
            ):
                evidence_reason = classification.evidence_reason
                evidence_mode = "required"

            # Prefer classification evidence_reason for conflict/live-news,
            # personal-finance reasoning, and financial data (policy layer is
            # more accurate than embedding router for these).
            if classification.evidence_reason in (
                "conflict_live",
                "personal_finance_reasoning",
                "financial_data",
            ):
                evidence_reason = classification.evidence_reason
                if classification.evidence_reason == "personal_finance_reasoning":
                    evidence_mode = ""
                elif classification.evidence_reason in (
                    "conflict_live",
                    "financial_data",
                ):
                    evidence_mode = "required"

            requires_evidence = evidence_mode == "required"
            embedding_route = result.get("embedding_route", route)
            guards_fired = result.get("guards_fired", [])
            top_k_neighbours = result.get("top_k_neighbours", [])
            ephemeral = result.get("ephemeral", False)

            # Confidence-triggered LLM arbiter: when the embedding classifier is
            # uncertain (low confidence and low margin), ask a small local model
            # before applying the remaining safety overrides.  If Ollama is
            # unavailable we keep the router's decision but mark it low-confidence.
            low_confidence = False
            confidence_margin = result.get("confidence_margin", 0.0)
            if confidence < 0.60 and confidence_margin < 0.15:
                low_confidence = True
                llm_route = _call_llm_arbiter(query)
                if llm_route:
                    route = llm_route
                    embedding_route = f"llm_arbiter:{llm_route}"
                    guards_fired = guards_fired + ["llm_arbiter"]

            # Conflict analysis override: the embedding router sometimes returns LOCAL
            # for live-conflict analysis questions (e.g. "Will Russia win in Ukraine").
            # Force AUGMENTED so the user gets real-time, cited information.
            if evidence_reason == "conflict_live" and route == "LOCAL":
                route = "AUGMENTED"
                guards_fired = guards_fired + ["conflict_live_analysis_override"]

            # Medical/veterinary safety override: the embedding router sometimes
            # returns LOCAL for symptom queries. Force EVIDENCE so the user gets
            # cited, vetted information rather than parametric knowledge.
            if evidence_reason in (
                "medical_context",
                "medical_body_symptom",
                "veterinary_context",
            ):
                route = "EVIDENCE"
                guards_fired = guards_fired + ["medical_vet_safety_override"]

            # Financial data override: the embedding router sometimes returns LOCAL
            # for live financial data queries (e.g. "current stock price of Apple",
            # "bitcoin price today"). Force AUGMENTED so the user gets current
            # market data rather than stale parametric knowledge.
            if evidence_reason == "financial_data" and route == "LOCAL":
                route = "AUGMENTED"
                guards_fired = guards_fired + ["financial_data_override"]

            # Public-figure age override: the embedding router currently routes
            # "How old is Bill Clinton?" to LOCAL. Force AUGMENTED so the answer
            # is computed from current date + web-augmented sources, not stale
            # parametric knowledge that may be off by a year.
            if route == "LOCAL" and _is_public_figure_age_query(query):
                route = "AUGMENTED"
                evidence_reason = "public_figure_age"
                guards_fired = guards_fired + ["public_figure_age_override"]

            # Memory-aware routing gate: override live-data routes for follow-ups
            memory_gate_override = _memory_routing_gate(query, route, session_id=session_id)
            if memory_gate_override:
                route = memory_gate_override
                guards_fired = guards_fired + ["memory_routing_gate"]

            # Diagnostic trace for embedding/router path
            embedding_trace = {
                "routing_source": result.get("routing_source", "knn"),
                "classifier_route": result.get("classifier_route", ""),
                "classifier_confidence": result.get("classifier_confidence", 0.0),
                "confidence_margin": result.get("confidence_margin", 0.0),
                "confidence_entropy": result.get("confidence_entropy", 0.0),
                "guards_fired": guards_fired,
            }
            embedding_meta = {
                "decision_stage": "embedding",
                "reason_code": f"semantic:{embedding_trace['routing_source']}",
                "matched_rule": embedding_trace["routing_source"],
                "trace": embedding_trace,
            }

            if route == "LOCAL":
                decision = RoutingDecision(
                    route="LOCAL",
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider="local",
                    provider_usage_class="local",
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason="router_local",
                    ephemeral=ephemeral,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )
            elif route == "NEWS":
                decision = RoutingDecision(
                    route="NEWS",
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider="news",
                    provider_usage_class="local",
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason="router_news",
                    ephemeral=True,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )
            elif route == "TIME":
                decision = RoutingDecision(
                    route="TIME",
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider="timeapi",
                    provider_usage_class="free",
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason="router_time",
                    ephemeral=True,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )
            elif route == "WEATHER":
                decision = RoutingDecision(
                    route="WEATHER",
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider="weather",
                    provider_usage_class="free",
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason="router_weather",
                    ephemeral=True,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )
            elif route == "FINANCE":
                decision = RoutingDecision(
                    route="FINANCE",
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider="finance",
                    provider_usage_class="free",
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason="router_finance",
                    ephemeral=True,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )
            else:  # AUGMENTED or EVIDENCE

                provider = provider_resolver.resolve_provider(classification)
                usage_class = provider_usage_class_for(provider)

                # Medical and veterinary queries route to EVIDENCE (strict trusted sources)
                # instead of AUGMENTED (general knowledge sources)
                if evidence_reason in (
                    "medical_context",
                    "medical_body_symptom",
                    "veterinary_context",
                ):
                    route = "EVIDENCE"
                    provider = "trusted"
                    usage_class = "local"
                    policy_reason = f"router_evidence_{evidence_reason}"
                else:
                    route = "AUGMENTED"
                    if evidence_reason == "news_synthesis":
                        policy_reason = "router_news_synthesis"
                    elif evidence_reason:
                        policy_reason = f"router_evidence_{evidence_reason}"
                    else:
                        policy_reason = "router_augmented"

                decision = RoutingDecision(
                    route=route,
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider=provider,
                    provider_usage_class=usage_class,
                    evidence_mode=evidence_mode,
                    evidence_reason=evidence_reason,
                    requires_evidence=requires_evidence,
                    policy_reason=policy_reason,
                    ephemeral=ephemeral,
                    low_confidence=low_confidence,
                    **embedding_meta,
                )

            # Continuation follow-up inheritance: "more details", "tell me more",
            # "elaborate", etc. should stay on the previous route so the user gets
            # a cited/elaborated answer instead of "what do you want me to clarify?".
            if _CONTINUATION_FOLLOWUP_RE.search(query):
                try:
                    _ns_cont = Path(
                        os.environ.get(
                            "LUCY_RUNTIME_NAMESPACE_ROOT",
                            str(lucy_runtime_namespace_root()),
                        )
                    )
                    _buf_path_cont = _ns_cont / "feedback_buffer.json"
                    if _buf_path_cont.exists():
                        _data_cont = _load_feedback_buffer(_buf_path_cont)
                        _exchanges_cont = _data_cont.get("exchanges", [])
                        if _exchanges_cont:
                            _last_route_cont = str(_exchanges_cont[-1].get("route", "")).upper()
                            if _last_route_cont in (
                                "AUGMENTED",
                                "EVIDENCE",
                                "NEWS",
                                "TIME",
                                "WEATHER",
                                "FINANCE",
                            ):
                                # Preserve the prior evidence/live-data route.  Copy the
                                # current decision's metadata but swap the route/provider.
                                prior_provider = {
                                    "AUGMENTED": decision.provider,
                                    "EVIDENCE": "trusted",
                                    "NEWS": "news",
                                    "TIME": "timeapi",
                                    "WEATHER": "weather",
                                    "FINANCE": "finance",
                                }.get(_last_route_cont, decision.provider)
                                prior_usage = {
                                    "AUGMENTED": decision.provider_usage_class,
                                    "EVIDENCE": "local",
                                    "NEWS": "local",
                                    "TIME": "free",
                                    "WEATHER": "free",
                                    "FINANCE": "free",
                                }.get(_last_route_cont, decision.provider_usage_class)
                                decision = RoutingDecision(
                                    route=_last_route_cont,
                                    mode="AUTO",
                                    intent_family=decision.intent_family,
                                    confidence=decision.confidence,
                                    provider=prior_provider,
                                    provider_usage_class=prior_usage,
                                    evidence_mode=decision.evidence_mode,
                                    evidence_reason=decision.evidence_reason,
                                    requires_evidence=decision.requires_evidence,
                                    policy_reason="continuation_followup_inherit",
                                    ephemeral=decision.ephemeral,
                                    low_confidence=decision.low_confidence,
                                    trace=decision.trace,
                                )
                                guards_fired = guards_fired + ["continuation_followup_inherit"]
                except Exception:
                    pass

            # Memory follow-up guard: if the query is an explicit memory recall,
            # override AUGMENTED/NEWS/TIME/WEATHER back to LOCAL.
            # EVIDENCE routes (medical/vet/financial/legal) are preserved — a follow-up
            # "why?" to a medical answer must stay on the evidence route, not drop to LOCAL.
            # Only active when session memory is enabled, to avoid false positives on
            # standalone queries that happen to contain follow-up words (e.g. "previous").
            if (
                decision.route in ("AUGMENTED", "NEWS", "TIME", "WEATHER", "FINANCE")
                and os.environ.get("LUCY_SESSION_MEMORY", "0") == "1"
            ):
                q = query.strip()
                if q and (
                    _MEMORY_EXPLICIT_RECALL_RE.search(q) or _MEMORY_FOLLOWUP_STRONG_RE.search(q)
                ):
                    # Continuation prompts already inherited the prior route above.
                    if not _CONTINUATION_FOLLOWUP_RE.search(q):
                        # Live-data keywords preserve embedding decision (e.g. "What about the weather?")
                        q_lower = q.lower()
                        has_live_data = any(kw in q_lower for kw in _LIVE_DATA_KEYWORDS)
                        if not has_live_data:
                            decision = RoutingDecision(
                                route="LOCAL",
                                mode="AUTO",
                                intent_family=decision.intent_family,
                                confidence=decision.confidence,
                                provider="local",
                                provider_usage_class="local",
                                evidence_mode="",
                                evidence_reason="memory_followup",
                                requires_evidence=False,
                                policy_reason="memory_followup_override",
                                ephemeral=decision.ephemeral,
                                low_confidence=decision.low_confidence,
                            )
                            guards_fired = guards_fired + ["memory_followup_override"]

            _log_decision(
                query,
                decision,
                embedding_route=embedding_route,
                guards_fired=guards_fired,
                top_k_neighbours=top_k_neighbours,
                memory_gate_override=memory_gate_override or "",
            )
            return decision
        except Exception as _router_exc:
            # Router failed — fall back to LOCAL, but log the real reason so
            # missing-function bugs don't wear camouflage.
            _exc_type = type(_router_exc).__name__
            _exc_msg = str(_router_exc)
            decision = _make_local_decision(classification, query=query)
            _log_decision(
                query or "",
                decision,
                embedding_route="FALLBACK_LOCAL",
                guards_fired=["router_failure", f"exception_{_exc_type}"],
            )
            _LOGGER.warning(
                "router_exception_fallback_local",
                extra={
                    "exception_type": _exc_type,
                    "exception_message": _exc_msg,
                },
                exc_info=True,
            )
            return decision

    # Safe fallback (only reached if router block didn't run at all, e.g. no query)
    decision = _make_local_decision(classification, query=query)
    _log_decision(
        query or "",
        decision,
        embedding_route="FALLBACK_LOCAL",
        guards_fired=["router_failure"],
    )
    return decision

