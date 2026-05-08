#!/usr/bin/env python3
"""
Legacy router evaluation baseline.
Run this to measure keyword-based router accuracy before ModernBERT cutover.
"""

import sys
from pathlib import Path

# Add router_py directly to path
sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "router_py"))

from classify import ClassificationResult, select_route
from policy import requires_evidence_mode

# Test cases: (query, expected_route, description)
TEST_CASES = [
    # === LOCAL answers (no web needed) ===
    ("What is 2+2?", "LOCAL", "math"),
    ("Tell me a joke", "LOCAL", "entertainment"),
    ("Write a short story about a robot", "LOCAL", "creative writing"),
    ("How do I bake sourdough bread?", "LOCAL", "procedural how-to"),
    ("Explain Python list comprehensions", "LOCAL", "technical explanation"),
    ("What is the meaning of life?", "LOCAL", "philosophy"),
    ("Translate 'hello' to French", "LOCAL", "translation"),
    ("Help me debug this code", "LOCAL", "coding help"),
    
    # === AUGMENTED (needs web, evidence not required) ===
    ("Who was Ada Lovelace?", "AUGMENTED", "biography"),
    ("What is quantum computing?", "AUGMENTED", "technical overview"),
    ("Explain the theory of relativity", "AUGMENTED", "scientific concept"),
    ("What caused the fall of Rome?", "AUGMENTED", "historical analysis"),
    ("Compare Python and JavaScript", "AUGMENTED", "comparison"),
    
    # === EVIDENCE REQUIRED -> AUGMENTED ===
    ("What are the symptoms of flu?", "AUGMENTED", "medical symptoms"),
    ("What is the treatment for diabetes?", "AUGMENTED", "medical treatment"),
    ("Can I take aspirin with ibuprofen?", "AUGMENTED", "drug interaction"),
    ("Is tadalafil safe with grapefruit?", "AUGMENTED", "medical interaction"),
    ("Breaking news about Israel", "AUGMENTED", "breaking news"),
    ("Latest updates on the war", "AUGMENTED", "conflict live"),
    ("What is the current situation in Gaza?", "AUGMENTED", "geopolitics"),
    ("Stock price of Apple", "AUGMENTED", "financial data"),
    ("Current bitcoin price", "AUGMENTED", "crypto price"),
    ("Is it legal to park here?", "AUGMENTED", "legal query"),
    ("Latest Supreme Court ruling", "AUGMENTED", "legal ruling"),
    ("Source for climate change data", "AUGMENTED", "source request"),
    ("Peer-reviewed studies on sleep", "AUGMENTED", "academic source"),
    
    # === NEWS route ===
    ("What is the latest world news?", "NEWS", "news world"),
    ("News from Australia today", "NEWS", "news australia"),
    ("Israel news headlines", "NEWS", "news israel"),
    
    # === TIME route ===
    ("What time is it in Tokyo?", "TIME", "time query"),
    ("Current time in London", "TIME", "time query"),
]


def make_classification(query: str) -> ClassificationResult:
    """Create a synthetic classification for testing."""
    requires, reason = requires_evidence_mode(query)
    
    # Simple heuristic for intent family
    family = "local_answer"
    needs_web = False
    category = "general"
    
    q = query.lower()
    
    if any(k in q for k in ["news", "headlines", "breaking"]):
        family = "current_evidence"
        needs_web = True
        category = "news_world"
    elif "time" in q or "current time" in q:
        family = "current_evidence"
        needs_web = True
        category = "time_query"
    elif any(k in q for k in ["who was", "what is", "explain", "compare", "caused"]):
        family = "background_overview"
        needs_web = True
        category = "informational"
    elif any(k in q for k in ["how to", "how do i", "recipe", "bake", "debug"]):
        family = "local_answer"
        needs_web = False
        category = "procedural"
    elif any(k in q for k in ["symptom", "treatment", "medication", "stock price", "bitcoin", "legal", "supreme court", "source", "peer-reviewed"]):
        family = "current_evidence"
        needs_web = True
        category = "medical" if any(m in q for m in ["symptom", "treatment", "medication"]) else "informational"
    
    return ClassificationResult(
        intent=family,
        intent_family=family,
        intent_class=family,
        category=category,
        confidence=0.85,
        needs_web=needs_web,
        needs_memory=False,
        needs_synthesis=False,
        clarify_required=False,
        evidence_mode="required" if requires else "",
        evidence_reason=reason,
        augmentation_recommended=needs_web and not requires,
        force_local="story" in q or "poem" in q or "joke" in q,
    )


def evaluate():
    print("=" * 60)
    print("Legacy Router Evaluation Baseline")
    print("=" * 60)
    
    correct = 0
    total = len(TEST_CASES)
    failures = []
    
    for query, expected, desc in TEST_CASES:
        classification = make_classification(query)
        decision = select_route(classification, policy="fallback_only")
        actual = decision.route
        
        status = "PASS" if actual == expected else "FAIL"
        if actual == expected:
            correct += 1
        else:
            failures.append((query, expected, actual, desc, decision.policy_reason))
        
        print(f"  [{status}] {desc:25s} -> {actual:10s} (expected {expected:10s})")
        if actual != expected:
            print(f"         Query: {query!r}")
            print(f"         Policy reason: {decision.policy_reason}")
    
    print()
    print(f"Results: {correct}/{total} correct ({100*correct/total:.1f}%)")
    print()
    
    if failures:
        print("Failures:")
        for query, expected, actual, desc, reason in failures:
            print(f"  - {desc}: expected {expected}, got {actual}")
            print(f"    Reason: {reason}")
            print(f"    Query: {query!r}")
    
    return correct / total


if __name__ == "__main__":
    evaluate()
