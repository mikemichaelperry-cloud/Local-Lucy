#!/usr/bin/env python3
"""Voice pipeline data models."""

from __future__ import annotations

import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Union


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    backend: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""


@dataclass
class AudioBuffer:
    """Container for raw PCM audio data with metadata.

    Attributes:
        data: Raw PCM audio bytes
        sample_rate: Sample rate in Hz (e.g., 16000)
        channels: Number of channels (1 for mono, 2 for stereo)
        sample_width: Bytes per sample (2 for 16-bit)
    """

    data: bytes
    sample_rate: int
    channels: int
    sample_width: int

    @property
    def duration_ms(self) -> int:
        """Calculate duration in milliseconds from data length."""
        if self.sample_rate <= 0 or self.channels <= 0 or self.sample_width <= 0:
            return 0
        frames = len(self.data) // (self.channels * self.sample_width)
        return int(frames * 1000 / self.sample_rate)

    @property
    def frame_count(self) -> int:
        """Number of audio frames."""
        if self.sample_width <= 0 or self.channels <= 0:
            return 0
        return len(self.data) // (self.sample_width * self.channels)

    def save_to_file(self, path: Union[str, Path], format: str = "wav") -> None:
        """Save audio buffer to file.

        Args:
            path: Output file path
            format: Audio format (currently only "wav" supported)
        """
        path = Path(path)
        if format.lower() != "wav":
            raise ValueError(f"Unsupported format: {format}")

        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(self.channels)
            wav.setsampwidth(self.sample_width)
            wav.setframerate(self.sample_rate)
            wav.writeframes(self.data)

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "AudioBuffer":
        """Load audio buffer from WAV file."""
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            data = wav.readframes(wav.getnframes())
        return cls(data, sample_rate, channels, sample_width)

    @classmethod
    def from_bytes(
        cls, data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2
    ) -> "AudioBuffer":
        """Create buffer from raw bytes."""
        return cls(data, sample_rate, channels, sample_width)


@dataclass
class VoiceMetrics:
    """Metrics for a voice interaction."""

    record_duration_ms: int = 0
    transcription_time_ms: int = 0
    processing_time_ms: int = 0
    tts_time_ms: int = 0
    playback_time_ms: int = 0
    total_latency_ms: int = 0

    @property
    def pipeline_time_ms(self) -> int:
        """Time spent in pipeline stages (excluding playback)."""
        return (
            self.record_duration_ms
            + self.transcription_time_ms
            + self.processing_time_ms
            + self.tts_time_ms
        )


@dataclass
class VoiceResult:
    """Result of a complete voice interaction.

    Attributes:
        success: Whether the interaction succeeded
        status: Final status (completed, cancelled, no_transcript, error)
        transcript: Transcribed user speech
        response_text: Lucy's text response
        error_message: Error description if failed
        metrics: Timing metrics
        audio_duration_ms: Duration of recorded audio
        tts_duration_ms: Duration of synthesized speech
        tts_status: TTS execution status
        request_id: Unique request ID
    """

    success: bool = False
    status: str = ""
    transcript: str = ""
    response_text: str = ""
    error_message: str = ""
    metrics: VoiceMetrics = field(default_factory=VoiceMetrics)
    audio_duration_ms: int = 0
    tts_duration_ms: int = 0
    tts_status: str = "none"
    request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        from dataclasses import asdict

        return asdict(self)


@dataclass
class VADConfig:
    """Voice Activity Detection configuration.

    Attributes:
        enabled: Whether VAD is enabled
        energy_threshold: Energy threshold for speech detection (0-32767)
        silence_timeout_ms: Stop recording after this much silence
        min_speech_ms: Minimum speech duration to consider valid
        max_silence_ms: Maximum silence duration before stopping
    """

    enabled: bool = True
    energy_threshold: int = 500
    silence_timeout_ms: int = 1500
    min_speech_ms: int = 200
    max_silence_ms: int = 3000


