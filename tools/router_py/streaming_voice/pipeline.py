"""Streaming voice pipeline for Local Lucy."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from .levels import _analyze_pcm_levels, _get_audio_levels_file, _write_output_level
from .text import _clean_for_tts, _strip_html_for_tts
from .worker import KokoroWorkerManager, _detect_kokoro_availability


class StreamingVoicePipeline:
    """Voice pipeline that streams TTS as text arrives."""

    def __init__(self, voice: str = None):
        self.sample_rate = 22050  # Match Piper's sample rate
        self.channels = 1
        self.sample_width = 2
        self._cancelled = False
        self._kokoro_available = _detect_kokoro_availability()
        # Use consistent voice - default to af_bella (mature female)
        self.voice = voice or os.environ.get("LUCY_VOICE_KOKORO_VOICE", "af_bella")

        # Initialize worker manager
        socket_path = (
            Path(__file__).resolve().parent.parent.parent.parent / "tmp" / "run" / "kokoro_tts_worker.sock"
        )
        self._worker = KokoroWorkerManager(socket_path)

    async def start(self) -> bool:
        """Initialize pipeline - start Kokoro worker."""
        return await self._worker.ensure_running()

    def stop(self):
        """Clean up - stop worker."""
        self._worker.stop()

    def cancel(self):
        self._cancelled = True

    async def stream_voice_interaction(
        self,
        audio_path: Path,
        on_transcription: Optional[callable] = None,
        on_response_chunk: Optional[callable] = None,
        on_response_ready: Optional[callable] = None,
    ) -> dict:
        from router_py.voice import AudioBuffer

        result = {
            "success": False,
            "transcript": "",
            "response_text": "",
            "response_data": None,
            "error": "",
        }

        try:
            # Ensure worker is running
            if not await self._worker.ensure_running():
                print("Warning: Could not start Kokoro worker, using subprocess fallback")

            # Step 1: Transcribe
            print("Transcribing...")
            audio = AudioBuffer.from_file(audio_path)
            transcript = await self._transcribe_async(audio)
            result["transcript"] = transcript

            if on_transcription:
                on_transcription(transcript)

            if not transcript:
                result["error"] = "No speech detected"
                return result

            # --- Feedback detection: check if user is correcting a prior response ---
            try:
                from router_py.feedback_parser import (
                    parse_feedback,
                    log_user_feedback,
                    trigger_background_learning,
                )

                fb = parse_feedback(transcript)
                if fb is not None:
                    print(f"[Feedback detected] {fb.feedback_type.name}: {transcript}")
                    logged = log_user_feedback(fb)
                    if logged:
                        trigger_background_learning()

                    # Build confirmation message
                    if fb.feedback_type.name == "ROUTE_CORRECTION":
                        msg = f"Got it. I'll remember that should route to {fb.corrected_route}."
                    elif fb.feedback_type.name == "ANSWER_NEGATIVE":
                        msg = "Noted. I'll work on improving that answer."
                    elif fb.feedback_type.name == "ANSWER_POSITIVE":
                        msg = "Thanks for the feedback!"
                    elif fb.feedback_type.name == "RETRACTION":
                        msg = "Okay, I've forgotten that."
                    else:
                        msg = "Noted."

                    # Stream confirmation via TTS
                    if msg:
                        clean_msg = self._clean_for_tts(msg)
                        await self._stream_tts_continuous(clean_msg, on_response_chunk)

                    result["success"] = True
                    result["response_text"] = msg
                    return result
            except Exception as e:
                print(f"[Feedback check warning] {e}")

            # Step 2: Get response from Lucy
            print(f"Query: {transcript}")
            print("Processing and streaming response...")

            response_data = await self._get_full_response(transcript)
            result["response_data"] = response_data

            if isinstance(response_data, dict):
                response_text = response_data.get("response_text", "")
                result["response_text"] = response_text
            else:
                response_text = str(response_data)
                result["response_text"] = response_text

            # Notify that full response is ready (before TTS starts)
            if on_response_ready:
                on_response_ready(response_text, response_data)

            # Step 3: Stream TTS
            if response_text:
                clean_text = self._clean_for_tts(response_text)
                await self._stream_tts_continuous(clean_text, on_response_chunk)

            result["success"] = True

        except Exception as e:
            result["error"] = str(e)
            print(f"Error: {e}")

        return result

    def _strip_html_for_tts(self, text: str) -> str:
        """Strip HTML tags from text for TTS synthesis."""
        return _strip_html_for_tts(text)

    def _clean_for_tts(self, text: str) -> str:
        """Clean text for TTS - strip HTML, news first, sources at the end."""
        return _clean_for_tts(text)

    async def _transcribe_async(self, audio) -> str:
        from router_py.voice import VoicePipeline

        pipeline = VoicePipeline()
        result = await pipeline.transcribe(audio)
        return result.text

    async def _get_full_response(self, query: str) -> dict:
        """Get response from Lucy using unified pipeline entry point."""
        import concurrent.futures
        from router_py.main import run

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                run,
                query,
                surface="voice",
                timeout=300,
                model="local-lucy-llama31",  # Voice: default model (low VRAM)
            )
            outcome = await asyncio.wrap_future(future)

        return {
            "status": "completed" if outcome.status == "completed" else outcome.status,
            "response_text": outcome.response_text or "",
            "route": outcome.route,
            "provider": outcome.provider,
            "outcome_code": outcome.outcome_code,
            "execution_time_ms": outcome.execution_time_ms,
        }

    async def _stream_tts_continuous(
        self,
        response_text: str,
        on_response_chunk: Optional[callable] = None,
    ):
        """Stream TTS - simple phrase-by-phrase approach."""
        import struct
        import logging

        logger = logging.getLogger("streaming_voice")
        logger.info(f"[_stream_tts_continuous] Starting TTS for {len(response_text)} chars")
        print(
            f"[TTS Debug] Input text length: {len(response_text)} chars, {response_text.count('.')} sentences"
        )

        # Split into phrases
        phrases = re.split(r"(?<=[.!?])\s+|(?<=,)\s+", response_text)
        phrases = [p for p in phrases if p.strip()]

        # Further split very long phrases (>400 chars) to avoid timeout/failure
        MAX_PHRASE_LEN = 400
        final_phrases = []
        for phrase in phrases:
            if len(phrase) <= MAX_PHRASE_LEN:
                final_phrases.append(phrase)
            else:
                # Split long phrase by sentence boundaries
                sentences = re.split(r"(?<=[.!?])\s+", phrase)
                current_chunk = ""
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) <= MAX_PHRASE_LEN:
                        current_chunk += sentence + " "
                    else:
                        if current_chunk.strip():
                            final_phrases.append(current_chunk.strip())
                        current_chunk = sentence + " "
                if current_chunk.strip():
                    final_phrases.append(current_chunk.strip())

        phrases = final_phrases
        print(f"[TTS Debug] Split into {len(phrases)} phrases (max {MAX_PHRASE_LEN} chars each)")

        if not phrases:
            if on_response_chunk:
                on_response_chunk(response_text)
            return

        # Synthesize FIRST chunk before starting playback
        first_chunk_pcm = await self._synthesize_to_pcm(phrases[0])
        if not first_chunk_pcm:
            phrases = phrases[1:]
            if phrases:
                first_chunk_pcm = await self._synthesize_to_pcm(phrases[0])

        if not first_chunk_pcm and not phrases:
            if on_response_chunk:
                on_response_chunk(response_text)
            return

        # Add prepad silence (120ms)
        PREPAD_MS = 120
        silence_samples = int(self.sample_rate * (PREPAD_MS / 1000.0))
        prepad_silence = struct.pack(f"<{silence_samples}h", *([0] * silence_samples))

        # Start aplay with larger buffer for smoother playback
        aplay_proc = await asyncio.create_subprocess_exec(
            "aplay",
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(self.sample_rate),
            "-c",
            str(self.channels),
            "-q",
            "-",
            "--buffer-size=65536",  # Larger buffer to prevent underrun
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Setup VU meter level tracking with time-based level map
        # Pre-calculate all audio levels and their timestamps for accurate VU meter
        levels_file = _get_audio_levels_file()
        level_running = [True]
        playback_start_time = [0.0]  # Will be set when first audio is written
        level_map = []  # List of (timestamp_ms, level) tuples

        def level_writer():
            """Background thread: write current level based on playback time."""
            write_count = 0

            # Wait for playback to start
            while level_running[0] and playback_start_time[0] == 0.0:
                time.sleep(0.01)

            if not level_running[0]:
                return

            last_level = 0
            while level_running[0]:
                try:
                    # Calculate current playback position
                    elapsed_ms = (time.time() - playback_start_time[0]) * 1000

                    # Find the level for current playback position
                    # Use the last level where timestamp_ms <= elapsed_ms
                    current_level = last_level
                    for timestamp_ms, level in level_map:
                        if elapsed_ms >= timestamp_ms:
                            current_level = level
                        else:
                            break
                    last_level = current_level

                    _write_output_level(current_level, levels_file)
                    write_count += 1
                except Exception:
                    pass
                time.sleep(0.03)  # 30ms = ~33fps

            # Final write with zero level
            try:
                _write_output_level(0, levels_file)
            except Exception:
                pass

        # Start level writer thread
        level_thread = threading.Thread(target=level_writer, daemon=True)
        level_thread.start()

        try:
            # Build detailed level map with 30ms chunks for accurate VU meter
            # Each entry: (timestamp_ms, level)
            current_time_ms = 0

            # Prepad silence: 120ms at level 0
            level_map.append((current_time_ms, 0))
            current_time_ms += PREPAD_MS

            # Send prepad silence first
            aplay_proc.stdin.write(prepad_silence)
            await aplay_proc.stdin.drain()

            def add_pcm_to_level_map(pcm_data: bytes, base_time_ms: float) -> float:
                """Analyze PCM into 30ms chunks and add to level map. Returns new time."""
                time_ms = base_time_ms
                levels = _analyze_pcm_levels(pcm_data, self.sample_rate, chunk_duration_ms=30.0)
                for level in levels:
                    level_map.append((time_ms, level))
                    time_ms += 30.0  # 30ms per chunk
                return time_ms

            # Now send the first chunk
            if first_chunk_pcm:
                # Analyze into detailed chunks
                current_time_ms = add_pcm_to_level_map(first_chunk_pcm, current_time_ms)

                # Mark playback start time when first real audio is sent
                if playback_start_time[0] == 0.0:
                    playback_start_time[0] = time.time()

                aplay_proc.stdin.write(first_chunk_pcm)
                await aplay_proc.stdin.drain()

                if on_response_chunk:
                    on_response_chunk(phrases[0] + " ")

            # Process remaining phrases
            revealed = phrases[0] + " " if first_chunk_pcm else ""
            phrases_processed = 1 if first_chunk_pcm else 0
            phrases_failed = 0

            for i, phrase in enumerate(phrases[1:], 1):
                if self._cancelled:
                    print(f"[TTS Debug] Cancelled after {phrases_processed} phrases")
                    break

                audio_data = await self._synthesize_to_pcm(phrase)

                if audio_data:
                    # Analyze into detailed chunks
                    current_time_ms = add_pcm_to_level_map(audio_data, current_time_ms)

                    aplay_proc.stdin.write(audio_data)
                    await aplay_proc.stdin.drain()
                    phrases_processed += 1
                else:
                    phrases_failed += 1
                    print(
                        f"[TTS Debug] Phrase {i + 1} failed ({len(phrase)} chars): {phrase[:80]}..."
                    )

                if on_response_chunk:
                    revealed += phrase + " "
                    on_response_chunk(revealed)

            print(
                f"[TTS Debug] Processed {phrases_processed}/{len(phrases)} phrases, {phrases_failed} failed"
            )

            # Add trailing silence to ensure last audio plays (2000ms = 2 seconds)
            # This is critical - aplay needs enough silence to flush its buffer
            TRAILING_MS = 2000
            trailing_samples = int(self.sample_rate * (TRAILING_MS / 1000.0))
            trailing_silence = struct.pack(f"<{trailing_samples}h", *([0] * trailing_silence))
            # Mark level 0 for trailing silence period
            level_map.append((current_time_ms, 0))
            aplay_proc.stdin.write(trailing_silence)
            await aplay_proc.stdin.drain()

            # Close stdin to signal EOF - aplay will finish when buffer is empty
            await aplay_proc.stdin.drain()
            aplay_proc.stdin.close()

            # Wait for aplay to actually finish playing all audio
            # This is more reliable than fixed sleep - aplay exits only after playback
            print("[TTS Debug] Waiting for playback to complete...")
            try:
                # Longer timeout for long content (30s instead of 10s)
                await asyncio.wait_for(aplay_proc.wait(), timeout=30.0)
                print("[TTS Debug] Playback complete")
            except asyncio.TimeoutError:
                print("[TTS Debug] aplay wait timeout, killing process")
                aplay_proc.kill()
                await aplay_proc.wait()
        finally:
            # Stop level writer
            level_running[0] = False
            level_thread.join(timeout=0.5)

    async def _synthesize_to_pcm(self, text: str) -> bytes:
        """Synthesize using Kokoro worker socket or subprocess fallback."""
        if not text.strip():
            return b""

        # Try Kokoro worker first (managed by this pipeline) - fast path
        pcm_data = await self._synthesize_via_worker(text)
        if pcm_data:
            return pcm_data

        # Fallback to subprocess
        return await self._synthesize_subprocess_to_pcm(text)

    async def _synthesize_via_worker(self, text: str) -> bytes:
        """Use Kokoro worker socket for fast synthesis."""
        import socket
        import json
        import tempfile
        import wave
        import numpy as np

        # Check phrase length - if too long, may cause issues
        if len(text) > 500:
            print(f"[TTS Debug] Warning: Long phrase ({len(text)} chars), may timeout")

        if not self._worker.socket_path.exists():
            print("[TTS Debug] Worker socket not found, skipping synthesis")
            return b""

        tmp_path: str | None = None
        wav_path: str | None = None
        sock: socket.socket | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            # Increase timeout for long phrases
            timeout = 30.0 if len(text) > 300 else 10.0
            sock.settimeout(timeout)
            sock.connect(str(self._worker.socket_path))

            request = {
                "cmd": "synthesize",
                "engine": "kokoro",
                "text": text,
                "voice": self.voice,
                "output_dir": str(Path(tmp_path).parent),
            }

            sock.send(json.dumps(request).encode() + b"\n")
            response_data = sock.recv(4096).decode()

            response = json.loads(response_data)

            if not response.get("ok"):
                error_msg = response.get("error", "unknown error")
                print(f"[TTS Debug] Worker error: {error_msg}")
                return b""

            wav_path = response.get("wav_path")
            if not wav_path or not Path(wav_path).exists():
                print("[TTS Debug] No WAV file produced")
                return b""

            with wave.open(wav_path, "rb") as wav:
                source_rate = wav.getframerate()
                pcm_data = wav.readframes(wav.getnframes())

            # Resample if needed (Kokoro outputs 24kHz, aplay expects 22050 Hz)
            if source_rate != self.sample_rate:
                try:
                    # Convert bytes to numpy array
                    audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32767.0

                    # Simple linear interpolation resampling
                    ratio = self.sample_rate / source_rate
                    new_length = int(len(audio) * ratio)
                    old_indices = np.arange(len(audio))
                    new_indices = np.linspace(0, len(audio) - 1, new_length)
                    audio_resampled = np.interp(new_indices, old_indices, audio)

                    # Convert back to int16 bytes
                    pcm_data = (audio_resampled * 32767).astype(np.int16).tobytes()
                except Exception as e:
                    print(f"[TTS Debug] Resampling error: {e}")
                    # Return original data if resampling fails

            return pcm_data

        except socket.timeout:
            print(f"[TTS Debug] Timeout synthesizing phrase ({len(text)} chars)")
            return b""
        except Exception as e:
            print(f"[TTS Debug] Worker error: {e}")
            return b""
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass
            if wav_path is not None:
                try:
                    Path(wav_path).unlink()
                except Exception:
                    pass
            if tmp_path is not None:
                try:
                    Path(tmp_path).unlink()
                except Exception:
                    pass

    async def _synthesize_subprocess_to_pcm(self, text: str) -> bytes:
        """Fallback subprocess synthesis."""
        helper_path = Path(__file__).resolve().parent.parent / "streaming_tts_helper.py"
        voice_python = _get_ui_v10_python()

        pcm_data = b""

        try:
            proc = await asyncio.create_subprocess_exec(
                voice_python,
                str(helper_path),
                text,
                "--voice",
                self.voice,
                "--speed",
                "1.0",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                pcm_data += chunk

                if self._cancelled:
                    proc.kill()
                    break

            await proc.wait()
        except Exception as e:
            print(f"TTS subprocess error: {e}")

        return pcm_data
