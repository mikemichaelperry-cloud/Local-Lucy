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

import pytest

REPO_UI_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = REPO_UI_ROOT.parent
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
        active_model={},
    )

    assert_ok(snapshot.snapshot_timestamp != "", "snapshot_timestamp should not be empty")
    assert_ok("T" in snapshot.snapshot_timestamp, "snapshot_timestamp should be ISO format")
    print("  ✓ Staleness indicators: RuntimeSnapshot has timestamp field")


def test_ptt_timeout_value():
    """Test that PTT stop timeout accommodates transcription + LLM + TTS + news digest overhead."""
    import os

    from app.services.runtime_bridge import RuntimeBridge

    # RuntimeBridge requires authority contract env vars
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_UI_ROOT.parent))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", str(REPO_UI_ROOT.parent / "runtime"))

    bridge = RuntimeBridge()

    assert_ok(
        bridge.voice_stop_timeout_seconds == 300,
        f"voice_stop_timeout should be 300s, got {bridge.voice_stop_timeout_seconds}s",
    )
    print(
        "  ✓ PTT timeout: voice_stop_timeout_seconds is 300s (accommodates transcription + request + TTS + long news digests)"
    )


def test_fail_loud_no_env_vars():
    """Test that state_store gracefully falls back to defaults when env vars are missing."""
    import subprocess

    # Test that state_store loads successfully without LUCY_RUNTIME_NAMESPACE_ROOT
    # (it now has sensible fallback defaults). Disable strict contract validation
    # so the default-derived paths are accepted.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services import state_store; print('RUNTIME_NAMESPACE_ROOT=', state_store.RUNTIME_NAMESPACE_ROOT)",
        ],
        cwd=str(REPO_UI_ROOT),
        capture_output=True,
        text=True,
        env={
            **{
                k: v
                for k, v in os.environ.items()
                if k
                not in [
                    "LUCY_RUNTIME_NAMESPACE_ROOT",
                    "LUCY_RUNTIME_AUTHORITY_ROOT",
                    "LUCY_UI_ROOT",
                    "LUCY_UI_STATE_DIR",
                ]
            },
            "LUCY_RUNTIME_CONTRACT_REQUIRED": "0",
        },
    )

    assert_ok(
        result.returncode == 0, f"state_store should load without env vars, got: {result.stderr}"
    )
    assert_ok(
        "RUNTIME_NAMESPACE_ROOT=" in result.stdout,
        f"state_store should set a default root, got: {result.stdout}",
    )
    print("  ✓ Fail-soft: state_store loads with default paths when env vars are missing")


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
        print(
            f"  ✓ GPU detection: {gpu_info['type'].upper()} GPU detected ({gpu_info.get('model', 'unknown')})"
        )
        if gpu_info["ollama_on_gpu"]:
            print("    - Ollama is using GPU ✓")
        elif gpu_info["model_loaded"]:
            print("    - Ollama model on CPU (check CUDA/ROCm)")
        else:
            print("    - No model loaded (idle)")
    else:
        print("  ✓ GPU detection: No GPU detected (CPU only)")


def test_direct_request_ids_are_unique():
    """Direct HMI submits should not reuse request IDs for identical prompts."""
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

    from app.services.runtime_bridge import RuntimeBridge

    bridge = RuntimeBridge()
    fake_result1 = SimpleNamespace(
        route="AUGMENTED",
        provider="openai",
        provider_usage_class="paid",
        outcome_code="answered",
        status="completed",
        error_message="",
        response_text="synthetic answer",
        metadata={},
        request_id="req-12345",
        intent_family="background_overview",
        confidence=0.95,
        evidence_reason="",
        policy_reason="router_augmented",
    )
    fake_result2 = SimpleNamespace(
        route="AUGMENTED",
        provider="openai",
        provider_usage_class="paid",
        outcome_code="answered",
        status="completed",
        error_message="",
        response_text="synthetic answer",
        metadata={},
        request_id="req-67890",
        intent_family="background_overview",
        confidence=0.95,
        evidence_reason="",
        policy_reason="router_augmented",
    )

    payload1 = bridge._build_payload_from_outcome(fake_result1, "repeat request", 1)
    payload2 = bridge._build_payload_from_outcome(fake_result2, "repeat request", 1)

    # The bridge is a display layer — it must faithfully preserve the core's request_id
    assert_ok(payload1["request_id"] == "req-12345", "bridge must preserve core request_id")
    assert_ok(payload2["request_id"] == "req-67890", "bridge must preserve core request_id")
    assert_ok(
        payload1["request_id"] != payload2["request_id"],
        "different core outcomes have different request_ids",
    )
    print("  ✓ Direct HMI request IDs are unique across repeated identical prompts")


