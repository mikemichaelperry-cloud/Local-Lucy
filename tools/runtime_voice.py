#!/usr/bin/env python3
from __future__ import annotations

import argparse
import audioop
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime_control import (
    RuntimeControlError,
    enforce_authority_contract,
    iso_now,
    load_or_create_state,
    locked_state_file,
    resolve_state_file,
)
from voice.playback import PlaybackError, detect_audio_player, play_wav_file

try:
    from voice.playback_with_levels import play_wav_file_with_levels
except ImportError:
    play_wav_file_with_levels = None

try:
    from voice.whisper_worker import (
        ensure_whisper_worker,
        transcribe_with_worker,
        WhisperWorkerError,
    )
except ImportError:
    ensure_whisper_worker = None  # type: ignore[assignment]
    transcribe_with_worker = None  # type: ignore[assignment]
    WhisperWorkerError = RuntimeError  # type: ignore[misc,assignment]

# Python Voice Tool integration (V8)
# Import voice_tool for optional Python-native voice pipeline
_VOICE_TOOL_AVAILABLE = False
_voice_tool_module = None

try:
    # Add router_py to path if needed
    router_py_path = Path(__file__).resolve().parent / "router_py"
    if str(router_py_path) not in sys.path:
        sys.path.insert(0, str(router_py_path.parent))
    
    from router_py.voice_tool import VoicePipeline, VoiceResult, VADConfig
    _VOICE_TOOL_AVAILABLE = True
except ImportError:
    _VOICE_TOOL_AVAILABLE = False


def use_python_voice() -> bool:
    """Check if Python voice pipeline should be used."""
    return os.environ.get("LUCY_VOICE_PY", "0") == "1" and _VOICE_TOOL_AVAILABLE


PTT_START_DISABLED = 2
PTT_START_UNAVAILABLE = 3
PTT_START_ALREADY_LISTENING = 4
PTT_START_BUSY = 5
PTT_START_FAILED = 6
PTT_STOP_NOT_LISTENING = 7
PTT_STOP_CAPTURE_FAILED = 8
PTT_STOP_TRANSCRIBE_FAILED = 9
PTT_STOP_REQUEST_FAILED = 10
AUTHORITY_ROOT_ENV = "LUCY_RUNTIME_AUTHORITY_ROOT"


class RuntimeVoiceError(RuntimeError):
    pass


