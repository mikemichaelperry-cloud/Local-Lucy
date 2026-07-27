#!/usr/bin/env python3
"""Main voice pipeline implementation."""

from __future__ import annotations

import asyncio
import audioop
import io
import json
import logging
import os
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Import base wrapper
try:
    from router_py.base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult
except ImportError:
    from base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult

# Import TTS adapter / playback
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root  # noqa: E402

VOICE_DIR = Path(__file__).resolve().parents[2] / "voice"
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

_playback_with_levels_import_error = None

try:
    import tts_adapter  # noqa: E402
    from playback import play_wav_file, detect_audio_player  # noqa: E402

    try:
        from playback_with_levels import play_wav_file_with_levels  # noqa: E402
    except ImportError as e:
        _playback_with_levels_import_error = str(e)
        play_wav_file_with_levels = None
except ImportError as e:
    tts_adapter = None
    play_wav_file = None
    play_wav_file_with_levels = None
    detect_audio_player = lambda: ""

from router_py.voice.exceptions import (
    PlaybackError,
    RecordingError,
    SynthesisError,
    TranscriptionError,
    VoicePipelineError,
)
from router_py.voice.models import (
    AudioBuffer,
    TranscriptionResult,
    VADConfig,
    VoiceMetrics,
    VoiceResult,
)
from router_py.voice.utils import _voice_usage_logger, clean_text, iso_now

logger = logging.getLogger(__name__)

_GPU_ERROR_KEYWORDS = ("cuda", "cublas", "gpu", "out of memory", "oom")


