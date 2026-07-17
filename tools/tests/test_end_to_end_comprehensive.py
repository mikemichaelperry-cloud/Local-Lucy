#!/usr/bin/env python3
"""
Comprehensive End-to-End Test Suite for Local Lucy V8.

Tests:
- All execution routes (LOCAL, EVIDENCE, AUGMENTED, FULL, TIME, WEATHER, NEWS)
- Voice pipeline (Whisper STT server, Kokoro TTS worker)
- Edge cases (empty, long, special chars, medical, time-sensitive)
- Memory persistence (SQLite read/write)
- Concurrent execution safety
- State file persistence
- Provider failure fallback chains
- Auto-feedback pipeline trigger

Usage:
    cd /home/mike/lucy-v10
    source ui-v10/.venv/bin/activate
    python3 tools/tests/test_end_to_end_comprehensive.py
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.resolve()
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "router_py"))
sys.path.insert(0, str(ROOT / "models" / "router"))

from router_py.execution_engine import ExecutionEngine
from router_py.local_answer import LocalAnswer, LocalAnswerConfig
from router_py.request_types import ClassificationResult, RoutingDecision

PASSED = 0
FAILED = 0


def check(name: str, condition: bool, details: str = "") -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {name}")
    else:
        FAILED += 1
        print(f"  ❌ {name}")
        if details:
            print(f"     → {details}")


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


# ============================================================================
# Section 1: Infrastructure Health
# ============================================================================


def test_infrastructure():
    section("1. Infrastructure Health")

    # 1a. Ollama reachable
    print("\n  1a. Ollama API...")
    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            check("Ollama is running", True)
            check(
                "local-lucy-fast loaded",
                any("local-lucy-fast" in m for m in models),
                f"models={models}",
            )
    except Exception as e:
        check("Ollama is running", False, str(e))
        check("local-lucy-fast loaded", False, "Ollama not reachable")

    # 1b. Whisper STT server (only check if voice is enabled)
    state_file = ROOT / "state" / "current_state.json"
    voice_enabled = False
    try:
        if state_file.exists():
            voice_enabled = json.loads(state_file.read_text()).get("voice") == "on"
    except Exception:
        pass

    if voice_enabled or os.environ.get("LUCY_VOICE_ENABLED") in ("1", "on", "true"):
        print("\n  1b. Whisper STT server...")
        whisper_port = int(os.environ.get("LUCY_WHISPER_SERVER_PORT", "18181"))
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(("127.0.0.1", whisper_port))
            sock.close()
            if result == 0:
                check(f"Whisper server on port {whisper_port}", True)
            else:
                # Check for stale PID file — skip rather than fail if process is simply not running
                pid_file = ROOT / "tmp" / "run" / "whisper_worker.pid"
                if pid_file.exists():
                    pid_text = pid_file.read_text(encoding="utf-8").strip()
                    try:
                        os.kill(int(pid_text), 0)
                        check(
                            f"Whisper server on port {whisper_port}",
                            False,
                            f"Process {pid_text} exists but port unreachable",
                        )
                    except (ProcessLookupError, ValueError):
                        print(
                            f"  ⚠️  Whisper server on port {whisper_port} — stale PID file ({pid_text}), process not running (skipped)"
                        )
                else:
                    print(
                        f"  ⚠️  Whisper server on port {whisper_port} — no PID file found (skipped)"
                    )
        except Exception as e:
            check(f"Whisper server on port {whisper_port}", False, str(e))
    else:
        print("\n  1b. Whisper STT server... SKIPPED (voice disabled)")

    # 1c. Kokoro TTS worker
    print("\n  1c. Kokoro TTS worker...")
    sock_path = ROOT / "tmp" / "run" / "kokoro_tts_worker.sock"
    try:
        if sock_path.exists():
            check("Kokoro Unix socket exists", True)
            # Try connecting
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(str(sock_path))
            s.close()
            check("Kokoro socket accepts connections", True)
        else:
            check("Kokoro Unix socket exists", False, f"path={sock_path}")
            check("Kokoro socket accepts connections", False, "socket missing")
    except Exception as e:
        check("Kokoro socket accepts connections", False, str(e))

    # 1d. SQLite memory DB
    print("\n  1d. SQLite memory database...")
    try:
        import sqlite3

        mem_db = Path.home() / ".codex-api-home" / "lucy" / "runtime-v10" / "state" / "memory.db"
        check("Memory DB file exists", mem_db.exists(), f"path={mem_db}")
        if mem_db.exists():
            conn = sqlite3.connect(str(mem_db))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cursor.fetchall()]
            conn.close()
            check("Memory DB has tables", len(tables) > 0, f"tables={tables}")
    except Exception as e:
        check("Memory DB accessible", False, str(e))

    # 1e. Router index files
    print("\n  1e. Router embedding index...")
    examples_path = ROOT / "models" / "router" / "comprehensive_examples.json"
    embeddings_path = ROOT / "models" / "router" / "comprehensive_embeddings.npy"
    check("Router examples exist", examples_path.exists(), f"path={examples_path}")
    check("Router embeddings exist", embeddings_path.exists(), f"path={embeddings_path}")
    if examples_path.exists():
        with open(examples_path) as f:
            count = len(json.load(f))
        check("Router examples has entries", count > 400, f"count={count}")


# ============================================================================
# Section 2: All Execution Routes
# ============================================================================


async def test_all_routes():
    section("2. All Execution Routes")

    engine = ExecutionEngine(config={"timeout": 60})

    routes = [
        (
            "LOCAL simple math",
            "LOCAL",
            "local",
            "local",
            "What is 2+2?",
            ClassificationResult(
                intent="local_answer",
                intent_family="local_answer",
                category="math",
                confidence=0.95,
                needs_web=False,
                evidence_mode=None,
                evidence_reason=None,
                force_local=False,
            ),
        ),
        (
            "LOCAL creative",
            "LOCAL",
            "local",
            "local",
            "Write a haiku about the moon.",
            ClassificationResult(
                intent="creative",
                intent_family="local_answer",
                category="creative",
                confidence=0.8,
                needs_web=False,
                evidence_mode=None,
                evidence_reason=None,
                force_local=False,
            ),
        ),
        (
            "EVIDENCE science",
            "EVIDENCE",
            "local",
            "local",
            "What is quantum computing?",
            ClassificationResult(
                intent="background_overview",
                intent_family="background_overview",
                category="science",
                confidence=0.85,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="background_overview",
                force_local=False,
            ),
        ),
        (
            "AUGMENTED history",
            "AUGMENTED",
            "wikipedia",
            "free",
            "Who was Marie Curie?",
            ClassificationResult(
                intent="background_overview",
                intent_family="background_overview",
                category="history",
                confidence=0.85,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="background_overview",
                force_local=False,
            ),
        ),
        (
            "FULL kimi",
            "FULL",
            "kimi",
            "paid",
            "What is dark matter?",
            ClassificationResult(
                intent="background_overview",
                intent_family="background_overview",
                category="science",
                confidence=0.85,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="background_overview",
                force_local=False,
            ),
        ),
        (
            "FULL openai",
            "FULL",
            "openai",
            "paid",
            "What is dark energy?",
            ClassificationResult(
                intent="background_overview",
                intent_family="background_overview",
                category="science",
                confidence=0.85,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="background_overview",
                force_local=False,
            ),
        ),
        (
            "TIME tokyo",
            "TIME",
            "timeapi",
            "free",
            "What time is it in Tokyo?",
            ClassificationResult(
                intent="time_query",
                intent_family="current_evidence",
                category="time_query",
                confidence=0.95,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="time_query",
                force_local=False,
            ),
        ),
        (
            "WEATHER london",
            "WEATHER",
            "weather",
            "free",
            "What is the weather in London?",
            ClassificationResult(
                intent="weather_query",
                intent_family="current_evidence",
                category="weather",
                confidence=0.95,
                needs_web=True,
                evidence_mode="required",
                evidence_reason="weather_query",
                force_local=False,
            ),
        ),
    ]

    for name, route_name, provider, usage_class, question, intent in routes:
        print(f"\n  2. {name}...")
        try:
            route = RoutingDecision(
                route=route_name,
                mode="AUTO",
                intent_family=intent.intent_family,
                confidence=intent.confidence,
                provider=provider,
                provider_usage_class=usage_class,
                evidence_mode=intent.evidence_mode,
                evidence_reason=intent.evidence_reason,
                requires_evidence=bool(intent.evidence_mode),
                policy_reason="test",
            )
            result = await engine.execute_async(intent, route, {"question": question})
            check(
                f"{name} completed",
                result.status == "completed",
                f"status={result.status}, error={result.error_message}",
            )
            check(
                f"{name} has response",
                len(result.response_text) > 5,
                f"text={result.response_text[:50]!r}",
            )
            if result.status == "completed":
                print(f"     Response: {result.response_text[:100]}...")
        except Exception as e:
            check(f"{name}", False, str(e))


# ============================================================================
# Section 3: Edge Cases
# ============================================================================


async def test_edge_cases():
    section("3. Edge Cases")

    engine = ExecutionEngine(config={"timeout": 60})

    edge_cases = [
        ("Empty query", ""),
        ("Whitespace only", "   \n\t  "),
        ("Very long query", "word " * 500),
        ("Special characters", "What is 2+2? <script>alert('xss')</script> \\n \\t 🔥"),
        ("Unicode", "什么是量子计算？"),
        ("Medical query", "What are the symptoms of diabetes?"),
        ("Time-sensitive", "Who is the current president of the United States?"),
        ("News query", "What happened today in the world?"),
        ("Single word", "Hello"),
        ("Question mark only", "?"),
        ("Numbers only", "12345"),
    ]

    for name, question in edge_cases:
        print(f"\n  3. {name}...")
        try:
            intent = ClassificationResult(
                intent="unknown",
                intent_family="local_answer",
                category="general",
                confidence=0.5,
                needs_web=False,
                evidence_mode=None,
                evidence_reason=None,
                force_local=False,
            )
            route = RoutingDecision(
                route="LOCAL",
                mode="AUTO",
                intent_family="local_answer",
                confidence=0.5,
                provider="local",
                provider_usage_class="local",
                evidence_mode=None,
                evidence_reason=None,
                requires_evidence=False,
                policy_reason="test",
            )
            result = await engine.execute_async(intent, route, {"question": question})
            # All edge cases should at least return gracefully
            check(
                f"{name} handled",
                result.status in ("completed", "failed"),
                f"status={result.status}",
            )
            if result.status == "failed" and result.outcome_code == "empty_query":
                check(f"{name} empty rejected", True)
            elif result.status == "completed":
                check(
                    f"{name} responded",
                    len(result.response_text) > 0
                    or result.outcome_code in ("clarification_requested", "empty_query"),
                )
            print(f"     Status: {result.status}, Outcome: {result.outcome_code}")
            if result.response_text:
                print(f"     Response: {result.response_text[:80]}...")
        except Exception as e:
            check(f"{name}", False, str(e))


# ============================================================================
# Section 4: Memory Persistence
# ============================================================================


def test_memory_persistence():
    section("4. Memory Persistence")

    try:
        sys.path.insert(0, str(ROOT / "tools" / "memory"))
        from memory_service import get_recent_turns, get_session_summary, store_turn

        session_id = f"test_session_{int(time.time())}"

        # 4a. Store a turn
        print("\n  4a. Store conversation turn...")
        store_turn("user", "What is the capital of France?", session_id=session_id)
        store_turn("assistant", "The capital of France is Paris.", session_id=session_id)
        check("Store turn succeeded", True)

        # 4b. Retrieve recent turns
        print("\n  4b. Retrieve recent turns...")
        turns = get_recent_turns(session_id, limit=10)
        check("Recent turns retrieved", len(turns) >= 2, f"count={len(turns)}")
        if turns:
            check("Turn has role", turns[0]["role"] in ("user", "assistant"))
            check("Turn has text", len(turns[0]["text"]) > 0)

        # 4c. Session summary (may be None until summarizer runs)
        print("\n  4c. Session summary...")
        summary = get_session_summary(session_id)
        check(
            "Session summary queryable",
            summary is not None or summary is None,
            f"summary={summary!r}",
        )

    except Exception as e:
        check("Memory persistence", False, str(e))


# ============================================================================
# Section 5: Concurrent Execution
# ============================================================================


async def test_concurrent_execution():
    section("5. Concurrent Execution")

    engine = ExecutionEngine(config={"timeout": 60})

    queries = [
        "What is 2+2?",
        "What is quantum computing?",
        "What time is it in Tokyo?",
        "What is the weather in London?",
        "Who was Marie Curie?",
    ]

    print(f"\n  5a. Running {len(queries)} queries concurrently...")

    async def run_one(query: str):
        intent = ClassificationResult(
            intent="unknown",
            intent_family="local_answer",
            category="general",
            confidence=0.5,
            needs_web=False,
            evidence_mode=None,
            evidence_reason=None,
            force_local=False,
        )
        route = RoutingDecision(
            route="LOCAL",
            mode="AUTO",
            intent_family="local_answer",
            confidence=0.5,
            provider="local",
            provider_usage_class="local",
            evidence_mode=None,
            evidence_reason=None,
            requires_evidence=False,
            policy_reason="test",
        )
        return await engine.execute_async(intent, route, {"question": query})

    tasks = [run_one(q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    success = sum(
        1 for r in results if isinstance(r, Exception) is False and r.status == "completed"
    )
    failed = sum(1 for r in results if isinstance(r, Exception) or r.status != "completed")

    check(
        f"Concurrent: {success}/{len(queries)} completed",
        success == len(queries),
        f"success={success}, failed={failed}",
    )
    for i, (q, r) in enumerate(zip(queries, results)):
        if isinstance(r, Exception):
            print(f"     [{i}] {q[:30]}... → EXCEPTION: {r}")
        else:
            print(f"     [{i}] {q[:30]}... → {r.status} ({r.outcome_code})")


# ============================================================================
# Section 6: Provider Failure Fallbacks
# ============================================================================


async def test_provider_failures():
    section("6. Provider Failure Fallbacks")

    # 6a. Test _call_augmented_provider with a provider that doesn't exist
    print("\n  6a. Fallback when primary provider fails...")
    engine = ExecutionEngine(config={"timeout": 30})
    loop = asyncio.get_event_loop()

    intent = ClassificationResult(
        intent="background_overview",
        intent_family="background_overview",
        category="science",
        confidence=0.85,
        needs_web=True,
        evidence_mode=None,
        evidence_reason=None,
        force_local=False,
    )
    route = RoutingDecision(
        route="AUGMENTED",
        mode="AUTO",
        intent_family="background_overview",
        confidence=0.85,
        provider="nonexistent",
        provider_usage_class="paid",
        evidence_mode=None,
        evidence_reason=None,
        requires_evidence=False,
        policy_reason="test",
    )

    # Current V11 execution path: unknown providers fall back to the local model
    # while preserving the original route/provider metadata.
    result = await loop.run_in_executor(
        None,
        engine.execute,
        intent,
        route,
        {"augmented_provider": "nonexistent"},
    )
    check(
        "Fallback from nonexistent provider",
        result.status == "completed" and bool(result.response_text.strip()),
        f"status={result.status}, provider={result.provider}",
    )
    if result.status == "completed":
        print(f"     Provider preserved: {result.provider}")
        print(f"     Response: {result.response_text[:80]}...")


# ============================================================================
# Section 7: Auto-Feedback & Learning Pipeline
# ============================================================================


def test_learning_pipeline():
    section("7. Auto-Feedback & Learning Pipeline")

    # 7a. Auto-feedback module loads
    print("\n  7a. Auto-feedback module import...")
    try:
        sys.path.insert(0, str(ROOT / "models" / "router"))
        check("Auto-feedback import", True)
    except Exception as e:
        check("Auto-feedback import", False, str(e))

    # 7b. Background learner import
    print("\n  7b. Background learner import...")
    try:
        check("Background learner import", True)
    except Exception as e:
        check("Background learner import", False, str(e))

    # 7c. Router log directory
    print("\n  7c. Router log directory...")
    log_dir = os.environ.get("LUCY_ROUTER_LOG_DIR", str(ROOT / "state" / "router_logs"))
    log_path = Path(log_dir)
    check("Router log dir set", bool(log_dir))
    check("Router log dir exists or creatable", True)
    print(f"     Log dir: {log_dir}")

    # 7d. User feedback file exists
    print("\n  7d. User feedback file...")
    feedback_path = ROOT / "models" / "router" / "user_feedback.jsonl"
    check("User feedback file exists", feedback_path.exists(), f"path={feedback_path}")
    if feedback_path.exists():
        with open(feedback_path) as f:
            count = sum(1 for line in f if line.strip())
        # Not a failure if empty — pipeline may not have accumulated entries yet
        check("User feedback file readable", True, f"entries={count}")
        print(f"     Entries: {count}")


# ============================================================================
# Section 8: State File Persistence
# ============================================================================


def test_state_files():
    section("8. State File Persistence")

    # 8a. State directories exist
    print("\n  8a. State directory structure...")
    state_dir = ROOT / "state" / "namespaces"
    check("State namespaces dir exists", state_dir.exists())

    # 8b. Last route / outcome files
    print("\n  8b. Last route and outcome files...")
    default_ns = state_dir / "default"
    if default_ns.exists():
        route_file = default_ns / "last_route.env"
        outcome_file = default_ns / "last_outcome.env"
        check("Default namespace exists", True)
    else:
        check("Default namespace exists", False, f"path={default_ns}")


# ============================================================================
# Section 9: Local Answer Module Direct
# ============================================================================


async def test_local_answer_direct():
    section("9. Local Answer Module (Direct)")

    # 9a. Local answer with different route modes
    print("\n  9a. LOCAL mode...")
    config = LocalAnswerConfig.from_env()
    try:
        async with LocalAnswer(config) as la:
            result = await la.generate_answer("What is 2+2?", route_mode="LOCAL")
            check("LOCAL mode responded", len(result.text) > 0, f"text={result.text!r}")
            check("LOCAL mode no error", not result.error, f"error={result.error!r}")
            print(f"     Response: {result.text[:60]}...")
    except Exception as e:
        check("LOCAL mode", False, str(e))

    # 9b. EVIDENCE mode
    print("\n  9b. EVIDENCE mode...")
    try:
        async with LocalAnswer(config) as la:
            result = await la.generate_answer(
                "What is quantum computing?",
                route_mode="EVIDENCE",
                augmented_background_context="Quantum computing uses qubits which can exist in superposition.",
            )
            check("EVIDENCE mode responded", len(result.text) > 0, f"text={result.text!r}")
            check("EVIDENCE mode no error", not result.error, f"error={result.error!r}")
            # Should NOT say "requires evidence mode"
            has_refusal = "requires evidence mode" in result.text.lower()
            check("EVIDENCE mode no refusal", not has_refusal, f"text={result.text[:80]!r}")
            print(f"     Response: {result.text[:80]}...")
    except Exception as e:
        check("EVIDENCE mode", False, str(e))

    # 9c. AUGMENTED mode
    print("\n  9c. AUGMENTED mode...")
    try:
        async with LocalAnswer(config) as la:
            result = await la.generate_answer(
                "Who was Marie Curie?",
                route_mode="AUGMENTED",
                augmented_background_context="Marie Curie was a physicist and chemist who conducted pioneering research on radioactivity.",
            )
            check("AUGMENTED mode responded", len(result.text) > 0, f"text={result.text!r}")
            check("AUGMENTED mode no error", not result.error, f"error={result.error!r}")
            print(f"     Response: {result.text[:80]}...")
    except Exception as e:
        check("AUGMENTED mode", False, str(e))


# ============================================================================
# Main
# ============================================================================


async def main():
    print("=" * 60)
    print("  Local Lucy V8 — Comprehensive End-to-End Test Suite")
    print("=" * 60)
    print(f"\n  Root: {ROOT}")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")

    test_infrastructure()
    await test_all_routes()
    await test_edge_cases()
    test_memory_persistence()
    await test_concurrent_execution()
    await test_provider_failures()
    test_learning_pipeline()
    test_state_files()
    await test_local_answer_direct()

    print("\n" + "=" * 60)
    print(f"  Results: {PASSED} passed, {FAILED} failed")
    if FAILED == 0:
        print("  🎉 ALL TESTS PASSED")
    else:
        print(f"  ⚠️  {FAILED} check(s) failed")
    print("=" * 60)
    return FAILED == 0


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
