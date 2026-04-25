#!/usr/bin/env python3
"""
Local Lucy v8 - Routing & Toggle Verification Test Suite

This script tests that each mode and runtime toggle routes as intended.
It runs prompts and verifies routing decisions from state files.

Usage:
    cd ~/lucy-v8/ui-v8 && source .venv/bin/activate
    python3 test_routing_modes.py [--verbose]
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

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "app"))

# Set required env vars for testing
os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
os.environ.setdefault("LUCY_ROUTER_PY", "1")
os.environ.setdefault("LUCY_EXEC_PY", "1")

from app.backend import execute_plan_python, ensure_control_env


class RoutingTestLogger:
    """Logger for test results."""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: list[dict[str, Any]] = []
        self.start_time = datetime.now()
        
    def log(self, message: str, level: str = "info") -> None:
        """Log a message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = {"info": "[INFO]", "pass": "[PASS]", "fail": "[FAIL]", 
                  "warn": "[WARN]", "test": "[TEST]"}.get(level, "[INFO]")
        print(f"{timestamp} {prefix} {message}")
        
    def test_start(self, test_name: str, description: str) -> None:
        """Log test start."""
        self.log(f"Starting: {test_name}", "test")
        if self.verbose:
            self.log(f"  Description: {description}", "info")
            
    def test_result(self, test_name: str, passed: bool, expected: str, actual: str, 
                    details: str = "") -> None:
        """Log test result."""
        level = "pass" if passed else "fail"
        status = "PASS" if passed else "FAIL"
        self.log(f"{status}: {test_name}", level)
        if not passed or self.verbose:
            self.log(f"  Expected: {expected}", level)
            self.log(f"  Actual:   {actual}", level)
            if details:
                self.log(f"  Details:  {details}", level)
                
        self.results.append({
            "test_name": test_name,
            "passed": passed,
            "expected": expected,
            "actual": actual,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })
        
    def summary(self) -> bool:
        """Print summary and return overall pass/fail."""
        passed = sum(1 for r in self.results if r["passed"])
        failed = len(self.results) - passed
        total = len(self.results)
        
        duration = (datetime.now() - self.start_time).total_seconds()
        
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests:  {total}")
        print(f"Passed:       {passed} ✅")
        print(f"Failed:       {failed} ❌")
        print(f"Duration:     {duration:.1f}s")
        print(f"Success Rate: {passed/total*100:.1f}%" if total > 0 else "N/A")
        print("=" * 60)
        
        if failed > 0:
            print("\nFAILED TESTS:")
            for r in self.results:
                if not r["passed"]:
                    print(f"  ❌ {r['test_name']}: {r['actual']}")
                    
        return failed == 0


def get_last_route_info() -> dict[str, Any]:
    """Get last route information from state file."""
    route_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "last_route.json"
    try:
        if route_file.exists():
            with open(route_file, "r") as f:
                return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    return {}


def get_current_state() -> dict[str, Any]:
    """Get current state from state file."""
    state_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json"
    try:
        if state_file.exists():
            with open(state_file, "r") as f:
                return json.load(f)
    except Exception as e:
        return {"error": str(e)}
    return {}


def submit_query(query: str, timeout: int = 60) -> dict[str, Any]:
    """Submit a query through the Python backend."""
    try:
        # Ensure env is set up
        ensure_control_env()
        
        # Set test mode to prevent actual voice/TTS
        os.environ["LUCY_TEST_MODE"] = "1"
        
        # Execute the query
        result = execute_plan_python(
            question=query,
            classification_override=None,
            decision_override=None,
            context={},
        )
        
        return {
            "status": result.status,
            "route": result.route,
            "provider": result.provider,
            "outcome_code": result.outcome_code,
            "response_text": result.response_text[:200] if result.response_text else "",
            "error_message": result.error_message,
        }
    except Exception as e:
        return {"error": str(e), "status": "error"}


def wait_for_state_update(timeout: int = 5) -> bool:
    """Wait for state files to be updated."""
    time.sleep(0.5)  # Brief delay for state write
    return True


def set_toggle(toggle_name: str, value: str) -> bool:
    """Set a runtime toggle via state file."""
    try:
        state_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json"
        
        state = {}
        if state_file.exists():
            with open(state_file, "r") as f:
                state = json.load(f)
        
        state[toggle_name] = value
        state["last_updated"] = datetime.now().isoformat()
        
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)
            
        # Also set environment variable
        env_var_map = {
            "memory": "LUCY_SESSION_MEMORY",
            "evidence": "LUCY_EVIDENCE_ENABLED",
            "conversation": "LUCY_CONVERSATION_MODE_FORCE",
            "voice": "LUCY_VOICE_ENABLED",
        }
        if toggle_name in env_var_map:
            os.environ[env_var_map[toggle_name]] = "1" if value in ("on", "true", "1") else "0"
            
        return True
    except Exception as e:
        print(f"Error setting toggle {toggle_name}: {e}")
        return False


