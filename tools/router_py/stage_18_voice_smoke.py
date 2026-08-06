#!/usr/bin/env python3
"""STAGE_18 — Optional voice-path smoke validation.

Validates that the voice surface does not damage the text path:
- voice routing parity with CLI/HMI,
- input validation (empty/whitespace rejected),
- response text and state persistence for voice turns,
- TTS sanitization.

This stage is gated because it exercises the full ExecutionEngine stack.

Usage:
    cd /home/mike/lucy-v11
    LUCY_ENABLE_VOICE_TESTS=1 python3 tools/router_py/stage_18_voice_smoke.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_PATH = ROOT / "qualification" / "results" / "stage_18_voice_smoke.json"

# Tests that together cover voice surface routing, validation, and state.
TEST_FILES = [
    "tools/router_py/test_voice_request_parity.py",
    "tools/router_py/test_e2e_hmi_voice.py",
]


def _run_pytest(test_file: str) -> dict:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "-v",
        "--tb=short",
        "-o",
        "addopts=",
    ]
    env = os.environ.copy()
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(ROOT / ".tmp_voice_test")
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    passed = proc.returncode == 0
    # Count pytest summary lines if available.
    summary = ""
    for line in (proc.stdout + proc.stderr).splitlines():
        if "passed" in line or "failed" in line or "error" in line:
            if "=" in line:
                summary = line.strip().replace("=", "").strip()
                break
    return {
        "file": test_file,
        "passed": passed,
        "returncode": proc.returncode,
        "summary": summary or ("passed" if passed else "failed"),
        "stdout_tail": "\n".join((proc.stdout or "").splitlines()[-20:]),
        "stderr_tail": "\n".join((proc.stderr or "").splitlines()[-20:]),
    }


def main() -> int:
    if os.environ.get("LUCY_ENABLE_VOICE_TESTS") != "1":
        print("STAGE_18 skipped: set LUCY_ENABLE_VOICE_TESTS=1 to run voice-path smoke tests")
        return 0

    results = []
    for test_file in TEST_FILES:
        print(f"Running {test_file} ...")
        result = _run_pytest(test_file)
        results.append(result)
        print(f"  {result['file']}: {result['summary']} (passed={result['passed']})")

    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    all_passed = passed_count == total

    report = {
        "stage": "STAGE_18",
        "passed": passed_count,
        "total": total,
        "all_passed": all_passed,
        "results": results,
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"\nSummary: {passed_count}/{total} voice smoke test files passed")
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
