#!/usr/bin/env python3
"""
Benchmark ModernBERT-base [CLS] vs sentence-transformers for routing embeddings.

Evaluates on the comprehensive_examples.json dataset using leave-one-out
cross-validation (or a held-out split) to compare:
  - Accuracy per route
  - Confidence calibration
  - Short-query robustness (the key weakness of ModernBERT [CLS])

Usage:
    cd /home/mike/lucy-v9
    source ui-v9/.venv/bin/activate
    python models/router/evaluate_embedding_models.py
"""

import json
import random
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROUTER_DIR = Path(__file__).parent
EXAMPLES_PATH = ROUTER_DIR / "comprehensive_examples.json"


def load_examples():
    with open(EXAMPLES_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Model A: ModernBERT-base [CLS] (current production router)
# ---------------------------------------------------------------------------
class ModernBERTEncoder:
    name = "ModernBERT-base [CLS]"

    def __init__(self):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.tokenizer = AutoTokenizer.from_pretrained("answerdotai/ModernBERT-base")
        self.model = AutoModel.from_pretrained("answerdotai/ModernBERT-base")
        self.model.eval()

    def encode(self, texts: list[str]) -> np.ndarray:
        import torch
        embeddings = []
        batch_size = 16
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                inputs = self.tokenizer(
                    batch, return_tensors="pt", truncation=True,
                    max_length=256, padding=True,
                )
                outputs = self.model(**inputs)
                cls = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                embeddings.append(cls)
        return np.vstack(embeddings)


# ---------------------------------------------------------------------------
# Model B: sentence-transformers (candidate replacement)
# ---------------------------------------------------------------------------
class SentenceTransformerEncoder:
    name = "sentence-transformers all-MiniLM-L6-v2"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)


# ---------------------------------------------------------------------------
# Evaluation harness
# ---------------------------------------------------------------------------
def evaluate_encoder(encoder, examples: list[dict], k: int = 3) -> dict:
    """Evaluate encoder using a 90/10 train/test split."""
    random.seed(42)
    shuffled = examples.copy()
    random.shuffle(shuffled)
    split = int(len(shuffled) * 0.9)
    train, test = shuffled[:split], shuffled[split:]

    print(f"  Encoding {len(train)} training examples with {encoder.name}...")
    train_embs = encoder.encode([ex["query"] for ex in train])
    print(f"  Encoding {len(test)} test queries...")
    test_embs = encoder.encode([ex["query"] for ex in test])

    correct_route = 0
    correct_intent = 0
    total = len(test)

    # Short-query (< 5 words) tracking
    short_total = 0
    short_correct = 0
    short_confidences = []
    long_confidences = []

    for i, ex in enumerate(test):
        query = ex["query"]
        sims = cosine_similarity(test_embs[i:i+1], train_embs)[0]
        top_k_idx = np.argsort(sims)[-k:][::-1]

        from collections import Counter
        route_votes = Counter()
        intent_votes = Counter()
        total_weight = 0
        for idx in top_k_idx:
            weight = sims[idx] ** 2
            route_votes[train[idx]["labels"]["route"]] += weight
            intent_votes[train[idx]["labels"]["intent_family"]] += weight
            total_weight += weight

        pred_route = route_votes.most_common(1)[0][0]
        pred_intent = intent_votes.most_common(1)[0][0]
        avg_sim = total_weight / k

        if pred_route == ex["labels"]["route"]:
            correct_route += 1
        if pred_intent == ex["labels"]["intent_family"]:
            correct_intent += 1

        word_count = len(query.split())
        if word_count < 5:
            short_total += 1
            if pred_route == ex["labels"]["route"]:
                short_correct += 1
            short_confidences.append(avg_sim)
        else:
            long_confidences.append(avg_sim)

    return {
        "route_accuracy": correct_route / total,
        "intent_accuracy": correct_intent / total,
        "short_accuracy": short_correct / short_total if short_total else 0.0,
        "short_count": short_total,
        "long_mean_confidence": float(np.mean(long_confidences)) if long_confidences else 0.0,
        "short_mean_confidence": float(np.mean(short_confidences)) if short_confidences else 0.0,
    }


# ---------------------------------------------------------------------------
# Known failure-mode probe set
# ---------------------------------------------------------------------------
PROBE_QUERIES = [
    ("Who is my dog?", "LOCAL"),
    ("What is my cat?", "LOCAL"),
    ("My brother is visiting", "LOCAL"),
    ("When is my birthday?", "LOCAL"),
    ("What time is it?", "TIME"),
    ("What day is it today?", "TIME"),
    ("Latest news", "NEWS"),
    ("Weather forecast", "WEATHER"),
    ("What is 2+2?", "LOCAL"),
    ("Tell me a joke", "LOCAL"),
    ("How are you?", "LOCAL"),
    ("Thanks", "LOCAL"),
    ("Correct", "LOCAL"),
    ("Wrong", "LOCAL"),
]


def probe_encoder(encoder, examples: list[dict]) -> dict:
    """Evaluate encoder on the small probe set using the full index."""
    all_embs = encoder.encode([ex["query"] for ex in examples])
    correct = 0
    results = []
    for query, expected in PROBE_QUERIES:
        q_emb = encoder.encode([query])
        sims = cosine_similarity(q_emb, all_embs)[0]
        top_k_idx = np.argsort(sims)[-3:][::-1]

        from collections import Counter
        route_votes = Counter()
        for idx in top_k_idx:
            route_votes[examples[idx]["labels"]["route"]] += sims[idx] ** 2
        pred = route_votes.most_common(1)[0][0]

        ok = pred == expected
        if ok:
            correct += 1
        results.append({
            "query": query,
            "expected": expected,
            "predicted": pred,
            "correct": ok,
            "top_sim": round(float(sims[top_k_idx[0]]), 4),
        })
    return {"accuracy": correct / len(PROBE_QUERIES), "results": results}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    examples = load_examples()
    print(f"Loaded {len(examples)} examples\n")

    encoders = [ModernBERTEncoder()]

    # Only add sentence-transformers if available
    try:
        encoders.append(SentenceTransformerEncoder())
    except Exception as exc:
        print(f"sentence-transformers not available ({exc}), skipping comparison.\n")

    for enc in encoders:
        print("=" * 60)
        print(enc.name)
        print("=" * 60)

        metrics = evaluate_encoder(enc, examples)
        print(f"  Route accuracy:     {metrics['route_accuracy']:.3f}")
        print(f"  Intent accuracy:    {metrics['intent_accuracy']:.3f}")
        print(f"  Short-query acc:    {metrics['short_accuracy']:.3f} (n={metrics['short_count']})")
        print(f"  Long mean conf:     {metrics['long_mean_confidence']:.3f}")
        print(f"  Short mean conf:    {metrics['short_mean_confidence']:.3f}")

        probe = probe_encoder(enc, examples)
        print(f"  Probe accuracy:     {probe['accuracy']:.3f}")
        for r in probe["results"]:
            status = "✅" if r["correct"] else "❌"
            print(f"    {status} {r['query']!r:30s} -> {r['predicted']:10s} (top_sim={r['top_sim']})")
        print()


if __name__ == "__main__":
    main()
