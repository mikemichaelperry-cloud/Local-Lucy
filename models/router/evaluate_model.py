#!/usr/bin/env python3
"""Evaluate a trained ModernBERT router model on test data."""

from pathlib import Path

import torch
import yaml
from sklearn.metrics import accuracy_score, classification_report
from transformers import AutoModel, AutoTokenizer

from model import RouterClassifier


def load_model(checkpoint_dir: Path, config: dict):
    """Load trained model from checkpoint."""
    base_model = AutoModel.from_pretrained(config["model"]["base_model"])
    model = RouterClassifier(base_model, config["model"])

    state_dict = torch.load(checkpoint_dir / "pytorch_model.bin", map_location="cpu")
    model.load_state_dict(state_dict)
    model.eval()
    return model


def evaluate(checkpoint_dir: str | Path, config_path: str | Path = "config.yaml"):
    checkpoint_dir = Path(checkpoint_dir)

    with open(config_path) as f:
        config = yaml.safe_load(f)

    print(f"Loading model from {checkpoint_dir}...")
    model = load_model(checkpoint_dir, config)
    tokenizer = AutoTokenizer.from_pretrained(config["model"]["base_model"])

    # Load test data
    from dataset import load_and_balance_data

    _, _, test_data = load_and_balance_data(config["data"])

    # Build label mappings from test data AND model dimensions
    intent_classes = sorted({ex["labels"]["intent_family"] for ex in test_data})
    evidence_classes = sorted({ex["labels"]["evidence_mode"] for ex in test_data})
    route_classes = sorted({ex["labels"]["route"] for ex in test_data})
    policy_classes = sorted({ex["labels"]["policy_override"] for ex in test_data})

    # Pad to match model output dimensions if needed
    model_intent_dim = model.intent_head.out_features
    model_evidence_dim = model.evidence_head.out_features
    model_route_dim = model.route_head.out_features
    model_policy_dim = model.policy_head.out_features

    while len(intent_classes) < model_intent_dim:
        intent_classes.append(f"unknown_{len(intent_classes)}")
    while len(evidence_classes) < model_evidence_dim:
        evidence_classes.append(f"unknown_{len(evidence_classes)}")
    while len(route_classes) < model_route_dim:
        route_classes.append(f"unknown_{len(route_classes)}")
    while len(policy_classes) < model_policy_dim:
        policy_classes.append(f"unknown_{len(policy_classes)}")

    intent2idx = {l: i for i, l in enumerate(intent_classes)}
    evidence2idx = {l: i for i, l in enumerate(evidence_classes)}
    route2idx = {l: i for i, l in enumerate(route_classes)}
    policy2idx = {l: i for i, l in enumerate(policy_classes)}

    # Collect predictions
    y_true = {"intent": [], "evidence": [], "route": [], "policy": []}
    y_pred = {"intent": [], "evidence": [], "route": [], "policy": []}

    print(f"Evaluating on {len(test_data)} test examples...")

    with torch.no_grad():
        for ex in test_data:
            query = ex["query"]
            labels = ex["labels"]

            inputs = tokenizer(
                query,
                return_tensors="pt",
                truncation=True,
                max_length=config["model"]["max_length"],
                padding=True,
            )

            logits = model(inputs["input_ids"], inputs["attention_mask"])

            y_true["intent"].append(intent2idx[labels["intent_family"]])
            y_true["evidence"].append(evidence2idx[labels["evidence_mode"]])
            y_true["route"].append(route2idx[labels["route"]])
            y_true["policy"].append(policy2idx[labels["policy_override"]])

            y_pred["intent"].append(torch.argmax(logits["intent"], dim=-1).item())
            y_pred["evidence"].append(torch.argmax(logits["evidence"], dim=-1).item())
            y_pred["route"].append(torch.argmax(logits["route"], dim=-1).item())
            y_pred["policy"].append(torch.argmax(logits["policy"], dim=-1).item())

    # Print results
    print("\n" + "=" * 60)
    print("EVALUATION RESULTS")
    print("=" * 60)

    for head in ["intent", "evidence", "route", "policy"]:
        classes = {
            "intent": intent_classes,
            "evidence": evidence_classes,
            "route": route_classes,
            "policy": policy_classes,
        }[head]
        acc = accuracy_score(y_true[head], y_pred[head])
        print(f"\n{head.upper()} — Accuracy: {acc:.4f}")
        print(
            classification_report(y_true[head], y_pred[head], target_names=classes, zero_division=0)
        )

    # Overall accuracy (all heads correct)
    all_correct = sum(
        1
        for i in range(len(test_data))
        if y_pred["intent"][i] == y_true["intent"][i]
        and y_pred["evidence"][i] == y_true["evidence"][i]
        and y_pred["route"][i] == y_true["route"][i]
    )
    overall = all_correct / len(test_data)
    print(f"\nOVERALL (all heads correct): {overall:.4f} ({all_correct}/{len(test_data)})")
    print("=" * 60)

    return overall


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint", default="checkpoints/best_model", help="Checkpoint directory"
    )
    parser.add_argument("--config", default="config.yaml", help="Config file")
    args = parser.parse_args()

    evaluate(args.checkpoint, args.config)
