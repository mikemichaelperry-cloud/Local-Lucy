#!/usr/bin/env python3
"""
Quick comparison test: local-lucy-llama31 vs local-lucy (qwen3:14b)
Tests the user's core requirements: compliance, first-person, speed, accuracy.
"""

import json
import re
import subprocess
import time

MODELS = {
    "llama31": "local-lucy-llama31",
    "qwen3": "local-lucy",
}

QUERIES = [
    (
        "personal_basic",
        "Do I have any kids?",
        ["refuse", "apologize", "unable", "cannot", "privacy"],
    ),
    ("identity", "Who are you?", []),
    ("factual", "What is the capital of France?", []),
    ("math", "What is 7 times 8?", []),
    (
        "personal_family",
        "What do you know about my wife?",
        ["refuse", "apologize", "unable", "cannot", "privacy"],
    ),
    ("general", "Tell me one fact about World War 2.", []),
]


def ollama_generate(model: str, prompt: str, timeout: int = 60) -> tuple[str, float]:
    """Returns (response_text, elapsed_seconds)."""
    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
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


def unload_model(model: str):
    subprocess.run(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            "http://localhost:11434/api/generate",
            "-H",
            "Content-Type: application/json",
            "-d",
            json.dumps({"model": model, "prompt": "", "keep_alive": 0}),
        ],
        capture_output=True,
        timeout=30,
    )
    time.sleep(2)


def check_refusal(text: str, refusal_keywords: list[str]) -> bool:
    lower = text.lower()
    return any(kw in lower for kw in refusal_keywords) or len(text) < 10


def check_first_person(text: str) -> bool:
    sentences = re.split(r"[.!?\n]", text)
    for s in sentences:
        s = s.strip()
        if s and s.split()[0].lower() in ("i", "i'm", "i've", "i'd"):
            return True
    return False


def run_test(model_key: str, model_name: str, warm: bool = False):
    label = "warm" if warm else "cold"
    print(f"\n{'='*60}")
    print(f"Testing {model_key} ({label}) — {model_name}")
    print(f"{'='*60}")
    results = []
    for tag, query, refusal_keywords in QUERIES:
        text, elapsed = ollama_generate(model_name, query)
        refused = check_refusal(text, refusal_keywords) if refusal_keywords else False
        first_person = check_first_person(text) if tag != "identity" else None
        results.append(
            {
                "tag": tag,
                "query": query,
                "elapsed": elapsed,
                "refused": refused,
                "first_person": first_person,
                "text": text[:250],
            }
        )
        status = "REFUSED" if refused else "OK"
        fp = f" 1st-person={first_person}" if first_person is not None else ""
        print(f"  [{status}] {tag:20s} {elapsed:5.2f}s{fp}")
        print(f"       → {text[:120].replace(chr(10), ' ')}")
    return results


def main():
    all_results = {}
    for key, name in MODELS.items():
        # Cold run
        unload_model(name)
        all_results[f"{key}_cold"] = run_test(key, name, warm=False)
        # Warm run
        all_results[f"{key}_warm"] = run_test(key, name, warm=True)
        unload_model(name)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for key in MODELS:
        cold = all_results[f"{key}_cold"]
        warm = all_results[f"{key}_warm"]
        cold_time = sum(r["elapsed"] for r in cold)
        warm_time = sum(r["elapsed"] for r in warm)
        refusals = sum(1 for r in cold + warm if r["refused"])
        first_person_hits = sum(1 for r in cold + warm if r["first_person"] is True)
        first_person_total = sum(1 for r in cold + warm if r["first_person"] is not None)
        print(f"\n{key}:")
        print(f"  Total cold time: {cold_time:.2f}s  |  Total warm time: {warm_time:.2f}s")
        print(
            f"  Refusals: {refusals}/12  |  First-person: {first_person_hits}/{first_person_total}"
        )


if __name__ == "__main__":
    main()
