#!/usr/bin/env python3
"""STAGE_13 Long-session model-switch qualification.

Exercises sequential model switches (Gemma -> Llama -> Gemma), verifying that
only one Local Lucy model is resident at any time and that requests complete
after each switch.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_13_model_switch.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from router_py.main import execute_plan_python
from router_py.ollama_cleanup import (
    is_lucy_model,
    ollama_load_lock,
    unload_all_lucy_models,
    unload_other_lucy_models,
)

GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
REPORT_PATH = ROOT / "qualification" / "results" / "stage_13_model_switch.json"


def _api_ps() -> list[str]:
    with urllib.request.urlopen(f"{DEFAULT_OLLAMA_URL}/api/ps", timeout=5.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name", m.get("model", "")) for m in data.get("models", [])]


def _lucy_models_loaded() -> list[str]:
    return [m for m in _api_ps() if is_lucy_model(m)]


def _is_other_lucy_model(name: str, keep_model: str) -> bool:
    if not is_lucy_model(name):
        return False
    base = name.split(":", 1)[0].lower()
    keep_base = keep_model.split(":", 1)[0].lower()
    return not base.startswith(keep_base)


def _wait_for_unload(name: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(name in m for m in _api_ps()):
            return True
        time.sleep(0.5)
    return False


def _load_model_exclusively(model: str) -> None:
    unload_all_lucy_models()
    for m in _lucy_models_loaded():
        if not _wait_for_unload(m):
            raise RuntimeError(f"Could not unload {m} before loading {model}")

    body = json.dumps(
        {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": "5m",
            "options": {"num_predict": 0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{DEFAULT_OLLAMA_URL}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with ollama_load_lock():
        unload_other_lucy_models(model)
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            resp.read()

    loaded = _lucy_models_loaded()
    if not any(model in m for m in loaded):
        raise RuntimeError(f"{model} did not load")
    others = [m for m in loaded if _is_other_lucy_model(m, model)]
    if others:
        raise RuntimeError(f"Other Local Lucy models loaded alongside {model}: {others}")


def _set_state_model(model: str) -> None:
    from router_py.main import load_state_from_file

    state = load_state_from_file() or {}
    state["model"] = model
    state["memory"] = "off"
    state["conversation"] = "off"

    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        state_file = Path(namespace_root).expanduser() / "state" / "current_state.json"
    else:
        state_file = Path.home() / ".local" / "share" / "local-lucy-v11" / "state" / "current_state.json"

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _run_step(model: str, question: str) -> dict:
    t0 = time.time()
    outcome = execute_plan_python(
        question,
        policy="fallback_only",
        timeout=180,
        surface="cli",
    )
    elapsed = time.time() - t0
    loaded = _lucy_models_loaded()
    others = [m for m in loaded if _is_other_lucy_model(m, model)]
    passed = outcome.status == "completed" and not others and any(model in m for m in loaded)
    return {
        "model": model,
        "question": question,
        "route": outcome.route,
        "status": outcome.status,
        "outcome_code": outcome.outcome_code,
        "response_len": len(outcome.response_text or ""),
        "loaded_models": loaded,
        "elapsed_s": round(elapsed, 2),
        "passed": passed,
        "notes": [] if passed else [f"others={others}"] if others else [f"status={outcome.status}"],
    }


def main() -> int:
    if "LUCY_RUNTIME_NAMESPACE_ROOT" not in os.environ:
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(
            Path.home() / ".local" / "share" / "local-lucy-v11"
        )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
    os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
    os.environ.setdefault("LUCY_WARMUP_ENABLED", "0")
    os.environ.setdefault("LUCY_SESSION_MEMORY", "0")

    steps = [
        (GEMMA_MODEL, "What is the capital of France?"),
        (LLAMA_MODEL, "What is 17 times 23?"),
        (GEMMA_MODEL, "Who was Marie Curie?"),
    ]

    results: list[dict] = []
    passed = True

    try:
        for model, question in steps:
            print(f"Switching to {model} ...")
            _load_model_exclusively(model)
            os.environ["LUCY_LOCAL_MODEL"] = model
            os.environ["LUCY_MODEL"] = model
            _set_state_model(model)

            print(f"Running on {model}: {question}")
            result = _run_step(model, question)
            results.append(result)
            print(f"  route={result['route']} passed={result['passed']} loaded={result['loaded_models']}")
            if not result["passed"]:
                passed = False
    finally:
        unload_all_lucy_models()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\nSummary: {passed_count}/{len(results)} switch steps passed")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
