#!/usr/bin/env python3
import argparse
import base64
import errno
import fcntl
import json
import os
import select
import shlex
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Optional

REQUEST_ENV_KEYS = (
    "LUCY_ROOT",
    "LUCY_LOCAL_MODEL",
    "LUCY_OLLAMA_API_URL",
    "LUCY_LOCAL_TEMPERATURE",
    "LUCY_LOCAL_TOP_P",
    "LUCY_LOCAL_SEED",
    "LUCY_LOCAL_KEEP_ALIVE",
    "LUCY_SESSION_MEMORY_CONTEXT",
    "LUCY_CONVERSATION_MODE_ACTIVE",
    "LUCY_CONVERSATION_MODE_FORCE",
    "LUCY_CONVERSATION_SYSTEM_BLOCK",
    "LUCY_IDENTITY_TRACE_FILE",
    "LUCY_LOCAL_POLICY_RESPONSE_ID",
    "LUCY_LOCAL_REPEAT_CACHE",
    "LUCY_LOCAL_REPEAT_CACHE_DIR",
    "LUCY_LOCAL_REPEAT_CACHE_TTL_S",
    "LUCY_LOCAL_REPEAT_CACHE_MAX_ENTRIES",
    "LUCY_LOCAL_PROMPT_GUARD_TOKENS",
    "LUCY_LOCAL_GEN_ROUTE_MODE",
    "LUCY_LOCAL_GEN_OUTPUT_MODE",
    "LUCY_LOCAL_NUM_PREDICT_DEFAULT",
    "LUCY_LOCAL_NUM_PREDICT_CHAT",
    "LUCY_LOCAL_NUM_PREDICT_CONVERSATION",
    "LUCY_LOCAL_NUM_PREDICT_BRIEF",
    "LUCY_LOCAL_NUM_PREDICT_DETAIL",
    "LUCY_LOCAL_NUM_PREDICT_CLARIFY",
    "LUCY_LOCAL_DIAG_FILE",
    "LUCY_LOCAL_DIAG_RUN_ID",
    "LUCY_LATENCY_PROFILE_ACTIVE",
    "LUCY_LATENCY_PROFILE_FILE",
    "LUCY_LATENCY_RUN_ID",
    "LUCY_LOCAL_MODEL_PRELOADED",
    "LUCY_TOOLS_DIR",
)

REQUEST_MODE_ENV = "LUCY_LOCAL_WORKER_REQUEST_MODE"


def _root() -> Path:
    return Path(os.environ.get("LUCY_ROOT") or Path(__file__).resolve().parents[1]).resolve()


def _run_dir(root: Path) -> Path:
    return root / "tmp" / "run"


def _socket_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_SOCKET") or (_run_dir(root) / "local_worker.sock"))


def _request_fifo_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_REQUEST_FIFO") or (_run_dir(root) / "local_worker.request.fifo"))


def _pid_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_PID_FILE") or (_run_dir(root) / "local_worker.pid"))


def _lock_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_LOCK_FILE") or (_run_dir(root) / "local_worker.lock"))


def _log_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_LOG_FILE") or (_run_dir(root) / "local_worker.log"))


def _code_stamp_path(root: Path) -> Path:
    return Path(os.environ.get("LUCY_LOCAL_WORKER_CODE_STAMP_FILE") or (_run_dir(root) / "local_worker.code_stamp"))


def _local_answer_path(root: Path) -> Path:
    return root / "tools" / "local_answer.sh"


def _worker_code_paths(root: Path) -> list[Path]:
    return [
        _local_answer_path(root),
        root / "tools" / "local_worker.py",
    ]


def _local_answer_code_stamp(root: Path) -> str:
    parts = []
    for path in _worker_code_paths(root):
        try:
            stat = path.stat()
        except OSError:
            return ""
        parts.append(f"{path}:{int(stat.st_mtime_ns)}:{int(stat.st_size)}")
    return "|".join(parts)


def _idle_timeout_s() -> int:
    raw = os.environ.get("LUCY_LOCAL_WORKER_IDLE_S", "900")
    try:
        return max(5, int(raw))
    except ValueError:
        return 900


def _startup_timeout_s() -> float:
    raw = os.environ.get("LUCY_LOCAL_WORKER_STARTUP_TIMEOUT_S", "3")
    try:
        return max(0.5, float(raw))
    except ValueError:
        return 3.0


