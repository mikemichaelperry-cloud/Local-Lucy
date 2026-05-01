#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pty
import select
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime_control import enforce_authority_contract, iso_now, locked_state_file


DEFAULT_START_TIMEOUT_SECONDS = 8.0
DEFAULT_STOP_TIMEOUT_SECONDS = 10.0
DEFAULT_ACTION_TIMEOUT_SECONDS = 15.0


class RuntimeLifecycleError(RuntimeError):
    pass


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        enforce_authority_contract(expected_authority_root=Path(__file__).resolve().parents[1])
        if args.command == "__serve":
            serve_runtime(args)
            return 0

        lifecycle_file = resolve_lifecycle_file(args.lifecycle_file)
        if args.command == "start":
            payload = start_runtime(
                lifecycle_file=lifecycle_file,
                launcher_path=resolve_launcher_path(args.launcher_path),
                log_file=resolve_log_file(args.log_file),
            )
            print(json.dumps(payload, sort_keys=True))
            return 0 if payload["status"] == "running" else 1
        if args.command == "stop":
            payload = stop_runtime(lifecycle_file)
            print(json.dumps(payload, sort_keys=True))
            return 0 if payload["status"] == "stopped" else 1
        if args.command == "status":
            payload = reconcile_lifecycle_state(lifecycle_file)
            print(json.dumps(payload, sort_keys=True))
            return 0
        raise RuntimeLifecycleError(f"unsupported command: {args.command}")
    except RuntimeLifecycleError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Authoritative Local Lucy runtime lifecycle endpoints.",
    )
    parser.add_argument(
        "--lifecycle-file",
        help="Override the authoritative lifecycle state file path.",
    )
    parser.add_argument(
        "--launcher-path",
        help="Override the managed launcher path.",
    )
    parser.add_argument(
        "--log-file",
        help="Override the managed lifecycle log file path.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    subparsers.add_parser("__serve")
    return parser


def resolve_lifecycle_file(explicit_path: str | None) -> Path:
    raw = explicit_path or os.environ.get("LUCY_RUNTIME_LIFECYCLE_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "state" / "runtime_lifecycle.json"


def resolve_launcher_path(explicit_path: str | None) -> Path:
    if explicit_path:
        return Path(explicit_path).expanduser()
    env_path = os.environ.get("LUCY_RUNTIME_LAUNCHER_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return Path(__file__).with_name("start_local_lucy_v8.sh")


def resolve_log_file(explicit_path: str | None) -> Path:
    raw = explicit_path or os.environ.get("LUCY_RUNTIME_LIFECYCLE_LOG_FILE")
    if raw:
        return Path(raw).expanduser()
    return default_runtime_namespace_root() / "logs" / "runtime_lifecycle.log"


def default_runtime_namespace_root() -> Path:
    explicit_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser()
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


DEFAULT_LIFECYCLE_FILE = str(default_runtime_namespace_root() / "state" / "runtime_lifecycle.json")
DEFAULT_LOG_FILE = str(default_runtime_namespace_root() / "logs" / "runtime_lifecycle.log")


def default_lifecycle_state() -> dict[str, Any]:
    return {
        "running": False,
        "pid": None,
        "runner_pid": None,
        "status": "stopped",
        "started_at": "",
        "stopped_at": "",
        "last_error": "",
        "heartbeat_at": "",
        "version": 1,
    }


def _kill_orphaned_processes(payload: dict[str, Any]) -> None:
    """Kill any orphaned launcher or runner processes from a crashed session."""
    for key in ("pid", "runner_pid"):
        pid = _coerce_pid(payload.get(key))
        if pid is not None and _process_alive(pid):
            try:
                os.kill(pid, signal.SIGTERM)
                time.sleep(0.5)
                if _process_alive(pid):
                    os.kill(pid, signal.SIGKILL)
            except (OSError, ProcessLookupError):
                pass


def _is_stale_state(payload: dict[str, Any], max_age_seconds: float = 30.0) -> bool:
    """Check if a 'running' state is stale (no recent heartbeat)."""
    if not bool(payload.get("running")):
        return False
    heartbeat = payload.get("heartbeat_at", "")
    if not heartbeat:
        return True
    try:
        heartbeat_time = datetime.fromisoformat(heartbeat.replace("Z", "+00:00")).timestamp()
        return (time.time() - heartbeat_time) > max_age_seconds
    except (ValueError, TypeError):
        return True


def start_runtime(*, lifecycle_file: Path, launcher_path: Path, log_file: Path) -> dict[str, Any]:
    lifecycle_file.parent.mkdir(parents=True, exist_ok=True)
    current = reconcile_lifecycle_state(lifecycle_file)
    
    # Handle stale or orphaned states
    if bool(current.get("running")):
        if _is_stale_state(current):
            # Stale state - kill orphaned processes and reset
            _kill_orphaned_processes(current)
            current = default_lifecycle_state()
            current["stopped_at"] = iso_now()
            current["last_error"] = "recovered from stale state"
            persist_lifecycle_state(lifecycle_file, current)
        else:
            return current
    
    if not launcher_path.exists():
        update = default_lifecycle_state()
        update["last_error"] = f"missing launcher: {launcher_path}"
        persist_lifecycle_state(lifecycle_file, update)
        raise RuntimeLifecycleError(update["last_error"])

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--lifecycle-file",
        str(lifecycle_file),
        "--launcher-path",
        str(launcher_path),
        "--log-file",
        str(log_file),
        "__serve",
    ]
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
        start_new_session=True,
        close_fds=True,
    )

    deadline = time.time() + DEFAULT_START_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(0.1)
        payload = read_lifecycle_state(lifecycle_file)
        if bool(payload.get("running")) and _process_alive(payload.get("runner_pid")):
            return payload
        if payload.get("last_error") and not bool(payload.get("running")):
            return payload

    payload = reconcile_lifecycle_state(lifecycle_file)
    if bool(payload.get("running")):
        return payload
    payload["last_error"] = payload.get("last_error") or "start timeout waiting for lifecycle truth"
    persist_lifecycle_state(lifecycle_file, payload)
    return payload


def stop_runtime(lifecycle_file: Path) -> dict[str, Any]:
    payload = reconcile_lifecycle_state(lifecycle_file)
    runner_pid = _coerce_pid(payload.get("runner_pid"))
    child_pid = _coerce_pid(payload.get("pid"))
    if not bool(payload.get("running")) or runner_pid is None:
        stopped = default_lifecycle_state()
        stopped["stopped_at"] = payload.get("stopped_at") or iso_now()
        persist_lifecycle_state(lifecycle_file, stopped)
        return stopped

    for target_pid in (runner_pid, child_pid):
        if target_pid is None:
            continue
        try:
            os.kill(target_pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except OSError as exc:
            payload["last_error"] = f"stop failed for pid {target_pid}: {exc}"
            persist_lifecycle_state(lifecycle_file, payload)
            return payload

    deadline = time.time() + DEFAULT_STOP_TIMEOUT_SECONDS
    while time.time() < deadline:
        time.sleep(0.1)
        payload = reconcile_lifecycle_state(lifecycle_file)
        if not bool(payload.get("running")):
            return payload

    timed_out = reconcile_lifecycle_state(lifecycle_file)
    timed_out["last_error"] = "stop timeout waiting for lifecycle truth"
    persist_lifecycle_state(lifecycle_file, timed_out)
    return timed_out


def reconcile_lifecycle_state(lifecycle_file: Path) -> dict[str, Any]:
    payload = read_lifecycle_state(lifecycle_file)
    runner_pid = _coerce_pid(payload.get("runner_pid"))
    child_pid = _coerce_pid(payload.get("pid"))

    if payload.get("running") and runner_pid is not None and _process_alive(runner_pid):
        # Also check heartbeat for stale detection
        if not _is_stale_state(payload, max_age_seconds=60.0):
            if child_pid is None or _process_alive(child_pid):
                payload["status"] = "running"
                persist_lifecycle_state(lifecycle_file, payload)
                return payload

    if payload.get("running"):
        # Process died or stale - clean up
        _kill_orphaned_processes(payload)
        payload["running"] = False
        payload["pid"] = None
        payload["runner_pid"] = None
        payload["status"] = "stopped"
        payload["stopped_at"] = payload.get("stopped_at") or iso_now()
        payload["last_error"] = payload.get("last_error") or "managed runtime is not active"
        persist_lifecycle_state(lifecycle_file, payload)
    return payload


def serve_runtime(args: argparse.Namespace) -> None:
    lifecycle_file = resolve_lifecycle_file(args.lifecycle_file)
    launcher_path = resolve_launcher_path(args.launcher_path)
    log_file = resolve_log_file(args.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    master_fd, slave_fd = pty.openpty()
    child: subprocess.Popen[str] | None = None
    stopping = False

    def handle_stop_signal(signum: int, frame: Any) -> None:
        del signum, frame
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            try:
                child.terminate()
            except OSError:
                pass

    signal.signal(signal.SIGTERM, handle_stop_signal)
    signal.signal(signal.SIGINT, handle_stop_signal)

    try:
        with open(log_file, "ab", buffering=0) as log_handle:
            env = os.environ.copy()
            env.setdefault("LUCY_RUNTIME_CONTROL_FORCE", "1")
            child = subprocess.Popen(
                [str(launcher_path)],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                shell=False,
                start_new_session=True,
                close_fds=True,
                cwd=str(launcher_path.parent.parent),
                env=env,
                text=False,
            )
            os.close(slave_fd)
            slave_fd = -1

            state = default_lifecycle_state()
            state["running"] = True
            state["pid"] = child.pid
            state["runner_pid"] = os.getpid()
            state["status"] = "running"
            state["started_at"] = iso_now()
            state["stopped_at"] = ""
            state["last_error"] = ""
            state["log_file"] = str(log_file)
            state["launcher_path"] = str(launcher_path)
            state["heartbeat_at"] = iso_now()
            persist_lifecycle_state(lifecycle_file, state)

            last_heartbeat = time.time()
            while True:
                if child.poll() is not None:
                    break
                
                # Update heartbeat every 5 seconds
                if time.time() - last_heartbeat >= 5.0:
                    try:
                        current_state = read_lifecycle_state(lifecycle_file)
                        if current_state.get("runner_pid") == os.getpid():
                            current_state["heartbeat_at"] = iso_now()
                            persist_lifecycle_state(lifecycle_file, current_state)
                        last_heartbeat = time.time()
                    except Exception:
                        pass
                
                readable, _, _ = select.select([master_fd], [], [], 0.25)
                if master_fd in readable:
                    try:
                        chunk = os.read(master_fd, 4096)
                    except OSError:
                        chunk = b""
                    if chunk:
                        log_handle.write(chunk)
                if stopping and child.poll() is None:
                    try:
                        child.terminate()
                    except OSError:
                        pass

            rc = child.wait(timeout=2)
            while True:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                log_handle.write(chunk)

            final_state = read_lifecycle_state(lifecycle_file)
            final_state["running"] = False
            final_state["pid"] = None
            final_state["runner_pid"] = None
            final_state["status"] = "stopped" if rc == 0 or stopping else "failed"
            final_state["stopped_at"] = iso_now()
            if rc != 0 and not stopping:
                final_state["last_error"] = f"launcher exited rc={rc}"
            persist_lifecycle_state(lifecycle_file, final_state)
    except Exception as exc:
        failed = read_lifecycle_state(lifecycle_file)
        failed["running"] = False
        failed["pid"] = None
        failed["runner_pid"] = None
        failed["status"] = "failed"
        failed["stopped_at"] = iso_now()
        failed["last_error"] = str(exc)
        persist_lifecycle_state(lifecycle_file, failed)
        raise
    finally:
        if slave_fd >= 0:
            os.close(slave_fd)
        try:
            os.close(master_fd)
        except OSError:
            pass


def read_lifecycle_state(lifecycle_file: Path) -> dict[str, Any]:
    if not lifecycle_file.exists():
        return default_lifecycle_state()
    try:
        payload = json.loads(lifecycle_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeLifecycleError(f"unable to read lifecycle state {lifecycle_file}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeLifecycleError(f"lifecycle state must contain a JSON object: {lifecycle_file}")
    normalized = default_lifecycle_state()
    normalized.update(payload)
    normalized["running"] = bool(normalized.get("running"))
    normalized["pid"] = _coerce_pid(normalized.get("pid"))
    normalized["runner_pid"] = _coerce_pid(normalized.get("runner_pid"))
    normalized["status"] = str(normalized.get("status") or "stopped").strip() or "stopped"
    normalized["started_at"] = str(normalized.get("started_at") or "").strip()
    normalized["stopped_at"] = str(normalized.get("stopped_at") or "").strip()
    normalized["last_error"] = str(normalized.get("last_error") or "").strip()
    return normalized


def persist_lifecycle_state(lifecycle_file: Path, payload: dict[str, Any]) -> None:
    lifecycle_file.parent.mkdir(parents=True, exist_ok=True)
    normalized = dict(default_lifecycle_state())
    normalized.update(payload)
    normalized["running"] = bool(normalized.get("running"))
    normalized["pid"] = _coerce_pid(normalized.get("pid"))
    normalized["runner_pid"] = _coerce_pid(normalized.get("runner_pid"))
    normalized["status"] = str(normalized.get("status") or "stopped").strip() or "stopped"
    normalized["started_at"] = str(normalized.get("started_at") or "").strip()
    normalized["stopped_at"] = str(normalized.get("stopped_at") or "").strip()
    normalized["last_error"] = str(normalized.get("last_error") or "").strip()

    with locked_state_file(lifecycle_file):
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=lifecycle_file.parent,
            delete=False,
            prefix=".runtime_lifecycle.",
            suffix=".tmp",
        ) as handle:
            json.dump(normalized, handle, indent=2, sort_keys=True)
            handle.write("\n")
            tmp_path = Path(handle.name)
        os.replace(tmp_path, lifecycle_file)


def _coerce_pid(value: Any) -> int | None:
    if value in {None, "", 0, "0"}:
        return None
    try:
        pid = int(str(value).strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _process_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


if __name__ == "__main__":
    sys.exit(main())
