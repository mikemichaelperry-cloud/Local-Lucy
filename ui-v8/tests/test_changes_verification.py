#!/usr/bin/env python3
"""
Test to verify the changes made in the code review:
1. Staleness indicators (timestamp in RuntimeSnapshot)
2. Silent fallback removal
3. PTT timeout reduction
4. Legacy namespace detection
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_UI_ROOT))


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def test_staleness_indicators():
    """Test that RuntimeSnapshot includes timestamp."""
    from app.services.state_store import RuntimeSnapshot
    
    # Create a minimal RuntimeSnapshot
    snapshot = RuntimeSnapshot(
        top_status={},
        runtime_status={},
        voice_runtime={},
        current_state={},
        file_paths={},
        lifecycle_available=False,
        lifecycle_running=False,
        lifecycle_status="unknown",
        lifecycle_pid=None,
        snapshot_timestamp="2026-04-09T20:00:00+00:00",
        legacy_namespace_detected=False,
        legacy_namespace_path="",
        gpu_info={},
    )
    
    assert_ok(snapshot.snapshot_timestamp != "", "snapshot_timestamp should not be empty")
    assert_ok("T" in snapshot.snapshot_timestamp, "snapshot_timestamp should be ISO format")
    print("  ✓ Staleness indicators: RuntimeSnapshot has timestamp field")


def test_ptt_timeout_value():
    """Test that PTT stop timeout accommodates transcription + LLM + TTS + news digest overhead."""
    from app.services.runtime_bridge import RuntimeBridge
    
    bridge = RuntimeBridge()
    
    assert_ok(bridge.voice_stop_timeout_seconds == 300, 
              f"voice_stop_timeout should be 300s, got {bridge.voice_stop_timeout_seconds}s")
    print("  ✓ PTT timeout: voice_stop_timeout_seconds is 300s (accommodates transcription + request + TTS + long news digests)")

def test_fail_loud_no_env_vars():
    """Test that missing env vars cause RuntimeError."""
    import subprocess
    
    # Test that state_store fails without LUCY_RUNTIME_NAMESPACE_ROOT
    result = subprocess.run(
        ["python3", "-c", "from app.services import state_store"],
        cwd=str(REPO_UI_ROOT),
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k not in [
            "LUCY_RUNTIME_NAMESPACE_ROOT", "LUCY_RUNTIME_AUTHORITY_ROOT", "LUCY_UI_ROOT"
        ]},
    )
    
    assert_ok(result.returncode != 0, "state_store should fail without env vars")
    assert_ok("missing required" in result.stderr.lower(), 
              f"error should mention 'missing required', got: {result.stderr}")
    print("  ✓ Fail-loud: state_store raises RuntimeError without LUCY_RUNTIME_NAMESPACE_ROOT")


def test_legacy_namespace_detection():
    """Test that legacy namespace detection works."""
    from app.services.state_store import _detect_legacy_namespace
    
    # This test depends on the actual filesystem state
    detected, path = _detect_legacy_namespace()
    
    if detected:
        assert_ok(path != "", "legacy path should be non-empty when detected")
        print(f"  ✓ Legacy namespace: detected at {path}")
    else:
        print("  ✓ Legacy namespace: not detected (expected if no legacy dir)")


def test_gpu_detection():
    """Test that GPU detection works."""
    from app.services.state_store import _detect_gpu_status
    
    gpu_info = _detect_gpu_status()
    
    # Should return a dict with expected keys
    assert_ok(isinstance(gpu_info, dict), "gpu_info should be a dict")
    assert_ok("available" in gpu_info, "gpu_info should have 'available' key")
    assert_ok("type" in gpu_info, "gpu_info should have 'type' key")
    assert_ok("ollama_on_gpu" in gpu_info, "gpu_info should have 'ollama_on_gpu' key")
    assert_ok("model_loaded" in gpu_info, "gpu_info should have 'model_loaded' key")
    
    if gpu_info["available"]:
        print(f"  ✓ GPU detection: {gpu_info['type'].upper()} GPU detected ({gpu_info.get('model', 'unknown')})")
        if gpu_info["ollama_on_gpu"]:
            print(f"    - Ollama is using GPU ✓")
        elif gpu_info["model_loaded"]:
            print(f"    - Ollama model on CPU (check CUDA/ROCm)")
        else:
            print(f"    - No model loaded (idle)")
    else:
        print("  ✓ GPU detection: No GPU detected (CPU only)")


def test_direct_request_ids_are_unique():
    """Direct HMI submits should not reuse request IDs for identical prompts."""
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev")
    os.environ.setdefault("LUCY_UI_ROOT", "/home/mike/lucy-v8/ui-v8")
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()
    fake_result = SimpleNamespace(
        route="AUGMENTED",
        provider="openai",
        provider_usage_class="paid",
        outcome_code="answered",
        status="completed",
        error_message="",
        response_text="synthetic answer",
        metadata={},
    )

    payload1 = bridge._build_payload_from_result(
        result=fake_result,
        route_data={"strategy": "AUGMENTED", "metadata": {}},
        outcome_data={},
        request_text="repeat request",
        execution_time_ms=1,
    )
    payload2 = bridge._build_payload_from_result(
        result=fake_result,
        route_data={"strategy": "AUGMENTED", "metadata": {}},
        outcome_data={},
        request_text="repeat request",
        execution_time_ms=1,
    )

    assert_ok(payload1["request_id"] != payload2["request_id"], "direct submit request IDs must be unique")
    print("  ✓ Direct HMI request IDs are unique across repeated identical prompts")


def test_operator_response_preserves_blank_line_separators():
    """Operator rendering should preserve intentional blank lines in the answer body."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v8/snapshots/opt-experimental-v8-dev")
    os.environ.setdefault("LUCY_UI_ROOT", "/home/mike/lucy-v8/ui-v8")
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

    from PySide6.QtWidgets import QApplication
    from app.panels.conversation_panel import ConversationPanel

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    panel = ConversationPanel()
    rendered = panel._operator_response_text(
        {
            "response_text": (
                "Medical answer body.\n\n\n"
                "[Note: This answer is based on general knowledge.]\n\n\n"
                "Authoritative sources for verification:\n"
                "- example.com"
            ),
            "outcome": {},
        }
    )

    assert_ok(
        "Medical answer body.\n\n[Note: This answer is based on general knowledge.]\n\nAuthoritative sources for verification:" in rendered,
        f"operator rendering should preserve blank separator lines, got: {rendered!r}",
    )
    print("  ✓ Operator response rendering preserves blank line separators")