def _transport() -> str:
    value = (os.environ.get("LUCY_LOCAL_WORKER_TRANSPORT") or "unix").strip().lower()
    if value in {"fifo", "file"}:
        return "fifo"
    return "unix"


def _append_latency_from_env(stage: str, ms: int, env: Optional[Dict[str, str]] = None, component: str = "local_worker") -> None:
    source_env = env or os.environ
    if (source_env.get("LUCY_LATENCY_PROFILE_ACTIVE") or "0") != "1":
        return
    path = (source_env.get("LUCY_LATENCY_PROFILE_FILE") or "").strip()
    run_id = (source_env.get("LUCY_LATENCY_RUN_ID") or "").strip()
    if not path or not run_id:
        return
    try:
        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        with path_obj.open("a", encoding="utf-8") as handle:
            handle.write(f"run={run_id}\tcomponent={component}\tstage={stage}\tms={int(ms)}\n")
    except OSError:
        return


def _append_latency(stage: str, ms: int, component: str = "local_worker") -> None:
    _append_latency_from_env(stage, ms, env=None, component=component)


def _request_mode() -> str:
    value = (os.environ.get(REQUEST_MODE_ENV) or "client").strip().lower()
    if value in {"direct", "client"}:
        return value
    return "client"


def _request_env_overrides() -> Dict[str, str]:
    out = _filtered_env()
    return {key: value for key, value in out.items() if value}


def _filtered_env() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, value in os.environ.items():
        if not key.startswith("LUCY_"):
            continue
        out[key] = value
    return out


def _env_shell_from_overrides(env_overrides: Dict[str, str]) -> str:
    valid_keys = [key for key in REQUEST_ENV_KEYS if env_overrides.get(key)]
    for key in sorted(env_overrides):
        if key in valid_keys:
            continue
        if not key.startswith("LUCY_"):
            continue
        if key.replace("_", "").isalnum() and key.upper() == key:
            valid_keys.append(key)
    if not valid_keys:
        return ""
    shell_lines = [f"LOCAL_ANSWER_WORKER_ENV_KEYS={shlex.quote(' '.join(valid_keys))}"]
    for key in valid_keys:
        shell_lines.append(f"export {key}={shlex.quote(env_overrides[key])}")
    return "\n".join(shell_lines)


def _read_pid(pid_path: Path) -> Optional[int]:
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
        return int(raw)
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _send_json_unix_line(sock_path: Path, payload: Dict[str, object], timeout_s: float = 2.0) -> Dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout_s)
        client.connect(str(sock_path))
        client.sendall(json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n")
        buf = b""
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\n" in buf:
                line, _rest = buf.split(b"\n", 1)
                return json.loads(line.decode("utf-8"))
    raise RuntimeError("worker returned no response")


def _send_json_fifo(root: Path, payload: Dict[str, object], timeout_s: float = 2.0) -> Dict[str, object]:
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    request_fifo = _request_fifo_path(root)
    if not request_fifo.exists():
        raise RuntimeError("worker request fifo missing")

    response_path = run_dir / f"local_worker.response.{os.getpid()}.{time.time_ns()}.json"
    env_payload = payload.get("env") or {}
    if not isinstance(env_payload, dict):
        env_payload = {}
    lines = [
        "BEGIN_REQUEST",
        f"RESPONSE\t{response_path}",
        f"COMMAND\t{str(payload.get('command') or 'request')}",
    ]
    if "question" in payload:
        question_b64 = base64.b64encode(str(payload.get("question") or "").encode("utf-8")).decode("ascii")
        lines.append(f"QUESTION\t{question_b64}")
    if payload.get("env_shell"):
        env_shell_b64 = base64.b64encode(str(payload.get("env_shell") or "").encode("utf-8")).decode("ascii")
        lines.append(f"ENV_SHELL\t{env_shell_b64}")
    for key in sorted(env_payload):
        value_b64 = base64.b64encode(str(env_payload[key]).encode("utf-8")).decode("ascii")
        lines.append(f"ENV\t{key}\t{value_b64}")
    lines.append("END_REQUEST")
    deadline = time.monotonic() + timeout_s

    while True:
        try:
            fd = os.open(str(request_fifo), os.O_WRONLY | os.O_NONBLOCK)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
            break
        except OSError as exc:
            if exc.errno not in {errno.ENXIO, errno.ENOENT} or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)

    while time.monotonic() < deadline:
        try:
            if response_path.exists() and response_path.stat().st_size > 0:
                raw = response_path.read_text(encoding="utf-8")
                response_path.unlink(missing_ok=True)
                parsed: Dict[str, object] = {}
                for line in raw.splitlines():
                    if line == "BEGIN_RESPONSE" or line == "END_RESPONSE" or not line:
                        continue
                    if line.startswith("OK\t"):
                        parsed["ok"] = line.split("\t", 1)[1] == "1"
                    elif line.startswith("RC\t"):
                        try:
                            parsed["rc"] = int(line.split("\t", 1)[1])
                        except ValueError:
                            parsed["rc"] = 1
                    elif line.startswith("PID\t"):
                        try:
                            parsed["pid"] = int(line.split("\t", 1)[1])
                        except ValueError:
                            pass
                    elif line.startswith("TRANSPORT\t"):
                        parsed["transport"] = line.split("\t", 1)[1]
                    elif line.startswith("SOCKET\t"):
                        parsed["socket"] = line.split("\t", 1)[1]
                    elif line.startswith("REQUEST_FIFO\t"):
                        parsed["request_fifo"] = line.split("\t", 1)[1]
                    elif line.startswith("OUTPUT\t"):
                        parsed["output"] = base64.b64decode(line.split("\t", 1)[1].encode("ascii")).decode("utf-8")
                    elif line.startswith("ERROR\t"):
                        parsed["error"] = base64.b64decode(line.split("\t", 1)[1].encode("ascii")).decode("utf-8")
                return parsed
        except OSError:
            pass
        time.sleep(0.05)
    response_path.unlink(missing_ok=True)
    raise RuntimeError("worker returned no fifo response")


