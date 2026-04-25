#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path


class PlaybackError(RuntimeError):
    pass


def detect_audio_player() -> str:
    if shutil.which("aplay"):
        return "aplay"
    if shutil.which("paplay"):
        return "paplay"
    return ""


def player_command(selected_player: str, wav_path: Path) -> list[str]:
    if selected_player == "aplay":
        return ["aplay", "-q", str(wav_path)]
    if selected_player == "paplay":
        return ["paplay", str(wav_path)]
    raise PlaybackError(f"unsupported audio player: {selected_player}")


def run_player_command(command: list[str], *, timeout_seconds: int) -> None:
    completed = subprocess.run(
        command,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout_seconds,
        shell=False,
    )
    if completed.returncode != 0:
        raise PlaybackError("audio playback failed")


def play_wav_file(
    wav_path: Path,
    *,
    player: str | None = None,
    prepad_ms: int = 0,
    prime_ms: int = 0,
    timeout_seconds: int = 120,
) -> str:
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
                    run_player_command(player_command(selected_player, prime_path), timeout_seconds=max(5, min(timeout_seconds, 15)))
                except PlaybackError:
                    pass
            finally:
                try:
                    prime_path.unlink()
                except OSError:
                    pass

        run_player_command(player_command(selected_player, playback_path), timeout_seconds=timeout_seconds)
        return selected_player
    except subprocess.TimeoutExpired as exc:
        raise PlaybackError(f"audio playback timed out: {exc}") from exc
    except OSError as exc:
        raise PlaybackError(f"unable to run audio playback: {exc}") from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except OSError:
                pass


def create_prepadded_copy(wav_path: Path, prepad_ms: int) -> Path:
    if prepad_ms <= 0:
        return wav_path
    try:
        with wave.open(str(wav_path), "rb") as source:
            params = source.getparams()
            frame_rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            frame_count = source.getnframes()
            audio_data = source.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise PlaybackError(f"unable to read wav file: {exc}") from exc

    if frame_rate <= 0 or channels <= 0 or sample_width <= 0:
        raise PlaybackError("unable to pad wav file: invalid audio format")

    pad_frames = int(frame_rate * prepad_ms / 1000)
    if pad_frames <= 0:
        return wav_path

    silence = b"\x00" * pad_frames * channels * sample_width
    temp_handle = tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=wav_path.parent,
        prefix=f"{wav_path.stem}_prepad_",
        suffix=wav_path.suffix,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()

    try:
        with wave.open(str(temp_path), "wb") as destination:
            destination.setparams(params)
            destination.writeframes(silence + audio_data)
    except (OSError, wave.Error) as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise PlaybackError(f"unable to write prepadded wav file: {exc}") from exc
    return temp_path


def create_silence_copy(wav_path: Path, duration_ms: int) -> Path:
    if duration_ms <= 0:
        raise PlaybackError("unable to create silence wav: invalid duration")
    try:
        with wave.open(str(wav_path), "rb") as source:
            params = source.getparams()
            frame_rate = source.getframerate()
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
    except (OSError, EOFError, wave.Error) as exc:
        raise PlaybackError(f"unable to read wav file: {exc}") from exc

    if frame_rate <= 0 or channels <= 0 or sample_width <= 0:
        raise PlaybackError("unable to create silence wav: invalid audio format")

    silence_frames = int(frame_rate * duration_ms / 1000)
    if silence_frames <= 0:
        silence_frames = 1

    silence = b"\x00" * silence_frames * channels * sample_width
    temp_handle = tempfile.NamedTemporaryFile(
        "wb",
        delete=False,
        dir=wav_path.parent,
        prefix=f"{wav_path.stem}_prime_",
        suffix=wav_path.suffix,
    )
    temp_path = Path(temp_handle.name)
    temp_handle.close()
    try:
        with wave.open(str(temp_path), "wb") as destination:
            destination.setparams(params)
            destination.writeframes(silence)
    except (OSError, wave.Error) as exc:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise PlaybackError(f"unable to write silence wav file: {exc}") from exc
    return temp_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play a synthesized wav file with the Local Lucy audio backend.")
    parser.add_argument("--wav", required=True, help="Path to the wav file to play.")
    parser.add_argument("--player", default="", help="Override the audio player (aplay or paplay).")
    parser.add_argument("--prepad-ms", default="0", help="Optional leading silence to prepend before playback.")
    parser.add_argument("--prime-ms", default="0", help="Optional silent priming playback before the real wav.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        prepad_ms = int(str(args.prepad_ms).strip() or "0")
    except ValueError:
        prepad_ms = 0
    try:
        prime_ms = int(str(args.prime_ms).strip() or "0")
    except ValueError:
        prime_ms = 0
    try:
        play_wav_file(
            Path(args.wav).expanduser(),
            player=str(args.player).strip() or None,
            prepad_ms=max(prepad_ms, 0),
            prime_ms=max(prime_ms, 0),
        )
        return 0
    except PlaybackError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
