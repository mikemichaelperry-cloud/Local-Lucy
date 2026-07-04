"""Automatic local-model selection for Local Lucy.

The selector chooses the best Ollama model tag for a LOCAL route based on the
user query, routing decision, and (optionally) the active persona.  It lets
Lucy stop forcing a single default model for every query and instead match the
model to the task.
"""

from __future__ import annotations

import logging
import re
import subprocess
from functools import lru_cache
from typing import Any

from router_py.request_types import RoutingDecision

logger = logging.getLogger(__name__)

# Base capability buckets.  Persona variants are resolved at runtime.
_CAPABILITY_DEFAULTS: dict[str, str] = {
    "general": "local-lucy-llama31",
    "fast": "local-lucy-fast",
    "memory": "local-lucy-memory",
    "reasoning": "local-lucy-stable",
    # Use the installed 30B parameter model for deep-thought queries.
    "deep_thought": "qwen3:30b",
    "coding": "local-lucy-qwen3",
    "creative": "local-lucy-mistral",
}

# Query-pattern heuristics.  Order matters: more specific patterns first.
_DEEP_THOUGHT_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(deep\s+(analysis|dive|investigation|examination|exploration)|"
        r"comprehensive\s+(analysis|review|explanation|overview)|"
        r"exhaustive\s+(analysis|treatment|review)|"
        r"thorough\s+(analysis|examination|investigation)|"
        r"philosophical\s+(analysis|inquiry|question|argument)|"
        r"complex\s+multi[- ]step|advanced\s+reasoning|"
        r"compare\s+and\s+contrast\s+(in\s+depth|deeply|thoroughly)|"
        r"synthesize\s+(the\s+literature|multiple\s+sources|conflicting\s+(views|perspectives))|"
        r"weight\s+the\s+(evidence|tradeoffs|arguments)\s+carefully|"
        r"what\s+are\s+the\s+deeper\s+(implications|foundations|assumptions))\b",
    )
)

_REASONING_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(explain\s+your\s+reasoning|step[- ]by[- ]step|prove|deduce|infer|"
        r"logical\s+(consequence|implication)|critical\s+thinking|analyse|analyze\s+in\s+detail|"
        r"evaluate\s+(the\s+argument|this\s+claim|the\s+evidence))\b",
        r"\b(why\s+does|why\s+is|why\s+would|how\s+do\s+you\s+know|what\s+if|"
        r"counterargument|fallacy|syllogism)\b",
    )
)

_CODING_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(write|generate|debug|fix|refactor|review)\s+(a\s+)?(python|javascript|bash|shell|"
        r"rust|go|c\+\+|java|rust|sql|regex|code|script|function)\b",
        r"\b(python|javascript|bash|shell|rust|go|c\+\+|java|sql)\s+(code|script|function|bug|error)\b",
        r"\bcode\s+(example|snippet|function|script)\b",
    )
)

_MATH_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"[\d\s]+[\+\-*/^=]+[\d\s]+",
        r"\b(calculate|solve|equation|integral|derivative|algebra|geometry|"
        r"statistics|probability|sum\s+of|product\s+of)\b",
    )
)

_MEMORY_PATTERNS = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(what\s+did\s+(i|we)\s+(say|mention|discuss|talk|ask)|"
        r"what\s+was\s+(i|we)\s+(saying|talking|discussing)|"
        r"remind\s+me|do\s+you\s+remember|what\s+is\s+my\s+|"
        r"my\s+(name|age|birthday|address|preference|favorite))\b",
    )
)

_SHORT_QUERY_RE = re.compile(r"^[^.!?]{0,60}$")


def _pattern_matches(query: str, patterns: tuple[re.Pattern, ...]) -> bool:
    return any(p.search(query) for p in patterns)


def _query_bucket(query: str) -> str:
    """Classify a LOCAL query into a capability bucket."""
    if not query:
        return "general"
    q = query.strip()

    if _pattern_matches(q, _MEMORY_PATTERNS):
        return "memory"

    if _pattern_matches(q, _DEEP_THOUGHT_PATTERNS):
        return "deep_thought"

    if _pattern_matches(q, _CODING_PATTERNS):
        return "coding"

    if _pattern_matches(q, _MATH_PATTERNS) or _pattern_matches(q, _REASONING_PATTERNS):
        return "reasoning"

    # Very short utterances benefit from the fastest model.
    if _SHORT_QUERY_RE.match(q):
        return "fast"

    return "general"