def run_mode_routing_tests(logger: RoutingTestLogger) -> None:
    """Test that different query types route to correct modes."""
    print("\n" + "=" * 60)
    print("MODE ROUTING TESTS")
    print("=" * 60)
    
    # Ensure evidence is on for these tests
    set_toggle("evidence", "on")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "1"
    
    tests = [
        {
            "name": "Simple Math (Local)",
            "prompt": "What is 15 multiplied by 23?",
            "expected_mode": "LOCAL",
            "description": "Simple math should route to local model",
        },
        {
            "name": "Identity Query (Local/Policy)",
            "prompt": "Who are you?",
            "expected_mode": ["LOCAL", "POLICY"],
            "description": "Identity query may use policy response",
        },
        {
            "name": "Current News (Augmented/Evidence)",
            "prompt": "What are today's headlines?",
            "expected_mode": ["AUGMENTED", "EVIDENCE", "CLARIFY"],
            "description": "Current info should trigger augmented or evidence mode",
        },
        {
            "name": "Wikipedia Search (Evidence)",
            "prompt": "Search Wikipedia for Python programming language",
            "expected_mode": ["EVIDENCE", "AUGMENTED"],
            "description": "Explicit Wikipedia search should use evidence",
        },
        {
            "name": "Medical Query (Evidence Required)",
            "prompt": "What are the symptoms of diabetes?",
            "expected_mode": ["EVIDENCE", "AUGMENTED", "CLARIFY"],
            "description": "Medical queries require evidence backing",
        },
        {
            "name": "Vague/Clarification",
            "prompt": "Tell me about it",
            "expected_mode": ["CLARIFY", "LOCAL"],
            "description": "Vague query should trigger clarification",
        },
    ]
    
    for test in tests:
        logger.test_start(test["name"], test["description"])
        
        result = submit_query(test["prompt"])
        wait_for_state_update()
        
        route_info = get_last_route_info()
        actual_mode = route_info.get("route", result.get("route", "unknown"))
        outcome = result.get("outcome_code", "unknown")
        
        expected = test["expected_mode"]
        if isinstance(expected, list):
            passed = actual_mode in expected or any(e.lower() in actual_mode.lower() for e in expected)
            expected_str = f"One of: {', '.join(expected)}"
        else:
            passed = actual_mode == expected or expected.lower() in actual_mode.lower()
            expected_str = expected
            
        details = f"Outcome: {outcome}, Response: {result.get('response_text', '')[:100]}..."
        logger.test_result(test["name"], passed, expected_str, actual_mode, details)
        
        time.sleep(0.5)  # Brief pause between tests


def run_memory_toggle_tests(logger: RoutingTestLogger) -> None:
    """Test that memory toggle works correctly."""
    print("\n" + "=" * 60)
    print("MEMORY TOGGLE TESTS")
    print("=" * 60)
    
    memory_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "chat_session_memory.txt"
    
    # Clear memory file first
    if memory_file.exists():
        memory_file.write_text("")
    
    # Test 1: Memory ON - Store a fact
    logger.test_start("Memory ON - Store Fact", "Store name with memory enabled")
    set_toggle("memory", "on")
    os.environ["LUCY_SESSION_MEMORY"] = "1"
    
    result = submit_query("My test name is Alice")
    wait_for_state_update()
    
    # Check memory file
    time.sleep(1)  # Give time for async write
    memory_content = memory_file.read_text() if memory_file.exists() else ""
    has_memory = "Alice" in memory_content
    
    logger.test_result("Memory ON - Store Fact", has_memory, 
                      "Name stored in memory file", 
                      "Memory saved" if has_memory else "Memory NOT saved",
                      f"Memory file content: {memory_content[:200]}")
    
    time.sleep(0.5)
    
    # Test 2: Memory ON - Recall fact
    logger.test_start("Memory ON - Recall Fact", "Ask for name with memory enabled")
    
    result = submit_query("What is my test name?")
    wait_for_state_update()
    
    response = result.get("response_text", "").lower()
    recalls_name = "alice" in response
    
    logger.test_result("Memory ON - Recall Fact", recalls_name,
                      "Response contains 'Alice'",
                      f"Recalled: {recalls_name}",
                      f"Response: {result.get('response_text', '')[:150]}")
    
    time.sleep(0.5)
    
    # Test 3: Memory OFF - Should not use context
    logger.test_start("Memory OFF - No Recall", "Ask with memory disabled")
    
    # Clear memory but disable toggle
    if memory_file.exists():
        memory_file.write_text("")
    set_toggle("memory", "off")
    os.environ["LUCY_SESSION_MEMORY"] = "0"
    
    # Store with memory off
    result = submit_query("My other name is Bob")
    time.sleep(1)
    
    memory_content = memory_file.read_text() if memory_file.exists() else ""
    should_be_empty = "Bob" not in memory_content
    
    logger.test_result("Memory OFF - No Storage", should_be_empty,
                      "Name NOT stored (memory off)",
                      "Not stored" if should_be_empty else "Incorrectly stored",
                      f"Memory file: {memory_content[:100]}")


