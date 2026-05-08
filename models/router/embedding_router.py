#!/usr/bin/env python3
"""Embedding-based nearest-neighbor router.

Uses ModernBERT [CLS] embeddings + cosine similarity for classification.
Much more data-efficient than training classification heads.
Works like a semantic search engine over labeled examples.
"""

import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics.pairwise import cosine_similarity
from transformers import AutoModel, AutoTokenizer


class EmbeddingRouter:
    """Nearest-neighbor classifier using ModernBERT embeddings."""

    def __init__(self, base_model: str = "answerdotai/ModernBERT-base"):
        self.device = torch.device("cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(base_model)
        self.model = AutoModel.from_pretrained(base_model)
        self.model.eval()
        self.model.to(self.device)

        self.examples: list[dict] = []
        self.embeddings: np.ndarray | None = None

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to [CLS] embeddings."""
        embeddings = []
        batch_size = 16
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                inputs = self.tokenizer(
                    batch,
                    return_tensors="pt",
                    truncation=True,
                    max_length=256,
                    padding=True,
                )
                inputs = {k: v.to(self.device) for k, v in inputs.items()}
                outputs = self.model(**inputs)
                # Use [CLS] token (first position)
                cls = outputs.last_hidden_state[:, 0, :].cpu().numpy()
                embeddings.append(cls)
        return np.vstack(embeddings)

    def fit(self, examples: list[dict]):
        """Index training examples."""
        self.examples = examples
        texts = [ex["query"] for ex in examples]
        print(f"Encoding {len(texts)} examples...")
        self.embeddings = self._encode(texts)
        print(f"Embeddings shape: {self.embeddings.shape}")

    def predict(self, query: str, k: int = 5) -> dict[str, Any]:
        """Predict labels for a query using k-NN."""
        if self.embeddings is None or len(self.examples) == 0:
            raise RuntimeError("Router not fitted. Call fit() first.")

        query_emb = self._encode([query])
        similarities = cosine_similarity(query_emb, self.embeddings)[0]

        # Get top-k nearest neighbors
        top_k_idx = np.argsort(similarities)[-k:][::-1]

        # Vote on labels
        from collections import Counter
        intent_votes = Counter()
        evidence_votes = Counter()
        route_votes = Counter()

        for idx in top_k_idx:
            ex = self.examples[idx]
            labels = ex["labels"]
            weight = similarities[idx]
            intent_votes[labels["intent_family"]] += weight
            evidence_votes[labels["evidence_mode"]] += weight
            route_votes[labels["route"]] += weight

        best_intent = intent_votes.most_common(1)[0][0]
        best_evidence = evidence_votes.most_common(1)[0][0]
        best_route = route_votes.most_common(1)[0][0]

        # Confidence = average similarity of top-k
        avg_sim = np.mean([similarities[i] for i in top_k_idx])

        return {
            "intent_family": best_intent,
            "evidence_mode": best_evidence,
            "route": best_route,
            "confidence": round(float(avg_sim), 4),
            "neighbors": [
                {
                    "query": self.examples[i]["query"],
                    "similarity": round(float(similarities[i]), 4),
                    "labels": self.examples[i]["labels"],
                }
                for i in top_k_idx
            ],
        }

    def evaluate(self, test_examples: list[dict], k: int = 5) -> dict[str, float]:
        """Evaluate on test set."""
        correct = {"intent": 0, "evidence": 0, "route": 0, "all": 0}
        total = len(test_examples)

        for ex in test_examples:
            pred = self.predict(ex["query"], k=k)
            labels = ex["labels"]

            if pred["intent_family"] == labels["intent_family"]:
                correct["intent"] += 1
            if pred["evidence_mode"] == labels["evidence_mode"]:
                correct["evidence"] += 1
            if pred["route"] == labels["route"]:
                correct["route"] += 1
            if (pred["intent_family"] == labels["intent_family"] and
                pred["evidence_mode"] == labels["evidence_mode"] and
                pred["route"] == labels["route"]):
                correct["all"] += 1

        return {key: count / total for key, count in correct.items()}


def main():
    import yaml
    from dataset_v2 import load_and_balance_data

    print("Embedding-based Router Evaluation")
    print("=" * 60)

    with open("config.yaml") as f:
        config = yaml.safe_load(f)

    train, val, test = load_and_balance_data(config["data"])
    print(f"Dataset: train={len(train)}, val={len(val)}, test={len(test)}")

    router = EmbeddingRouter()
    router.fit(train)

    print("\nEvaluating on test set...")
    metrics = router.evaluate(test, k=5)
    print(f"Intent accuracy:  {metrics['intent']:.4f}")
    print(f"Evidence accuracy: {metrics['evidence']:.4f}")
    print(f"Route accuracy:   {metrics['route']:.4f}")
    print(f"All correct:      {metrics['all']:.4f}")

    print("\nSample predictions:")
    for ex in test[:5]:
        pred = router.predict(ex["query"], k=5)
        labels = ex["labels"]
        print(f"  Query: {ex['query']}")
        print(f"    Pred: intent={pred['intent_family']}, route={pred['route']}, conf={pred['confidence']}")
        print(f"    True: intent={labels['intent_family']}, route={labels['route']}")
        print()


if __name__ == "__main__":
    main()