class RuntimeVoiceExit(RuntimeVoiceError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


@dataclass(frozen=True)
class VoiceBackend:
    available: bool
    recorder_engine: str
    recorder_bin: str
    stt_engine: str
    stt_bin: str
    tts_engine: str
    tts_bin: str
    tts_device: str
    audio_player: str
    reason: str


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    backend: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""


# Keywords that indicate a GPU/CUDA failure requiring CPU fallback
_GPU_ERROR_KEYWORDS = ("cuda", "cublas", "gpu", "out of memory", "oom")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    
    
    enforce_authority_contract(expected_authority_root=Path(__file__).resolve().parents[1])

    runtime_file = resolve_voice_runtime_file(args.runtime_file)
    capture_dir = resolve_capture_directory(args.capture_dir)
    state_file = resolve_state_file(args.state_file)

    try:
        if args.command == "status":
            # Use Python voice tool for status when enabled
            if use_python_voice():
                payload = handle_status_python()
            else:
                payload = sync_voice_runtime(runtime_file, state_file)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "ptt-start":
            # Use Python voice pipeline when enabled
            if use_python_voice():
                payload = handle_ptt_start_python(runtime_file, state_file, capture_dir)
            else:
                payload = handle_ptt_start(runtime_file, state_file, capture_dir)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "ptt-stop":
            # Use Python voice pipeline when enabled
            if use_python_voice():
                payload = handle_ptt_stop_python(runtime_file, state_file, capture_dir)
            else:
                payload = handle_ptt_stop(runtime_file, state_file, capture_dir)
            print(json.dumps(payload, sort_keys=True))
            return 0
        if args.command == "internal-record":
            return run_internal_recorder(Path(args.output).expanduser(), Path(args.runtime_file).expanduser())
        if args.command == "internal-prewarm-tts":
            # Internal command: prewarm TTS worker to reduce latency
            backend = detect_backend()
            if backend.tts_engine == "kokoro":
                success = prewarm_kokoro_worker()
                print(json.dumps({"ok": success, "engine": "kokoro", "prewarmed": success}, sort_keys=True))
            else:
                print(json.dumps({"ok": False, "engine": backend.tts_engine or "none", "prewarmed": False}, sort_keys=True))
            return 0
        if args.command == "speak":
            backend = detect_backend()
            tts_status = speak_response(backend, args.text)
            ok = tts_status == "completed"
            print(json.dumps({"ok": ok, "tts_status": tts_status}, sort_keys=True))
            return 0 if ok else 1
        raise RuntimeVoiceError(f"unsupported command: {args.command}")
    except RuntimeVoiceExit as exc:
        print(f"ERROR: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except RuntimeVoiceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except RuntimeControlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authoritative Local Lucy voice PTT runtime endpoint.")
    parser.add_argument(
        "--state-file",
        help="Override the authoritative runtime control state file path.",
    )
    parser.add_argument(
        "--runtime-file",
        help="Override the authoritative voice runtime state file path.",
    )
    parser.add_argument(
        "--capture-dir",
        help="Override the voice capture directory path.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("ptt-start")
    subparsers.add_parser("ptt-stop")
    internal_record = subparsers.add_parser("internal-record")
    internal_record.add_argument("--output", required=True)
    internal_record.add_argument("--runtime-file", required=True)
    internal_prewarm = subparsers.add_parser("internal-prewarm-tts")
    internal_prewarm.help = "Internal: prewarm TTS worker to reduce latency (auto-called by HMI)"
    speak_parser = subparsers.add_parser("speak")
    speak_parser.add_argument("--text", required=True, help="Text to synthesize and speak")
    return parser


def resolve_root() -> Path:
    env_root = os.environ.get(AUTHORITY_ROOT_ENV)
    if env_root:
        return Path(env_root).expanduser().resolve()
    return Path(__file__).resolve().parents[1]


def resolve_voice_runtime_file(explicit_path: str | None) -> Path:
    raw = explicit_path or os.environ.get("LUCY_VOICE_RUNTIME_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "state" / "voice_runtime.json"


def resolve_capture_directory(explicit_path: str | None) -> Path:
    raw = explicit_path or os.environ.get("LUCY_VOICE_CAPTURE_DIR")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "voice" / "ui_ptt"


def default_runtime_namespace_root() -> Path:
    explicit_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser()
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


DEFAULT_VOICE_RUNTIME_FILE = str(default_runtime_namespace_root() / "state" / "voice_runtime.json")
DEFAULT_CAPTURE_DIR = str(default_runtime_namespace_root() / "voice" / "ui_ptt")


def resolve_request_tool() -> Path:
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_TOOL") or str(resolve_root() / "tools" / "runtime_request.py")
    return Path(raw).expanduser()


def resolve_tts_adapter_tool() -> Path:
    return resolve_root() / "tools" / "voice" / "tts_adapter.py"


def resolve_kokoro_worker_tool() -> Path:
    return resolve_root() / "tools" / "voice" / "kokoro_session_worker.py"


def resolve_kokoro_worker_socket() -> Path:
    return resolve_root() / "tmp" / "run" / "kokoro_tts_worker.sock"


def resolve_kokoro_worker_pid_file() -> Path:
    return resolve_root() / "tmp" / "run" / "kokoro_tts_worker.pid"


def resolve_kokoro_worker_log_file() -> Path:
    return resolve_root() / "tmp" / "logs" / "kokoro_tts_worker.log"


def resolve_voice_python(requested_engine: str | None = None) -> str:
    root = resolve_root()
    workspace_root = root if root.name == "lucy-v8" else root.parent.parent
    preferred_engine = clean_text(requested_engine).lower()
    if preferred_engine in {"", "auto"}:
        preferred_engine = "kokoro"

    adapter_tool = resolve_tts_adapter_tool()
    explicit = clean_text(os.environ.get("LUCY_VOICE_PYTHON_BIN"))
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.exists() and os.access(explicit_path, os.X_OK):
            if preferred_engine in {"kokoro", "piper"} and adapter_tool.exists():
                payload = run_tts_adapter_command(
                    python_bin=str(explicit_path),
                    command="probe",
                    requested_engine=preferred_engine,
                )
                if payload.get("ok") and clean_text(payload.get("engine")) == preferred_engine:
                    return str(explicit_path)
            else:
                return str(explicit_path)

    # ISOLATION: V8 only uses ui-v8, NEVER falls back to ui-v7
    candidate = workspace_root / "ui-v8" / ".venv" / "bin" / "python3"
    if candidate.exists() and os.access(candidate, os.X_OK):
        if preferred_engine in {"kokoro", "piper"} and adapter_tool.exists():
            payload = run_tts_adapter_command(
                python_bin=str(candidate),
                command="probe",
                requested_engine=preferred_engine,
            )
            if payload.get("ok") and clean_text(payload.get("engine")) == preferred_engine:
                return str(candidate)
        return str(candidate)

    last_error = ""
    for fallback in (Path(sys.executable), Path("/usr/bin/python3")):
        if fallback.exists() and os.access(fallback, os.X_OK):
            if preferred_engine in {"kokoro", "piper"} and adapter_tool.exists():
                payload = run_tts_adapter_command(
                    python_bin=str(fallback),
                    command="probe",
                    requested_engine=preferred_engine,
                )
                if payload.get("ok") and clean_text(payload.get("engine")) == preferred_engine:
                    return str(fallback)
                last_error = clean_text(payload.get("error"))
                continue
            return str(fallback)

    raise RuntimeError(
        f"V8 voice Python for {preferred_engine} not available at {candidate}"
        + (f": {last_error}" if last_error else "")
    )


def read_pid_file(path: Path) -> int | None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return parse_pid(raw)


def remove_stale_kokoro_worker_files() -> None:
    for path in (resolve_kokoro_worker_socket(), resolve_kokoro_worker_pid_file()):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass


def ensure_kokoro_worker() -> bool:
    worker_tool = resolve_kokoro_worker_tool()
    if not worker_tool.exists():
        return False
    socket_path = resolve_kokoro_worker_socket()
    pid_file = resolve_kokoro_worker_pid_file()
    worker_pid = read_pid_file(pid_file)
    if worker_pid is not None and socket_path.exists() and is_process_running(worker_pid):
        return True

    remove_stale_kokoro_worker_files()
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    resolve_kokoro_worker_log_file().parent.mkdir(parents=True, exist_ok=True)
    voice_python = resolve_voice_python("kokoro")
    log_handle = resolve_kokoro_worker_log_file().open("a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [voice_python, str(worker_tool), "serve", "--socket", str(socket_path)],
            stdin=subprocess.DEVNULL,
            stdout=log_handle,
            stderr=log_handle,
            shell=False,
            start_new_session=True,
            env=os.environ.copy(),
        )
    finally:
        log_handle.close()
    pid_file.write_text(f"{proc.pid}\n", encoding="utf-8")
    for _ in range(40):
        if socket_path.exists():
            return True
        time.sleep(0.05)
    return socket_path.exists()


def kokoro_worker_request(payload: dict[str, Any], *, timeout_seconds: float = 120.0) -> dict[str, Any]:
    socket_path = resolve_kokoro_worker_socket()
    if not socket_path.exists():
        return {"ok": False, "error": "kokoro worker unavailable"}
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect(str(socket_path))
        client.sendall((json.dumps(payload, sort_keys=True) + "\n").encode("utf-8"))
        raw = b""
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            raw += chunk
            if b"\n" in raw:
                break
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        client.close()
    line = raw.decode("utf-8", errors="replace").strip()
    parsed = parse_json_payload(line)
    return parsed if parsed is not None else {"ok": False, "error": line or "kokoro worker invalid response"}


def prewarm_kokoro_worker() -> bool:
    if not ensure_kokoro_worker():
        return False
    payload = kokoro_worker_request({"cmd": "prewarm", "engine": "kokoro"}, timeout_seconds=30.0)
    return bool(payload.get("ok"))


def default_voice_runtime() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "available": False,
        "listening": False,
        "processing": False,
        "status": "unavailable",
        "last_error": "",
        "last_updated": iso_now(),
        "recorder": "unavailable",
        "stt": "unavailable",
        "stt_backend": "",
        "stt_fallback_reason": "",
        "tts": "none",
        "tts_device": "none",
        "audio_player": "none",
        "record_pid": None,
        "processing_pid": None,
        "capture_path": "",
        "last_transcript": "",
        "last_request_id": "",
    }


def normalize_voice_runtime(payload: dict[str, Any] | None) -> dict[str, Any]:
    state = default_voice_runtime()
    if isinstance(payload, dict):
        for key, value in payload.items():
            state[key] = value
    state["schema_version"] = 1
    state["available"] = bool(state.get("available", False))
    state["listening"] = bool(state.get("listening", False))
    state["processing"] = bool(state.get("processing", False))
    state["status"] = clean_text(state.get("status")) or "unavailable"
    state["last_error"] = clean_text(state.get("last_error"))
    state["last_updated"] = clean_text(state.get("last_updated")) or iso_now()
    state["recorder"] = clean_text(state.get("recorder")) or "unavailable"
    state["stt"] = clean_text(state.get("stt")) or "unavailable"
    state["stt_backend"] = clean_text(state.get("stt_backend"))
    state["stt_fallback_reason"] = clean_text(state.get("stt_fallback_reason"))
    state["tts"] = clean_text(state.get("tts")) or "none"
    state["tts_device"] = clean_text(state.get("tts_device")) or "none"
    state["audio_player"] = clean_text(state.get("audio_player")) or "none"
    state["record_pid"] = parse_pid(state.get("record_pid"))
    state["processing_pid"] = parse_pid(state.get("processing_pid"))
    state["capture_path"] = clean_text(state.get("capture_path"))
    state["last_transcript"] = clean_text(state.get("last_transcript"))
    state["last_request_id"] = clean_text(state.get("last_request_id"))
    return state


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_pid(value: Any) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        pid = int(value)
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def read_voice_runtime(runtime_file: Path) -> dict[str, Any] | None:
    if not runtime_file.exists():
        return None
    try:
        payload = json.loads(runtime_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeVoiceError(f"unable to read voice runtime file {runtime_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeVoiceError(f"voice runtime file must contain a JSON object: {runtime_file}")
    return payload


def write_voice_runtime(runtime_file: Path, state: dict[str, Any]) -> None:
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=runtime_file.parent,
            delete=False,
            prefix=".voice_runtime.",
            suffix=".tmp",
        ) as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, runtime_file)
    except OSError as exc:
        raise RuntimeVoiceError(f"unable to write voice runtime file {runtime_file}: {exc}") from exc


def load_voice_runtime_locked(runtime_file: Path) -> dict[str, Any]:
    return normalize_voice_runtime(read_voice_runtime(runtime_file))


def detect_backend(
    *,
    include_tts: bool = True,
    tts_engine_hint: str = "",
    tts_device_hint: str = "",
) -> VoiceBackend:
    recorder_engine, recorder_bin = detect_recorder()
    stt_engine, stt_bin = detect_stt()
    if include_tts:
        tts_engine, tts_bin, tts_device, audio_player = detect_tts()
    else:
        tts_engine = clean_text(tts_engine_hint) or "none"
        tts_bin = tts_engine if tts_engine in {"piper", "kokoro"} else ""
        tts_device = clean_text(tts_device_hint) or ("cpu" if tts_engine == "piper" else "none")
        audio_player = detect_audio_player() or "none"
    request_tool = resolve_request_tool()
    missing: list[str] = []
    if not recorder_bin:
        missing.append("recorder")
    if not stt_bin:
        missing.append("stt")
    if not request_tool.exists():
        missing.append(f"request tool {request_tool}")

    available = not missing
    reason = "ready" if available else f"missing {'; '.join(missing)}"
    return VoiceBackend(
        available=available,
        recorder_engine=recorder_engine or "unavailable",
        recorder_bin=recorder_bin or "",
        stt_engine=stt_engine or "unavailable",
        stt_bin=stt_bin or "",
        tts_engine=tts_engine or "none",
        tts_bin=tts_bin or "",
        tts_device=tts_device or "none",
        audio_player=audio_player or "none",
        reason=reason,
    )


def detect_recorder() -> tuple[str, str]:
    arecord_bin = shutil.which("arecord")
    if arecord_bin:
        return "arecord", arecord_bin
    pw_record_bin = shutil.which("pw-record")
    if pw_record_bin:
        return "pw-record", pw_record_bin
    return "", ""


def detect_stt() -> tuple[str, str]:
    _voice_logger.debug("Detecting STT engine...")
    root = resolve_root()
    whisper_bin = clean_text(os.environ.get("LUCY_VOICE_WHISPER_BIN"))
    if whisper_bin:
        whisper_path = Path(whisper_bin).expanduser()
        if whisper_path.exists():
            return "whisper", str(whisper_path)
    for candidate in (
        bundled_whisper_binary(root),
        Path(shutil.which("whisper") or ""),
        Path(shutil.which("whisper-cli") or ""),
        Path(shutil.which("whisper-cpp") or ""),
    ):
        if not str(candidate) or not candidate.exists():
            continue
        if candidate == bundled_whisper_binary(root) and not bundled_whisper_runtime_ready(root):
            continue
        _voice_logger.info(f"STT engine selected: whisper ({candidate})")
        return "whisper", str(candidate)

    vosk_bin = clean_text(os.environ.get("LUCY_VOICE_VOSK_BIN"))
    if vosk_bin:
        vosk_path = Path(vosk_bin).expanduser()
        if vosk_path.exists():
            _voice_logger.info(f"STT engine selected: vosk (env: {vosk_path})")
            return "vosk", str(vosk_path)
    system_vosk = shutil.which("vosk-transcriber")
    if system_vosk:
        _voice_logger.info(f"STT engine selected: vosk (system)")
        return "vosk", system_vosk
    _voice_logger.info("STT engine selected: none (unavailable)")
    return "", ""


def bundled_whisper_binary(root: Path) -> Path:
    return root / "runtime" / "voice" / "bin" / "whisper"


def bundled_whisper_library_dirs(root: Path) -> list[Path]:
    return [
        root / "runtime" / "voice" / "whisper.cpp" / "build" / "src",
        root / "runtime" / "voice" / "whisper.cpp" / "build" / "ggml" / "src",
    ]


def bundled_whisper_runtime_ready(root: Path) -> bool:
    whisper_bin = bundled_whisper_binary(root)
    if not whisper_bin.exists():
        return False
    return all(path.is_dir() for path in bundled_whisper_library_dirs(root))


def whisper_command_env(stt_bin: str) -> dict[str, str]:
    env = os.environ.copy()
    root = resolve_root()
    bundled = bundled_whisper_binary(root)
    try:
        is_bundled = Path(stt_bin).expanduser().resolve() == bundled.resolve()
    except OSError:
        is_bundled = False
    if not is_bundled:
        return env

    library_dirs = [str(path) for path in bundled_whisper_library_dirs(root) if path.is_dir()]
    if not library_dirs:
        return env
    existing = clean_text(env.get("LD_LIBRARY_PATH"))
    env["LD_LIBRARY_PATH"] = ":".join(library_dirs + ([existing] if existing else []))
    return env


def detect_tts() -> tuple[str, str, str, str]:
    requested_engine = clean_text(os.environ.get("LUCY_VOICE_TTS_ENGINE")) or "auto"
    _voice_logger.debug(f"Detecting TTS engine (requested: {requested_engine})...")
    try:
        voice_python = resolve_voice_python(requested_engine)
    except RuntimeError as exc:
        _voice_logger.info(f"TTS engine selected: none ({exc})")
        return "none", "", "none", "none"
    payload = run_tts_adapter_command(
        python_bin=voice_python,
        command="probe",
        requested_engine=requested_engine,
    )
    engine = clean_text(payload.get("engine")) if payload.get("ok") else "none"
    if engine not in {"piper", "kokoro"}:
        _voice_logger.info(f"TTS engine selected: none (requested: {requested_engine}, probe failed)")
        return "none", "", "none", "none"
    device = clean_text(payload.get("device")) or ("cpu" if engine == "piper" else "unknown")
    player = detect_audio_player() or "none"
    _voice_logger.info(f"TTS engine selected: {engine} (device: {device}, player: {player})")
    return engine, engine, device, player


def sync_voice_runtime(runtime_file: Path, state_file: Path) -> dict[str, Any]:
    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        runtime_state = load_voice_runtime_locked(runtime_file)
        backend = detect_backend()
        synced_state = synchronize_state(runtime_state, backend, current_state)
        if synced_state != runtime_state:
            write_voice_runtime(runtime_file, synced_state)
        return synced_state


def synchronize_state(
    runtime_state: dict[str, Any],
    backend: VoiceBackend,
    current_state: dict[str, Any],
) -> dict[str, Any]:
    state = dict(runtime_state)
    prior_status = clean_text(state.get("status"))

    record_pid = parse_pid(state.get("record_pid"))
    if state.get("listening") and (record_pid is None or not is_process_running(record_pid)):
        state["listening"] = False
        state["record_pid"] = None
        if prior_status == "listening":
            state["last_error"] = "voice recorder exited unexpectedly"

    processing_pid = parse_pid(state.get("processing_pid"))
    if state.get("processing") and (processing_pid is None or not is_process_running(processing_pid)):
        state["processing"] = False
        state["processing_pid"] = None
        if prior_status == "processing":
            state["last_error"] = "voice processing reset after worker exit"

    state["available"] = backend.available
    state["recorder"] = backend.recorder_engine
    state["stt"] = backend.stt_engine
    state["tts"] = backend.tts_engine
    state["tts_device"] = backend.tts_device
    state["audio_player"] = backend.audio_player
    state["last_updated"] = iso_now()

    voice_enabled = clean_text(current_state.get("voice")).lower() == "on"
    if state.get("processing"):
        status = "processing"
    elif state.get("listening"):
        status = "listening"
    elif not voice_enabled:
        status = "disabled"
    elif not backend.available:
        status = "unavailable"
        if not state.get("last_error"):
            state["last_error"] = backend.reason
    elif state.get("last_error") and prior_status == "fault":
        status = "fault"
    else:
        status = "idle"
    state["status"] = status
    return normalize_voice_runtime(state)


def is_process_running(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def handle_ptt_start(runtime_file: Path, state_file: Path, capture_dir: Path) -> dict[str, Any]:
    capture_dir.mkdir(parents=True, exist_ok=True)
    should_prewarm_kokoro = False
    result_state: dict[str, Any] | None = None

    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        existing_runtime_state = load_voice_runtime_locked(runtime_file)
        backend = detect_backend(
            include_tts=False,
            tts_engine_hint=clean_text(existing_runtime_state.get("tts")),
            tts_device_hint=clean_text(existing_runtime_state.get("tts_device")),
        )
        runtime_state = synchronize_state(existing_runtime_state, backend, current_state)
        voice_enabled = clean_text(current_state.get("voice")).lower() == "on"

        if not voice_enabled:
            runtime_state["status"] = "disabled"
            runtime_state["last_error"] = "voice disabled"
            runtime_state["last_updated"] = iso_now()
            write_voice_runtime(runtime_file, runtime_state)
            raise_with_state("voice disabled", PTT_START_DISABLED)
        if not backend.available:
            runtime_state["status"] = "unavailable"
            runtime_state["last_error"] = backend.reason
            runtime_state["last_updated"] = iso_now()
            write_voice_runtime(runtime_file, runtime_state)
            raise_with_state(backend.reason, PTT_START_UNAVAILABLE)
        if runtime_state.get("listening"):
            raise_with_state("voice already listening", PTT_START_ALREADY_LISTENING)
        if runtime_state.get("processing"):
            raise_with_state("voice busy processing", PTT_START_BUSY)

        capture_path = capture_dir / f"ptt_{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}.wav"
        recorder = start_recorder(backend, capture_path, runtime_file)
        runtime_state.update(
            {
                "available": backend.available,
                "listening": True,
                "processing": False,
                "status": "listening",
                "last_error": "",
                "last_updated": iso_now(),
                "record_pid": recorder.pid,
                "processing_pid": None,
                "capture_path": str(capture_path),
                "last_transcript": "",
                "recorder": backend.recorder_engine,
                "stt": backend.stt_engine,
                "tts": backend.tts_engine,
                "tts_device": backend.tts_device,
                "audio_player": backend.audio_player,
            }
        )
        write_voice_runtime(runtime_file, runtime_state)
        should_prewarm_kokoro = clean_text(current_state.get("voice")).lower() == "on"
        result_state = dict(runtime_state)

    if should_prewarm_kokoro:
        tts_engine, _, _, _ = detect_tts()
        if tts_engine == "kokoro":
            prewarm_kokoro_worker()

    # Pre-warm whisper worker for fast STT (GPU stays loaded)
    if ensure_whisper_worker is not None:
        try:
            backend = detect_backend()
            if backend.stt_engine == "whisper" and backend.available:
                model_path = resolve_whisper_model_path()
                ensure_whisper_worker(model_path, use_gpu=True)
        except Exception:
            pass  # Non-fatal: fallback to whisper-cli remains available

    return normalize_voice_runtime(result_state or {})


def handle_ptt_stop(runtime_file: Path, state_file: Path, capture_dir: Path) -> dict[str, Any]:
    backend = detect_backend()
    capture_path = Path()
    record_pid: int | None = None

    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        runtime_state = synchronize_state(load_voice_runtime_locked(runtime_file), backend, current_state)
        if not runtime_state.get("listening"):
            raise_with_state("voice not listening", PTT_STOP_NOT_LISTENING)
        record_pid = parse_pid(runtime_state.get("record_pid"))
        capture_path = Path(clean_text(runtime_state.get("capture_path"))).expanduser()
        runtime_state.update(
            {
                "listening": False,
                "processing": True,
                "status": "processing",
                "last_error": "",
                "last_updated": iso_now(),
                "record_pid": None,
                "processing_pid": os.getpid(),
            }
        )
        write_voice_runtime(runtime_file, runtime_state)

    try:
        stop_recorder(record_pid)
        if not capture_path.exists() or capture_path.stat().st_size == 0:
            finalize_voice_state(
                runtime_file,
                state_file,
                backend,
                status="idle",
                last_error="",
                last_transcript="",
                last_request_id="",
                stt_backend="",
                stt_fallback_reason="",
            )
            return build_turn_payload("no_transcript", "", None, "no audio captured")

        tx_result = transcribe_capture(backend, capture_path)
        if not tx_result.text:
            finalize_voice_state(
                runtime_file,
                state_file,
                backend,
                status="idle",
                last_error="",
                last_transcript="",
                last_request_id="",
                stt_backend=tx_result.backend,
                stt_fallback_reason=tx_result.fallback_reason,
            )
            return build_turn_payload("no_transcript", "", None, "no transcript")

        # Voice is an input modality only. Return transcript to UI;
        # UI submits through normal text pipeline (memory, routing, evidence,
        # augmented, telemetry all preserved).
        finalize_voice_state(
            runtime_file,
            state_file,
            backend,
            status="idle",
            last_error="",
            last_transcript=tx_result.text,
            last_request_id="",
            stt_backend=tx_result.backend,
            stt_fallback_reason=tx_result.fallback_reason,
        )
        return build_turn_payload("completed", tx_result.text, None, "")
    except RuntimeVoiceExit as exc:
        finalize_voice_state(
            runtime_file,
            state_file,
            backend,
            status="fault",
            last_error=exc.message,
            last_transcript="",
            last_request_id="",
            stt_backend="",
            stt_fallback_reason="",
        )
        raise
    except RuntimeVoiceError as exc:
        finalize_voice_state(
            runtime_file,
            state_file,
            backend,
            status="fault",
            last_error=str(exc),
            last_transcript="",
            last_request_id="",
            stt_backend="",
            stt_fallback_reason="",
        )
        raise
    finally:
        if capture_path:
            try:
                if capture_path.exists():
                    capture_path.unlink()
            except OSError:
                pass


def finalize_voice_state(
    runtime_file: Path,
    state_file: Path,
    backend: VoiceBackend,
    *,
    status: str,
    last_error: str,
    last_transcript: str,
    last_request_id: str,
    stt_backend: str = "",
    stt_fallback_reason: str = "",
) -> None:
    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        runtime_state = synchronize_state(load_voice_runtime_locked(runtime_file), backend, current_state)
        runtime_state.update(
            {
                "listening": False,
                "processing": False,
                "processing_pid": None,
                "record_pid": None,
                "capture_path": "",
                "last_error": last_error,
                "last_transcript": last_transcript,
                "last_request_id": last_request_id,
                "stt_backend": stt_backend,
                "stt_fallback_reason": stt_fallback_reason,
                "last_updated": iso_now(),
                "status": status,
            }
        )
        if not runtime_state.get("available"):
            runtime_state["status"] = "unavailable"
        elif clean_text(current_state.get("voice")).lower() != "on":
            runtime_state["status"] = "disabled"
        elif last_error and status == "fault":
            runtime_state["status"] = "fault"
        else:
            runtime_state["status"] = "idle"
        write_voice_runtime(runtime_file, normalize_voice_runtime(runtime_state))


def build_turn_payload(
    status: str,
    transcript: str,
    request_payload: dict[str, Any] | None,
    error: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "transcript": transcript,
        "error": error,
    }
    if isinstance(request_payload, dict):
        payload["request"] = request_payload
    return payload


def start_recorder(backend: VoiceBackend, capture_path: Path, runtime_file: Path) -> subprocess.Popen[str]:
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "internal-record",
        "--output",
        str(capture_path),
        "--runtime-file",
        str(runtime_file),
    ]
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise RuntimeVoiceError(f"unable to start {backend.recorder_engine}: {exc}") from exc

    time.sleep(0.12)
    if process.poll() is not None:
        raise_with_state(f"{backend.recorder_engine} exited immediately", PTT_START_FAILED)
    return process


def recorder_command(backend: VoiceBackend, capture_path: Path) -> list[str]:
    if backend.recorder_engine == "arecord":
        return [backend.recorder_bin, "-q", "-f", "S16_LE", "-r", "16000", "-c", "1", str(capture_path)]
    if backend.recorder_engine == "pw-record":
        return [backend.recorder_bin, "--channels", "1", "--rate", "16000", "--format", "s16", str(capture_path)]
    raise RuntimeVoiceError("no recorder available")


def recorder_stream_command() -> list[str]:
    arecord_bin = shutil.which("arecord")
    if arecord_bin:
        return [arecord_bin, "-q", "-t", "raw", "-f", "S16_LE", "-r", "16000", "-c", "1", "-"]
    pw_record_bin = shutil.which("pw-record")
    if pw_record_bin:
        return [pw_record_bin, "--channels", "1", "--rate", "16000", "--format", "s16", "-"]
    raise RuntimeVoiceError("no recorder available")


_INTERNAL_RECORD_STOP = False


def _handle_internal_record_signal(signum: int, frame: Any) -> None:
    del signum, frame
    global _INTERNAL_RECORD_STOP
    _INTERNAL_RECORD_STOP = True


def run_internal_recorder(output_path: Path, runtime_file: Path, max_duration_seconds: int | None = None) -> int:
    if max_duration_seconds is None:
        max_duration_seconds = int(os.environ.get("LUCY_VOICE_PTT_MAX_SECONDS", "60"))
        if max_duration_seconds <= 0:
            max_duration_seconds = 60
    """Record microphone audio while writing input VU levels for the HMI."""
    global _INTERNAL_RECORD_STOP
    _INTERNAL_RECORD_STOP = False
    signal.signal(signal.SIGINT, _handle_internal_record_signal)
    signal.signal(signal.SIGTERM, _handle_internal_record_signal)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    levels_file = audio_levels_file_for_runtime(runtime_file)
    command = recorder_stream_command()
    process: subprocess.Popen[bytes] | None = None

    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        if process.stdout is None:
            raise RuntimeVoiceError("recorder stdout unavailable")

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            prefix=".voice_capture.",
            dir=output_path.parent,
            delete=False,
        ) as tmp:
            tmp_path = Path(tmp.name)

        with wave.open(str(tmp_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            chunk_counter = 0
            recording_start_time = time.monotonic()
            while not _INTERNAL_RECORD_STOP:
                if time.monotonic() - recording_start_time >= max_duration_seconds:
                    print(f"internal recorder stopped after reaching max duration ({max_duration_seconds}s)", file=sys.stderr)
                    break
                chunk = process.stdout.read(2048)
                if not chunk:
                    if process.poll() is not None:
                        break
                    time.sleep(0.01)
                    continue
                wav_file.writeframesraw(chunk)
                chunk_counter += 1
                if chunk_counter % 5 == 0:
                    write_audio_levels(levels_file, input_level=pcm_level(chunk), recording=True)

        os.replace(tmp_path, output_path)
        return 0
    except Exception as exc:
        try:
            write_audio_levels(levels_file, input_level=0, recording=False)
        except Exception:
            pass
        print(f"internal recorder failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1.0)
        write_audio_levels(levels_file, input_level=0, recording=False)


def audio_levels_file_for_runtime(runtime_file: Path | None = None) -> Path:
    if runtime_file is not None:
        return runtime_file.expanduser().parent / "voice_audio_levels.json"
    runtime_root = Path(os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(resolve_root()))).expanduser()
    return runtime_root / "state" / "voice_audio_levels.json"


def read_audio_levels(levels_file: Path) -> dict[str, Any]:
    try:
        if levels_file.exists():
            payload = json.loads(levels_file.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}
    return {}


def write_audio_levels(
    levels_file: Path,
    *,
    input_level: int | None = None,
    output_level: int | None = None,
    recording: bool | None = None,
    playing: bool | None = None,
) -> None:
    existing = read_audio_levels(levels_file)
    payload = {
        "input_level": int(existing.get("input_level", 0)),
        "output_level": int(existing.get("output_level", 0)),
        "recording": bool(existing.get("recording", False)),
        "playing": bool(existing.get("playing", False)),
        "timestamp": time.time(),
    }
    if input_level is not None:
        payload["input_level"] = max(0, min(100, int(input_level)))
    if output_level is not None:
        payload["output_level"] = max(0, min(100, int(output_level)))
    if recording is not None:
        payload["recording"] = bool(recording)
    if playing is not None:
        payload["playing"] = bool(playing)

    levels_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=levels_file.parent,
        delete=False,
        prefix=".voice_audio_levels.",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle)
        tmp_path = Path(handle.name)
    os.replace(tmp_path, levels_file)


def pcm_level(data: bytes) -> int:
    if not data:
        return 0
    try:
        rms = audioop.rms(data, 2)
    except audioop.error:
        return 0
    if rms <= 0:
        return 0
    db = 20 * math.log10(rms / 32767.0)
    return max(0, min(100, int((db + 60) / 60 * 100)))


def stop_recorder(record_pid: int | None) -> None:
    if record_pid is None:
        raise_with_state("voice recorder pid missing", PTT_STOP_CAPTURE_FAILED)
    if not is_process_running(record_pid):
        return
    for sig, timeout_seconds in ((signal.SIGINT, 1.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 0.5)):
        try:
            os.kill(record_pid, sig)
        except ProcessLookupError:
            return
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if not is_process_running(record_pid):
                return
            time.sleep(0.05)
    if is_process_running(record_pid):
        raise_with_state("voice recorder did not stop cleanly", PTT_STOP_CAPTURE_FAILED)


def transcribe_capture(backend: VoiceBackend, capture_path: Path) -> TranscriptionResult:
    if backend.stt_engine == "whisper":
        result = transcribe_with_whisper(backend.stt_bin, capture_path)
    elif backend.stt_engine == "vosk":
        text = transcribe_with_vosk(backend.stt_bin, capture_path)
        result = TranscriptionResult(text=text)
    else:
        raise_with_state("voice stt unavailable", PTT_STOP_TRANSCRIBE_FAILED)
    normalized = normalize_transcript(result.text)
    if normalized.lower() in {"[blank_audio]", "[inaudible]", "[silence]", "[no_speech]", "[no speech]"}:
        return TranscriptionResult(text="", backend=result.backend, fallback_used=result.fallback_used, fallback_reason=result.fallback_reason)
    return TranscriptionResult(text=normalized, backend=result.backend, fallback_used=result.fallback_used, fallback_reason=result.fallback_reason)


def _is_gpu_error(stderr_text: str) -> bool:
    lower = stderr_text.lower()
    return any(keyword in lower for keyword in _GPU_ERROR_KEYWORDS)


def resolve_whisper_model_path() -> Path:
    """Resolve the whisper model file path from env or defaults."""
    root = resolve_root()
    model = clean_text(os.environ.get("LUCY_VOICE_WHISPER_MODEL"))
    if not model:
        model = str(root / "runtime" / "voice" / "models" / f"ggml-{os.environ.get('LUCY_VOICE_MODEL', 'small.en')}.bin")
    model_path = Path(model).expanduser()
    if not model_path.exists():
        fallback = root / "models" / "ggml-base.bin"
        if fallback.exists():
            model_path = fallback
    return model_path


def transcribe_with_whisper(stt_bin: str, capture_path: Path) -> TranscriptionResult:
    # Fast-path: persistent whisper-server worker (GPU already warm)
    if ensure_whisper_worker is not None:
        try:
            model_path = resolve_whisper_model_path()
            port = ensure_whisper_worker(model_path, use_gpu=True)
            if port:
                result = transcribe_with_worker(capture_path, port, timeout=30.0)
                return TranscriptionResult(
                    text=result["text"],
                    backend=result["backend"],
                    fallback_used=result["fallback_used"],
                    fallback_reason=result["fallback_reason"],
                )
        except WhisperWorkerError:
            pass  # Fall through to whisper-cli subprocess path
        except Exception:
            pass  # Defensive: any unexpected error falls through

    root = resolve_root()
    model = clean_text(os.environ.get("LUCY_VOICE_WHISPER_MODEL"))
    if not model:
        model = str(root / "runtime" / "voice" / "models" / f"ggml-{os.environ.get('LUCY_VOICE_MODEL', 'small.en')}.bin")
    model_path = Path(model).expanduser()
    if not model_path.exists():
        fallback = root / "models" / "ggml-base.bin"
        if fallback.exists():
            model_path = fallback
    prefix = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=capture_path.parent,
        delete=False,
        prefix="voice_whisper_",
        suffix=".tmp",
    )
    prefix_path = Path(prefix.name)
    prefix.close()
    prefix_base = prefix_path.with_suffix("")

    def _run_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            shell=False,
            env=whisper_command_env(stt_bin),
        )

    def _extract_text(completed: subprocess.CompletedProcess[str]) -> str:
        txt_path = prefix_base.with_suffix(".txt")
        if txt_path.exists():
            return txt_path.read_text(encoding="utf-8")
        if completed.stdout:
            return completed.stdout
        return ""

    try:
        command = [stt_bin, "-m", str(model_path), "-f", str(capture_path), "-otxt", "-of", str(prefix_base), "--no-timestamps"]
        lang = clean_text(os.environ.get("LUCY_VOICE_STT_LANG"))
        if lang and lang.lower() != "auto":
            command[1:1] = ["-l", lang]

        # Fast decode for voice assistant (tunable via env)
        beam_size = clean_text(os.environ.get("LUCY_VOICE_WHISPER_BEAM_SIZE"))
        if beam_size:
            try:
                command += ["--beam-size", str(int(beam_size))]
            except ValueError:
                command += ["--beam-size", "1", "--best-of", "1"]
        else:
            command += ["--beam-size", "1", "--best-of", "1"]

        # First attempt: GPU (default whisper behavior)
        completed = _run_command(command)
        if completed.returncode == 0:
            return TranscriptionResult(text=_extract_text(completed), backend="gpu")

        # GPU failed — check if it's a GPU-specific error
        error_text = first_nonempty_line(completed.stderr) or first_nonempty_line(completed.stdout)
        if not error_text:
            error_text = f"whisper exited with status {completed.returncode}"

        if not _is_gpu_error(error_text):
            raise_with_state(error_text, PTT_STOP_TRANSCRIBE_FAILED)

        # Retry with CPU fallback (--no-gpu)
        command_cpu = command + ["--no-gpu"]
        completed_cpu = _run_command(command_cpu)
        if completed_cpu.returncode == 0:
            return TranscriptionResult(
                text=_extract_text(completed_cpu),
                backend="cpu",
                fallback_used=True,
                fallback_reason=error_text,
            )

        # CPU fallback also failed
        cpu_error = first_nonempty_line(completed_cpu.stderr) or first_nonempty_line(completed_cpu.stdout) or error_text
        raise_with_state(cpu_error, PTT_STOP_TRANSCRIBE_FAILED)

    except subprocess.TimeoutExpired as exc:
        raise_with_state(f"voice transcription timed out: {exc}", PTT_STOP_TRANSCRIBE_FAILED)
    except OSError as exc:
        raise RuntimeVoiceError(f"unable to run whisper transcription: {exc}") from exc
    finally:
        for path in (prefix_path, prefix_base.with_suffix(".txt")):
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass


