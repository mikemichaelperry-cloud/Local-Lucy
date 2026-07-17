#!/usr/bin/env python3
"""Add personal/family query examples to the router index and rebuild embeddings."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "models" / "router"))
from background_learner import rebuild_embeddings

EXAMPLES_PATH = Path(__file__).parent / "models" / "router" / "comprehensive_examples.json"

NEW_EXAMPLES = [
    # Personal / family queries — all should route LOCAL
    {
        "query": "Who is my dog?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my dog's name?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My dog is hungry",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Where is my cat?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Tell me about my cat",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my son's name?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "How old is my daughter?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My wife is coming home",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What does my husband do?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My mom called me",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Where does my dad live?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My brother is visiting",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my sister doing?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My family is here",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Who is my best friend?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my name?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Do I have any pets?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "When is my birthday?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "How am I doing today?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My grandmother is ill",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What did my uncle say?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My aunt is visiting tomorrow",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Where is my pet?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My partner is late",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What does my child want?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My parents are coming over",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Who are my neighbors?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My roommate is noisy",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my address?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "Where do I live?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "My car is broken",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
    {
        "query": "What is my phone number?",
        "labels": {
            "intent_family": "local_answer",
            "evidence_mode": "not_required",
            "route": "LOCAL",
            "policy_override": "none",
        },
        "metadata": {"source": "personal_family_vocabulary"},
    },
]


def main():
    with open(EXAMPLES_PATH) as f:
        examples = json.load(f)

    original_count = len(examples)
    existing_queries = {ex["query"].lower().strip() for ex in examples}

    added = 0
    for ex in NEW_EXAMPLES:
        if ex["query"].lower().strip() not in existing_queries:
            examples.append(ex)
            added += 1

    print(f"Original examples: {original_count}")
    print(f"New examples added: {added}")
    print(f"Total examples: {len(examples)}")

    with open(EXAMPLES_PATH, "w") as f:
        json.dump(examples, f, indent=2)

    # Also update the JSONL index (background_learner uses this)
    from background_learner import save_index

    save_index(examples)

    print("\nRebuilding embeddings...")
    rebuild_embeddings(examples)
    print("Done.")


if __name__ == "__main__":
    main()
