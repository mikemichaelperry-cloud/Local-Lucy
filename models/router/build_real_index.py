#!/usr/bin/env python3
"""Build embedding router index from real user queries + supplementary examples.

1. Extracts real queries from request_history.jsonl
2. Labels them with intent_family based on content
3. Adds supplementary examples for underrepresented categories
4. Builds embedding index
5. Runs embedding evaluation against legacy router
"""

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode


def extract_real_queries() -> list[dict]:
    """Extract and clean real user queries from request history."""
    queries = []
    seen = set()

    for path in [
        Path("../../state/request_history.jsonl"),
        Path("../../snapshots/opt-experimental-v9-dev/state/request_history.jsonl"),
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
                    route = data.get("route", {}).get("final_mode", "UNKNOWN")

                    # Skip junk
                    if not q or len(q) < 3 or route == "UNKNOWN":
                        continue
                    if any(j in q.lower() for j in [
                        "test query", "evidence mode is now", "mode was switched",
                        "thank you", "2+2 2+2", "please repeat that story"
                    ]):
                        continue

                    key = q.lower()
                    if key not in seen:
                        seen.add(key)
                        queries.append({"query": q, "route": route})
                except:
                    pass

    return queries


def label_intent(query: str, route: str) -> tuple[str, str]:
    """Determine intent_family and evidence_mode from query + route."""
    q = query.lower()
    requires_evidence, evidence_reason = requires_evidence_mode(query)

    # Determine intent family from query content
    if any(k in q for k in ["story", "poem", "novel", "compose", "write a"]):
        return "creative_writing", "not_required"

    if any(k in q for k in ["news", "headlines", "latest", "breaking"]):
        return "news_request", "not_required"

    if any(k in q for k in ["time", "what day is it", "what time is it"]):
        return "time_query", "not_required"

    if any(k in q for k in ["hello", "who are you", "good morning", "how are you", "what is your name"]):
        return "local_answer", "not_required"

    if any(k in q for k in ["how to", "how do i", "install", "debug", "what is python", "what are mosfets"]):
        return "technical_explanation", "not_required"

    if any(k in q for k in ["symptom", "treatment", "medication", "dosage", "side effects"]):
        return "medical_inquiry", "required"

    if any(k in q for k in ["who was", "who is", "what is the capital", "what is the speed", "when did"]):
        if route == "LOCAL":
            return "background_overview", "not_required"
        else:
            return "current_evidence", "required" if requires_evidence else "not_required"

    if any(k in q for k in ["how can i", "what can i do", "how capable", "what would you"]):
        return "local_answer", "not_required"

    # Fallback based on route
    route_to_intent = {
        "LOCAL": "local_answer",
        "LOCAL_WITH_FALLBACK": "background_overview",
        "AUGMENTED": "current_evidence",
        "NEWS": "news_request",
        "TIME": "time_query",
        "CLARIFY": "clarification",
    }
    intent = route_to_intent.get(route, "local_answer")
    evidence = "required" if requires_evidence else "not_required"
    return intent, evidence


def get_supplementary_examples() -> list[dict]:
    """Add realistic examples for underrepresented categories."""

    supplementary = [
        # Medical (AUGMENTED)
        {"query": "What are the symptoms of diabetes?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Can I take ibuprofen with aspirin?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What is the treatment for high blood pressure?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Side effects of metformin", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Flu symptoms in children", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "How do I know if I have COVID?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Migraine treatment options", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Is it safe to exercise with chest pain?", "labels": {"intent_family": "medical_inquiry", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Financial (AUGMENTED)
        {"query": "What is the current price of Apple stock?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Bitcoin price today", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Current EUR to USD exchange rate", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What is the current federal reserve interest rate?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Tesla stock performance this week", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Legal (AUGMENTED)
        {"query": "Is it legal to record a phone call without consent?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "What are tenant rights in California?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Latest Supreme Court decision on guns", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Background knowledge (LOCAL_WITH_FALLBACK)
        {"query": "Who was Marie Curie?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Explain photosynthesis", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What caused the French Revolution?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "How does a nuclear reactor work?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What is CRISPR gene editing?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Explain the theory of relativity in simple terms", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "What is dark matter?", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "History of the Roman Empire", "labels": {"intent_family": "background_overview", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},

        # Technical how-to (LOCAL)
        {"query": "How do I install Docker on Ubuntu?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "What is the best way to learn Python?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "How does garbage collection work in Python?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "policy_override": "none"}},
        {"query": "Debug this Python error: AttributeError", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "How do I set up a VPN?", "labels": {"intent_family": "technical_explanation", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},

        # Math/translation/local (LOCAL)
        {"query": "What is 15 times 23?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Translate hello to Japanese", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "What is the square root of 144?", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Factor x squared minus 9", "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},

        # News (NEWS)
        {"query": "Breaking news about the election", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "What is happening in Gaza right now?", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Latest tech news", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Weather alert for Sydney", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Sports headlines today", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},
        {"query": "Current situation in Ukraine", "labels": {"intent_family": "news_request", "evidence_mode": "not_required", "route": "NEWS", "policy_override": "none"}},

        # Time (TIME)
        {"query": "What time is it in London?", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "Current time in New York", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "What day is it today?", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},
        {"query": "Timezone difference between Tokyo and London", "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"}},

        # Clarification (CLARIFY)
        {"query": "What?", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "Explain that again", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "I don't understand", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},
        {"query": "Huh?", "labels": {"intent_family": "clarification", "evidence_mode": "not_required", "route": "CLARIFY", "policy_override": "none"}},

        # Current evidence (AUGMENTED)
        {"query": "What does the latest research say about climate change?", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Peer-reviewed studies on intermittent fasting", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},
        {"query": "Evidence for vaccines being safe", "labels": {"intent_family": "current_evidence", "evidence_mode": "required", "route": "AUGMENTED", "policy_override": "none"}},

        # Creative (LOCAL)
        {"query": "Write a poem about the ocean", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Imagine a world where AI governs everything", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
        {"query": "Create a dialogue between Shakespeare and Einstein", "labels": {"intent_family": "creative_writing", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"}},
    ]

    return supplementary


def build_dataset() -> list[dict]:
    """Build combined dataset from real + supplementary examples."""
    real_queries = extract_real_queries()

    # Label real queries
    labeled_real = []
    for item in real_queries:
        intent, evidence = label_intent(item["query"], item["route"])
        labeled_real.append({
            "query": item["query"],
            "labels": {
                "intent_family": intent,
                "evidence_mode": evidence,
                "route": item["route"],
                "policy_override": "none",
            },
            "metadata": {"source": "real", "original": item["query"]},
        })

    supplementary = get_supplementary_examples()
    for ex in supplementary:
        ex["metadata"] = {"source": "supplementary"}

    combined = labeled_real + supplementary

    # Print stats
    print(f"Real queries: {len(labeled_real)}")
    print(f"Supplementary: {len(supplementary)}")
    print(f"Total: {len(combined)}")

    intent_counts = Counter(ex["labels"]["intent_family"] for ex in combined)
    route_counts = Counter(ex["labels"]["route"] for ex in combined)

    print("\nIntent distribution:")
    for intent, count in sorted(intent_counts.items()):
        print(f"  {intent:25s}: {count}")

    print("\nRoute distribution:")
    for route, count in sorted(route_counts.items()):
        print(f"  {route:20s}: {count}")

    return combined


def main():
    print("=" * 60)
    print("Building Real Query Dataset for Embedding Router")
    print("=" * 60)

    dataset = build_dataset()

    # Save
    output_path = Path("real_query_index.jsonl")
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in dataset:
            f.write(json.dumps(ex) + "\n")

    print(f"\nSaved {len(dataset)} examples to {output_path}")

    # Also save as embedding router training format
    from dataset_v2 import RouterDataset
    print("\nTo build the embedding index, run:")
    print("  from embedding_router import EmbeddingRouter")
    print("  from build_real_index import build_dataset")
    print("  router = EmbeddingRouter()")
    print("  router.fit(build_dataset())")


if __name__ == "__main__":
    main()