def transcribe_with_vosk(stt_bin: str, capture_path: Path) -> str:
    commands = ([stt_bin, "-i", str(capture_path)], [stt_bin, str(capture_path)])
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=45,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise_with_state(f"voice transcription timed out: {exc}", PTT_STOP_TRANSCRIBE_FAILED)
        except OSError as exc:
            raise RuntimeVoiceError(f"unable to run vosk transcription: {exc}") from exc
        output = completed.stdout.strip()
        if output:
            return output
    return ""


def normalize_transcript(text: str) -> str:
    normalized = clean_text(text.replace("\r", " ").replace("\n", " "))
    # Strip whisper timestamp lines that may leak through
    normalized = re.sub(r"\[\d{2}:\d{2}:\d{2}\.\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}\.\d{3}\]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.strip()
    # Filter known silence hallucinations from small.en
    if normalized.lower() in {"you", "i", "a", "the", "um", "uh", "hm", "mm", "mhm", "uh huh", "hmm"}:
        return ""
    return normalized


def _resolve_history_file() -> Path:
    """Resolve the history file path (same logic as runtime_request.py)."""
    raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "state" / "request_history.jsonl"


def _resolve_control_state() -> dict[str, Any]:
    """Load current control state for history entry."""
    state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE")
    if not state_file:
        state_file = default_runtime_namespace_root() / "state" / "current_state.json"
    else:
        state_file = Path(state_file).expanduser()
    
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _resolve_authority() -> dict[str, Any]:
    """Build authority info for history entry."""
    authority_root = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", "")
    runtime_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "")
    return {
        "active_root": authority_root,
        "authority_root": authority_root,
        "runtime_namespace_root": runtime_root,
    }


