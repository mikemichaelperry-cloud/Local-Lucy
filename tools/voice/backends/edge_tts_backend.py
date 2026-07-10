#!/usr/bin/env python3
"""Microsoft Edge-TTS backend for Local Lucy.

Provides cloud TTS fallback for English text. Requires internet connectivity.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Mapping

DEFAULT_VOICE = "en-US-AriaNeural"
SAMPLE_RATE = 16000


class EdgeTtsBackendError(RuntimeError):
    pass


def detect_binary(root: Path, env: Mapping[str, str] | None = None) -> Path | None:
    """Return the Python executable path if edge-tts is importable."""
    del root  # unused
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return None
    return Path(__import__("sys").executable)


def resolve_voice_name(
    env: Mapping[str, str] | None = None, explicit_voice: str | None = None
) -> str:
    if explicit_voice and explicit_voice.strip():
        return explicit_voice.strip()
    values = env or os.environ
    return str(values.get("LUCY_VOICE_EDGE_TTS_VOICE", "")).strip() or DEFAULT_VOICE


def _has_internet(env: Mapping[str, str] | None = None) -> bool:
    """Best-effort connectivity check; failures are treated as 'no internet'."""
    del env  # reserved for future proxy-aware checks
    try:
        import socket

        # A TCP connect to the Edge-TTS endpoint is enough; we do not need a
        # successful HTTP response (Bing may return 400 on a bare GET).
        with socket.create_connection(("speech.platform.bing.com", 443), timeout=3.0):
            return True
    except Exception:
        return False


def synthesize(
    *,
    root: Path,
    text: str,
    output_path: Path,
    voice: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: int = 30,
) -> str:
    """Synthesize text with Microsoft Edge TTS and write a 16-bit PCM WAV file."""
    del root  # unused
    values = env or os.environ
    resolved_voice = resolve_voice_name(values, voice)

    if not shutil.which("ffmpeg"):
        raise EdgeTtsBackendError("ffmpeg is required to convert Edge-TTS MP3 output to WAV")

    if not _has_internet(values):
        raise EdgeTtsBackendError("no internet connectivity for Edge-TTS")

    try:
        import edge_tts

        mp3_path = Path(tempfile.gettempdir()) / f"lucy_edge_tts_{os.getpid()}.mp3"

        async def _run() -> None:
            communicate = edge_tts.Communicate(text.strip(), voice=resolved_voice)
            await communicate.save(str(mp3_path))

        import asyncio

        asyncio.run(_run())

        if not mp3_path.exists() or mp3_path.stat().st_size == 0:
            raise EdgeTtsBackendError("edge-tts produced no audio output")

        # Convert MP3 -> 16 kHz mono PCM WAV.
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(mp3_path),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_seconds,
        )
    except subprocess.CalledProcessError as exc:
        raise EdgeTtsBackendError(
            f"ffmpeg conversion failed: {exc.stderr.decode('utf-8', errors='ignore')[:200]}"
        ) from exc
    except Exception as exc:
        raise EdgeTtsBackendError(f"edge-tts synthesis failed: {exc}") from exc
    finally:
        try:
            mp3_path.unlink()
        except Exception:
            pass

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise EdgeTtsBackendError("edge-tts produced no wav output")
    return resolved_voice