def _send_json(root: Path, payload: Dict[str, object], timeout_s: float = 2.0) -> Dict[str, object]:
    if _transport() == "fifo":
        return _send_json_fifo(root, payload, timeout_s=timeout_s)
    return _send_json_unix_line(_socket_path(root), payload, timeout_s=timeout_s)


def _ping(root: Path, timeout_s: float = 1.0) -> bool:
    transport = _transport()
    target = _request_fifo_path(root) if transport == "fifo" else _socket_path(root)
    if not target.exists():
        return False
    try:
        reply = _send_json(root, {"command": "ping"}, timeout_s=timeout_s)
    except Exception:
        return False
    return bool(reply.get("ok"))


def _read_code_stamp(root: Path) -> str:
    try:
        return _code_stamp_path(root).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_code_stamp(root: Path) -> None:
    stamp = _local_answer_code_stamp(root)
    if not stamp:
        return
    _code_stamp_path(root).write_text(stamp, encoding="utf-8")


def _stop_pid(pid: Optional[int]) -> None:
    if pid is None or pid <= 0 or not _pid_alive(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.05)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return


class ShellWorker:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.proc: Optional[subprocess.Popen[str]] = None
        self.log_handle = None

    def start(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            return
        log_path = _log_path(self.root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_handle = log_path.open("a", encoding="utf-8")
        env = dict(os.environ)
        env["LUCY_ROOT"] = str(self.root)
        env["LUCY_LOCAL_WORKER_ACTIVE"] = "1"
        self.proc = subprocess.Popen(
            [str(self.root / "tools" / "local_answer.sh"), "--worker-stdio"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log_handle,
            text=True,
            cwd=str(self.root),
            env=env,
            bufsize=1,
        )

    def stop(self) -> None:
        if self.proc is None:
            return
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.proc = None
        if self.log_handle is not None:
            self.log_handle.close()
            self.log_handle = None

    def request(
        self,
        question: str,
        env_overrides: Dict[str, str],
        env_shell_script: str = "",
    ) -> Dict[str, object]:
        self.start()
        if self.proc is None or self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("worker subprocess unavailable")
        request_env = dict(os.environ)
        request_env.update(env_overrides)
        request_started = time.monotonic()
        message_lines = ["BEGIN"]
        if env_shell_script:
            encoded_shell = base64.b64encode(env_shell_script.encode("utf-8")).decode("ascii")
            message_lines.append(f"ENV_SHELL\t{encoded_shell}")
        else:
            valid_keys = sorted(key for key in env_overrides if key and key.replace("_", "").isalnum() and key.upper() == key)
            if valid_keys:
                shell_lines = [f"LOCAL_ANSWER_WORKER_ENV_KEYS={shlex.quote(' '.join(valid_keys))}"]
                for key in valid_keys:
                    shell_lines.append(f"export {key}={shlex.quote(env_overrides[key])}")
                encoded_shell = base64.b64encode("\n".join(shell_lines).encode("utf-8")).decode("ascii")
                message_lines.append(f"ENV_SHELL\t{encoded_shell}")
        question_b64 = base64.b64encode(question.encode("utf-8")).decode("ascii")
        message_lines.append(f"QUESTION\t{question_b64}")
        message_lines.append("END")
        dispatch_started = time.monotonic()
        self.proc.stdin.write("\n".join(message_lines) + "\n")
        self.proc.stdin.flush()
        _append_latency_from_env("worker_dispatch_write", max(1, int(round((time.monotonic() - dispatch_started) * 1000))), env=request_env)

        rc = 1
        output = ""
        in_response = False
        wait_started = time.monotonic()
        while True:
            line = self.proc.stdout.readline()
            if line == "":
                raise RuntimeError("worker subprocess closed unexpectedly")
            line = line.rstrip("\n")
            if line == "BEGIN_RESPONSE":
                in_response = True
                continue
            if line == "END_RESPONSE":
                if in_response:
                    _append_latency_from_env("worker_response_wait", max(1, int(round((time.monotonic() - wait_started) * 1000))), env=request_env)
                    _append_latency_from_env("worker_request_total", max(1, int(round((time.monotonic() - request_started) * 1000))), env=request_env)
                    return {"rc": rc, "output": output}
                continue
            if not in_response:
                continue
            if line.startswith("RC\t"):
                try:
                    rc = int(line.split("\t", 1)[1])
                except ValueError:
                    rc = 1
            elif line.startswith("OUTPUT\t"):
                encoded = line.split("\t", 1)[1]
                try:
                    output = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                except Exception:
                    output = ""


def _serve(root: Path) -> int:
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    pid_path = _pid_path(root)
    worker = ShellWorker(root)
    worker.start()
    _write_code_stamp(root)

    stop_flag = {"value": False}

    def _handle_signal(_signum, _frame) -> None:
        stop_flag["value"] = True

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    transport = _transport()
    sock_path = _socket_path(root)
    request_fifo = _request_fifo_path(root)
    if sock_path.exists():
        sock_path.unlink()
    if request_fifo.exists():
        request_fifo.unlink()

    def build_reply(payload: Dict[str, object]) -> Dict[str, object]:
        command = str(payload.get("command") or "request")
        if command == "ping":
            return {"ok": True, "pid": os.getpid(), "transport": transport}
        if command == "status":
            return {
                "ok": True,
                "pid": os.getpid(),
                "socket": str(sock_path) if transport == "unix" else "",
                "request_fifo": str(request_fifo) if transport == "fifo" else "",
                "transport": transport,
            }
        if command == "request":
            question = str(payload.get("question") or "")
            env_overrides = payload.get("env") or {}
            if not isinstance(env_overrides, dict):
                env_overrides = {}
            normalized_env = {str(k): str(v) for k, v in env_overrides.items()}
            env_shell_script = str(payload.get("env_shell") or "")
            handle_started = time.monotonic()
            try:
                worker_reply = worker.request(question, normalized_env, env_shell_script=env_shell_script)
                _append_latency_from_env(
                    "server_handle_total",
                    max(1, int(round((time.monotonic() - handle_started) * 1000))),
                    env=normalized_env,
                )
                return {
                    "ok": worker_reply.get("rc", 1) == 0,
                    "rc": int(worker_reply.get("rc", 1)),
                    "output": str(worker_reply.get("output") or ""),
                    "transport": transport,
                }
            except Exception as exc:
                worker.stop()
                _append_latency_from_env(
                    "server_handle_total",
                    max(1, int(round((time.monotonic() - handle_started) * 1000))),
                    env=normalized_env,
                )
                return {"ok": False, "error": f"worker_request_failed:{exc}", "transport": transport}
        return {"ok": False, "error": "unsupported_command", "transport": transport}

    if transport == "fifo":
        os.mkfifo(request_fifo, 0o600)
        request_fd = os.open(str(request_fifo), os.O_RDWR | os.O_NONBLOCK)
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        last_activity = time.monotonic()
        idle_timeout_s = _idle_timeout_s()
        buffer = ""
        frame_lines = []
        in_frame = False
        while not stop_flag["value"]:
            if time.monotonic() - last_activity > idle_timeout_s:
                break
            ready, _, _ = select.select([request_fd], [], [], 1.0)
            if not ready:
                continue
            chunk = os.read(request_fd, 4096)
            if not chunk:
                continue
            buffer += chunk.decode("utf-8")
            while "\n" in buffer:
                raw, buffer = buffer.split("\n", 1)
                if raw == "BEGIN_REQUEST":
                    frame_lines = []
                    in_frame = True
                    continue
                if raw == "END_REQUEST":
                    payload: Dict[str, object] = {"env": {}}
                    for line in frame_lines:
                        if line.startswith("RESPONSE\t"):
                            payload["response_path"] = line.split("\t", 1)[1]
                        elif line.startswith("COMMAND\t"):
                            payload["command"] = line.split("\t", 1)[1]
                        elif line.startswith("QUESTION\t"):
                            encoded = line.split("\t", 1)[1]
                            payload["question"] = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                        elif line.startswith("ENV_SHELL\t"):
                            encoded = line.split("\t", 1)[1]
                            payload["env_shell"] = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                        elif line.startswith("ENV\t"):
                            _prefix, key, encoded = line.split("\t", 2)
                            env_map = payload.setdefault("env", {})
                            if isinstance(env_map, dict):
                                env_map[key] = base64.b64decode(encoded.encode("ascii")).decode("utf-8")
                    last_activity = time.monotonic()
                    reply = build_reply(payload)
                    response_path = str(payload.get("response_path") or "")
                    if response_path:
                        response_lines = [
                            "BEGIN_RESPONSE",
                            f"OK\t{1 if reply.get('ok') else 0}",
                            f"RC\t{int(reply.get('rc', 0) or 0)}",
                            f"PID\t{reply.get('pid', os.getpid())}",
                            f"TRANSPORT\t{reply.get('transport', transport)}",
                        ]
                        if reply.get("socket") is not None:
                            response_lines.append(f"SOCKET\t{reply.get('socket')}")
                        if reply.get("request_fifo") is not None:
                            response_lines.append(f"REQUEST_FIFO\t{reply.get('request_fifo')}")
                        if "output" in reply:
                            encoded_out = base64.b64encode(str(reply.get("output") or "").encode("utf-8")).decode("ascii")
                            response_lines.append(f"OUTPUT\t{encoded_out}")
                        if "error" in reply:
                            encoded_err = base64.b64encode(str(reply.get("error") or "").encode("utf-8")).decode("ascii")
                            response_lines.append(f"ERROR\t{encoded_err}")
                        response_lines.append("END_RESPONSE")
                        with open(response_path, "w", encoding="utf-8") as handle:
                            handle.write("\n".join(response_lines) + "\n")
                    frame_lines = []
                    in_frame = False
                    continue
                if in_frame:
                    frame_lines.append(raw)
        os.close(request_fd)
    else:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(sock_path))
            server.listen(8)
            server.settimeout(1.0)
            pid_path.write_text(str(os.getpid()), encoding="utf-8")
            last_activity = time.monotonic()
            idle_timeout_s = _idle_timeout_s()
            while not stop_flag["value"]:
                if time.monotonic() - last_activity > idle_timeout_s:
                    break
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    last_activity = time.monotonic()
                    data = b""
                    while b"\n" not in data:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    if not data:
                        continue
                    raw = data.split(b"\n", 1)[0]
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except Exception:
                        reply = {"ok": False, "error": "invalid_json", "transport": transport}
                    else:
                        reply = build_reply(payload)
                    conn.sendall(json.dumps(reply, separators=(",", ":")).encode("utf-8") + b"\n")
    worker.stop()
    try:
        sock_path.unlink()
    except FileNotFoundError:
        pass
    try:
        request_fifo.unlink()
    except FileNotFoundError:
        pass
    try:
        pid_path.unlink()
    except FileNotFoundError:
        pass
    try:
        _code_stamp_path(root).unlink()
    except FileNotFoundError:
        pass
    return 0


def _ensure(root: Path) -> int:
    run_dir = _run_dir(root)
    run_dir.mkdir(parents=True, exist_ok=True)
    sock_path = _socket_path(root)
    request_fifo = _request_fifo_path(root)
    pid_path = _pid_path(root)
    lock_path = _lock_path(root)
    expected_code_stamp = _local_answer_code_stamp(root)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        current_pid = _read_pid(pid_path)
        code_matches = bool(expected_code_stamp) and _read_code_stamp(root) == expected_code_stamp
        if _ping(root) and code_matches:
            return 0
        if current_pid is not None and _pid_alive(current_pid):
            _stop_pid(current_pid)
        pid = _read_pid(pid_path)
        if pid is not None and not _pid_alive(pid):
            try:
                pid_path.unlink()
            except FileNotFoundError:
                pass
        if sock_path.exists():
            try:
                sock_path.unlink()
            except OSError:
                pass
        if request_fifo.exists():
            try:
                request_fifo.unlink()
            except OSError:
                pass
        try:
            _code_stamp_path(root).unlink()
        except FileNotFoundError:
            pass
        env = dict(os.environ)
        env["LUCY_ROOT"] = str(root)
        log_path = _log_path(root)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as log_handle:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), "serve"],
                cwd=str(root),
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=log_handle,
                start_new_session=True,
            )
        deadline = time.monotonic() + _startup_timeout_s()
        while time.monotonic() < deadline:
            if _ping(root, timeout_s=0.25):
                return 0
            time.sleep(0.05)
    return 1


