#!/usr/bin/env python3
"""
Background voice recorder for Local Lucy PTT.

This module runs as a standalone background process that:
1. Records audio continuously until signaled to stop
2. Listens for SIGTERM to stop gracefully
3. Saves recorded audio to specified file path
4. Writes PID to runtime file for parent process tracking

Usage:
    python3 voice_recorder.py --output /path/to/output.wav --runtime-file /path/to/voice_runtime.json

Signals:
    SIGTERM: Stop recording gracefully and exit
"""

import argparse
import audioop
import json
import os
import signal
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Optional

# Global for audio level updates
_audio_level_state = {
    "running": False,
    "level": 0,
    "last_update": 0,
}
_audio_levels_file: Optional[Path] = None

# Recording parameters
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit
CHUNK_SIZE = 1024

# Safety cap to prevent runaway recording (configurable via env var)
_MAX_RECORDING_DURATION_SECONDS = int(os.environ.get("LUCY_VOICE_PTT_MAX_SECONDS", "60"))
if _MAX_RECORDING_DURATION_SECONDS <= 0:
    _MAX_RECORDING_DURATION_SECONDS = 60  # Fallback for invalid values

# Global state for signal handling
_recording = True
_stop_requested = False
_output_path: Optional[Path] = None
_temp_path: Optional[Path] = None

def get_logger():
    """Get simple logger."""
    import logging
    logger = logging.getLogger("voice_recorder")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def check_stop_signal(stop_file: Optional[Path] = None) -> bool:
    """Check if stop signal has been sent.
    
    Uses either a stop file (created by parent) or PID-based signal.
    """
    global _stop_requested
    
    if _stop_requested:
        return True
    
    # Check for stop file (alternative to signals)
    if stop_file and stop_file.exists():
        return True
    
    return False

def detect_recorder() -> tuple[str, str]:
    """Detect available audio recorder."""
    arecord = shutil.which("arecord")
    if arecord:
        return "arecord", arecord
    pw_record = shutil.which("pw-record")
    if pw_record:
        return "pw-record", pw_record
    return "", ""

def build_record_command(recorder_bin: str, channels: int = 1, sample_rate: int = 16000) -> list[str]:
    """Build recorder command."""
    if "arecord" in recorder_bin:
        return [
            recorder_bin,
            "-q",
            "-t", "wav",
            "-f", "S16_LE",
            "-r", str(sample_rate),
            "-c", str(channels),
            "-",
        ]
    elif "pw-record" in recorder_bin:
        return [
            recorder_bin,
            "--rate", str(sample_rate),
            "--channels", str(channels),
            "--format", "s16",
            "-",
        ]
    else:
        raise RuntimeError(f"Unknown recorder: {recorder_bin}")

