#!/usr/bin/env python3
"""
Local Lucy v8 — End-to-End Smoke Test
Small but representative set of full-pipeline queries.
Pre-warms Ollama to keep model loaded.
"""
from __future__ import annotations

import gc, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "app"))
sys.path.insert(0, str(Path.home() / "lucy-v9" / "models" / "router"))

os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v9" / "snapshots" / "opt-experimental-v9-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v9"))
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")
os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")
os.environ.setdefault("LUCY_SESSION_MEMORY", "1")

from app.backend import execute_plan_python


def get_gpu():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None


def get_ram():
    with open("/proc/meminfo") as f:
        lines = f.readlines()
    total = avail = 0
    for line in lines:
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) // 1024
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1]) // 1024
    return total - avail, total


def warm_ollama():
    """Send a tiny prompt to force model load into VRAM."""
    print("🔥 Pre-warming Ollama model...")
    try:
        import requests
        requests.post("http://localhost:11434/api/generate", json={
            "model": "local-lucy",
            "prompt": "hi",
            "stream": False,
            "options": {"num_predict": 1}
        }, timeout=120)
    except Exception as e:
        print(f"  Warm-up warning: {e}")
    # Wait for model to settle
    for _ in range(10):
        time.sleep(1)
        gpu = get_gpu()
        print(f"  GPU VRAM: {gpu or '?'} MiB")
        if gpu and gpu > 4000:
            break
    print("  Model loaded.")


def run_query(query, expected_route=None, expected_contains=None):
    t0 = time.time()
    try:
        result = execute_plan_python(query)
        latency = (time.time() - t0) * 1000
        response = result.response_text or ""
        ok = True
        if expected_route and result.route != expected_route:
            ok = False
        if expected_contains and expected_contains.lower() not in response.lower():
            ok = False
        return {
            "query": query, "route": result.route, "status": result.status,
            "response": response[:300], "latency_ms": latency, "ok": ok,
            "error": result.error_message or ""
        }
    except Exception as e:
        return {
            "query": query, "route": "ERROR", "status": "failed",
            "response": "", "latency_ms": (time.time() - t0) * 1000, "ok": False,
            "error": str(e)
        }


def print_result(r):
    status = "✅" if r["ok"] and r["status"] == "completed" else "❌"
    print(f"  {status} [{r['route']:8s}] {r['latency_ms']:6.0f}ms | {r['query'][:55]}")
    if r["error"]:
        print(f"      ERROR: {r['error'][:80]}")
    if not r["ok"] and r["status"] == "completed":
        print(f"      RESPONSE: {r['response'][:80]}...")


def main():
    print("=" * 70)
    print("LOCAL LUCY V8 — END-TO-END SMOKE TEST")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    gpu0 = get_gpu()
    ram0, ram_total = get_ram()
    print(f"Baseline GPU: {gpu0 or '?'} MiB | RAM: {ram0}/{ram_total} MiB")

    warm_ollama()

    results = []

    # ── Batch 1: LOCAL ──
    print("\n🧪 LOCAL (5 queries)")
    for q, contains in [
        ("What is 2+2?", "4"),
        ("Who are you?", "Lucy"),
        ("Tell me a joke", None),
        ("What is the capital of France?", "Paris"),
        ("Explain recursion", "itself"),
    ]:
        r = run_query(q, "LOCAL", contains)
        results.append(r)
        print_result(r)

    # ── Batch 2: TIME ──
    print("\n🧪 TIME (2 queries)")
    for q in ["What time is it?", "What time is it in Tokyo?"]:
        r = run_query(q, "TIME", None)
        results.append(r)
        print_result(r)

    # ── Batch 3: WEATHER ──
    print("\n🧪 WEATHER (3 queries)")
    for q, contains in [
        ("What is the weather in London?", "London"),
        ("Temperature in Tokyo", "Tokyo"),
        ("Do I need an umbrella in Seattle?", "Seattle"),
    ]:
        r = run_query(q, "WEATHER", contains)
        results.append(r)
        print_result(r)

    # ── Batch 4: NEWS ──
    print("\n🧪 NEWS (2 queries)")
    for q in ["What are todays headlines?", "Breaking news"]:
        r = run_query(q, "NEWS", None)
        results.append(r)
        print_result(r)

    # ── Batch 5: AUGMENTED ──
    print("\n🧪 AUGMENTED (3 queries)")
    for q, contains in [
        ("What are symptoms of diabetes?", "diabetes"),
        ("Tesla stock price", None),
        ("What is the treatment for flu?", "flu"),
    ]:
        r = run_query(q, "AUGMENTED", contains)
        results.append(r)
        print_result(r)

    # ── Batch 6: MEMORY ──
    print("\n🧪 MEMORY PIPELINE (2 queries)")
    r1 = run_query("My favorite color is blue")
    print(f"  {'✅' if r1['status']=='completed' else '❌'} STORE  {r1['latency_ms']:6.0f}ms | {r1['query']}")
    results.append(r1)
    time.sleep(0.5)
    r2 = run_query("What is my favorite color?", None, "blue")
    print(f"  {'✅' if r2['ok'] else '❌'} RECALL {r2['latency_ms']:6.0f}ms | {r2['query']}")
    print(f"      Response: {r2['response'][:80]}...")
    results.append(r2)

    # ── Final resources ──
    gpu1 = get_gpu()
    ram1, _ = get_ram()
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    completed = [r for r in results if r["status"] == "completed"]
    failed = [r for r in results if r["status"] != "completed"]
    correct = [r for r in results if r["ok"]]
    avg_lat = sum(r["latency_ms"] for r in results) / len(results)
    max_lat = max(r["latency_ms"] for r in results)

    print(f"Queries:    {len(results)}")
    print(f"Completed:  {len(completed)} ({len(completed)*100//len(results)}%)")
    print(f"Failed:     {len(failed)}")
    print(f"Correct:    {len(correct)} ({len(correct)*100//len(results)}%)")
    print(f"Avg latency:{avg_lat:.0f}ms")
    print(f"Max latency:{max_lat:.0f}ms")
    print(f"GPU VRAM:   {gpu0 or '?'} → {gpu1 or '?'} MiB")
    print(f"RAM used:   {ram0} → {ram1} MiB")

    if failed:
        print("\n❌ FAILED:")
        for r in failed:
            print(f"  [{r['route']}] {r['query']}: {r['error'][:80]}")

    report_path = Path.home() / ".codex-api-home" / "lucy" / "runtime-v9" / "logs" / f"e2e_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": len(results),
            "completed": len(completed),
            "failed": len(failed),
            "correct": len(correct),
            "avg_ms": avg_lat,
            "max_ms": max_lat,
            "gpu0": gpu0, "gpu1": gpu1,
            "ram0": ram0, "ram1": ram1,
            "results": results,
        }, f, indent=2, default=str)
    print(f"\n📄 Report: {report_path}")

    return 0 if len(correct) >= len(results) * 0.85 else 1


if __name__ == "__main__":
    sys.exit(main())
