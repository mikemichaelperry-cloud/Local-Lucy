#!/usr/bin/env python3
"""Voice pipeline exceptions."""


class VoicePipelineError(RuntimeError):
    """Base exception for voice pipeline errors."""

    pass


class RecordingError(VoicePipelineError):
    """Error during audio recording."""

    pass


class TranscriptionError(VoicePipelineError):
    """Error during transcription."""

    pass


class SynthesisError(VoicePipelineError):
    """Error during TTS synthesis."""

    pass


class PlaybackError(VoicePipelineError):
    """Error during audio playback."""

    pass
