#!/usr/bin/env python3
"""Generate persona-tagged Ollama Modelfiles for Local Lucy.

Usage:
    python3 tools/lora/build_modelfiles.py

Outputs Modelfiles under config/ for each selectable base model + persona.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
PERSONA_DIR = CONFIG_DIR / "personas"
LORA_ROOT = PROJECT_ROOT / "models" / "lora"

SELECTABLE_TAGS = [
    "local-lucy-llama31",
]

PERSONAS = ["michael"]


def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()


def build_modelfile(base_tag: str, persona: str) -> str:
    """Return the contents of a persona Modelfile."""
    system_prompt = read_text(CONFIG_DIR / "system_prompt.txt")

    # GGUF adapter path relative to the config/ directory.
    adapter_rel_path = f"../models/lora/{base_tag}/{persona}/adapter.gguf"

    # The persona fragment is still injected at runtime by local_answer.py for
    # both base-model fallback and LoRA-tagged models, so only the shared
    # system prompt is baked into the Modelfile. This avoids double-injection.
    lines = [
        f"FROM {base_tag}",
        "",
        f"ADAPTER {adapter_rel_path}",
        "",
        'SYSTEM """',
        system_prompt,
        '"""',
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Local Lucy persona Modelfiles")
    parser.add_argument("--base-tags", nargs="+", default=SELECTABLE_TAGS, help="Base Ollama tags")
    parser.add_argument("--personas", nargs="+", default=PERSONAS, help="Personas")
    args = parser.parse_args()

    for base_tag in args.base_tags:
        for persona in args.personas:
            content = build_modelfile(base_tag, persona)
            filename = f"Modelfile.{base_tag}-{persona}"
            out_path = CONFIG_DIR / filename
            with out_path.open("w", encoding="utf-8") as f:
                f.write(content)
            print(f"Wrote {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
