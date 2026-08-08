#!/usr/bin/env python3
"""STAGE_11 Llama shared scenario suite and Gemma parity runner.

Loads the shared scenario catalogue, runs each scenario sequentially through
Llama, compares route/outcome/response structure against the STAGE_09 Gemma
baseline, and writes a combined report.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_11_llama_scenario_suite.py
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
GEMMA_REPORT_PATH = ROOT / "qualification" / "results" / "stage_09_gemma_scenarios.json"
REPORT_PATH = ROOT / "qualification" / "results" / "stage_11_llama_scenarios.json"
MEMORY_BASELINE_FIXTURE_PATH = (
    ROOT / "qualification" / "fixtures" / "gemma_memory_baseline.json"
)


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
    unload_all_lucy_models()
    for m in _lucy_models_loaded():
        if not _wait_for_unload(m):
            raise RuntimeError(f"Could not unload {m} before Llama scenario suite")

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


def _load_suite() -> list[dict]:
    with open(SUITE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_gemma_report() -> dict[str, dict]:
    if not GEMMA_REPORT_PATH.exists():
        return {}
    with open(GEMMA_REPORT_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {r["scenario_id"]: r for r in data}


def _load_memory_baseline_fixture() -> dict[str, list[str]]:
    """Load the Gemma memory baseline key entities fixture.

    The fixture records the key entities that Gemma responses are expected to
    contain for each memory scenario.  Llama must contain the same entities to
    satisfy outcome parity.
    """
    if not MEMORY_BASELINE_FIXTURE_PATH.exists():
        return {}
    with open(MEMORY_BASELINE_FIXTURE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return {item["scenario_id"]: item.get("entities", []) for item in data.get("scenarios", [])}


def _set_state_model_to_llama() -> None:
    """Update current_state.json so the pipeline uses Llama exclusively."""
    from router_py.main import load_state_from_file

    state = load_state_from_file() or {}
    state["model"] = LLAMA_MODEL
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


def _adapt_concepts_for_llama(scenario: dict) -> tuple[list[str], list[str]]:
    """Return (required_concepts, forbidden_claims) adapted for Llama runs.

    The shared catalogue was authored for the Gemma smoke.  When the same
    scenario runs against Llama, model-specific concepts/claims must flip.
    """
    required = list(scenario.get("required_answer_concepts", []))
    forbidden = list(scenario.get("forbidden_answer_claims", []))
    if scenario.get("id") == "S09-GEM-011":
        required = ["Local Lucy", "llama"]
        forbidden = ["gemma", "gemma4", "OpenAI", "GPT"]
    return required, forbidden


def _run_scenario(
    scenario: dict,
    gemma_report: dict[str, dict],
    memory_baseline: dict[str, list[str]],
) -> dict:
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
            "required_concepts_found": [],
            "forbidden_claims_found": [],
            "passed": False,
            "notes": ["no outcomes produced"],
            "elapsed_s": round(elapsed, 2),
            "loaded_models": _lucy_models_loaded(),
            "parity": {
                "gemma_route": gemma_report.get(scenario["id"], {}).get("actual_route"),
                "route_matches": None,
                "gemma_outcome_code": gemma_report.get(scenario["id"], {}).get("outcome_code"),
                "outcome_matches": None,
                "gemma_entities": memory_baseline.get(scenario["id"], []),
                "entity_matches": None,
                "missing_entities": [],
            },
        }

    response_text = final_outcome.response_text or ""
    required_concepts, forbidden_claims = _adapt_concepts_for_llama(scenario)
    expected_route = scenario.get("expected_route")

    adapted = {**scenario, "required_answer_concepts": required_concepts,
               "forbidden_answer_claims": forbidden_claims}
    passed, notes = evaluate_response(adapted, final_outcome)

    loaded = _lucy_models_loaded()
    non_llama = [m for m in loaded if _is_non_llama_lucy_model(m)]
    if non_llama:
        notes.append(f"Non-Llama Lucy model(s) loaded: {non_llama}")
        passed = False

    if final_outcome.status != "completed":
        notes.append(f"status={final_outcome.status}, error={final_outcome.error_message}")
        passed = False

    # Parity comparison against Gemma baseline.
    gemma_result = gemma_report.get(scenario["id"], {})
    gemma_route = gemma_result.get("actual_route")
    route_parity = final_outcome.route == gemma_route if gemma_route else None
    outcome_parity = final_outcome.outcome_code == gemma_result.get("outcome_code") if gemma_result else None

    baseline_entities = memory_baseline.get(scenario["id"], [])
    missing_entities = [
        e for e in baseline_entities if e.lower() not in response_text.lower()
    ]
    entity_parity = None
    if is_memory and baseline_entities:
        entity_parity = not missing_entities
        if missing_entities:
            notes.append(f"missing Gemma baseline entities: {missing_entities}")
            passed = False

    return {
        "scenario_id": scenario["id"],
        "category": scenario["category"],
        "expected_route": expected_route,
        "actual_route": final_outcome.route,
        "status": final_outcome.status,
        "outcome_code": final_outcome.outcome_code,
        "response_len": len(response_text),
        "required_concepts_found": [c for c in required_concepts if c.lower() in response_text.lower()],
        "forbidden_claims_found": [c for c in forbidden_claims if c.lower() in response_text.lower()],
        "passed": passed,
        "notes": notes,
        "elapsed_s": round(elapsed, 2),
        "loaded_models": loaded,
        "parity": {
            "gemma_route": gemma_route,
            "route_matches": route_parity,
            "gemma_outcome_code": gemma_result.get("outcome_code"),
            "outcome_matches": outcome_parity,
            "gemma_entities": baseline_entities,
            "entity_matches": entity_parity,
            "missing_entities": missing_entities,
        },
    }


def main() -> int:
    assert_single_local_lucy_model("start")

    with tempfile.TemporaryDirectory(prefix="lucy-stage11-") as tmp:
        namespace_root = Path(tmp)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(namespace_root)
        os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
        os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
        os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
        os.environ.setdefault("LUCY_WARMUP_ENABLED", "0")
        os.environ.setdefault("LUCY_SESSION_MEMORY", "0")
        os.environ.setdefault("LUCY_MEMORY_SUMMARIZE_THRESHOLD", "0")
        os.environ.setdefault("LUCY_MEMORY_SUMMARIZE_MODEL", LLAMA_MODEL)
        os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
        os.environ.setdefault("LUCY_ENABLE_INTERNET", "1")
        os.environ["LUCY_LOCAL_MODEL"] = LLAMA_MODEL
        os.environ["LUCY_MODEL"] = LLAMA_MODEL
        _seed_synthetic_location_fact(namespace_root)
        _set_state_model_to_llama()

        suite = _load_suite()
        gemma_report = _load_gemma_report()
        memory_baseline = _load_memory_baseline_fixture()
        results: list[dict] = []
        passed = True

        try:
            _load_llama_exclusively()
            for scenario in suite:
                print(f"Running {scenario['id']}: {scenario['description']}")
                result = _run_scenario(scenario, gemma_report, memory_baseline)
                results.append(result)
                print(
                    f"  route={result['actual_route']} "
                    f"parity={result['parity']['route_matches']} "
                    f"passed={result['passed']} notes={result['notes']}"
                )
                if not result["passed"]:
                    passed = False
        finally:
            unload_all_lucy_models()

        route_matches = sum(1 for r in results if r["parity"]["route_matches"] is True)
        outcome_matches = sum(1 for r in results if r["parity"]["outcome_matches"] is True)
        entity_matches = sum(1 for r in results if r["parity"]["entity_matches"] is True)
        parity_available = sum(1 for r in results if r["parity"]["gemma_route"] is not None)
        entity_parity_available = sum(
            1 for r in results if r["parity"]["entity_matches"] is not None
        )

        summary = {
            "llama_model": LLAMA_MODEL,
            "gemma_model": GEMMA_MODEL,
            "total_scenarios": len(results),
            "passed_scenarios": sum(1 for r in results if r["passed"]),
            "failed_scenarios": sum(1 for r in results if not r["passed"]),
            "route_parity": f"{route_matches}/{parity_available}",
            "outcome_parity": f"{outcome_matches}/{parity_available}",
            "entity_parity": f"{entity_matches}/{entity_parity_available}",
            "results": results,
        }

        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

        assert_single_local_lucy_model("end")
        loaded_after = get_local_lucy_loaded_models()
        assert len(loaded_after) <= 1, loaded_after

        print(f"\nSummary: {summary['passed_scenarios']}/{summary['total_scenarios']} scenarios passed")
        print(f"Route parity with Gemma: {summary['route_parity']}")
        print(f"Outcome parity with Gemma: {summary['outcome_parity']}")
        print(f"Entity parity with Gemma: {summary['entity_parity']}")
        return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
