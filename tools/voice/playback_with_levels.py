#!/usr/bin/env python3
"""
Playback with real-time audio level monitoring for VU meter.

Analyzes WAV file audio levels during playback and writes to
voice_audio_levels.json for the HMI VU meter display.
"""

from __future__ import annotations

import audioop
import json
import math
import subprocess
import threading
import time
import wave
from pathlib import Path
from typing import Optional

try:
    # When imported as part of voice package
    from voice.playback import (
        PlaybackError,
        create_prepadded_copy,
        create_silence_copy,
        detect_audio_player,
        play_wav_file,
        player_command,
        run_player_command,
    )
except ImportError:
    # When imported directly
    from playback import (
        PlaybackError,
        create_prepadded_copy,
        create_silence_copy,
        detect_audio_player,
        play_wav_file,
        player_command,
        run_player_command,
    )


def _write_output_level(level: list[int], levels_file: Path, running: list[bool]) -> None:
    """
    Background thread: write output audio level to file.
    Preserves input_level from existing file if present.
    
    Args:
        level: List containing current audio level 0-100 (mutable for updates)
        levels_file: Path to audio levels JSON file
        running: List with single boolean to control thread
    """
    import logging
    logger = logging.getLogger("playback_with_levels")
    logger.info(f"Level writer thread started: {levels_file}")
    
    def _read_existing_levels() -> dict[str, object]:
        """Read existing levels so playback does not clobber recording state."""
        try:
            if levels_file.exists():
                with open(levels_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}
    
    while running[0]:
        try:
            existing = _read_existing_levels()
            
            data = {
                "input_level": int(existing.get("input_level", 0)),
                "output_level": level[0],
                "recording": bool(existing.get("recording", False)),
                "timestamp": time.time(),
                "playing": True,
            }
            # Atomic write
            tmp_file = levels_file.with_suffix('.tmp')
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            tmp_file.rename(levels_file)
        except Exception as e:
            logger.debug(f"Level write error: {e}")
        
        # Update every 30ms
        time.sleep(0.03)
    
    logger.info("Level writer thread stopping")
    # Write final zero level (preserve input_level)
    try:
        existing = _read_existing_levels()
        data = {
            "input_level": int(existing.get("input_level", 0)),
            "output_level": 0,
            "recording": bool(existing.get("recording", False)),
            "timestamp": time.time(),
            "playing": False,
        }
        with open(levels_file, "w", encoding="utf-8") as f:
            json.dump(data, f)
        logger.info("Final zero level written")
    except Exception as e:
        logger.debug(f"Final level write error: {e}")


def _analyze_wav_levels(
    wav_path: Path,
    chunk_duration_ms: float = 30.0,
) -> list[int]:
    """
    Pre-analyze WAV file and calculate RMS levels for each chunk.
    
    Args:
        wav_path: Path to WAV file
        chunk_duration_ms: Duration of each chunk in milliseconds
        
    Returns:
        List of audio levels (0-100) for each chunk
    """
    levels = []
    
    try:
        with wave.open(str(wav_path), 'rb') as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            
            # Calculate chunk size in frames
            chunk_frames = int(frame_rate * chunk_duration_ms / 1000)
            
            # Read and analyze chunks
            while n_frames > 0:
                frames_to_read = min(chunk_frames, n_frames)
                data = wav_file.readframes(frames_to_read)
                
                if not data:
                    break
                
                # Calculate RMS
                if len(data) >= sample_width:
                    rms = audioop.rms(data, sample_width)
                    
                    # Convert to dB scale 0-100
                    if rms > 0:
                        # 16-bit max is 32767
                        db = 20 * math.log10(rms / 32767.0)
                        level = int((db + 60) / 60 * 100)
                        level = max(0, min(100, level))
                    else:
                        level = 0
                    
                    levels.append(level)
                else:
                    levels.append(0)
                
                n_frames -= frames_to_read
    
    except Exception:
        # Return empty list on error
        pass
    
    return levels


