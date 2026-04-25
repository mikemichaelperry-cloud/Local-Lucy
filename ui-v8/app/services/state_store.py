from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileLoadResult:
    path: Path
    status: str
    data: dict[str, Any] | None


@dataclass(frozen=True)
class RuntimeSnapshot:
    top_status: dict[str, str]
    runtime_status: dict[str, str]
    voice_runtime: dict[str, Any]
    current_state: dict[str, Any]
    file_paths: dict[str, str]
    lifecycle_available: bool
    lifecycle_running: bool
    lifecycle_status: str
    lifecycle_pid: int | None
    snapshot_timestamp: str  # ISO format timestamp when snapshot was loaded
    legacy_namespace_detected: bool  # True if legacy runtime namespace exists
    legacy_namespace_path: str  # Path to legacy namespace if detected, empty otherwise
    gpu_info: dict[str, Any]  # GPU acceleration status for performance monitoring


@dataclass(frozen=True)
class HistoryLoadResult:
    path: Path
    status: str
    entries: list[dict[str, Any]]



def _default_runtime_namespace_root() -> Path:
    # Use environment variable if set, otherwise use same default as backend
    raw = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    
    # Match backend default from runtime_request.py
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8"


def _default_legacy_runtime_namespace_root() -> Path:
    home = Path.home()
    workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
    return workspace_home / "lucy" / "runtime-v8"


def _detect_legacy_namespace() -> tuple[bool, str]:
    """Detect if legacy runtime namespace exists and differs from current."""
    legacy = _default_legacy_runtime_namespace_root()
    current = RUNTIME_NAMESPACE_ROOT
    if legacy != current and legacy.exists() and legacy.is_dir():
        return True, str(legacy)
    return False, ""


