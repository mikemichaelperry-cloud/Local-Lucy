#!/usr/bin/env python3
"""Convert trained Safetensors LoRA adapters to GGUF for Ollama compatibility.

Older Ollama versions (e.g., 0.14.x) do not load Safetensors adapters directly.
This script wraps llama.cpp's convert_lora_to_gguf.py to produce adapter.gguf
files next to each adapter_model.safetensors.

Usage:
    python3 tools/lora/convert_adapters_to_gguf.py

Requires:
    - llama.cpp repository with convert_lora_to_gguf.py
    - pip install -r /path/to/llama.cpp/requirements/requirements-convert_lora_to_gguf.txt

Environment:
    LLAMA_CPP_ROOT  path to llama.cpp checkout (default: /tmp/llama.cpp)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LORA_ROOT = PROJECT_ROOT / "models" / "lora"
DEFAULT_LLAMA_CPP_ROOT = Path("/tmp/llama.cpp")


def find_adapter_dirs(root: Path) -> list[Path]:
    """Return directories containing adapter_model.safetensors."""
    dirs: list[Path] = []
    if not root.exists():
        return dirs
    for path in root.rglob("adapter_model.safetensors"):
        dirs.append(path.parent)
    return dirs


def convert_adapter(adapter_dir: Path, llama_cpp_root: Path, outtype: str, hf_token: str | None) -> None:
    """Convert a single adapter directory to GGUF."""
    adapter_file = adapter_dir / "adapter_model.safetensors"
    if not adapter_file.exists():
        print(f"[skip] No adapter weights in {adapter_dir}")
        return

    converter = llama_cpp_root / "convert_lora_to_gguf.py"
    if not converter.exists():
        raise FileNotFoundError(f"Converter not found: {converter}")

    outfile = adapter_dir / "adapter.gguf"
    cmd = [
        sys.executable,
        str(converter),
        "--outfile",
        str(outfile),
        "--outtype",
        outtype,
        str(adapter_dir),
    ]

    env = os.environ.copy()
    if hf_token:
        env["HF_TOKEN"] = hf_token

    print(f"Converting {adapter_dir} -> {outfile}")
    result = subprocess.run(cmd, check=False, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(f"ERROR converting {adapter_dir}:")
        print(result.stderr)
        raise RuntimeError(f"Conversion failed for {adapter_dir}")
    print(f"OK: {outfile}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert LoRA adapters to GGUF")
    parser.add_argument("--llama-cpp-root", type=Path, default=DEFAULT_LLAMA_CPP_ROOT, help="Path to llama.cpp checkout")
    parser.add_argument("--outtype", type=str, default="f16", choices=["f32", "f16", "bf16", "q8_0", "auto"], help="GGUF output type")
    parser.add_argument("--adapter-dir", type=Path, default=None, help="Convert a single adapter directory instead of all")
    parser.add_argument("--hf-token", type=str, default=os.environ.get("HF_TOKEN"), help="HuggingFace read token")
    args = parser.parse_args()

    if args.adapter_dir:
        adapter_dirs = [args.adapter_dir]
    else:
        adapter_dirs = find_adapter_dirs(LORA_ROOT)

    if not adapter_dirs:
        print(f"No adapters found under {LORA_ROOT}")
        return 0

    for adapter_dir in adapter_dirs:
        try:
            convert_adapter(adapter_dir, args.llama_cpp_root, args.outtype, args.hf_token)
        except Exception as exc:
            print(f"FAILED: {adapter_dir}: {exc}")
            return 1

    print(f"\nConverted {len(adapter_dirs)} adapter(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
