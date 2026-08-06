#!/usr/bin/env python3
"""PolicyRouter implementation."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Ensure tools package is importable when this module is loaded directly.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import ClassificationResult

from .models import PolicyDecision
from .gates import (
    gate_explicit_assistant_instruction,
    gate_explicit_capability_restriction,
    gate_personal_family,
    gate_recreational_pet,
    gate_science_fact,
    gate_medical_vet,
    gate_ambiguous_local,
    gate_stable_knowledge,
    gate_local_reasoning,
    gate_garbage_nonsense,
    gate_residence_statement,
    gate_specific_entity_fact,
    gate_finance,
    gate_restaurant_dining,
    gate_time,
    gate_weather,
    gate_news,
    gate_evidence_request,
    gate_conflict_analysis,
    gate_public_figure_age,
    gate_recipe,
    gate_travel_tourism,
    gate_factual_lookup,
    gate_current_information,
    gate_attachment,
    gate_memory_followup,
)


class PolicyRouter:
    """Runs deterministic policy gates in priority order."""

    # Priority order matters: medical/vet must beat personal/family when symptoms
    # are present; weather must beat current-information; finance must beat
    # current-information for prices.
    DEFAULT_GATES = (
        gate_personal_family,
        gate_recreational_pet,
        # Explicit assistant meta-instructions (self-model tests, diagnostic
        # exercises) must stay LOCAL before medical/vet or factual-lookup gates
        # can misroute them.
        gate_explicit_assistant_instruction,
        # Short capability-restriction messages ("do not store this", "no network")
        # are meta-instructions, not factual lookups.
        gate_explicit_capability_restriction,
        # Stable science facts (boiling point, speed of light, etc.) must run
        # before the weather gate so "temperature" does not force them outward.
        gate_science_fact,
        gate_medical_vet,
        # Garbage / noise should not be routed outward by the embedding router.
        # Run it early so symbol-only or placeholder input does not accidentally
        # match a downstream weather/news/finance keyword heuristic.
        gate_garbage_nonsense,
        # Residence / location statements must stay LOCAL before the weather gate
        # can misroute "I live in Kibbutz Magal" to WEATHER.
        gate_residence_statement,
        # Dedicated external-source gates run next so time/weather/news/finance
        # /conflict/age/current queries keep their routes and reason codes.
        # Restaurant/dining must run before time/weather so "restaurants open today"
        # is not misrouted as a time or weather query.
        gate_finance,
        gate_restaurant_dining,
        gate_time,
        gate_weather,
        gate_news,
        gate_evidence_request,
        gate_conflict_analysis,
        gate_public_figure_age,
        gate_recipe,
        gate_travel_tourism,
        gate_current_information,
        # Explicit memory follow-ups must stay LOCAL; the broad factual_lookup
        # gate would otherwise misroute "what did we discuss earlier?" to
        # AUGMENTED because the query shares few keywords with the prior topic.
        gate_memory_followup,
        # Stable knowledge / local reasoning must run before the broad
        # factual_lookup gate and before specific_entity_fact so opinion,
        # speculation, conspiracy, and timeless educational/historical concepts
        # stay LOCAL instead of being forced outward.
        gate_stable_knowledge,
        gate_local_reasoning,
        # Remaining specific named-entity factual lookups route outward for
        # verification.
        gate_specific_entity_fact,
        # Catch remaining broad factual lookups before the ambiguous-local gate
        # forces them to the local model. The factual_lookup gate carries its own
        # exclusions for local capabilities (translation, coding, math, creative,
        # opinion, DIY, stable science, history).
        gate_factual_lookup,
        gate_ambiguous_local,
        gate_attachment,
    )

    def __init__(self, gates: tuple | None = None):
        self.gates = gates if gates is not None else self.DEFAULT_GATES

    def apply(
        self,
        query: str,
        classification: ClassificationResult,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision | None:
        """Return the first matching policy decision, or None if no gate matches."""
        for gate in self.gates:
            decision = gate(query, classification, context)
            if decision is not None:
                return decision
        return None
