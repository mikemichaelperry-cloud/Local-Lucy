#!/usr/bin/env python3
"""STAGE_09 Gemma shared scenario suite runner.

Loads the shared scenario catalogue, runs each scenario sequentially through
Gemma, and writes a structured report.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_09_gemma_scenario_suite.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from router_py.main import execute_plan_python
from router_py.model_residency import (
    assert_single_local_lucy_model,
    get_local_lucy_loaded_models,
)
from router_py.ollama_cleanup import (
    is_lucy_model,
    ollama_load_lock,
    unload_all_lucy_models,
    unload_other_lucy_models,
)
from router_py.scenario_checks import evaluate_response

GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
SUITE_PATH = ROOT / "qualification" / "scenarios" / "shared_scenario_suite.json"
REPORT_PATH = ROOT / "qualification" / "results" / "stage_09_gemma_scenarios.json"


def _api_ps() -> list[str]:
    with urllib.request.urlopen(f"{DEFAULT_OLLAMA_URL}/api/ps", timeout=5.0) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name", m.get("model", "")) for m in data.get("models", [])]


def _lucy_models_loaded() -> list[str]:
    return [m for m in _api_ps() if is_lucy_model(m)]


def _is_non_gemma_lucy_model(name: str) -> bool:
    """Return True for any Local Lucy model that is not the Gemma variant."""
    if not is_lucy_model(name):
        return False
    base = name.split(":", 1)[0].lower()
    return not base.startswith("local-lucy-gemma4")


def _wait_for_unload(name: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not any(name in m for m in _api_ps()):
            return True
        time.sleep(0.5)
    return False


def _load_gemma_exclusively() -> None:
    unload_all_lucy_models()
    for m in _lucy_models_loaded():
        if not _wait_for_unload(m):
            raise RuntimeError(f"Could not unload {m} before Gemma scenario suite")

    body = json.dumps(
        {
            "model": GEMMA_MODEL,
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
        unload_other_lucy_models(GEMMA_MODEL)
        with urllib.request.urlopen(req, timeout=120.0) as resp:
            resp.read()

    loaded = _lucy_models_loaded()
    if not any(GEMMA_MODEL in m for m in loaded):
        raise RuntimeError(f"Gemma {GEMMA_MODEL} did not load")
    non_gemma = [m for m in loaded if _is_non_gemma_lucy_model(m)]
    if non_gemma:
        raise RuntimeError(f"Non-Gemma Lucy models are still loaded: {non_gemma}")


def _load_suite() -> list[dict]:
    with open(SUITE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _set_state_model_to_gemma() -> None:
    """Update current_state.json so the pipeline uses Gemma exclusively."""
    from router_py.main import load_state_from_file

    state = load_state_from_file() or {}
    state["model"] = GEMMA_MODEL
    # Keep conversation off to avoid side effects, but leave memory read on so
    # that location-anaphora scenarios can resolve against the seeded fact.
    # Evidence is enabled because restaurant/augmented scenarios expect it.
    state["memory"] = "on"
    state["conversation"] = "off"
    state["evidence"] = "on"

    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        state_file = Path(namespace_root).expanduser() / "state" / "current_state.json"
    else:
        state_file = Path.home() / ".local" / "share" / "local-lucy-v11" / "state" / "current_state.json"

    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _seed_synthetic_location_fact(namespace_root: Path) -> None:
    """Create an isolated memory DB and insert a synthetic location fact.

    The shared scenario S09-GEM-009 asks about weather "in this area".  To
    resolve the anaphora without depending on (or polluting) the user's
    persistent memory, we seed a single synthetic location fact in the
    temporary namespace used only for this suite run.
    """
    import tools.memory.memory_service as memory_service

    state_dir = namespace_root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "memory.db"
    os.environ["LUCY_MEMORY_DB_PATH"] = str(db_path)

    conn = sqlite3.connect(str(db_path))
    memory_service._ensure_schema(conn)
    conn.close()

    memory_service.store_persistent_fact(
        "The user lives in Springfield, Example County.",
        category="location",
    )


def _is_memory_scenario(scenario: dict) -> bool:
    """Return True when the scenario needs a multi-turn memory session."""
    return scenario.get("id", "").startswith("S09-MEM-") or "turns" in scenario


def _run_scenario(scenario: dict) -> dict:
    turns = scenario.get("turns", [scenario["user_request"]])
    if not turns:
        turns = [scenario["user_request"]]

    is_memory = _is_memory_scenario(scenario)
    previous_session_memory = os.environ.get("LUCY_SESSION_MEMORY")
    previous_session_id = os.environ.get("LUCY_SESSION_ID")

    if is_memory:
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        os.environ["LUCY_SESSION_ID"] = scenario["id"]
    else:
        os.environ["LUCY_SESSION_MEMORY"] = "0"
        os.environ.pop("LUCY_SESSION_ID", None)

    outcomes: list = []
    t0 = time.time()
    try:
        for turn_index, turn_request in enumerate(turns):
            outcome = execute_plan_python(
                turn_request,
                policy="fallback_only",
                timeout=180,
                surface="cli",
            )
            outcomes.append(outcome)
            if outcome.status != "completed" and turn_index < len(turns) - 1:
                break
    finally:
        if previous_session_memory is None:
            os.environ.pop("LUCY_SESSION_MEMORY", None)
        else:
            os.environ["LUCY_SESSION_MEMORY"] = previous_session_memory
        if previous_session_id is None:
            os.environ.pop("LUCY_SESSION_ID", None)
        else:
            os.environ["LUCY_SESSION_ID"] = previous_session_id

    elapsed = time.time() - t0
    final_outcome = outcomes[-1] if outcomes else None
    if final_outcome is None:
        return {
            "scenario_id": scenario["id"],
            "category": scenario["category"],
            "expected_route": scenario.get("expected_route"),
            "actual_route": "LOCAL",
            "status": "failed",
            "outcome_code": "no_outcome",
            "response_len": 0,
            "response_text": "",
            "turn_responses": [],
            "required_concepts_found": [],
            "forbidden_claims_found": [],
            "passed": False,
            "notes": ["no outcomes produced"],
            "elapsed_s": round(elapsed, 2),
            "loaded_models": _lucy_models_loaded(),
        }

    response_text = final_outcome.response_text or ""
    required_concepts = scenario.get("required_answer_concepts", [])
    forbidden_claims = scenario.get("forbidden_answer_claims", [])
    expected_route = scenario.get("expected_route")

    passed, notes = evaluate_response(scenario, final_outcome)

    loaded = _lucy_models_loaded()
    non_gemma = [m for m in loaded if _is_non_gemma_lucy_model(m)]
    if non_gemma:
        notes.append(f"Non-Gemma Lucy model(s) loaded: {non_gemma}")
        passed = False

    if final_outcome.status != "completed":
        notes.append(f"status={final_outcome.status}, error={final_outcome.error_message}")
        passed = False

    return {
        "scenario_id": scenario["id"],
        "category": scenario["category"],
        "expected_route": expected_route,
        "actual_route": final_outcome.route,
        "status": final_outcome.status,
        "outcome_code": final_outcome.outcome_code,
        "response_len": len(response_text),
        "response_text": response_text,
        "turn_responses": [o.response_text or "" for o in outcomes],
        "required_concepts_found": [c for c in required_concepts if c.lower() in response_text.lower()],
        "forbidden_claims_found": [c for c in forbidden_claims if c.lower() in response_text.lower()],
        "passed": passed,
        "notes": notes,
        "elapsed_s": round(elapsed, 2),
        "loaded_models": loaded,
    }


def main() -> int:
    assert_single_local_lucy_model("start")

    with tempfile.TemporaryDirectory(prefix="lucy-stage09-") as tmp:
        namespace_root = Path(tmp)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(namespace_root)
        os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
        os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
        os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
        os.environ.setdefault("LUCY_WARMUP_ENABLED", "0")
        os.environ.setdefault("LUCY_SESSION_MEMORY", "0")
        os.environ.setdefault("LUCY_MEMORY_SUMMARIZE_THRESHOLD", "0")
        os.environ.setdefault("LUCY_MEMORY_SUMMARIZE_MODEL", GEMMA_MODEL)
        os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
        os.environ.setdefault("LUCY_ENABLE_INTERNET", "1")
        os.environ["LUCY_LOCAL_MODEL"] = GEMMA_MODEL
        os.environ["LUCY_MODEL"] = GEMMA_MODEL
        _seed_synthetic_location_fact(namespace_root)
        _set_state_model_to_gemma()

        suite = _load_suite()
        results: list[dict] = []
        passed = True

        try:
            _load_gemma_exclusively()
            for scenario in suite:
                print(f"Running {scenario['id']}: {scenario['description']}")
                result = _run_scenario(scenario)
                results.append(result)
                print(f"  route={result['actual_route']} passed={result['passed']} notes={result['notes']}")
                if not result["passed"]:
                    passed = False
        finally:
            unload_all_lucy_models()

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

        assert_single_local_lucy_model("end")
        loaded_after = get_local_lucy_loaded_models()
        assert len(loaded_after) <= 1, loaded_after

        passed_count = sum(1 for r in results if r["passed"])
        print(f"\nSummary: {passed_count}/{len(results)} scenarios passed")
        return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
