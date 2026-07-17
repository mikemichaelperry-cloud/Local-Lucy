#!/usr/bin/env python3
"""Train a lightweight classifier head on frozen fine-tuned MiniLM embeddings.

The head learns explicit decision boundaries over the existing embeddings instead
of relying solely on k-NN similarity.  The embedding model is never updated, so
this is fast and memory-cheap.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import cast

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from sklearn.metrics import classification_report
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import train_test_split
from torch.utils.data import DataLoader, TensorDataset


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class RouteClassifierHead(nn.Module):
    """Simple linear (or one-hidden-layer) classifier over frozen embeddings."""

    def __init__(self, input_dim: int, num_classes: int, hidden_dim: int | None = None):
        super().__init__()
        self.net: nn.Module
        if hidden_dim:
            self.net = nn.Sequential(
                nn.Linear(input_dim, hidden_dim),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden_dim, num_classes),
            )
        else:
            self.net = nn.Linear(input_dim, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return cast(torch.Tensor, self.net(x))


# ---------------------------------------------------------------------------
# Training helpers
# ---------------------------------------------------------------------------


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def compute_class_weights(labels: np.ndarray) -> torch.Tensor:
    """Inverse-frequency weights for imbalanced routes."""
    counts = Counter(labels.tolist())
    total = len(labels)
    num_classes = len(counts)
    weights = [total / (num_classes * counts[i]) for i in range(num_classes)]
    return torch.tensor(weights, dtype=torch.float32)


def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    device: torch.device,
) -> float:
    model.train()
    total_loss = 0.0
    total_samples = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item() * x.size(0)
        total_samples += x.size(0)
    return total_loss / total_samples


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    device: torch.device,
) -> tuple[float, np.ndarray, np.ndarray]:
    model.eval()
    all_preds: list[int] = []
    all_labels: list[int] = []
    for x, y in loader:
        x = x.to(device)
        logits = model(x)
        preds = torch.argmax(logits, dim=1).cpu().numpy()
        all_preds.extend(preds.tolist())
        all_labels.extend(y.numpy().tolist())
    accuracy = sum(p == l for p, l in zip(all_preds, all_labels)) / len(all_labels)
    return accuracy, np.array(all_labels), np.array(all_preds)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train a route classifier head on frozen embeddings."
    )
    parser.add_argument(
        "--examples", default="comprehensive_examples.json", help="Examples JSON file"
    )
    parser.add_argument(
        "--embeddings", default="comprehensive_embeddings.npy", help="Embeddings .npy file"
    )
    parser.add_argument("--output-dir", default=".", help="Directory to save head artifacts")
    parser.add_argument(
        "--hidden-dim", type=int, default=0, help="If >0, use a one-hidden-layer MLP"
    )
    parser.add_argument("--epochs", type=int, default=200, help="Max training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=1e-4, help="Weight decay")
    parser.add_argument("--patience", type=int, default=20, help="Early-stopping patience")
    parser.add_argument("--val-size", type=float, default=0.15, help="Validation fraction")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="Device to train on (default: auto)",
    )
    args = parser.parse_args()

    set_seed(args.seed)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resolve paths relative to the script directory if not absolute
    here = Path(__file__).resolve().parent
    examples_path = (
        here / args.examples if not Path(args.examples).is_absolute() else Path(args.examples)
    )
    embeddings_path = (
        here / args.embeddings if not Path(args.embeddings).is_absolute() else Path(args.embeddings)
    )

    examples = json.loads(examples_path.read_text())
    embeddings = np.load(embeddings_path)

    # Build label mapping from actual data, sorted for stability
    routes = sorted({ex["labels"]["route"] for ex in examples})
    route_to_idx = {route: i for i, route in enumerate(routes)}
    idx_to_route = {i: route for route, i in route_to_idx.items()}

    labels = np.array([route_to_idx[ex["labels"]["route"]] for ex in examples])

    print(f"Loaded {len(examples)} examples, {embeddings.shape[1]}D embeddings")
    print(f"Routes ({len(routes)}): {routes}")
    print("Route distribution:")
    for route, count in sorted(
        Counter(ex["labels"]["route"] for ex in examples).items(), key=lambda x: -x[1]
    ):
        print(f"  {route}: {count}")

    # Stratified split
    X_train, X_val, y_train, y_val = train_test_split(
        embeddings, labels, test_size=args.val_size, random_state=args.seed, stratify=labels
    )

    # Normalise embeddings to unit length (helps linear head stability)
    X_train = X_train / (np.linalg.norm(X_train, axis=1, keepdims=True) + 1e-12)
    X_val = X_val / (np.linalg.norm(X_val, axis=1, keepdims=True) + 1e-12)

    train_dataset = TensorDataset(
        torch.tensor(X_train, dtype=torch.float32),
        torch.tensor(y_train, dtype=torch.long),
    )
    val_dataset = TensorDataset(
        torch.tensor(X_val, dtype=torch.float32),
        torch.tensor(y_val, dtype=torch.long),
    )

    train_loader = DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=args.batch_size)

    device = torch.device(
        "cuda"
        if args.device == "cuda" or (args.device == "auto" and torch.cuda.is_available())
        else "cpu"
    )
    print(f"Training on {device}")

    hidden_dim = args.hidden_dim if args.hidden_dim > 0 else None
    model = RouteClassifierHead(
        input_dim=embeddings.shape[1],
        num_classes=len(routes),
        hidden_dim=hidden_dim,
    ).to(device)

    class_weights = compute_class_weights(y_train).to(device)
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)

    best_val_acc = 0.0
    best_state: dict | None = None
    patience_counter = 0

    for epoch in range(1, args.epochs + 1):
        train_loss = train_epoch(model, train_loader, optimizer, criterion, device)
        val_acc, val_labels, val_preds = evaluate(model, val_loader, device)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = model.state_dict()
            patience_counter = 0
        else:
            patience_counter += 1

        if epoch % 10 == 0 or patience_counter == 0:
            print(
                f"Epoch {epoch:3d} | loss={train_loss:.4f} | val_acc={val_acc:.4f} | best={best_val_acc:.4f}"
            )

        if patience_counter >= args.patience:
            print(f"Early stopping at epoch {epoch}")
            break

    # Load best checkpoint
    assert best_state is not None
    model.load_state_dict(best_state)

    # Final evaluation
    val_acc, val_labels, val_preds = evaluate(model, val_loader, device)
    print("\nFinal validation accuracy:", f"{val_acc:.4f}")
    print("\nPer-route validation report:")
    print(classification_report(val_labels, val_preds, target_names=routes, zero_division=0))

    # Calibrate a confidence threshold using k-NN as the fallback.
    # For each candidate threshold, use the classifier when its max probability
    # is >= threshold; otherwise use the k-NN prediction.  Pick the threshold
    # that maximises the combined accuracy on the validation set.
    def _knn_fallback_preds(k: int = 3) -> np.ndarray:
        sims = cosine_similarity(X_val, X_train)
        knn_preds = []
        for sim in sims:
            top_idx = np.argsort(sim)[-k:][::-1]
            vote_counter: Counter = Counter()
            for idx in top_idx:
                vote_counter[y_train[idx]] += sim[idx] ** 2
            knn_preds.append(vote_counter.most_common(1)[0][0])
        return np.array(knn_preds)

    knn_val_preds = _knn_fallback_preds()
    knn_val_acc = float(np.mean(knn_val_preds == y_val))
    print(f"\nk-NN-only validation accuracy: {knn_val_acc:.4f}")

    model.eval()
    with torch.no_grad():
        val_probs = F.softmax(model(torch.tensor(X_val, dtype=torch.float32).to(device)), dim=-1)
        val_max_probs, _ = torch.max(val_probs, dim=-1)
        val_max_probs_np = val_max_probs.cpu().numpy()

    best_combined_acc = 0.0
    best_threshold = 0.0
    print("\nThreshold calibration (classifier + k-NN fallback):")
    for thr in np.arange(0.50, 0.96, 0.05):
        use_clf = val_max_probs_np >= thr
        combined = np.where(use_clf, val_preds, knn_val_preds)
        acc = float(np.mean(combined == y_val))
        if acc > best_combined_acc:
            best_combined_acc = acc
            best_threshold = float(thr)
        print(f"  thr={thr:.2f} -> combined acc={acc:.4f}")

    print(
        f"\nBest combined validation accuracy: {best_combined_acc:.4f} at threshold {best_threshold:.2f}"
    )

    # Save artifacts.
    # Always save the inner network state dict so the router can load it directly
    # into an equivalent raw `nn.Linear` or `nn.Sequential` architecture.
    model_path = output_dir / "classifier_head.pt"
    torch.save(model.net.state_dict(), model_path)

    config = {
        "input_dim": embeddings.shape[1],
        "num_classes": len(routes),
        "hidden_dim": hidden_dim,
        "routes": routes,
        "route_to_idx": route_to_idx,
        "idx_to_route": idx_to_route,
        "best_val_accuracy": float(best_val_acc),
        "knn_val_accuracy": knn_val_acc,
        "best_combined_val_accuracy": best_combined_acc,
        "threshold": best_threshold,
        "hyperparameters": {
            "epochs": args.epochs,
            "batch_size": args.batch_size,
            "lr": args.lr,
            "weight_decay": args.weight_decay,
            "patience": args.patience,
            "val_size": args.val_size,
            "seed": args.seed,
        },
    }
    config_path = output_dir / "classifier_head_config.json"
    config_path.write_text(json.dumps(config, indent=2))

    print(f"\nSaved classifier head to {model_path}")
    print(f"Saved config to {config_path}")


if __name__ == "__main__":
    main()