def _debug_log(msg: str) -> None:
    """Write debug message to stderr."""
    print(f"[runtime_voice] {msg}", file=sys.stderr)


def _clear_history_file() -> None:
    """Clear the history file to start fresh for a new interaction."""
    history_file = _resolve_history_file()
    _debug_log(f"Clearing history file: {history_file}")
    try:
        # Truncate the file (clear all entries)
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            pass  # Opening in "w" mode truncates the file
        _debug_log("History file cleared successfully")
    except Exception as e:
        _debug_log(f"Warning: failed to clear history file: {e}")


def _write_history_entry(
    history_file: Path,
    request_id: str,
    request_text: str,
    response_text: str,
    status: str,
    route: dict[str, Any],
    outcome: dict[str, Any],
    error: str,
) -> None:
    """Write a history entry to the jsonl file (matching runtime_request.py format)."""
    from datetime import datetime, timezone
    
    _debug_log(f"Writing history entry: request_id={request_id}, history_file={history_file}")
    
    entry = {
        "authority": _resolve_authority(),
        "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "control_state": _resolve_control_state(),
        "error": error,
        "outcome": outcome,
        "request_id": request_id,
        "request_text": request_text,
        "response_text": response_text,
        "route": route,
        "status": status,
    }
    
    try:
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True))
            f.write("\n")
        _debug_log(f"History entry written successfully: {request_id}")
    except Exception as e:
        _debug_log(f"ERROR writing history entry: {e}")
        raise


