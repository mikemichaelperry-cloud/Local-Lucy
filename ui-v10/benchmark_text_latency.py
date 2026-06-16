#!/usr/bin/env python3
"""Text latency benchmark - Phase 2"""

import json
import os
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI_ROOT = ROOT / "ui-v10"
RUNTIME_NS = Path(
    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    or (Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
)

PROMPTS = [
    "What is Ohm's law?",
    "What does a 6205 bearing number mean?",
    "Explain entropy in simple terms.",
    "What is the difference between AC and DC?",
    "Give me a short chicken soup tip.",
]

RESULTS = []
REQUEST_TOOL = str(ROOT / "tools" / "runtime_request.py")

# Set required env vars
env = os.environ.copy()
env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(ROOT)
env["LUCY_UI_ROOT"] = str(UI_ROOT)
env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(RUNTIME_NS)
env["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"

print("=" * 70)
print("PHASE 2: TEXT LATENCY BENCHMARK")
print("=" * 70)
print(f"Start time: {time.strftime('%H:%M:%S')}")
print(f"Tool: {REQUEST_TOOL}")
print("")

for prompt in PROMPTS:
    print(f"\nPrompt: '{prompt}'")
    print("-" * 50)

    for run in range(1, 4):
        start_time = time.time()

        try:
            result = subprocess.run(
                ["python3", REQUEST_TOOL, "submit", "--text", prompt],
                capture_output=True,
                text=True,
                timeout=130,
                env=env,
            )
            end_time = time.time()
            ttc = end_time - start_time

            # Parse response
            response_data = json.loads(result.stdout) if result.stdout else {}
            error = response_data.get("error", "")
            accepted = response_data.get("accepted", False)

            record = {
                "prompt": prompt[:40],
                "run": run,
                "ttc": round(ttc, 2),
                "accepted": accepted,
                "error": error,
                "status": "success" if accepted else "failed",
            }
            RESULTS.append(record)

            status_icon = "✓" if accepted else "✗"
            err_info = f" ({error[:40]}...)" if error else ""
            print(f"  Run {run}: {status_icon} TTC={ttc:.2f}s{err_info}")

        except subprocess.TimeoutExpired:
            record = {"prompt": prompt[:40], "run": run, "ttc": None, "status": "timeout"}
            RESULTS.append(record)
            print(f"  Run {run}: ✗ TIMEOUT (>130s)")
        except Exception as e:
            record = {"prompt": prompt[:40], "run": run, "ttc": None, "status": f"error: {e}"}
            RESULTS.append(record)
            print(f"  Run {run}: ✗ ERROR - {e}")

        time.sleep(1)

# Summary
print("\n" + "=" * 70)
print("SUMMARY - MEDIANS")
print("=" * 70)

for prompt in PROMPTS:
    prompt_key = prompt[:40]
    times = [
        r["ttc"]
        for r in RESULTS
        if r["prompt"] == prompt_key and r["ttc"] is not None and r.get("accepted")
    ]
    if times:
        med = statistics.median(times)
        print(f"{prompt[:38]:38} | Median TTC: {med:5.2f}s")
    else:
        print(f"{prompt[:38]:38} | No successful runs")

# Save results
report_path = Path.home() / "Desktop" / "benchmark_text_results.json"
with open(report_path, "w") as f:
    json.dump(RESULTS, f, indent=2)

success_count = sum(1 for r in RESULTS if r.get("accepted"))
print(f"\nResults saved to {report_path}")
print(f"Successful runs: {success_count}/{len(RESULTS)}")
