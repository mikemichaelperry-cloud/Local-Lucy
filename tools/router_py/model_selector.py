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