def submit_transcript(transcript: str) -> dict[str, Any]:
    """Submit transcript to Lucy using Python-native router (shell-free)."""
    import sys
    from pathlib import Path
    
    # Add router_py to path
    router_py_path = Path(__file__).parent / "router_py"
    if str(router_py_path) not in sys.path:
        sys.path.insert(0, str(router_py_path))
    
    try:
        from classify import classify_intent, select_route
        from execution_engine import ExecutionEngine
        from policy import normalize_augmentation_policy
    except ImportError:
        from router_py.classify import classify_intent, select_route
        from router_py.execution_engine import ExecutionEngine
        from router_py.policy import normalize_augmentation_policy
    
    engine = ExecutionEngine(config={
        "timeout": 125,
        "use_sqlite_state": True,
    })
    
    try:
        classification = classify_intent(transcript, surface="voice")
        policy = normalize_augmentation_policy(
            os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
        )
        decision = select_route(classification, policy=policy)
        
        result = engine.execute(
            intent=classification,
            route=decision,
            context={"question": transcript},
            use_python_path=True,
        )
        
        request_id = f"voice_{int(time.time() * 1000)}"
        status = "completed" if result.status == "completed" else result.status
        route = {
            "mode": result.route,
            "provider": result.provider,
        }
        outcome = {
            "outcome_code": result.outcome_code,
            "success": result.status == "completed",
        }
        error = result.error_message or ""
        response_text = result.response_text or ""
        
        # Write to history file for HMI display
        try:
            _write_history_entry(
                _resolve_history_file(),
                request_id=request_id,
                request_text=transcript,
                response_text=response_text,
                status=status,
                route=route,
                outcome=outcome,
                error=error,
            )
        except Exception as hist_exc:
            # Log but don't fail the request if history write fails
            print(f"Warning: failed to write history entry: {hist_exc}", file=sys.stderr)
        
        # Build payload matching runtime_request.py format
        return {
            "status": status,
            "response_text": response_text,
            "request_id": request_id,
            "route": route,
            "outcome": outcome,
            "error": error,
        }
    except Exception as exc:
        raise_with_state(f"voice submit failed: {exc}", PTT_STOP_REQUEST_FAILED)
    finally:
        engine.close()


