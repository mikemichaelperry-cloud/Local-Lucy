#!/usr/bin/env python3
"""Dataset loading, synthetic generation, and tokenization for ModernBERT router."""

import json
import random
from pathlib import Path
from typing import Any

import yaml
from torch.utils.data import Dataset


# Synthetic template generation for class balance
SYNTHETIC_TEMPLATES = {
    "background_overview": [
        "what is {topic}",
        "explain {topic}",
        "how does {topic} work",
        "overview of {topic}",
        "tell me about {topic}",
        "introduction to {topic}",
    ],
    "current_evidence": [
        "what is the latest on {topic}",
        "current status of {topic}",
        "recent developments in {topic}",
        "news about {topic}",
        "evidence for {claim}",
        "what do we know about {topic} today",
    ],
    "clarification": [
        "what",
        "how",
        "why",
        "when",
        "where",
        "explain",
    ],
    "technical_explanation": [
        "how do I {action}",
        "how does {topic} work technically",
        "explain the mechanism of {topic}",
        "what is the algorithm for {topic}",
        "debug this: {code_snippet}",
    ],
    "creative_writing": [
        "write a story about {topic}",
        "create a poem about {topic}",
        "imagine a world where {scenario}",
        "write a dialogue between {character_a} and {character_b}",
    ],
    "medical_inquiry": [
        "is {drug} safe for {condition}",
        "side effects of {drug}",
        "treatment for {condition}",
        "dosage of {drug} for {condition}",
        "can I take {drug_a} with {drug_b}",
    ],
    "news_request": [
        "latest news on {topic}",
        "headlines about {topic}",
        "what happened in {location} today",
        "breaking news {topic}",
    ],
    "time_query": [
        "what time is it in {location}",
        "current time in {location}",
        "time now {location}",
    ],
}

SLOT_VALUES = {
    "topic": [
        "Python", "quantum computing", "Palestine", "AI safety", "diabetes",
        "blockchain", "climate change", "nuclear fusion", "CRISPR", "dark matter",
        "machine learning", "cybersecurity", "space exploration", "renewable energy",
        "neuroscience", "economics", "philosophy", "history of Rome", "World War II",
        "the solar system", "DNA replication", "photosynthesis", "evolution",
    ],
    "claim": [
        "vaccines are safe", "climate change is real", "AI will replace jobs",
        "nuclear power is clean", "organic food is healthier",
    ],
    "action": [
        "install Python", "deploy a Docker container", "configure nginx",
        "set up a VPN", "create a React app", "train a neural network",
    ],
    "code_snippet": [
        "def foo(): pass", "Segmentation fault", "null pointer exception",
        "IndexError: list index out of range", "ModuleNotFoundError",
    ],
    "scenario": [
        "humans can fly", "water flows uphill", "AI governs the world",
        "dinosaurs never went extinct", "people live underwater",
    ],
    "character_a": ["Einstein", "Shakespeare", "Tesla", "Cleopatra", "Mozart"],
    "character_b": ["Newton", "Hemingway", "Edison", "Caesar", "Beethoven"],
    "drug": [
        "ibuprofen", "tadalafil", "sildenafil", "metformin", "insulin",
        "amoxicillin", "lisinopril", "atorvastatin", "omeprazole",
    ],
    "condition": [
        "diabetes", "hypertension", "depression", "asthma", "arthritis",
        "migraine", "anxiety", "high cholesterol", "GERD",
    ],
    "location": [
        "Tokyo", "New York", "London", "Sydney", "Berlin",
        "Paris", "Moscow", "Beijing", "Dubai", "Rio de Janeiro",
    ],
}


def fill_template(template: str) -> str:
    """Replace {slot} placeholders with random values."""
    result = template
    for slot, values in SLOT_VALUES.items():
        placeholder = f"{{{slot}}}"
        while placeholder in result:
            result = result.replace(placeholder, random.choice(values), 1)
    return result


def generate_synthetic_examples(intent_family: str, count: int) -> list[dict]:
    """Generate synthetic labeled examples for a given intent family."""
    templates = SYNTHETIC_TEMPLATES.get(intent_family, [])
    if not templates:
        return []
    
    examples = []
    for _ in range(count):
        template = random.choice(templates)
        query = fill_template(template)
        
        # Derive route and evidence from intent
        route = _intent_to_default_route(intent_family)
        evidence = "required" if intent_family == "medical_inquiry" else "not_required"
        policy = "none"
        
        examples.append({
            "query": query,
            "labels": {
                "intent_family": intent_family,
                "evidence_mode": evidence,
                "route": route,
                "policy_override": policy,
            },
            "metadata": {
                "source": "synthetic",
                "confidence": 1.0,
                "template": template,
            }
        })
    
    return examples


