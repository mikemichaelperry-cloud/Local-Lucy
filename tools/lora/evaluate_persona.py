#!/usr/bin/env python3
"""Evaluate persona-tagged models against golden test cases.

Usage (LoRA adapter path):
    python3 tools/lora/evaluate_persona.py --model local-lucy-llama31-michael

Usage (prompt-level fallback path):
    python3 tools/lora/evaluate_persona.py --model local-lucy-llama31 --prompt-persona michael

Use --persona to filter cases, e.g. --persona michael.
Use --json for machine-readable output.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_CASES_PATH = PROJECT_ROOT / "tests" / "golden_persona_cases.jsonl"
PERSONA_DIR = PROJECT_ROOT / "config" / "personas"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


def load_persona_fragment(persona_name: str) -> str:
    """Load the prompt-level persona fragment used by local_answer.py.

    Returns an empty string if the fragment file is missing.
    """
    path = PERSONA_DIR / f"{persona_name.lower()}.txt"
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, FileNotFoundError):
        return ""


def model_has_persona_suffix(model: str, persona: str) -> bool:
    """Return True if the Ollama model tag ends with the persona suffix."""
    return model.lower().endswith(f"-{persona.lower()}")


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def query_ollama(model: str, prompt: str, ollama_url: str, system: str | None = None) -> str:
    """Send a single prompt to Ollama and return the response text."""
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0, "seed": 42},
    }
    if system:
        body["system"] = system
    req = urllib.request.Request(
        ollama_url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "").strip()


def run_case(
    case: dict,
    model: str,
    ollama_url: str,
    system: str | None = None,
    *,
    path_label: str = "LoRA",
) -> dict:
    """Run a single golden case and return results."""
    response = query_ollama(model, case["query"], ollama_url, system=system)
    failed = []
    for check in case.get("checks", []):
        value = check["value"]
        text = response.lower().replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
        if check["type"] == "contains":
            if value.lower() not in text:
                failed.append(f"should contain '{value}'")
        elif check["type"] == "not_contains":
            if value.lower() in text:
                failed.append(f"should NOT contain '{value}'")
        elif check["type"] == "contains_any":
            candidates = value if isinstance(value, list) else [value]
            if not any(c.lower() in text for c in candidates):
                failed.append(f"should contain any of {candidates}")
        elif check["type"] == "not_contains_any":
            candidates = value if isinstance(value, list) else [value]
            for c in candidates:
                if c.lower() in text:
                    failed.append(f"should NOT contain '{c}'")
                    break
    return {
        "query": case["query"],
        "expected_persona": case["persona"],
        "path": path_label,
        "response": response,
        "passed": not failed,
        "failures": failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Local Lucy persona models against golden cases",
        epilog=(
            "Examples:\n"
            "  # LoRA adapter path (persona baked into the model tag)\n"
            "  python3 tools/lora/evaluate_persona.py --model local-lucy-llama31-michael\n\n"
            "  # Prompt-level fallback path (base model + injected persona fragment)\n"
            "  python3 tools/lora/evaluate_persona.py --model local-lucy-llama31 --prompt-persona michael\n\n"
            "  # Machine-readable report\n"
            "  python3 tools/lora/evaluate_persona.py --model local-lucy-llama31 --prompt-persona michael --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--model", type=str, required=True, help="Ollama model tag to test")
    parser.add_argument("--persona", type=str, default=None, help="Filter cases by persona (michael)")
    parser.add_argument("--prompt-persona", type=str, default=None, help="Inject the prompt-level persona fragment for this name (tests fallback path)")
    parser.add_argument("--cases", type=Path, default=GOLDEN_CASES_PATH, help="Path to golden cases JSONL")
    parser.add_argument("--ollama-url", type=str, default=DEFAULT_OLLAMA_URL, help="Ollama API URL")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of human text")
    parser.add_argument("--min-pass-rate", type=float, default=60.0, help="Minimum pass rate (%%) to exit with code 0 (default: 60)")
    args = parser.parse_args()

    if not args.cases.exists():
        print(f"ERROR: Cases file not found: {args.cases}", file=sys.stderr)
        return 1

    system_prompt: str | None = None
    if args.prompt_persona:
        fragment = load_persona_fragment(args.prompt_persona)
        if not fragment:
            print(
                f"ERROR: Prompt-level persona fragment not found: {PERSONA_DIR / f'{args.prompt_persona.lower()}.txt'}",
                file=sys.stderr,
            )
            return 1
        system_prompt = fragment

    cases = load_cases(args.cases)
    if args.persona:
        cases = [c for c in cases if c.get("persona") == args.persona]

    if not cases:
        print("No cases to evaluate.")
        return 0

    if args.prompt_persona:
        path_label = f"prompt-level ({args.prompt_persona})"
    elif args.persona and model_has_persona_suffix(args.model, args.persona):
        path_label = f"LoRA ({args.persona})"
    else:
        path_label = "base (no persona injection)"

    results = []
    for case in cases:
        if not args.json:
            print(f"\n[query] {case['query']}")
        result = run_case(
            case, args.model, args.ollama_url, system=system_prompt, path_label=path_label
        )
        results.append(result)
        if not args.json:
            print(f"[path] {result['path']}")
            print(f"[response] {result['response'][:200]}...")
            if result["passed"]:
                print("[PASS]")
            else:
                print(f"[FAIL] {', '.join(result['failures'])}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    per_persona: dict[str, list[dict]] = {}
    for r in results:
        per_persona.setdefault(r["expected_persona"], []).append(r)

    if args.json:
        report = {
            "model": args.model,
            "prompt_persona": args.prompt_persona,
            "passed": passed,
            "total": total,
            "pass_rate": round(100 * passed / total, 1) if total else 0.0,
            "all_passed": passed == total,
            "per_persona": {
                persona: {
                    "passed": sum(1 for x in items if x["passed"]),
                    "total": len(items),
                    "pass_rate": round(100 * sum(1 for x in items if x["passed"]) / len(items), 1) if items else 0.0,
                }
                for persona, items in sorted(per_persona.items())
            },
            "results": results,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"\n=== Overall: {passed}/{total} passed ({100 * passed / total:.1f}%) ===")
        for persona in sorted(per_persona):
            items = per_persona[persona]
            p = sum(1 for x in items if x["passed"])
            print(f"  {persona}: {p}/{len(items)} passed ({100 * p / len(items):.1f}%)")

    pass_rate = 100 * passed / total if total else 0.0
    return 0 if pass_rate >= args.min_pass_rate else 1


if __name__ == "__main__":
    sys.exit(main())
