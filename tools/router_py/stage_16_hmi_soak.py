#!/usr/bin/env python3
"""STAGE_16 — HMI end-to-end stability and model-switch soak.

Runs a short sequence of real requests through the HMI surface
(RuntimeBridge.submit_request) with Gemma and Llama, verifying:
- every request returns a successful CommandResult,
- responses are non-empty,
- only one Local Lucy model is resident at any time,
- model switches complete cleanly.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_16_hmi_soak.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# Ensure app and tools are importable.
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui-v10"))
sys.path.insert(0, str(ROOT / "tools"))

from router_py.ollama_cleanup import (
    is_lucy_model,
    ollama_load_lock,
    unload_all_lucy_models,
    unload_other_lucy_models,
)

GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
REPORT_PATH = ROOT / "qualification" / "results" / "stage_16_hmi_soak.json"


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
            "keep_alive": "10m",
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
    state["memory"] = "on"
    state["conversation"] = "on"

    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        state_file = Path(namespace_root).expanduser() / "state" / "current_state.json"
    else:
        state_file = Path.home() / ".local" / "share" / "local-lucy-v11" / "state" / "current_state.json"

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _run_hmi_request(bridge, question: str) -> dict:
    t0 = time.time()
    result = bridge.run_action("submit_request", question)
    elapsed = time.time() - t0
    payload = result.payload or {}
    route = (payload.get("route") or {}).get("mode", "unknown")
    return {
        "status": result.status,
        "route": route,
        "stdout_len": len(result.stdout or ""),
        "stderr": result.stderr,
        "elapsed_s": round(elapsed, 2),
    }


def main() -> int:
    if "LUCY_RUNTIME_NAMESPACE_ROOT" not in os.environ:
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(
            Path.home() / ".local" / "share" / "local-lucy-v11"
        )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
    os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

    from app.services.runtime_bridge import RuntimeBridge

    scenarios = [
        (GEMMA_MODEL, [
            "What is the capital of France?",
            "What is 17 times 23?",
            "Write a haiku about the moon.",
        ]),
        (LLAMA_MODEL, [
            "Who was Marie Curie?",
            "What is the weather like in this area?",
            "Who are you and what model are you running?",
        ]),
    ]

    results: list[dict] = []
    passed = True

    try:
        for model, questions in scenarios:
            print(f"Soaking {model} ...")
            _load_model_exclusively(model)
            os.environ["LUCY_LOCAL_MODEL"] = model
            os.environ["LUCY_MODEL"] = model
            _set_state_model(model)

            bridge = RuntimeBridge()
            for question in questions:
                print(f"  HMI: {question[:60]}")
                outcome = _run_hmi_request(bridge, question)
                loaded = _lucy_models_loaded()
                others = [m for m in loaded if _is_other_lucy_model(m, model)]
                step_passed = (
                    outcome["status"] == "ok"
                    and outcome["stdout_len"] > 0
                    and not outcome["stderr"]
                    and not others
                )
                results.append({
                    "model": model,
                    "question": question,
                    "passed": step_passed,
                    "outcome": outcome,
                    "loaded_models": loaded,
                })
                print(f"    status={outcome['status']} route={outcome['route']} passed={step_passed} loaded={loaded}")
                if not step_passed:
                    passed = False
    finally:
        unload_all_lucy_models()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\nSummary: {passed_count}/{len(results)} HMI soak steps passed")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