def _detect_gpu_status() -> dict[str, Any]:
    """Detect GPU acceleration status for Ollama/local inference.
    
    Returns dict with:
    - available: bool - GPU is available and being used
    - type: str - 'nvidia', 'amd', 'none'
    - model: str - GPU model name
    - vram_used_mb: int - VRAM usage in MB
    - vram_total_mb: int - Total VRAM in MB
    - ollama_on_gpu: bool - Ollama is using GPU
    - model_loaded: bool - Any model is currently loaded in Ollama
    """
    result = {
        "available": False,
        "type": "none",
        "model": "",
        "vram_used_mb": 0,
        "vram_total_mb": 0,
        "ollama_on_gpu": False,
        "model_loaded": False,
    }
    
    # Check for NVIDIA GPU
    try:
        nvidia_smi = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if nvidia_smi.returncode == 0 and nvidia_smi.stdout.strip():
            lines = nvidia_smi.stdout.strip().split("\n")
            if lines:
                parts = lines[0].split(", ")
                if len(parts) >= 3:
                    result["type"] = "nvidia"
                    result["model"] = parts[0].strip()
                    result["vram_used_mb"] = int(float(parts[1].strip()))
                    result["vram_total_mb"] = int(float(parts[2].strip()))
                    result["available"] = True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    
    # Check for AMD GPU
    if not result["available"]:
        try:
            rocm_smi = subprocess.run(
                ["rocm-smi", "--showproductname"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
            if rocm_smi.returncode == 0 and "GPU" in rocm_smi.stdout:
                result["type"] = "amd"
                result["available"] = True
                # Try to extract model name
                for line in rocm_smi.stdout.split("\n"):
                    if "GPU" in line and ":" in line:
                        result["model"] = line.split(":")[-1].strip()
                        break
        except (OSError, subprocess.TimeoutExpired):
            pass
    
    # Check if Ollama is using GPU
    try:
        ollama_ps = subprocess.run(
            ["curl", "-s", "http://localhost:11434/api/ps"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if ollama_ps.returncode == 0 and ollama_ps.stdout.strip():
            data = json.loads(ollama_ps.stdout)
            if isinstance(data, dict) and "models" in data:
                models = data["models"]
                if models:
                    result["model_loaded"] = True
                    for model in models:
                        if isinstance(model, dict) and model.get("size_vram", 0) > 0:
                            result["ollama_on_gpu"] = True
                            break
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        pass
    
    return result


def _contract_required() -> bool:
    raw = os.environ.get("LUCY_RUNTIME_CONTRACT_REQUIRED", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _detect_router() -> str:
    """Detect which router is being used."""
    # Check environment variables that indicate Python router usage
    router_py = os.environ.get("LUCY_ROUTER_PY", "0")
    exec_py = os.environ.get("LUCY_EXEC_PY", "0")
    
    if router_py == "1" and exec_py == "1":
        return "Python"
    elif router_py == "1":
        return "Python-Router"
    else:
        return "Shell"


def _validate_within_namespace(path: Path, namespace_root: Path, *, label: str) -> Path:
    resolved_path = path.expanduser().resolve()
    resolved_root = namespace_root.expanduser().resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(
            f"{label} must be inside LUCY_RUNTIME_NAMESPACE_ROOT in strict mode: "
            f"{resolved_path} vs {resolved_root}"
        ) from exc
    return path


RUNTIME_NAMESPACE_ROOT = Path(
    os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", str(_default_runtime_namespace_root()))
).expanduser()
LEGACY_RUNTIME_NAMESPACE_ROOT = Path(
    os.environ.get("LUCY_LEGACY_RUNTIME_NAMESPACE_ROOT", str(_default_legacy_runtime_namespace_root()))
).expanduser()
STATE_DIRECTORY = Path(os.environ.get("LUCY_UI_STATE_DIR", str(RUNTIME_NAMESPACE_ROOT / "state"))).expanduser()
if _contract_required():
    _validate_within_namespace(STATE_DIRECTORY, RUNTIME_NAMESPACE_ROOT, label="LUCY_UI_STATE_DIR")
STATE_FILES = {
    "current_state": Path(os.environ.get("LUCY_RUNTIME_STATE_FILE", str(STATE_DIRECTORY / "current_state.json"))).expanduser(),
    "last_route": STATE_DIRECTORY / "last_route.json",
    "last_preprocess": STATE_DIRECTORY / "last_preprocess.json",
    "health": STATE_DIRECTORY / "health.json",
    "runtime_lifecycle": Path(
        os.environ.get("LUCY_RUNTIME_LIFECYCLE_FILE", str(STATE_DIRECTORY / "runtime_lifecycle.json"))
    ).expanduser(),
    "voice_runtime": Path(os.environ.get("LUCY_VOICE_RUNTIME_FILE", str(STATE_DIRECTORY / "voice_runtime.json"))).expanduser(),
}
REQUEST_RESULT_FILE = Path(
    os.environ.get("LUCY_RUNTIME_REQUEST_RESULT_FILE", str(STATE_DIRECTORY / "last_request_result.json"))
).expanduser()
REQUEST_HISTORY_FILE = Path(
    os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE", str(STATE_DIRECTORY / "request_history.jsonl"))
).expanduser()

if _contract_required():
    for key, path in STATE_FILES.items():
        _validate_within_namespace(path, RUNTIME_NAMESPACE_ROOT, label=f"STATE_FILES[{key}]")
    _validate_within_namespace(REQUEST_RESULT_FILE, RUNTIME_NAMESPACE_ROOT, label="LUCY_RUNTIME_REQUEST_RESULT_FILE")
    _validate_within_namespace(REQUEST_HISTORY_FILE, RUNTIME_NAMESPACE_ROOT, label="LUCY_RUNTIME_REQUEST_HISTORY_FILE")


def load_runtime_snapshot() -> RuntimeSnapshot:
    current_state = _load_json(STATE_FILES["current_state"])
    last_route = _load_json(STATE_FILES["last_route"])
    last_preprocess = _load_json(STATE_FILES["last_preprocess"])
    health = _load_json(STATE_FILES["health"])
    lifecycle = _load_json(STATE_FILES["runtime_lifecycle"])
    voice_runtime = _load_json(STATE_FILES["voice_runtime"])
    lifecycle_status = _resolve_value(lifecycle, (("status",),))
    lifecycle_running = _resolve_lifecycle_running(lifecycle)
    lifecycle_pid = _resolve_lifecycle_pid(lifecycle)
    voice_runtime_data = _normalize_voice_runtime(voice_runtime)

    top_status = {
        "Profile": _resolve_value(current_state, (("profile",), ("active_profile",))),
        "Mode": _resolve_value(current_state, (("mode",),)),
        "Router": _detect_router(),
        "Conversation": _resolve_value(current_state, (("conversation",),)),
        "Model": _resolve_value(current_state, (("model",), ("active_model",))),
        "Memory": _resolve_value(current_state, (("memory",), ("memory_enabled",))),
        "Evidence": _resolve_value(current_state, (("evidence",), ("evidence_enabled",))),
        "Voice": _resolve_value(current_state, (("voice",), ("voice_enabled",))),
        "Augmented Policy": _resolve_value(current_state, (("augmentation_policy",),)),
        "Augmented Provider": _resolve_value(current_state, (("augmented_provider",),)),
        "Selected Provider Paid": _resolve_selected_provider_paid(current_state),
        "Approval Required": _resolve_value(
            current_state,
            (("approval_required",),),
            label="approval_required",
        ),
        "Overall Status": _resolve_value(
            lifecycle,
            (("status",),),
            fallback_result=health,
            fallback_paths=(("overall_status",), ("status",)),
        ),
    }

    runtime_status = {
        "Current Route": _resolve_optional_value(last_route, (("route",), ("current_route",), ("route_reason",))),
        "Source Type": _resolve_optional_value(last_route, (("source_type",), ("source",))),
        "Conversation": _resolve_value(current_state, (("conversation",),)),
        "Answer Class": _resolve_optional_value(last_route, (("answer_class",),)),
        "Operator Trust": _resolve_optional_value(last_route, (("operator_trust_label",), ("trust_class",))),
        "Voice State": _resolve_voice_state(voice_runtime_data, voice_runtime.status),
        "Preprocess Active": _resolve_optional_value(last_preprocess, (("active",), ("preprocess_active",))),
        "Reduced Scope": _resolve_optional_value(last_preprocess, (("reduced_scope",),)),
        "Patch Surface Summary": _resolve_optional_value(last_preprocess, (("patch_surface_summary",),)),
        "Uncertainty / Underspecified": _resolve_optional_value(
            last_preprocess,
            (("underspecified",), ("uncertainty",), ("notes",)),
        ),
        "Voice Backend": _resolve_voice_backend(voice_runtime_data, voice_runtime.status),
        "Voice Error": _resolve_voice_error(voice_runtime_data, voice_runtime.status),
        "Augmented Policy": _resolve_value(current_state, (("augmentation_policy",),)),
        "Configured Provider": _resolve_value(current_state, (("augmented_provider",),)),
        "Configured Provider Paid": _resolve_selected_provider_paid(current_state),
        "Authority Root": _resolve_optional_value(last_route, (("authority", "active_root"), ("authority", "authority_root"))),
        "Runtime Namespace": _resolve_optional_value(last_route, (("authority", "runtime_namespace_root"),)),
        "Legacy Runtime Tree": _resolve_optional_value(last_route, (("authority", "legacy_runtime_namespace_status"),)),
        "Health": _format_lifecycle_summary(
            lifecycle_status=lifecycle_status,
            lifecycle_running=lifecycle_running,
            lifecycle_pid=lifecycle_pid,
            fallback=_resolve_value(health, (("health",), ("status",), ("overall_status",))),
        ),
    }

    snapshot_timestamp = datetime.now(timezone.utc).isoformat()
    legacy_detected, legacy_path = _detect_legacy_namespace()
    gpu_info = _detect_gpu_status()

    return RuntimeSnapshot(
        top_status=top_status,
        runtime_status=runtime_status,
        voice_runtime=voice_runtime_data,
        current_state=current_state.data if isinstance(current_state.data, dict) else {},
        file_paths={
            **{name: str(path) for name, path in STATE_FILES.items()},
            "last_request_result": str(REQUEST_RESULT_FILE),
            "request_history": str(REQUEST_HISTORY_FILE),
            "runtime_namespace_root": str(RUNTIME_NAMESPACE_ROOT),
            "legacy_runtime_namespace_root": str(LEGACY_RUNTIME_NAMESPACE_ROOT),
        },
        lifecycle_available=lifecycle.status == "ok",
        lifecycle_running=lifecycle_running,
        lifecycle_status=lifecycle_status,
        lifecycle_pid=lifecycle_pid,
        snapshot_timestamp=snapshot_timestamp,
        legacy_namespace_detected=legacy_detected,
        legacy_namespace_path=legacy_path,
        gpu_info=gpu_info,
    )


def get_state_directory() -> Path:
    # Fail loudly if state directory doesn't exist - no silent fallbacks
    if not STATE_DIRECTORY.exists():
        raise RuntimeError(
            f"state directory does not exist: {STATE_DIRECTORY}. "
            f"Ensure LUCY_RUNTIME_NAMESPACE_ROOT is set correctly."
        )
    return STATE_DIRECTORY


def load_last_request_result() -> FileLoadResult:
    return _load_json(REQUEST_RESULT_FILE)


def load_recent_request_history(max_entries: int = 24) -> HistoryLoadResult:
    path = REQUEST_HISTORY_FILE
    if not path.exists():
        return HistoryLoadResult(path=path, status="file missing", entries=[])

    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return HistoryLoadResult(path=path, status="unavailable", entries=[])

    entries: list[dict[str, Any]] = []
    invalid_lines = 0
    for raw_line in raw_lines[-max(max_entries * 2, max_entries):]:
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        if not isinstance(parsed, dict):
            invalid_lines += 1
            continue
        entries.append(parsed)

    status = "ok" if invalid_lines == 0 else "partial"
    if max_entries > 0:
        entries = entries[-max_entries:]
    return HistoryLoadResult(path=path, status=status, entries=entries)

def build_request_details(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    last_result = load_last_request_result()

    if entry is None:
        if last_result.status == "ok" and last_result.data is not None:
            return last_result.data
        return None

    if last_result.status == "ok" and last_result.data is not None:
        history_id = str(entry.get("request_id", "")).strip()
        result_id = str(last_result.data.get("request_id", "")).strip()
        if history_id and history_id == result_id:
            merged = dict(entry)
            control_state = last_result.data.get("control_state")
            if isinstance(control_state, dict):
                merged["control_state"] = control_state
            return merged

    return entry


def resolve_last_request_provider(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    outcome = payload.get("outcome")
    if not isinstance(outcome, dict):
        return "unknown"
    provider = _stringify(outcome.get("augmented_provider_used") or outcome.get("augmented_provider")).lower()
    if provider in {"openai", "kimi", "wikipedia", "none"}:
        return provider
    return "unknown"


def resolve_last_request_paid(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return "unknown"
    outcome = payload.get("outcome")
    if not isinstance(outcome, dict):
        return "unknown"
    paid_flag = _stringify(outcome.get("augmented_paid_provider_invoked")).lower()
    if paid_flag in {"true", "1", "yes"}:
        return "yes"
    if paid_flag in {"false", "0", "no"}:
        return "no"
    provider = resolve_last_request_provider(payload)
    if provider in {"wikipedia", "none"}:
        return "no"
    return "unknown"


def _load_json(path: Path) -> FileLoadResult:
    if not path.exists():
        return FileLoadResult(path=path, status="file missing", data=None)

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError:
        return FileLoadResult(path=path, status="unavailable", data=None)

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return FileLoadResult(path=path, status="invalid json", data=None)

    if not isinstance(parsed, dict):
        return FileLoadResult(path=path, status="unsupported json", data=None)

    return FileLoadResult(path=path, status="ok", data=parsed)


def _normalize_voice_runtime(result: FileLoadResult) -> dict[str, Any]:
    data = result.data if isinstance(result.data, dict) else {}
    return {
        "available": bool(data.get("available", False)),
        "listening": bool(data.get("listening", False)),
        "processing": bool(data.get("processing", False)),
        "status": _stringify(data.get("status") or result.status),
        "last_error": _stringify(data.get("last_error")) if data.get("last_error") else "",
        "last_updated": _stringify(data.get("last_updated")) if data.get("last_updated") else "",
        "recorder": _stringify(data.get("recorder")) if data.get("recorder") else "unknown",
        "stt": _stringify(data.get("stt")) if data.get("stt") else "unknown",
        "tts": _stringify(data.get("tts")) if data.get("tts") else "none",
        "tts_device": _stringify(data.get("tts_device")) if data.get("tts_device") else "none",
        "audio_player": _stringify(data.get("audio_player")) if data.get("audio_player") else "none",
    }


def _resolve_voice_state(voice_runtime: dict[str, Any], voice_status: str) -> str:
    if voice_status != "ok":
        return _present_optional_status(voice_status)
    status = str(voice_runtime.get("status", "unknown")).strip() or "unknown"
    available = bool(voice_runtime.get("available", False))
    if status == "idle" and available:
        return "idle / ready"
    return status


def _resolve_voice_backend(voice_runtime: dict[str, Any], voice_status: str) -> str:
    if voice_status != "ok":
        return _present_optional_status(voice_status)
    return ", ".join(
        [
            f"available={'yes' if voice_runtime.get('available') else 'no'}",
            f"recorder={voice_runtime.get('recorder', 'unknown')}",
            f"stt={voice_runtime.get('stt', 'unknown')}",
            f"tts={voice_runtime.get('tts', 'none')}",
            f"tts_device={voice_runtime.get('tts_device', 'none')}",
        ]
    )


def _resolve_voice_error(voice_runtime: dict[str, Any], voice_status: str) -> str:
    if voice_status != "ok":
        return _present_optional_status(voice_status)
    detail = str(voice_runtime.get("last_error", "")).strip()
    return detail or "none"


def _resolve_selected_provider_paid(current_state: FileLoadResult) -> str:
    provider_value = _lookup_candidate_paths(current_state.data, (("augmented_provider",),))
    if provider_value is None:
        if current_state.status != "ok":
            return current_state.status
        return "unknown"
    provider = _stringify(provider_value).lower()
    if provider in {"openai", "kimi"}:
        return "yes"
    if provider == "wikipedia":
        return "no"
    return "unknown"


def _resolve_value(
    result: FileLoadResult,
    candidate_paths: tuple[tuple[str, ...], ...],
    *,
    fallback_result: FileLoadResult | None = None,
    fallback_paths: tuple[tuple[str, ...], ...] = (),
    label: str | None = None,
) -> str:
    value = _lookup_candidate_paths(result.data, candidate_paths)
    if value is not None:
        return _stringify(value, label=label)

    if fallback_result is not None:
        fallback_value = _lookup_candidate_paths(fallback_result.data, fallback_paths)
        if fallback_value is not None:
            return _stringify(fallback_value, label=label)

    if result.status != "ok":
        return result.status
    return "unknown"


def _resolve_optional_value(
    result: FileLoadResult,
    candidate_paths: tuple[tuple[str, ...], ...],
) -> str:
    value = _lookup_candidate_paths(result.data, candidate_paths)
    if value is not None:
        return _stringify(value)
    if result.status != "ok":
        return _present_optional_status(result.status)
    return "not yet populated"


def _lookup_candidate_paths(
    data: dict[str, Any] | None,
    candidate_paths: tuple[tuple[str, ...], ...],
) -> Any:
    if data is None:
        return None

    for candidate_path in candidate_paths:
        current: Any = data
        found = True
        for key in candidate_path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                found = False
                break
        if found:
            return current
    return None


def _stringify(value: Any, *, label: str | None = None) -> str:
    if isinstance(value, bool):
        if label == "approval_required":
            return "required" if value else "not required"
        return "true" if value else "false"
    if value is None:
        return "unknown"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) if value else "unknown"
    if isinstance(value, dict):
        parts = [f"{key}={value[key]}" for key in sorted(value)]
        return ", ".join(parts) if parts else "unknown"
    text = str(value).strip()
    return text if text else "unknown"


def _resolve_lifecycle_running(result: FileLoadResult) -> bool:
    if result.status != "ok" or not isinstance(result.data, dict):
        return False
    return bool(result.data.get("running"))


def _resolve_lifecycle_pid(result: FileLoadResult) -> int | None:
    if result.status != "ok" or not isinstance(result.data, dict):
        return None
    raw = result.data.get("pid")
    if raw in {None, "", 0, "0"}:
        return None
    try:
        pid = int(str(raw).strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _format_lifecycle_summary(
    *,
    lifecycle_status: str,
    lifecycle_running: bool,
    lifecycle_pid: int | None,
    fallback: str,
) -> str:
    if lifecycle_status in {"file missing", "unavailable", "invalid json", "unsupported json"}:
        return fallback
    parts = [
        f"status={lifecycle_status or 'unknown'}",
        f"running={'true' if lifecycle_running else 'false'}",
    ]
    if lifecycle_pid is not None:
        parts.append(f"pid={lifecycle_pid}")
    return ", ".join(parts)


def _present_optional_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"file missing", "unavailable"}:
        return "not yet populated"
    return status
