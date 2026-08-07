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

GEMMA_MODEL = os.environ.get("LUCY_GEMMA_MODEL", "local-lucy-gemma4:latest")
LLAMA_MODEL = os.environ.get("LUCY_LLAMA_MODEL", "local-lucy-llama31:latest")
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")
REPORT_PATH = ROOT / "qualification" / "results" / "stage_13_model_switch.json"

# Fixed session ID for the cross-model memory continuity step.
MEMORY_SESSION_ID = "stage-13-memory-continuity"
MEMORY_STORY_PROMPT = "Tell me a short story about Oscar."
MEMORY_CONTINUE_PROMPT = "Continue the story."


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


def _set_state_model(model: str, memory: str = "off") -> None:
    from router_py.main import load_state_from_file

    state = load_state_from_file() or {}
    state["model"] = model
    state["memory"] = memory
    state["conversation"] = "off"

    namespace_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if namespace_root:
        state_file = Path(namespace_root).expanduser() / "state" / "current_state.json"
    else:
        state_file = (
            Path.home() / ".local" / "share" / "local-lucy-v11" / "state" / "current_state.json"
        )

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
        "response_text": outcome.response_text or "",
        "response_len": len(outcome.response_text or ""),
        "loaded_models": loaded,
        "elapsed_s": round(elapsed, 2),
        "passed": passed,
        "notes": [] if passed else [f"others={others}"] if others else [f"status={outcome.status}"],
    }


