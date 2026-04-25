#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKER_SOURCE = REPO_ROOT / "tools" / "voice" / "kokoro_session_worker.py"
sys.path.insert(0, str(REPO_ROOT / "tools"))
sys.path.insert(0, str(REPO_ROOT / "tools" / "voice"))

import tts_adapter


def main() -> int:
    worker = load_worker_module()

    original_resolve_selected_backend = worker.tts_adapter.resolve_selected_backend
    original_resolve_root = worker.tts_adapter.resolve_root
    original_configure_runtime_environment = worker.kokoro_backend.configure_runtime_environment
    original_resolve_lang_code = worker.kokoro_backend.resolve_lang_code
    original_resolve_repo_id = worker.kokoro_backend.resolve_repo_id
    original_resolve_device = worker.kokoro_backend.resolve_device
    original_get_pipeline = worker.kokoro_backend.get_pipeline
    original_synthesize_text = worker.tts_adapter.synthesize_text

    calls: dict[str, object] = {}
    try:
        worker.tts_adapter.resolve_selected_backend = lambda **_: tts_adapter.SelectedBackend(
            engine="kokoro",
            voice="af_heart",
            binary="/tmp/kokoro",
            device="cpu",
            fallback_engine="piper",
        )
        worker.tts_adapter.resolve_root = lambda: Path("/tmp/local-lucy")
        worker.kokoro_backend.configure_runtime_environment = lambda root, env: calls.setdefault("configured", (root, dict(env)))
        worker.kokoro_backend.resolve_lang_code = lambda env, voice: "a"
        worker.kokoro_backend.resolve_repo_id = lambda env: "hexgrad/Kokoro-82M"
        worker.kokoro_backend.resolve_device = lambda env: "cpu"
        worker.kokoro_backend.get_pipeline = lambda **kwargs: calls.setdefault("pipeline", kwargs) or object()

        prewarm = worker.handle_request({"cmd": "prewarm"}, env={"LUCY_VOICE_TTS_ENGINE": "auto"})
        assert_ok(prewarm["ok"] is True, f"expected successful prewarm: {prewarm}")
        assert_ok(prewarm["engine"] == "kokoro", f"unexpected engine: {prewarm}")
        assert_ok(prewarm["prewarmed"] is True, f"expected prewarmed flag: {prewarm}")
        assert_ok(calls.get("pipeline") == {"lang_code": "a", "repo_id": "hexgrad/Kokoro-82M", "device": "cpu"}, f"unexpected pipeline call: {calls}")

        worker.tts_adapter.synthesize_text = lambda **kwargs: {
            "ok": True,
            "engine": "kokoro",
            "wav_path": "/tmp/out.wav",
            "requested_engine": kwargs.get("requested_engine"),
        }
        synth = worker.handle_request(
            {"cmd": "synthesize", "text": "hello world", "output_dir": "/tmp/outdir"},
            env={"LUCY_VOICE_TTS_ENGINE": "auto"},
        )
        assert_ok(synth["ok"] is True, f"expected successful synth response: {synth}")
        assert_ok(synth["engine"] == "kokoro", f"unexpected synth engine: {synth}")
        assert_ok(synth["requested_engine"] == "auto", f"unexpected requested_engine: {synth}")
    finally:
        worker.tts_adapter.resolve_selected_backend = original_resolve_selected_backend
        worker.tts_adapter.resolve_root = original_resolve_root
        worker.kokoro_backend.configure_runtime_environment = original_configure_runtime_environment
        worker.kokoro_backend.resolve_lang_code = original_resolve_lang_code
        worker.kokoro_backend.resolve_repo_id = original_resolve_repo_id
        worker.kokoro_backend.resolve_device = original_resolve_device
        worker.kokoro_backend.get_pipeline = original_get_pipeline
        worker.tts_adapter.synthesize_text = original_synthesize_text

    print("PASS: test_kokoro_session_worker")
    return 0


def load_worker_module():
    with tempfile.TemporaryDirectory(prefix="kokoro_session_worker_"):
        spec = importlib.util.spec_from_file_location("kokoro_session_worker_test_module", WORKER_SOURCE)
        if spec is None or spec.loader is None:
            raise AssertionError(f"unable to load module spec: {WORKER_SOURCE}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