def _resolve_installed_tag(candidate: str, installed: set[str]) -> str | None:
    """Return the concrete installed tag for a candidate base name.

    Ollama tags often include a digest suffix such as ``:latest``.  This lets
    callers specify a base model name (e.g. ``local-lucy-llama31``) and still
    match the installed ``local-lucy-llama31:latest`` tag.
    """
    if not candidate:
        return None
    if candidate in installed:
        return candidate
    latest = f"{candidate}:latest"
    if latest in installed:
        return latest
    matches = [tag for tag in installed if tag == candidate or tag.startswith(f"{candidate}:")]
    if matches:
        # Prefer :latest, otherwise the first matching tag.
        for tag in matches:
            if tag.endswith(":latest"):
                return tag
        return sorted(matches)[0]
    return None


def _resolve_persona_model(base_model: str, persona: str, available: set[str]) -> str:
    """Prefer a persona-tuned variant when one exists and is installed."""
    if not persona:
        return base_model
    persona = persona.strip().lower()
    candidate = f"{base_model}-{persona}"
    resolved = _resolve_installed_tag(candidate, available)
    if resolved:
        return resolved
    # Some older naming used the persona as a suffix on the root tag.
    resolved = _resolve_installed_tag(f"{base_model}-{persona}", available)
    if resolved:
        return resolved
    return base_model


