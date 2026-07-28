#!/usr/bin/env python3
"""
Intent classification integration - Python API for router classification.

This module is now a thin facade over classify_core. New code should import
from router_py.classify_core.* directly; this facade exists for backward
compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

# Re-export request types for callers that imported them from here
from router_py.request_types import ClassificationResult, RoutingDecision

# Public API
from router_py.classify_core.intent import classify_intent
from router_py.classify_core.router import prewarm_router
from router_py.classify_core.select import select_route

# Privates used by other production modules and tests
from router_py.classify_core.guards import (
    _is_capability_query,
    _is_clear_news_query,
    _is_conflict_analysis_query,
    _is_cooking_query,
    _is_creative_writing,
    _is_financial_ephemeral,
    _is_historical_query,
    _is_hostile_override_attempt,
    _is_language_or_translation_query,
    _is_news_query_typos,
    _is_personal_family_query,
    _is_public_figure_age_query,
    _is_synthesis_request,
    _is_technical_knowledge_query,
    _is_time_query,
    _is_weather_query,
)
from router_py.classify_core.intent import _map_to_intent_family
from router_py.classify_core.memory import _memory_routing_gate
from router_py.classify_core.select import (
    _call_llm_arbiter,
    _make_augmented_decision,
    _make_local_decision,
)

# Keep the CLI interface from the original file
if __name__ == "__main__":
    import argparse
    import json

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
