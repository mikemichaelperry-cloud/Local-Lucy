#!/usr/bin/env python3
"""
Local Lucy v8 — FAST ROUTING STRESS TEST
Tests hybrid router directly (no LLM, no network). ~100 queries in <10 seconds.
"""
import gc, json, os, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path.home() / "lucy-v8" / "models" / "router"))
sys.path.insert(0, str(Path(__file__).parent / "app"))

os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v9-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v9"))

from hybrid_router import HybridRouter

ROUTER = HybridRouter()

TEST_CASES = [
    # LOCAL — math, identity, cooking, general knowledge
    ("What is 2+2?", "LOCAL"),
    ("What is 15 times 23?", "LOCAL"),
    ("Who are you?", "LOCAL"),
    ("Tell me a joke", "LOCAL"),
    ("Explain quantum computing", "LOCAL"),
    ("How do I bake sourdough bread?", "LOCAL"),
    ("What is the capital of France?", "LOCAL"),
    ("Write a haiku about rain", "LOCAL"),
    ("Translate hello to Japanese", "LOCAL"),
    ("What is CRISPR?", "LOCAL"),
    ("How do I make pancakes?", "LOCAL"),
    ("What is the Pythagorean theorem?", "LOCAL"),
    ("Who invented the telephone?", "LOCAL"),
    ("What is the speed of light?", "LOCAL"),
    ("Explain recursion", "LOCAL"),
    ("What is 5+5?", "LOCAL"),
    ("What is gravity?", "LOCAL"),
    ("What is AI?", "LOCAL"),
    ("Tell me a story", "LOCAL"),
    ("Write a poem about the ocean", "LOCAL"),
    ("How do I change a tire?", "LOCAL"),
    ("What is the largest planet?", "LOCAL"),

    # TIME
    ("What time is it?", "TIME"),
    ("What time is it in Tokyo?", "TIME"),
    ("Current time in London", "TIME"),
    ("What time is it in New York?", "TIME"),
    ("Time in Sydney Australia", "TIME"),
    ("What is the time right now?", "TIME"),
    ("Tell me the current time", "TIME"),
    ("What time is it in Berlin?", "TIME"),

    # WEATHER
    ("What is the weather in London?", "WEATHER"),
    ("Whats the current weather in Hadera Israel?", "WEATHER"),
    ("Will it rain in Paris tomorrow?", "WEATHER"),
    ("Temperature in Tokyo", "WEATHER"),
    ("Do I need an umbrella in Seattle?", "WEATHER"),
    ("Should I bring a jacket today?", "WEATHER"),
    ("Weather forecast for New York", "WEATHER"),
    ("Is it sunny in Barcelona?", "WEATHER"),
    ("What is the weather like outside?", "WEATHER"),
    ("How hot is it in Dubai?", "WEATHER"),

    # NEWS
    ("What are todays headlines?", "NEWS"),
    ("Latest news on technology", "NEWS"),
    ("Breaking news", "NEWS"),
    ("What happened today?", "NEWS"),
    ("Current events", "NEWS"),
    ("Whats in the news?", "NEWS"),
    ("Any news about space?", "NEWS"),
    ("Top stories right now", "NEWS"),

    # AUGMENTED (medical, financial, search)
    ("What are symptoms of diabetes?", "AUGMENTED"),
    ("Search Wikipedia for Python programming language", "AUGMENTED"),
    ("What is the treatment for flu?", "AUGMENTED"),
    ("Tesla stock price", "AUGMENTED"),
    ("Current NVIDIA stock price", "AUGMENTED"),
    ("How much is Bitcoin worth?", "AUGMENTED"),
    ("Latest Supreme Court ruling", "AUGMENTED"),
    ("What are the side effects of aspirin?", "AUGMENTED"),
    ("What is hypertension?", "AUGMENTED"),
    ("Apple stock today", "AUGMENTED"),
    ("Ethereum price", "AUGMENTED"),
    ("Search for CRISPR therapy", "AUGMENTED"),

    # EDGE / MISDIRECTION (things that used to misfire)
    ("World Cup final", "NEWS"),
    ("World Cup", "NEWS"),
    ("What temperature should I cook chicken at?", "LOCAL"),
    ("What temperature is a fever?", "AUGMENTED"),
    ("What is my favorite color?", "LOCAL"),  # no memory context
    ("My favorite color is blue", "LOCAL"),    # no memory context
    ("Do I need a coat?", "WEATHER"),
    ("Is it going to snow?", "WEATHER"),
    ("Give me the headlines", "NEWS"),
    ("Whats trending?", "NEWS"),
    ("Stock market today", "AUGMENTED"),
    ("Gold price", "AUGMENTED"),
]

def get_gpu():
    try:
        import subprocess
        out = subprocess.run(["nvidia-smi","--query-gpu=memory.used","--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
        return int(out.stdout.strip()) if out.returncode == 0 else None
    except Exception:
        return None

def main():
    print("=" * 70)
    print("LOCAL LUCY V8 — FAST ROUTING STRESS TEST")
    print(f"Started: {datetime.now().isoformat()}")
    print("=" * 70)

    gpu0 = get_gpu()
    print(f"GPU VRAM baseline: {gpu0 or '?'} MiB")
    print(f"Test cases: {len(TEST_CASES)}")
    print()

    results = []
    correct = 0
    total_ms = 0
    route_counts = {}

    for q, expected in TEST_CASES:
        t0 = time.time()
        pred = ROUTER.predict(q)
        ms = (time.time() - t0) * 1000
        route = pred.get("route", "UNKNOWN")
        intent = pred.get("intent_family", "UNKNOWN")
        guards = pred.get("guards_fired", [])

        ok = route == expected
        if ok:
            correct += 1
        total_ms += ms
        route_counts[route] = route_counts.get(route, 0) + 1

        results.append({"q": q, "expected": expected, "got": route, "intent": intent, "ms": round(ms, 1), "ok": ok, "guards": guards})

        status = "✅" if ok else "❌"
        print(f"{status} [{route:8s}] {ms:5.1f}ms | {q[:55]}")
        if not ok:
            print(f"      Expected: {expected} | Intent: {intent} | Guards: {guards}")

    gpu1 = get_gpu()
    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    acc = correct / len(TEST_CASES) * 100
    print(f"Accuracy:   {correct}/{len(TEST_CASES)} ({acc:.1f}%)")
    print(f"Avg latency: {total_ms/len(TEST_CASES):.1f}ms")
    print(f"Max latency: {max(r['ms'] for r in results):.1f}ms")
    print(f"GPU VRAM:   {gpu0 or '?'} → {gpu1 or '?'} MiB")
    print("\nRoute distribution:")
    for r, c in sorted(route_counts.items(), key=lambda x: -x[1]):
        print(f"  {r:12s}: {c}")

    # Save report
    report_dir = Path.home() / ".codex-api-home" / "lucy" / "runtime-v9" / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"routing_stress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "total": len(TEST_CASES),
            "correct": correct,
            "accuracy": acc,
            "avg_ms": total_ms/len(TEST_CASES),
            "gpu_baseline_mb": gpu0,
            "gpu_final_mb": gpu1,
            "routes": route_counts,
            "results": results,
        }, f, indent=2)
    print(f"\n📄 Report saved: {report_path}")
    return 0 if acc >= 90 else 1

if __name__ == "__main__":
    sys.exit(main())