def _status(root: Path) -> int:
    sock_path = _socket_path(root)
    request_fifo = _request_fifo_path(root)
    pid_path = _pid_path(root)
    payload = {
        "running": False,
        "pid": _read_pid(pid_path),
        "socket": str(sock_path),
        "request_fifo": str(request_fifo),
        "transport": _transport(),
    }
    if _ping(root):
        payload["running"] = True
        try:
            payload.update(_send_json(root, {"command": "status"}, timeout_s=0.5))
        except Exception:
            pass
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0


def _stop(root: Path) -> int:
    sock_path = _socket_path(root)
    request_fifo = _request_fifo_path(root)
    pid_path = _pid_path(root)
    pid = _read_pid(pid_path)
    if pid is not None and _pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and _pid_alive(pid):
            time.sleep(0.05)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
    if sock_path.exists():
        try:
            sock_path.unlink()
        except OSError:
            pass
    if request_fifo.exists():
        try:
            request_fifo.unlink()
        except OSError:
            pass
    if pid_path.exists():
        try:
            pid_path.unlink()
        except OSError:
            pass
    return 0


def _request(root: Path, question: str) -> int:
    request_env = _request_env_overrides()
    serialize_started = time.monotonic()
    env_shell = _env_shell_from_overrides(request_env)
    _append_latency_from_env(
        "request_serialize",
        max(1, int(round((time.monotonic() - serialize_started) * 1000))),
        env=request_env,
    )
    setup_started = time.monotonic()
    if not _ping(root):
        auto_start = (os.environ.get("LUCY_LOCAL_WORKER_AUTO_START") or "1").strip().lower()
        if auto_start in {"1", "true", "yes", "on"}:
            if _ensure(root) != 0:
                return 1
        elif not _ping(root):
            return 1
    _append_latency_from_env(
        "request_setup",
        max(1, int(round((time.monotonic() - setup_started) * 1000))),
        env=request_env,
    )
    started = time.monotonic()
    try:
        reply = _send_json(
            root,
            {
                "command": "request",
                "question": question,
                "env": request_env,
                "env_shell": env_shell,
                "request_mode": _request_mode(),
            },
            timeout_s=180.0,
        )
    except Exception:
        return 1
    elapsed_ms = max(1, int(round((time.monotonic() - started) * 1000)))
    _append_latency_from_env("request_roundtrip", elapsed_ms, env=request_env)
    _append_latency_from_env("client_roundtrip", elapsed_ms, env=request_env)
    if not reply.get("ok"):
        return int(reply.get("rc") or 1)
    sys.stdout.write(str(reply.get("output") or ""))
    if str(reply.get("output") or "").endswith("\n"):
        return 0
    sys.stdout.write("\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("serve")
    sub.add_parser("ensure")
    sub.add_parser("status")
    sub.add_parser("stop")
    req = sub.add_parser("request")
    req.add_argument("--question", required=True)

    args = parser.parse_args()
    root = _root()
    if args.command == "serve":
        return _serve(root)
    if args.command == "ensure":
        return _ensure(root)
    if args.command == "status":
        return _status(root)
    if args.command == "stop":
        return _stop(root)
    if args.command == "request":
        return _request(root, args.question)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
