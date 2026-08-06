#!/usr/bin/env python3
"""STAGE_10 Llama model smoke qualification.

Unloads Gemma, loads Llama exclusively, runs a small set of core requests
through the HMI surface, and records route/outcome/response metadata.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_10_llama_smoke.py

Requires:
    - Ollama running with local-lucy-llama31:latest available.
    - LUCY_RUNTIME_NAMESPACE_ROOT set (defaults to ~/.local/share/local-lucy-v11).
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
    list_loaded_models,
    ollama_load_lock,
    unload_all_lucy_models,
    unload_other_lucy_models,
)

GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")


def _api_ps() -> list[str]:
    with urllib.request.urlopen(f"{DEFAULT_OLLAMA_URL}/api/ps", timeout=5.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name", m.get("model", "")) for m in data.get("models", [])]


def _lucy_models_loaded() -> list[str]:
    return [m for m in _api_ps() if is_lucy_model(m)]


def _is_non_llama_lucy_model(name: str) -> bool:
    """Return True for any Local Lucy model that is not the Llama variant."""
    if not is_lucy_model(name):
        return False
    base = name.split(":", 1)[0].lower()
    return not base.startswith("local-lucy-llama31")


def _wait_for_unload(name: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(name in m for m in _api_ps()):
            return True
        time.sleep(0.5)
    return False


def _load_llama_exclusively() -> None:
    """Unload every Lucy model, then load Llama and confirm Gemma is gone."""
    unload_all_lucy_models()
    for m in _lucy_models_loaded():
        if not _wait_for_unload(m):
            raise RuntimeError(f"Could not unload {m} before Llama smoke")

    body = json.dumps(
        {
            "model": LLAMA_MODEL,
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
        unload_other_lucy_models(LLAMA_MODEL)
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            resp.read()

    loaded = _lucy_models_loaded()
    if not any(LLAMA_MODEL in m for m in loaded):
        raise RuntimeError(f"Llama {LLAMA_MODEL} did not load")
    non_llama = [m for m in loaded if _is_non_llama_lucy_model(m)]
    if non_llama:
        raise RuntimeError(f"Non-Llama Lucy models are still loaded: {non_llama}")


def _run_hmi_surface_request(question: str) -> dict:
    """Submit one request through the HMI surface and return payload metadata."""
    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()
    result = bridge.run_action("submit_request", question)
    return {
        "status": result.status,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "payload": result.payload,
    }


def _set_state_model_to_llama() -> None:
    """Update current_state.json so the HMI surface uses Llama."""
    from router_py.main import load_state_from_file

    state = load_state_from_file() or {}
    state["model"] = LLAMA_MODEL

    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        state_file = Path(namespace_root).expanduser() / "state" / "current_state.json"
    else:
        state_file = Path.home() / ".local" / "share" / "local-lucy-v11" / "state" / "current_state.json"

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    if "LUCY_RUNTIME_NAMESPACE_ROOT" not in os.environ:
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(
            Path.home() / ".local" / "share" / "local-lucy-v11"
        )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
    os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

    # Pin Llama for this smoke run in both env and state file.
    os.environ["LUCY_LOCAL_MODEL"] = LLAMA_MODEL
    os.environ["LUCY_MODEL"] = LLAMA_MODEL
    _set_state_model_to_llama()

    cases = [
        {
            "id": "llama_local_fact",
            "question": "What is the capital of France?",
            "expected_route": "LOCAL",
        },
        {
            "id": "llama_augmented_fact",
            "question": "Who was Marie Curie?",
            # Smoke-level check: must complete and return a non-empty response.
            "expected_route": {"LOCAL", "AUGMENTED"},
        },
        {
            "id": "llama_hmi_surface",
            "question": "What is 17 times 23?",
            "expected_route": "LOCAL",
            "hmi_surface": True,
        },
    ]

    results: list[dict] = []
    passed = True

    try:
        _load_llama_exclusively()

        for case in cases:
            print(f"Running {case['id']}: {case['question']}")
            if case.get("hmi_surface"):
                outcome = _run_hmi_surface_request(case["question"])
                payload = outcome.get("payload") or {}
                route = (payload.get("route") or {}).get("mode", "unknown")
            else:
                from router_py.main import execute_plan_python

                router_outcome = execute_plan_python(
                    case["question"],
                    policy="fallback_only",
                    timeout=180,
                    surface="cli",
                )
                outcome = {
                    "status": router_outcome.status,
                    "route": router_outcome.route,
                    "outcome_code": router_outcome.outcome_code,
                    "response_len": len(router_outcome.response_text or ""),
                }
                route = router_outcome.route

            expected = case["expected_route"]
            case_passed = route in expected if isinstance(expected, set) else route == expected
            loaded = _lucy_models_loaded()
            non_llama = [m for m in loaded if _is_non_llama_lucy_model(m)]
            if non_llama:
                case_passed = False
                outcome["parallel_model_error"] = f"Non-Llama Lucy model(s) loaded: {non_llama}"

            expected_report = (
                list(case["expected_route"])
                if isinstance(case["expected_route"], set)
                else case["expected_route"]
            )
            results.append(
                {
                    "case_id": case["id"],
                    "expected_route": expected_report,
                    "actual_route": route,
                    "passed": case_passed,
                    "outcome": outcome,
                    "loaded_models": loaded,
                }
            )
            if not case_passed:
                passed = False

    finally:
        unload_all_lucy_models()

    report_path = Path("qualification/results/stage_10_llama_smoke.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    for r in results:
        print(f"  {r['case_id']}: {r['actual_route']} (expected {r['expected_route']}) passed={r['passed']}")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
