#!/usr/bin/env python3
"""Fine-tune all-MiniLM-L6-v2 on routing examples with contrastive learning."""

import json
import random
from collections import defaultdict
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer, InputExample, losses
from torch.utils.data import DataLoader


def load_examples(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def build_training_pairs(examples: list[dict]) -> list[InputExample]:
    """Build (anchor, positive) pairs from same-route examples."""
    by_route = defaultdict(list)
    for ex in examples:
        by_route[ex["labels"]["route"]].append(ex["query"])

    pairs = []
    for route, queries in by_route.items():
        if len(queries) < 2:
            continue
        # Create pairs - shuffle to avoid always pairing adjacent items
        shuffled = queries[:]
        random.shuffle(shuffled)
        for i in range(0, len(shuffled) - 1, 2):
            pairs.append(InputExample(texts=[shuffled[i], shuffled[i + 1]]))
        # Also pair first with last for extra coverage on small classes
        if len(queries) >= 3:
            pairs.append(InputExample(texts=[shuffled[0], shuffled[-1]]))
    random.shuffle(pairs)
    return pairs


def main():
    random.seed(42)
    torch.manual_seed(42)

    examples_path = Path(__file__).parent / "comprehensive_examples.json"
    examples = load_examples(examples_path)
    print(f"Loaded {len(examples)} examples")

    train_pairs = build_training_pairs(examples)
    print(f"Built {len(train_pairs)} training pairs")

    # Show class distribution in pairs
    route_counts = defaultdict(int)
    for ex in examples:
        route_counts[ex["labels"]["route"]] += 1
    print("Route distribution:")
    for route, count in sorted(route_counts.items(), key=lambda x: -x[1]):
        print(f"  {route}: {count}")

    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    print("Loaded base model: all-MiniLM-L6-v2")

    train_dataloader = DataLoader(train_pairs, shuffle=True, batch_size=32)
    train_loss = losses.MultipleNegativesRankingLoss(model)

    # Fine-tune for 3 epochs with a small warmup
    output_path = Path(__file__).parent / "finetuned_minilm"
    print(f"Training to {output_path} ...")

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=3,
        warmup_steps=max(1, len(train_dataloader) // 10),
        output_path=str(output_path),
        show_progress_bar=True,
    )

    print(f"Model saved to {output_path}")

    # Rebuild embeddings with fine-tuned model
    print("Rebuilding embeddings...")
    queries = [ex["query"] for ex in examples]
    embeddings = model.encode(queries, show_progress_bar=True, convert_to_numpy=True)

    emb_path = Path(__file__).parent / "comprehensive_embeddings.npy"
    import numpy as np
    np.save(emb_path, embeddings)
    print(f"Saved embeddings: {embeddings.shape} -> {emb_path}")

    # Quick sanity check
    from sklearn.metrics.pairwise import cosine_similarity
    test_queries = [
        "What time is it in Tokyo?",
        "Latest news on Israel",
        "What are the symptoms of flu?",
        "How are you today?",
    ]
    for q in test_queries:
        q_emb = model.encode([q])
        sims = cosine_similarity(q_emb, embeddings)[0]
        top3 = sims.argsort()[-3:][::-1]
        print(f"\n  Query: {q}")
        for idx in top3:
            print(f"    {sims[idx]:.4f} | {examples[idx]['labels']['route']:12s} | {queries[idx][:50]}")


if __name__ == "__main__":
    main()
