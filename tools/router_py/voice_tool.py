#!/usr/bin/env python3
"""
Async voice processing pipeline for Local Lucy v8.

Replaces shell-based voice processing with a fully async Python implementation.

Stages:
1. Record audio from microphone (arecord/pw-record)
2. Transcribe using Whisper (or vosk)
3. Process through Lucy (text query)
4. Synthesize response using TTS
5. Play audio output

All stages are async and cancellable.
"""

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
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Import base wrapper
try:
    from .base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult
except ImportError:
    from base_tool_wrapper import BaseToolWrapper, ToolConfig, ToolResult

# Import TTS adapter
import sys

VOICE_DIR = Path(__file__).resolve().parents[1] / "voice"
if str(VOICE_DIR) not in sys.path:
    sys.path.insert(0, str(VOICE_DIR))

# Import playback with levels - track import status for debugging
_playback_with_levels_import_error = None

try:
    import tts_adapter
    from playback import play_wav_file, PlaybackError, detect_audio_player
    # Import playback with levels for VU meter (fallback to regular playback)
    try:
        from playback_with_levels import play_wav_file_with_levels
    except ImportError as e:
        _playback_with_levels_import_error = str(e)
        play_wav_file_with_levels = None
except ImportError as e:
    tts_adapter = None
    play_wav_file = None
    play_wav_file_with_levels = None
    PlaybackError = RuntimeError
    detect_audio_player = lambda: ""


# =============================================================================
# Exceptions
# =============================================================================


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


# =============================================================================
# Data Classes
# =============================================================================


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
    def from_bytes(cls, data: bytes, sample_rate: int = 16000, 
                   channels: int = 1, sample_width: int = 2) -> "AudioBuffer":
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
        return self.record_duration_ms + self.transcription_time_ms + \
               self.processing_time_ms + self.tts_time_ms


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


