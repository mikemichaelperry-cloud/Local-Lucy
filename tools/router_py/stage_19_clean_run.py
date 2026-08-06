#!/usr/bin/env python3
"""STAGE_19 — Final clean-run qualification.

Runs the approved mandatory model/HMI stage scripts sequentially from a clean
process state, verifies no dual-model residency, and records a single
machine-readable qualification report.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_19_clean_run.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

REPORT_PATH = ROOT / "qualification" / "results" / "stage_19_clean_run.json"
DEFAULT_OLLAMA_URL = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434").rstrip("/")

from router_py.ollama_cleanup import is_lucy_model, unload_all_lucy_models

STAGES = [
    ("STAGE_08", "tools/router_py/stage_08_gemma_smoke.py"),
    ("STAGE_09", "tools/router_py/stage_09_gemma_scenario_suite.py"),
    ("STAGE_10", "tools/router_py/stage_10_llama_smoke.py"),
    ("STAGE_11", "tools/router_py/stage_11_llama_scenario_suite.py"),
    ("STAGE_13", "tools/router_py/stage_13_model_switch.py"),
    ("STAGE_16", "tools/router_py/stage_16_hmi_soak.py"),
    ("STAGE_16_WX", "tools/router_py/stage_16_hmi_weather_boundary.py"),
]


def _api_ps() -> list[str]:
    try:
        with urllib.request.urlopen(f"{DEFAULT_OLLAMA_URL}/api/ps", timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("name", m.get("model", "")) for m in data.get("models", [])]
    except Exception:
        return []


def _lucy_models_loaded() -> list[str]:
    return [m for m in _api_ps() if is_lucy_model(m)]


def _run_stage(name: str, script: str) -> dict:
    env = os.environ.copy()
    env.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".local" / "share" / "local-lucy-v11"))
    env.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
    env.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
    env.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")

    print(f"Running {name}: {script}")
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, script],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
    )
    elapsed = time.time() - t0
    loaded = _lucy_models_loaded()
    passed = proc.returncode == 0 and len(loaded) <= 1

    return {
        "stage": name,
        "script": script,
        "passed": passed,
        "returncode": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "loaded_models_after": loaded,
        "stdout_tail": "\n".join(proc.stdout.splitlines()[-10:]),
        "stderr_tail": "\n".join(proc.stderr.splitlines()[-10:]),
    }


def main() -> int:
    print("STAGE_19: starting clean-run qualification")
    unload_all_lucy_models()
    time.sleep(1)
    if _lucy_models_loaded():
        print(f"Warning: models still loaded after cleanup: {_lucy_models_loaded()}")

    results = []
    all_passed = True
    for name, script in STAGES:
        result = _run_stage(name, script)
        results.append(result)
        print(f"  {name}: passed={result['passed']} elapsed={result['elapsed_s']}s loaded={result['loaded_models_after']}")
        if not result["passed"]:
            all_passed = False

    unload_all_lucy_models()
    final_loaded = _lucy_models_loaded()

    report = {
        "stage": "STAGE_19",
        "passed": sum(1 for r in results if r["passed"]),
        "total": len(results),
        "all_passed": all_passed and not final_loaded,
        "final_loaded_models": final_loaded,
        "results": results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nSummary: {report['passed']}/{report['total']} clean-run stages passed")
    print(f"Final loaded models: {final_loaded}")
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