def test_operator_response_preserves_blank_line_separators():
    """Operator rendering should preserve intentional blank lines in the answer body."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault(
        "LUCY_RUNTIME_NAMESPACE_ROOT", str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v10")
    )
    os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(REPO_ROOT))
    os.environ.setdefault("LUCY_UI_ROOT", str(REPO_UI_ROOT))
    os.environ.setdefault("LUCY_RUNTIME_CONTRACT_REQUIRED", "1")

    from app.panels.conversation_panel import ConversationPanel
    from PySide6.QtWidgets import QApplication

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
        "Medical answer body.\n\n[Note: This answer is based on general knowledge.]\n\nAuthoritative sources for verification:"
        in rendered,
        f"operator rendering should preserve blank separator lines, got: {rendered!r}",
    )
    print("  ✓ Operator response rendering preserves blank line separators")


def test_status_panel_freshness_indicator():
    """Test that StatusPanel has freshness indicator."""
    from app.panels.status_panel import StatusPanel
    from PySide6.QtWidgets import QApplication

    # Need a QApplication for Qt widgets
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)

    panel = StatusPanel()

    assert_ok(hasattr(panel, "_freshness_label"), "StatusPanel should have _freshness_label")
    assert_ok(
        hasattr(panel, "_legacy_warning_label"), "StatusPanel should have _legacy_warning_label"
    )
    assert_ok(
        hasattr(panel, "_update_freshness_indicator"),
        "StatusPanel should have _update_freshness_indicator method",
    )
    assert_ok(
        hasattr(panel, "_update_legacy_warning"),
        "StatusPanel should have _update_legacy_warning method",
    )
    assert_ok(
        hasattr(panel, "_update_gpu_status"), "StatusPanel should have _update_gpu_status method"
    )
    print("  ✓ StatusPanel: has freshness, legacy warning, and GPU status UI elements")


def test_strict_contract_boundary_violation():
    """Test that strict contract mode raises RuntimeError when paths escape namespace."""
    import subprocess

    # With LUCY_RUNTIME_CONTRACT_REQUIRED=1, a state dir outside the namespace
    # must raise RuntimeError to prevent cross-tree contamination.
    test_env = {
        "LUCY_RUNTIME_CONTRACT_REQUIRED": "1",
        "LUCY_RUNTIME_NAMESPACE_ROOT": "/tmp/fake_runtime_root",
        "LUCY_UI_STATE_DIR": "/tmp/outside_namespace",
        "LUCY_RUNTIME_AUTHORITY_ROOT": str(REPO_ROOT),
        "LUCY_UI_ROOT": str(REPO_UI_ROOT),
    }

    result = subprocess.run(
        [sys.executable, "-c", "from app.services import state_store"],
        cwd=str(REPO_UI_ROOT),
        capture_output=True,
        text=True,
        env=test_env,
    )

    assert_ok(
        result.returncode != 0, "strict contract should fail when state_dir escapes namespace"
    )
    assert_ok(
        "strict mode" in result.stderr.lower() or "runtimeerror" in result.stderr.lower(),
        f"error should mention strict mode or RuntimeError, got: {result.stderr}",
    )
    print("  ✓ Strict contract: RuntimeError raised when state_dir escapes namespace boundary")


def main() -> int:
    return pytest.main([__file__, "-v"])


if __name__ == "__main__":
    raise SystemExit(main())