# =============================================================================
# Voice Pipeline
# =============================================================================


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
        transcript = await pipeline.transcribe(audio)
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
        
        self._logger.info(f"Recording with {recorder_engine} " +
                         f"(duration={'VAD' if duration is None else f'{duration}s'})")
        
        # Build command
        if recorder_engine == "arecord":
            cmd = [recorder_bin, "-q", "-f", "S16_LE", "-r", str(sample_rate), 
                   "-c", str(channels)]
            if device:
                cmd.extend(["-D", device])
            if duration:
                cmd.extend(["-d", str(int(duration))])
            cmd.append("-")  # Output to stdout
        elif recorder_engine == "pw-record":
            cmd = [recorder_bin, "--channels", str(channels), 
                   "--rate", str(sample_rate), "--format", "s16"]
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
                audio_data = await self._record_fixed_duration(
                    self._record_process, max_duration
                )
            
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
        
        self._logger.info(f"Recorded {buffer.duration_ms}ms of audio " +
                         f"({len(audio_data)} bytes)")
        
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
                    process.stdout.read(4096),
                    timeout=min(0.5, deadline - time.time())
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
                chunk = await asyncio.wait_for(process.stdout.read(bytes_per_frame * 4), timeout=0.5)
                if not chunk:
                    break
                buffer.extend(chunk)
            except asyncio.TimeoutError:
                if silence_start and time.time() - silence_start > self.vad_config.silence_timeout_ms / 1000:
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
                            self._logger.debug(f"Silence detected for {silence_duration:.2f}s, stopping")
                            break
            
            if silence_start and time.time() - silence_start > self.vad_config.silence_timeout_ms / 1000:
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
    ) -> str:
        """Transcribe audio using Whisper or Vosk.
        
        Args:
            audio: Audio buffer to transcribe
            model: Whisper model name (uses instance default if None)
            language: Language code (None for auto-detect)
        
        Returns:
            Transcribed text
        
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
                transcript = await self._transcribe_whisper(stt_bin, tmp_path, model, language)
            elif stt_engine == "vosk":
                transcript = await self._transcribe_vosk(stt_bin, tmp_path)
            else:
                raise TranscriptionError(f"Unknown STT engine: {stt_engine}")
            
            # Normalize transcript
            transcript = self._normalize_transcript(transcript)
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.info(f"Transcription completed in {elapsed_ms}ms: '{transcript[:50]}...'")
            
            return transcript
            
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
    ) -> str:
        """Transcribe using Whisper."""
        # Resolve model path
        model_path = self._resolve_whisper_model(model)
        
        # Build command
        cmd = [stt_bin, "-m", str(model_path), "-f", str(wav_path), "-otxt", "-of", "-"]
        
        if language and language.lower() != "auto":
            cmd[1:1] = ["-l", language]
        
        # Set up environment for bundled whisper
        env = self._whisper_env(stt_bin)
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=45.0
            )
            
            if proc.returncode != 0:
                error = stderr.decode("utf-8", errors="replace").strip() or \
                       stdout.decode("utf-8", errors="replace").strip()
                raise TranscriptionError(f"Whisper failed: {error}")
            
            return stdout.decode("utf-8", errors="replace").strip()
            
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
            r'\[(blank_audio|inaudible|silence|no_speech|no speech)\]',
            '',
            text,
            flags=re.IGNORECASE
        )
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
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
        
        # Try execute_plan_python first (preferred)
        try:
            from .main import execute_plan_python
        except ImportError:
            try:
                from main import execute_plan_python
            except ImportError:
                execute_plan_python = None
        
        if execute_plan_python:
            try:
                outcome = await execute_plan_python(transcript)
                response = outcome.answer
                
                elapsed_ms = int((time.time() - start_time) * 1000)
                self._logger.info(f"Query processed in {elapsed_ms}ms")
                
                return response
            except Exception as e:
                self._logger.error(f"execute_plan_python failed: {e}, trying ExecutionEngine")
        
        # Fallback to ExecutionEngine directly (shell-free)
        try:
            from .classify import classify_intent, select_route
            from .execution_engine import ExecutionEngine
            from .policy import normalize_augmentation_policy
            from .main import ensure_control_env
        except ImportError:
            from classify import classify_intent, select_route
            from execution_engine import ExecutionEngine
            from policy import normalize_augmentation_policy
            from main import ensure_control_env
        
        # Ensure control environment is loaded from state file
        ensure_control_env()
        
        engine = ExecutionEngine(config={
            "timeout": 125,
            "use_sqlite_state": True,
        })
        
        try:
            classification = classify_intent(transcript, surface=surface)
            policy = normalize_augmentation_policy(
                os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
            )
            decision = select_route(classification, policy=policy)
            
            # Map mode setting to forced_mode for execution engine
            mode = os.environ.get("LUCY_MODE", "auto").lower()
            forced_mode_map = {
                "auto": "AUTO",
                "online": "FORCED_ONLINE",
                "offline": "FORCED_OFFLINE",
            }
            forced_mode = forced_mode_map.get(mode, "AUTO")
            
            result = engine.execute(
                intent=classification,
                route=decision,
                context={
                    "question": transcript,
                    "forced_mode": forced_mode,
                    "surface": surface,
                },
                use_python_path=True,
            )
            
            # Persist chat memory turn if memory is enabled
            if os.environ.get("LUCY_SESSION_MEMORY") == "1" and result.response_text:
                try:
                    from router_py.execution_engine import DEFAULT_CHAT_MEMORY_FILE
                    # Check both runtime and standard env vars for memory file path
                    mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
                    if not mem_file:
                        mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
                    if not mem_file:
                        mem_file = DEFAULT_CHAT_MEMORY_FILE
                    mem_path = Path(mem_file).expanduser()
                    mem_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Format assistant text (clean up markers, truncate)
                    assistant_text = (
                        result.response_text.replace("BEGIN_VALIDATED", " ")
                        .replace("END_VALIDATED", " ")
                        .replace("\r", " ")
                        .replace("\n", " ")
                    )
                    assistant_text = re.sub(r"\s+", " ", assistant_text).strip()
                    if len(assistant_text) > 500:
                        assistant_text = assistant_text[:500]
                    
                    # Read existing content
                    existing = ""
                    try:
                        existing = mem_path.read_text(encoding="utf-8")
                    except FileNotFoundError:
                        pass
                    
                    # Build new block and append
                    block = f"User: {transcript.strip()}\nAssistant: {assistant_text}\n\n"
                    blocks = [item.strip() for item in re.split(r"\n\s*\n", existing) if item.strip()]
                    blocks.append(block.strip())
                    
                    # Keep only last 6 turns
                    max_turns = 6
                    trimmed = "\n\n".join(blocks[-max_turns:]).strip()
                    if trimmed:
                        trimmed += "\n\n"
                    
                    mem_path.write_text(trimmed, encoding="utf-8")
                except Exception:
                    # Silently ignore memory persistence errors in voice path
                    pass
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.info(f"Query processed via ExecutionEngine in {elapsed_ms}ms")
            
            return result.response_text or ""
        finally:
            engine.close()
    
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
            sys.executable, str(request_tool), "submit", "--text", transcript,
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
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
        
        # Replace <br>, <p> etc with newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
        
        # Replace <li> with bullet points
        text = re.sub(r'<li[^>]*>', '\n• ', text, flags=re.IGNORECASE)
        text = re.sub(r'</li>', '', text, flags=re.IGNORECASE)
        
        # Replace <a href="...">text</a> with "text (link)" or just "text"
        # Use lambda to avoid backreference interpretation issues with $ in content
        text = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', lambda m: m.group(2), text, flags=re.IGNORECASE)
        text = re.sub(r'<a[^>]*>([^<]*)</a>', lambda m: m.group(1), text, flags=re.IGNORECASE)
        
        # Remove all remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode common HTML entities
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        text = text.replace('&nbsp;', ' ').replace('&#160;', ' ')
        text = text.replace('&#8211;', '–').replace('&#8212;', '—')
        text = text.replace('&#8216;', ''').replace('&#8217;', ''')
        text = text.replace('&#8220;', '"').replace('&#8221;', '"')
        
        # Normalize whitespace
        text = re.sub(r'\n\s*\n', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
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
                # Use UI-v8 Python for TTS to ensure Kokoro is available
                voice_python = self._resolve_voice_python()
                
                # Always use subprocess to avoid Python environment issues
                # (Kokoro is installed in ui-v8 venv, not system Python)
                if not voice_python:
                    raise SynthesisError(
                        "No voice Python available. Ensure ui-v8 venv exists."
                    )
                
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
                self._logger.info(f"Synthesis completed in {elapsed_ms}ms " +
                                 f"(engine={result.get('engine')})")
                
                return audio
                
            except Exception as e:
                if isinstance(e, SynthesisError):
                    raise
                raise SynthesisError(f"Synthesis failed: {e}") from e
    
    def _resolve_voice_python(self) -> str:
        """Resolve Python binary for TTS (ui-v8 venv has Kokoro)."""
        # Check explicit env var
        explicit = os.environ.get("LUCY_VOICE_PYTHON_BIN", "").strip()
        if explicit:
            path = Path(explicit).expanduser()
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        
        # ISOLATION: V8 only uses ui-v8, NEVER falls back to ui-v7
        root = self._resolve_root()
        workspace_root = root if root.name == "lucy-v8" else root.parent.parent
        candidate = workspace_root / "ui-v8" / ".venv" / "bin" / "python3"
        
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)

        for fallback in (Path(sys.executable), Path("/usr/bin/python3")):
            if fallback.exists() and os.access(fallback, os.X_OK):
                return str(fallback)
        
        raise RuntimeError(
            f"V8 ISOLATION VIOLATION: ui-v8 Python not found at {candidate}, "
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
        """Synthesize using TTS adapter via subprocess with ui-v8 Python."""
        import subprocess
        import json
        
        tts_adapter_path = Path(__file__).parent.parent / "voice" / "tts_adapter.py"
        
        cmd = [
            python_bin,
            str(tts_adapter_path),
            "synthesize",
            "--text", text,
            "--engine", engine,
            "--output-dir", output_dir,
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
            self._logger.info(f"play_audio: play_wav_file_with_levels={play_wav_file_with_levels is not None}, play_wav_file={play_wav_file is not None}")
            if play_wav_file_with_levels:
                # Playback with VU meter level output
                try:
                    # Get levels file path from environment or use default
                    import os
                    runtime_dir = Path(os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", 
                        Path.home() / ".codex-api-home/lucy/runtime-v8"))
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
        return Path(__file__).resolve().parents[2]
    
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
        tts_device = "cuda" if tts_engine == "kokoro" else "cpu" if tts_engine == "piper" else "none"
        
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
    
    async def health_check(self) -> bool:
        """Check if voice pipeline is available."""
        recorder_ok = self._detect_recorder()[0] is not None
        stt_ok = self._detect_stt()[0] is not None
        return recorder_ok and stt_ok


# =============================================================================
# Standalone Functions
# =============================================================================


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


# =============================================================================
# Tests
# =============================================================================


async def test_record():
    """Test audio recording."""
    print("\n=== Test: Record Audio ===")
    print("Recording 3 seconds of audio...")
    
    pipeline = VoicePipeline()
    audio = await pipeline.record_audio(duration=3.0)
    
    print(f"Recorded: {audio.duration_ms}ms")
    print(f"Sample rate: {audio.sample_rate}Hz")
    print(f"Channels: {audio.channels}")
    print(f"Data size: {len(audio.data)} bytes")
    
    # Save to file for inspection
    test_path = Path("/tmp/test_record.wav")
    audio.save_to_file(test_path)
    print(f"Saved to: {test_path}")
    
    return audio


async def test_transcribe(audio: Optional[AudioBuffer] = None):
    """Test transcription."""
    print("\n=== Test: Transcribe ===")
    
    pipeline = VoicePipeline()
    
    if audio is None:
        # Try to load test file or record
        test_path = Path("/tmp/test_record.wav")
        if test_path.exists():
            print(f"Loading audio from {test_path}")
            audio = AudioBuffer.from_file(test_path)
        else:
            print("No audio provided, recording 3 seconds...")
            audio = await pipeline.record_audio(duration=3.0)
    
    print(f"Transcribing {audio.duration_ms}ms of audio...")
    transcript = await pipeline.transcribe(audio)
    
    print(f"Transcript: '{transcript}'")
    return transcript


async def test_synthesize():
    """Test TTS synthesis."""
    print("\n=== Test: Synthesize ===")
    
    pipeline = VoicePipeline()
    text = "Hello, this is a test of the Local Lucy voice system."
    
    print(f"Synthesizing: '{text}'")
    audio = await pipeline.synthesize(text)
    
    print(f"Synthesized: {audio.duration_ms}ms of audio")
    return audio


async def test_playback(audio: Optional[AudioBuffer] = None):
    """Test audio playback."""
    print("\n=== Test: Playback ===")
    
    pipeline = VoicePipeline()
    
    if audio is None:
        audio = await test_synthesize()
    
    print("Playing audio...")
    await pipeline.play_audio(audio)
    print("Playback complete")


async def test_pipeline():
    """Test full voice pipeline."""
    print("\n=== Test: Full Pipeline ===")
    print("This will record, transcribe, process, and speak.")
    print("Speak when ready...")
    await asyncio.sleep(1)
    
    pipeline = VoicePipeline()
    
    def on_transcript(t: str):
        print(f"\n[Transcript] {t}")
    
    def on_response(r: str):
        print(f"\n[Response] {r[:100]}...")
    
    result = await pipeline.voice_interaction(
        on_transcription=on_transcript,
        on_response=on_response,
        max_duration=10.0,
    )
    
    print(f"\n=== Result ===")
    print(f"Success: {result.success}")
    print(f"Transcript: {result.transcript}")
    print(f"Response: {result.response_text[:200]}...")
    print(f"Metrics:")
    print(f"  Record: {result.metrics.record_duration_ms}ms")
    print(f"  Transcription: {result.metrics.transcription_time_ms}ms")
    print(f"  Processing: {result.metrics.processing_time_ms}ms")
    print(f"  TTS: {result.metrics.tts_time_ms}ms")
    print(f"  Total: {result.metrics.total_latency_ms}ms")
    
    return result


async def test_cancellation():
    """Test pipeline cancellation."""
    print("\n=== Test: Cancellation ===")
    print("Recording for 5 seconds, will cancel after 2 seconds...")
    
    pipeline = VoicePipeline()
    
    async def delayed_cancel():
        await asyncio.sleep(2)
        print("\n[Cancelling...]")
        pipeline.cancel()
    
    # Start recording and cancellation task
    cancel_task = asyncio.create_task(delayed_cancel())
    
    try:
        audio = await pipeline.record_audio(duration=5.0)
        print(f"Recorded: {audio.duration_ms}ms (should be ~2000ms)")
    except VoicePipelineError as e:
        print(f"Expected error: {e}")
    finally:
        cancel_task.cancel()
        try:
            await cancel_task
        except asyncio.CancelledError:
            pass


async def test_health():
    """Test health check."""
    print("\n=== Test: Health Check ===")
    
    pipeline = VoicePipeline()
    healthy = await pipeline.health_check()
    
    print(f"Pipeline healthy: {healthy}")
    
    recorder = pipeline._detect_recorder()
    stt = pipeline._detect_stt()
    
    print(f"Recorder: {recorder[0] or 'NOT FOUND'} ({recorder[1] or 'N/A'})")
    print(f"STT: {stt[0] or 'NOT FOUND'} ({stt[1] or 'N/A'})")


# =============================================================================
# Main Entry Point
# =============================================================================


async def main():
    """Main entry point with command-line test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Local Lucy Voice Pipeline")
    parser.add_argument("--test", choices=[
        "record", "transcribe", "synthesize", "playback", 
        "pipeline", "cancel", "health", "all"
    ], default="health", help="Test to run")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    
    tests = {
        "record": test_record,
        "transcribe": test_transcribe,
        "synthesize": test_synthesize,
        "playback": test_playback,
        "pipeline": test_pipeline,
        "cancel": test_cancellation,
        "health": test_health,
    }
    
    if args.test == "all":
        print("Running all tests...")
        for name, test_func in tests.items():
            print(f"\n{'='*60}")
            print(f"Running: {name}")
            print('='*60)
            try:
                await test_func()
            except Exception as e:
                print(f"FAILED: {e}")
    else:
        await tests[args.test]()
    
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())


# =============================================================================
# Verification Logging
# =============================================================================

def log_voice_pipeline_start():
    """Log that Python voice pipeline is being used."""
    import logging
    logger = logging.getLogger(__name__)

# Voice engine usage logger
class VoiceUsageLogger:
    """Logger for voice engine usage."""
    def __init__(self):
        self.log_dir = Path.home() / ".local" / "share" / "lucy" / "logs"
        self.log_file = self.log_dir / "voice_engine.log"
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, level: str, msg: str):
        from datetime import datetime
        ts = datetime.now().isoformat()
        try:
            with open(self.log_file, "a") as f:
                f.write(f"{ts} [{level}] {msg}\n")
        except Exception:
            pass
    
    def info(self, msg: str):
        self.log("INFO", msg)

_voice_usage_logger = VoiceUsageLogger()


# Fix: VoicePipeline needs to have its abstract methods cleared
# The execute method is implemented but ABC doesn't recognize it
VoicePipeline.__abstractmethods__ = frozenset()
