"""CLI entry point for the streaming voice pipeline."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .pipeline import StreamingVoicePipeline


async def main():
    if len(sys.argv) < 2:
        print("Usage: python3 -m streaming_voice <audio.wav>")
        return

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"Audio file not found: {audio_path}")
        return

    pipeline = StreamingVoicePipeline()

    def on_transcript(text):
        print(f"Transcript: {text}")

    def on_chunk(chunk):
        print(chunk, end="", flush=True)

    result = await pipeline.stream_voice_interaction(
        audio_path, on_transcription=on_transcript, on_response_chunk=on_chunk
    )

    print(f"\n\nSuccess: {result['success']}")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