def test_status_panel_freshness_indicator():
    """Test that StatusPanel has freshness indicator."""
    from PySide6.QtWidgets import QApplication
    from app.panels.status_panel import StatusPanel
    
    # Need a QApplication for Qt widgets
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    panel = StatusPanel()
    
    assert_ok(hasattr(panel, '_freshness_label'), "StatusPanel should have _freshness_label")
    assert_ok(hasattr(panel, '_legacy_warning_label'), "StatusPanel should have _legacy_warning_label")
    assert_ok(hasattr(panel, '_update_freshness_indicator'), 
              "StatusPanel should have _update_freshness_indicator method")
    assert_ok(hasattr(panel, '_update_legacy_warning'), 
              "StatusPanel should have _update_legacy_warning method")
    assert_ok(hasattr(panel, '_update_gpu_status'), 
              "StatusPanel should have _update_gpu_status method")
    print("  ✓ StatusPanel: has freshness, legacy warning, and GPU status UI elements")


def main() -> int:
    print("Running verification tests for code review changes...")
    print()
    
    # Set up required environment for tests that need it
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", "/home/mike/lucy-v8")
    os.environ.setdefault("LUCY_UI_ROOT", "/home/mike/lucy-v8/ui-v8")
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")
    
    print("Test 1: Staleness indicators")
    test_staleness_indicators()
    
    print("Test 2: PTT timeout value")
    test_ptt_timeout_value()
    
    print("Test 3: Fail-loud behavior (no env vars)")
    test_fail_loud_no_env_vars()
    
    print("Test 4: Legacy namespace detection")
    test_legacy_namespace_detection()
    
    print("Test 5: GPU detection")
    test_gpu_detection()
    
    print("Test 6: Direct request IDs are unique")
    test_direct_request_ids_are_unique()

    print("Test 7: Operator response preserves blank separators")
    test_operator_response_preserves_blank_line_separators()

    print("Test 8: StatusPanel freshness indicator")
    test_status_panel_freshness_indicator()
    
    print()
    print("=" * 50)
    print("ALL VERIFICATION TESTS PASSED")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
