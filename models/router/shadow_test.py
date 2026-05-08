#!/usr/bin/env python3
"""Shadow test: Run ModernBERT alongside legacy router, log divergence.

Usage:
    python shadow_test.py --model checkpoints/best --queries "queries.jsonl"
"""

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))

from classify import ClassificationResult, select_route
from policy import requires_evidence_mode
from model import ModernBertRouter


def legacy_classify(query: str) -> ClassificationResult:
    """Simulate legacy classifier output for a query."""
    requires, reason = requires_evidence_mode(query)
    q = query.lower()
    
    # Simple heuristic matching
    if any(k in q for k in ["news", "headlines", "breaking"]):
        family, needs_web, cat = "current_evidence", True, "news_world"
    elif "time" in q or "current time" in q:
        family, needs_web, cat = "current_evidence", True, "time_query"
    elif any(k in q for k in ["who was", "what is", "explain", "compare", "caused"]):
        family, needs_web, cat = "background_overview", True, "informational"
    elif any(k in q for k in ["how to", "how do i", "recipe", "bake", "debug"]):
        family, needs_web, cat = "local_answer", False, "procedural"
    elif any(k in q for k in ["symptom", "treatment", "medication", "stock price", "bitcoin", "legal", "supreme court", "source", "peer-reviewed"]):
        family, needs_web, cat = "current_evidence", True, "medical" if any(m in q for m in ["symptom", "treatment", "medication"]) else "informational"
    else:
        family, needs_web, cat = "local_answer", False, "general"
    
    return ClassificationResult(
        intent=family, intent_family=family, intent_class=family,
        category=cat, confidence=0.85, needs_web=needs_web,
        needs_memory=False, needs_synthesis=False, clarify_required=False,
        evidence_mode="required" if requires else "",
        evidence_reason=reason, augmentation_recommended=needs_web and not requires,
        force_local="story" in q or "poem" in q or "joke" in q,
    )


def run_shadow_test(model_path: str, queries: list[str], output_path: str | None = None):
    router = ModernBertRouter(model_path, temperature=0.5)
    
    results = []
    divergences = []
    
    print(f"{'Query':<50s} {'Legacy':<12s} {'ModernBERT':<12s} {'Agree?':<6s} {'MB Conf'}")
    print("=" * 100)
    
    for query in queries:
        # Legacy decision
        legacy_cls = legacy_classify(query)
        legacy_dec = select_route(legacy_cls, policy="fallback_only")
        legacy_route = legacy_dec.route
        
        # ModernBERT decision
        mb = router.predict(query)
        mb_route = mb["route"]
        
        agree = legacy_route == mb_route
        status = "✅" if agree else "❌"
        
        print(f"{query:<50s} {legacy_route:<12s} {mb_route:<12s} {status:<6s} {mb['confidence']:.3f}")
        
        if not agree:
            divergences.append({
                "query": query,
                "legacy": legacy_route,
                "modernbert": mb_route,
                "mb_confidence": mb["confidence"],
                "mb_intent": mb["intent_family"],
            })
        
        results.append({
            "query": query,
            "legacy_route": legacy_route,
            "modernbert_route": mb_route,
            "modernbert_intent": mb["intent_family"],
            "modernbert_confidence": mb["confidence"],
            "agree": agree,
        })
    
    print()
    agreement = sum(1 for r in results if r["agree"]) / len(results) * 100
    print(f"Agreement: {agreement:.1f}% ({len(results) - len(divergences)}/{len(results)})")
    print(f"Divergences: {len(divergences)}")
    
    if divergences:
        print("\nDivergence details:")
        for d in divergences:
            print(f"  {d['query']}: legacy={d['legacy']} vs modernbert={d['modernbert']} (conf={d['mb_confidence']:.3f}, intent={d['mb_intent']})")
    
    if output_path:
        with open(output_path, "w") as f:
            json.dump({
                "timestamp": datetime.now().isoformat(),
                "model_path": model_path,
                "agreement_rate": agreement,
                "total_queries": len(queries),
                "divergences": len(divergences),
                "results": results,
            }, f, indent=2)
        print(f"\nSaved results to {output_path}")
    
    return agreement, divergences


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="checkpoints/best", help="Model checkpoint path")
    parser.add_argument("--output", default="shadow_results.json", help="Output JSON path")
    args = parser.parse_args()
    
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
    ]
    
    run_shadow_test(args.model, test_queries, args.output)