def parse_json_payload(text: str) -> dict[str, Any] | None:
    raw = clean_text(text)
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def first_nonempty_line(text: str) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def run_tts_adapter_command(
    *,
    python_bin: str,
    command: str,
    requested_engine: str,
    text: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    adapter_tool = resolve_tts_adapter_tool()
    if not adapter_tool.exists():
        return {"ok": False, "error": f"missing tts adapter: {adapter_tool}"}

    invoke = [python_bin, str(adapter_tool), command, "--engine", requested_engine]
    if output_dir:
        invoke.extend(["--output-dir", output_dir])
    if text is not None:
        invoke.extend(["--text", text])

    try:
        completed = subprocess.run(
            invoke,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
            env=os.environ.copy(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}

    payload = parse_json_payload(completed.stdout)
    if payload is None:
        error_text = first_nonempty_line(completed.stderr) or first_nonempty_line(completed.stdout) or "tts adapter failed"
        return {"ok": False, "error": error_text}
    return payload


def speak_response(backend: VoiceBackend, response_text: str) -> str:
    if backend.tts_engine == "none":
        return "skipped"
    spoken_text = sanitize_tts_text(response_text)
    if not spoken_text:
        return "skipped"
    try:
        chunks = split_tts_chunks(spoken_text)
        if not chunks:
            return "skipped"
        pause_ms = resolve_tts_chunk_pause_ms()
        output_dir = resolve_capture_directory(None)
        output_dir.mkdir(parents=True, exist_ok=True)
        voice_python = resolve_voice_python(backend.tts_engine)
        levels_file = audio_levels_file_for_runtime(None)
        for index, chunk in enumerate(chunks):
            if backend.tts_engine == "kokoro" and ensure_kokoro_worker():
                payload = kokoro_worker_request(
                    {
                        "cmd": "synthesize",
                        "engine": "kokoro",
                        "text": chunk,
                        "output_dir": str(output_dir),
                    }
                )
            else:
                payload = run_tts_adapter_command(
                    python_bin=voice_python,
                    command="synthesize",
                    requested_engine=backend.tts_engine,
                    output_dir=str(output_dir),
                    text=chunk,
                )
            if not payload.get("ok"):
                raise RuntimeVoiceError(clean_text(payload.get("error")) or "tts synthesis failed")
            wav_path = Path(str(payload.get("wav_path") or "")).expanduser()
            if not wav_path.exists():
                raise RuntimeVoiceError("tts synthesis produced no wav output")
            is_first_chunk = index == 0
            engine_name = clean_text(payload.get("engine"))
            prepad_ms = resolve_tts_prepad_ms(engine_name, is_first_chunk=is_first_chunk)
            prime_ms = resolve_kokoro_first_chunk_player_prime_ms() if is_first_chunk and engine_name == "kokoro" else 0
            player = None if backend.audio_player == "none" else backend.audio_player
            try:
                if play_wav_file_with_levels is not None:
                    play_wav_file_with_levels(
                        wav_path,
                        levels_file,
                        player=player,
                        prepad_ms=prepad_ms,
                        prime_ms=prime_ms,
                    )
                else:
                    play_wav_file(
                        wav_path,
                        player=player,
                        prepad_ms=prepad_ms,
                        prime_ms=prime_ms,
                    )
            finally:
                try:
                    wav_path.unlink()
                except OSError:
                    pass
            if index + 1 < len(chunks) and pause_ms > 0:
                time.sleep(pause_ms / 1000.0)
        return "completed"
    except (PlaybackError, RuntimeVoiceError):
        return "failed"
    return "skipped"


def sanitize_tts_text(text: str) -> str:
    cleaned = text.replace("\r", "\n")
    cleaned = strip_tts_only_boilerplate(cleaned)
    
    # Strip HTML tags for TTS
    # Remove script and style elements first
    cleaned = re.sub(r'<script[^>]*>.*?</script>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'<style[^>]*>.*?</style>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    # Replace common HTML elements with newlines or spaces
    cleaned = re.sub(r'<br\s*/?>', '\n', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'</p>', '\n', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<p[^>]*>', '', cleaned, flags=re.IGNORECASE)
    # Extract link text from anchor tags
    cleaned = re.sub(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', lambda m: m.group(2), cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'<a[^>]*>([^<]*)</a>', lambda m: m.group(1), cleaned, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    cleaned = re.sub(r'<[^>]+>', '', cleaned)
    # Decode common HTML entities
    cleaned = cleaned.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    cleaned = cleaned.replace('&quot;', '"').replace('&#39;', "'")
    cleaned = cleaned.replace('&nbsp;', ' ').replace('&#160;', ' ')
    
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.replace("`", "")
    cleaned = cleaned.replace("**", "")
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    max_chars_raw = clean_text(os.environ.get("LUCY_VOICE_TTS_MAX_CHARS")) or "10000"
    try:
        max_chars = int(max_chars_raw)
    except ValueError:
        max_chars = 10000
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = truncate_tts_text_cleanly(cleaned, max_chars)
    return cleaned


def ensure_terminal_list_punctuation(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    if cleaned.endswith(("...", "…")):
        return cleaned
    if re.search(r'[.!?]["\')\]”’]*$', cleaned):
        return cleaned + ".."
    return cleaned + "..."


def split_tts_chunks(text: str) -> list[str]:
    units: list[str] = []
    max_chunk_chars = resolve_tts_chunk_max_chars(multiline="\n" in text)
    for raw_line in text.splitlines():
        line = clean_text(raw_line)
        if not line:
            continue
        if len(line) <= max_chunk_chars:
            units.append(line)
            continue
        parts = [clean_text(part) for part in re.split(r'(?<=[.!?;:])\s+', line) if clean_text(part)]
        if not parts:
            continue
        current = ""
        for part in parts:
            candidate = part if not current else f"{current} {part}"
            if current and len(candidate) > max_chunk_chars:
                units.append(current)
                current = part
            else:
                current = candidate
        if current:
            units.append(current)
    chunks: list[str] = []
    current = ""
    for unit in units:
        candidate = unit if not current else f"{current}\n{unit}"
        if current and len(candidate) > max_chunk_chars:
            chunks.append(current)
            current = unit
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def truncate_tts_text_cleanly(text: str, max_chars: int) -> str:
    cleaned = clean_text(text)
    if not cleaned or max_chars <= 0 or len(cleaned) <= max_chars:
        return cleaned

    chunks = split_tts_chunks(cleaned)
    if not chunks:
        return cleaned[:max_chars].rstrip()

    selected: list[str] = []
    current_len = 0
    for chunk in chunks:
        next_len = len(chunk) if not selected else current_len + 1 + len(chunk)
        if next_len > max_chars:
            break
        selected.append(chunk)
        current_len = next_len

    if selected:
        return " ".join(selected).rstrip()

    cut = cleaned[:max_chars].rstrip()
    sentence_end = [m.end() for m in re.finditer(r"[.!?;:](?:\s|$)", cut)]
    if sentence_end:
        return cut[: sentence_end[-1]].rstrip()
    return cut


def resolve_tts_chunk_pause_ms() -> int:
    raw = clean_text(os.environ.get("LUCY_VOICE_TTS_CHUNK_PAUSE_MS"))
    if raw:
        try:
            pause_ms = int(raw)
        except ValueError:
            return 56
        return max(pause_ms, 0)
    return 56


def resolve_tts_chunk_max_chars(*, multiline: bool = False) -> int:
    default_value = "1200" if multiline else "480"
    env_name = "LUCY_VOICE_TTS_MULTILINE_CHUNK_MAX_CHARS" if multiline else "LUCY_VOICE_TTS_CHUNK_MAX_CHARS"
    raw = clean_text(os.environ.get(env_name)) or default_value
    try:
        max_chars = int(raw)
    except ValueError:
        return 1200 if multiline else 480
    return max(max_chars, 80)


def strip_tts_only_boilerplate(text: str) -> str:
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        is_list_item = bool(re.match(r"^(?:-\s+|\*\s+|\d+\.\s+)", line))
        if not line:
            continue
        if re.match(r"^(From current sources:|Key items:|Sources:)$", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^Latest items extracted from allowlisted sources as of\b", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^Conflicts/uncertainty:", line, flags=re.IGNORECASE):
            continue
        if re.match(r"^\-?\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}\s*$", line):
            continue
        line = re.sub(r"^\-\s+", "", line)
        line = re.sub(r"\[([^\]]+)\]", r"\1", line)
        line = re.sub(r"(\S)\s*\((?:[^)]*\d{4}[^)]*)\)\s*:", r"\1:", line)
        line = strip_spoken_datetime_tokens(line)
        line = re.sub(r"^[A-Za-z0-9.-]+\.[A-Za-z]{2,}:\s*", "", line)
        line = re.sub(r"\bas of\b[\s,:-]*$", "", line, flags=re.IGNORECASE)
        line = re.sub(r"\(\s*\)", "", line)
        line = re.sub(r"\s+", " ", line).strip(" ,:-")
        if is_list_item:
            line = ensure_terminal_list_punctuation(line)
        if line:
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def strip_spoken_datetime_tokens(text: str) -> str:
    patterns = (
        r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\b",
        r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+\d{1,2}\s+"
        r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
        r"\d{4}\s+\d{2}:\d{2}(?::\d{2})?\s*(?:GMT|UTC|[+-]\d{4})?\b",
        r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:GMT|UTC|[+-]\d{4})\b",
    )
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\(\s*,?\s*\)", "", cleaned)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def resolve_piper_prepad_ms() -> int:
    raw = clean_text(os.environ.get("LUCY_VOICE_PIPER_PREPAD_MS")) or "80"
    try:
        prepad_ms = int(raw)
    except ValueError:
        return 80
    return prepad_ms if prepad_ms >= 0 else 0


def resolve_kokoro_prepad_ms() -> int:
    raw = clean_text(os.environ.get("LUCY_VOICE_KOKORO_PREPAD_MS"))
    if not raw:
        return 120
    try:
        prepad_ms = int(raw)
    except ValueError:
        return 120
    return prepad_ms if prepad_ms >= 0 else 0


def resolve_kokoro_first_chunk_prepad_ms() -> int:
    raw = clean_text(os.environ.get("LUCY_VOICE_KOKORO_FIRST_CHUNK_PREPAD_MS"))
    if not raw:
        return 220
    try:
        prepad_ms = int(raw)
    except ValueError:
        return 220
    return prepad_ms if prepad_ms >= 0 else 0


def resolve_kokoro_first_chunk_player_prime_ms() -> int:
    raw = clean_text(os.environ.get("LUCY_VOICE_KOKORO_FIRST_CHUNK_PLAYER_PRIME_MS"))
    if not raw:
        return 80
    try:
        prime_ms = int(raw)
    except ValueError:
        return 80
    return prime_ms if prime_ms >= 0 else 0


def resolve_tts_prepad_ms(engine: str, *, is_first_chunk: bool = False) -> int:
    if engine == "piper":
        return resolve_piper_prepad_ms()
    if engine == "kokoro":
        if is_first_chunk:
            return resolve_kokoro_first_chunk_prepad_ms()
        return resolve_kokoro_prepad_ms()
    return 0


def raise_with_state(message: str, exit_code: int) -> None:
    raise RuntimeVoiceExit(message, exit_code)


# ============================================================================
# Python Voice Pipeline Integration (V8)
# ============================================================================
# These functions provide a Python-native voice pipeline that integrates
# with the existing shell-based infrastructure. Enable with LUCY_VOICE_PY=1

# Global storage for Python voice pipeline state
_python_voice_pipeline: Any = None
_python_voice_capture_path: Path | None = None


def handle_status_python() -> dict[str, Any]:
    """Handle voice status using Python voice pipeline."""
    if not _VOICE_TOOL_AVAILABLE:
        return {
            "schema_version": 1,
            "available": False,
            "listening": False,
            "processing": False,
            "status": "unavailable",
            "last_error": "Python voice tool not available",
            "last_updated": iso_now(),
            "recorder": "unavailable",
            "stt": "unavailable",
            "tts": "none",
            "tts_device": "none",
            "audio_player": "none",
            "record_pid": None,
            "processing_pid": None,
            "capture_path": "",
            "last_transcript": "",
            "last_request_id": "",
        }
    
    global _python_voice_pipeline
    
    pipeline = VoicePipeline()
    backend = pipeline._detect_backend()
    
    # Determine status
    is_listening = _python_voice_pipeline is not None and _python_voice_capture_path is not None
    
    return {
        "schema_version": 1,
        "available": backend.available,
        "listening": is_listening,
        "processing": False,
        "status": "listening" if is_listening else ("idle" if backend.available else "unavailable"),
        "last_error": backend.reason if not backend.available else "",
        "last_updated": iso_now(),
        "recorder": backend.recorder_engine,
        "stt": backend.stt_engine,
        "tts": backend.tts_engine,
        "tts_device": backend.tts_device,
        "audio_player": backend.audio_player,
        "record_pid": None,
        "processing_pid": None,
        "capture_path": str(_python_voice_capture_path) if _python_voice_capture_path else "",
        "last_transcript": "",
        "last_request_id": "",
    }


def handle_ptt_start_python(
    runtime_file: Path, state_file: Path, capture_dir: Path
) -> dict[str, Any]:
    """Handle PTT start using Python voice pipeline.
    
    Launches background recorder process that continues until ptt-stop.
    """
    import subprocess
    
    capture_dir.mkdir(parents=True, exist_ok=True)
    capture_path = capture_dir / f"ptt_{time.strftime('%Y%m%dT%H%M%S')}_{os.getpid()}.wav"
    
    # Check voice is enabled
    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        voice_enabled = clean_text(current_state.get("voice")).lower() == "on"
        
        if not voice_enabled:
            raise_with_state("voice disabled", PTT_START_DISABLED)
        
        # Check backend
        pipeline = VoicePipeline()
        backend = pipeline._detect_backend()
        
        if not backend.available:
            raise_with_state(backend.reason, PTT_START_UNAVAILABLE)
        
        # Launch background recorder
        recorder_script = Path(__file__).parent / "router_py" / "voice_recorder.py"
        if not recorder_script.exists():
            raise_with_state(f"Recorder script not found: {recorder_script}", PTT_START_UNAVAILABLE)
        
        # Use a stop file for reliable signaling (signals can be lost)
        stop_file = capture_path.with_suffix('.stop')
        
        try:
            # Launch background recorder with IMMEDIATE audio capture
            # The recorder starts arecord FIRST, then writes PID to minimize latency
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(recorder_script),
                    "--output", str(capture_path),
                    "--runtime-file", str(runtime_file),
                    "--stop-file", str(stop_file),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # Detach from parent
            )
            
            # Return IMMEDIATELY - don't wait for PID to be written
            # The recorder will update the runtime file asynchronously
            # This minimizes latency between button press and audio capture
            runtime_state = {
                "schema_version": 1,
                "available": True,
                "listening": True,
                "processing": False,
                "status": "listening",
                "last_error": "",
                "last_updated": iso_now(),
                "recorder": backend.recorder_engine,
                "stt": backend.stt_engine,
                "tts": backend.tts_engine,
                "tts_device": backend.tts_device,
                "audio_player": backend.audio_player,
                "record_pid": proc.pid,  # Use our PID, recorder will update
                "processing_pid": None,
                "capture_path": str(capture_path),
                "last_transcript": "",
                "last_request_id": "",
            }
            write_voice_runtime(runtime_file, runtime_state)
            
            return normalize_voice_runtime(runtime_state)
            
        except Exception as e:
            raise_with_state(f"Failed to start recorder: {e}", PTT_START_FAILED)


def handle_ptt_stop_python(
    runtime_file: Path, state_file: Path, capture_dir: Path
) -> dict[str, Any]:
    """Handle PTT stop using Python voice pipeline.
    
    Signals background recorder to stop, then processes the recorded audio.
    """
    import asyncio
    import os
    import signal
    
    
    # Read recorder PID and capture path from runtime file
    with locked_state_file(runtime_file):
        current_state = load_or_create_state(state_file, refresh_timestamp=False)
        runtime_state = load_voice_runtime_locked(runtime_file)
        
        if not runtime_state.get("listening"):
            raise_with_state("voice not listening", PTT_STOP_NOT_LISTENING)
        
        record_pid = runtime_state.get("record_pid")
        capture_path_str = runtime_state.get("capture_path")
    
    # Signal recorder to stop using stop file (more reliable than signals)
    capture_path = Path(capture_path_str) if capture_path_str else None
    stop_file = capture_path.with_suffix('.stop') if capture_path else None
    
    if stop_file:
        try:
            stop_file.touch()  # Create stop file
        except Exception as e:
            print(f"Warning: Failed to create stop file: {e}", file=sys.stderr)
    
    # Also try SIGTERM as backup
    if record_pid:
        try:
            os.kill(record_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass  # Process already exited
        except Exception as e:
            pass  # Ignore errors
        
        # Wait for recorder to finish (up to 3 seconds)
        import time
        for _ in range(30):
            try:
                os.kill(record_pid, 0)  # Check if process exists
                time.sleep(0.1)
            except ProcessLookupError:
                break  # Process exited
    
    # Check if audio file exists
    if not capture_path or not capture_path.exists():
        # No audio recorded - update state and return
        with locked_state_file(runtime_file):
            error_state = {
                "schema_version": 1,
                "available": True,
                "listening": False,
                "processing": False,
                "status": "no_transcript",
                "last_error": "No audio recorded",
                "stt_backend": "",
                "stt_fallback_reason": "",
                "last_updated": iso_now(),
            }
            write_voice_runtime(runtime_file, error_state)
        return {
            "status": "no_transcript",
            "transcript": "",
            "error": "No audio recorded",
            "tts_status": "none",
        }
    
    # Clear history file to start fresh for this interaction
    _clear_history_file()
    
    # Process the recorded audio using STREAMING pipeline
    # Import streaming pipeline
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).parent / "router_py"))
    from streaming_voice import StreamingVoicePipeline
    
    # Update state to processing
    with locked_state_file(runtime_file):
        runtime_state = load_voice_runtime_locked(runtime_file)
        runtime_state["status"] = "processing"
        runtime_state["listening"] = False
        runtime_state["processing_pid"] = os.getpid()
        runtime_state["last_updated"] = iso_now()
        write_voice_runtime(runtime_file, runtime_state)
    
    # Voice is an input modality only. Transcribe and return transcript to UI;
    # UI submits through normal text pipeline (memory, routing, evidence,
    # augmented, telemetry all preserved).
    try:
        _sys.path.insert(0, str(Path(__file__).parent / "router_py"))
        from voice_tool import AudioBuffer, VoicePipeline

        audio = AudioBuffer.from_file(capture_path)
        pipeline = VoicePipeline()
        transcript = asyncio.run(pipeline.transcribe(audio))
        transcript = normalize_transcript(transcript)
    except Exception as exc:
        with locked_state_file(runtime_file):
            error_state = {
                "schema_version": 1,
                "available": True,
                "listening": False,
                "processing": False,
                "status": "error",
                "last_error": str(exc),
                "stt_backend": "",
                "stt_fallback_reason": "",
                "last_updated": iso_now(),
            }
            write_voice_runtime(runtime_file, error_state)
        raise_with_state(f"Python voice transcription failed: {exc}", PTT_STOP_TRANSCRIBE_FAILED)

    if not transcript:
        with locked_state_file(runtime_file):
            no_transcript_state = {
                "schema_version": 1,
                "available": True,
                "listening": False,
                "processing": False,
                "status": "idle",
                "last_error": "",
                "last_transcript": "",
                "last_request_id": "",
                "stt_backend": "",
                "stt_fallback_reason": "",
                "last_updated": iso_now(),
            }
            write_voice_runtime(runtime_file, no_transcript_state)
        return {
            "status": "no_transcript",
            "transcript": "",
            "error": "no transcript",
        }

    with locked_state_file(runtime_file):
        runtime_state = {
            "schema_version": 1,
            "available": True,
            "listening": False,
            "processing": False,
            "status": "idle",
            "last_error": "",
            "last_transcript": transcript,
            "last_request_id": "",
            "stt_backend": "",
            "stt_fallback_reason": "",
            "last_updated": iso_now(),
        }
        write_voice_runtime(runtime_file, runtime_state)

    return {
        "status": "completed",
        "transcript": transcript,
        "error": "",
    }


# =============================================================================
# Voice Engine Logging
# =============================================================================

class VoiceEngineLogger:
    """Logger for voice engine detection and usage."""
    
    def __init__(self):
        # ISOLATION: Use V8-specific logs if available
        v8_logs = os.environ.get("LUCY_LOGS_DIR")
        if v8_logs:
            self.log_dir = Path(v8_logs)
        else:
            self.log_dir = Path.home() / ".local" / "share" / "lucy-v8" / "logs"
        self.log_file = self.log_dir / "voice_engine.log"
        self._ensure_log_dir()
    
    def _ensure_log_dir(self):
        """Ensure log directory exists."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, level: str, message: str) -> None:
        """Write log entry."""
        from datetime import datetime
        timestamp = datetime.now().isoformat()
        entry = f"{timestamp} [{level}] {message}\n"
        try:
            with open(self.log_file, "a") as f:
                f.write(entry)
        except Exception:
            pass
    
    def info(self, message: str) -> None:
        self.log("INFO", message)
    
    def debug(self, message: str) -> None:
        self.log("DEBUG", message)


_voice_logger = VoiceEngineLogger()


if __name__ == "__main__":
    raise SystemExit(main())
