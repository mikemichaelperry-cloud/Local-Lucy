#!/usr/bin/env python3
"""Comprehensive end-to-end test for Control Panel Runtime toggles.

Tests all runtime toggles and their interactions:
- Mode (auto/online/offline)
- Conversation (on/off)
- Memory (on/off)
- Evidence (on/off)
- Voice (on/off)
- Augmentation policy (disabled/fallback_only/direct_allowed)
- Augmented provider (wikipedia/grok/openai)
"""

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "router_py"))


class ToggleTestError(Exception):
    pass


class RuntimeToggleTester:
    """Test harness for runtime toggles."""
    
    def __init__(self):
        self.root = Path(os.environ.get(
            "LUCY_RUNTIME_AUTHORITY_ROOT",
            os.environ.get("LUCY_ROOT", str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
        ))
        self.runtime_control = self.root / "tools" / "runtime_control.py"
        self.state_file = Path(os.environ.get(
            "LUCY_RUNTIME_STATE_FILE",
            str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json")
        ))
        self.results = []
        
    def run_control_command(self, command: str, value: str = None) -> dict:
        """Run a runtime_control.py command."""
        cmd = [sys.executable, str(self.runtime_control), command]
        if value:
            cmd.extend(["--value", value])
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise ToggleTestError(f"Command failed: {command} {value}\n{result.stderr}")
        
        # Parse success output
        try:
            # Try to parse JSON from output
            lines = result.stdout.strip().split('\n')
            for line in lines:
                if line.startswith('{'):
                    return json.loads(line)
            # If no JSON, return raw output
            return {"raw": result.stdout}
        except json.JSONDecodeError:
            return {"raw": result.stdout}
    
    def get_current_state(self) -> dict:
        """Get current runtime state."""
        result = subprocess.run(
            [sys.executable, str(self.runtime_control), "show-state"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise ToggleTestError(f"Failed to get state: {result.stderr}")
        return json.loads(result.stdout)
    
    def set_state(self, field: str, value: str) -> dict:
        """Set a state field."""
        command_map = {
            "mode": "set-mode",
            "conversation": "set-conversation",
            "memory": "set-memory",
            "evidence": "set-evidence",
            "voice": "set-voice",
            "augmentation_policy": "set-augmentation",
            "augmented_provider": "set-augmented-provider",
        }
        return self.run_control_command(command_map[field], value)
    
    def test_toggle(self, name: str, field: str, values: list[str], check_env: bool = True) -> dict:
        """Test a toggle with multiple values."""
        print(f"\n{'='*60}")
        print(f"Testing: {name}")
        print(f"{'='*60}")
        
        results = {"name": name, "field": field, "tests": []}
        
        for value in values:
            try:
                print(f"\n  Setting {field} = {value}...")
                result = self.set_state(field, value)
                
                # Verify state was updated
                state = self.get_current_state()
                actual_value = state.get(field)
                
                success = actual_value == value
                test_result = {
                    "value": value,
                    "expected": value,
                    "actual": actual_value,
                    "success": success
                }
                
                if success:
                    print(f"  ✓ {field} = {actual_value}")
                else:
                    print(f"  ✗ Expected {value}, got {actual_value}")
                    
                results["tests"].append(test_result)
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results["tests"].append({
                    "value": value,
                    "error": str(e),
                    "success": False
                })
        
        return results
    
    def test_mode_toggle(self) -> dict:
        """Test mode toggle (auto/online/offline)."""
        return self.test_toggle(
            "Mode Toggle",
            "mode",
            ["auto", "online", "offline", "auto"]
        )
    
    def test_conversation_toggle(self) -> dict:
        """Test conversation toggle (on/off)."""
        return self.test_toggle(
            "Conversation Toggle",
            "conversation",
            ["on", "off", "on"]
        )
    
    def test_memory_toggle(self) -> dict:
        """Test memory toggle (on/off)."""
        return self.test_toggle(
            "Memory Toggle",
            "memory",
            ["on", "off", "off", "on"]
        )
    
    def test_evidence_toggle(self) -> dict:
        """Test evidence toggle (on/off)."""
        return self.test_toggle(
            "Evidence Toggle",
            "evidence",
            ["on", "off", "on"]
        )
    
    def test_voice_toggle(self) -> dict:
        """Test voice toggle (on/off)."""
        return self.test_toggle(
            "Voice Toggle",
            "voice",
            ["on", "off", "on"]
        )
    
    def test_augmentation_policy(self) -> dict:
        """Test augmentation policy toggle."""
        return self.test_toggle(
            "Augmentation Policy",
            "augmentation_policy",
            ["disabled", "fallback_only", "direct_allowed", "disabled"]
        )
    
    def test_augmented_provider(self) -> dict:
        """Test augmented provider toggle."""
        return self.test_toggle(
            "Augmented Provider",
            "augmented_provider",
            ["wikipedia", "grok", "openai", "wikipedia"]
        )
    
    def test_interaction_evidence_augmentation(self) -> dict:
        """Test interaction: Evidence + Augmentation policy."""
        print(f"\n{'='*60}")
        print("Testing Interaction: Evidence + Augmentation Policy")
        print(f"{'='*60}")
        
        results = {"name": "Evidence + Augmentation", "tests": []}
        
        # Test combinations
        combinations = [
            ("on", "direct_allowed"),
            ("off", "direct_allowed"),
            ("on", "disabled"),
            ("off", "disabled"),
            ("on", "fallback_only"),
        ]
        
        for evidence, augmentation in combinations:
            try:
                print(f"\n  Setting evidence={evidence}, augmentation={augmentation}...")
                self.set_state("evidence", evidence)
                self.set_state("augmentation_policy", augmentation)
                
                state = self.get_current_state()
                
                success = (
                    state.get("evidence") == evidence and
                    state.get("augmentation_policy") == augmentation
                )
                
                if success:
                    print(f"  ✓ evidence={state['evidence']}, augmentation={state['augmentation_policy']}")
                else:
                    print(f"  ✗ Mismatch: got evidence={state.get('evidence')}, augmentation={state.get('augmentation_policy')}")
                
                results["tests"].append({
                    "evidence": evidence,
                    "augmentation": augmentation,
                    "success": success
                })
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results["tests"].append({
                    "evidence": evidence,
                    "augmentation": augmentation,
                    "error": str(e),
                    "success": False
                })
        
        return results
    
    def test_interaction_voice_mode(self) -> dict:
        """Test interaction: Voice + Mode."""
        print(f"\n{'='*60}")
        print("Testing Interaction: Voice + Mode")
        print(f"{'='*60}")
        
        results = {"name": "Voice + Mode", "tests": []}
        
        combinations = [
            ("on", "auto"),
            ("off", "auto"),
            ("on", "offline"),
            ("off", "offline"),
            ("on", "online"),
        ]
        
        for voice, mode in combinations:
            try:
                print(f"\n  Setting voice={voice}, mode={mode}...")
                self.set_state("voice", voice)
                self.set_state("mode", mode)
                
                state = self.get_current_state()
                
                success = (
                    state.get("voice") == voice and
                    state.get("mode") == mode
                )
                
                if success:
                    print(f"  ✓ voice={state['voice']}, mode={state['mode']}")
                else:
                    print(f"  ✗ Mismatch: got voice={state.get('voice')}, mode={state.get('mode')}")
                
                results["tests"].append({
                    "voice": voice,
                    "mode": mode,
                    "success": success
                })
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results["tests"].append({
                    "voice": voice,
                    "mode": mode,
                    "error": str(e),
                    "success": False
                })
        
        return results
    
    def test_env_variable_propagation(self) -> dict:
        """Test that toggles propagate to environment variables."""
        print(f"\n{'='*60}")
        print("Testing Environment Variable Propagation")
        print(f"{'='*60}")
        
        results = {"name": "Env Variable Propagation", "tests": []}
        
        # Set specific states and check env output
        test_cases = [
            ("evidence", "on", "LUCY_EVIDENCE_ENABLED", "1"),
            ("evidence", "off", "LUCY_EVIDENCE_ENABLED", "0"),
            ("voice", "on", "LUCY_VOICE_ENABLED", "1"),
            ("voice", "off", "LUCY_VOICE_ENABLED", "0"),
        ]
        
        for field, value, env_var, expected in test_cases:
            try:
                print(f"\n  Setting {field}={value}, checking {env_var}...")
                self.set_state(field, value)
                
                # Get env output
                result = subprocess.run(
                    [sys.executable, str(self.runtime_control), "print-env"],
                    capture_output=True, text=True
                )
                
                env_output = result.stdout
                actual = None
                for line in env_output.split('\n'):
                    if line.startswith(f"{env_var}="):
                        actual = line.split('=', 1)[1]
                        break
                
                success = actual == expected
                
                if success:
                    print(f"  ✓ {env_var}={actual}")
                else:
                    print(f"  ✗ Expected {env_var}={expected}, got {actual}")
                
                results["tests"].append({
                    "field": field,
                    "value": value,
                    "env_var": env_var,
                    "expected": expected,
                    "actual": actual,
                    "success": success
                })
                
            except Exception as e:
                print(f"  ✗ Error: {e}")
                results["tests"].append({
                    "field": field,
                    "value": value,
                    "env_var": env_var,
                    "error": str(e),
                    "success": False
                })
        
        return results
    
    def run_all_tests(self) -> dict:
        """Run all toggle tests."""
        print("\n" + "="*60)
        print("RUNTIME TOGGLES - COMPREHENSIVE TEST SUITE")
        print("="*60)
        
        # Store initial state
        initial_state = self.get_current_state()
        print(f"\nInitial state: {json.dumps(initial_state, indent=2)}")
        
        all_results = []
        
        # Run individual toggle tests
        all_results.append(self.test_mode_toggle())
        all_results.append(self.test_conversation_toggle())
        all_results.append(self.test_memory_toggle())
        all_results.append(self.test_evidence_toggle())
        all_results.append(self.test_voice_toggle())
        all_results.append(self.test_augmentation_policy())
        all_results.append(self.test_augmented_provider())
        
        # Run interaction tests
        all_results.append(self.test_interaction_evidence_augmentation())
        all_results.append(self.test_interaction_voice_mode())
        
        # Run env propagation test
        all_results.append(self.test_env_variable_propagation())
        
        # Restore initial state
        print(f"\n{'='*60}")
        print("Restoring Initial State")
        print(f"{'='*60}")
        for field, value in initial_state.items():
            if field in ["mode", "conversation", "memory", "evidence", "voice", "augmentation_policy", "augmented_provider"]:
                try:
                    self.set_state(field, value)
                    print(f"  Restored {field} = {value}")
                except Exception as e:
                    print(f"  Failed to restore {field}: {e}")
        
        # Calculate summary
        total_tests = sum(len(r["tests"]) for r in all_results)
        passed_tests = sum(
            sum(1 for t in r["tests"] if t.get("success", False))
            for r in all_results
        )
        
        summary = {
            "total_tests": total_tests,
            "passed": passed_tests,
            "failed": total_tests - passed_tests,
            "success_rate": f"{(passed_tests/total_tests*100):.1f}%" if total_tests > 0 else "N/A",
            "results": all_results
        }
        
        # Print summary
        print(f"\n{'='*60}")
        print("TEST SUMMARY")
        print(f"{'='*60}")
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {summary['success_rate']}")
        
        return summary


def main():
    tester = RuntimeToggleTester()
    results = tester.run_all_tests()
    
    # Return non-zero if any tests failed
    failed = results["failed"]
    if failed > 0:
        print(f"\n❌ {failed} test(s) failed")
        return 1
    else:
        print("\n✓ All tests passed")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
