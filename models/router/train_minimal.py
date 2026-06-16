#!/usr/bin/env python3
"""Minimal ModernBERT router training — robust, progress-reporting."""

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


def log(msg):
    print(msg, flush=True)


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def compute_loss(logits, labels):
    total = 0.0
    for head in HEAD_NAMES:
        total += F.cross_entropy(logits[head], labels[head])
    return total


def evaluate(model, dataloader, device):
    model.eval()
    all_preds = {h: [] for h in HEAD_NAMES}
    all_labels = {h: [] for h in HEAD_NAMES}
    total_loss = 0.0
    with torch.no_grad():
        for batch in dataloader:
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = {k: v.to(device) for k, v in batch["labels"].items()}
            logits = model(input_ids, attention_mask)
            total_loss += compute_loss(logits, labels).item()
            for h in HEAD_NAMES:
                preds = torch.argmax(logits[h], dim=-1).cpu().numpy()
                all_preds[h].extend(preds)
                all_labels[h].extend(labels[h].cpu().numpy())
    metrics = {"loss": total_loss / len(dataloader)}
    for h in HEAD_NAMES:
        metrics[h] = classification_report(
            all_labels[h], all_preds[h], output_dict=True, zero_division=0
        )
    return metrics


def main():
    log("=" * 60)
    log("ModernBERT Router Training")
    log("=" * 60)

    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    set_seed(config["training"]["seed"])

    device = torch.device("cpu")
    log(f"Device: {device}")

    log("Loading tokenizer and model...")
    tokenizer = AutoTokenizer.from_pretrained(config["model"]["base_model"])
    base_model = AutoModel.from_pretrained(config["model"]["base_model"])
    log("Model loaded.")

    model = RouterClassifier(base_model, config["model"])
    model.to(device)

    log("Loading dataset...")
    train_data, val_data, test_data = load_and_balance_data(config["data"])
    log(f"Train: {len(train_data)}, Val: {len(val_data)}, Test: {len(test_data)}")

    train_ds = RouterDataset(train_data, tokenizer, config["model"]["max_length"])
    val_ds = RouterDataset(val_data, tokenizer, config["model"]["max_length"])
    test_ds = RouterDataset(test_data, tokenizer, config["model"]["max_length"])

    train_loader = DataLoader(train_ds, batch_size=config["training"]["batch_size"], shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=config["training"]["batch_size"])
    test_loader = DataLoader(test_ds, batch_size=config["training"]["batch_size"])
    log(f"Batches per epoch: {len(train_loader)}")

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

    checkpoint_dir = Path("checkpoints")
    checkpoint_dir.mkdir(exist_ok=True)
    best_val_loss = float("inf")

    for epoch in range(config["training"]["epochs"]):
        log(f"\n--- Epoch {epoch + 1}/{config['training']['epochs']} ---")
        model.train()
        epoch_loss = 0.0

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

            epoch_loss += loss.item() * config["training"]["gradient_accumulation_steps"]

            if (step + 1) % 20 == 0:
                log(f"  Step {step + 1}/{len(train_loader)}: loss={loss.item():.4f}")

        avg_train_loss = epoch_loss / len(train_loader)
        val_metrics = evaluate(model, val_loader, device)
        avg_val_loss = val_metrics["loss"]

        log(
            f"Epoch {epoch + 1} summary: train_loss={avg_train_loss:.4f}, val_loss={avg_val_loss:.4f}"
        )

        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            model.save_pretrained(checkpoint_dir / "best")
            log(f"  -> Saved best model (val_loss={avg_val_loss:.4f})")

    log("\n=== Final Test Evaluation ===")
    test_metrics = evaluate(model, test_loader, device)
    log(json.dumps({k: v for k, v in test_metrics.items() if k != "loss"}, indent=2))

    # Simple calibration: find temperature that minimizes ECE on validation
    log("\n=== Temperature Calibration ===")
    best_temp = 1.0
    best_ece = float("inf")
    for t_val in np.linspace(0.5, 3.0, 20):
        t = torch.tensor(t_val)
        ece = 0.0
        total = 0
        model.eval()
        with torch.no_grad():
            for batch in val_loader:
                input_ids = batch["input_ids"].to(device)
                attention_mask = batch["attention_mask"].to(device)
                labels = {k: v.to(device) for k, v in batch["labels"].items()}
                logits = model(input_ids, attention_mask)
                for h in HEAD_NAMES:
                    probs = torch.softmax(logits[h] / t, dim=-1)
                    conf, pred = torch.max(probs, dim=-1)
                    acc = (pred == labels[h]).float()
                    ece += torch.abs(conf - acc).sum().item()
                    total += len(acc)
        ece = ece / total
        if ece < best_ece:
            best_ece = ece
            best_temp = t_val

    log(f"Optimal temperature: {best_temp:.3f}, ECE: {best_ece:.4f}")

    config["calibration_temperature"] = float(best_temp)
    with open(checkpoint_dir / "best" / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    log("\nTraining complete. Model saved to checkpoints/best/")


if __name__ == "__main__":
    main()
