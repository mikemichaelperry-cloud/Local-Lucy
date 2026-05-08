#!/usr/bin/env python3
"""Shadow mode integration for embedding router.

Runs alongside the legacy router, logging both decisions for comparison.
Legacy router remains PRIMARY - this only logs, never affects routing.
"""

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from classify import ClassificationResult, select_route
from policy import requires_evidence_mode

# Import hybrid router
from hybrid_router import HybridRouter


class ShadowModeRouter:
    """Wrapper that runs embedding router in shadow mode alongside legacy."""

    def __init__(self, log_path: str = "shadow_divergences.jsonl"):
        self.log_path = Path(log_path)
        self.shadow_router = HybridRouter()
        self.divergence_count = 0
        self.total_count = 0

    def route(self, query: str, policy: str = "fallback_only") -> dict[str, Any]:
        """Route query using legacy router, log shadow prediction.

        Returns the legacy decision as primary, plus shadow metadata.
        """
        # --- LEGACY ROUTER (PRIMARY) ---
        requires_evidence, evidence_reason = requires_evidence_mode(query)
        q_lower = query.lower()

        # Build ClassificationResult for legacy router
        if any(k in q_lower for k in ["story", "poem", "novel", "compose a", "write a"]):
            family = "local_answer"
            needs_web = False
            cat = "creative"
        elif any(k in q_lower for k in ["news", "headlines", "latest news", "breaking"]):
            family = "current_evidence"
            needs_web = True
            cat = "news_world"
        elif any(k in q_lower for k in ["time is it", "current time", "what day is it", "timezone"]):
            family = "current_evidence"
            needs_web = True
            cat = "time_query"
        elif any(k in q_lower for k in ["symptom", "treatment", "medication", "dosage", "side effects", "is it safe"]):
            family = "current_evidence"
            needs_web = True
            cat = "medical"
        elif any(k in q_lower for k in ["stock price", "bitcoin", "exchange rate", "interest rate", "market cap"]):
            family = "current_evidence"
            needs_web = True
            cat = "financial"
        elif any(k in q_lower for k in ["legal to", "court ruling", "supreme court", "tenant rights", "statute"]):
            family = "current_evidence"
            needs_web = True
            cat = "legal"
        elif any(k in q_lower for k in ["how to", "how do i", "install", "debug", "what is python"]):
            family = "local_answer"
            needs_web = False
            cat = "procedural"
        elif any(k in q_lower for k in ["who was", "who is", "what is the capital", "what is the speed", "when did", "what caused"]):
            family = "background_overview"
            needs_web = True
            cat = "informational"
        elif any(k in q_lower for k in ["hello", "who are you", "good morning", "how are you", "what is your name"]):
            family = "local_answer"
            needs_web = False
            cat = "greeting"
        elif any(k in q_lower for k in ["what is 2+2", "what is 5+5", "calculate", "translate"]):
            family = "local_answer"
            needs_web = False
            cat = "math"
        else:
            family = "local_answer"
            needs_web = False
            cat = "general"

        classification = ClassificationResult(
            intent=family, intent_family=family, intent_class=family,
            category=cat, confidence=0.85, needs_web=needs_web,
            evidence_mode="required" if requires_evidence else "",
            evidence_reason=evidence_reason,
            augmentation_recommended=needs_web and not requires_evidence,
            force_local="story" in q_lower or "poem" in q_lower,
        )

        legacy_decision = select_route(classification, policy=policy)

        # --- SHADOW ROUTER (LOGGING ONLY) ---
        shadow_result = self.shadow_router.predict(query)
        self.total_count += 1

        # Log divergence
        if legacy_decision.route != shadow_result["route"]:
            self.divergence_count += 1
            log_entry = {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "query": query,
                "legacy": {
                    "route": legacy_decision.route,
                    "intent_family": classification.intent_family,
                    "evidence_mode": classification.evidence_mode,
                    "provider": legacy_decision.provider,
                    "policy_reason": legacy_decision.policy_reason,
                },
                "shadow": shadow_result,
                "divergence": True,
            }
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry) + "\n")

        agreement_rate = (self.total_count - self.divergence_count) / self.total_count * 100

        return {
            # Primary decision (legacy router)
            "route": legacy_decision.route,
            "mode": legacy_decision.mode,
            "provider": legacy_decision.provider,
            "provider_usage_class": legacy_decision.provider_usage_class,
            "intent_family": classification.intent_family,
            "confidence": classification.confidence,
            "evidence_mode": classification.evidence_mode,
            "evidence_reason": classification.evidence_reason,
            "policy_reason": legacy_decision.policy_reason,

            # Shadow metadata (for monitoring)
            "shadow": {
                "route": shadow_result["route"],
                "intent_family": shadow_result["intent_family"],
                "confidence": shadow_result["confidence"],
                "evidence_mode": shadow_result["evidence_mode"],
            },
            "shadow_metrics": {
                "total_queries": self.total_count,
                "divergences": self.divergence_count,
                "agreement_rate": round(agreement_rate, 2),
            },
        }


def demo():
    print("=" * 90)
    print("Shadow Mode Router Demo")
    print("Legacy router = PRIMARY | Embedding router = SHADOW (logging only)")
    print("=" * 90)

    router = ShadowModeRouter()

    test_queries = [
        "What are the symptoms of flu?",
        "Who was Ada Lovelace?",
        "What time is it in Tokyo?",
        "Latest news on Israel",
        "Write a story about a robot",
        "What is 2+2?",
        "How do I install Python?",
        "Breaking news about earthquake",
        "Stock price of Apple",
        "Is it legal to ride a bike on the sidewalk?",
        "Explain quantum computing",
        "Tell me a joke",
        "What is the treatment for diabetes?",
        "Current bitcoin price",
        "Latest Supreme Court ruling",
        "Who invented the telephone?",
        "What is the capital of France?",
        "How do I bake sourdough bread?",
        "Translate hello to Japanese",
        "What is CRISPR?",
    ]

    for q in test_queries:
        result = router.route(q)
        legacy = result["route"]
        shadow = result["shadow"]["route"]
        agree = "✅" if legacy == shadow else "❌"
        print(f"  {agree} {q:50s} legacy={legacy:12s} shadow={shadow:12s} (agree={result['shadow_metrics']['agreement_rate']:.0f}%)")

    print()
    print(f"Final: {result['shadow_metrics']['total_queries']} queries, "
          f"{result['shadow_metrics']['divergences']} divergences, "
          f"{result['shadow_metrics']['agreement_rate']:.1f}% agreement")

    if router.log_path.exists():
        print(f"\nDivergences logged to: {router.log_path}")
        with open(router.log_path) as f:
            divergences = [json.loads(line) for line in f if line.strip()]
        print(f"Total divergence entries: {len(divergences)}")


if __name__ == "__main__":
    demo()