def play_wav_file_with_levels(
    wav_path: Path,
    levels_file: Path,
    *,
    player: Optional[str] = None,
    prepad_ms: int = 0,
    prime_ms: int = 0,
    timeout_seconds: int = 120,
) -> None:
    """
    Play WAV file with real-time audio level output for VU meter.
    
    Args:
        wav_path: Path to WAV file to play
        levels_file: Path to write audio levels (voice_audio_levels.json)
        player: Optional player override (aplay/paplay)
        prepad_ms: Optional leading silence to prepend before playback
        prime_ms: Optional silent priming playback before real playback
        timeout_seconds: Playback timeout
        
    Raises:
        PlaybackError: If playback fails
    """
    import shutil
    import logging
    logger = logging.getLogger("playback_with_levels")
    
    # Convert to Path if string
    wav_path = Path(wav_path) if isinstance(wav_path, str) else wav_path
    levels_file = Path(levels_file) if isinstance(levels_file, str) else levels_file
    
    logger.info(f"play_wav_file_with_levels called: wav={wav_path}, levels_file={levels_file}")
    
    if not wav_path.exists():
        raise PlaybackError(f"missing wav file: {wav_path}")
    
    selected_player = player or detect_audio_player()
    if not selected_player:
        raise PlaybackError("no audio player available")
    
    playback_path = wav_path
    temp_path: Path | None = None
    try:
        if prepad_ms > 0:
            temp_path = create_prepadded_copy(wav_path, prepad_ms)
            playback_path = temp_path

        if prime_ms > 0:
            prime_path = create_silence_copy(playback_path, prime_ms)
            try:
                try:
                    run_player_command(
                        player_command(selected_player, prime_path),
                        timeout_seconds=max(5, min(timeout_seconds, 15)),
                    )
                except PlaybackError:
                    pass
            finally:
                try:
                    prime_path.unlink()
                except OSError:
                    pass

        # Pre-analyze WAV levels
        levels = _analyze_wav_levels(playback_path)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass
        raise
    logger.info(f"Analyzed {len(levels)} level chunks from WAV")
    
    if not levels:
        # No levels analyzed, fall back to standard playback
        try:
            play_wav_file(
                wav_path,
                player=player,
                prepad_ms=prepad_ms,
                prime_ms=prime_ms,
                timeout_seconds=timeout_seconds,
            )
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        return
    
    # Start player subprocess
    cmd = player_command(selected_player, playback_path)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    
    # Start level writer thread
    running = [True]
    current_level = [0]  # List so it can be mutated by reference
    
    def level_updater():
        """Update current level based on playback progress."""
        import logging
        logger = logging.getLogger("playback_with_levels")
        chunk_duration = 0.03  # 30ms per chunk
        start_time = time.time()
        logger.info(f"Level updater thread started: {len(levels)} chunks")
        
        for i, level in enumerate(levels):
            if not running[0]:
                break
            current_level[0] = level
            
            # Wait for next chunk time
            expected_time = start_time + (chunk_duration * (i + 1))
            sleep_time = expected_time - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)
        
        logger.info("Level updater thread done")
    
    # Start threads
    writer_thread = threading.Thread(
        target=_write_output_level,
        args=(current_level, levels_file, running),
        daemon=True
    )
    updater_thread = threading.Thread(
        target=level_updater,
        daemon=True
    )
    
    writer_thread.start()
    updater_thread.start()
    
    try:
        # Wait for playback to complete
        returncode = proc.wait(timeout=timeout_seconds)
        if returncode != 0:
            raise PlaybackError("audio playback failed")
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except:
            proc.kill()
        raise PlaybackError("playback timed out")
    finally:
        # Stop threads
        running[0] = False
        writer_thread.join(timeout=0.5)
        updater_thread.join(timeout=0.5)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    # Test
    import sys
    if len(sys.argv) >= 2:
        wav_path = Path(sys.argv[1])
        levels_file = Path(sys.argv[2]) if len(sys.argv) >= 3 else Path("/tmp/test_audio_levels.json")
        try:
            play_wav_file_with_levels(wav_path, levels_file)
            print(f"Playback complete, levels written to {levels_file}")
        except PlaybackError as e:
            print(f"Error: {e}")
            sys.exit(1)
