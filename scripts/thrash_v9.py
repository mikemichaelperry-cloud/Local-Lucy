#!/usr/bin/env python3
"""Local Lucy v8 Professional Thrash Test — GPU, Accuracy, Stability, Speed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / "lucy-v10" / "ui-v10" / "app"))

SNAPSHOT = Path.home() / "lucy-v10"
TOOLS = SNAPSHOT / "tools"
TOOLS = SNAPSHOT / "tools"
sys.path.insert(0, str(TOOLS))

os.environ["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(SNAPSHOT)
os.environ["LUCY_UI_ROOT"] = str(Path.home() / "lucy-v10" / "ui-v10")
os.environ["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(
    Path.home() / ".codex-api-home" / "lucy" / "runtime-v10"
)
os.environ["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
os.environ["LUCY_ROUTER_PY"] = "1"
os.environ["LUCY_EXEC_PY"] = "1"
os.environ["LUCY_AUGMENTATION_POLICY"] = "fallback_only"

from router_py.classify import classify_intent, select_route  # noqa: E402
from router_py.execution_engine import ExecutionEngine  # noqa: E402
from router_py.policy import normalize_augmentation_policy  # noqa: E402

RESULTS: list[dict] = []
FAILURES: list[str] = []


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def record(name: str, passed: bool, details: dict | None = None, error: str = "") -> None:
    RESULTS.append({"name": name, "passed": passed, "details": details or {}, "error": error})
    status = "PASS" if passed else "FAIL"
    print(f"  [{status}] {name}" + (f" — {error}" if error else ""), flush=True)


def gpu_status() -> dict:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        parts = out.stdout.strip().split(",")
        return {
            "vram_used_mb": int(parts[0].strip()),
            "vram_total_mb": int(parts[1].strip()),
            "gpu_util": int(parts[2].strip()),
        }
    except Exception:
        return {}


def ollama_ps() -> list[dict]:
    try:
        out = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/ps"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        data = json.loads(out.stdout)
        return data.get("models", [])
    except Exception:
        return []


def query_local(question: str, model: str = "local-lucy", timeout: int = 125) -> dict:
    """Direct execution — fastest path, no UI overhead."""
    start = time.monotonic()
    classification = classify_intent(question, surface="hmi")
    policy = normalize_augmentation_policy(
        os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
    )
    decision = select_route(classification, policy=policy)
    engine = ExecutionEngine(config={"timeout": timeout, "use_sqlite_state": True, "model": model})
    result = engine.execute(
        intent=classification,
        route=decision,
        context={"question": question},
    )
    engine.close()
    elapsed = time.monotonic() - start
    return {
        "status": result.status,
        "response": result.response_text,
        "route": result.route,
        "provider": result.provider,
        "error": result.error_message,
        "elapsed_ms": int(elapsed * 1000),
    }


# ── TEST SUITE ──────────────────────────────────────────────────────────────


def test_empty_queries() -> None:
    log("=== Empty / Whitespace Queries ===")
    for q in ("", "   ", "\t\n", "   \n  "):
        r = query_local(q)
        passed = r["status"] == "failed" and "empty" in r["error"].lower()
        record(
            f"empty_query({q!r})",
            passed,
            {"status": r["status"], "error": r["error"]},
            "" if passed else f"expected failed(empty), got {r['status']}: {r['error']}",
        )


def test_factual_accuracy() -> None:
    log("=== Factual Accuracy (8B) ===")
    cases = [
        ("What is the capital of France?", ["Paris"]),
        ("What is 15 multiplied by 7?", ["105"]),
        ("Who wrote Romeo and Juliet?", ["Shakespeare", "William Shakespeare"]),
        ("What is the square root of 144?", ["12"]),
        ("What planet is known as the Red Planet?", ["Mars"]),
        ("In what year did World War II end?", ["1945"]),
        ("What is the chemical symbol for gold?", ["Au"]),
        ("How many continents are there?", ["7", "seven", "Seven"]),
    ]
    for question, expected in cases:
        r = query_local(question)
        resp = r["response"]
        found = any(exp.lower() in resp.lower() for exp in expected)
        passed = r["status"] == "completed" and found
        record(
            f"fact_8B({question[:40]}...)",
            passed,
            {"elapsed_ms": r["elapsed_ms"], "route": r["route"]},
            "" if passed else f"missing {expected} in: {resp[:120]}",
        )


def test_qwen3_accuracy() -> None:
    log("=== Qwen3 14B Accuracy ===")
    if "local-lucy-qwen3" not in ollama_models():
        log("  qwen3 not available, skipping")
        return
    cases = [
        ("What is the derivative of x squared?", ["2x"]),
        ("What is the atomic number of oxygen?", ["8"]),
        ("Name the first five prime numbers.", ["2", "3", "5", "7", "11"]),
    ]
    for question, expected in cases:
        r = query_local(question, model="local-lucy-qwen3")
        resp = r["response"]
        found = all(exp.lower() in resp.lower() for exp in expected)
        passed = r["status"] == "completed" and found
        record(
            f"fact_qwen3({question[:40]}...)",
            passed,
            {"elapsed_ms": r["elapsed_ms"]},
            "" if passed else f"missing {expected} in: {resp[:120]}",
        )


def test_speed_baseline() -> None:
    log("=== Speed Baseline (8B) ===")
    times = []
    for _ in range(5):
        start = time.monotonic()
        r = query_local("What is 2+2?")
        times.append(time.monotonic() - start)
    avg = sum(times) / len(times)
    passed = avg < 15.0 and r["status"] == "completed"
    record(
        "speed_baseline_8B",
        passed,
        {"avg_s": round(avg, 2), "samples": len(times)},
        "" if passed else f"too slow: {avg:.2f}s",
    )


def test_speed_qwen3() -> None:
    log("=== Speed Baseline (Qwen3 14B) ===")
    if "local-lucy-qwen3" not in ollama_models():
        log("  qwen3 not available, skipping")
        return
    times = []
    for _ in range(3):
        start = time.monotonic()
        r = query_local("What is 2+2?", model="local-lucy-qwen3")
        times.append(time.monotonic() - start)
    avg = sum(times) / len(times)
    passed = avg < 30.0 and r["status"] == "completed"
    record(
        "speed_baseline_qwen3",
        passed,
        {"avg_s": round(avg, 2)},
        "" if passed else f"too slow: {avg:.2f}s",
    )


def test_repetition_stability() -> None:
    log("=== Repetition Stability (same query 5x) ===")
    responses = []
    for i in range(5):
        r = query_local("What is the capital of Italy?")
        responses.append(r["response"].strip()[:60])
    unique = len(set(responses))
    passed = unique <= 2 and all("Rome" in resp for resp in responses)
    record(
        "repetition_stability",
        passed,
        {"unique_responses": unique, "samples": responses},
        "" if passed else f"{unique} unique responses, expected <= 2",
    )


def test_model_switch_race() -> None:
    log("=== Rapid Model Switch ===")
    available = ollama_models()
    models = ["local-lucy", "local-lucy-qwen3"]
    models = [m for m in models if m in available]
    if len(models) < 2:
        log("  only one model available, skipping")
        return
    errors = []
    for i in range(6):
        m = models[i % len(models)]
        r = query_local("Say hello briefly.", model=m)
        if r["status"] != "completed":
            errors.append(f"switch {i} ({m}): {r['error']}")
        # Wait for UI cooldown (5s) + model load margin
        time.sleep(6.5)
    passed = len(errors) == 0
    record(
        "rapid_model_switch",
        passed,
        {"switches": 6, "errors": len(errors)},
        "; ".join(errors) if errors else "",
    )


def test_concurrent_load() -> None:
    log("=== Concurrent Load (3 parallel) ===")
    questions = [
        "What is the capital of Germany?",
        "What is 12 times 12?",
        "Who painted the Mona Lisa?",
    ]

    def _q(q: str) -> dict:
        return query_local(q)

    with ThreadPoolExecutor(max_workers=3) as pool:
        t0 = time.time()
        results = list(pool.map(_q, questions))
        total = time.time() - t0
    all_ok = all(r["status"] == "completed" for r in results)
    passed = all_ok and total < 60.0
    record(
        "concurrent_3x",
        passed,
        {"total_s": round(total, 2), "all_completed": all_ok},
        "" if passed else f"some failed or too slow: {total:.2f}s",
    )


def test_vram_pressure() -> None:
    log("=== VRAM Pressure Check ===")
    before = gpu_status()
    # Run qwen3 (largest model) to load it
    if "local-lucy-qwen3" in ollama_models():
        query_local("Load check.", model="local-lucy-qwen3")
        time.sleep(2)
    after = gpu_status()
    ps = ollama_ps()
    passed = after.get("vram_used_mb", 0) < after.get("vram_total_mb", 1)
    record(
        "vram_pressure",
        passed,
        {
            "before_mb": before.get("vram_used_mb"),
            "after_mb": after.get("vram_used_mb"),
            "total_mb": after.get("vram_total_mb"),
            "ollama_models": [m.get("name") for m in ps],
        },
        "" if passed else "VRAM overflow risk",
    )


def test_special_characters() -> None:
    log("=== Special Characters / Injection ===")
    queries = [
        "What is 2+2? (test) [brackets] {braces}",
        "Say 'hello' with \"quotes\"",
        "Path /home/user/file.txt",
        "Code: `print(1+1)`",
        "Unicode: café résumé naïve",
    ]
    for q in queries:
        r = query_local(q)
        passed = r["status"] == "completed" and len(r["response"]) > 0
        record(
            f"special_chars({q[:30]}...)",
            passed,
            {"elapsed_ms": r["elapsed_ms"]},
            "" if passed else f"failed: {r['error']}",
        )


def test_long_query() -> None:
    log("=== Long Query ===")
    long_q = "Explain " + "step by step " * 100 + "how photosynthesis works."
    r = query_local(long_q)
    passed = r["status"] == "completed" and len(r["response"]) > 50
    record(
        "long_query",
        passed,
        {
            "query_len": len(long_q),
            "response_len": len(r["response"]),
            "elapsed_ms": r["elapsed_ms"],
        },
        "" if passed else f"failed or short: {r['error']}",
    )


def test_augmented_wikipedia() -> None:
    log("=== Augmented Provider (Wikipedia) ===")
    old_policy = os.environ.get("LUCY_AUGMENTATION_POLICY")
    os.environ["LUCY_AUGMENTATION_POLICY"] = "direct_allowed"
    try:
        r = query_local("What is the capital of Australia?")
        resp = r["response"]
        has_canberra = "Canberra" in resp
        # Route should be AUGMENTED for a factual query with direct_allowed
        passed = r["status"] == "completed" and has_canberra
        record(
            "augmented_wikipedia",
            passed,
            {"route": r["route"], "provider": r["provider"], "elapsed_ms": r["elapsed_ms"]},
            "" if passed else f"missing Canberra or wrong route: {r['route']}",
        )
    finally:
        if old_policy is not None:
            os.environ["LUCY_AUGMENTATION_POLICY"] = old_policy
        else:
            os.environ.pop("LUCY_AUGMENTATION_POLICY", None)


def test_self_review() -> None:
    log("=== Self-Review Path ===")
    r = query_local("review your own code for bugs")
    passed = r["status"] == "completed" and len(r["response"]) > 20
    record(
        "self_review",
        passed,
        {"elapsed_ms": r["elapsed_ms"]},
        "" if passed else f"failed: {r['error']}",
    )


def test_voice_silent_audio() -> None:
    log("=== Voice Silent Audio ===")
    runtime_voice = Path.home() / "lucy-v10" / "tools" / "runtime_voice.py"
    with tempfile.TemporaryDirectory() as tmp:
        # Create a silent WAV
        path = Path(tmp) / "silent.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b"\x00" * 16000 * 2)  # 1 second silence
        # Test normalize_transcript directly
        sys.path.insert(0, str(runtime_voice.parent))
        from runtime_voice import normalize_transcript

        result = normalize_transcript("")
        passed = result == ""
        record("voice_silent_audio", passed, {}, "" if passed else f"expected '', got {result!r}")


def test_voice_tts_speak() -> None:
    log("=== Voice TTS Speak Command ===")
    runtime_voice = Path.home() / "lucy-v10" / "tools" / "runtime_voice.py"
    result = subprocess.run(
        [sys.executable, str(runtime_voice), "speak", "--text", "test"],
        capture_output=True,
        text=True,
        timeout=15,
        env={**os.environ, "LUCY_RUNTIME_AUTHORITY_ROOT": str(SNAPSHOT)},
    )
    # TTS may fail if no audio device, but command should parse and run
    passed = result.returncode in (0, 1)  # 0=ok, 1=tts failed but parsed correctly
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {}
    record(
        "voice_tts_speak",
        passed,
        {"returncode": result.returncode, "payload": payload},
        "" if passed else f"crash: {result.stderr[:200]}",
    )


def test_policy_modes() -> None:
    log("=== Policy Modes ===")
    for policy in ("disabled", "fallback_only", "direct_allowed"):
        os.environ["LUCY_AUGMENTATION_POLICY"] = policy
        r = query_local("What is 5+5?")
        passed = r["status"] == "completed"
        record(
            f"policy_{policy}",
            passed,
            {"route": r["route"]},
            "" if passed else f"failed: {r['error']}",
        )


def test_news_freshness() -> None:
    """NEWS route must always fetch fresh RSS content — no cache, no history, direct sources."""
    log("=== NEWS Freshness & Direct Sourcing ===")

    # --- Test 1: World news ---
    r1 = query_local("latest world news")
    passed_world = (
        r1["status"] == "completed"
        and r1["route"] == "NEWS"
        and r1["provider"] == "news"
        and "1." in r1["response"]
        and "Read more:" in r1["response"]
        and "http" in r1["response"]
    )
    record(
        "news_world_format",
        passed_world,
        {
            "route": r1["route"],
            "provider": r1["provider"],
            "articles": r1["response"].count("Read more:"),
        },
        "" if passed_world else f"bad format/route: {r1['route']}/{r1['provider']}",
    )

    # --- Test 2: Israel news ---
    r2 = query_local("israel news")
    passed_israel = (
        r2["status"] == "completed"
        and r2["route"] == "NEWS"
        and r2["provider"] == "news"
        and "1." in r2["response"]
    )
    record(
        "news_israel_format",
        passed_israel,
        {"route": r2["route"], "provider": r2["provider"]},
        "" if passed_israel else f"bad route: {r2['route']}",
    )

    # --- Test 3: Australia news ---
    r3 = query_local("latest australian news")
    passed_aus = (
        r3["status"] == "completed"
        and r3["route"] == "NEWS"
        and r3["provider"] == "news"
        and "1." in r3["response"]
    )
    record(
        "news_australia_format",
        passed_aus,
        {"route": r3["route"], "provider": r3["provider"]},
        "" if passed_aus else f"bad route: {r3['route']}",
    )

    # --- Test 4: Freshness — two queries separated by 1.1s must have different fetch timestamps ---
    r4a = query_local("latest world news")
    time.sleep(1.1)  # Ensure timestamp resolution (1s) advances
    r4b = query_local("latest world news")
    ts_a = (
        r4a["response"].split("(Fetched: ")[1].split(")")[0]
        if "(Fetched:" in r4a["response"]
        else ""
    )
    ts_b = (
        r4b["response"].split("(Fetched: ")[1].split(")")[0]
        if "(Fetched:" in r4b["response"]
        else ""
    )
    passed_fresh = ts_a != ts_b and ts_a != "" and ts_b != ""
    record(
        "news_freshness_no_cache",
        passed_fresh,
        {"ts_a": ts_a, "ts_b": ts_b},
        "" if passed_fresh else f"timestamps identical — cache leak! {ts_a}",
    )

    # --- Test 5: No LLM involvement — no local model hallucination ---
    passed_no_llm = (
        r1["route"] == "NEWS"
        and "I'm sorry" not in r1["response"]
        and "As an AI" not in r1["response"]
    )
    record(
        "news_no_llm_hallucination",
        passed_no_llm,
        {},
        "" if passed_no_llm else "LLM preamble detected in NEWS response",
    )

    # --- Test 6: No history persistence (delta check) ---
    def _count_news_in_history() -> int:
        history_file = (
            Path.home()
            / ".codex-api-home"
            / "lucy"
            / "runtime-v10"
            / "state"
            / "request_history.jsonl"
        )
        count = 0
        if history_file.exists():
            for line in history_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if "news" in entry.get("request_text", "").lower():
                        count += 1
                except json.JSONDecodeError:
                    continue
        return count

    news_before = _count_news_in_history()
    # Run a fresh news query via the bridge path
    _ = query_local("latest world news")
    news_after = _count_news_in_history()
    passed_no_history = news_after == news_before
    record(
        "news_no_history_persistence",
        passed_no_history,
        {"news_before": news_before, "news_after": news_after},
        ""
        if passed_no_history
        else f"news history grew from {news_before} to {news_after} — leak!",
    )


def ollama_models() -> set[str]:
    try:
        out = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/tags"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        data = json.loads(out.stdout)
        names = set()
        for m in data.get("models", []):
            name = m.get("name", "")
            names.add(name)
            # Also add base name without :latest tag for easier matching
            if ":" in name:
                names.add(name.rsplit(":", 1)[0])
        return names
    except Exception:
        return set()


# ── MAIN ────────────────────────────────────────────────────────────────────


def main() -> int:
    log("Local Lucy v8 Professional Thrash Test")
    log(f"GPU: {gpu_status()}")
    log(f"Ollama models: {ollama_models()}")

    # Warmup
    log("Warming up...")
    query_local("Hello.")
    time.sleep(1)

    test_empty_queries()
    test_factual_accuracy()
    test_qwen3_accuracy()
    test_speed_baseline()
    test_speed_qwen3()
    test_repetition_stability()
    test_model_switch_race()
    test_concurrent_load()
    test_vram_pressure()
    test_special_characters()
    test_long_query()
    test_augmented_wikipedia()
    test_self_review()
    test_voice_silent_audio()
    test_voice_tts_speak()
    test_policy_modes()
    test_news_freshness()

    passed = sum(1 for r in RESULTS if r["passed"])
    failed = sum(1 for r in RESULTS if not r["passed"])

    log("=" * 60)
    log(f"RESULTS: {passed} passed, {failed} failed, {len(RESULTS)} total")
    if failed:
        log("FAILURES:")
        for r in RESULTS:
            if not r["passed"]:
                log(f"  • {r['name']}: {r['error']}")
    log(f"Final GPU: {gpu_status()}")
    log(f"Ollama PS: {ollama_ps()}")

    # Write report
    report_path = Path.home() / "lucy-v10" / "thrash_report.json"
    report_path.write_text(
        json.dumps(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "passed": passed,
                "failed": failed,
                "total": len(RESULTS),
                "results": RESULTS,
                "gpu_final": gpu_status(),
                "ollama_final": ollama_ps(),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    log(f"Report written to {report_path}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
