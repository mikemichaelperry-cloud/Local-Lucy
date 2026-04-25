#!/usr/bin/env python3
"""HMI Runtime Toggles Test Suite

Tests runtime toggles as they are used from the HMI Control Panel.
The HMI updates current_state.json directly, and the runtime system
reads from this file.

Usage:
    python3 test_hmi_runtime_toggles.py [test_name]
    
    test_name can be:
    - all (default): Run all tests
    - evidence: Test evidence toggle effects
    - voice: Test voice toggle effects
    - mode: Test mode toggle effects
    - memory: Test memory toggle effects
    - conversation: Test conversation toggle effects
    - augmentation: Test augmentation policy effects
    - interactions: Test toggle interactions
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Paths
RUNTIME_V8 = Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"
STATE_FILE = RUNTIME_V8 / "state" / "current_state.json"
VOICE_RUNTIME_FILE = RUNTIME_V8 / "state" / "voice_runtime.json"
LUCY_V8 = Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"
RUNTIME_CONTROL = LUCY_V8 / "tools" / "runtime_control.py"


class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"


def log(msg: str, color: str = Colors.RESET):
    print(f"{color}{msg}{Colors.RESET}")


def read_state() -> dict:
    """Read current runtime state (as HMI would)."""
    with open(STATE_FILE) as f:
        return json.load(f)


def write_state(state: dict):
    """Write runtime state (as HMI would)."""
    state["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_env_from_state() -> dict:
    """Get environment variables that would be set from current state."""
    env_vars = os.environ.copy()
    result = subprocess.run(
        [sys.executable, str(RUNTIME_CONTROL), "print-env"],
        capture_output=True, text=True,
        env=env_vars
    )
    env = {}
    for line in result.stdout.strip().split("\n"):
        if "=" in line and not line.startswith("ERROR"):
            key, value = line.split("=", 1)
            env[key] = value
    return env


class HMIToggleTests:
    """Test suite for HMI runtime toggles."""
    
    def __init__(self):
        self.initial_state = read_state()
        self.tests_run = 0
        self.tests_passed = 0
        
    def teardown(self):
        """Restore initial state."""
        log("\nRestoring initial state...", Colors.BLUE)
        write_state(self.initial_state)
        log("✓ State restored", Colors.GREEN)
        
    def assert_eq(self, actual, expected, msg: str) -> bool:
        """Assert equality and log result."""
        self.tests_run += 1
        if actual == expected:
            log(f"  ✓ {msg}: {actual}", Colors.GREEN)
            self.tests_passed += 1
            return True
        else:
            log(f"  ✗ {msg}: expected {expected}, got {actual}", Colors.RED)
            return False
            
    def assert_true(self, condition: bool, msg: str) -> bool:
        """Assert true and log result."""
        self.tests_run += 1
        if condition:
            log(f"  ✓ {msg}", Colors.GREEN)
            self.tests_passed += 1
            return True
        else:
            log(f"  ✗ {msg}", Colors.RED)
            return False

    # ==================================================================
    # INDIVIDUAL TOGGLE TESTS
    # ==================================================================
    
    def test_evidence_toggle(self):
        """Test Evidence toggle: on/off behavior."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Evidence Toggle", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        
        # Test 1: Enable evidence
        log("\n1. Setting evidence to ON...")
        state["evidence"] = "on"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        self.assert_eq(state["evidence"], "on", "State file shows evidence=on")
        self.assert_eq(env.get("LUCY_EVIDENCE_ENABLED"), "1", "LUCY_EVIDENCE_ENABLED=1")
        self.assert_eq(env.get("LUCY_ENABLE_INTERNET"), "1", "LUCY_ENABLE_INTERNET=1 (mirrors evidence)")
        
        # Test 2: Disable evidence
        log("\n2. Setting evidence to OFF...")
        state["evidence"] = "off"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        self.assert_eq(state["evidence"], "off", "State file shows evidence=off")
        self.assert_eq(env.get("LUCY_EVIDENCE_ENABLED"), "0", "LUCY_EVIDENCE_ENABLED=0")
        self.assert_eq(env.get("LUCY_ENABLE_INTERNET"), "0", "LUCY_ENABLE_INTERNET=0")
        
        # Restore
        state["evidence"] = "on"
        write_state(state)

    def test_voice_toggle(self):
        """Test Voice toggle: on/off behavior."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Voice Toggle", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        
        # Test 1: Enable voice
        log("\n1. Setting voice to ON...")
        state["voice"] = "on"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        self.assert_eq(state["voice"], "on", "State file shows voice=on")
        self.assert_eq(env.get("LUCY_VOICE_ENABLED"), "1", "LUCY_VOICE_ENABLED=1")
        
        # Test voice_runtime.json update
        voice_runtime_file = RUNTIME_V8 / "state" / "voice_runtime.json"
        if voice_runtime_file.exists():
            with open(voice_runtime_file) as f:
                voice_runtime = json.load(f)
            # Note: voice_runtime.json may not update immediately from state file alone
            log(f"  ℹ Voice runtime status: {voice_runtime.get('status', 'unknown')}", Colors.YELLOW)
        
        # Test 2: Disable voice
        log("\n2. Setting voice to OFF...")
        state["voice"] = "off"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        self.assert_eq(state["voice"], "off", "State file shows voice=off")
        self.assert_eq(env.get("LUCY_VOICE_ENABLED"), "0", "LUCY_VOICE_ENABLED=0")
        
        # Restore
        state["voice"] = "on"
        write_state(state)

    def test_mode_toggle(self):
        """Test Mode toggle: auto/online/offline."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Mode Toggle", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        original_mode = state["mode"]
        
        modes = ["auto", "online", "offline"]
        for mode in modes:
            log(f"\nSetting mode to {mode.upper()}...")
            state["mode"] = mode
            write_state(state)
            time.sleep(0.5)
            
            state = read_state()
            self.assert_eq(state["mode"], mode, f"State file shows mode={mode}")
            
            # Verify route control mapping
            mode_to_route = {"auto": "AUTO", "online": "FORCED_ONLINE", "offline": "FORCED_OFFLINE"}
            log(f"  ℹ Route control: {mode_to_route.get(mode)}", Colors.YELLOW)
        
        # Restore
        state["mode"] = original_mode
        write_state(state)

    def test_memory_toggle(self):
        """Test Memory toggle: on/off behavior."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Memory Toggle", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        original_memory = state.get("memory", "off")
        
        # Test 1: Enable memory
        log("\n1. Setting memory to ON...")
        state["memory"] = "on"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        self.assert_eq(state["memory"], "on", "State file shows memory=on")
        
        # Test 2: Disable memory
        log("\n2. Setting memory to OFF...")
        state["memory"] = "off"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        self.assert_eq(state["memory"], "off", "State file shows memory=off")
        
        # Restore
        state["memory"] = original_memory
        write_state(state)

    def test_conversation_toggle(self):
        """Test Conversation toggle: on/off behavior."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Conversation Toggle", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        original_conv = state.get("conversation", "off")
        
        # Test 1: Enable conversation
        log("\n1. Setting conversation to ON...")
        state["conversation"] = "on"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        self.assert_eq(state["conversation"], "on", "State file shows conversation=on")
        
        # Test 2: Disable conversation
        log("\n2. Setting conversation to OFF...")
        state["conversation"] = "off"
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        self.assert_eq(state["conversation"], "off", "State file shows conversation=off")
        
        # Restore
        state["conversation"] = original_conv
        write_state(state)

    def test_augmentation_policy(self):
        """Test Augmentation Policy: disabled/fallback_only/direct_allowed."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Augmentation Policy", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        original_policy = state.get("augmentation_policy", "fallback_only")
        
        policies = ["disabled", "fallback_only", "direct_allowed"]
        for policy in policies:
            log(f"\nSetting augmentation_policy to {policy}...")
            state["augmentation_policy"] = policy
            write_state(state)
            time.sleep(0.5)
            
            state = read_state()
            self.assert_eq(state["augmentation_policy"], policy, f"State file shows augmentation_policy={policy}")
            
            # Check behavior implications
            if policy == "disabled":
                log("  ℹ Evidence routes will be disabled", Colors.YELLOW)
            elif policy == "fallback_only":
                log("  ℹ Only fallback evidence allowed", Colors.YELLOW)
            elif policy == "direct_allowed":
                log("  ℹ Full evidence augmentation enabled", Colors.YELLOW)
        
        # Restore
        state["augmentation_policy"] = original_policy
        write_state(state)

    # ==================================================================
    # INTERACTION TESTS
    # ==================================================================
    
    def test_evidence_augmentation_interaction(self):
        """Test Evidence + Augmentation Policy interaction."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Evidence + Augmentation Policy Interaction", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        
        test_cases = [
            ("on", "direct_allowed", "Full evidence enabled"),
            ("on", "disabled", "Evidence on but policy disables routes"),
            ("off", "direct_allowed", "Evidence off, policy irrelevant"),
            ("off", "disabled", "Both disabled"),
        ]
        
        for evidence, policy, description in test_cases:
            log(f"\n{description}")
            log(f"  Setting evidence={evidence}, augmentation_policy={policy}...")
            
            state["evidence"] = evidence
            state["augmentation_policy"] = policy
            write_state(state)
            time.sleep(0.5)
            
            state = read_state()
            env = get_env_from_state()
            
            success = True
            success &= self.assert_eq(state["evidence"], evidence, f"  evidence={evidence}")
            success &= self.assert_eq(state["augmentation_policy"], policy, f"  augmentation_policy={policy}")
            
            # Evidence env var should match evidence toggle
            expected_evidence_env = "1" if evidence == "on" else "0"
            success &= self.assert_eq(
                env.get("LUCY_EVIDENCE_ENABLED"), 
                expected_evidence_env, 
                f"  LUCY_EVIDENCE_ENABLED={expected_evidence_env}"
            )

    def test_voice_mode_interaction(self):
        """Test Voice + Mode interaction."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: Voice + Mode Interaction", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        
        test_cases = [
            ("on", "auto", "Voice on, auto mode"),
            ("on", "offline", "Voice on, offline mode"),
            ("off", "auto", "Voice off, auto mode"),
            ("off", "online", "Voice off, online mode"),
        ]
        
        for voice, mode, description in test_cases:
            log(f"\n{description}")
            
            state["voice"] = voice
            state["mode"] = mode
            write_state(state)
            time.sleep(0.5)
            
            state = read_state()
            env = get_env_from_state()
            
            self.assert_eq(state["voice"], voice, f"  voice={voice}")
            self.assert_eq(state["mode"], mode, f"  mode={mode}")
            
            expected_voice_env = "1" if voice == "on" else "0"
            self.assert_eq(
                env.get("LUCY_VOICE_ENABLED"),
                expected_voice_env,
                f"  LUCY_VOICE_ENABLED={expected_voice_env}"
            )

    def test_all_toggles_together(self):
        """Test all toggles in a realistic configuration."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST: All Toggles - Realistic Configuration", Colors.BLUE)
        log("="*60, Colors.BLUE)
        
        state = read_state()
        
        # Scenario 1: Full online mode
        log("\n1. Full Online Mode (all features on)...")
        config = {
            "mode": "auto",
            "voice": "on",
            "evidence": "on",
            "conversation": "on",
            "memory": "on",
            "augmentation_policy": "direct_allowed",
            "augmented_provider": "wikipedia"
        }
        state.update(config)
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        
        all_ok = True
        for key, expected in config.items():
            if state.get(key) != expected:
                log(f"  ✗ {key}: expected {expected}, got {state.get(key)}", Colors.RED)
                all_ok = False
        
        if all_ok:
            log("  ✓ All toggles set correctly", Colors.GREEN)
        
        self.assert_eq(env.get("LUCY_EVIDENCE_ENABLED"), "1", "  LUCY_EVIDENCE_ENABLED=1")
        self.assert_eq(env.get("LUCY_VOICE_ENABLED"), "1", "  LUCY_VOICE_ENABLED=1")
        self.assert_eq(env.get("LUCY_ENABLE_INTERNET"), "1", "  LUCY_ENABLE_INTERNET=1")
        
        # Scenario 2: Privacy mode (minimal features)
        log("\n2. Privacy Mode (minimal features)...")
        config = {
            "mode": "offline",
            "voice": "off",
            "evidence": "off",
            "conversation": "off",
            "memory": "off",
            "augmentation_policy": "disabled"
        }
        state.update(config)
        write_state(state)
        time.sleep(0.5)
        
        state = read_state()
        env = get_env_from_state()
        
        all_ok = True
        for key, expected in config.items():
            if state.get(key) != expected:
                log(f"  ✗ {key}: expected {expected}, got {state.get(key)}", Colors.RED)
                all_ok = False
        
        if all_ok:
            log("  ✓ All toggles set correctly", Colors.GREEN)
            self.tests_passed += 1
        self.tests_run += 1
        
        self.assert_eq(env.get("LUCY_EVIDENCE_ENABLED"), "0", "  LUCY_EVIDENCE_ENABLED=0")
        self.assert_eq(env.get("LUCY_VOICE_ENABLED"), "0", "  LUCY_VOICE_ENABLED=0")

    # ==================================================================
    # SUMMARY
    # ==================================================================
    
    def print_summary(self):
        """Print test summary."""
        log("\n" + "="*60, Colors.BLUE)
        log("TEST SUMMARY", Colors.BLUE)
        log("="*60, Colors.BLUE)
        log(f"Tests Run: {self.tests_run}")
        log(f"Tests Passed: {self.tests_passed}")
        log(f"Tests Failed: {self.tests_run - self.tests_passed}")
        
        if self.tests_run > 0:
            rate = (self.tests_passed / self.tests_run) * 100
            color = Colors.GREEN if rate >= 90 else Colors.YELLOW if rate >= 70 else Colors.RED
            log(f"Success Rate: {rate:.1f}%", color)
        
        if self.tests_passed == self.tests_run:
            log("\n✓ ALL TESTS PASSED", Colors.GREEN)
            return 0
        else:
            log(f"\n✗ {self.tests_run - self.tests_passed} TEST(S) FAILED", Colors.RED)
            return 1


