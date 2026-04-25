#!/usr/bin/env python3
"""Test Memory Toggle - verifies memory system works as expected.

The memory toggle controls whether session context is passed to the model.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "router_py"))

RUNTIME_V8 = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"
STATE_FILE = RUNTIME_V8 / "state" / "current_state.json"
MEMORY_FILE = RUNTIME_V8 / "state" / "chat_session_memory.txt"
LUCY_V8 = Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"
RUNTIME_CONTROL = LUCY_V8 / "tools" / "runtime_control.py"


def set_memory_toggle(value: str):
    """Set memory toggle via runtime_control."""
    result = subprocess.run(
        [sys.executable, str(RUNTIME_CONTROL), "set-memory", "--value", value],
        capture_output=True, text=True
    )
    return result.returncode == 0


def get_state():
    """Get current state."""
    with open(STATE_FILE) as f:
        return json.load(f)


def write_memory(content: str):
    """Write fake memory to memory file."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(content)


def read_memory():
    """Read memory file."""
    if MEMORY_FILE.exists():
        return MEMORY_FILE.read_text()
    return ""


def clear_memory():
    """Clear memory file."""
    if MEMORY_FILE.exists():
        MEMORY_FILE.unlink()


def test_memory_toggle_basic():
    """Test that memory toggle updates state file."""
    print("="*60)
    print("TEST 1: Memory Toggle - State File Update")
    print("="*60)
    
    # Save original state
    original = get_state()
    
    # Test ON
    print("\nSetting memory to ON...")
    assert set_memory_toggle("on"), "Failed to set memory ON"
    time.sleep(0.5)
    state = get_state()
    assert state["memory"] == "on", f"Expected memory=on, got {state['memory']}"
    print("✓ State file shows memory=on")
    
    # Test OFF
    print("\nSetting memory to OFF...")
    assert set_memory_toggle("off"), "Failed to set memory OFF"
    time.sleep(0.5)
    state = get_state()
    assert state["memory"] == "off", f"Expected memory=off, got {state['memory']}"
    print("✓ State file shows memory=off")
    
    # Restore original
    with open(STATE_FILE, "w") as f:
        json.dump(original, f, indent=2)
    print("\n✓ TEST 1 PASSED")


def test_memory_env_var():
    """Test that memory toggle sets env var correctly."""
    print("\n" + "="*60)
    print("TEST 2: Memory Toggle - Environment Variable")
    print("="*60)
    
    # Save original state
    original = get_state()
    
    # Test ON
    print("\nSetting memory to ON...")
    set_memory_toggle("on")
    time.sleep(0.5)
    
    # Check env var via runtime_control
    result = subprocess.run(
        [sys.executable, str(RUNTIME_CONTROL), "print-env"],
        capture_output=True, text=True,
        env=os.environ.copy()
    )
    env_output = result.stdout
    
    if "LUCY_SESSION_MEMORY=1" in env_output:
        print("✓ LUCY_SESSION_MEMORY=1 when memory=on")
    else:
        print("✗ Expected LUCY_SESSION_MEMORY=1")
        print(f"Env output: {env_output}")
        return False
    
    # Test OFF
    print("\nSetting memory to OFF...")
    set_memory_toggle("off")
    time.sleep(0.5)
    
    result = subprocess.run(
        [sys.executable, str(RUNTIME_CONTROL), "print-env"],
        capture_output=True, text=True,
        env=os.environ.copy()
    )
    env_output = result.stdout
    
    if "LUCY_SESSION_MEMORY=0" in env_output:
        print("✓ LUCY_SESSION_MEMORY=0 when memory=off")
    else:
        print("✗ Expected LUCY_SESSION_MEMORY=0")
        return False
    
    # Restore original
    with open(STATE_FILE, "w") as f:
        json.dump(original, f, indent=2)
    print("\n✓ TEST 2 PASSED")
    return True


def test_memory_file_operations():
    """Test that memory file is written and read correctly."""
    print("\n" + "="*60)
    print("TEST 3: Memory File Operations")
    print("="*60)
    
    # Clear any existing memory
    clear_memory()
    
    # Test writing memory
    print("\nWriting test memory...")
    test_content = "User: What is Python?\nAssistant: Python is a programming language.\n\n"
    write_memory(test_content)
    
    # Verify it was written
    content = read_memory()
    assert content == test_content, f"Memory content mismatch"
    print("✓ Memory file written correctly")
    
    # Verify it can be read
    assert "Python" in content, "Expected 'Python' in memory"
    print("✓ Memory file read correctly")
    
    # Clean up
    clear_memory()
    print("\n✓ TEST 3 PASSED")
    return True


