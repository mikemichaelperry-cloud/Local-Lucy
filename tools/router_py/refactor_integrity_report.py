#!/usr/bin/env python3
"""Generate a refactor-integrity report after the Phase 8 module splits.

The report verifies that every split module imports cleanly, that the facades
re-export the expected names, and that no circular imports were introduced.
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
TOOLS = ROOT / "tools"
ROUTER_PY = TOOLS / "router_py"


def _subprocess_import(module_name: str) -> dict:
    """Import a module in a fresh subprocess and return the result."""
    cmd = [sys.executable, "-c", f"import {module_name}; print('ok')"]
    result = subprocess.run(
        cmd,
        cwd=TOOLS,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {
        "module": module_name,
        "ok": result.returncode == 0,
        "error": result.stderr.strip() if result.returncode != 0 else None,
    }


def _split_modules() -> list[str]:
    """Modules that were created or heavily modified during Phase 8 splits."""
    return [
        "router_py.classify",
        "router_py.classify_core.guards",
        "router_py.classify_core.intent",
        "router_py.classify_core.memory",
        "router_py.classify_core.router",
        "router_py.classify_core.select",
        "router_py.local_answer",
        "router_py.local_answer_core.config",
        "router_py.local_answer_core.engine",
        "router_py.local_answer_core.logger",
        "router_py.local_answer_core.self_knowledge",
        "router_py.local_answer_core.utils",
        "router_py.voice",
        "router_py.voice.exceptions",
        "router_py.voice.models",
        "router_py.voice.pipeline",
        "router_py.voice.utils",
        "router_py.policy",
        "router_py.policy.core",
        "router_py.policy.finance",
        "router_py.policy.historical",
        "router_py.policy.semantic",
        "router_py.policy.utils",
        "router_py.policy_router",
        "router_py.policy_router.gates",
        "router_py.policy_router.models",
        "router_py.policy_router.router",
        "router_py.execution_engine",
        "router_py.execution_engine.helpers",
        "router_py.execution_engine_state",
        "router_py.execution_engine_utils",
        "router_py.state_manager",
        "router_py.state.schema",
        "router_py.state.queries",
        "router_py.news",
        "router_py.news.models",
        "router_py.news.provider",
        "router_py.news.rss",
        "router_py.news.utils",
    ]


def _check_split_module_imports() -> list[dict]:
    return [_subprocess_import(m) for m in _split_modules()]


def _check_circular_imports() -> dict:
    """Verify the main facades can be imported together."""
    cmd = [
        sys.executable,
        "-c",
        (
            "import router_py.classify; import router_py.local_answer; "
            "import router_py.execution_engine; import router_py.state_manager; "
            "import router_py.policy; import router_py.policy_router; "
            "import router_py.news; import router_py.voice; print('ok')"
        ),
    ]
    result = subprocess.run(cmd, cwd=TOOLS, capture_output=True, text=True, timeout=60)
    return {
        "ok": result.returncode == 0,
        "error": result.stderr.strip() if result.returncode != 0 else None,
    }


def _check_public_api_surface() -> dict:
    """Verify facade re-export surfaces are present."""
    import router_py.classify as classify
    import router_py.local_answer as local_answer
    import router_py.voice as voice

    classify_required = {
        "classify_intent",
        "select_route",
        "prewarm_router",
        "ClassificationResult",
        "RoutingDecision",
        "_is_capability_query",
        "_is_clear_news_query",
        "_is_news_query_typos",
        "_map_to_intent_family",
        "_memory_routing_gate",
        "_call_llm_arbiter",
        "_make_local_decision",
        "_make_augmented_decision",
    }
    local_answer_required = {"LocalAnswer", "LocalAnswerConfig", "LocalAnswerLogger"}
    voice_required = {
        "AudioBuffer",
        "TranscriptionResult",
        "VADConfig",
        "VoiceMetrics",
        "VoiceResult",
        "VoicePipeline",
        "quick_voice_interaction",
        "clean_text",
        "iso_now",
    }

    return {
        "classify_missing": sorted(classify_required - set(dir(classify))),
        "local_answer_missing": sorted(local_answer_required - set(dir(local_answer))),
        "voice_missing": sorted(voice_required - set(dir(voice))),
    }


def generate_report() -> dict:
    """Run all checks and return the report as a dict."""
    split_results = _check_split_module_imports()
    return {
        "split_module_imports": split_results,
        "circular_imports": _check_circular_imports(),
        "public_api_surface": _check_public_api_surface(),
        "summary": {
            "modules_checked": len(split_results),
            "modules_ok": sum(1 for m in split_results if m["ok"]),
            "modules_failed": sum(1 for m in split_results if not m["ok"]),
            "api_surface_complete": not any(_check_public_api_surface().values()),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate refactor-integrity report")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=Path("refactor_integrity_report.json"),
    )
    args = parser.parse_args()

    report = generate_report()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
