from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class LogSnapshot:
    lines: list[str]
    active_paths: list[str]
    mode: str


@dataclass
class _FileCursor:
    offset: int = 0
    inode: int | None = None


class LogWatcher:
    def __init__(self, *, max_lines: int = 180, tail_bytes: int = 65536) -> None:
        self.max_lines = max_lines
        self.tail_bytes = tail_bytes
        runtime_namespace_root = Path(
            os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(_default_runtime_namespace_root()))
        ).expanduser()
        runtime_log_dir = Path(os.environ.get("LUCY_UI_LOG_DIR", str(runtime_namespace_root / "logs"))).expanduser()
        if _contract_required():
            _validate_within_namespace(runtime_log_dir, runtime_namespace_root, label="LUCY_UI_LOG_DIR")
        self.candidate_paths = [
            runtime_log_dir / "events.log",
            runtime_log_dir / "runtime.log",
            runtime_log_dir / "chat.log",
            runtime_log_dir / "stable_desktop.log",
        ]
        self._cursors: dict[Path, _FileCursor] = {path: _FileCursor() for path in self.candidate_paths}
        self._recent_lines_by_path: dict[Path, list[str]] = {}
        self._stopped = False

    def stop(self) -> None:
        """Stop the log watcher. No-op since LogWatcher is polling-based."""
        self._stopped = True

    def poll(self) -> LogSnapshot:
        active_paths: list[str] = []

        for path in self.candidate_paths:
            if not path.exists() or not path.is_file():
                self._recent_lines_by_path.pop(path, None)
                self._cursors[path] = _FileCursor()
                continue

            active_paths.append(str(path))
            entries = self._read_incremental(path)
            if entries is None:
                continue
            self._recent_lines_by_path[path] = entries[-self.max_lines :]

        combined_lines: list[str] = []
        for path in self.candidate_paths:
            lines = self._recent_lines_by_path.get(path)
            if not lines:
                continue
            combined_lines.extend(lines[-self.max_lines :])

        combined_lines = combined_lines[-self.max_lines :]

        if combined_lines:
            return LogSnapshot(lines=list(reversed(combined_lines)), active_paths=active_paths, mode="incremental-tail")

        return LogSnapshot(
            lines=[
                "18:44:00  event.source          no event source available",
                "18:44:01  watcher.mode          allowlisted tail watcher idle",
                "18:44:02  watcher.paths         checked version-local runtime log candidates",
            ],
            active_paths=active_paths,
            mode="incremental-tail",
        )

    def get_log_directory(self, active_paths: list[str] | None = None) -> Path:
        if active_paths:
            first_active = Path(active_paths[0]).expanduser()
            if first_active.parent.exists() and first_active.parent.is_dir():
                return first_active.parent

        for candidate in self.candidate_paths:
            directory = candidate.parent
            if directory.exists() and directory.is_dir():
                return directory

        return self.candidate_paths[0].parent

    def _read_incremental(self, path: Path) -> list[str] | None:
        try:
            stat = path.stat()
        except OSError:
            return None

        cursor = self._cursors[path]
        rotated = cursor.inode is not None and cursor.inode != stat.st_ino
        truncated = stat.st_size < cursor.offset
        first_read = cursor.offset == 0 or cursor.inode is None

        try:
            with path.open("rb") as handle:
                if first_read or rotated or truncated:
                    start = max(0, stat.st_size - self.tail_bytes)
                    handle.seek(start)
                    raw = handle.read()
                else:
                    handle.seek(cursor.offset)
                    raw = handle.read()
        except OSError:
            return None

        cursor.offset = stat.st_size
        cursor.inode = stat.st_ino

        decoded = raw.decode("utf-8", errors="replace")
        parsed = self._parse_lines(path, decoded.splitlines())

        if first_read or rotated or truncated:
            return parsed

        previous = self._recent_lines_by_path.get(path, [])
        combined = previous + parsed
        return combined[-self.max_lines :]

    def _parse_lines(self, path: Path, lines: list[str]) -> list[str]:
        parsed_lines: list[str] = []
        source = path.name

        for raw_line in lines:
            clean = _sanitize_line(raw_line)
            if not clean:
                continue

            if source == "chat.log":
                event_line = _parse_chat_log_line(clean, source)
            else:
                event_line = _parse_plain_log_line(clean, source)

            if event_line:
                parsed_lines.append(event_line)

        return parsed_lines[-self.max_lines :]


