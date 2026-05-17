#!/usr/bin/env python3
"""
Intent classification integration - Python API for router classification.

Single-path router: ModernBERT embedding k-NN + keyword guards.
No shadow/legacy dual path. One router, one decision.
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Centralized pipeline types (Stage 5 migration)
from router_py.request_types import ClassificationResult, RoutingDecision

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

# Import our policy functions — support both package and direct imports
try:
    from .policy import requires_evidence_mode, provider_usage_class_for
except ImportError:
    from policy import requires_evidence_mode, provider_usage_class_for



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


# ============================================================================
# Single-path router: ModernBERT embedding k-NN
# ============================================================================

_ROUTER = None


def _get_router():
    """Lazy-load the embedding router."""
    global _ROUTER
    if _ROUTER is None:
        try:
            router_dir = Path(__file__).resolve().parent.parent.parent / "models" / "router"
            if str(router_dir) not in sys.path:
                sys.path.insert(0, str(router_dir))
            from hybrid_router import HybridRouter
            _ROUTER = HybridRouter(
                embeddings_path=str(router_dir / "comprehensive_embeddings.npy"),
                examples_path=str(router_dir / "comprehensive_examples.json"),
            )
        except Exception:
            _ROUTER = False  # Mark as failed
    return _ROUTER if _ROUTER is not False else None


def prewarm_router() -> bool:
    """Eagerly load the embedding router so first query isn't penalized.

    Returns True if router loaded successfully, False otherwise.
    Safe to call multiple times; only loads on first call.
    """
    try:
        router = _get_router()
        return router is not None
    except Exception:
        return False


def _get_log_path() -> Path | None:
    """Get router decision log path from environment."""
    log_dir = os.environ.get("LUCY_ROUTER_LOG_DIR")
    if log_dir:
        path = Path(log_dir) / "router_decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _log_decision(
    query: str,
    decision: RoutingDecision,
    *,
    embedding_route: str = "",
    guards_fired: list[str] | None = None,
    top_k_neighbours: list[dict] | None = None,
    legacy_route_audit: str = "",
    memory_gate_override: str = "",
) -> None:
    """Log routing decision if logging is enabled.

    Logs everything needed to diagnose a misroute:
    - final route, intent, confidence, provider
    - embedding_route (what k-NN voted before guard overrides)
    - guards_fired (which keyword guards triggered)
    - top_k_neighbours (nearest examples for transparency)
    - legacy_route_audit (what the old keyword router would have chosen)
    """
    log_path = _get_log_path()
    if not log_path:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "query": query,
            "route": decision.route,
            "intent": decision.intent_family,
            "confidence": decision.confidence,
            "provider": decision.provider,
            "evidence_reason": decision.evidence_reason,
            "policy_reason": decision.policy_reason,
            "embedding_route": embedding_route,
            "guards_fired": guards_fired or [],
            "top_k_neighbours": top_k_neighbours or [],
            "legacy_route_audit": legacy_route_audit,
            "memory_gate_override": memory_gate_override,
            "legacy_agrees": decision.route == legacy_route_audit,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _select_route_legacy(
    classification: ClassificationResult,
    policy: str = "fallback_only",
    forced_mode: str | None = None,
    query: str = "",
) -> RoutingDecision:
    """Legacy keyword-based router — preserved for rollback only.

    Set LUCY_ROUTER_LEGACY_PRIMARY=1 to use this instead of the embedding router.
    """
    if forced_mode == "FORCED_OFFLINE":
        return _make_local_decision(classification, query=query)
    if forced_mode == "FORCED_ONLINE":
        return _make_augmented_decision(classification, prefer_paid=True, query=query)
    if classification.force_local:
        return _make_local_decision(classification, query=query)
    if policy == "disabled":
        return _make_local_decision(classification, query=query)
    if classification.evidence_mode == "required":
        return _make_augmented_decision(classification, prefer_paid=True, query=query)
    if classification.intent_family == "current_evidence":
        if classification.category in ("news_world", "news_israel", "news_australia"):
            return _make_news_decision(classification)
        if classification.category == "time_query":
            return _make_time_decision(classification)
        if policy == "fallback_only":
            return _make_local_with_fallback(classification, query=query)
        elif policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False, query=query)
        return _make_local_decision(classification, query=query)
    if classification.needs_web:
        if classification.intent_family in ("background_overview", "synthesis_explanation"):
            if policy == "direct_allowed":
                return _make_augmented_decision(classification, prefer_paid=False, query=query)
            return _make_local_with_fallback(classification, query=query)
        if policy == "fallback_only":
            return _make_local_with_fallback(classification, query=query)
        elif policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False, query=query)
    if classification.intent_family in ("background_overview", "synthesis_explanation"):
        if policy == "direct_allowed":
            return _make_augmented_decision(classification, prefer_paid=False, query=query)
        return _make_local_with_fallback(classification, query=query)
    if classification.intent_family == "local_answer":
        return _make_local_decision(classification, query=query)
    return _make_local_decision(classification, query=query)


def select_route(
    classification: ClassificationResult,
    policy: str = "fallback_only",
    forced_mode: str | None = None,
    query: str = "",
    session_id: str = "default",
) -> RoutingDecision:
    """
    Select final route using the embedding router.

    Rollback: set LUCY_ROUTER_LEGACY_PRIMARY=1 to use the legacy keyword router.

    Args:
        classification: Result from classify_intent()
        policy: Augmentation policy (disabled, fallback_only, direct_allowed)
        forced_mode: Optional forced mode override
        query: Original query string (required for embedding router)

    Returns:
        RoutingDecision with final route and provider
    """
    # Rollback: legacy keyword router (for emergency use only)
    if os.environ.get("LUCY_ROUTER_LEGACY_PRIMARY", "").strip().lower() in ("1", "on", "true", "yes"):
        decision = _select_route_legacy(classification, policy, forced_mode, query=query)
        _log_decision(
            query or "",
            decision,
            embedding_route="LEGACY",
            guards_fired=["legacy_rollback"],
        )
        return decision

    # Hard overrides
    if forced_mode == "FORCED_OFFLINE":
        return _make_local_decision(classification, query=query)

    if forced_mode == "FORCED_ONLINE":
        return _make_augmented_decision(classification, prefer_paid=True, query=query)

    if policy == "disabled":
        return _make_local_decision(classification, query=query)

    if classification.force_local:
        return _make_local_decision(classification, query=query)

    # Short-query guard: very short utterances that look like feedback,
    # confirmations, or follow-ups should stay LOCAL regardless of embedding,
    # UNLESS the prior exchange required evidence AND the current query is an
    # informational follow-up (not feedback or social). Drug-interaction
    # follow-ups like "why?" need AUGMENTED; "thanks" and "wrong" do not.
    if query and len(query.strip()) < 12 and classification.intent_family == "local_answer":
        # Feedback, social, and confirmation utterances always stay LOCAL
        q_lower = query.strip().lower().rstrip("?")
        local_always = {
            "correct", "yes", "no", "right", "wrong", "thanks", "thank you",
            "ok", "okay", "got it", "understood", "sure", "fine", "exactly",
            "perfect", "great", "good", "nice", "awesome", "cool", "nope",
            "nah", "not really", "that was wrong", "bad answer", "incorrect",
            "that's wrong", "not right", "that was right", "good answer",
            "well done", "nice job", "exactly right", "spot on", "you got it",
            "hi", "hello", "hey", "bye", "goodbye", "see you", "yo",
            "stop", "pause", "wait", "hold on", "never mind", "nevermind",
            "forget it", "ignore that", "scratch that", "cancel", "redo",
            "try again", "start over", "back", "previous", "next", "skip",
            "done", "finished", "enough", "that's enough", "wow", "oh", "ah",
            "oh no", "really", "seriously", "interesting", "makes sense",
            "i see", "i get it", "of course", "obviously", "naturally",
            "indeed", "absolutely", "definitely", "certainly", "probably",
            "maybe", "perhaps", "possibly", "not sure", "i don't know",
            "who knows", "whatever", "alright", "sounds good", "works for me",
            "fair enough", "i suppose", "i guess", "thx", "kk", "k", "yea",
            "yep", "yup", "correcr", "corect", "wrng", "wrond", "incorect",
            "thabks", "okkk", "uh", "um", "hmm", "huh",
        }
        if q_lower not in local_always:
            try:
                # Read buffer directly from disk to avoid module-aliasing issues
                # (classify.py may import feedback_buffer under a different name
                # than main.py, creating separate singleton instances).
                _ns = Path(
                    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
                )
                _buf_path = _ns / "feedback_buffer.json"
                if _buf_path.exists():
                    import json
                    _data = json.loads(_buf_path.read_text(encoding="utf-8"))
                    _exchanges = _data.get("exchanges", [])
                    if _exchanges:
                        _last_route = str(_exchanges[-1].get("route", "")).upper()
                        if _last_route in ("AUGMENTED", "EVIDENCE", "NEWS", "TIME", "WEATHER"):
                            # Informational follow-up to an evidence route: inherit
                            return _make_augmented_decision(classification, prefer_paid=False, query=query)
            except Exception:
                pass
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

    # Primary path: embedding router
    router = _get_router()
    if router and query:
        try:
            result = router.predict(query)
            route = result.get("route", "LOCAL")
            intent_family = result.get("intent_family", classification.intent_family)
            confidence = result.get("confidence", classification.confidence)
            evidence_mode = result.get("evidence_mode", "")
            evidence_reason = result.get("evidence_reason", classification.evidence_reason)
            # Prefer classification evidence_reason for medical/veterinary context
            # (policy layer is more accurate than embedding router for these)
            if classification.evidence_reason in (
                "medical_context", "medical_body_symptom", "veterinary_context"
            ):
                evidence_reason = classification.evidence_reason
                evidence_mode = "required"
            
            # Prefer classification evidence_reason for personal-finance reasoning
            # (policy layer distinguishes reasoning from live data; embedding router
            # often conflates them into generic financial_data)
            if classification.evidence_reason == "personal_finance_reasoning":
                evidence_reason = classification.evidence_reason
                evidence_mode = ""
            
            requires_evidence = evidence_mode == "required"
            embedding_route = result.get("embedding_route", route)
            guards_fired = result.get("guards_fired", [])
            top_k_neighbours = result.get("top_k_neighbours", [])
            ephemeral = result.get("ephemeral", False)

            # Memory-aware routing gate: override live-data routes for follow-ups
            memory_gate_override = _memory_routing_gate(query, route, session_id=session_id)
            if memory_gate_override:
                route = memory_gate_override
                guards_fired = guards_fired + ["memory_routing_gate"]

            # Medical/veterinary safety guard: override ANY embedding prediction
            # (WEATHER, NEWS, TIME, LOCAL, AUGMENTED) when policy detects
            # medical or veterinary context. Safety-critical queries must
            # never route to weather, news, or general knowledge.
            is_medical_or_vet = classification.evidence_reason in (
                "medical_context", "medical_body_symptom", "veterinary_context"
            )
            if is_medical_or_vet and classification.evidence_mode == "required" and route != "EVIDENCE":
                route = "EVIDENCE"
                provider = "trusted"
                evidence_mode = "required"
                evidence_reason = classification.evidence_reason
                requires_evidence = True
                guards_fired = guards_fired + ["medical_vet_safety_override"]

            # Personal-finance reasoning guard: override embedding AUGMENTED when
            # the query is asking for opinion/planning ("comfortable bank balance",
            # "how should I budget") rather than live market data. The policy layer
            # already downgraded evidence_mode; if the classifier agrees it's not
            # evidence-required, keep it LOCAL so the model can reason instead of
            # forcing a generic evidence lookup.
            if (
                route == "AUGMENTED"
                and classification.evidence_reason == "personal_finance_reasoning"
                and classification.evidence_mode != "required"
            ):
                route = "LOCAL"
                evidence_mode = ""
                evidence_reason = "personal_finance_reasoning"
                requires_evidence = False
                guards_fired = guards_fired + ["personal_finance_reasoning_override"]

            # Override embedding LOCAL when intent classifier strongly signals evidence
            raw_signals = classification.raw_plan.get("routing_signals", {}) if classification.raw_plan else {}
            candidate_routes = classification.raw_plan.get("candidate_routes", []) if classification.raw_plan else []
            # Medical/veterinary evidence requirements override ephemeral classification
            is_medical_or_vet = classification.evidence_reason in (
                "medical_context", "medical_body_symptom", "veterinary_context"
            )
            embedding_local_override = (
                route == "LOCAL"
                and (not ephemeral or is_medical_or_vet)
                and (
                    raw_signals.get("source_request")
                    or "EVIDENCE" in candidate_routes
                    or classification.evidence_mode == "required"
                )
            )

            if route == "LOCAL" and not embedding_local_override:
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
                )
            elif embedding_local_override:
                # Intent classifier overrode embedding LOCAL → AUGMENTED/EVIDENCE
                from router_py import provider_resolver
                provider = provider_resolver.resolve_provider(classification)
                usage_class = provider_usage_class_for(provider)

                # Preserve the original evidence_reason from classification
                # (e.g., medical_context, medical_body_symptom) instead of
                # hardcoding source_request.
                _evidence_reason = classification.evidence_reason or "source_request"
                _evidence_mode = classification.evidence_mode or "required"

                # Medical/veterinary queries route to EVIDENCE (strict trusted sources)
                if _evidence_reason in ("medical_context", "medical_body_symptom", "veterinary_context"):
                    route = "EVIDENCE"
                    provider = "trusted"
                    usage_class = "local"
                    policy_reason = f"router_evidence_{_evidence_reason}"
                elif "NEWS" in candidate_routes:
                    # Intent classifier detected a news query
                    if _is_synthesis_request(query):
                        # Synthesis requests (opinion, probability, assessment) need
                        # AUGMENTED so OpenAI/Kimi can analyze headlines + context
                        route = "AUGMENTED"
                        provider = "openai"
                        usage_class = "paid"
                        policy_reason = "router_news_synthesis"
                        _evidence_reason = "news_synthesis"
                    else:
                        # Pure news request — raw headlines
                        route = "NEWS"
                        provider = "news"
                        usage_class = "local"
                        policy_reason = "router_news_override"
                else:
                    route = "AUGMENTED"
                    policy_reason = "router_source_request_override"

                decision = RoutingDecision(
                    route=route,
                    mode="AUTO",
                    intent_family=intent_family,
                    confidence=confidence,
                    provider=provider,
                    provider_usage_class=usage_class,
                    evidence_mode=_evidence_mode,
                    evidence_reason=_evidence_reason,
                    requires_evidence=True,
                    policy_reason=policy_reason,
                    ephemeral=ephemeral,
                )
            elif route == "NEWS":
                # Synthesis requests (opinion, probability, assessment) on news topics
                # need AUGMENTED so OpenAI/Kimi can analyze headlines + context
                if _is_synthesis_request(query):
                    from router_py import provider_resolver
                    provider = provider_resolver.resolve_provider(classification)
                    usage_class = provider_usage_class_for(provider)
                    decision = RoutingDecision(
                        route="AUGMENTED",
                        mode="AUTO",
                        intent_family=intent_family,
                        confidence=confidence,
                        provider=provider,
                        provider_usage_class=usage_class,
                        evidence_mode="required",
                        evidence_reason="news_synthesis",
                        requires_evidence=True,
                        policy_reason="router_news_synthesis",
                        ephemeral=True,
                    )
                else:
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
                )
            else:  # AUGMENTED or EVIDENCE
                from router_py import provider_resolver
                provider = provider_resolver.resolve_provider(classification)
                usage_class = provider_usage_class_for(provider)

                # Medical and veterinary queries route to EVIDENCE (strict trusted sources)
                # instead of AUGMENTED (general knowledge sources)
                if evidence_reason in ("medical_context", "medical_body_symptom", "veterinary_context"):
                    route = "EVIDENCE"
                    provider = "trusted"
                    usage_class = "local"
                    policy_reason = f"router_evidence_{evidence_reason}"
                else:
                    route = "AUGMENTED"
                    policy_reason = f"router_evidence_{evidence_reason}" if evidence_reason else "router_augmented"

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
                )

            # Cheap legacy audit — not used for routing, only for diagnostics
            legacy_audit = _select_route_legacy(classification, policy, forced_mode)

            _log_decision(
                query,
                decision,
                embedding_route=embedding_route,
                guards_fired=guards_fired,
                top_k_neighbours=top_k_neighbours,
                legacy_route_audit=legacy_audit.route,
                memory_gate_override=memory_gate_override or "",
            )
            return decision
        except Exception:
            # Router failed — fall back to LOCAL
            pass

    # Safe fallback
    decision = _make_local_decision(classification, query=query)
    _log_decision(query or "", decision, embedding_route="FALLBACK_LOCAL", guards_fired=["router_failure"])
    return decision


def _is_news_query_typos(query: str) -> bool:
    """Detect news queries with heavy typos that the classifier misses.

    Catches queries like "wats teh latest newz abot teh war".
    """
    if not query:
        return False
    q = query.lower()
    news_typos = ["newz", "nooz", "nuwz", "hedline", "hedlines", "hedlinez"]
    has_news_typo = any(t in q for t in news_typos)
    news_context = ["latest", "current", "breaking", "update", "updates", "today", "now"]
    has_news_context = any(c in q for c in news_context)
    wat_pattern = any(p in q for p in ["wats ", "wat ", "wut ", "whats "])
    return has_news_typo or (wat_pattern and has_news_context)


def _is_capability_query(query: str) -> bool:
    """Detect meta-questions about Lucy's own capabilities/providers.

    These should route to AUGMENTED so the system can answer accurately
    about its own architecture instead of the local model hallucinating.
    Examples:
        "Do you have any fallback such as OpenAI or Kimi?"
        "Can you search the web?"
        "What providers do you use?"
    """
    if not query:
        return False
    q = query.lower().strip()

    # Fallback / provider questions
    if "fallback" in q and any(p in q for p in ["openai", "kimi", "wikipedia", "provider", "providers"]):
        return True
    if "back up" in q and any(p in q for p in ["openai", "kimi", "wikipedia", "provider"]):
        return True

    # Internet / web access questions
    if any(p in q for p in ["do you have", "can you use", "do you use", "are you using", "are you connected"]):
        if any(t in q for t in ["internet", "online", "offline", "web", "search", "browse", "google", "bing"]):
            return True

    # Provider / backend / model questions
    if any(p in q for p in ["what providers", "what backends", "what engines", "what models", "what llm", "what ai"]):
        return True
    if "what" in q and any(p in q for p in ["provider", "backend", "engine", "model", "llm"]):
        return True

    # Architecture / system questions
    if any(p in q for p in ["how do you work", "what is your architecture", "how are you built", "what system are you", "what is your stack"]):
        return True

    return False


def _is_synthesis_request(query: str) -> bool:
    """Detect queries asking for analysis, opinion, probability, or assessment.

    These should route to AUGMENTED (not NEWS) so that OpenAI/Kimi can
    synthesize an answer from live headlines + their own knowledge.
    Examples:
        "What do you think the probability is of renewed military action..."
        "How likely is a ceasefire?"
        "Give me your assessment of the situation in Gaza."
    """
    if not query:
        return False
    q = query.lower()
    synthesis_patterns = [
        r"\bwhat do you think\b",
        r"\bprobability\b",
        r"\blikelihood\b",
        r"\bchance\b",
        r"\bodds\b",
        r"\bassessment\b",
        r"\banalysis\b",
        r"\bevaluate\b",
        r"\bopinion\b",
        r"\bpredict\b",
        r"\bforecast\b",
        r"\boutlook\b",
        r"\bhow likely\b",
        r"\bgive me your\b",
        r"\bwhat is your\b",
    ]
    return any(re.search(p, q) for p in synthesis_patterns)


def _is_creative_writing(query: str) -> bool:
    """Detect creative writing queries that should always route LOCAL.

    Prevents evidence mode from overriding creative intent.
    E.g., 'Write a story about a hospital' → LOCAL (not AUGMENTED).
    """
    if not query:
        return False
    q = query.lower().strip()
    creative_patterns = [
        r'^(write|compose|craft|create|draft| pen)( me| us| a| an| the|\s+)?\s+(story|poem|essay|novel|narrative|tale|fiction|screenplay|script|song|lyric|rap|haiku|limerick|sonnet|ballad|epic|fable|myth|legend|fanfic|fan fiction|novella|short story)',
        r'^(tell me|read me|share)( a| an| the|\s+)?\s+(story|poem|tale|joke|riddle|fable|myth|legend)',
        r'^(write|compose|craft|create)( me| us)?\s+(a|an|the|\d+)\s+\w+\s+(story|poem|essay|novel|tale)',
        r'^(write|compose|craft|create)( me| us)?\s+(a|an|the|\d+)[\s\-]*\w*[\s\-]*(word|words)[\s\-]*\w*\s+(story|poem|essay|novel|narrative|tale)',
        r'^(write|compose|craft|create)( me| us)?\s+(a|an|the|\d+)[\s\-]*\w*[\s\-]*(word|words)\s+about',
    ]
    return any(re.search(p, q) for p in creative_patterns)


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


_EPHEMERAL_KEYWORDS = [
    "weather", "forecast", "temperature", "rain", "snow", "sunny",
    "cloudy", "windy", "storm", "humidity", "precipitation",
    "stock price", "bitcoin price", "crypto price", "current price",
    "price of", "trading at", "market cap", "market price", "markets",
    "exchange rate", "currency rate", "forex",
    "score", "who won", "game result", "match result", "final score",
    "live score", "half time", "full time", "overtime",
    "traffic", "delay", "road closure", "accident on", "congestion",
    "flight status", "departure", "arrival", "gate", "boarding",
    "election results", "vote count", "polls closed", "live updates",
]


def _is_ephemeral(query: str) -> bool:
    """Check if a query is ephemeral (changes hour-to-hour)."""
    q_lower = query.lower()
    return any(kw in q_lower for kw in _EPHEMERAL_KEYWORDS)


# ---------------------------------------------------------------------------
# Memory-aware routing gate
# ---------------------------------------------------------------------------

# Patterns that indicate the query references prior conversation context
_MEMORY_FOLLOWUP_RE = re.compile(
    r"\b(him|her|it|that|this|they|them|their|those|the same|such|so|thus|there|then|"
    r"earlier|previous|before|above|mentioned|discussed|agreed|decided|said|stated)\b",
    re.IGNORECASE,
)

_MEMORY_EXPLICIT_RECALL_RE = re.compile(
    r"\b(what did I say|what was my|what is my|remind me|do you remember|"
    r"did I tell you|what did we discuss|what did I ask|what did you say|"
    r"repeat that|say that again|what about that|how about that|"
    r"tell me more|elaborate|continue|go on|expand on|follow up|more details|more info)\b",
    re.IGNORECASE,
)

# Live-data keywords that should NOT be overridden even with follow-up markers
_LIVE_DATA_KEYWORDS = [
    "weather", "forecast", "temperature", "rain", "snow", "sunny", "cloudy", "windy",
    "news", "headlines", "latest news", "breaking",
    "time is it", "time in", "current time", "what time",
    "stock", "price", "bitcoin", "crypto", "trading", "market",
]


def _memory_routing_gate(query: str, embedding_route: str, session_id: str = "default") -> str | None:
    """
    Lightweight memory-aware routing gate.

    Returns "LOCAL" if memory should take precedence over a live-data route,
    or None to keep the embedding router's decision.

    Rules:
    1. Memory must be enabled (LUCY_SESSION_MEMORY == "1").
    2. Query must look like it needs prior context (pronouns, follow-ups, explicit recall).
    3. There must be recent conversation turns in SQLite.
    4. Only overrides live-data routes (WEATHER, NEWS, TIME, STOCKS, AUGMENTED).
    5. If query contains live-data keywords alongside follow-up markers, preserve embedding decision.
    """
    # Fast reject — memory disabled
    if os.environ.get("LUCY_SESSION_MEMORY", "0") != "1":
        return None

    # Fast reject — kill switch
    if os.environ.get("LUCY_MEMORY_GATE", "1") == "0":
        return None

    # Fast reject — already LOCAL (memory will be used in execution anyway)
    if embedding_route == "LOCAL":
        return None

    # Fast reject — not a follow-up or recall query
    q = query.strip()
    if not q:
        return None

    has_followup = bool(_MEMORY_FOLLOWUP_RE.search(q) or _MEMORY_EXPLICIT_RECALL_RE.search(q))
    if not has_followup:
        return None

    # Live-data guard: if query contains live-data keywords AND follow-up markers,
    # preserve the embedding router's decision (e.g. "What about the weather?")
    q_lower = q.lower()
    has_live_data = any(kw in q_lower for kw in _LIVE_DATA_KEYWORDS)
    if has_live_data:
        return None

    # Lightweight memory check: fetch recent turns from SQLite
    try:
        from memory.memory_service import get_recent_turns
        turns = get_recent_turns(session_id=session_id, limit=2)
        if not turns:
            return None
    except Exception:
        # SQLite not available or empty — fall back to legacy text file check
        try:
            runtime_dir = Path(
                os.environ.get(
                    "LUCY_RUNTIME_NAMESPACE_ROOT",
                    Path.home() / ".codex-api-home/lucy/runtime-v8",
                )
            )
            mem_file = runtime_dir / "state" / "chat_session_memory.txt"
            if not mem_file.exists():
                return None
            content = mem_file.read_text(encoding="utf-8").strip()
            if not content:
                return None
        except Exception:
            return None

    # All conditions met — override to LOCAL
    return "LOCAL"


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
        ephemeral=_is_ephemeral(query),
    )



def _make_augmented_decision(
    classification: ClassificationResult,
    prefer_paid: bool = False,
    query: str = "",
) -> RoutingDecision:
    """Create an augmented or evidence routing decision."""
    from router_py import provider_resolver

    # Medical and veterinary queries route to EVIDENCE (strict trusted sources)
    if classification.evidence_reason in ("medical_context", "medical_body_symptom", "veterinary_context"):
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
            ephemeral=_is_ephemeral(query),
        )

    provider = provider_resolver.resolve_provider(
        classification, prefer_paid=prefer_paid
    )

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
        ephemeral=_is_ephemeral(query),
    )


def _make_local_with_fallback(classification: ClassificationResult, query: str = "") -> RoutingDecision:
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
        ephemeral=_is_ephemeral(query),
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
        decision = select_route(classification, policy=args.policy, query=args.query)

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