def test_memory_context_in_prompt():
    """Test that memory context is included in prompt when enabled."""
    print("\n" + "="*60)
    print("TEST 4: Memory Context in Prompt (Integration)")
    print("="*60)
    
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    
    # Save original state
    original = get_state()
    
    # Test with memory ON
    print("\n1. Testing with memory=ON...")
    set_memory_toggle("on")
    
    # Create test memory
    test_memory = "User: My dog's name is Oscar.\nAssistant: Got it. Oscar is your dog.\n\n"
    
    config = LocalAnswerConfig()
    answer = LocalAnswer(config)
    
    # Build prompt with memory
    prompt = answer._build_prompt(
        query="Who is my dog?",
        session_memory=test_memory,
        generation_profile="chat",
        budget_instruction="",
        conversation_mode_active=False,
        conversation_system_block=False
    )
    
    if "Session memory" in prompt and "Oscar" in prompt:
        print("✓ Memory context included in prompt when enabled")
    else:
        print("✗ Memory context NOT included in prompt")
        print(f"Prompt: {prompt[:500]}")
        return False
    
    # Test with memory OFF (should not include)
    print("\n2. Testing with memory=OFF...")
    set_memory_toggle("off")
    
    prompt_no_memory = answer._build_prompt(
        query="Who is my dog?",
        session_memory="",  # Empty memory
        generation_profile="chat",
        budget_instruction="",
        conversation_mode_active=False,
        conversation_system_block=False
    )
    
    if "Session memory" not in prompt_no_memory:
        print("✓ Memory context NOT included when disabled")
    else:
        print("✗ Memory context included when disabled")
        return False
    
    # Restore original state
    with open(STATE_FILE, "w") as f:
        json.dump(original, f, indent=2)
    print("\n✓ TEST 4 PASSED")
    return True


def test_memory_unsafe_queries():
    """Test that memory is excluded for backchannel/vague queries."""
    print("\n" + "="*60)
    print("TEST 5: Memory Safety - Backchannel Queries")
    print("="*60)
    
    from router_py.local_answer import LocalAnswer, LocalAnswerConfig
    
    answer = LocalAnswer(LocalAnswerConfig())
    
    # Test backchannel queries (should not allow memory context)
    backchannel_queries = [
        "Hmm",
        "Okay",
        "Thanks",
        "Ugh",
    ]
    
    print("\nTesting backchannel queries (memory should be disabled)...")
    for query in backchannel_queries:
        allowed = answer._is_memory_context_allowed(query)
        if not allowed:
            print(f"✓ '{query}' - memory correctly DISABLED")
        else:
            print(f"✗ '{query}' - memory should be disabled")
            return False
    
    # Test normal queries (should allow memory)
    normal_queries = [
        "What is Python?",
        "Tell me about your dog",
        "How do I bake bread?",
        "What are the side effects of ibuprofen?",  # Medical is still allowed for memory
    ]
    
    print("\nTesting normal queries (memory should be enabled)...")
    for query in normal_queries:
        allowed = answer._is_memory_context_allowed(query)
        if allowed:
            print(f"✓ '{query[:40]}...' - memory correctly ENABLED")
        else:
            print(f"✗ '{query[:40]}...' - memory should be enabled")
            return False
    
    print("\n✓ TEST 5 PASSED")
    return True


def main():
    print("\n" + "="*60)
    print("MEMORY TOGGLE TEST SUITE")
    print("="*60)
    
    # Set required env vars
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(LUCY_V8))
    os.environ.setdefault("LUCY_UI_ROOT", str(Path.home() / "lucy-v8" / "ui-v8"))
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(RUNTIME_V8))
    
    tests = [
        ("State File Update", test_memory_toggle_basic),
        ("Environment Variable", test_memory_env_var),
        ("Memory File Operations", test_memory_file_operations),
        ("Memory in Prompt", test_memory_context_in_prompt),
        ("Memory Safety", test_memory_unsafe_queries),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"\n✗ TEST FAILED: {name}")
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n✓ ALL TESTS PASSED - Memory toggle is working correctly!")
        return 0
    else:
        print(f"\n✗ {failed} test(s) failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
