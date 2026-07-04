#!/usr/bin/env python3
"""Mine hard-negative / boundary routing examples from the current dataset.

Uses stratified k-fold cross-validation so the router is evaluated on examples
it did not train on. Misclassifications and very low-confidence correct answers
are written to a JSON file for review.
"""

import json
import os
import random
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold
from sentence_transformers import SentenceTransformer

# Force CPU for deterministic, light-weight evaluation.
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")


def predict_route(train_ex, train_embs, query_emb, top_k: int = 3):
    sims = cosine_similarity(query_emb, train_embs)[0]
    top_idx = np.argsort(sims)[-top_k:][::-1]
    votes = Counter()
    for idx in top_idx:
        votes[train_ex[idx]["labels"]["route"]] += sims[idx] ** 2
    return votes.most_common(1)[0][0], votes


def main():
    random.seed(42)
    np.random.seed(42)

    examples_path = Path(__file__).parent / "comprehensive_examples.json"
    examples = json.loads(examples_path.read_text())

    model = SentenceTransformer(str(Path(__file__).parent / "finetuned_minilm"))
    embs = model.encode([ex["query"] for ex in examples], show_progress_bar=True)

    labels = [ex["labels"]["route"] for ex in examples]
    skf = StratifiedKFold(n_splits=10, shuffle=True, random_state=42)

    mistakes = []
    low_conf_correct = []
    per_route_correct = defaultdict(lambda: [0, 0])

    for fold, (train_idx, test_idx) in enumerate(skf.split(embs, labels), 1):
        train_ex = [examples[i] for i in train_idx]
        train_embs = embs[train_idx]
        for i in test_idx:
            ex = examples[i]
            true_route = ex["labels"]["route"]
            pred_route, votes = predict_route(train_ex, train_embs, embs[i : i + 1])
            conf = votes[pred_route] / sum(votes.values())
            per_route_correct[true_route][1] += 1
            if pred_route == true_route:
                per_route_correct[true_route][0] += 1
                if conf < 0.5:
                    low_conf_correct.append(
                        {
                            "fold": fold,
                            "query": ex["query"],
                            "true_route": true_route,
                            "pred_route": pred_route,
                            "confidence": round(float(conf), 3),
                            "top3": {k: float(v) for k, v in votes.most_common(3)},
                        }
                    )
            else:
                mistakes.append(
                    {
                        "fold": fold,
                        "query": ex["query"],
                        "true_route": true_route,
                        "pred_route": pred_route,
                        "confidence": round(float(conf), 3),
                        "top3": {k: float(v) for k, v in votes.most_common(3)},
                    }
                )

    out_path = Path(__file__).parent / "hard_negatives_report.json"
    out_path.write_text(
        json.dumps(
            {
                "total_examples": len(examples),
                "mistakes_count": len(mistakes),
                "low_confidence_correct_count": len(low_conf_correct),
                "per_route_accuracy": {
                    route: round(c / t, 3) if t else 0
                    for route, (c, t) in sorted(per_route_correct.items())
                },
                "mistakes": mistakes,
                "low_confidence_correct": low_conf_correct,
            },
            indent=2,
        )
    )
    print(f"Wrote report to {out_path}")
    print(f"Mistakes: {len(mistakes)} / {len(examples)}")
    print(f"Low-confidence correct: {len(low_conf_correct)}")
    print("Per-route accuracy:")
    for route, (c, t) in sorted(per_route_correct.items()):
        print(f"  {route}: {c}/{t} = {c/t:.3f}")


if __name__ == "__main__":
    main()
