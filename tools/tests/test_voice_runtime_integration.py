#!/usr/bin/env python3
"""
Integration tests for runtime_voice.py voice pipeline.

Mocks all external dependencies (recorders, STT, TTS, request pipeline)
and tests the full voice turn lifecycle through runtime_voice.py functions.

Run with: pytest tools/tests/test_voice_runtime_integration.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "router_py"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "voice"))

import runtime_voice as rv


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------


@pytest.fixture
def tmp_runtime(tmp_path: Path):
    """Provide isolated temp paths for voice runtime state files."""
    runtime_file = tmp_path / "state" / "voice_runtime.json"
    state_file = tmp_path / "state" / "current_state.json"
    capture_dir = tmp_path / "voice" / "ui_ptt"
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    capture_dir.mkdir(parents=True, exist_ok=True)

    # Default state: voice=on, mode=auto
    state_file.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "profile": "test-profile",
                "mode": "auto",
                "memory": "on",
                "evidence": "on",
                "voice": "on",
                "model": "local-lucy",
                "approval_required": False,
                "status": "ready",
                "last_updated": "2026-05-31T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    # Default voice runtime
    runtime_file.write_text(
        json.dumps(rv.default_voice_runtime()) + "\n", encoding="utf-8"
    )

    return {
        "root": tmp_path,
        "runtime_file": runtime_file,
        "state_file": state_file,
        "capture_dir": capture_dir,
    }


@pytest.fixture
def mock_backend():
    """Provide a fully-available mock VoiceBackend."""
    return rv.VoiceBackend(
        available=True,
        recorder_engine="arecord",
        recorder_bin="/usr/bin/arecord",
        stt_engine="whisper",
        stt_bin="/usr/bin/whisper",
        stt_device="gpu",
        tts_engine="kokoro",
        tts_bin="kokoro",
        tts_device="cuda",
        audio_player="paplay",
        reason="ready",
    )


# -----------------------------------------------------------------------------
# Voice runtime state transitions
# -----------------------------------------------------------------------------


class TestVoiceRuntimeStateTransitions:
    def test_ptt_start_transitions_to_listening(self, tmp_runtime, mock_backend):
        """ptt-start should set listening=True, status=listening."""
        with patch.object(rv, "detect_backend", return_value=mock_backend):
            with patch.object(rv, "start_recorder", return_value=MagicMock(pid=12345)):
                payload = rv.handle_ptt_start(
                    tmp_runtime["runtime_file"],
                    tmp_runtime["state_file"],
                    tmp_runtime["capture_dir"],
                )

        assert payload["listening"] is True
        assert payload["status"] == "listening"
        assert payload["record_pid"] == 12345
        assert payload["last_error"] == ""

        # Verify persisted state
        persisted = json.loads(tmp_runtime["runtime_file"].read_text(encoding="utf-8"))
        assert persisted["listening"] is True
        assert persisted["status"] == "listening"

    def test_ptt_stop_when_not_listening(self, tmp_runtime, mock_backend):
        """ptt-stop when not listening should raise RuntimeVoiceExit."""
        with patch.object(rv, "detect_backend", return_value=mock_backend):
            with pytest.raises(rv.RuntimeVoiceExit) as exc_info:
                rv.handle_ptt_stop(
                    tmp_runtime["runtime_file"],
                    tmp_runtime["state_file"],
                    tmp_runtime["capture_dir"],
                )
        assert exc_info.value.exit_code == rv.PTT_STOP_NOT_LISTENING

    def test_ptt_stop_no_audio(self, tmp_runtime, mock_backend):
        """ptt-stop with no audio should return no_transcript."""
        # Pre-seed listening state
        runtime = rv.load_voice_runtime_locked(tmp_runtime["runtime_file"])
        runtime["listening"] = True
        runtime["record_pid"] = 12345
        runtime["capture_path"] = str(tmp_runtime["capture_dir"] / "empty.wav")
        rv.write_voice_runtime(tmp_runtime["runtime_file"], runtime)

        with patch.object(rv, "is_process_running", return_value=True):
            with patch.object(rv, "detect_backend", return_value=mock_backend):
                with patch.object(rv, "stop_recorder"):
                    payload = rv.handle_ptt_stop(
                        tmp_runtime["runtime_file"],
                        tmp_runtime["state_file"],
                        tmp_runtime["capture_dir"],
                    )

        assert payload["status"] == "no_transcript"
        assert payload["transcript"] == ""

        # Verify state reset to idle
        persisted = rv.load_voice_runtime_locked(tmp_runtime["runtime_file"])
        assert persisted["listening"] is False
        assert persisted["processing"] is False
        assert persisted["status"] == "idle"

    def test_ptt_stop_successful_transcription(self, tmp_runtime, mock_backend):
        """Full turn: ptt-start → record → ptt-stop → transcript → idle."""
        capture_path = tmp_runtime["capture_dir"] / "test.wav"
        # Create a valid WAV file so existence check passes
        _write_dummy_wav(capture_path)

        runtime = rv.load_voice_runtime_locked(tmp_runtime["runtime_file"])
        runtime["listening"] = True
        runtime["record_pid"] = 12345
        runtime["capture_path"] = str(capture_path)
        rv.write_voice_runtime(tmp_runtime["runtime_file"], runtime)

        with patch.object(rv, "is_process_running", return_value=True):
            with patch.object(rv, "detect_backend", return_value=mock_backend):
                with patch.object(rv, "stop_recorder"):
                    with patch.object(
                        rv, "transcribe_capture", return_value=rv.TranscriptionResult(text="Hello Lucy")
                    ):
                        payload = rv.handle_ptt_stop(
                            tmp_runtime["runtime_file"],
                            tmp_runtime["state_file"],
                            tmp_runtime["capture_dir"],
                        )

        assert payload["status"] == "completed"
        assert payload["transcript"] == "Hello Lucy"

        persisted = rv.load_voice_runtime_locked(tmp_runtime["runtime_file"])
        assert persisted["listening"] is False
        assert persisted["processing"] is False
        assert persisted["status"] == "idle"
        assert persisted["last_transcript"] == "Hello Lucy"


# -----------------------------------------------------------------------------
# Transcription fallback
# -----------------------------------------------------------------------------


class TestTranscriptionFallback:
    def test_transcribe_with_whisper_gpu_fallback_to_cpu(self, tmp_path, monkeypatch):
        """Whisper GPU failure with CUDA error should retry with CPU."""
        wav_path = tmp_path / "test.wav"
        _write_dummy_wav(wav_path)

        call_count = 0

        def fake_run(cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First call: GPU fails with CUDA OOM
                result.returncode = 1
                result.stdout = ""
                result.stderr = "CUDA out of memory: failed to allocate GPU memory"
            elif call_count == 2:
                # Second call: CPU succeeds
                result.returncode = 0
                result.stdout = "Hello from CPU fallback"
                result.stderr = ""
            else:
                result.returncode = 0
                result.stdout = ""
                result.stderr = ""
            return result

        monkeypatch.setattr(rv.subprocess, "run", fake_run)
        monkeypatch.setattr(rv, "ensure_whisper_worker", lambda *a, **k: None)
        monkeypatch.setattr(rv, "stop_whisper_worker", lambda *a, **k: None)

        # Need a fake whisper binary path
        fake_whisper = tmp_path / "whisper"
        fake_whisper.write_text("#!/bin/sh\necho mock")
        fake_whisper.chmod(0o755)

        result = rv.transcribe_with_whisper(str(fake_whisper), wav_path)

        assert result.text == "Hello from CPU fallback"
        assert result.backend == "cpu"
        assert result.fallback_used is True
        assert "cuda" in result.fallback_reason.lower()

    def test_transcribe_with_whisper_non_gpu_error_no_fallback(self, tmp_path, monkeypatch):
        """Non-GPU whisper error should NOT trigger CPU fallback."""
        wav_path = tmp_path / "test.wav"
        _write_dummy_wav(wav_path)

        def fake_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 1
            result.stdout = ""
            result.stderr = "File not found: invalid_model.bin"
            return result

        monkeypatch.setattr(rv.subprocess, "run", fake_run)
        monkeypatch.setattr(rv, "ensure_whisper_worker", lambda *a, **k: None)
        monkeypatch.setattr(rv, "stop_whisper_worker", lambda *a, **k: None)

        fake_whisper = tmp_path / "whisper"
        fake_whisper.write_text("#!/bin/sh\necho mock")
        fake_whisper.chmod(0o755)

        with pytest.raises(rv.RuntimeVoiceExit) as exc_info:
            rv.transcribe_with_whisper(str(fake_whisper), wav_path)
        assert exc_info.value.exit_code == rv.PTT_STOP_TRANSCRIBE_FAILED

    def test_normalize_transcript_strips_whitespace_and_timestamps(self):
        """normalize_transcript should strip whitespace and timestamp lines."""
        assert rv.normalize_transcript("  hello   world  ") == "hello world"
        assert rv.normalize_transcript("line1\nline2") == "line1 line2"
        assert rv.normalize_transcript("[00:00:00.000 --> 00:00:05.000]") == ""

    def test_transcribe_capture_filters_silence_markers(self, monkeypatch):
        """transcribe_capture should return empty text for silence markers."""
        monkeypatch.setattr(rv, "transcribe_with_whisper", lambda _bin, _path: rv.TranscriptionResult(text="[BLANK_AUDIO]"))
        result = rv.transcribe_capture(
            rv.VoiceBackend(
                available=True, recorder_engine="arecord", recorder_bin="",
                stt_engine="whisper", stt_bin="whisper", stt_device="gpu",
                tts_engine="none", tts_bin="", tts_device="none",
                audio_player="none", reason="ready",
            ),
            Path("/dev/null"),
        )
        assert result.text == ""


# -----------------------------------------------------------------------------
# TTS text processing
# -----------------------------------------------------------------------------


class TestTtsTextProcessing:
    def test_sanitize_tts_text_strips_html(self):
        """sanitize_tts_text should strip HTML tags and decode entities."""
        raw = (
            "<p>Hello &amp; welcome!</p>\n"
            "<a href='http://example.com'>click here</a>\n"
            "<script>alert(1)</script>\n"
            "More text with &#39;quotes&#39;"
        )
        cleaned = rv.sanitize_tts_text(raw)
        assert "<p>" not in cleaned
        assert "<script>" not in cleaned
        assert "alert(1)" not in cleaned
        assert "click here" in cleaned
        assert "'quotes'" in cleaned
        assert "http://example.com" not in cleaned

    def test_sanitize_tts_text_strips_urls(self):
        """sanitize_tts_text should remove raw URLs."""
        raw = "Visit https://example.com/path for more info"
        cleaned = rv.sanitize_tts_text(raw)
        assert "https://example.com/path" not in cleaned
        assert "Visit" in cleaned
        assert "for more info" in cleaned

    def test_split_tts_chunks_respects_max_chars(self):
        """split_tts_chunks should not exceed max chunk size."""
        text = "One. Two. Three. Four. Five. Six."
        chunks = rv.split_tts_chunks(text)
        for chunk in chunks:
            assert len(chunk) <= rv.resolve_tts_chunk_max_chars(multiline="\n" in text)

    def test_truncate_tts_text_cleanly(self):
        """truncate_tts_text_cleanly should cut at sentence boundary."""
        text = "First sentence. Second sentence. Third sentence."
        truncated = rv.truncate_tts_text_cleanly(text, 35)
        # Should end at a sentence boundary
        assert truncated.endswith(".")
        assert len(truncated) <= 35

    def test_ensure_terminal_list_punctuation(self):
        """ensure_terminal_list_punctuation should add terminal punctuation."""
        assert rv.ensure_terminal_list_punctuation("hello").endswith("...")
        assert rv.ensure_terminal_list_punctuation("hello.").endswith("..")
        assert rv.ensure_terminal_list_punctuation("hello...") == "hello..."


# -----------------------------------------------------------------------------
# Voice runtime normalization / helpers
# -----------------------------------------------------------------------------


class TestVoiceRuntimeHelpers:
    def test_default_voice_runtime_structure(self):
        """default_voice_runtime should return all required v2 fields."""
        state = rv.default_voice_runtime()
        assert state["schema_version"] == 2
        assert "available" in state
        assert "listening" in state
        assert "processing" in state
        assert "status" in state
        assert "stt_backend" in state
        assert "stt_fallback_reason" in state

    def test_normalize_voice_runtime_migrates_v1(self):
        """normalize_voice_runtime should add missing v2 fields."""
        v1 = {
            "schema_version": 1,
            "available": True,
            "listening": False,
            "status": "idle",
        }
        migrated = rv.normalize_voice_runtime(v1)
        assert migrated["schema_version"] == 2
        assert "stt_backend" in migrated
        assert "stt_fallback_reason" in migrated
        assert migrated["available"] is True

    def test_normalize_voice_runtime_sanitizes(self):
        """normalize_voice_runtime should coerce types and strip whitespace."""
        dirty = {
            "available": "yes",
            "listening": 1,
            "record_pid": "12345",
            "status": "  idle  ",
            "last_error": "  some error  ",
        }
        cleaned = rv.normalize_voice_runtime(dirty)
        assert cleaned["available"] is True  # truthy string → bool
        assert cleaned["listening"] is True  # truthy int → bool
        assert cleaned["record_pid"] == 12345
        assert cleaned["status"] == "idle"
        assert cleaned["last_error"] == "some error"

    def test_is_process_running(self):
        """is_process_running should handle None, invalid, and real PIDs."""
        assert rv.is_process_running(None) is False
        assert rv.is_process_running(-1) is False
        assert rv.is_process_running(0) is False
        # PID 1 (init) should be running on Linux
        assert rv.is_process_running(1) is True
        # A very high PID is unlikely to exist
        assert rv.is_process_running(99999999) is False

    def test_build_turn_payload(self):
        """build_turn_payload should include request when provided."""
        payload = rv.build_turn_payload("completed", "hello", None, "")
        assert payload["status"] == "completed"
        assert payload["transcript"] == "hello"
        assert "request" not in payload

        with_request = rv.build_turn_payload(
            "completed", "hello", {"response_text": "hi"}, ""
        )
        assert with_request["request"]["response_text"] == "hi"


# -----------------------------------------------------------------------------
# Backend detection
# -----------------------------------------------------------------------------


class TestBackendDetection:
    def test_detect_backend_all_missing(self, monkeypatch):
        """detect_backend with no binaries should report missing components."""
        monkeypatch.setattr(rv.shutil, "which", lambda x: None)
        backend = rv.detect_backend()
        assert backend.available is False
        assert "missing" in backend.reason.lower()

    def test_detect_backend_with_recorder_only(self, monkeypatch):
        """detect_backend with only recorder should still be unavailable."""
        def fake_which(cmd):
            if cmd == "arecord":
                return "/usr/bin/arecord"
            return None

        monkeypatch.setattr(rv.shutil, "which", fake_which)
        # Also block bundled whisper discovery
        monkeypatch.setattr(rv, "bundled_whisper_runtime_ready", lambda _root: False)
        backend = rv.detect_backend()
        assert backend.available is False
        assert backend.recorder_engine == "arecord"
        assert "stt" in backend.reason.lower() or "missing" in backend.reason.lower()


# -----------------------------------------------------------------------------
# PCM / audio level helpers
# -----------------------------------------------------------------------------


class TestAudioLevelHelpers:
    def test_pcm_level_silence(self):
        """pcm_level of silence should be 0."""
        assert rv.pcm_level(b"\x00" * 1024) == 0

    def test_pcm_level_max(self):
        """pcm_level of full-scale square wave should be high."""
        import struct
        # 16-bit full-scale samples (little-endian)
        data = struct.pack("<h", 32767) * 512
        level = rv.pcm_level(data)
        assert level > 90

    def test_write_audio_levels_roundtrip(self, tmp_path):
        """write_audio_levels should persist readable levels."""
        levels_file = tmp_path / "levels.json"
        rv.write_audio_levels(levels_file, input_level=42, output_level=7, recording=True)
        payload = rv.read_audio_levels(levels_file)
        assert payload["input_level"] == 42
        assert payload["output_level"] == 7
        assert payload["recording"] is True


# -----------------------------------------------------------------------------
# Utility helpers
# -----------------------------------------------------------------------------


def _write_dummy_wav(path: Path) -> None:
    """Write a minimal valid WAV file."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00" * 32000)  # 1 second of silence
