#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import stat
import struct
import sys
import tempfile
import textwrap
import wave
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools"))

from voice import playback


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="playback_priming_") as tmp_dir:
        root = Path(tmp_dir)
        wav_path = root / "sample.wav"
        log_path = root / "aplay_log.jsonl"
        bin_dir = root / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        write_sample_wav(wav_path)
        write_fake_aplay(bin_dir / "aplay")

        original_path = os.environ.get("PATH")
        os.environ["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        os.environ["LUCY_TEST_APLAY_LOG"] = str(log_path)
        try:
            playback.play_wav_file(wav_path, player="aplay", prime_ms=80, prepad_ms=0, timeout_seconds=5)
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path

        entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert_ok(len(entries) == 2, f"expected prime + real playback, got: {entries}")
        assert_ok(entries[0]["first_nonzero_frame"] is None, f"expected silent prime playback first, got: {entries}")
        assert_ok(entries[1]["first_nonzero_frame"] == 0, f"expected real playback second, got: {entries}")
    print("PASS: test_playback_priming")
    return 0


def write_sample_wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(22050)
        handle.writeframes(struct.pack("<hhhh", 1200, 900, 600, 300))


def write_fake_aplay(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import wave

            wav_path = sys.argv[-1]
            with wave.open(wav_path, "rb") as handle:
                channels = handle.getnchannels()
                sample_width = handle.getsampwidth()
                frame_count = handle.getnframes()
                raw = handle.readframes(frame_count)

            frame_size = channels * sample_width
            first_nonzero_frame = None
            for index in range(frame_count):
                start = index * frame_size
                frame = raw[start : start + frame_size]
                if any(byte != 0 for byte in frame):
                    first_nonzero_frame = index
                    break

            with open(os.environ["LUCY_TEST_APLAY_LOG"], "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"wav_path": wav_path, "first_nonzero_frame": first_nonzero_frame}) + "\\n")
            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


if __name__ == "__main__":
    raise SystemExit(main())