@lru_cache(maxsize=1)
def _ollama_installed_models() -> frozenset[str]:
    """Return installed Ollama model tags, or an empty set if ollama is unreachable."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode != 0:
            logger.warning("ollama list failed: %s", result.stderr.strip())
            return frozenset()
        tags: set[str] = set()
        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if parts:
                tags.add(parts[0])
        return frozenset(tags)
    except Exception as exc:  # pragma: no cover - ollama may not be installed in CI
        logger.warning("Could not list Ollama models: %s", exc)
        return frozenset()


def _available_models(preferred: list[str] | None = None) -> set[str]:
    """Return the model universe the selector may choose from.

    If the caller passes an explicit ``preferred`` list, it is trusted as the
    allowed universe (useful for tests and for callers that already verified
    availability).  Otherwise the set of installed Ollama models is used, with
    a conservative static fallback when Ollama is unreachable.
    """
    if preferred is not None:
        return set(preferred)
    installed = _ollama_installed_models()
    if installed:
        return set(installed)
    # Fallback static list for environments where ollama is not reachable.
    return {
        "local-lucy-llama31",
        "local-lucy",
        "local-lucy-fast",
        "local-lucy-stable",
        "local-lucy-qwen3",
        "local-lucy-mistral",
        "local-lucy-memory",
    }


def select_local_model(
    query: str,
    route: RoutingDecision | None = None,
    context: dict[str, Any] | None = None,
    available: list[str] | None = None,
) -> str:
    """Pick the best local Ollama model tag for the current query.

    Args:
        query: The user's question.
        route: The routing decision (used for intent_family when present).
        context: Execution context; ``persona`` key selects a persona variant.
        available: Optional list of allowed model tags. Defaults to installed models.

    Returns:
        An Ollama model tag such as ``local-lucy-llama31``.
    """
    ctx = context or {}
    persona = str(ctx.get("persona") or ctx.get("active_persona") or "").strip()
    installed = _available_models(available)

    # If the user or HMI has already pinned a model, respect it unless we are
    # explicitly in fully-autonomous mode.  This preserves backward compatibility
    # while the toggle-removal work is in progress.
    pinned = ctx.get("LUCY_LOCAL_MODEL") or ctx.get("local_model")
    autonomous = ctx.get("LUCY_AUTONOMOUS_MODEL_SELECTION", "false").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    if pinned and not autonomous:
        resolved = _resolve_installed_tag(str(pinned), installed)
        if not installed or resolved:
            return resolved or str(pinned)

    # Use the route's intent family to refine the bucket.
    bucket = _query_bucket(query)
    intent_family = getattr(route, "intent_family", None) or ctx.get("intent_family", "")
    if intent_family in ("synthesis_explanation", "self_review") and bucket == "general":
        bucket = "reasoning"
    elif intent_family == "local_answer" and bucket == "general":
        bucket = "general"  # how-to / coding already caught above

    base_model = _CAPABILITY_DEFAULTS.get(bucket, _CAPABILITY_DEFAULTS["general"])

    # Ensure the chosen base model is installed; fall back through capability
    # buckets until we find one that is available.  Resolve to the concrete
    # installed tag (e.g. local-lucy-llama31:latest) so Ollama does not have to
    # guess the digest and so model switching is explicit.
    fallback_order = [bucket] + [b for b in _CAPABILITY_DEFAULTS if b != bucket]
    chosen: str | None = None
    for fb in fallback_order:
        candidate = _CAPABILITY_DEFAULTS[fb]
        resolved = _resolve_installed_tag(candidate, installed)
        if not installed or resolved:
            chosen = resolved or candidate
            break
    if chosen is None:
        chosen = next(iter(installed)) if installed else _CAPABILITY_DEFAULTS["general"]

    if persona:
        chosen = _resolve_persona_model(chosen, persona, installed)

    logger.debug(
        "Model selection: query_bucket=%s intent_family=%s persona=%s -> %s",
        bucket,
        intent_family,
        persona or "none",
        chosen,
    )
    return chosen


# ---------------------------------------------------------------------------
# Phase 3: automatic model-selection policy (shadow mode)
# ---------------------------------------------------------------------------

# Routes that are always answered by the factual/default model.
_FACTUAL_ROUTES: frozenset[str] = frozenset({"NEWS", "TIME", "WEATHER", "FINANCE", "EVIDENCE"})

# Query-only signals for factual/current information.
_CURRENT_INFO_RE = re.compile(
    r"\b(current|today|tonight|latest|now|news|weather|forecast|"
    r"stock price|share price|price of|market|bitcoin|crypto|exchange rate|"
    r"time in|what time|what is the capital|who is the president|"
    r"who won|recent events|this week|this month)\b",
    re.IGNORECASE,
)

# Query-only signals for creative/short/low-latency requests.
_CREATIVE_RE = re.compile(
    r"\b(write|compose|tell me|create|make up|draft)\b.*?"
    r"\b(story|poem|joke|song|script|essay|fiction|horror|fantasy|sci-fi|"
    r"romance|thriller|mystery|dialogue|scene|chapter|novel)\b",
    re.IGNORECASE,
)

# Latency budgets by base model name (milliseconds). These are planning
# estimates, not hard timeouts.
_LATENCY_BUDGETS_MS: dict[str, int] = {
    "local-lucy-fast": 3000,
    "local-lucy": 8000,
    "local-lucy-qwen3": 8000,
    "local-lucy-llama31": 5000,
    "local-lucy-stable": 8000,
    "local-lucy-memory": 5000,
    "local-lucy-mistral": 8000,
    "qwen3:30b": 25000,
}


def is_auto_model(model_name: str | None) -> bool:
    """Return True if *model_name* represents the Auto option.

    Accepts backend values like ``"auto"`` and display labels like
    ``"Auto (Lucy chooses per query)"``.
    """
    if not model_name:
        return True
    return str(model_name).strip().lower().startswith("auto")


def _base_name(model_tag: str) -> str:
    """Strip an optional ``:latest`` or ``:<digest>`` suffix for budget lookup."""
    if ":" in model_tag:
        return model_tag.split(":", 1)[0]
    return model_tag


def _latency_budget_for(model_tag: str) -> int:
    """Return the planning latency budget for a concrete model tag."""
    return _LATENCY_BUDGETS_MS.get(_base_name(model_tag), 8000)


def _is_factual_current_query(query: str) -> bool:
    """Detect queries that ask for factual or current information."""
    return bool(_CURRENT_INFO_RE.search(query or ""))


def _is_creative_query(query: str) -> bool:
    """Detect creative-writing or light creative requests."""
    return bool(_CREATIVE_RE.search(query or ""))


def _confidence_for_bucket(
    bucket: str,
    route_name: str,
    intent_family: str,
    query: str,
) -> float:
    """Return a heuristic confidence for the recommendation."""
    if route_name in _FACTUAL_ROUTES:
        return 0.95
    if route_name == "AUGMENTED" and intent_family == "factual":
        return 0.92
    if _is_factual_current_query(query):
        return 0.88
    if bucket in ("memory", "coding", "deep_thought"):
        return 0.90
    if bucket == "reasoning":
        return 0.85
    if bucket == "fast" or _is_creative_query(query):
        return 0.80
    return 0.75


def _competing_model(recommended: str, installed: set[str]) -> str:
    """Pick a sensible competing model for shadow A/B comparisons."""
    base = _base_name(recommended)
    candidates: list[str] = []
    if base == "local-lucy-llama31":
        candidates = ["local-lucy-qwen3", "local-lucy-stable", "local-lucy-fast"]
    elif base in ("local-lucy-qwen3", "local-lucy"):
        candidates = ["local-lucy-llama31", "local-lucy-fast"]
    elif base == "local-lucy-fast":
        candidates = ["local-lucy", "local-lucy-llama31"]
    elif base == "local-lucy-memory":
        candidates = ["local-lucy-llama31"]
    elif base == "qwen3:30b":
        candidates = ["local-lucy-stable", "local-lucy-llama31"]
    elif base == "local-lucy-stable":
        candidates = ["qwen3:30b", "local-lucy-llama31"]
    else:
        candidates = ["local-lucy-llama31", "local-lucy-fast"]

    for cand in candidates:
        resolved = _resolve_installed_tag(cand, installed)
        if resolved:
            return resolved
    # Final fallback to the first installed model, or Llama 3.1.
    return next(iter(installed), "local-lucy-llama31")


def select_model(
    query: str,
    route: RoutingDecision | str | None = None,
    intent_family: str | None = None,
    manual_model: str | None = None,
    available: list[str] | None = None,
) -> dict[str, Any]:
    """Return a policy-driven model recommendation with metadata.

    The recommendation is independent of any manual HMI selection so it can be
    used in shadow mode.

    Args:
        query: The user's question.
        route: Optional routing decision or route name.
        intent_family: Optional intent family (e.g. ``"factual"``).
        manual_model: The manually-selected model, if any (recorded only).
        available: Optional universe of installed model tags for tests.

    Returns:
        Dict with keys ``recommended``, ``reason``, ``competing``,
        ``confidence``, ``latency_budget_ms``.
    """
    installed = _available_models(available)
    bucket = _query_bucket(query)

    route_name = ""
    if isinstance(route, RoutingDecision):
        route_name = route.route
        intent_family = route.intent_family or intent_family
    elif isinstance(route, str):
        route_name = route

    if intent_family in ("synthesis_explanation", "self_review") and bucket == "general":
        bucket = "reasoning"
    elif intent_family == "local_answer" and bucket == "general":
        bucket = "general"

    recommended: str
    reason: str

    if route_name in _FACTUAL_ROUTES:
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = f"{route_name} route requires factual accuracy; defaulting to Llama 3.1"
    elif route_name == "AUGMENTED" and intent_family == "factual":
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = "AUGMENTED factual query; using Llama 3.1 for accuracy"
    elif _is_factual_current_query(query):
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = "Query asks for factual/current information; using Llama 3.1"
    elif bucket == "memory":
        recommended = _resolve_installed_tag("local-lucy-memory", installed) or "local-lucy-memory"
        reason = "Memory/personal-fact query; using memory-tuned model"
    elif bucket == "deep_thought":
        resolved = _resolve_installed_tag("qwen3:30b", installed)
        if resolved:
            recommended = resolved
            reason = "Deep-thought pattern; using qwen3:30b"
        else:
            recommended = (
                _resolve_installed_tag("local-lucy-stable", installed) or "local-lucy-stable"
            )
            reason = "Deep-thought pattern; qwen3:30b unavailable, using stable model"
    elif bucket in ("coding", "reasoning"):
        resolved = _resolve_installed_tag("local-lucy-qwen3", installed)
        if resolved:
            recommended = resolved
            reason = f"{bucket} query; qwen3:14b installed"
        else:
            recommended = (
                _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
            )
            reason = f"{bucket} query; qwen3:14b not installed, using Llama 3.1"
    elif bucket == "fast" or intent_family == "creative" or _is_creative_query(query):
        resolved = _resolve_installed_tag("local-lucy", installed)
        if resolved:
            recommended = resolved
            reason = "Creative/short-chat/low-latency query; using qwen3:14b with shorter budget"
        else:
            recommended = _resolve_installed_tag("local-lucy-fast", installed) or "local-lucy-fast"
            reason = "Creative/short-chat/low-latency query; using fast model"
    else:
        recommended = (
            _resolve_installed_tag("local-lucy-llama31", installed) or "local-lucy-llama31"
        )
        reason = "General query; defaulting to Llama 3.1"

    if manual_model and not is_auto_model(manual_model):
        reason = f"{reason} (manual override selected: {manual_model})"

    competing = _competing_model(recommended, installed)
    confidence = _confidence_for_bucket(bucket, route_name, intent_family or "", query)
    latency_budget_ms = _latency_budget_for(recommended)

    logger.debug(
        "Policy model selection: bucket=%s route=%s recommended=%s competing=%s",
        bucket,
        route_name,
        recommended,
        competing,
    )
    return {
        "recommended": recommended,
        "reason": reason,
        "competing": competing,
        "confidence": confidence,
        "latency_budget_ms": latency_budget_ms,
    }


def generate_ab_pair(
    query: str,
    route: RoutingDecision | str | None = None,
    available: list[str] | None = None,
) -> tuple[str, str]:
    """Return (model_a, model_b) for a blind A/B comparison.

    *model_a* is the recommended model; *model_b* is the competing model.
    """
    recommendation = select_model(query, route=route, available=available)
    return recommendation["recommended"], recommendation["competing"]