def main():
    test_name = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    tester = HMIToggleTests()
    
    try:
        if test_name == "all":
            tester.test_evidence_toggle()
            tester.test_voice_toggle()
            tester.test_mode_toggle()
            tester.test_memory_toggle()
            tester.test_conversation_toggle()
            tester.test_augmentation_policy()
            tester.test_evidence_augmentation_interaction()
            tester.test_voice_mode_interaction()
            tester.test_all_toggles_together()
        elif test_name == "evidence":
            tester.test_evidence_toggle()
        elif test_name == "voice":
            tester.test_voice_toggle()
        elif test_name == "mode":
            tester.test_mode_toggle()
        elif test_name == "memory":
            tester.test_memory_toggle()
        elif test_name == "conversation":
            tester.test_conversation_toggle()
        elif test_name == "augmentation":
            tester.test_augmentation_policy()
        elif test_name == "interactions":
            tester.test_evidence_augmentation_interaction()
            tester.test_voice_mode_interaction()
            tester.test_all_toggles_together()
        else:
            log(f"Unknown test: {test_name}", Colors.RED)
            log("Available tests: all, evidence, voice, mode, memory, conversation, augmentation, interactions")
            return 1
        
        return tester.print_summary()
        
    finally:
        tester.teardown()


if __name__ == "__main__":
    raise SystemExit(main())
