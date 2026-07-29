"""Audio level / VU meter utilities for streaming voice."""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from tools.xdg_paths import lucy_runtime_namespace_root


def _get_audio_levels_file() -> Path:
    """Get path to audio levels file for VU meter."""
    runtime_dir = Path(
        os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(lucy_runtime_namespace_root()))
    )
    return runtime_dir / "state" / "voice_audio_levels.json"


def _read_existing_input_level(levels_file: Path) -> int:
    """Read existing input_level from file if present."""
    try:
        if levels_file.exists():
            with open(levels_file, "r") as f:
                data = json.load(f)
                return int(data.get("input_level", 0))
    except Exception:
        pass
    return 0


def _write_output_level(level: int, levels_file: Path) -> None:
    """Write output audio level to file (preserves input_level)."""
    import logging

    logger = logging.getLogger("streaming_voice")
    try:
        # Ensure parent directory exists
        levels_file.parent.mkdir(parents=True, exist_ok=True)

        input_level = _read_existing_input_level(levels_file)
        data = {
            "input_level": input_level,
            "output_level": level,
            "timestamp": time.time(),
            "playing": level > 0,
        }
        # Atomic write
        tmp_file = levels_file.with_suffix(".tmp")
        with open(tmp_file, "w") as f:
            json.dump(data, f)
        tmp_file.rename(levels_file)
        logger.debug(f"Wrote output_level={level} to {levels_file}")
    except Exception as e:
        logger.debug(f"Level write error: {e}")


def _calculate_pcm_level(pcm_data: bytes) -> int:
    """Calculate audio level (0-100) from PCM data using peak detection."""
    if not pcm_data:
        return 0
    try:
        # Use max (peak) level instead of RMS for more dynamic response
        # This better follows speech patterns as it catches transients
        sample_count = len(pcm_data) // 2  # 16-bit samples
        max_val = 0
        for i in range(sample_count):
            # Extract 16-bit signed sample
            sample = pcm_data[i * 2] | (pcm_data[i * 2 + 1] << 8)
            if sample > 32767:
                sample -= 65536
            abs_sample = abs(sample)
            if abs_sample > max_val:
                max_val = abs_sample

        if max_val > 0:
            # Convert to dB scale 0-100
            # 16-bit max is 32767, map -60dB to 0% and 0dB to 100%
            db = 20 * math.log10(max_val / 32767.0)
            level = int((db + 60) / 60 * 100)
            return max(0, min(100, level))
    except Exception:
        pass
    return 0


def _analyze_pcm_levels(
    pcm_data: bytes, sample_rate: int = 22050, chunk_duration_ms: float = 30.0
) -> list[int]:
    """Analyze PCM data into level chunks for VU meter.

    Args:
        pcm_data: Raw PCM data (16-bit mono)
        sample_rate: Sample rate in Hz
        chunk_duration_ms: Duration of each chunk in milliseconds

    Returns:
        List of audio levels (0-100) for each chunk
    """
    if not pcm_data:
        return []

    levels = []
    sample_width = 2  # 16-bit = 2 bytes
    chunk_samples = int(sample_rate * chunk_duration_ms / 1000)
    chunk_bytes = chunk_samples * sample_width

    # Process PCM data in chunks
    offset = 0
    while offset < len(pcm_data):
        chunk = pcm_data[offset : offset + chunk_bytes]
        if len(chunk) < sample_width:
            break

        level = _calculate_pcm_level(chunk)
        levels.append(level)
        offset += chunk_bytes

    return levels
