#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice.backends import kokoro_backend
from voice import tts_adapter


def resolve_root() -> Path:
    """Resolve runtime root directory."""
    authority = os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT")
    if authority:
        return Path(authority).expanduser().resolve()
    root = os.environ.get("LUCY_ROOT")
    if root:
        return Path(root).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _failure(error: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"ok": False, "error": error}
    payload.update(extra)
    return payload


def handle_request(payload: Mapping[str, Any], env: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = dict(env or os.environ)
    command = _clean_text(payload.get("cmd")).lower()
    if command == "prewarm":
        return handle_prewarm(payload, values)
    if command == "synthesize":
        requested_engine = _clean_text(payload.get("engine")) or values.get("LUCY_VOICE_TTS_ENGINE") or "auto"
        return tts_adapter.synthesize_text(
            text=_clean_text(payload.get("text")),
            requested_engine=requested_engine,
            requested_voice=_clean_text(payload.get("voice")) or None,
            output_dir=_clean_text(payload.get("output_dir")) or None,
            fallback_engine=_clean_text(payload.get("fallback_engine")) or None,
            env=values,
        )
    if command == "quit":
        return {"ok": True, "status": "bye"}
    return _failure(f"unsupported command: {command}")


def handle_prewarm(payload: Mapping[str, Any], env: Mapping[str, str]) -> dict[str, Any]:
    requested_engine = _clean_text(payload.get("engine")) or env.get("LUCY_VOICE_TTS_ENGINE") or "auto"
    requested_voice = _clean_text(payload.get("voice")) or None
    fallback_engine = _clean_text(payload.get("fallback_engine")) or None
    selected = tts_adapter.resolve_selected_backend(
        requested_engine=tts_adapter.normalize_engine(requested_engine),
        requested_voice=requested_voice,
        fallback_engine=fallback_engine,
        env=env,
    )
    if selected is None:
        return _failure(
            "no tts backend available",
            requested_engine=requested_engine,
            engine="none",
            prewarmed=False,
        )
    if selected.engine != "kokoro":
        return {
            "ok": True,
            "requested_engine": requested_engine,
            "engine": selected.engine,
            "voice": selected.voice,
            "prewarmed": False,
            "error": "",
        }
    try:
        root = tts_adapter.resolve_root()
        kokoro_backend.configure_runtime_environment(root, env)
        lang_code = kokoro_backend.resolve_lang_code(env, selected.voice)
        repo_id = kokoro_backend.resolve_repo_id(env)
        device = kokoro_backend.resolve_device(env)
        kokoro_backend.get_pipeline(lang_code=lang_code, repo_id=repo_id, device=device)
    except Exception as exc:
        return _failure(
            str(exc),
            requested_engine=requested_engine,
            engine="kokoro",
            voice=selected.voice,
            prewarmed=False,
        )
    return {
        "ok": True,
        "requested_engine": requested_engine,
        "engine": "kokoro",
        "voice": selected.voice,
        "prewarmed": True,
        "error": "",
    }


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "serve":
        return serve_main(sys.argv[2:])
    if len(sys.argv) >= 2 and sys.argv[1] == "--daemon":
        # Shortcut for daemon mode with default socket
        return serve_main(["--daemon"])
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _failure(f"invalid json: {exc}")
        else:
            response = handle_request(payload)
        sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
        sys.stdout.flush()
        if _clean_text(response.get("status")) == "bye":
            return 0
    return 0


def serve_main(argv: list[str]) -> int:
    """Run socket server. Supports --socket <path> and --daemon flags."""
    socket_path: Path | None = None
    daemon_mode = False
    pid_file: Path | None = None
    
    i = 0
    while i < len(argv):
        if argv[i] == "--socket" and i + 1 < len(argv):
            socket_path = Path(argv[i + 1]).expanduser()
            i += 2
        elif argv[i] == "--daemon":
            daemon_mode = True
            i += 1
        elif argv[i] == "--pid-file" and i + 1 < len(argv):
            pid_file = Path(argv[i + 1]).expanduser()
            i += 2
        else:
            i += 1
    
    if socket_path is None:
        # Default socket path
        root = resolve_root()
        socket_path = root / "tmp" / "run" / "kokoro_tts_worker.sock"
    
    if pid_file is None:
        root = resolve_root()
        pid_file = root / "tmp" / "run" / "kokoro_tts_worker.pid"
    
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()
    
    if daemon_mode:
        # Daemonize: fork, detach, write PID file
        try:
            pid = os.fork()
            if pid > 0:
                # Parent exits
                return 0
        except OSError as e:
            print(json.dumps(_failure(f"fork failed: {e}"), sort_keys=True), file=sys.stderr)
            return 1
        
        # Child process
        os.setsid()
        os.umask(0o022)
        
        # Second fork to prevent re-acquiring terminal
        try:
            pid = os.fork()
            if pid > 0:
                return 0
        except OSError as e:
            print(json.dumps(_failure(f"second fork failed: {e}"), sort_keys=True), file=sys.stderr)
            return 1
        
        # Write PID file
        pid_file.write_text(str(os.getpid()))
        
        # Redirect stdout/stderr to /dev/null
        sys.stdout.flush()
        sys.stderr.flush()
        with open("/dev/null", "w") as devnull:
            os.dup2(devnull.fileno(), sys.stdout.fileno())
            os.dup2(devnull.fileno(), sys.stderr.fileno())
    
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                raw = b""
                while True:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    raw += chunk
                    if b"\n" in raw:
                        break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    response = _failure("empty request")
                else:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError as exc:
                        response = _failure(f"invalid json: {exc}")
                    else:
                        response = handle_request(payload)
                try:
                    conn.sendall((json.dumps(response, sort_keys=True) + "\n").encode("utf-8"))
                except (BrokenPipeError, ConnectionResetError):
                    # Client disconnected (e.g., timed out), log and continue
                    print(f"[Worker] Client disconnected while sending response", flush=True)
                    pass
                if _clean_text(response.get("status")) == "bye":
                    return 0
    finally:
        server.close()
        try:
            socket_path.unlink()
        except FileNotFoundError:
            pass
        try:
            pid_file.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
