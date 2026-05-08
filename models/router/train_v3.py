#!/usr/bin/env python3
"""ModernBERT router training with 1000+ augmented examples."""

import random
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
import yaml
from sklearn.metrics import classification_report
from torch.utils.data import DataLoader
from transformers import AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from dataset_v2 import RouterDataset, generate_large_dataset, load_historical_data
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
        metrics[h] = classification_report(all_labels[h], all_preds[h], output_dict=True, zero_division=0)
    return metrics


def main():
    log("=" * 60)
    log("ModernBERT Router Training V3 (1000+ examples)")
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

    log("Generating large dataset...")
    historical = load_historical_data(Path(config["data"].get("historical_path", "historical_routes.jsonl")))
    all_data = generate_large_dataset(target_total=1200)
    
    # Add historical if any
    if historical:
        all_data.extend(historical)
        random.shuffle(all_data)
    
    # Stratified split
    from collections import defaultdict
    by_intent = defaultdict(list)
    for ex in all_data:
        by_intent[ex["labels"]["intent_family"]].append(ex)
    
    train, val, test = [], [], []
    for intent, examples in by_intent.items():
        random.shuffle(examples)
        n = len(examples)
        n_test = max(1, int(n * 0.15))
        n_val = max(1, int(n * 0.15))
        test.extend(examples[:n_test])
        val.extend(examples[n_test:n_test + n_val])
        train.extend(examples[n_test + n_val:])
    
    random.shuffle(train)
    random.shuffle(val)
    random.shuffle(test)
    
    log(f"Train: {len(train)}, Val: {len(val)}, Test: {len(test)}")

    train_ds = RouterDataset(train, tokenizer, config["model"]["max_length"])
    val_ds = RouterDataset(val, tokenizer, config["model"]["max_length"])
    test_ds = RouterDataset(test, tokenizer, config["model"]["max_length"])

    train_loader = DataLoader(train_ds, batch_size=config["training"]["batch_size"], shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=config["training"]["batch_size"])
    test_loader = DataLoader(test_ds, batch_size=config["training"]["batch_size"])
    log(f"Batches per epoch: {len(train_loader)}")

    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )

    total_steps = len(train_loader) * config["training"]["epochs"] // config["training"]["gradient_accumulation_steps"]
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=int(total_steps * config["training"]["warmup_ratio"]),
        num_training_steps=total_steps,
    )

    best_val_loss = float("inf")
    patience = 3
    patience_counter = 0

    for epoch in range(1, config["training"]["epochs"] + 1):
        log(f"\n--- Epoch {epoch}/{config['training']['epochs']} ---")
        model.train()
        epoch_loss = 0.0
        optimizer.zero_grad()

        for step, batch in enumerate(train_loader):
            input_ids = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels = {k: v.to(device) for k, v in batch["labels"].items()}
            logits = model(input_ids, attention_mask)
            loss = compute_loss(logits, labels)
            loss = loss / config["training"]["gradient_accumulation_steps"]
            loss.backward()
            epoch_loss += loss.item() * config["training"]["gradient_accumulation_steps"]

            if (step + 1) % config["training"]["gradient_accumulation_steps"] == 0:
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

        avg_train_loss = epoch_loss / len(train_loader)
        val_metrics = evaluate(model, val_loader, device)
        val_loss = val_metrics["loss"]

        log(f"Epoch {epoch} summary: train_loss={avg_train_loss:.4f}, val_loss={val_loss:.4f}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            save_dir = Path("checkpoints/best_v3")
            save_dir.mkdir(parents=True, exist_ok=True)
            model.save_pretrained(save_dir)
            log(f"  -> Saved best model (val_loss={val_loss:.4f})")
        else:
            patience_counter += 1
            log(f"  -> No improvement (patience {patience_counter}/{patience})")
            if patience_counter >= patience:
                log("Early stopping triggered.")
                break

    log("\n=== Final Test Evaluation ===")
    test_metrics = evaluate(model, test_loader, device)
    log(f"Test loss: {test_metrics['loss']:.4f}")
    for head in HEAD_NAMES:
        acc = test_metrics[head]["accuracy"]
        log(f"Test {head} accuracy: {acc:.4f}")

    log("\nTraining complete.")


if __name__ == "__main__":
    main()
