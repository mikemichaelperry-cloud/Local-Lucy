#!/usr/bin/env python3
"""Build embedding router index from real queries with CORRECTED labels.

CRITICAL: Historical routes may be WRONG due to previously unfixed bugs.
We re-route ALL real queries through the FIXED legacy router to get
accurate ground-truth labels.
"""

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from classify import ClassificationResult, select_route
from policy import requires_evidence_mode


def extract_all_real_queries() -> list[str]:
    """Extract unique real user queries from all sources."""
    seen = set()
    queries = []

    # Source 1: SQLite routes table
    try:
        conn = sqlite3.connect(Path(__file__).parent.parent.parent / "state" / "lucy_state.db")
        cur = conn.cursor()
        cur.execute("SELECT metadata FROM routes WHERE metadata IS NOT NULL")
        for row in cur:
            try:
                meta = json.loads(row[0])
                q = meta.get("question", "").strip()
                if q and len(q) > 2:
                    key = q.lower()
                    if key not in seen:
                        seen.add(key)
                        queries.append(q)
            except:
                pass
        conn.close()
    except Exception as e:
        print(f"Warning: Could not read SQLite DB: {e}")

    # Source 2: request_history.jsonl (live)
    for path in [
        Path(__file__).parent.parent.parent / "state" / "request_history.jsonl",
        Path(__file__).parent.parent.parent / "snapshots" / "opt-experimental-v8-dev" / "state" / "request_history.jsonl",
    ]:
        if not path.exists():
            continue
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    q = data.get("request_text", "").strip()
                    if q and len(q) > 2:
                        key = q.lower()
                        if key not in seen:
                            seen.add(key)
                            queries.append(q)
                except:
                    pass

    # Source 3: classifier audit log
    audit_path = Path(__file__).parent.parent.parent / "logs" / "classifier_audit.jsonl"
    if audit_path.exists():
        with open(audit_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    q = data.get("raw_query", "").strip() or data.get("query", "").strip()
                    if q and len(q) > 2:
                        key = q.lower()
                        if key not in seen:
                            seen.add(key)
                            queries.append(q)
                except:
                    pass

    # Filter out junk / system commands
    filtered = []
    junk_keywords = [
        "test query", "evidence mode is now", "mode was switched",
        "[ silence ]", "please repeat that story", "2+2 2+2",
    ]
    for q in queries:
        q_lower = q.lower()
        if any(j in q_lower for j in junk_keywords):
            continue
        if len(q) > 1000:  # Too long
            continue
        filtered.append(q)

    return filtered


def classify_with_fixed_legacy(query: str) -> dict:
    """Run query through the FIXED legacy router for accurate labels."""
    requires_evidence, evidence_reason = requires_evidence_mode(query)
    q_lower = query.lower()

    # Build a synthetic ClassificationResult
    # Determine intent family from query content
    if any(k in q_lower for k in ["story", "poem", "novel", "compose a", "write a"]):
        intent_family = "local_answer"
        needs_web = False
        category = "creative"
    elif any(k in q_lower for k in ["news", "headlines", "latest news", "breaking"]):
        intent_family = "current_evidence"
        needs_web = True
        category = "news_world"
    elif any(k in q_lower for k in ["time is it", "current time", "what day is it", "timezone"]):
        intent_family = "current_evidence"
        needs_web = True
        category = "time_query"
    elif any(k in q_lower for k in ["symptom", "treatment", "medication", "dosage", "side effects", "is it safe"]):
        intent_family = "current_evidence"
        needs_web = True
        category = "medical"
    elif any(k in q_lower for k in ["stock price", "bitcoin", "exchange rate", "interest rate", "market cap"]):
        intent_family = "current_evidence"
        needs_web = True
        category = "financial"
    elif any(k in q_lower for k in ["legal to", "court ruling", "supreme court", "tenant rights", "statute"]):
        intent_family = "current_evidence"
        needs_web = True
        category = "legal"
    elif any(k in q_lower for k in ["how to", "how do i", "install", "debug", "what is python", "what are mosfets", "how capable"]):
        intent_family = "local_answer"
        needs_web = False
        category = "procedural"
    elif any(k in q_lower for k in ["who was", "who is", "what is the capital", "what is the speed", "when did", "what caused"]):
        intent_family = "background_overview"
        needs_web = True
        category = "informational"
    elif any(k in q_lower for k in ["hello", "who are you", "good morning", "how are you", "what is your name", "thank you"]):
        intent_family = "local_answer"
        needs_web = False
        category = "greeting"
    elif any(k in q_lower for k in ["what is 2+2", "what is 5+5", "what is 5 + 3", "calculate", "translate"]):
        intent_family = "local_answer"
        needs_web = False
        category = "math"
    else:
        intent_family = "local_answer"
        needs_web = False
        category = "general"

    classification = ClassificationResult(
        intent=intent_family,
        intent_family=intent_family,
        intent_class=intent_family,
        category=category,
        confidence=0.85,
        needs_web=needs_web,
        needs_memory=False,
        needs_synthesis=False,
        clarify_required=False,
        evidence_mode="required" if requires_evidence else "",
        evidence_reason=evidence_reason,
        augmentation_recommended=needs_web and not requires_evidence,
        force_local="story" in q_lower or "poem" in q_lower,
    )

    # Get route from select_route with fixed policy logic
    decision = select_route(classification, policy="fallback_only")

    return {
        "query": query,
        "labels": {
            "intent_family": intent_family,
            "evidence_mode": "required" if requires_evidence else "not_required",
            "route": decision.route,
            "policy_override": "none",
        },
        "metadata": {
            "source": "real_re_routed",
            "legacy_reason": decision.policy_reason,
            "provider": decision.provider,
        },
    }


def get_supplementary_examples() -> list[dict]:
    """Hand-crafted examples for underrepresented categories."""
    return [
        # Medical (AUGMENTED)
        {"query": "What are the symptoms of diabetes?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Can I take ibuprofen with aspirin?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What is the treatment for high blood pressure?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Side effects of metformin", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Flu symptoms in children", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "How do I know if I have COVID?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Migraine treatment options", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Is it safe to exercise with chest pain?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What are early signs of dementia?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Antibiotics for strep throat dosage", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Financial (AUGMENTED)
        {"query": "What is the current price of Apple stock?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Bitcoin price today", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Current EUR to USD exchange rate", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What is the current federal reserve interest rate?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Tesla stock performance this week", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Ethereum price right now", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "S&P 500 index today", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Legal (AUGMENTED)
        {"query": "Is it legal to record a phone call without consent?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What are tenant rights in California?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Latest Supreme Court decision on guns", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Speeding ticket penalty in New York", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Background knowledge (LOCAL_WITH_FALLBACK)
        {"query": "Who was Marie Curie?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Explain photosynthesis", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What caused the French Revolution?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "How does a nuclear reactor work?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What is CRISPR gene editing?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Explain the theory of relativity in simple terms", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What is dark matter?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "History of the Roman Empire", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What is machine learning?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Tell me about Napoleon", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},

        # Technical how-to (LOCAL)
        {"query": "How do I install Docker on Ubuntu?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "What is the best way to learn Python?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "How does garbage collection work in Python?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Debug this Python error: AttributeError", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "How do I set up a VPN?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Explain React hooks", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},

        # Math/translation/local (LOCAL)
        {"query": "What is 15 times 23?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Translate hello to Japanese", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "What is the square root of 144?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Factor x squared minus 9", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Solve 3x + 7 = 22", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},

        # News (NEWS)
        {"query": "Breaking news about the election", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "What is happening in Gaza right now?", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Latest tech news", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Weather alert for Sydney", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Sports headlines today", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Current situation in Ukraine", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Political news from Australia", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Latest Israel headlines", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},

        # Time (TIME)
        {"query": "What time is it in London?", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "Current time in New York", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "What day is it today?", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "Timezone difference between Tokyo and London", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "How many days until Christmas?", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},

        # Clarification (CLARIFY)
        {"query": "What?", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "Explain that again", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "I don't understand", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "Huh?", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "Can you clarify?", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},

        # Current evidence (AUGMENTED)
        {"query": "What does the latest research say about climate change?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Peer-reviewed studies on intermittent fasting", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Evidence for vaccines being safe", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Meta-analysis of coffee health effects", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Has cold fusion been proven?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Creative (LOCAL)
        {"query": "Write a poem about the ocean", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Imagine a world where AI governs everything", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Create a dialogue between Shakespeare and Einstein", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Write a short horror story", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Draft a screenplay scene about time travel", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},

        # Local advice/opinion
        {"query": "Should I learn Python or JavaScript?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "What are the pros and cons of remote work?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "How do I deal with burnout?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Advice for public speaking", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
    ]


def main():
    print("=" * 70)
    print("Building Shadow Router Index with Corrected Labels")
    print("=" * 70)

    # Extract real queries
    real_queries = extract_all_real_queries()
    print(f"\nExtracted {len(real_queries)} unique real queries")

    # Re-route through fixed legacy router
    print("\nRe-routing through FIXED legacy router for accurate labels...")
    real_labeled = []
    for q in real_queries:
        labeled = classify_with_fixed_legacy(q)
        real_labeled.append(labeled)

    # Add supplementary
    supplementary = get_supplementary_examples()

    # Combine
    combined = real_labeled + supplementary

    # Stats
    print(f"\n{'=' * 70}")
    print(f"Dataset Summary:")
    print(f"  Real queries (re-routed): {len(real_labeled)}")
    print(f"  Supplementary examples:   {len(supplementary)}")
    print(f"  Total:                    {len(combined)}")

    intent_counts = Counter(ex["labels"]["intent_family"] for ex in combined)
    route_counts = Counter(ex["labels"]["route"] for ex in combined)

    print(f"\n  Intent distribution:")
    for intent, count in sorted(intent_counts.items()):
        print(f"    {intent:25s}: {count:3d}")

    print(f"\n  Route distribution:")
    for route, count in sorted(route_counts.items()):
        print(f"    {route:20s}: {count:3d}")

    # Save
    output_path = Path("shadow_index.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in combined:
            f.write(json.dumps(ex) + "\n")

    print(f"\n  Saved to {output_path}")

    # Now build embedding index and test
    print(f"\n{'=' * 70}")
    print("Building Embedding Index...")
    print(f"{'=' * 70}")

    from embedding_router import EmbeddingRouter

    router = EmbeddingRouter()
    router.fit(combined)

    # Save index
    import numpy as np
    np.save("shadow_index_embeddings.npy", router.embeddings)
    with open("shadow_index_examples.json", "w") as f:
        json.dump(router.examples, f, indent=2)

    print(f"  Embeddings saved to shadow_index_embeddings.npy")
    print(f"  Examples saved to shadow_index_examples.json")

    # Quick test
    print(f"\n{'=' * 70}")
    print("Quick Inference Test")
    print(f"{'=' * 70}")
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
    ]

    for q in test_queries:
        result = router.predict(q, k=5)
        print(f"  {q:50s} -> {result['route']:15s} intent={result['intent_family']:20s} conf={result['confidence']:.3f}")

    return router, combined


if __name__ == "__main__":
    main()