def _run_memory_continuation_step() -> dict:
    """Cross-model memory continuity: Gemma seeds a story, Llama continues it.

    Uses a fixed session ID so the chat-memory context persists across the
    model switch.  The step passes only if Llama's continuation references
    Oscar and appears to advance the prior narrative.
    """
    previous_session_memory = os.environ.get("LUCY_SESSION_MEMORY")
    previous_session_id = os.environ.get("LUCY_SESSION_ID")
    previous_memory_db = os.environ.get("LUCY_MEMORY_DB_PATH")
    previous_chat_memory_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE")
    tmp_dir = None

    try:
        # Isolate memory state in a fresh temp namespace so a previous run of
        # this stage (or any other session) cannot leak into the continuity test.
        tmp_dir = tempfile.TemporaryDirectory(prefix="lucy-stage13-memory-")
        tmp_path = Path(tmp_dir.name)
        os.environ["LUCY_SESSION_MEMORY"] = "1"
        os.environ["LUCY_SESSION_ID"] = MEMORY_SESSION_ID
        os.environ["LUCY_MEMORY_DB_PATH"] = str(tmp_path / "memory.db")
        os.environ["LUCY_RUNTIME_CHAT_MEMORY_FILE"] = str(
            tmp_path / "chat_session_memory.txt"
        )
        # Ensure the fallback chat file exists empty so prior sessions cannot leak in.
        (tmp_path / "chat_session_memory.txt").write_text("", encoding="utf-8")
        # Clear any prior turns for the fixed session ID from the fresh DB.
        try:
            from memory import memory_service

            memory_service.clear_session(MEMORY_SESSION_ID)
        except Exception:
            pass

        # Step 1: Gemma tells the story.
        print(f"Switching to {GEMMA_MODEL} for memory story seed ...")
        _load_model_exclusively(GEMMA_MODEL)
        os.environ["LUCY_LOCAL_MODEL"] = GEMMA_MODEL
        os.environ["LUCY_MODEL"] = GEMMA_MODEL
        _set_state_model(GEMMA_MODEL, memory="on")

        print(f"Running on {GEMMA_MODEL}: {MEMORY_STORY_PROMPT}")
        gemma_result = _run_step(GEMMA_MODEL, MEMORY_STORY_PROMPT)
        print(
            f"  route={gemma_result['route']} passed={gemma_result['passed']} "
            f"loaded={gemma_result['loaded_models']}"
        )

        # Step 2: Switch to Llama and continue the same session.
        print(f"Switching to {LLAMA_MODEL} for memory continuation ...")
        _load_model_exclusively(LLAMA_MODEL)
        os.environ["LUCY_LOCAL_MODEL"] = LLAMA_MODEL
        os.environ["LUCY_MODEL"] = LLAMA_MODEL
        _set_state_model(LLAMA_MODEL, memory="on")

        print(f"Running on {LLAMA_MODEL}: {MEMORY_CONTINUE_PROMPT}")
        llama_result = _run_step(LLAMA_MODEL, MEMORY_CONTINUE_PROMPT)
        print(
            f"  route={llama_result['route']} passed={llama_result['passed']} "
            f"loaded={llama_result['loaded_models']}"
        )

        # Step 3: Verify the continuation references Oscar and advances the story.
        response_text = (llama_result.get("response_text") or "").lower()
        mentions_oscar = "oscar" in response_text
        continuation_markers = [
            "continued",
            "continues",
            "continue",
            "next",
            "later",
            "then",
            "after",
            "soon",
            "meanwhile",
            "following",
            "sequel",
            "picked up",
            "adventure",
            "story",
            "tale",
            "journey",
            "again",
            "as",
            "while",
            "with",
            "until",
            "eventually",
        ]
        continues_narrative = any(marker in response_text for marker in continuation_markers)

        notes: list[str] = []
        if not mentions_oscar:
            notes.append("continuation does not reference Oscar")
        if not continues_narrative:
            notes.append("continuation does not appear to advance the narrative")

        combined_passed = (
            gemma_result["passed"]
            and llama_result["passed"]
            and mentions_oscar
            and continues_narrative
        )

        return {
            "model": f"{GEMMA_MODEL} -> {LLAMA_MODEL}",
            "question": f"{MEMORY_STORY_PROMPT} / {MEMORY_CONTINUE_PROMPT}",
            "gemma_result": gemma_result,
            "llama_result": llama_result,
            "mentions_oscar": mentions_oscar,
            "continues_narrative": continues_narrative,
            "passed": combined_passed,
            "notes": notes,
        }
    finally:
        if previous_session_memory is None:
            os.environ.pop("LUCY_SESSION_MEMORY", None)
        else:
            os.environ["LUCY_SESSION_MEMORY"] = previous_session_memory
        if previous_session_id is None:
            os.environ.pop("LUCY_SESSION_ID", None)
        else:
            os.environ["LUCY_SESSION_ID"] = previous_session_id
        if previous_memory_db is None:
            os.environ.pop("LUCY_MEMORY_DB_PATH", None)
        else:
            os.environ["LUCY_MEMORY_DB_PATH"] = previous_memory_db
        if previous_chat_memory_file is None:
            os.environ.pop("LUCY_RUNTIME_CHAT_MEMORY_FILE", None)
        else:
            os.environ["LUCY_RUNTIME_CHAT_MEMORY_FILE"] = previous_chat_memory_file
        if tmp_dir is not None:
            tmp_dir.cleanup()


def main() -> int:
    assert_single_local_lucy_model("start")

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
            print(
                f"  route={result['route']} passed={result['passed']} loaded={result['loaded_models']}"
            )
            if not result["passed"]:
                passed = False

        # Step 4: cross-model memory continuity (Gemma -> Llama, fixed session).
        print("Running cross-model memory continuity step ...")
        memory_result = _run_memory_continuation_step()
        results.append(memory_result)
        print(
            f"  mentions_oscar={memory_result['mentions_oscar']} "
            f"continues_narrative={memory_result['continues_narrative']} "
            f"passed={memory_result['passed']}"
        )
        if not memory_result["passed"]:
            passed = False
    finally:
        unload_all_lucy_models()

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")

    assert_single_local_lucy_model("end")
    loaded_after = get_local_lucy_loaded_models()
    assert len(loaded_after) <= 1, loaded_after

    passed_count = sum(1 for r in results if r["passed"])
    print(f"\nSummary: {passed_count}/{len(results)} switch steps passed")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