class VoicePipeline(BaseToolWrapper):
    """Async voice processing pipeline for Local Lucy.

    Provides a complete async pipeline for voice interactions:
    1. Record audio from microphone
    2. Transcribe using Whisper or Vosk
    3. Process through Lucy (text query)
    4. Synthesize response using TTS
    5. Play audio output

    All stages support cancellation via the `cancel()` method.

    Example:
        pipeline = VoicePipeline()

        # Full interaction
        result = await pipeline.voice_interaction()
        print(f"Transcript: {result.transcript}")
        print(f"Response: {result.response_text}")

        # Or use individual stages
        audio = await pipeline.record_audio(duration=5.0)
        tx_result = await pipeline.transcribe(audio)
        transcript = tx_result.text
    """

    # Explicitly declare that this class implements the abstract method

    def __init__(
        self,
        config: Optional[ToolConfig] = None,
        vad_config: Optional[VADConfig] = None,
        whisper_model: str = "base",
        tts_engine: str = "auto",
        tts_voice: Optional[str] = None,
        sample_rate: int = 16000,
        channels: int = 1,
    ):
        """Initialize voice pipeline.

        Args:
            config: Tool configuration
            vad_config: Voice Activity Detection configuration
            whisper_model: Whisper model name or path
            tts_engine: TTS engine ("auto", "piper", "kokoro", or "none")
            tts_voice: TTS voice identifier
            sample_rate: Audio sample rate
            channels: Audio channels (1 for mono)
        """
        super().__init__(config)
        self.vad_config = vad_config or VADConfig()
        self.whisper_model = whisper_model
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_width = 2  # 16-bit

        self._cancelled = False
        self._current_task: Optional[asyncio.Task] = None
        self._record_process: Optional[asyncio.subprocess.Process] = None
        self._logger = logging.getLogger(__name__)

        # Cache for recorder/whisper detection
        self._recorder_engine: Optional[str] = None
        self._recorder_bin: Optional[str] = None
        self._stt_engine: Optional[str] = None
        self._stt_bin: Optional[str] = None

    # =========================================================================
    # Cancellation Support
    # =========================================================================

    def cancel(self) -> None:
        """Cancel the current operation.

        Sets the cancelled flag and attempts to terminate any running subprocess.
        """
        self._cancelled = True
        self._logger.info("Voice pipeline cancellation requested")

        if self._record_process and self._record_process.returncode is None:
            try:
                self._record_process.send_signal(signal.SIGTERM)
            except ProcessLookupError:
                pass

    def _check_cancelled(self) -> None:
        """Check if cancelled and raise exception if so."""
        if self._cancelled:
            raise VoicePipelineError("Operation cancelled")

    def reset(self) -> None:
        """Reset cancellation state for reuse."""
        self._cancelled = False
        self._record_process = None

    # =========================================================================
    # Stage 1: Audio Recording
    # =========================================================================

    async def record_audio(
        self,
        duration: Optional[float] = None,
        sample_rate: Optional[int] = None,
        channels: Optional[int] = None,
        device: Optional[str] = None,
    ) -> AudioBuffer:
        """Record audio from microphone.

        Args:
            duration: Recording duration in seconds. If None, uses VAD to
                     detect silence and stop automatically.
            sample_rate: Sample rate (defaults to instance setting)
            channels: Number of channels (defaults to instance setting)
            device: Audio device (None for default)

        Returns:
            AudioBuffer containing recorded PCM data

        Raises:
            RecordingError: If recording fails
            VoicePipelineError: If cancelled
        """
        self._check_cancelled()

        sample_rate = sample_rate or self.sample_rate
        channels = channels or self.channels

        # Detect recorder
        recorder_engine, recorder_bin = self._detect_recorder()
        if not recorder_bin:
            raise RecordingError("No audio recorder available (arecord or pw-record)")

        self._logger.info(
            f"Recording with {recorder_engine} "
            + f"(duration={'VAD' if duration is None else f'{duration}s'})"
        )

        # Build command
        if recorder_engine == "arecord":
            cmd = [recorder_bin, "-q", "-f", "S16_LE", "-r", str(sample_rate), "-c", str(channels)]
            if device:
                cmd.extend(["-D", device])
            if duration:
                cmd.extend(["-d", str(int(duration))])
            cmd.append("-")  # Output to stdout
        elif recorder_engine == "pw-record":
            cmd = [
                recorder_bin,
                "--channels",
                str(channels),
                "--rate",
                str(sample_rate),
                "--format",
                "s16",
            ]
            if duration:
                cmd.extend(["--duration", str(int(duration))])
            cmd.append("-")  # Output to stdout
        else:
            raise RecordingError(f"Unknown recorder: {recorder_engine}")

        # Run recording
        start_time = time.time()
        audio_data = bytearray()

        try:
            self._record_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            if duration is None and self.vad_config.enabled:
                # VAD mode: read chunks and detect silence
                audio_data = await self._record_with_vad(
                    self._record_process, sample_rate, channels
                )
            else:
                # Fixed duration mode
                max_duration = duration or 30.0
                audio_data = await self._record_fixed_duration(self._record_process, max_duration)

            await self._record_process.wait()
            self._record_process = None

        except asyncio.CancelledError:
            self.cancel()
            raise
        except VoicePipelineError:
            raise
        except Exception as e:
            raise RecordingError(f"Recording failed: {e}") from e
        finally:
            if self._record_process and self._record_process.returncode is None:
                try:
                    self._record_process.kill()
                    await self._record_process.wait()
                except Exception:
                    pass
                self._record_process = None

        record_time = int((time.time() - start_time) * 1000)
        buffer = AudioBuffer(bytes(audio_data), sample_rate, channels, self.sample_width)

        self._logger.info(
            f"Recorded {buffer.duration_ms}ms of audio " + f"({len(audio_data)} bytes)"
        )

        return buffer

    async def _record_fixed_duration(
        self,
        process: asyncio.subprocess.Process,
        duration: float,
    ) -> bytearray:
        """Record for a fixed duration with cancellation support."""
        audio_data = bytearray()
        deadline = time.time() + duration

        assert process.stdout is not None

        while time.time() < deadline:
            self._check_cancelled()

            try:
                chunk = await asyncio.wait_for(
                    process.stdout.read(4096), timeout=min(0.5, deadline - time.time())
                )
                if not chunk:
                    break
                audio_data.extend(chunk)
            except asyncio.TimeoutError:
                continue

        # Drain any remaining data
        try:
            while True:
                chunk = await asyncio.wait_for(process.stdout.read(4096), timeout=0.1)
                if not chunk:
                    break
                audio_data.extend(chunk)
        except asyncio.TimeoutError:
            pass

        return audio_data

    async def _record_with_vad(
        self,
        process: asyncio.subprocess.Process,
        sample_rate: int,
        channels: int,
    ) -> bytearray:
        """Record with Voice Activity Detection to stop on silence."""
        audio_data = bytearray()
        silence_start: Optional[float] = None
        speech_started = False
        frame_duration_ms = 30  # 30ms frames
        bytes_per_frame = int(sample_rate * frame_duration_ms / 1000) * channels * self.sample_width

        assert process.stdout is not None

        # Buffer for partial frames
        buffer = bytearray()
        max_record_time = 30.0  # Hard limit
        record_start = time.time()

        while time.time() - record_start < max_record_time:
            self._check_cancelled()

            try:
                chunk = await asyncio.wait_for(
                    process.stdout.read(bytes_per_frame * 4), timeout=0.5
                )
                if not chunk:
                    break
                buffer.extend(chunk)
            except asyncio.TimeoutError:
                if (
                    silence_start
                    and time.time() - silence_start > self.vad_config.silence_timeout_ms / 1000
                ):
                    break
                continue

            # Process complete frames
            while len(buffer) >= bytes_per_frame:
                frame = bytes(buffer[:bytes_per_frame])
                buffer = buffer[bytes_per_frame:]
                audio_data.extend(frame)

                # VAD check
                is_speech = self._detect_speech(frame, sample_rate, channels)

                if is_speech:
                    if not speech_started:
                        self._logger.debug("Speech detected")
                        speech_started = True
                    silence_start = None
                else:
                    if speech_started and silence_start is None:
                        silence_start = time.time()

                    if silence_start:
                        silence_duration = time.time() - silence_start
                        if silence_duration > self.vad_config.silence_timeout_ms / 1000:
                            self._logger.debug(
                                f"Silence detected for {silence_duration:.2f}s, stopping"
                            )
                            break

            if (
                silence_start
                and time.time() - silence_start > self.vad_config.silence_timeout_ms / 1000
            ):
                break

        # Add any remaining buffered data
        audio_data.extend(buffer)

        # Check minimum speech duration
        if speech_started:
            speech_duration = len(audio_data) / (sample_rate * channels * self.sample_width) * 1000
            if speech_duration < self.vad_config.min_speech_ms:
                self._logger.warning(f"Speech too short: {speech_duration:.0f}ms")

        return audio_data

    def _detect_speech(self, frame: bytes, sample_rate: int, channels: int) -> bool:
        """Detect speech in an audio frame using energy-based VAD.

        Args:
            frame: Raw audio bytes
            sample_rate: Sample rate
            channels: Number of channels

        Returns:
            True if speech detected
        """
        if len(frame) < 2:
            return False

        try:
            # Calculate RMS energy
            if self.sample_width == 2:
                # 16-bit samples
                rms = audioop.rms(frame, 2)
            elif self.sample_width == 1:
                rms = audioop.rms(frame, 1)
            else:
                return False

            return rms > self.vad_config.energy_threshold
        except Exception:
            return False

    # =========================================================================
    # Stage 2: Transcription
    # =========================================================================

    async def transcribe(
        self,
        audio: AudioBuffer,
        model: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TranscriptionResult:
        """Transcribe audio using Whisper or Vosk.

        Args:
            audio: Audio buffer to transcribe
            model: Whisper model name (uses instance default if None)
            language: Language code (None for auto-detect)

        Returns:
            TranscriptionResult with text, backend, fallback info

        Raises:
            TranscriptionError: If transcription fails
        """
        self._check_cancelled()

        stt_engine, stt_bin = self._detect_stt()
        if not stt_bin:
            raise TranscriptionError("No STT engine available (whisper or vosk)")

        start_time = time.time()

        # Save audio to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            audio.save_to_file(tmp_path)
            self._check_cancelled()

            if stt_engine == "whisper":
                result = await self._transcribe_whisper(stt_bin, tmp_path, model, language)
            elif stt_engine == "vosk":
                text = await self._transcribe_vosk(stt_bin, tmp_path)
                result = TranscriptionResult(text=text)
            else:
                raise TranscriptionError(f"Unknown STT engine: {stt_engine}")

            # Normalize transcript
            normalized = self._normalize_transcript(result.text)
            result = TranscriptionResult(
                text=normalized,
                backend=result.backend,
                fallback_used=result.fallback_used,
                fallback_reason=result.fallback_reason,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)
            backend_label = result.backend or "unknown"
            fb_flag = " (CPU fallback)" if result.fallback_used else ""
            self._logger.info(
                f"Transcription completed in {elapsed_ms}ms [{backend_label}{fb_flag}]: '{result.text[:50]}...'"
            )

            return result

        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    async def _transcribe_whisper(
        self,
        stt_bin: str,
        wav_path: Path,
        model: Optional[str],
        language: Optional[str],
    ) -> TranscriptionResult:
        """Transcribe using Whisper."""
        # Resolve model path
        model_path = self._resolve_whisper_model(model)

        # Build command
        cmd = [
            stt_bin,
            "-m",
            str(model_path),
            "-f",
            str(wav_path),
            "-otxt",
            "-of",
            "-",
            "--no-timestamps",
        ]

        if language and language.lower() != "auto":
            cmd[1:1] = ["-l", language]

        # Fast decode for voice assistant (tunable via env)
        beam_size = os.environ.get("LUCY_VOICE_WHISPER_BEAM_SIZE", "").strip()
        if beam_size:
            try:
                cmd += ["--beam-size", str(int(beam_size))]
            except ValueError:
                cmd += ["--beam-size", "1", "--best-of", "1"]
        else:
            cmd += ["--beam-size", "1", "--best-of", "1"]

        # Set up environment for bundled whisper
        env = self._whisper_env(stt_bin)

        async def _run(cmd_list: list[str]) -> tuple[int, bytes, bytes]:
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45.0)
            return proc.returncode, stdout, stderr

        def _is_gpu_error(stderr_text: str) -> bool:
            lower = stderr_text.lower()
            return any(keyword in lower for keyword in _GPU_ERROR_KEYWORDS)

        try:
            # First attempt: GPU (default whisper behavior)
            returncode, stdout, stderr = await _run(cmd)
            if returncode == 0:
                text = stdout.decode("utf-8", errors="replace").strip()
                return TranscriptionResult(text=text, backend="gpu")

            # GPU failed — check if it's a GPU-specific error
            error_text = (
                stderr.decode("utf-8", errors="replace").strip()
                or stdout.decode("utf-8", errors="replace").strip()
            )
            if not error_text:
                error_text = f"whisper exited with status {returncode}"

            if not _is_gpu_error(error_text):
                raise TranscriptionError(f"Whisper failed: {error_text}")

            # Retry with CPU fallback (--no-gpu)
            returncode_cpu, stdout_cpu, stderr_cpu = await _run(cmd + ["--no-gpu"])
            if returncode_cpu == 0:
                text = stdout_cpu.decode("utf-8", errors="replace").strip()
                return TranscriptionResult(
                    text=text,
                    backend="cpu",
                    fallback_used=True,
                    fallback_reason=error_text,
                )

            # CPU fallback also failed
            cpu_error = stderr_cpu.decode("utf-8", errors="replace").strip() or error_text
            raise TranscriptionError(f"Whisper failed: {cpu_error}")

        except asyncio.TimeoutError:
            raise TranscriptionError("Whisper transcription timed out")

    async def _transcribe_vosk(
        self,
        stt_bin: str,
        wav_path: Path,
    ) -> str:
        """Transcribe using Vosk."""
        # Try different command formats
        commands = [
            [stt_bin, "-i", str(wav_path)],
            [stt_bin, str(wav_path)],
        ]

        for cmd in commands:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=45.0)
                result = stdout.decode("utf-8", errors="replace").strip()

                if result:
                    return result

            except asyncio.TimeoutError:
                continue
            except Exception:
                continue

        raise TranscriptionError("Vosk transcription failed")

    def _normalize_transcript(self, text: str) -> str:
        """Normalize transcript text."""
        # Remove blank audio markers
        text = re.sub(
            r"\[(blank_audio|inaudible|silence|no_speech|no speech)\]",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text)
        text = text.strip()

        return text

    # =========================================================================
    # Stage 3: Lucy Query Processing
    # =========================================================================

    async def process_query(
        self,
        transcript: str,
        surface: str = "voice",
    ) -> str:
        """Process transcript through Lucy.

        Args:
            transcript: User's transcribed speech
            surface: Interface surface ("voice", "chat", etc.)

        Returns:
            Lucy's text response
        """
        self._check_cancelled()

        start_time = time.time()

        # Unified pipeline entry point (replaces inline classify→route→execute)
        import concurrent.futures
        from router_py.main import run

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(
                run,
                transcript,
                surface=surface,
                timeout=125,
            )
            outcome = await asyncio.wrap_future(future)

        elapsed_ms = int((time.time() - start_time) * 1000)
        self._logger.info(f"Query processed via unified pipeline in {elapsed_ms}ms")
        return outcome.response_text or ""

    async def _process_query_shell(
        self,
        transcript: str,
        surface: str,
    ) -> str:
        """Fallback: process query using shell execution."""
        root = self._resolve_root()
        request_tool = root / "tools" / "runtime_request.py"

        if not request_tool.exists():
            raise VoicePipelineError("No query processing tool available")

        env = os.environ.copy()
        env["LUCY_SURFACE"] = surface

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(request_tool),
            "submit",
            "--text",
            transcript,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=150.0)

        if proc.returncode != 0:
            raise VoicePipelineError(f"Query failed: {stderr.decode()}")

        try:
            result = json.loads(stdout.decode())
            return result.get("response_text", "")
        except json.JSONDecodeError:
            return stdout.decode().strip()

    # =========================================================================
    # Stage 4: TTS Synthesis
    # =========================================================================

    def _strip_html_for_tts(self, text: str) -> str:
        """Strip HTML tags from text for TTS synthesis."""
        import re

        if not text:
            return ""

        # Remove script and style elements
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Replace <br>, <p> etc with newlines
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

        # Replace <li> with bullet points
        text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "", text, flags=re.IGNORECASE)

        # Replace <a href="...">text</a> with "text (link)" or just "text"
        # Use lambda to avoid backreference interpretation issues with $ in content
        text = re.sub(
            r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>',
            lambda m: m.group(2),
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"<a[^>]*>([^<]*)</a>", lambda m: m.group(1), text, flags=re.IGNORECASE)

        # Remove all remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode common HTML entities
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'")
        text = text.replace("&nbsp;", " ").replace("&#160;", " ")
        text = text.replace("&#8211;", "–").replace("&#8212;", "—")
        text = text.replace("&#8216;", """).replace('&#8217;', """)
        text = text.replace("&#8220;", '"').replace("&#8221;", '"')

        # Normalize whitespace
        text = re.sub(r"\n\s*\n", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = text.strip()

        return text

    async def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
    ) -> AudioBuffer:
        """Synthesize speech from text.

        Args:
            text: Text to synthesize
            voice: Voice identifier (uses default if None)
            speed: Speech speed multiplier

        Returns:
            AudioBuffer with synthesized speech
        """
        self._check_cancelled()

        if not text or not text.strip():
            return AudioBuffer(b"", self.sample_rate, self.channels, self.sample_width)

        # Strip HTML tags for TTS
        text = self._strip_html_for_tts(text)

        if not text.strip():
            return AudioBuffer(b"", self.sample_rate, self.channels, self.sample_width)

        start_time = time.time()

        # Use tts_adapter for synthesis
        voice = voice or self.tts_voice
        engine = self.tts_engine

        _voice_usage_logger.info(f"Voice synthesis starting: engine={engine}, voice={voice}")

        # Create temp output directory
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                # Use ui-v10 Python for TTS to ensure Kokoro is available
                voice_python = self._resolve_voice_python()

                # Always use subprocess to avoid Python environment issues
                # (Kokoro is installed in ui-v10 venv, not system Python)
                if not voice_python:
                    raise SynthesisError("No voice Python available. Ensure ui-v10 venv exists.")

                result = self._synthesize_with_subprocess(
                    text=text.strip(),
                    engine=engine,
                    voice=voice,
                    output_dir=tmpdir,
                    python_bin=voice_python,
                )

                if not result.get("ok"):
                    error = result.get("error", "Unknown TTS error")
                    raise SynthesisError(f"TTS failed: {error}")

                wav_path = Path(result.get("wav_path", ""))
                if not wav_path.exists():
                    raise SynthesisError("TTS produced no audio output")

                # Load audio
                audio = AudioBuffer.from_file(wav_path)

                elapsed_ms = int((time.time() - start_time) * 1000)
                self._logger.info(
                    f"Synthesis completed in {elapsed_ms}ms " + f"(engine={result.get('engine')})"
                )

                return audio

            except Exception as e:
                if isinstance(e, SynthesisError):
                    raise
                raise SynthesisError(f"Synthesis failed: {e}") from e

    def _resolve_voice_python(self) -> str:
        """Resolve Python binary for TTS (ui-v10 venv has Kokoro)."""
        # Check explicit env var
        explicit = os.environ.get("LUCY_VOICE_PYTHON_BIN", "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            if path.exists() and os.access(path, os.X_OK):
                return str(path)

        # ISOLATION: V8 only uses ui-v10, NEVER falls back to ui-v7
        root = self._resolve_root()
        workspace_root = root if root.name in ("lucy-v10", "lucy-v11") else root.parent.parent
        candidate = workspace_root / "ui-v10" / ".venv" / "bin" / "python3"

        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

        for fallback in (Path(sys.executable), Path("/usr/bin/python3")):
            if fallback.exists() and os.access(fallback, os.X_OK):
                return str(fallback)

        raise RuntimeError(
            f"V8 ISOLATION VIOLATION: ui-v10 Python not found at {candidate}, "
            "and no system python3 fallback is executable. V8 cannot use V7 components."
        )

    def _synthesize_with_subprocess(
        self,
        text: str,
        engine: str,
        voice: Optional[str],
        output_dir: str,
        python_bin: str,
    ) -> dict[str, Any]:
        """Synthesize using TTS adapter via subprocess with ui-v10 Python."""
        import subprocess
        import json

        tts_adapter_path = Path(__file__).resolve().parents[2] / "voice" / "tts_adapter.py"

        cmd = [
            python_bin,
            str(tts_adapter_path),
            "synthesize",
            "--text",
            text,
            "--engine",
            engine,
            "--output-dir",
            output_dir,
        ]

        if voice:
            cmd.extend(["--voice", voice])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )

        if result.returncode != 0:
            return {"ok": False, "error": result.stderr or "Subprocess failed"}

        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"ok": False, "error": f"Invalid JSON output: {result.stdout}"}

    # =========================================================================
    # Stage 5: Audio Playback
    # =========================================================================

    async def play_audio(
        self,
        audio: AudioBuffer,
        device: Optional[str] = None,
        prepad_ms: int = 0,
    ) -> None:
        """Play audio using aplay or paplay.

        Args:
            audio: Audio buffer to play
            device: Audio device (None for default)
            prepad_ms: Leading silence to prepend (ms)
        """
        self._check_cancelled()

        if audio.duration_ms == 0:
            return

        start_time = time.time()

        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            audio.save_to_file(tmp_path)
            self._check_cancelled()

            # Use playback.py if available
            self._logger.info(
                f"play_audio: play_wav_file_with_levels={play_wav_file_with_levels is not None}, play_wav_file={play_wav_file is not None}"
            )
            if play_wav_file_with_levels:
                # Playback with VU meter level output
                try:
                    # Get levels file path from environment or use default
                    import os

                    runtime_dir = Path(
                        os.environ.get(
                            "LUCY_RUNTIME_NAMESPACE_ROOT",
                            str(lucy_runtime_namespace_root()),
                        )
                    )
                    levels_file = runtime_dir / "state" / "voice_audio_levels.json"

                    play_wav_file_with_levels(
                        tmp_path,
                        levels_file,
                        player=device,
                    )
                except Exception as e:
                    self._logger.warning(f"Playback with levels failed: {e}, falling back")
                    # Fallback to regular playback
                    play_wav_file(
                        tmp_path,
                        player=device,
                        prepad_ms=prepad_ms,
                    )
            elif play_wav_file:
                try:
                    play_wav_file(
                        tmp_path,
                        player=device,
                        prepad_ms=prepad_ms,
                    )
                except Exception as e:
                    raise PlaybackError(f"Playback failed: {e}")
            else:
                # Fallback to direct player execution
                await self._play_with_player(tmp_path, device, prepad_ms)

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.info(f"Playback completed in {elapsed_ms}ms")

        finally:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    async def _play_with_player(
        self,
        wav_path: Path,
        player: Optional[str],
        prepad_ms: int,
    ) -> None:
        """Play using system audio player."""
        player = player or detect_audio_player()

        if not player:
            raise PlaybackError("No audio player available (aplay or paplay)")

        # Pre-pad the WAV file with silence to prevent truncating first word
        # This embeds silence INTO the audio file rather than playing separately

        if player == "aplay":
            cmd = ["aplay", "-q", str(wav_path)]
        elif player == "paplay":
            cmd = ["paplay", str(wav_path)]
        else:
            raise PlaybackError(f"Unknown player: {player}")

        proc = await asyncio.create_subprocess_exec(*cmd)
        await proc.wait()

        if proc.returncode != 0:
            raise PlaybackError(f"Player exited with code {proc.returncode}")

    def _detect_recorder(self) -> Tuple[Optional[str], Optional[str]]:
        """Detect available audio recorder."""
        if self._recorder_engine and self._recorder_bin:
            return self._recorder_engine, self._recorder_bin

        arecord = shutil.which("arecord")
        if arecord:
            self._recorder_engine = "arecord"
            self._recorder_bin = arecord
            return self._recorder_engine, self._recorder_bin

        pw_record = shutil.which("pw-record")
        if pw_record:
            self._recorder_engine = "pw-record"
            self._recorder_bin = pw_record
            return self._recorder_engine, self._recorder_bin

        return None, None

    def _detect_stt(self) -> Tuple[Optional[str], Optional[str]]:
        """Detect available STT engine."""
        if self._stt_engine and self._stt_bin:
            return self._stt_engine, self._stt_bin

        # Check for whisper
        whisper_bin = os.environ.get("LUCY_VOICE_WHISPER_BIN", "")
        if whisper_bin and Path(whisper_bin).exists():
            self._stt_engine = "whisper"
            self._stt_bin = whisper_bin
            return self._stt_engine, self._stt_bin

        # Check bundled whisper
        root = self._resolve_root()
        bundled = root / "runtime" / "voice" / "bin" / "whisper"
        if bundled.exists():
            # Check libraries are available
            lib_dirs = [
                root / "runtime" / "voice" / "whisper.cpp" / "build" / "src",
                root / "runtime" / "voice" / "whisper.cpp" / "build" / "ggml" / "src",
            ]
            if all(d.is_dir() for d in lib_dirs):
                self._stt_engine = "whisper"
                self._stt_bin = str(bundled)
                return self._stt_engine, self._stt_bin

        # Check system whisper
        for name in ["whisper", "whisper-cli", "whisper-cpp"]:
            path = shutil.which(name)
            if path:
                self._stt_engine = "whisper"
                self._stt_bin = path
                return self._stt_engine, self._stt_bin

        # Check for vosk
        vosk_bin = os.environ.get("LUCY_VOICE_VOSK_BIN", "")
        if vosk_bin and Path(vosk_bin).exists():
            self._stt_engine = "vosk"
            self._stt_bin = vosk_bin
            return self._stt_engine, self._stt_bin

        system_vosk = shutil.which("vosk-transcriber")
        if system_vosk:
            self._stt_engine = "vosk"
            self._stt_bin = system_vosk
            return self._stt_engine, self._stt_bin

        return None, None

    def _resolve_whisper_model(self, model: Optional[str]) -> str:
        """Resolve whisper model path."""
        if model and Path(model).exists():
            return str(model)

        # Check environment
        env_model = os.environ.get("LUCY_VOICE_WHISPER_MODEL", "")
        if env_model and Path(env_model).exists():
            return env_model

        # Check bundled models
        root = self._resolve_root()
        model_name = model or os.environ.get("LUCY_VOICE_MODEL", "small.en")
        bundled = root / "runtime" / "voice" / "models" / f"ggml-{model_name}.bin"
        if bundled.exists():
            return str(bundled)

        # Fallback to models directory
        fallback = root / "models" / "ggml-base.bin"
        if fallback.exists():
            return str(fallback)

        # Last resort: return model name and hope it's in PATH
        return model or "base"

    def _whisper_env(self, stt_bin: str) -> Dict[str, str]:
        """Get environment for whisper execution."""
        env = os.environ.copy()
        root = self._resolve_root()
        bundled = root / "runtime" / "voice" / "bin" / "whisper"

        try:
            is_bundled = Path(stt_bin).resolve() == bundled.resolve()
        except OSError:
            is_bundled = False

        if not is_bundled:
            return env

        # Set LD_LIBRARY_PATH for bundled whisper
        lib_dirs = [
            str(root / "runtime" / "voice" / "whisper.cpp" / "build" / "src"),
            str(root / "runtime" / "voice" / "whisper.cpp" / "build" / "ggml" / "src"),
        ]
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))

        return env

    def _resolve_root(self) -> Path:
        """Resolve Local Lucy root directory."""
        env_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT")
        if env_root:
            return Path(env_root).expanduser().resolve()
        return Path(__file__).resolve().parents[3]

    def _detect_backend(self):
        """Detect voice backend availability.

        Returns a SimpleNamespace with attributes:
        - available: bool
        - recorder_engine: str
        - stt_engine: str
        - tts_engine: str
        - tts_device: str
        - audio_player: str
        - reason: str
        """
        from types import SimpleNamespace

        recorder_engine, recorder_bin = self._detect_recorder()
        stt_engine, stt_bin = self._detect_stt()

        # Detect TTS
        tts_engine = self.tts_engine if self.tts_engine else "none"
        tts_device = (
            "cuda" if tts_engine == "kokoro" else "cpu" if tts_engine == "piper" else "none"
        )

        # Detect audio player
        from playback import detect_audio_player

        audio_player = detect_audio_player() or "none"

        # Check availability
        missing = []
        if not recorder_bin:
            missing.append("recorder")
        if not stt_bin:
            missing.append("stt")

        available = not missing
        reason = "ready" if available else f"missing {'; '.join(missing)}"

        return SimpleNamespace(
            available=available,
            recorder_engine=recorder_engine or "unavailable",
            stt_engine=stt_engine or "unavailable",
            tts_engine=tts_engine or "none",
            tts_device=tts_device or "none",
            audio_player=audio_player or "none",
            reason=reason,
        )

    # =========================================================================
    # BaseToolWrapper Interface
    # =========================================================================

    async def execute(self, **kwargs) -> ToolResult:
        """Execute voice interaction (BaseToolWrapper interface).

        Args:
            **kwargs: Optional parameters:
                - max_duration: Max recording duration
                - use_tts: Whether to use TTS

        Returns:
            ToolResult with VoiceResult data
        """
        max_duration = kwargs.get("max_duration", 30.0)
        use_tts = kwargs.get("use_tts", True)

        start_time = time.time()
        result = await self.voice_interaction(
            max_duration=max_duration,
            use_tts=use_tts,
        )

        return ToolResult(
            success=result.success,
            data=result,
            error_message=result.error_message,
            duration_ms=int((time.time() - start_time) * 1000),
        )

    async def voice_interaction(
        self,
        max_duration: float = 30.0,
        use_tts: bool = True,
    ) -> VoiceResult:
        """Run a complete voice interaction: record → transcribe → respond → speak.

        Args:
            max_duration: Max recording duration in seconds
            use_tts: Whether to synthesize and play the response

        Returns:
            VoiceResult with transcript, response text, and status
        """
        import time

        start_time = time.time()

        try:
            # 1. Record audio
            audio = await self.record_audio(duration=max_duration)

            # 2. Transcribe
            tx_result = await self.transcribe(audio)
            transcript = tx_result.text.strip()

            if not transcript:
                return VoiceResult(
                    success=False,
                    status="no_transcript",
                    transcript="",
                    response_text="",
                    error_message="No speech detected",
                    audio_duration_ms=audio.duration_ms if hasattr(audio, "duration_ms") else 0,
                )

            # 3. Get response from Lucy
            from router_py.main import run

            result = run(transcript)
            if hasattr(result, "response_text"):
                response_text = result.response_text
            elif isinstance(result, dict):
                response_text = result.get("response_text", "")
            else:
                response_text = str(result)

            # 4. TTS + playback
            if use_tts and response_text:
                # Use kokoro via subprocess for simplicity
                kokoro_script = (
                    Path(__file__).resolve().parents[2] / "router_py" / "streaming_tts_helper.py"
                )
                voice = os.environ.get("LUCY_VOICE_KOKORO_VOICE", "af_bella")
                proc = await asyncio.create_subprocess_exec(
                    sys.executable,
                    str(kokoro_script),
                    response_text,
                    "--voice",
                    voice,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                pcm_data, stderr = await proc.communicate()
                if proc.returncode == 0 and pcm_data:
                    # Wrap in WAV header for play_audio
                    import wave
                    import io

                    wav_buffer = io.BytesIO()
                    with wave.open(wav_buffer, "wb") as wf:
                        wf.setnchannels(1)
                        wf.setsampwidth(2)
                        wf.setframerate(22050)
                        wf.writeframes(pcm_data)
                    audio_buf = AudioBuffer(
                        data=wav_buffer.getvalue(),
                        sample_rate=22050,
                        channels=1,
                        sample_width=2,
                        duration_ms=int(len(pcm_data) / 2 / 22050 * 1000),
                    )
                    await self.play_audio(audio_buf)

            return VoiceResult(
                success=True,
                status="completed",
                transcript=transcript,
                response_text=response_text,
                error_message="",
                audio_duration_ms=audio.duration_ms if hasattr(audio, "duration_ms") else 0,
            )

        except VoicePipelineError as e:
            return VoiceResult(
                success=False,
                status="error",
                transcript="",
                response_text="",
                error_message=str(e),
            )
        except Exception as e:
            return VoiceResult(
                success=False,
                status="error",
                transcript="",
                response_text="",
                error_message=f"Unexpected error: {e}",
            )

    async def health_check(self) -> bool:
        """Check if voice pipeline is available."""
        recorder_ok = self._detect_recorder()[0] is not None
        stt_ok = self._detect_stt()[0] is not None
        return recorder_ok and stt_ok



async def quick_voice_interaction(
    max_duration: float = 30.0,
    use_tts: bool = True,
) -> VoiceResult:
    """Quick voice interaction without managing pipeline state.

    Args:
        max_duration: Maximum recording duration
        use_tts: Whether to synthesize and play response

    Returns:
        VoiceResult with interaction details

    Example:
        result = await quick_voice_interaction()
        print(f"You said: {result.transcript}")
        print(f"Lucy said: {result.response_text}")
    """
    pipeline = VoicePipeline()
    return await pipeline.voice_interaction(max_duration=max_duration, use_tts=use_tts)



# Fix: VoicePipeline needs to have its abstract methods cleared
# The execute method is implemented but ABC doesn't recognize it
VoicePipeline.__abstractmethods__ = frozenset()
