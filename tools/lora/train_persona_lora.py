#!/usr/bin/env python3
"""Train a persona LoRA adapter for a Local Lucy base model.

Usage:
    python3 tools/lora/train_persona_lora.py \
        --dataset data/lora/datasets/michael.jsonl \
        --base-model meta-llama/Llama-3.1-8B-Instruct \
        --base-tag local-lucy-llama31 \
        --persona michael

The adapter is saved to models/lora/<base-tag>/<persona>/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "models" / "lora"


# Map selectable Ollama tags to their HuggingFace base model defaults.
BASE_TAG_TO_HF_MODEL: dict[str, str] = {
    # Unsloth mirror is public; the official meta-llama repo is gated.
    "local-lucy-llama31": "unsloth/Meta-Llama-3.1-8B-Instruct",
    "local-lucy-stable": "unsloth/Meta-Llama-3.1-8B-Instruct",
    "local-lucy": "Qwen/Qwen3-14B",
    "local-lucy-fast": "Qwen/Qwen3-14B",
    "local-lucy-qwen3": "Qwen/Qwen3-14B",
    "local-lucy-mistral": "mistralai/Mistral-Nemo-Instruct-2407",
}


# Model-specific training defaults for RTX 3060 12 GB.
MODEL_CONFIG_OVERRIDES: dict[str, dict[str, object]] = {
    "local-lucy-llama31": {
        "rank": 16,
        "alpha": 32,
        "max_seq_length": 2048,
        "target_modules": "all-linear",
    },
    "local-lucy-stable": {
        "rank": 16,
        "alpha": 32,
        "max_seq_length": 2048,
        "target_modules": "all-linear",
    },
    # 14B qwen3 needs a smaller rank/seq budget to fit on RTX 3060 12 GB.
    "local-lucy": {
        "rank": 4,
        "alpha": 8,
        "max_seq_length": 512,
        "target_modules": ["q_proj", "v_proj"],
    },
    "local-lucy-fast": {
        "rank": 4,
        "alpha": 8,
        "max_seq_length": 512,
        "target_modules": ["q_proj", "v_proj"],
    },
    "local-lucy-qwen3": {
        "rank": 4,
        "alpha": 8,
        "max_seq_length": 512,
        "target_modules": ["q_proj", "v_proj"],
    },
    # 12B Mistral-Nemo needs a conservative budget to fit on RTX 3060 12 GB.
    "local-lucy-mistral": {
        "rank": 4,
        "alpha": 8,
        "max_seq_length": 512,
        "target_modules": ["q_proj", "v_proj"],
    },
}


def format_alpaca(example: dict) -> dict[str, str]:
    """Format a dataset record into Alpaca-style text."""
    instruction = example.get("instruction", "")
    context = example.get("context") or ""
    response = example.get("response", "")
    if context:
        text = (
            f"### Instruction:\n{instruction}\n\n### Input:\n{context}\n\n### Response:\n{response}"
        )
    else:
        text = f"### Instruction:\n{instruction}\n\n### Response:\n{response}"
    return {"text": text}


def load_dataset(path: Path) -> Dataset:
    """Load a JSONL dataset."""
    records = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return Dataset.from_list(records)


def resolve_base_model(base_tag: str, override: str | None) -> str:
    """Return the HuggingFace model id for a base tag."""
    if override:
        return override
    if base_tag not in BASE_TAG_TO_HF_MODEL:
        raise ValueError(
            f"Unknown base tag: {base_tag}. Known tags: {list(BASE_TAG_TO_HF_MODEL.keys())}. "
            "Use --base-model to specify a HuggingFace id or local path."
        )
    return BASE_TAG_TO_HF_MODEL[base_tag]


def _parse_target_modules(value: str | None) -> list[str] | str:
    """Return a list of module names, the string 'all-linear', or None."""
    if value is None:
        return "all-linear"
    if value == "all-linear":
        return "all-linear"
    return [m.strip() for m in value.split(",") if m.strip()]


def get_model_config(base_tag: str, args: argparse.Namespace) -> dict[str, object]:
    """Merge CLI args with model-specific defaults."""
    defaults = MODEL_CONFIG_OVERRIDES.get(base_tag, {})
    return {
        "rank": args.rank if args.rank is not None else defaults.get("rank", 8),
        "alpha": args.alpha if args.alpha is not None else defaults.get("alpha", 16),
        "max_seq_length": args.max_seq_length
        if args.max_seq_length is not None
        else defaults.get("max_seq_length", 1024),
        "target_modules": _parse_target_modules(args.target_modules)
        if args.target_modules is not None
        else defaults.get("target_modules", "all-linear"),
    }


def train(
    dataset_path: Path,
    base_model: str,
    base_tag: str,
    persona: str,
    output_root: Path,
    epochs: int,
    batch_size: int,
    grad_accum: int,
    learning_rate: float,
    rank: int,
    alpha: int,
    max_seq_length: int,
    target_modules: str,
    seed: int,
) -> Path:
    """Train and save a persona LoRA adapter."""
    output_dir = output_root / base_tag / persona
    output_dir.mkdir(parents=True, exist_ok=True)

    # Reproducibility
    torch.manual_seed(seed)

    # Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
        tokenizer.pad_token_id = tokenizer.eos_token_id

    # 4-bit quantization config
    compute_dtype = (
        torch.bfloat16
        if torch.cuda.is_available() and torch.cuda.is_bf16_supported()
        else torch.float16
    )
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=True,
    )

    # Model
    print(f"Loading base model: {base_model}")
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        dtype=compute_dtype,
        attn_implementation="eager",  # safest default for QLoRA across architectures
    )
    model = prepare_model_for_kbit_training(model)

    # LoRA config
    lora_config = LoraConfig(
        r=rank,
        lora_alpha=alpha,
        target_modules=target_modules,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Dataset
    print(f"Loading dataset: {dataset_path}")
    dataset = load_dataset(dataset_path)
    dataset = dataset.map(format_alpaca, remove_columns=dataset.column_names)

    # Training config
    training_args = SFTConfig(
        output_dir=str(output_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        logging_steps=10,
        save_strategy="epoch",
        save_total_limit=2,
        bf16=compute_dtype == torch.bfloat16,
        fp16=compute_dtype == torch.float16,
        report_to="none",
        max_length=max_seq_length,
        seed=seed,
        dataloader_num_workers=0,  # safer for small datasets
        gradient_checkpointing=True,
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    print("Starting training ...")
    trainer.train()

    print(f"Saving adapter to {output_dir}")
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    # Save a small metadata file for traceability
    metadata = {
        "base_model": base_model,
        "base_tag": base_tag,
        "persona": persona,
        "rank": rank,
        "alpha": alpha,
        "max_seq_length": max_seq_length,
        "epochs": epochs,
        "batch_size": batch_size,
        "gradient_accumulation_steps": grad_accum,
        "learning_rate": learning_rate,
        "seed": seed,
    }
    with (output_dir / "training_metadata.json").open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    return output_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Train a persona LoRA adapter for Local Lucy")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to persona JSONL dataset")
    parser.add_argument(
        "--base-tag", type=str, required=True, help="Local Ollama base tag, e.g. local-lucy-llama31"
    )
    parser.add_argument(
        "--base-model",
        type=str,
        default=None,
        help="Override HuggingFace base model id or local path",
    )
    parser.add_argument(
        "--persona", type=str, required=True, choices=("michael",), help="Persona to train"
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Root directory for adapter output",
    )
    parser.add_argument("--epochs", type=int, default=4, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=1, help="Per-device train batch size")
    parser.add_argument("--grad-accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--learning-rate", type=float, default=2e-4, help="Learning rate")
    parser.add_argument(
        "--rank", type=int, default=None, help="LoRA rank (default: model-specific)"
    )
    parser.add_argument(
        "--alpha", type=int, default=None, help="LoRA alpha (default: model-specific)"
    )
    parser.add_argument(
        "--max-seq-length",
        type=int,
        default=None,
        help="Max sequence length (default: model-specific)",
    )
    parser.add_argument(
        "--target-modules", type=str, default=None, help="LoRA target modules (default: all-linear)"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"ERROR: Dataset not found: {args.dataset}", file=sys.stderr)
        return 1

    base_model = resolve_base_model(args.base_tag, args.base_model)
    config = get_model_config(args.base_tag, args)

    print(f"Training persona '{args.persona}' for base tag '{args.base_tag}'")
    print(f"Base model: {base_model}")
    print(f"Config: {config}")

    try:
        output = train(
            dataset_path=args.dataset,
            base_model=base_model,
            base_tag=args.base_tag,
            persona=args.persona,
            output_root=args.output_root,
            epochs=args.epochs,
            batch_size=args.batch_size,
            grad_accum=args.grad_accum,
            learning_rate=args.learning_rate,
            rank=config["rank"],
            alpha=config["alpha"],
            max_seq_length=config["max_seq_length"],
            target_modules=config["target_modules"],
            seed=args.seed,
        )
    except torch.OutOfMemoryError as exc:
        print(f"\nOOM_ERROR: {exc}", file=sys.stderr)
        print(
            f"The base model '{base_model}' does not fit in GPU memory with the current QLoRA config. "
            "Consider a smaller model, lower rank/sequence length, or a GPU with more VRAM.",
            file=sys.stderr,
        )
        return 77

    print(f"\nTraining complete. Adapter saved to: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