def write_pid_to_runtime(runtime_file: Path, pid: int, capture_path: Path) -> None:
    """Write recording state to runtime file."""
    try:
        if runtime_file.exists():
            with open(runtime_file) as f:
                state = json.load(f)
        else:
            state = {}
        
        state.update({
            "record_pid": pid,
            "capture_path": str(capture_path),
            "recording_started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "listening",
            "listening": True,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        
        # Atomic write
        tmp_file = runtime_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2)
        tmp_file.rename(runtime_file)
    except Exception as e:
        get_logger().error(f"Failed to write runtime state: {e}")

def clear_pid_from_runtime(runtime_file: Path) -> None:
    """Clear recording state from runtime file."""
    try:
        if runtime_file.exists():
            with open(runtime_file) as f:
                state = json.load(f)
        else:
            state = {}
        
        state.update({
            "record_pid": None,
            "recording_stopped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "status": "processing" if state.get("capture_path") else "idle",
            "listening": False,
            "last_updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        
        tmp_file = runtime_file.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(state, f, indent=2)
        tmp_file.rename(runtime_file)
    except Exception as e:
        get_logger().error(f"Failed to clear runtime state: {e}")


def start_audio_level_writer(runtime_file: Path) -> None:
    """Start the audio level writer thread."""
    global _audio_levels_file, _audio_level_state
    
    # Audio levels file is alongside runtime file
    _audio_levels_file = runtime_file.parent / "voice_audio_levels.json"
    _audio_level_state["running"] = True
    _audio_level_state["level"] = 0
    _audio_level_state["last_update"] = time.time()
    
    # Start writer thread
    thread = threading.Thread(target=_audio_level_writer_loop, daemon=True)
    thread.start()


def stop_audio_level_writer() -> None:
    """Stop the audio level writer."""
    global _audio_level_state
    _audio_level_state["running"] = False


def _read_existing_output_level() -> int:
    """Read existing output_level from file if it exists."""
    global _audio_levels_file
    try:
        if _audio_levels_file and _audio_levels_file.exists():
            with open(_audio_levels_file, 'r') as f:
                data = json.load(f)
                return int(data.get("output_level", 0))
    except Exception:
        pass
    return 0


def _audio_level_writer_loop() -> None:
    """Background thread: write audio levels to file every 30ms."""
    global _audio_levels_file, _audio_level_state
    
    logger = get_logger()
    
    while _audio_level_state["running"]:
        try:
            if _audio_levels_file:
                # Preserve output_level from existing file
                output_level = _read_existing_output_level()
                
                # Write current level
                data = {
                    "input_level": _audio_level_state["level"],
                    "output_level": output_level,
                    "timestamp": time.time(),
                    "recording": True,
                }
                
                # Atomic write
                tmp_file = _audio_levels_file.with_suffix('.tmp')
                with open(tmp_file, 'w') as f:
                    json.dump(data, f)
                tmp_file.rename(_audio_levels_file)
        except Exception as e:
            logger.debug(f"Audio level write error: {e}")
        
        # Update every 30ms (~33fps)
        time.sleep(0.03)
    
    # Write final zero level when stopping (preserve output_level)
    try:
        if _audio_levels_file:
            output_level = _read_existing_output_level()
            data = {
                "input_level": 0,
                "output_level": output_level,
                "timestamp": time.time(),
                "recording": False,
            }
            with open(_audio_levels_file, 'w') as f:
                json.dump(data, f)
    except Exception:
        pass


def update_audio_level(audio_data: bytes) -> None:
    """
    Calculate RMS from audio chunk and update level.
    
    Args:
        audio_data: Raw audio bytes (16-bit PCM)
    """
    global _audio_level_state
    
    if not audio_data:
        return
    
    try:
        # Calculate RMS
        rms = audioop.rms(audio_data, 2)  # 16-bit = 2 bytes
        
        # Convert to 0-100 scale
        # RMS for 16-bit audio ranges 0-32767
        # Use logarithmic scale for better visual response
        if rms > 0:
            import math
            # Log scale: 0-100 mapped to -60dB to 0dB
            db = 20 * math.log10(rms / 32767.0)
            level = int((db + 60) / 60 * 100)
            level = max(0, min(100, level))
        else:
            level = 0
        
        # Smooth the level (exponential moving average)
        old_level = _audio_level_state["level"]
        smoothed = int(0.3 * level + 0.7 * old_level)
        _audio_level_state["level"] = smoothed
        
    except Exception:
        pass

def signal_handler(signum, frame):
    """Handle SIGTERM to stop recording gracefully."""
    global _recording, _stop_requested
    get_logger().info(f"Received signal {signum}, stopping recording...")
    _stop_requested = True
    _recording = False

def record_audio(output_path: Path, runtime_file: Optional[Path] = None, stop_file: Optional[Path] = None, max_duration_seconds: Optional[int] = None) -> bool:
    """Record audio until signaled to stop.
    
    CRITICAL: Start audio capture IMMEDIATELY to avoid truncating first word.
    PID/state writing happens AFTER recording starts.
    
    Args:
        output_path: Path to save the recorded WAV file
        runtime_file: Optional path to runtime file for state tracking
        stop_file: Optional path to stop file (created by parent to signal stop)
        max_duration_seconds: Optional maximum recording duration (defaults to MAX_RECORDING_DURATION_SECONDS)
        
    Returns:
        True if recording succeeded, False otherwise
    """
    global _output_path, _temp_path
    
    logger = get_logger()
    _output_path = output_path
    
    # Detect recorder
    recorder_name, recorder_bin = detect_recorder()
    if not recorder_bin:
        logger.error("No audio recorder found (arecord or pw-record)")
        return False
    
    # Build command
    cmd = build_record_command(recorder_bin)
    
    # Create output directory
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # START RECORDING IMMEDIATELY (before any other operations)
    # This ensures audio capture begins as soon as possible
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        logger.info(f"Recorder started with PID {proc.pid}")
    except Exception as e:
        logger.error(f"Failed to start recorder: {e}")
        return False
    
    # NOW write PID to runtime file (after recording has started)
    # This minimizes latency between user pressing button and audio capture
    if runtime_file:
        write_pid_to_runtime(runtime_file, os.getpid(), output_path)
        # Start audio level writer (for VU meter)
        start_audio_level_writer(runtime_file)
    
    logger.info(f"Recording started (recorder PID: {proc.pid})")
    
    # Open temp file for writing
    try:
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            _temp_path = Path(tmp.name)
            
            # Write WAV header
            with wave.open(tmp.name, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(SAMPLE_RATE)
                
                # Read audio data until stopped or max duration reached
                import select
                max_dur = max_duration_seconds if max_duration_seconds is not None else _MAX_RECORDING_DURATION_SECONDS
                recording_start_time = time.monotonic()
                while _recording and not check_stop_signal(stop_file):
                    if time.monotonic() - recording_start_time >= max_dur:
                        logger.warning(f"Recording stopped after reaching max duration ({max_dur}s)")
                        break
                    try:
                        # Use select to check if data is available with timeout
                        ready, _, _ = select.select([proc.stdout], [], [], 0.1)
                        if ready:
                            data = proc.stdout.read(CHUNK_SIZE)
                            if not data:
                                break
                            wav_file.writeframesraw(data)
                            # Update audio level for VU meter
                            update_audio_level(data)
                    except select.error:
                        break
                    except Exception as e:
                        logger.error(f"Error reading audio: {e}")
                        break
            
            # Check if we got any audio
            tmp_size = _temp_path.stat().st_size
            logger.info(f"Recorded {tmp_size} bytes to temp file")
            
            # Stop audio level writer
            stop_audio_level_writer()
            
            # Terminate recorder
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            
            # Move temp file to final location
            # Use shutil.move instead of rename because rename doesn't work across filesystems
            try:
                import shutil
                shutil.move(str(_temp_path), str(output_path))
                logger.info(f"Recording saved to {output_path}")
            except Exception as e:
                logger.error(f"Failed to move recording to final location: {e}")
                return False
            
            # Note: We don't update runtime file here - let ptt-stop handle state updates
            # This avoids race conditions where recorder finishes before ptt-stop runs
            
            return True
    
    except Exception as e:
        logger.error(f"Recording failed: {e}")
        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except:
                proc.kill()
        # Note: We don't update runtime file here - let ptt-stop handle state updates
        return False
    
    finally:
        # Cleanup temp file if it still exists
        if _temp_path and _temp_path.exists():
            try:
                _temp_path.unlink()
            except:
                pass

def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Background voice recorder")
    parser.add_argument(
        "--output", "-o",
        type=Path,
        required=True,
        help="Output WAV file path"
    )
    parser.add_argument(
        "--runtime-file", "-r",
        type=Path,
        default=None,
        help="Runtime state file path (for PID tracking)"
    )
    parser.add_argument(
        "--duration", "-d",
        type=float,
        default=None,
        help="Maximum recording duration in seconds (default: unlimited until stopped)"
    )
    parser.add_argument(
        "--stop-file", "-s",
        type=Path,
        default=None,
        help="Stop file path (recording stops when this file is created)"
    )
    
    args = parser.parse_args()
    
    # Setup signal handlers (SIGTERM still works but is less reliable)
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    logger = get_logger()
    logger.info("Voice recorder starting...")
    
    # Set duration timer if specified
    if args.duration:
        def timeout_handler(signum, frame):
            logger.info(f"Duration limit ({args.duration}s) reached, stopping...")
            signal_handler(signum, frame)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(args.duration))
    
    # Start recording (will check for stop file if provided)
    success = record_audio(args.output, args.runtime_file, args.stop_file)
    
    if success:
        logger.info("Recording completed successfully")
        return 0
    else:
        logger.error("Recording failed")
        return 1

if __name__ == "__main__":
    sys.exit(main())
