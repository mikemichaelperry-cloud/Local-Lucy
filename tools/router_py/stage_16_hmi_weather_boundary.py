#!/usr/bin/env python3
"""HMI boundary test for weather/time misrouting fix.

Submits explicit weather/time queries and queries that should stay LOCAL
through the HMI surface (RuntimeBridge), asserting routes are correct.

Usage:
    cd /home/mike/lucy-v11
    python3 tools/router_py/stage_16_hmi_weather_boundary.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ui-v10"))
sys.path.insert(0, str(ROOT / "tools"))

from app.services.runtime_bridge import RuntimeBridge


def _write_evidence_on_state(namespace_root: Path) -> None:
    """Write a current_state.json with evidence enabled in the namespace."""
    state_file = namespace_root / "state" / "current_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "model": os.environ.get("LUCY_LOCAL_MODEL", "local-lucy-llama31:latest"),
        "evidence": "on",
        "memory": "off",
        "conversation": "off",
        "voice": "off",
        "schema_version": 1,
    }
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="lucy-wx-boundary-") as tmp:
        namespace_root = Path(tmp)
        os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(namespace_root)
        os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(ROOT))
        os.environ.setdefault("LUCY_UI_ROOT", str(ROOT / "ui-v10"))
        os.environ.setdefault("LUCY_DISABLE_BACKGROUND_WARMUP", "1")
        os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
        os.environ.setdefault("LUCY_ENABLE_INTERNET", "1")
        _write_evidence_on_state(namespace_root)

        cases = [
            ("What is the weather in London?", {"WEATHER"}),
            ("What time is it in Tokyo?", {"TIME"}),
            # These must NOT be misrouted to WEATHER/TIME as a low-confidence fallback.
            ("Why is the sky blue?", {"LOCAL", "AUGMENTED"}),
            ("What is your opinion on climate change?", {"LOCAL", "AUGMENTED"}),
            ("How does temperature affect baking?", {"LOCAL", "AUGMENTED", "EVIDENCE"}),
            ("Explain thermodynamics to me.", {"LOCAL", "AUGMENTED"}),
        ]

        bridge = RuntimeBridge()
        results: list[dict] = []
        passed = True

        for question, expected in cases:
            result = bridge.run_action("submit_request", question)
            payload = result.payload or {}
            route = (payload.get("route") or {}).get("mode", "unknown")
            ok = result.status == "ok" and route in expected
            results.append({
                "question": question,
                "expected": sorted(expected),
                "actual": route,
                "status": result.status,
                "passed": ok,
            })
            print(f"{question!r}: {route} (expected {sorted(expected)}) passed={ok}")
            if not ok:
                passed = False

        report_path = Path("qualification/results/stage_16_hmi_weather_boundary.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

        passed_count = sum(1 for r in results if r["passed"])
        print(f"\nSummary: {passed_count}/{len(cases)} boundary cases passed")
        return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
