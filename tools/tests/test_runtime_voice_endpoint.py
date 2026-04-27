#!/usr/bin/env python3
from __future__ import annotations

import json
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_VOICE_SOURCE = REPO_ROOT / "tools" / "runtime_voice.py"
RUNTIME_CONTROL_SOURCE = REPO_ROOT / "tools" / "runtime_control.py"
VOICE_PACKAGE_SOURCE = REPO_ROOT / "tools" / "voice"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="runtime_voice_endpoint_") as tmp_dir:
        root = Path(tmp_dir)
        home = root / "home"
        bin_dir = root / "bin"
        capture_dir = home / ".codex-api-home" / "lucy" / "runtime-v8" / "voice" / "ui_ptt"
        runtime_namespace_root = home / ".codex-api-home" / "lucy" / "runtime-v8"
        state_dir = home / ".codex-api-home" / "lucy" / "runtime-v8" / "state"
        ui_root = home / "lucy" / "ui-v8"
        tools_dir = home / "lucy" / "snapshots" / "lucy-v8" / "tools"
        authority_root = home / "lucy" / "snapshots" / "lucy-v8"
        runtime_file = state_dir / "voice_runtime.json"
        state_file = state_dir / "current_state.json"
        request_history = state_dir / "request_history.jsonl"
        request_result = state_dir / "last_request_result.json"

        bin_dir.mkdir(parents=True, exist_ok=True)
        capture_dir.mkdir(parents=True, exist_ok=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        ui_root.mkdir(parents=True, exist_ok=True)
        tools_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RUNTIME_VOICE_SOURCE, tools_dir / "runtime_voice.py")
        shutil.copy2(RUNTIME_CONTROL_SOURCE, tools_dir / "runtime_control.py")
        shutil.copytree(VOICE_PACKAGE_SOURCE, tools_dir / "voice")

        write_executable(
            bin_dir / "arecord",
            """
            #!/usr/bin/env python3
            import signal
            import sys
            import time

            output_path = sys.argv[-1]
            running = True

            def stop(_sig, _frame):
                global running
                running = False

            signal.signal(signal.SIGINT, stop)
            signal.signal(signal.SIGTERM, stop)
            while running:
                time.sleep(0.05)
            with open(output_path, "wb") as handle:
                handle.write(b"RIFF....WAVEfmt ")
            """,
        )
        write_executable(
            bin_dir / "whisper",
            """
            #!/usr/bin/env python3
            import sys

            args = sys.argv[1:]
            prefix = args[args.index("-of") + 1]
            with open(prefix + ".txt", "w", encoding="utf-8") as handle:
                handle.write("hello from endpoint test")
            """,
        )
        write_executable(
            tools_dir / "runtime_request.py",
            """
            #!/usr/bin/env python3
            import json
            import os
            import sys
            from pathlib import Path

            transcript = sys.argv[-1]
            state_dir = Path(os.path.expanduser("~/.codex-api-home/lucy/runtime-v8/state"))
            state_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "accepted": True,
                "completed_at": "2026-03-21T00:00:00Z",
                "control_state": {
                    "mode": "auto",
                    "memory": "on",
                    "evidence": "on",
                    "voice": "on",
                    "voice_tts_chunk_pause_ms": 56,
                    "model": "local-lucy",
                    "profile": "test-profile",
                },
                "error": "",
                "outcome": {
                    "action_hint": "",
                    "evidence_created": "false",
                    "outcome_code": "answered",
                    "rc": 0,
                    "utc": "2026-03-21T00:00:00Z",
                },
                "request_id": "req-endpoint-1",
                "request_text": transcript,
                "response_text": "endpoint response",
                "route": {
                    "mode": "LOCAL",
                    "query": transcript,
                    "reason": "endpoint-test",
                    "session_id": "",
                    "utc": "2026-03-21T00:00:00Z",
                },
                "status": "completed",
            }
            result_path = state_dir / "last_request_result.json"
            history_path = state_dir / "request_history.jsonl"
            with result_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.write("\\n")
            with history_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\\n")
            print(json.dumps(payload))
            """,
        )

        state_file.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "profile": "test-profile",
                    "mode": "auto",
                    "memory": "on",
                    "evidence": "on",
                    "voice": "on",
                    "voice_tts_chunk_pause_ms": 56,
                    "model": "local-lucy",
                    "approval_required": False,
                    "status": "ready",
                    "last_updated": "2026-03-21T00:00:00Z",
                }
            )
            + "\n",
            encoding="utf-8",
        )

        env = build_env(
            home=home,
            bin_dir=bin_dir,
            request_tool=tools_dir / "runtime_request.py",
            authority_root=authority_root,
            ui_root=ui_root,
            runtime_namespace_root=runtime_namespace_root,
        )
        runtime_voice = tools_dir / "runtime_voice.py"

        status_result = run_voice(runtime_voice, "status", state_file, runtime_file, capture_dir, env)
        assert_ok(status_result.returncode == 0, f"status failed: {status_result.stderr}")
        status_payload = json.loads(status_result.stdout)
        assert_ok(status_payload["status"] == "idle", f"unexpected idle status: {status_payload}")
        assert_ok(runtime_file.exists(), "status did not materialize voice_runtime.json")

        run_control(tools_dir / "runtime_control.py", state_file, "set-voice", "off", env)
        disabled_start = run_voice(runtime_voice, "ptt-start", state_file, runtime_file, capture_dir, env)
        assert_ok(disabled_start.returncode == 2, f"expected disabled rc=2, got {disabled_start.returncode}")
        disabled_runtime = load_json(runtime_file)
        assert_ok(disabled_runtime["status"] == "disabled", f"expected disabled runtime, got {disabled_runtime}")

        run_control(tools_dir / "runtime_control.py", state_file, "set-voice", "on", env)
        stop_not_listening = run_voice(runtime_voice, "ptt-stop", state_file, runtime_file, capture_dir, env)
        assert_ok(stop_not_listening.returncode == 7, f"expected not-listening rc=7, got {stop_not_listening.returncode}")

        first_start = run_voice(runtime_voice, "ptt-start", state_file, runtime_file, capture_dir, env)
        assert_ok(first_start.returncode == 0, f"start failed: {first_start.stderr}")
        listening_runtime = load_json(runtime_file)
        assert_ok(listening_runtime["listening"] is True, f"expected listening=true, got {listening_runtime}")
        assert_ok(listening_runtime["status"] == "listening", f"expected listening status, got {listening_runtime}")

        second_start = run_voice(runtime_voice, "ptt-start", state_file, runtime_file, capture_dir, env)
        assert_ok(second_start.returncode == 4, f"expected already-listening rc=4, got {second_start.returncode}")

        successful_stop = run_voice(runtime_voice, "ptt-stop", state_file, runtime_file, capture_dir, env)
        assert_ok(successful_stop.returncode == 0, f"stop failed: {successful_stop.stderr}")
        stop_payload = json.loads(successful_stop.stdout)
        assert_ok(stop_payload["status"] == "completed", f"unexpected stop payload: {stop_payload}")
        final_runtime = load_json(runtime_file)
        assert_ok(final_runtime["status"] == "idle", f"expected idle after stop, got {final_runtime}")
        assert_ok(final_runtime["last_transcript"] == "hello from endpoint test", f"unexpected transcript: {final_runtime}")
        assert_ok(load_json(request_result)["request_text"] == "hello from endpoint test", "last_request_result mismatch")
        history_lines = [json.loads(line) for line in request_history.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert_ok(history_lines[-1]["request_text"] == "hello from endpoint test", "request_history mismatch")

        unavailable_env = build_env(
            home=home,
            bin_dir=bin_dir,
            request_tool=tools_dir / "missing_runtime_request.py",
            authority_root=authority_root,
            ui_root=ui_root,
            runtime_namespace_root=runtime_namespace_root,
        )
        unavailable_status = run_voice(runtime_voice, "status", state_file, runtime_file, capture_dir, unavailable_env)
        assert_ok(unavailable_status.returncode == 0, f"status with missing request tool failed: {unavailable_status.stderr}")
        unavailable_payload = json.loads(unavailable_status.stdout)
        assert_ok(unavailable_payload["status"] == "unavailable", f"expected unavailable backend: {unavailable_payload}")
        unavailable_start = run_voice(runtime_voice, "ptt-start", state_file, runtime_file, capture_dir, unavailable_env)
        assert_ok(unavailable_start.returncode == 3, f"expected unavailable rc=3, got {unavailable_start.returncode}")

        piper_model = home / "lucy" / "runtime" / "voice" / "models" / "piper" / "test-voice" / "test-voice.onnx"
        piper_model.parent.mkdir(parents=True, exist_ok=True)
        piper_model.write_bytes(b"stub-model")
        aplay_log = root / "aplay_log.json"

        write_executable(
            bin_dir / "piper",
            """
            #!/usr/bin/env python3
            import struct
            import sys
            import wave

            output_path = sys.argv[sys.argv.index("--output_file") + 1]
            with wave.open(output_path, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(22050)
                handle.writeframes(struct.pack("<hhhh", 1200, 900, 600, 300))
            """,
        )
        write_executable(
            bin_dir / "aplay",
            """
            #!/usr/bin/env python3
            import json
            import os
            import sys
            import wave

            wav_path = sys.argv[-1]
            with wave.open(wav_path, "rb") as handle:
                channels = handle.getnchannels()
                sample_width = handle.getsampwidth()
                frame_rate = handle.getframerate()
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

            payload = {
                "channels": channels,
                "frame_count": frame_count,
                "frame_rate": frame_rate,
                "first_nonzero_frame": first_nonzero_frame,
                "sample_width": sample_width,
            }
            with open(os.environ["LUCY_VOICE_APLAY_LOG"], "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
                handle.write("\\n")
            raise SystemExit(0)
            """,
        )

        piper_env = build_env(
            home=home,
            bin_dir=bin_dir,
            request_tool=tools_dir / "runtime_request.py",
            authority_root=authority_root,
            ui_root=ui_root,
            runtime_namespace_root=runtime_namespace_root,
        )
        piper_env["LUCY_VOICE_PIPER_MODEL"] = str(piper_model)
        piper_env["LUCY_VOICE_PIPER_PREPAD_MS"] = "160"
        piper_env["LUCY_VOICE_APLAY_LOG"] = str(aplay_log)

        piper_start = run_voice(runtime_voice, "ptt-start", state_file, runtime_file, capture_dir, piper_env)
        assert_ok(piper_start.returncode == 0, f"piper start failed: {piper_start.stderr}")
        piper_runtime = load_json(runtime_file)
        assert_ok(piper_runtime["tts"] == "none", f"ptt-start should defer tts detection, got {piper_runtime}")
        assert_ok(piper_runtime["tts_device"] == "none", f"ptt-start should defer tts device detection, got {piper_runtime}")
        piper_stop = run_voice(runtime_voice, "ptt-stop", state_file, runtime_file, capture_dir, piper_env)
        assert_ok(piper_stop.returncode == 0, f"piper stop failed: {piper_stop.stderr}")
        piper_stop_payload = json.loads(piper_stop.stdout)
        assert_ok(piper_stop_payload["tts_status"] == "completed", f"unexpected piper tts status: {piper_stop_payload}")
        piper_runtime_after_stop = load_json(runtime_file)
        assert_ok(piper_runtime_after_stop["tts"] == "piper", f"expected piper runtime engine after stop, got {piper_runtime_after_stop}")
        assert_ok(piper_runtime_after_stop["tts_device"] == "cpu", f"expected cpu tts device after stop, got {piper_runtime_after_stop}")
        playback_log = load_json(aplay_log)
        assert_ok(playback_log["frame_rate"] == 22050, f"unexpected playback frame rate: {playback_log}")
        assert_ok(
            int(playback_log["first_nonzero_frame"]) >= 3528,
            f"expected leading silence before piper speech, got {playback_log}",
        )

        original_home = os.environ.get("HOME")
        original_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE")
        original_pause_override = os.environ.get("LUCY_VOICE_TTS_CHUNK_PAUSE_MS")
        try:
            os.environ["HOME"] = str(home)
            os.environ["LUCY_RUNTIME_STATE_FILE"] = str(state_file)
            os.environ.pop("LUCY_VOICE_TTS_CHUNK_PAUSE_MS", None)
            runtime_voice_module = load_runtime_voice_module(runtime_voice)
            assert_ok(
                runtime_voice_module.resolve_tts_chunk_pause_ms() == 56,
                "runtime voice should default to the authoritative state pause when env override is absent",
            )
        finally:
            if original_home is None:
                os.environ.pop("HOME", None)
            else:
                os.environ["HOME"] = original_home
            if original_state_file is None:
                os.environ.pop("LUCY_RUNTIME_STATE_FILE", None)
            else:
                os.environ["LUCY_RUNTIME_STATE_FILE"] = original_state_file
            if original_pause_override is None:
                os.environ.pop("LUCY_VOICE_TTS_CHUNK_PAUSE_MS", None)
            else:
                os.environ["LUCY_VOICE_TTS_CHUNK_PAUSE_MS"] = original_pause_override
        spoken_text = runtime_voice_module.sanitize_tts_text(
            textwrap.dedent(
                """
                From current sources:
                Latest items extracted from allowlisted sources as of 2026-03-21T17:30:33Z.
                Key items:
                - [timesofisrael.com] (Sat, 21 Mar 2026 16:30:18 +0000): US said to strike Iran's Natanz enrichment site, IDF hits missile production sites
                - [jpost.com] (Sat, 21 Mar 2026 18:16:10 GMT): Israel's Mossad calls on Iranians to share information on Islamic Republic's nuclear industry
                Sources:
                - timesofisrael.com
                - jpost.com
                """
            ).strip()
        )
        assert_ok("2026-03-21T17:30:33Z" not in spoken_text, f"iso timestamp leaked into spoken text: {spoken_text}")
        assert_ok("Sat, 21 Mar 2026 16:30:18 +0000" not in spoken_text, f"article timestamp leaked into spoken text: {spoken_text}")
        assert_ok("18:16:10 GMT" not in spoken_text, f"clock time leaked into spoken text: {spoken_text}")
        assert_ok("From current sources" not in spoken_text, f"evidence header leaked into spoken text: {spoken_text}")
        assert_ok("Key items" not in spoken_text, f"evidence section label leaked into spoken text: {spoken_text}")
        assert_ok("Sources" not in spoken_text, f"sources label leaked into spoken text: {spoken_text}")
        assert_ok("timesofisrael.com:" not in spoken_text, f"source domain label leaked into spoken text: {spoken_text}")
        assert_ok("jpost.com:" not in spoken_text, f"source domain label leaked into spoken text: {spoken_text}")
        assert_ok("US said to strike Iran's Natanz enrichment site" in spoken_text, f"expected article content missing: {spoken_text}")
        assert_ok("Israel's Mossad calls on Iranians to share information" in spoken_text, f"expected second article content missing: {spoken_text}")
        assert_ok(
            "sites..." in spoken_text,
            f"spoken news items should use the longer separator pause for TTS: {spoken_text}",
        )
        chunks = runtime_voice_module.split_tts_chunks(spoken_text)
        assert_ok(
            chunks == [spoken_text],
            f"short multi-item news payloads should stay in one TTS chunk to avoid synth gaps: {chunks}",
        )
        assert_ok(
            chunks[0].count("\n") == 1,
            f"aggregated news chunk should preserve line boundaries between items: {chunks}",
        )
        prose_chunks = runtime_voice_module.split_tts_chunks(
            "First sentence is complete. Second sentence is also complete."
        )
        assert_ok(
            prose_chunks == ["First sentence is complete. Second sentence is also complete."],
            f"ordinary prose should stay in a single tts chunk to avoid synth gaps: {prose_chunks}",
        )
        longer_prose = (
            "First sentence is complete and introduces the answer clearly. "
            "Second sentence adds more detail without changing the topic. "
            "Third sentence closes the paragraph in a natural speaking cadence."
        )
        longer_chunks = runtime_voice_module.split_tts_chunks(longer_prose)
        assert_ok(
            longer_chunks == [longer_prose],
            f"regular paragraphs should stay in one TTS chunk when they fit the prose cap: {longer_chunks}",
        )
        assert_ok(
            runtime_voice_module.resolve_kokoro_prepad_ms() > runtime_voice_module.resolve_piper_prepad_ms(),
            "kokoro should keep a slightly larger startup prepad than piper to avoid clipping first phonemes",
        )
        assert_ok(
            runtime_voice_module.resolve_kokoro_first_chunk_prepad_ms() > runtime_voice_module.resolve_kokoro_prepad_ms(),
            "kokoro first chunk should keep a slightly larger startup prepad than later chunks",
        )
        assert_ok(
            runtime_voice_module.resolve_kokoro_first_chunk_player_prime_ms() > 0,
            "kokoro first chunk should prime the player to avoid clipping after idle wakeup",
        )
        long_news_items = "\n".join(
            [
                "Gunfire heard near Israeli consulate in Istanbul...",
                "Middle East crisis live: Trump says he is not at all worried about possible war crimes as his deadline for Iran nears...",
                "Weizmann Institute helps map Moon's shadowy sources of ice...",
                "Ten killed in Israeli strikes and clashes between Hamas and militia in Gaza, local sources say...",
                "WATCH: IDF kills Hezbollah anti-tank terrorists operating from southern Lebanon mosque...",
                "WATCH: IDF strikes Shiraz petrochemical site, releases footage of attacks on Iranian air defenses...",
                "Schools set to partially reopen Sunday, subject to IDF guidelines...",
                "Mojtaba Khamenei unconscious in Qom, not actually running Iran - report...",
                "US shouldn't negotiate with Iran until it realizes how badly it's losing - editorial...",
                "UN expected to vote on watered-down Hormuz resolution that omits military action...",
            ]
        )
        long_news_chunks = runtime_voice_module.split_tts_chunks(long_news_items)
        assert_ok(
            long_news_chunks == [long_news_items],
            f"multiline headline lists should stay in one chunk when they fit the larger news cap: {long_news_chunks}",
        )
        original_max_chars = os.environ.get("LUCY_VOICE_TTS_MAX_CHARS")
        try:
            os.environ["LUCY_VOICE_TTS_MAX_CHARS"] = "120"
            truncated_text = runtime_voice_module.sanitize_tts_text(
                "First sentence is complete. Second sentence is also complete. "
                "Add the chopped tomatoes and bring to a simmer before covering the pan."
            )
        finally:
            if original_max_chars is None:
                os.environ.pop("LUCY_VOICE_TTS_MAX_CHARS", None)
            else:
                os.environ["LUCY_VOICE_TTS_MAX_CHARS"] = original_max_chars
        assert_ok(
            truncated_text == "First sentence is complete. Second sentence is also complete.",
            f"TTS truncation should stop on the last full spoken chunk, got: {truncated_text!r}",
        )

        print("RUNTIME_VOICE_ENDPOINT_OK")
        return 0


def build_env(
    *,
    home: Path,
    bin_dir: Path,
    request_tool: Path,
    authority_root: Path,
    ui_root: Path,
    runtime_namespace_root: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
    env["LUCY_RUNTIME_AUTHORITY_ROOT"] = str(authority_root)
    env["LUCY_UI_ROOT"] = str(ui_root)
    env["LUCY_RUNTIME_NAMESPACE_ROOT"] = str(runtime_namespace_root)
    env["LUCY_RUNTIME_CONTRACT_REQUIRED"] = "1"
    env["LUCY_RUNTIME_REQUEST_TOOL"] = str(request_tool)
    return env


def load_runtime_voice_module(runtime_voice: Path):
    spec = importlib.util.spec_from_file_location("runtime_voice_test_module", runtime_voice)
    assert_ok(spec is not None and spec.loader is not None, f"unable to load module spec for {runtime_voice}")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(runtime_voice.parent))
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def run_control(control_tool: Path, state_file: Path, command: str, value: str, env: dict[str, str]) -> None:
    completed = subprocess.run(
        [
            "python3",
            str(control_tool),
            "--state-file",
            str(state_file),
            command,
            "--value",
            value,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert_ok(completed.returncode == 0, f"runtime_control failed: {completed.stderr or completed.stdout}")


def run_voice(
    runtime_voice: Path,
    command: str,
    state_file: Path,
    runtime_file: Path,
    capture_dir: Path,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "python3",
            str(runtime_voice),
            "--state-file",
            str(state_file),
            "--runtime-file",
            str(runtime_file),
            "--capture-dir",
            str(capture_dir),
            command,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def assert_ok(condition: bool, message: str) -> None:
    if condition:
        return
    print(f"ASSERTION FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
    raise SystemExit(main())
