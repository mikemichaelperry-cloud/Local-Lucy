#!/usr/bin/env python3
"""Validate the Python environment can run QLoRA training for Local Lucy personas."""

from __future__ import annotations

import argparse
import importlib
import sys

REQUIRED_PACKAGES = [
    "torch",
    "transformers",
    "peft",
    "bitsandbytes",
    "trl",
    "datasets",
    "accelerate",
]

OPTIONAL_PACKAGES = ["unsloth"]


def check_imports() -> list[str]:
    """Return list of missing required packages."""
    missing: list[str] = []
    for pkg in REQUIRED_PACKAGES:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    return missing


def report_versions() -> None:
    """Print installed versions of relevant packages."""
    for pkg in REQUIRED_PACKAGES + OPTIONAL_PACKAGES:
        try:
            mod = importlib.import_module(pkg)
            version = getattr(mod, "__version__", "unknown")
            print(f"  {pkg}: {version}")
        except ImportError:
            print(f"  {pkg}: NOT INSTALLED")


def check_cuda() -> dict[str, object]:
    """Return CUDA/GPU status."""
    import torch

    info: dict[str, object] = {
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "pytorch_version": torch.__version__,
    }
    if torch.cuda.is_available():
        info["device_name"] = torch.cuda.get_device_name(0)
        info["total_memory_gb"] = torch.cuda.get_device_properties(0).total_memory / 1e9
        info["free_memory_gb"] = (
            torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_allocated(0)
        ) / 1e9
    return info


def run_smoke_test() -> None:
    """Run one training step on a tiny model to confirm the stack works."""
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    model_name = "sshleifer/tiny-gpt2"
    print(f"\nSmoke test: loading {model_name} ...")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
    )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
    )
    model = prepare_model_for_kbit_training(model)

    lora_config = LoraConfig(
        r=4,
        lora_alpha=8,
        target_modules=["c_attn"],  # tiny-gpt2 attention projection
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    # Minimal dataset
    examples = [
        {"text": "### Instruction:\nSay hello.\n\n### Response:\nHello."},
        {"text": "### Instruction:\nSay goodbye.\n\n### Response:\nGoodbye."},
    ]
    dataset = Dataset.from_list(examples)

    training_args = SFTConfig(
        output_dir="/tmp/lucy_lora_smoke",
        num_train_epochs=1,
        per_device_train_batch_size=1,
        max_steps=1,
        logging_steps=1,
        save_steps=1,
        bf16=torch.cuda.is_bf16_supported(),
        fp16=not torch.cuda.is_bf16_supported(),
        report_to="none",
        max_length=64,
    )

    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    print("Running one training step ...")
    trainer.train()
    print("Smoke test PASSED: one training step completed.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Local Lucy LoRA training environment")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Run a one-step training smoke test"
    )
    parser.add_argument(
        "--skip-smoke-if-no-gpu",
        action="store_true",
        help="Skip smoke test when no GPU is available",
    )
    args = parser.parse_args()

    print("=== Local Lucy LoRA Environment Check ===\n")

    print("Checking required packages ...")
    missing = check_imports()
    report_versions()
    if missing:
        print(f"\nERROR: Missing required packages: {', '.join(missing)}")
        print("Install with:")
        print("  cd ui-v10 && source .venv/bin/activate")
        print("  pip install peft bitsandbytes trl")
        return 1
    print("All required packages are installed.\n")

    print("Checking CUDA/GPU ...")
    cuda_info = check_cuda()
    for key, value in cuda_info.items():
        print(f"  {key}: {value}")
    if not cuda_info.get("cuda_available"):
        print("\nWARNING: CUDA is not available. Training will be extremely slow on CPU.")
        if args.skip_smoke_if_no_gpu:
            print("Skipping smoke test because --skip-smoke-if-no-gpu was set.")
            return 0
    print("")

    if args.smoke_test:
        try:
            run_smoke_test()
        except Exception as exc:
            print(f"\nERROR: Smoke test failed: {exc}")
            import traceback

            traceback.print_exc()
            return 1

    print("\nEnvironment check PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