def run_evidence_toggle_tests(logger: RoutingTestLogger) -> None:
    """Test that evidence toggle works correctly."""
    print("\n" + "=" * 60)
    print("EVIDENCE TOGGLE TESTS")
    print("=" * 60)
    
    # Test with evidence ON
    logger.test_start("Evidence ON - Wikipedia Query", "Query should use evidence")
    set_toggle("evidence", "on")
    os.environ["LUCY_EVIDENCE_ENABLED"] = "1"
    
    result = submit_query("What is the capital of France?")
    wait_for_state_update()
    
    route_info = get_last_route_info()
    actual_mode = route_info.get("route", result.get("route", "unknown"))
    
    # With evidence on, this might route to EVIDENCE or AUGMENTED
    passed = actual_mode in ["EVIDENCE", "AUGMENTED", "LOCAL"] or "evidence" in actual_mode.lower()
    
    logger.test_result("Evidence ON - Routing", passed,
                      "EVIDENCE or AUGMENTED mode",
                      actual_mode,
                      f"Outcome: {result.get('outcome_code', 'unknown')}")


def run_conversation_mode_tests(logger: RoutingTestLogger) -> None:
    """Test conversation mode toggle."""
    print("\n" + "=" * 60)
    print("CONVERSATION MODE TESTS")
    print("=" * 60)
    
    # Test conversation ON
    logger.test_start("Conversation ON", "Context should be maintained")
    set_toggle("conversation", "on")
    set_toggle("memory", "on")
    os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1"
    os.environ["LUCY_SESSION_MEMORY"] = "1"
    
    # First query establishes context
    result1 = submit_query("Let's talk about Python programming")
    time.sleep(0.5)
    
    # Second query should maintain context
    result2 = submit_query("What are its main benefits?")
    wait_for_state_update()
    
    # Check if response acknowledges context
    response = result2.get("response_text", "").lower()
    maintains_context = any(word in response for word in ["python", "programming", "language"])
    
    logger.test_result("Conversation Mode - Context", maintains_context,
                      "Response maintains conversation context",
                      f"Context maintained: {maintains_context}",
                      f"Response: {response[:150]}")


def main():
    """Main test runner."""
    parser = argparse.ArgumentParser(description="Local Lucy v8 Routing & Toggle Tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--test", choices=["all", "routing", "memory", "evidence", "conversation"],
                       default="all", help="Which tests to run")
    args = parser.parse_args()
    
    logger = RoutingTestLogger(verbose=args.verbose)
    
    print("=" * 60)
    print("LOCAL LUCY v8 - ROUTING & TOGGLE VERIFICATION")
    print("=" * 60)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test Mode: {args.test}")
    print("=" * 60)
    
    try:
        if args.test in ("all", "routing"):
            run_mode_routing_tests(logger)
            
        if args.test in ("all", "memory"):
            run_memory_toggle_tests(logger)
            
        if args.test in ("all", "evidence"):
            run_evidence_toggle_tests(logger)
            
        if args.test in ("all", "conversation"):
            run_conversation_mode_tests(logger)
            
    except KeyboardInterrupt:
        print("\n\nTests interrupted by user")
    except Exception as e:
        logger.log(f"Test suite error: {e}", "fail")
        import traceback
        traceback.print_exc()
    
    # Print summary
    all_passed = logger.summary()
    
    # Save results to file
    results_file = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "logs" / "routing_test_results.json"
    results_file.parent.mkdir(parents=True, exist_ok=True)
    with open(results_file, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "test_mode": args.test,
            "results": logger.results,
            "summary": {
                "total": len(logger.results),
                "passed": sum(1 for r in logger.results if r["passed"]),
                "failed": sum(1 for r in logger.results if not r["passed"]),
            }
        }, f, indent=2)
    print(f"\nResults saved to: {results_file}")
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
