#!/usr/bin/env python3
"""End-to-end stress test across both Gemma and Llama local models.

Exercises the full runtime_request → router_py → local_model → state-write
path for each model with short, reasoning, regression, long-input, and repeat
queries. Verifies that every request completes, produces exactly one history
entry, and does not duplicate request IDs.

Skips automatically if Ollama is unreachable or if either model is missing.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import runtime_request
from router_py.ollama_cleanup import unload_all_lucy_models


_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_URL", "http://127.0.0.1:11434")


def _available_model_names() -> set[str]:
    try:
        req = urllib.request.Request(f"{_OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return {m["name"] for m in data.get("models", [])}
    except Exception:
        return set()


def _model_present(alias: str) -> bool:
    names = _available_model_names()
    return f"{alias}:latest" in names or alias in names


@pytest.fixture
def isolated_namespace(tmp_path: Path, monkeypatch):
    """Provide a temp runtime namespace and reset env so state files land there."""
    ns = tmp_path / "runtime-v11-stress"
    ns.mkdir(parents=True)
    state_file = ns / "current_state.json"
    monkeypatch.setenv("LUCY_RUNTIME_STATE_FILE", str(state_file))
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(ns))
    monkeypatch.setenv("LUCY_STATE_DB", str(ns / "state" / "lucy_state.db"))
    monkeypatch.setenv("LUCY_MEMORY_DB_PATH", str(ns / "state" / "memory.db"))
    monkeypatch.setenv(
        "LUCY_RUNTIME_CHAT_MEMORY_FILE", str(ns / "state" / "chat_session_memory.txt")
    )
    monkeypatch.setenv("LUCY_SESSION_MEMORY", "0")
    monkeypatch.delenv("LUCY_RUNTIME_REQUEST_RESULT_FILE", raising=False)
    monkeypatch.delenv("LUCY_RUNTIME_REQUEST_HISTORY_FILE", raising=False)
    monkeypatch.delenv("LUCY_UI_STATE_DIR", raising=False)

    # Seed empty isolation files so prior-suite state cannot leak through any
    # module-level path that was resolved before this fixture ran.
    (ns / "state").mkdir(parents=True, exist_ok=True)
    (ns / "feedback_buffer.json").write_text('{"exchanges": []}', encoding="utf-8")
    (ns / "state" / "chat_session_memory.txt").write_text("", encoding="utf-8")

    yield ns, state_file

    # Unload any model this test loaded so the next stress test does not keep
    # both Gemma and Llama resident at the same time.
    try:
        unload_all_lucy_models()
    except Exception:
        pass


def _make_state(model: str) -> dict:
    return {
        "active_model": model,
        "augmentation_policy": "fallback_only",
        "augmented_provider": "openai",
        "code_review_model": "gemma4_code_review_agentic",
        "code_review_specialist_enabled": "on",
        "conversation": "on",
        "evidence": "on",
        "gemma4_smart_routing": "off",
        "learner": "on",
        "memory": "on",
        "mode": "auto",
        "model": model,
        "profile": "lucy-v11",
        "self_analysis_mode": "off",
        "status": "ready",
        "voice": "off",
    }


def _run_stress_for_model(model: str, isolated_namespace):
    ns, state_file = isolated_namespace
    state_file.write_text(json.dumps(_make_state(model)), encoding="utf-8")

    # Force a fresh embedding-router singleton for each model run.  Earlier
    # tests (especially HMI/voice tests that start background warmup threads)
    # can leave the cached router in a corrupted state, which manifests as
    # every query routing to NEWS.
    for mod_name in list(sys.modules.keys()):
        if "classify" in mod_name.lower() and hasattr(sys.modules[mod_name], "_ROUTER"):
            sys.modules[mod_name]._ROUTER = None

    long_text = "word " * 3000  # ~18 k chars before prefix; guard truncates near 16 k
    queries = [
        ("hi", "short_local"),
        ("Explain the difference between a CPU and a GPU in one paragraph.", "reasoning_local"),
        (
            "What would give you the biggest boost whilst taking into consideration my limited hardware?",
            "hardware_advice_regression",
        ),
        ("Summarize the following text concisely: " + long_text, "long_input_local"),
        ("hi", "repeat_local"),
    ]

    history_file = ns / "state" / "request_history.jsonl"
    result_file = ns / "state" / "last_request_result.json"
    seen_ids: list[str] = []
    failures: list[tuple[str, str]] = []

    for q, tag in queries:
        t0 = time.time()
        try:
            payload = runtime_request.submit_request(q, persist=True, surface="cli", model=model)
        except Exception as exc:
            failures.append((tag, f"exception: {exc}"))
            continue
        elapsed = time.time() - t0

        status = payload.get("status")
        response = payload.get("response_text", "")
        rid = payload.get("request_id", "")
        route = payload.get("route", {}).get("selected_route", "?")
        model_in_state = payload.get("control_state", {}).get("model", "?")

        print(
            f"  [{tag:28s}] route={route:6s} status={status:9s} "
            f"len={len(response):5d} id={rid[:34]:34s} t={elapsed:.1f}s"
        )

        if status != "completed":
            failures.append((tag, f"status={status} error={payload.get('error')}"))
        elif not response.strip():
            failures.append((tag, "empty response"))
        if rid in seen_ids:
            failures.append((tag, f"duplicate request_id {rid}"))
        seen_ids.append(rid)
        if model_in_state != model:
            failures.append((tag, f"control_state.model={model_in_state} != {model}"))

    if not history_file.exists():
        failures.append(("history", "request_history.jsonl not created"))
    else:
        lines = [
            line for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        if len(lines) != len(queries):
            failures.append(("history", f"expected {len(queries)} entries, got {len(lines)}"))
        hist_ids = [json.loads(line).get("request_id") for line in lines]
        if len(hist_ids) != len(set(hist_ids)):
            failures.append(("history", "duplicate request_ids in history file"))

    if not result_file.exists():
        failures.append(("result", "last_request_result.json not created"))

    return failures


@pytest.mark.skipif(
    not _model_present("local-lucy-gemma4"), reason="local-lucy-gemma4 not in Ollama"
)
def test_stress_gemma4(isolated_namespace):
    failures = _run_stress_for_model("local-lucy-gemma4", isolated_namespace)
    assert not failures, "Gemma4 stress failures:\n" + "\n".join(f"  {t}: {m}" for t, m in failures)


@pytest.mark.skipif(
    not _model_present("local-lucy-llama31"), reason="local-lucy-llama31 not in Ollama"
)
def test_stress_llama31(isolated_namespace):
    failures = _run_stress_for_model("local-lucy-llama31", isolated_namespace)
    assert not failures, "Llama31 stress failures:\n" + "\n".join(
        f"  {t}: {m}" for t, m in failures
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
