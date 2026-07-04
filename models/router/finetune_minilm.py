#!/usr/bin/env python3
"""Fine-tune the MiniLM routing embedding model on routing examples with contrastive learning.

By default the script starts from an existing `finetuned_minilm/` checkpoint if one exists
and runs a short continual-training update. This preserves previously learned behaviours
while adapting to new examples. To train from the base model instead, delete or move the
existing `finetuned_minilm/` directory before running.
"""

import argparse
import json
import random
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer, InputExample
from sentence_transformers.sentence_transformer.losses import (
    BatchHardTripletLoss,
    BatchHardTripletLossDistanceFunction,
    MultipleNegativesRankingLoss,
)
from sklearn.metrics.pairwise import cosine_similarity
from torch.utils.data import DataLoader


def load_examples(path: Path) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def _route_to_index(examples: list[dict]) -> dict[str, int]:
    """Return a stable route -> integer label mapping."""
    return {route: i for i, route in enumerate(sorted({ex["labels"]["route"] for ex in examples}))}


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


def build_training_triplets(examples: list[dict]) -> tuple[list[InputExample], dict[str, int]]:
    """Build single-sentence examples with route labels for batch-hard triplet loss.

    The loss mines the hardest positive (same route) and hardest negative
    (different route) inside each batch automatically. This focuses the model
    on boundary cases rather than just pulling all same-route examples together.
    """
    route2idx = _route_to_index(examples)
    return [
        InputExample(texts=[ex["query"]], label=route2idx[ex["labels"]["route"]]) for ex in examples
    ], route2idx


def _choose_start_model(
    output_path: Path, force_base: bool, base_model: str
) -> tuple[SentenceTransformer, str]:
    """Pick the starting checkpoint."""
    if force_base:
        return SentenceTransformer(base_model), base_model

    existing = output_path
    if existing.exists():
        # Copy to a temp directory so we can overwrite `finetuned_minilm/` safely.
        temp_dir = Path(tempfile.mkdtemp(prefix="router_start_"))
        shutil.copytree(existing, temp_dir / "model")
        start = str(temp_dir / "model")
        print(f"Continuing from existing checkpoint: {existing}")
        return SentenceTransformer(start), "existing finetuned_minilm"
    return SentenceTransformer(base_model), base_model


def main():
    parser = argparse.ArgumentParser(description="Fine-tune the MiniLM routing embedding model.")
    parser.add_argument(
        "--epochs",
        type=int,
        default=2,
        help="Number of training epochs (default: 2 for continual fine-tuning).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Training batch size (default: 32).",
    )
    parser.add_argument(
        "--from-base",
        action="store_true",
        help="Train from the base model instead of the existing finetuned checkpoint.",
    )
    parser.add_argument(
        "--base-model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Base Sentence-Transformers model to start from (default: all-MiniLM-L6-v2).",
    )
    parser.add_argument(
        "--loss",
        choices=["mnrl", "batch_hard_triplet"],
        default="batch_hard_triplet",
        help=(
            "Loss function: mnrl = MultipleNegativesRankingLoss (anchor-positive pairs), "
            "batch_hard_triplet = hardest triplet inside each batch (default)."
        ),
    )
    args = parser.parse_args()

    random.seed(42)
    torch.manual_seed(42)

    examples_path = Path(__file__).parent / "comprehensive_examples.json"
    examples = load_examples(examples_path)
    print(f"Loaded {len(examples)} examples")

    # Show class distribution
    route_counts = defaultdict(int)
    for ex in examples:
        route_counts[ex["labels"]["route"]] += 1
    print("Route distribution:")
    for route, count in sorted(route_counts.items(), key=lambda x: -x[1]):
        print(f"  {route}: {count}")

    output_path = Path(__file__).parent / "finetuned_minilm"
    model, start_label = _choose_start_model(output_path, args.from_base, args.base_model)
    print(f"Loaded start model: {start_label}")

    if args.loss == "batch_hard_triplet":
        train_examples, route2idx = build_training_triplets(examples)
        print(f"Built {len(train_examples)} labeled examples for batch-hard triplet loss")
        # Larger batches give the loss more negatives/positives to mine.
        # Keep it modest so the 12 GB VRAM budget isn't stressed.
        effective_batch_size = max(args.batch_size, 64)
        train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=effective_batch_size)
        train_loss = BatchHardTripletLoss(
            model,
            distance_metric=BatchHardTripletLossDistanceFunction.cosine_distance,
            margin=0.5,
        )
    else:
        train_pairs = build_training_pairs(examples)
        print(f"Built {len(train_pairs)} training pairs for MultipleNegativesRankingLoss")
        train_dataloader = DataLoader(train_pairs, shuffle=True, batch_size=args.batch_size)
        train_loss = MultipleNegativesRankingLoss(model)

    print(f"Training to {output_path} for {args.epochs} epoch(s) with {args.loss}...")

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=args.epochs,
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
    np.save(emb_path, embeddings)
    print(f"Saved embeddings: {embeddings.shape} -> {emb_path}")

    # Quick sanity check
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
            print(
                f"    {sims[idx]:.4f} | {examples[idx]['labels']['route']:12s} | {queries[idx][:50]}"
            )


if __name__ == "__main__":
    main()