def _default_runtime_namespace_root() -> Path:
    if _contract_required():
        raw = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
        if not raw:
            raise RuntimeError(
                "missing required LUCY_RUNTIME_NAMESPACE_ROOT while LUCY_RUNTIME_CONTRACT_REQUIRED is active"
            )
        return Path(raw).expanduser()
    explicit_root = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
    if explicit_root:
        return Path(explicit_root).expanduser()
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    # V8 ISOLATION: Use v8 runtime namespace
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


def _contract_required() -> bool:
    raw = os.environ.get("LUCY_RUNTIME_CONTRACT_REQUIRED", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _validate_within_namespace(path: Path, namespace_root: Path, *, label: str) -> None:
    resolved_path = path.expanduser().resolve()
    resolved_root = namespace_root.expanduser().resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(
            f"{label} must be inside LUCY_RUNTIME_NAMESPACE_ROOT in strict mode: "
            f"{resolved_path} vs {resolved_root}"
        ) from exc


def _sanitize_line(line: str) -> str:
    cleaned = "".join(ch for ch in line if ch == "\t" or (" " <= ch <= "~"))
    cleaned = cleaned.strip()
    if not cleaned:
        return ""
    if cleaned.startswith("[?") or "[?2026h" in cleaned:
        return ""
    return cleaned


def _parse_chat_log_line(line: str, source: str) -> str | None:
    if not line.startswith("{"):
        return _parse_plain_log_line(line, source)

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return _parse_plain_log_line(line, source)

    if not isinstance(payload, dict):
        return None

    ts_value = payload.get("ts")
    mode_value = payload.get("mode")
    latency_value = payload.get("latency_s")
    user_value = str(payload.get("user", "")).strip()
    output_value = str(payload.get("output", "")).strip()

    stamp = _format_timestamp(ts_value) if isinstance(ts_value, (int, float)) else "recent"
    level = _classify_level(user_value or output_value)
    summary = user_value if user_value else output_value
    summary = _truncate(summary.replace("\n", " "), 120)

    details: list[str] = []
    if mode_value:
        details.append(f"mode={mode_value}")
    if isinstance(latency_value, (int, float)):
        details.append(f"latency={latency_value:.3f}s")
    if summary:
        details.append(summary)

    if not details:
        return None

    return f"{stamp}  [{level:<7}] {source:<18} " + " | ".join(details)


def _parse_plain_log_line(line: str, source: str) -> str | None:
    lower = line.lower()
    if line.startswith("==="):
        return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"
    if line.startswith("ts="):
        return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"
    if line.startswith("Model:") or line.startswith("Started:") or line.startswith("launcher="):
        return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"
    if line.startswith("workdir=") or line.startswith("pwd_before=") or line.startswith("user=") or line.startswith("shell="):
        return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"
    if "error" in lower or "fail" in lower:
        return f"recent  [alarm  ] {source:<18} {_truncate(line, 120)}"
    if "warn" in lower:
        return f"recent  [warning] {source:<18} {_truncate(line, 120)}"
    if "info" in lower:
        return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"
    return f"recent  [info   ] {source:<18} {_truncate(line, 120)}"


def _classify_level(text: str) -> str:
    lower = text.lower()
    if "error" in lower or "fail" in lower:
        return "alarm"
    if "warn" in lower:
        return "warning"
    return "info"


def _truncate(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _format_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds).astimezone().strftime("%H:%M:%S")