def _intent_to_default_route(intent: str) -> str:
    mapping = {
        "background_overview": "LOCAL",
        "current_evidence": "LOCAL_WITH_FALLBACK",
        "clarification": "CLARIFY",
        "technical_explanation": "LOCAL_WITH_FALLBACK",
        "creative_writing": "LOCAL",
        "medical_inquiry": "AUGMENTED",
        "news_request": "NEWS",
        "time_query": "TIME",
    }
    return mapping.get(intent, "LOCAL")


def load_historical_data(path: Path) -> list[dict]:
    """Load historical examples from JSONL."""
    if not path.exists():
        return []
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def balance_dataset(examples: list[dict], target_per_class: int) -> list[dict]:
    """Oversample rare classes with synthetic data to reach target count."""
    from collections import Counter
    
    intent_counts = Counter(ex["labels"]["intent_family"] for ex in examples)
    balanced = list(examples)
    
    for intent, count in intent_counts.items():
        if count < target_per_class:
            needed = target_per_class - count
            synthetic = generate_synthetic_examples(intent, needed)
            balanced.extend(synthetic)
            print(f"  Generated {needed} synthetic examples for {intent}")
    
    # Also generate for completely missing classes
    all_intents = set(SYNTHETIC_TEMPLATES.keys())
    present_intents = set(intent_counts.keys())
    for missing in all_intents - present_intents:
        needed = target_per_class
        synthetic = generate_synthetic_examples(missing, needed)
        balanced.extend(synthetic)
        print(f"  Generated {needed} synthetic examples for missing class {missing}")
    
    random.shuffle(balanced)
    return balanced


def split_dataset(examples: list[dict], train_ratio: float = 0.7, val_ratio: float = 0.15):
    """Split into train/val/test."""
    n = len(examples)
    n_train = int(n * train_ratio)
    n_val = int(n * val_ratio)
    
    return {
        "train": examples[:n_train],
        "val": examples[n_train:n_train + n_val],
        "test": examples[n_train + n_val:],
    }


class RouterDataset(Dataset):
    """PyTorch Dataset for tokenized router examples."""
    
    def __init__(self, examples: list[dict], tokenizer, max_length: int = 256):
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length
        
        # Build label index maps
        self.intent_to_idx = {name: i for i, name in enumerate([
            "background_overview", "current_evidence", "clarification",
            "technical_explanation", "creative_writing", "medical_inquiry",
            "news_request", "time_query"
        ])}
        self.evidence_to_idx = {name: i for i, name in enumerate(["not_required", "required", "uncertain"])}
        self.route_to_idx = {name: i for i, name in enumerate([
            "LOCAL", "LOCAL_WITH_FALLBACK", "AUGMENTED", "NEWS", "TIME", "CLARIFY"
        ])}
        self.policy_to_idx = {name: i for i, name in enumerate(["none", "disabled", "fallback_only", "force_augmented"])}
    
    def __len__(self):
        return len(self.examples)
    
    def __getitem__(self, idx):
        ex = self.examples[idx]
        query = ex["query"]
        labels = ex["labels"]
        
        encoding = self.tokenizer(
            query,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
            return_tensors="pt",
        )
        
        return {
            "input_ids": encoding["input_ids"].squeeze(0),
            "attention_mask": encoding["attention_mask"].squeeze(0),
            "labels": {
                "intent": self.intent_to_idx[labels["intent_family"]],
                "evidence": self.evidence_to_idx[labels["evidence_mode"]],
                "route": self.route_to_idx[labels["route"]],
                "policy": self.policy_to_idx[labels["policy_override"]],
            }
        }


def load_and_balance_data(config: dict[str, Any]) -> tuple[list[dict], list[dict], list[dict]]:
    """Load, balance, and split dataset."""
    data_dir = Path(__file__).parent / "data"
    
    # Load historical data
    historical = load_historical_data(data_dir / "raw" / "historical_routes.jsonl")
    print(f"Loaded {len(historical)} historical examples")
    
    # Balance with synthetic data
    target = config.get("min_samples_per_class", 50)
    balanced = balance_dataset(historical, target)
    print(f"Balanced dataset size: {len(balanced)}")
    
    # Split
    splits = split_dataset(balanced, config["train_split"], config["val_split"])
    print(f"Train: {len(splits['train'])}, Val: {len(splits['val'])}, Test: {len(splits['test'])}")
    
    return splits["train"], splits["val"], splits["test"]
