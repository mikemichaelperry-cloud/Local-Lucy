#!/usr/bin/env python3
"""Run response_regression against all installed Ollama models and summarize."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_FILE = PROJECT_ROOT / "tools" / "router_py" / "test_response_regression.py"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434") + "/api/generate"


def list_installed_models() -> list[str]:
    result = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    models: list[str] = []
    if result.returncode != 0:
        print(f"ollama list failed: {result.stderr}", file=sys.stderr)
        return models
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def unload_model(model: str) -> None:
    """Ask Ollama to unload *model* from VRAM before loading the next model.

    Rapid model switching in the all-models regression can leave weights or
    KV-cache state resident, causing subsequent models to fail or run slowly.
    A generate call with keep_alive=0 forces immediate unload.
    """
    try:
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(
                {
                    "model": model,
                    "prompt": "",
                    "stream": False,
                    "keep_alive": 0,
                    "options": {"num_predict": 0},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        # Brief pause lets the Ollama runner release GPU memory before the
        # next model is requested.  5 s is enough for the runner to tear down
        # the previous context on an RTX 3060 / 12 GB system.
        time.sleep(5)
    except Exception as exc:
        print(f"  (unload warning: {exc})", file=sys.stderr, flush=True)


def run_for_model(model: str) -> tuple[int, int, str, list[str]]:
    env = os.environ.copy()
    env["LUCY_LOCAL_MODEL"] = model
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(TEST_FILE),
            "-v",
            "--tb=short",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
    )
    stdout = result.stdout + result.stderr
    passed = stdout.count(" PASSED")
    failed = stdout.count(" FAILED")
    # Pytest -v output contains per-test lines; capture the final summary.
    summary_line = ""
    for line in stdout.splitlines():
        line_stripped = line.strip()
        if "passed" in line_stripped or "failed" in line_stripped:
            summary_line = line_stripped

    # Collect failing case IDs so the summary is actionable.
    failing_cases: list[str] = []
    for line in stdout.splitlines():
        if "FAILED" in line and "test_response_regression[case" in line:
            # Line looks like:
            # tools/.../test_response_regression.py::test_response_regression[caseN] FAILED
            if "case" in line:
                start = line.find("case")
                end = line.find("]", start)
                if end > start:
                    failing_cases.append(line[start:end])

    return passed, failed, summary_line, failing_cases


def main() -> int:
    models = list_installed_models()
    if not models:
        print("No Ollama models found.")
        return 1

    print(f"Running response_regression against {len(models)} models...\n")
    results: list[tuple[str, str, str, list[str]]] = []
    for idx, model in enumerate(models):
        print(f"[{model}] ...", flush=True)
        passed, failed, summary, failing_cases = run_for_model(model)
        status = "PASS" if failed == 0 and passed > 0 else "FAIL"
        results.append((model, status, summary, failing_cases))
        detail = ""
        if failing_cases:
            detail = f" (failing: {', '.join(failing_cases)})"
        print(f"  {status}: {summary}{detail}\n", flush=True)

        # Unload before the next model to avoid cross-model contamination.
        if idx < len(models) - 1:
            unload_model(model)

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for model, status, summary, failing_cases in results:
        detail = ""
        if failing_cases:
            detail = f" (failing: {', '.join(failing_cases)})"
        print(f"{status:4} | {model:45} | {summary}{detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
