#!/usr/bin/env python3
"""Autonomous ModernBERT router pipeline — data generation, training, embedding router, cutover."""

import json
import random
import sys
from pathlib import Path

random.seed(42)

# Step 1: Generate comprehensive synthetic dataset
print("=" * 60)
print("STEP 1: Generating balanced synthetic training data")
print("=" * 60)

sys.path.insert(0, str(Path(__file__).parent))
from dataset import generate_synthetic_examples, load_historical_data, balance_dataset, split_dataset

config = {
    "train_split": 0.7,
    "val_split": 0.15,
    "min_samples_per_class": 200,
}

historical = load_historical_data(Path(__file__).parent / "data" / "raw" / "historical_routes.jsonl")
print(f"Historical examples: {len(historical)}")

balanced = balance_dataset(historical, config["min_samples_per_class"])
print(f"Balanced dataset: {len(balanced)}")

splits = split_dataset(balanced, config["train_split"], config["val_split"])

# Write splits
for split_name, data in splits.items():
    path = Path(__file__).parent / "data" / "processed" / f"{split_name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for ex in data:
            f.write(json.dumps(ex) + "\n")
    print(f"Wrote {len(data)} examples to {path}")

print("\nSTEP 1 complete.")
