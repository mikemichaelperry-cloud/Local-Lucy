#!/usr/bin/env python3
"""Training script for ModernBERT router classifier.

Usage:
    cd models/router
    python3 train.py

Requires: transformers, torch, datasets, scikit-learn, PyYAML
"""

import json
import random
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from sklearn.metrics import classification_report
from torch.utils.data import DataLoader
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from dataset import RouterDataset, load_and_balance_data
from model import HEAD_NAMES, RouterClassifier


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def load_config(path: str = "config.yaml") -> dict:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def compute_loss(logits: dict[str, torch.Tensor], labels: dict[str, torch.Tensor]) -> torch.Tensor:
    total_loss = 0.0
    for head in HEAD_NAMES:
        loss = F.cross_entropy(logits[head], labels[head])
        total_loss += loss
    return total_loss


def evaluate(model, dataloader, device) -> dict:
    model.eval()
    all_preds = {head: [] for head in HEAD_NAMES}
    all_labels = {head: [] for head in HEAD_NAMES}
    total_loss = 0.0

    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = {k: v.to(device) for k, v in batch["labels"].items()}

            logits = model(input_ids, attention_mask)
            loss = compute_loss(logits, labels)
            total_loss += loss.item()

            for head in HEAD_NAMES:
                preds = torch.argmax(logits[head], dim=-1).cpu().numpy()
                all_preds[head].extend(preds)
                all_labels[head].extend(labels[head].cpu().numpy())

    metrics = {"loss": total_loss / len(dataloader)}
    for head in HEAD_NAMES:
        metrics[head] = classification_report(
            all_labels[head], all_preds[head], output_dict=True, zero_division=0
        )
    return metrics


def calibrate_temperature(model, val_loader, device) -> float:
    """Find optimal temperature for confidence calibration."""
    best_t = 1.0
    best_ece = float("inf")

    for t_val in np.linspace(0.5, 3.0, 50):
        t = torch.tensor(t_val).to(device)
        ece = compute_ece(model, val_loader, device, t)
        if ece < best_ece:
            best_ece = ece
            best_t = t_val

    print(f"Best temperature: {best_t:.3f}, ECE: {best_ece:.4f}")
    return best_t


def compute_ece(model, dataloader, device, temperature: torch.Tensor) -> float:
    """Compute Expected Calibration Error."""
    model.eval()
    confidences = []
    accuracies = []

    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = {k: v.to(device) for k, v in batch["labels"].items()}

            logits = model(input_ids, attention_mask)

            for head in HEAD_NAMES:
                probs = torch.softmax(logits[head] / temperature, dim=-1)
                pred = torch.argmax(probs, dim=-1)
                conf = torch.max(probs, dim=-1)[0]

                confidences.extend(conf.cpu().numpy())
                accuracies.extend((pred == labels[head]).cpu().numpy())

    confidences = np.array(confidences)
    accuracies = np.array(accuracies)

    n_bins = 10
    bin_boundaries = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i in range(n_bins):
        mask = (confidences >= bin_boundaries[i]) & (confidences < bin_boundaries[i + 1])
        if mask.sum() == 0:
            continue
        avg_conf = confidences[mask].mean()
        avg_acc = accuracies[mask].mean()
        ece += mask.sum() * abs(avg_conf - avg_acc)

    return ece / len(confidences)


def train():
    config = load_config()
    set_seed(config["training"]["seed"])

    device = torch.device("cpu")
    print(f"Using device: {device}")

    # Load tokenizer and base model
    print("Loading ModernBERT-base...")
    tokenizer = AutoTokenizer.from_pretrained(config["model"]["base_model"])
    base_model = AutoModel.from_pretrained(config["model"]["base_model"])

    # Build classifier
    model = RouterClassifier(base_model, config["model"])
    model.to(device)

    # Load data
    print("Loading dataset...")
    train_data, val_data, test_data = load_and_balance_data(config["data"])

    train_dataset = RouterDataset(train_data, tokenizer, config["model"]["max_length"])
    val_dataset = RouterDataset(val_data, tokenizer, config["model"]["max_length"])
    test_dataset = RouterDataset(test_data, tokenizer, config["model"]["max_length"])

    train_loader = DataLoader(
        train_dataset, batch_size=config["training"]["batch_size"], shuffle=True
    )
    val_loader = DataLoader(val_dataset, batch_size=config["training"]["batch_size"])
    test_loader = DataLoader(test_dataset, batch_size=config["training"]["batch_size"])

    # Optimizer
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )

    total_steps = (
        len(train_loader)
        * config["training"]["epochs"]
        // config["training"]["gradient_accumulation_steps"]
    )
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * config["training"]["warmup_ratio"]),
        num_training_steps=total_steps,
    )

    # Training loop
    checkpoint_dir = Path("checkpoints")
    checkpoint_dir.mkdir(exist_ok=True)
    best_val_loss = float("inf")

    for epoch in range(config["training"]["epochs"]):
        model.train()
        total_loss = 0.0

        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = {k: v.to(device) for k, v in batch["labels"].items()}

            logits = model(input_ids, attention_mask)
            loss = compute_loss(logits, labels)
            loss = loss / config["training"]["gradient_accumulation_steps"]
            loss.backward()

            if (step + 1) % config["training"]["gradient_accumulation_steps"] == 0:
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            total_loss += loss.item() * config["training"]["gradient_accumulation_steps"]

        # Validation
        val_metrics = evaluate(model, val_loader, device)
        avg_train_loss = total_loss / len(train_loader)
        avg_val_loss = val_metrics["loss"]

        print(
            f"Epoch {epoch + 1}/{config['training']['epochs']}: "
            f"train_loss={avg_train_loss:.4f}, val_loss={avg_val_loss:.4f}"
        )

        # Save best model
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            model.save_pretrained(checkpoint_dir / "best")
            print(f"  -> Saved new best model (val_loss={avg_val_loss:.4f})")

    # Final test evaluation
    print("\n=== Final Test Evaluation ===")
    test_metrics = evaluate(model, test_loader, device)
    print(json.dumps({k: v for k, v in test_metrics.items() if k != "loss"}, indent=2))

    # Calibration
    print("\n=== Temperature Calibration ===")
    optimal_temp = calibrate_temperature(model, val_loader, device)

    # Save final config
    config["calibration_temperature"] = float(optimal_temp)
    with open(checkpoint_dir / "best" / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    print("\nTraining complete. Model saved to checkpoints/best/")


if __name__ == "__main__":
    train()
