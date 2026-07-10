#!/usr/bin/env python3
"""
Test llama3.1 with explicit persistent memory context.
The key question: will it use personal facts when provided, or still refuse?
"""

import json
import subprocess
import time

MODEL = "local-lucy-llama31"

MEMORY_CONTEXT = """--- Persistent Memory (approved facts) ---
The user has a son named Thomas who is 12 years old.
The user has a wife named Sarah.
The user has a dog named Max, a golden retriever.
-------------------------------------------"""

QUERIES = [
    "Do I have any kids?",
    "What is my wife's name?",
    "Tell me about my dog.",
]


def ollama_generate(
    model: str, prompt: str, system: str = "", timeout: int = 60
) -> tuple[str, float]:
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"num_predict": 128},
        }
    )
    start = time.perf_counter()
    result = subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            "http://localhost:11434/api/generate",
            "-H",
            "Content-Type: application/json",
            "-d",
            payload,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    elapsed = time.perf_counter() - start
    try:
        data = json.loads(result.stdout)
        return data.get("response", "").strip(), elapsed
    except Exception as e:
        return f"ERROR: {e}\nRAW: {result.stdout[:200]}", elapsed


def main():
    print("Testing llama3.1:8b WITH persistent memory context")
    print("=" * 60)
    for query in QUERIES:
        text, elapsed = ollama_generate(MODEL, query, system=MEMORY_CONTEXT)
        print(f"\nQ: {query}")
        print(f"  ({elapsed:.2f}s) → {text}")


if __name__ == "__main__":
    main()
