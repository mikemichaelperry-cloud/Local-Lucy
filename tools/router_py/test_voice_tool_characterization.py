#!/usr/bin/env python3
"""Characterization tests for the voice_tool public API.

These tests exercise symbols that are always available (no heavy voice deps).
They must pass before and after the voice_tool.py split.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from router_py.voice import (
    AudioBuffer,
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoicePipelineError,
    VoiceResult,
    clean_text,
    iso_now,
)


def test_clean_text():
    assert clean_text("  hello  ") == "hello"
    assert clean_text(None) == ""
    assert clean_text(123) == "123"


def test_iso_now():
    ts = iso_now()
    assert "T" in ts
    assert ts.endswith("Z")


def test_audio_buffer_duration():
    # 1 second of 16-bit mono 16000 Hz silence
    data = b"\x00" * (16000 * 1 * 2)
    buf = AudioBuffer(data=data, sample_rate=16000, channels=1, sample_width=2)
    assert buf.duration_ms == 1000
    assert buf.frame_count == 16000


def test_transcription_result():
    result = TranscriptionResult(text="hello", backend="whisper")
    assert result.text == "hello"
    assert result.backend == "whisper"


def test_voice_result_defaults():
    result = VoiceResult(
        transcript="hello",
        response_text="hi there",
    )
    assert result.transcript == "hello"
    assert result.response_text == "hi there"
    assert result.success is False


def test_vad_config_defaults():
    cfg = VADConfig()
    assert cfg.enabled is True


def test_voice_metrics_defaults():
    metrics = VoiceMetrics()
    assert metrics.total_latency_ms == 0


def test_exception_hierarchy():
    assert issubclass(RecordingError, VoicePipelineError)
    assert issubclass(TranscriptionError, VoicePipelineError)
    assert issubclass(SynthesisError, VoicePipelineError)
    assert issubclass(PlaybackError, VoicePipelineError)
