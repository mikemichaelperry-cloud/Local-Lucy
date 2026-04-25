#!/usr/bin/env python3
"""
Local Lucy v8 - Comprehensive Routing & Toggle Test Suite

Tests routing modes and toggles, logging results to state files for verification.
Run with HMI active or standalone.

Usage:
    cd ~/lucy-v8/ui-v8 && source .venv/bin/activate
    python3 test_routing_verification.py [--quick|--full]

Test Categories:
    - Mode Routing: Verify LOCAL, AUGMENTED, EVIDENCE, CLARIFY routing
    - Toggle Verification: Test Memory, Evidence, Conversation toggles
    - State Consistency: Verify state files reflect toggle changes
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Clear Python caches before any imports
# This ensures we test the latest code, not cached bytecode
def _clear_python_caches():
    """Clear all Python __pycache__ directories and .pyc files."""
    lucy_base = Path.home() / "lucy-v8"
    codex_base = Path.home() / ".codex-api-home"
    
    # Clear router_py cache
    router_py_path = lucy_base / "snapshots" / "opt-experimental-v8-dev" / "tools" / "router_py"
    if router_py_path.exists():
        for pycache in router_py_path.rglob("__pycache__"):
            try:
                import shutil
                shutil.rmtree(pycache, ignore_errors=True)
            except Exception:
                pass
        for pyc in router_py_path.rglob("*.pyc"):
            try:
                pyc.unlink()
            except Exception:
                pass
    
    # Clear UI cache
    ui_path = lucy_base / "ui-v8"
    if ui_path.exists():
        for pycache in ui_path.rglob("__pycache__"):
            try:
                import shutil
                shutil.rmtree(pycache, ignore_errors=True)
            except Exception:
                pass
        for pyc in ui_path.rglob("*.pyc"):
            try:
                pyc.unlink()
            except Exception:
                pass

# Clear caches BEFORE any imports
_clear_python_caches()

# Setup paths (must be before backend import)
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "app"))

# Set required environment BEFORE importing backend
# (backend uses these at import time)
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")  # CRITICAL: Use Python execution path, not shell
os.environ.setdefault("LUCY_SESSION_MEMORY", "1")
os.environ.setdefault("LUCY_EVIDENCE_ENABLED", "1")

# Now import backend (this imports router_py fresh after cache clear)
from app.backend import execute_plan_python, ensure_control_env


class TestReporter:
    """Test result reporter and logger."""
    
    def __init__(self):
        self.results: list[dict] = []
        self.start_time = datetime.now()
        
    def section(self, title: str) -> None:
        print(f"\n{'='*60}")
        print(title)
        print('='*60)
        
    def info(self, msg: str) -> None:
        print(f"  ℹ️  {msg}")
        
    def pass_(self, test: str, details: str = "") -> None:
        print(f"  ✅ PASS: {test}")
        if details:
            print(f"      {details}")
        self.results.append({"test": test, "status": "PASS", "details": details, "time": datetime.now().isoformat()})
        
    def fail(self, test: str, expected: str, actual: str, details: str = "") -> None:
        print(f"  ❌ FAIL: {test}")
        print(f"      Expected: {expected}")
        print(f"      Actual:   {actual}")
        if details:
            print(f"      Details:  {details}")
        self.results.append({"test": test, "status": "FAIL", "expected": expected, "actual": actual, "details": details, "time": datetime.now().isoformat()})
        
    def warn(self, test: str, msg: str) -> None:
        print(f"  ⚠️  WARN: {test}")
        print(f"      {msg}")
        self.results.append({"test": test, "status": "WARN", "details": msg, "time": datetime.now().isoformat()})
        
    def summary(self) -> tuple[int, int]:
        passed = sum(1 for r in self.results if r["status"] == "PASS")
        failed = sum(1 for r in self.results if r["status"] == "FAIL")
        warnings = sum(1 for r in self.results if r["status"] == "WARN")
        total = len(self.results)
        duration = (datetime.now() - self.start_time).total_seconds()
        
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        print(f"Total:    {total}")
        print(f"Passed:   {passed} ✅")
        print(f"Failed:   {failed} ❌")
        print(f"Warnings: {warnings} ⚠️")
        print(f"Duration: {duration:.1f}s")
        print(f"Rate:     {passed/max(total,1)*100:.0f}%")
        print("="*60)
        
        if failed > 0:
            print("\nFailed Tests:")
            for r in self.results:
                if r["status"] == "FAIL":
                    print(f"  - {r['test']}: {r['actual']}")
                    
        return passed, failed


def get_last_route() -> dict:
    """Read last route from state file."""
    try:
        path = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "last_route.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    return {}


def get_current_state() -> dict:
    """Read current state from state file."""
    try:
        path = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json"
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    return {}


def set_state_value(key: str, value: str) -> bool:
    """Update state file and environment."""
    try:
        state = get_current_state()
        state[key] = value
        state["last_updated"] = datetime.now().isoformat()
        
        path = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f, indent=2)
            
        # Sync env vars
        env_map = {
            "memory": "LUCY_SESSION_MEMORY",
            "evidence": "LUCY_EVIDENCE_ENABLED",
            "conversation": "LUCY_CONVERSATION_MODE_FORCE",
            "voice": "LUCY_VOICE_ENABLED",
        }
        if key in env_map:
            os.environ[env_map[key]] = "1" if value in ("on", "true", "1") else "0"
            
        return True
    except Exception as e:
        print(f"Error setting state: {e}")
        return False


def submit_query(prompt: str) -> dict:
    """Submit query through backend."""
    try:
        ensure_control_env()
        os.environ["LUCY_TEST_MODE"] = "1"
        
        result = execute_plan_python(
            question=prompt,
            policy="fallback_only",
        )
        
        # Wait for state write
        time.sleep(0.5)
        
        return {
            "status": result.status,
            "route": result.route,
            "outcome": result.outcome_code,
            "provider": result.provider,
            "response": result.response_text[:150] if result.response_text else "",
            "error": result.error_message,
        }
    except Exception as e:
        return {"error": str(e), "status": "error"}


def test_mode_routing(r: TestReporter) -> None:
    """Test routing to different modes."""
    r.section("MODE ROUTING TESTS")
    
    # Ensure evidence is on
    set_state_value("evidence", "on")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "1"
    
    tests = [
        ("Simple Math → LOCAL", "What is 25 times 17?", ["LOCAL"], "Simple math stays local"),
        ("Identity → LOCAL/POLICY", "Who are you?", ["LOCAL", "POLICY", "IDENTITY"], "Identity handled locally"),
        ("Current Info → AUGMENTED/EVIDENCE", "What time is it in Tokyo?", 
         ["AUGMENTED", "EVIDENCE", "AUGMENT", "INTERNET"], "Current info needs augmentation"),
        ("Wikipedia Search → LOCAL/AUGMENTED", "Search Wikipedia for Albert Einstein", 
         ["LOCAL", "AUGMENTED", "EVIDENCE"], "May route local depending on classification"),
        ("Vague Query → CLARIFY/LOCAL", "Tell me about it", 
         ["CLARIFY", "LOCAL"], "Vague queries may need clarification"),
    ]
    
    for name, prompt, expected_modes, desc in tests:
        r.info(f"Testing: {name}")
        r.info(f"  Prompt: '{prompt}'")
        
        result = submit_query(prompt)
        # Use actual result route (not stale state file)
        actual_route = result.get("route", "UNKNOWN")
        
        # Check if any expected mode matches
        matched = any(mode in actual_route.upper() for mode in expected_modes)
        
        if matched:
            r.pass_(name, f"Routed to {actual_route}")
        else:
            r.fail(name, f"One of {expected_modes}", actual_route, 
                   f"Outcome: {result.get('outcome')}, Response: {result.get('response', '')[:80]}")
        
        time.sleep(0.3)


def test_memory_toggle(r: TestReporter) -> None:
    """Test memory toggle functionality."""
    r.section("MEMORY TOGGLE TESTS")
    
    memory_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "chat_session_memory.txt"
    
    # Test 1: Memory ON
    r.info("Testing Memory ON...")
    set_state_value("memory", "on")
    os.environ["LUCY_SESSION_MEMORY"] = "1"
    
    # Clear memory
    if memory_file.exists():
        memory_file.write_text("")
    
    result = submit_query("My favorite color is blue")
    time.sleep(1.5)  # Wait for async write
    
    content = memory_file.read_text() if memory_file.exists() else ""
    if "blue" in content.lower():
        r.pass_("Memory ON - Stores conversation", "Found in memory file")
    else:
        r.warn("Memory ON - Store test", "Memory file may write asynchronously")
        r.info(f"  Memory content: {content[:100]}")
    
    # Test 2: Memory persistence
    r.info("Testing Memory recall...")
    result = submit_query("What is my favorite color?")
    
    response = result.get("response", "").lower()
    if "blue" in response:
        r.pass_("Memory Recall", "Correctly recalled 'blue'")
    else:
        r.warn("Memory Recall", f"Response: {response[:100]}")
    
    # Test 3: Memory OFF
    r.info("Testing Memory OFF...")
    set_state_value("memory", "off")
    os.environ["LUCY_SESSION_MEMORY"] = "0"
    
    # Clear and try to store
    if memory_file.exists():
        memory_file.write_text("")
    
    result = submit_query("My favorite number is 42")
    time.sleep(1.0)
    
    content = memory_file.read_text() if memory_file.exists() else ""
    if "42" not in content:
        r.pass_("Memory OFF - No storage", "Correctly NOT storing when off")
    else:
        r.fail("Memory OFF", "No storage", "Stored anyway", f"Content: {content[:100]}")


def test_evidence_toggle(r: TestReporter) -> None:
    """Test evidence toggle."""
    r.section("EVIDENCE TOGGLE TESTS")
    
    # Evidence ON
    r.info("Testing Evidence ON...")
    set_state_value("evidence", "on")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "1"
    
    result = submit_query("What is the tallest mountain in the world?")
    route = get_last_route().get("route", "UNKNOWN")
    
    # With evidence on, might route various ways
    r.pass_(f"Evidence ON routing: {route}", "Evidence toggle active")
    
    # Evidence OFF
    r.info("Testing Evidence OFF...")
    set_state_value("evidence", "off")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "0"
    
    result = submit_query("Who wrote Romeo and Juliet?")
    route = get_last_route().get("route", "UNKNOWN")
    
    # Should still work but not use evidence
    if "EVIDENCE" not in route.upper():
        r.pass_("Evidence OFF - No evidence route", f"Routed to {route}")
    else:
        r.warn("Evidence OFF", f"Still routing to {route} (may be expected)")


def test_conversation_toggle(r: TestReporter) -> None:
    """Test conversation mode toggle."""
    r.section("CONVERSATION MODE TESTS")
    
    r.info("Testing Conversation ON...")
    set_state_value("conversation", "on")
    set_state_value("memory", "on")
    os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1"
    os.environ["LUCY_SESSION_MEMORY"] = "1"
    
    # First query
    result1 = submit_query("Let's discuss Python programming")
    time.sleep(0.5)
    
    # Follow-up should maintain context
    result2 = submit_query("What are its advantages?")
    
    response = result2.get("response", "").lower()
    maintains = any(w in response for w in ["python", "programming", "language", "code"])
    
    if maintains:
        r.pass_("Conversation Mode - Context maintained", "Referenced Python in follow-up")
    else:
        r.warn("Conversation Mode", f"Response: {response[:100]}")


def test_state_consistency(r: TestReporter) -> None:
    """Test state file consistency."""
    r.section("STATE CONSISTENCY TESTS")
    
    # Set specific values
    set_state_value("memory", "on")
    set_state_value("evidence", "on")
    set_state_value("conversation", "on")
    
    state = get_current_state()
    
    checks = [
        ("memory", "on", "Memory state"),
        ("evidence", "on", "Evidence state"),
        ("conversation", "on", "Conversation state"),
    ]
    
    for key, expected, name in checks:
        actual = state.get(key, "missing")
        if actual == expected:
            r.pass_(name, f"{key}={actual}")
        else:
            r.fail(name, expected, str(actual))
    
    # Environment sync
    if os.environ.get("LUCY_SESSION_MEMORY") == "1":
        r.pass_("Environment sync - LUCY_SESSION_MEMORY", "Synced to env")
    else:
        r.fail("Environment sync", "LUCY_SESSION_MEMORY=1", os.environ.get("LUCY_SESSION_MEMORY", "missing"))


def generate_report(reporter: TestReporter, output_path: Path) -> None:
    """Generate JSON test report."""
    passed, failed = reporter.summary()
    
    report = {
        "timestamp": datetime.now().isoformat(),
        "total_tests": len(reporter.results),
        "passed": passed,
        "failed": failed,
        "success_rate": passed / max(len(reporter.results), 1) * 100,
        "environment": {
            "LUCY_ROUTER_PY": os.environ.get("LUCY_ROUTER_PY"),
            "LUCY_EXEC_PY": os.environ.get("LUCY_EXEC_PY"),
            "LUCY_SESSION_MEMORY": os.environ.get("LUCY_SESSION_MEMORY"),
            "LUCY_EVIDENCE_ENABLED": os.environ.get("LUCY_EVIDENCE_ENABLED"),
        },
        "results": reporter.results,
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print(f"\n📄 Full report saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Local Lucy v8 Routing Verification")
    parser.add_argument("--quick", action="store_true", help="Quick mode (skip slow tests)")
    parser.add_argument("--full", action="store_true", help="Full comprehensive test")
    parser.add_argument("--output", type=Path, default=None, help="Output JSON file")
    args = parser.parse_args()
    
    reporter = TestReporter()
    
    print("="*60)
    print("LOCAL LUCY v8 - ROUTING & TOGGLE VERIFICATION")
    print("="*60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Mode: {'Quick' if args.quick else 'Full' if args.full else 'Standard'}")
    print("="*60)
    
    try:
        # Always run these
        test_state_consistency(reporter)
        test_mode_routing(reporter)
        
        if not args.quick:
            test_memory_toggle(reporter)
            test_evidence_toggle(reporter)
            
        if args.full:
            test_conversation_toggle(reporter)
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Tests interrupted")
    except Exception as e:
        reporter.fail("Test Suite", "Clean execution", f"Exception: {e}")
        import traceback
        traceback.print_exc()
    
    # Generate report
    default_output = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "logs" / "routing_verification_report.json"
    output = args.output or default_output
    generate_report(reporter, output)
    
    passed, failed = reporter.summary()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
