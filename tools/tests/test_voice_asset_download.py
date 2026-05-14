#!/usr/bin/env python3
"""Tests for tools/voice/download_assets.py — verify-only logic, no network downloads."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "tools" / "voice" / "download_assets.py"

# Import the module directly since it lives outside the package namespace
_spec = importlib.util.spec_from_file_location("download_assets", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
download_assets = importlib.util.module_from_spec(_spec)
sys.modules["download_assets"] = download_assets
_spec.loader.exec_module(download_assets)


class TestFormatSize:
    def test_bytes(self) -> None:
        assert download_assets.format_size(512) == "512 B"

    def test_kilobytes(self) -> None:
        assert download_assets.format_size(1536) == "1.5 KB"

    def test_megabytes(self) -> None:
        assert download_assets.format_size(1024 * 1024 * 2) == "2.0 MB"

    def test_gigabytes(self) -> None:
        assert download_assets.format_size(1024 * 1024 * 1024 * 1.5) == "1.5 GB"


class TestResolveRoot:
    def test_defaults_to_repo_root(self) -> None:
        root = download_assets.resolve_root()
        assert root == REPO_ROOT

    def test_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUCY_ROOT", "/tmp/fake-lucy")
        root = download_assets.resolve_root()
        assert root == Path("/tmp/fake-lucy")


class TestResolveInstallPrefix:
    def test_default_relative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LUCY_VOICE_INSTALL_PREFIX", raising=False)
        prefix = download_assets.resolve_install_prefix()
        assert prefix == REPO_ROOT / "runtime" / "voice"

    def test_env_override_absolute(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUCY_VOICE_INSTALL_PREFIX", "/opt/voice")
        prefix = download_assets.resolve_install_prefix()
        assert prefix == Path("/opt/voice")

    def test_env_override_relative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUCY_VOICE_INSTALL_PREFIX", "custom/voice")
        prefix = download_assets.resolve_install_prefix()
        assert prefix == REPO_ROOT / "custom" / "voice"


class TestVerifyWhisper:
    def test_missing_model(self, tmp_path: Path) -> None:
        result = download_assets.verify_whisper("small.en", tmp_path)
        assert result["component"] == "whisper"
        assert result["model"] == "small.en"
        assert result["exists"] is False
        assert result["size"] == 0
        assert result["size_ok"] is False

    def test_present_model(self, tmp_path: Path) -> None:
        model_path = tmp_path / "models" / "ggml-small.en.bin"
        model_path.parent.mkdir(parents=True)
        model_path.write_bytes(b"x" * 1024)
        result = download_assets.verify_whisper("small.en", tmp_path)
        assert result["exists"] is True
        assert result["size"] == 1024
        # 1024 is not the known size, but it's > 1MB threshold... wait, it's not.
        # size_ok = known is None or size == known or size > 1MB
        # known = 487614201, size = 1024, so size_ok should be False
        assert result["size_ok"] is False

    def test_present_model_correct_size(self, tmp_path: Path) -> None:
        model_path = tmp_path / "models" / "ggml-base.en.bin"
        model_path.parent.mkdir(parents=True)
        # Write exactly the known size
        known_size = download_assets.KNOWN_SIZES["ggml-base.en.bin"]
        model_path.write_bytes(b"x" * known_size)
        result = download_assets.verify_whisper("base.en", tmp_path)
        assert result["exists"] is True
        assert result["size_ok"] is True

    def test_known_size_lookup(self) -> None:
        assert "ggml-small.en.bin" in download_assets.KNOWN_SIZES
        assert download_assets.KNOWN_SIZES["ggml-small.en.bin"] == 487614201


class TestVerifyPiper:
    def test_missing_voice(self, tmp_path: Path) -> None:
        result = download_assets.verify_piper("en_GB-cori-high", tmp_path)
        assert result["component"] == "piper"
        assert result["voice"] == "en_GB-cori-high"
        assert result["complete"] is False
        assert result["onnx_exists"] is False
        assert result["json_exists"] is False

    def test_partial_voice_missing_json(self, tmp_path: Path) -> None:
        onnx_path = tmp_path / "models" / "piper" / "en_GB-cori-high" / "en_GB-cori-high.onnx"
        onnx_path.parent.mkdir(parents=True)
        onnx_path.write_bytes(b"onnx")
        result = download_assets.verify_piper("en_GB-cori-high", tmp_path)
        assert result["onnx_exists"] is True
        assert result["json_exists"] is False
        assert result["complete"] is False

    def test_complete_voice(self, tmp_path: Path) -> None:
        voice_dir = tmp_path / "models" / "piper" / "en_GB-cori-high"
        voice_dir.mkdir(parents=True)
        (voice_dir / "en_GB-cori-high.onnx").write_bytes(b"onnxdata")
        (voice_dir / "en_GB-cori-high.onnx.json").write_bytes(b'{"audio":{"sample_rate":22050}}')
        result = download_assets.verify_piper("en_GB-cori-high", tmp_path)
        assert result["complete"] is True
        assert result["onnx_size"] == 8
        assert result["json_size"] > 0


class TestVerifyKokoro:
    def test_missing_cache(self, tmp_path: Path) -> None:
        result = download_assets.verify_kokoro(tmp_path)
        assert result["component"] == "kokoro"
        assert result["ready"] is False
        assert result["snapshot_path"] is None

    def test_complete_cache(self, tmp_path: Path) -> None:
        cache_home = tmp_path / "cache" / "huggingface"
        repo_cache = cache_home / "hub" / "models--hexgrad--Kokoro-82M"
        snapshot = repo_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}")
        (snapshot / "kokoro-v1_0.pth").write_bytes(b"pth" * 1000)
        (snapshot / "voices").mkdir()
        (snapshot / "voices" / "af_bella.pt").write_bytes(b"pt")
        ref = repo_cache / "refs" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("abc123")

        result = download_assets.verify_kokoro(tmp_path)
        assert result["ready"] is True
        assert len(result["files"]) == 3
        assert result["snapshot_path"] == str(snapshot)

    def test_missing_voice_file(self, tmp_path: Path) -> None:
        cache_home = tmp_path / "cache" / "huggingface"
        repo_cache = cache_home / "hub" / "models--hexgrad--Kokoro-82M"
        snapshot = repo_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("{}")
        (snapshot / "kokoro-v1_0.pth").write_bytes(b"pth" * 1000)
        # Missing voices/af_bella.pt
        ref = repo_cache / "refs" / "main"
        ref.parent.mkdir(parents=True)
        ref.write_text("abc123")

        result = download_assets.verify_kokoro(tmp_path)
        assert result["ready"] is False
        assert any(f["name"] == "voices/af_bella.pt" and not f["exists"] for f in result["files"])


class TestCLI:
    def test_verify_only_json_output(self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("LUCY_VOICE_INSTALL_PREFIX", str(tmp_path))
        # Ensure no real downloads happen by using a temp prefix
        sys.argv = ["download_assets.py", "--verify-only", "--json"]
        rc = download_assets.main()
        captured = capsys.readouterr()
        assert captured.out
        payload = json.loads(captured.out)
        assert payload["prefix"] == str(tmp_path)
        assert len(payload["assets"]) == 3
        # Whisper and Piper should be missing; Kokoro may or may not be present
        assert rc == 2  # Some assets missing

    def test_download_all_no_network(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """--download-all with missing assets should attempt downloads but fail gracefully."""
        monkeypatch.setenv("LUCY_VOICE_INSTALL_PREFIX", str(tmp_path))
        monkeypatch.setenv("LUCY_VOICE_WHISPER_MODEL_URL", "http://localhost:0/invalid")
        monkeypatch.setenv("LUCY_VOICE_PIPER_VOICE_ONNX_URL", "http://localhost:0/invalid")
        monkeypatch.setenv("LUCY_VOICE_PIPER_VOICE_JSON_URL", "http://localhost:0/invalid")
        sys.argv = ["download_assets.py", "--download-all", "--json"]
        rc = download_assets.main()
        # Should return 2 because downloads will fail
        assert rc == 2
