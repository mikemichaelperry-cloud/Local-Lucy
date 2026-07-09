from __future__ import annotations

# ROLE: PERMITTED GLOBAL CONTROL-PLANE EXCEPTION
# This HMI bridge intentionally lives in the shared UI tree outside any single
# snapshot. Runtime authority remains pinned to snapshot-local backend tools.

import contextlib
import fcntl
import importlib
import io
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv may be absent in minimal installs
    load_dotenv = None  # type: ignore[assignment,misc]


@dataclass(frozen=True)
class ActionCapability:
    name: str
    available: bool
    allowed_values: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class CommandResult:
    action: str
    requested_value: str | None
    status: str
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    payload: dict[str, Any] | None


class RuntimeActionTaskSignals(QObject):
    finished = Signal(object)


class RuntimeActionTask(QRunnable):
    def __init__(
        self,
        bridge: "RuntimeBridge",
        action: str,
        requested_value: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._bridge = bridge
        self._action = action
        self._requested_value = requested_value
        self._context = context
        self.signals = RuntimeActionTaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._bridge.run_action(
                self._action, self._requested_value, context=self._context
            )
        except Exception as exc:  # pragma: no cover - defensive UI worker guard
            result = CommandResult(
                action=self._action,
                requested_value=self._requested_value,
                status="failed",
                returncode=None,
                stdout="",
                stderr=f"unexpected worker error: {exc}",
                timed_out=False,
                payload=None,
            )
        self.signals.finished.emit(result)


class RuntimeBridge:
    def __init__(self) -> None:
        self.control_timeout_seconds = 5
        self.profile_timeout_seconds = 5
        self.lifecycle_timeout_seconds = 15
        self.request_timeout_seconds = 125
        self.voice_status_timeout_seconds = 5
        self.voice_start_timeout_seconds = 5
        self.voice_stop_timeout_seconds = 300  # Must accommodate: transcription + backend request (125s) + TTS + overhead. Increased to 300s for long news digests
        self.authority_root_env = "LUCY_RUNTIME_AUTHORITY_ROOT"
        self.ui_root_env = "LUCY_UI_ROOT"
        self.runtime_namespace_env = "LUCY_RUNTIME_NAMESPACE_ROOT"
        self.contract_required_env = "LUCY_RUNTIME_CONTRACT_REQUIRED"
        self._load_project_dotenv()
        self._enforce_authority_contract()
        self.snapshot_root = self._resolve_snapshot_root()
        self.control_tool_path = self.snapshot_root / "tools" / "runtime_control.py"
        self.profile_tool_path = self.snapshot_root / "tools" / "runtime_profile.py"
        self.lifecycle_tool_path = self.snapshot_root / "tools" / "runtime_lifecycle.py"
        self.request_tool_path = self.snapshot_root / "tools" / "runtime_request.py"
        self.voice_tool_path = self.snapshot_root / "tools" / "runtime_voice.py"
        self.memory_tool_path = self.snapshot_root / "tools" / "memory" / "memory_service.py"
        self.voice_python_bin = self._resolve_voice_python_hint()
        self.capabilities = self._discover_capabilities()
        self.profile_capability = self._discover_profile_capability()
        self.lifecycle_capability = self._discover_lifecycle_capability()
        self.request_capability = self._discover_request_capability()
        self.voice_capability = self._discover_voice_capability()
        self._last_used_model: str | None = None
        self._prime_voice_state()
        threading.Thread(target=self._background_warmup_ollama, daemon=True).start()
        threading.Thread(target=self._background_warmup_router, daemon=True).start()

    def _load_project_dotenv(self) -> None:
        """Load lucy-v10/.env so API keys are available to HMI subprocesses.

        Existing environment variables take precedence. This is a safety net
        for users who start the HMI directly instead of via START_LUCY.sh.
        """
        if load_dotenv is None:
            return
        authority_root = os.environ.get(self.authority_root_env, "").strip()
        if authority_root:
            candidates = [Path(authority_root).expanduser().resolve()]
        else:
            candidates = [
                Path(__file__).resolve().parents[3],
            ]
        for root in candidates:
            env_path = root / ".env"
            if env_path.exists():
                load_dotenv(env_path, override=False)
                break

    def _workspace_root(self) -> Path:
        # When authority root is the project root (e.g., /home/mike/lucy-v10),
        # the workspace root is the same directory.
        return self.snapshot_root

    def _contract_required(self) -> bool:
        raw = (os.environ.get(self.contract_required_env) or "").strip().lower()
        if raw in {"0", "false", "no", "off"}:
            return False
        return True

    def _enforce_authority_contract(self) -> None:
        if not self._contract_required():
            return
        missing: list[str] = []
        authority_raw = (os.environ.get(self.authority_root_env) or "").strip()
        ui_root_raw = (os.environ.get(self.ui_root_env) or "").strip()
        runtime_ns_raw = (os.environ.get(self.runtime_namespace_env) or "").strip()
        if not authority_raw:
            missing.append(self.authority_root_env)
        if not ui_root_raw:
            missing.append(self.ui_root_env)
        if not runtime_ns_raw:
            missing.append(self.runtime_namespace_env)
        if missing:
            raise RuntimeError(f"missing required authority contract env(s): {', '.join(missing)}")

        authority_root = Path(authority_raw).expanduser().resolve()
        ui_root = Path(ui_root_raw).expanduser().resolve()
        runtime_ns_root = Path(runtime_ns_raw).expanduser().resolve()
        bridge_file = Path(__file__).resolve()
        if ui_root.name != "ui-v10" or not ui_root.exists() or not ui_root.is_dir():
            raise RuntimeError(f"invalid UI root in authority contract: {ui_root}")
        if authority_root.name not in ("lucy-v10",):
            raise RuntimeError(f"invalid authority root in authority contract: {authority_root}")
        if not runtime_ns_root.is_absolute():
            raise RuntimeError(
                f"invalid runtime namespace root in authority contract: {runtime_ns_root}"
            )
        try:
            bridge_file.relative_to(ui_root)
        except ValueError as exc:
            raise RuntimeError(
                f"runtime bridge path mismatch: bridge={bridge_file} ui_root={ui_root}"
            ) from exc

    def _resolve_voice_python_hint(self) -> str:
        explicit = (os.environ.get("LUCY_VOICE_PYTHON_BIN") or "").strip()
        if explicit:
            return explicit

        candidates = [
            self._workspace_root() / "ui-v10" / ".venv" / "bin" / "python3",
        ]
        # Direct Python probe (avoids subprocess hop); failure is non-fatal.
        try:
            with self._runtime_env():
                tts_adapter = self._import_tool("voice.tts_adapter")
                payload = tts_adapter.probe_backend(requested_engine="kokoro")
            if (
                isinstance(payload, dict)
                and payload.get("ok")
                and payload.get("engine") == "kokoro"
            ):
                for candidate in candidates:
                    if candidate.exists() and candidate.is_file():
                        return str(candidate)
        except Exception:
            pass
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        return ""

    def _command_env(self, *, include_voice_python: bool = False) -> dict[str, str]:
        """Build command environment with Python router settings."""
        env = os.environ.copy()
        # Pin the authority/namespace contract so backend tools resolve the same
        # paths even if the spawned process sanitizes its environment.
        env.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", str(self.snapshot_root))
        env.setdefault("LUCY_UI_ROOT", os.environ.get(self.ui_root_env, ""))
        env.setdefault(
            "LUCY_RUNTIME_NAMESPACE_ROOT", os.environ.get(self.runtime_namespace_env, "")
        )
        env.setdefault(
            "LUCY_RUNTIME_CONTRACT_REQUIRED", os.environ.get(self.contract_required_env, "1")
        )
        if include_voice_python and self.voice_python_bin:
            env.setdefault("LUCY_VOICE_PYTHON_BIN", self.voice_python_bin)
        # Always include Python router settings so they're propagated to subprocesses
        # These are only active when LUCY_ROUTER_PY=1
        env.setdefault("LUCY_ROUTER_PY", os.environ.get("LUCY_ROUTER_PY", "0"))
        env.setdefault(
            "LUCY_ROUTER_PY_PERCENTAGE", os.environ.get("LUCY_ROUTER_PY_PERCENTAGE", "0")
        )
        env.setdefault(
            "LUCY_ROUTER_PY_DETERMINISTIC", os.environ.get("LUCY_ROUTER_PY_DETERMINISTIC", "true")
        )
        env.setdefault(
            "LUCY_ROUTER_PY_EMERGENCY_KILL", os.environ.get("LUCY_ROUTER_PY_EMERGENCY_KILL", "0")
        )
        # Python Voice Pipeline toggle (V8)
        # Set LUCY_VOICE_PY=1 to use Python-native voice pipeline instead of shell
        env.setdefault("LUCY_VOICE_PY", os.environ.get("LUCY_VOICE_PY", "0"))
        # Propagate evidence/control settings from HMI to voice subprocesses
        env.setdefault("LUCY_EVIDENCE_ENABLED", os.environ.get("LUCY_EVIDENCE_ENABLED", "0"))
        env.setdefault(
            "LUCY_AUGMENTATION_POLICY", os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
        )
        env.setdefault(
            "LUCY_CONVERSATION_MODE_FORCE", os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "0")
        )
        env.setdefault("LUCY_SESSION_MEMORY", os.environ.get("LUCY_SESSION_MEMORY", "0"))
        env.setdefault("LUCY_AUGMENTED_PROVIDER", self._resolve_augmented_provider())
        # Propagate model selection so subprocess paths match direct-Python path
        env.setdefault("LUCY_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31"))
        env.setdefault("LUCY_LOCAL_MODEL", os.environ.get("LUCY_LOCAL_MODEL", "local-lucy-llama31"))
        # Ollama model used by the memory service for summarization/embedding fallback
        env.setdefault(
            "LUCY_OLLAMA_MODEL",
            os.environ.get("LUCY_OLLAMA_MODEL", os.environ.get("LUCY_MODEL", "local-lucy-llama31")),
        )
        # Router decision logging — default to project logs directory
        default_log_dir = str(Path(__file__).resolve().parents[3] / "logs" / "router")
        env.setdefault(
            "LUCY_ROUTER_LOG_DIR", os.environ.get("LUCY_ROUTER_LOG_DIR", default_log_dir)
        )
        return env

    def _import_tool(self, module_name: str) -> Any:
        """Lazily import a module from the snapshot tools directory.

        Imports happen inside methods so that modules which set global state or
        run side effects at import time do not affect HMI startup.
        """
        tools_path = str(self.snapshot_root / "tools")
        if tools_path not in sys.path:
            sys.path.insert(0, tools_path)
        return importlib.import_module(module_name)

    @contextlib.contextmanager
    def _runtime_env(self, *, include_voice_python: bool = False) -> Iterator[None]:
        """Apply the same environment defaults used for subprocess calls.

        Only adds missing keys so the current process env is not overwritten.
        Keys are left in place after the call to avoid thread races and because
        they represent global runtime defaults that direct calls should see.
        """
        env = self._command_env(include_voice_python=include_voice_python)
        for key, value in env.items():
            os.environ.setdefault(key, value)
        yield

    def _resolve_snapshot_root(self) -> Path:
        override = (os.environ.get(self.authority_root_env) or "").strip()
        if override:
            return Path(override).expanduser().resolve()
        # Always fail loudly - no silent fallbacks allowed
        raise RuntimeError(
            f"missing required {self.authority_root_env}. "
            f"Set it explicitly to the project root (e.g., /home/mike/lucy-v10)"
        )

    def _discover_capabilities(self) -> dict[str, ActionCapability]:
        available = self.control_tool_path.exists() and self.control_tool_path.is_file()
        reason = (
            f"Live: authoritative runtime control via {self.control_tool_path}"
            if available
            else f"Unavailable: missing backend control tool {self.control_tool_path}"
        )

        return {
            "mode_selection": ActionCapability(
                name="mode_selection",
                available=available,
                allowed_values=("auto", "online", "offline"),
                reason=reason,
            ),
            "conversation_toggle": ActionCapability(
                name="conversation_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
            "memory_toggle": ActionCapability(
                name="memory_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
            "evidence_toggle": ActionCapability(
                name="evidence_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
            "voice_toggle": ActionCapability(
                name="voice_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
            "augmentation_policy": ActionCapability(
                name="augmentation_policy",
                available=available,
                allowed_values=("disabled", "fallback_only", "direct_allowed"),
                reason=reason,
            ),
            "augmented_provider": ActionCapability(
                name="augmented_provider",
                available=available,
                allowed_values=("wikipedia", "openai", "kimi"),
                reason=reason,
            ),
            "model_selection": ActionCapability(
                name="model_selection",
                available=available,
                allowed_values=(
                    "auto",
                    "local-lucy-llama31",
                    "local-lucy",
                    "local-lucy-fast",
                    "local-lucy-mistral",
                ),
                reason=reason,
            ),
            "learner_toggle": ActionCapability(
                name="learner_toggle",
                available=available,
                allowed_values=("on", "off"),
                reason=reason,
            ),
        }

    def _discover_request_capability(self) -> ActionCapability:
        available = self.request_tool_path.exists() and self.request_tool_path.is_file()
        reason = (
            f"Live: authoritative runtime submit via {self.request_tool_path}"
            if available
            else f"Unavailable: missing backend request tool {self.request_tool_path}"
        )
        return ActionCapability(
            name="submit_request",
            available=available,
            allowed_values=(),
            reason=reason,
        )

    def _discover_profile_capability(self) -> ActionCapability:
        available = self.profile_tool_path.exists() and self.profile_tool_path.is_file()
        reason = (
            f"Live: authoritative profile defaults reset via {self.profile_tool_path}"
            if available
            else f"Unavailable: missing backend profile tool {self.profile_tool_path}"
        )
        return ActionCapability(
            name="profile_reload",
            available=available,
            allowed_values=(),
            reason=reason,
        )

    def _discover_lifecycle_capability(self) -> ActionCapability:
        available = self.lifecycle_tool_path.exists() and self.lifecycle_tool_path.is_file()
        reason = (
            f"Live: authoritative runtime lifecycle via {self.lifecycle_tool_path}"
            if available
            else f"Unavailable: missing backend lifecycle tool {self.lifecycle_tool_path}"
        )
        return ActionCapability(
            name="lifecycle_controls",
            available=available,
            allowed_values=("start", "stop"),
            reason=reason,
        )

    def _discover_voice_capability(self) -> ActionCapability:
        available = self.voice_tool_path.exists() and self.voice_tool_path.is_file()
        reason = (
            f"Live: authoritative voice PTT via {self.voice_tool_path}"
            if available
            else f"Unavailable: missing backend voice tool {self.voice_tool_path}"
        )
        return ActionCapability(
            name="voice_ptt",
            available=available,
            allowed_values=("start", "stop"),
            reason=reason,
        )

    def capability_notes(self) -> dict[str, str]:
        mode_note = self.capabilities["mode_selection"].reason
        feature_note = self.capabilities["memory_toggle"].reason
        return {
            "mode_selection": mode_note,
            "feature_toggles": feature_note,
            "lifecycle_controls": self.lifecycle_capability.reason,
            "profile_reload": self.profile_capability.reason,
            "voice_ptt": self.voice_capability.reason,
        }

    def request_available(self) -> bool:
        return self.request_capability.available

    def profile_available(self) -> bool:
        return self.profile_capability.available

    def lifecycle_available(self) -> bool:
        return self.lifecycle_capability.available

    def voice_available(self) -> bool:
        return self.voice_capability.available

    def run_action(
        self, action: str, requested_value: str, *, context: dict[str, Any] | None = None
    ) -> CommandResult:
        if action == "submit_request":
            return self._run_submit_request(
                requested_value, action=action, augmented_direct_once=False, context=context
            )
        if action == "submit_request_force_augmented_once":
            return self._run_submit_request(
                requested_value, action=action, augmented_direct_once=True, context=context
            )
        if action == "submit_self_review_request":
            return self._run_submit_request(
                requested_value,
                action=action,
                augmented_direct_once=False,
                self_review=True,
                context=context,
            )
        if action == "reload_profile":
            return self._run_profile_action(action)
        if action in {"runtime_start", "runtime_stop"}:
            return self._run_lifecycle_action(action, requested_value)
        if action in {"voice_ptt_start", "voice_ptt_stop", "voice_status"}:
            return self._run_voice_action(action, requested_value)
        if action == "speak":
            return self._run_speak_action(requested_value)
        if action == "persona_clear":
            return self._run_clear_persona_action()
        if action == "persona_set":
            return self._run_set_persona_action(requested_value)

        capability = self.capabilities.get(action)
        if capability is None:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr="unknown action",
                timed_out=False,
                payload=None,
            )

        if not capability.available:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=capability.reason,
                timed_out=False,
                payload=None,
            )

        if requested_value not in capability.allowed_values:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=f"invalid value '{requested_value}' for {action}",
                timed_out=False,
                payload=None,
            )

        return self._run_control_action_direct(action, requested_value)

    _CONTROL_ACTION_MAP: dict[str, tuple[str, str]] = {
        "mode_selection": ("set-mode", "mode"),
        "conversation_toggle": ("set-conversation", "conversation"),
        "memory_toggle": ("set-memory", "memory"),
        "evidence_toggle": ("set-evidence", "evidence"),
        "voice_toggle": ("set-voice", "voice"),
        "augmentation_policy": ("set-augmentation", "augmentation_policy"),
        "augmented_provider": ("set-augmented-provider", "augmented_provider"),
        "model_selection": ("set-model", "model"),
        "learner_toggle": ("set-learner", "learner"),
    }

    def _run_control_action_direct(self, action: str, requested_value: str) -> CommandResult:
        command_name, field = self._CONTROL_ACTION_MAP[action]
        try:
            with self._runtime_env():
                runtime_control = self._import_tool("runtime_control")
                state_file = runtime_control.resolve_runtime_paths(None).state_file
                if action == "learner_toggle":
                    result = runtime_control.update_learner_state(state_file, requested_value)
                else:
                    result = runtime_control.update_state_field(state_file, field, requested_value)
                payload: dict[str, Any] = {
                    "ok": True,
                    "action": command_name,
                    "field": result.field,
                    "value": result.value,
                    "changed": result.changed,
                    "state_file": str(state_file),
                    "state": result.state,
                }
                stdout = json.dumps(payload, sort_keys=True)
        except Exception as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )

        if action == "model_selection":
            # Evict every other loaded model immediately so the user does not
            # see stale Ollama state. Warm up the selected model afterwards.
            if requested_value and requested_value.lower() != "auto":
                threading.Thread(
                    target=self._unload_other_ollama_models,
                    args=(requested_value,),
                    daemon=True,
                ).start()
            threading.Thread(
                target=self._warmup_ollama_model,
                args=(requested_value,),
                daemon=True,
            ).start()

        return CommandResult(
            action=action,
            requested_value=requested_value,
            status="ok",
            returncode=0,
            stdout=stdout,
            stderr="",
            timed_out=False,
            payload=payload,
        )

    def _run_profile_action(self, action: str) -> CommandResult:
        if not self.profile_capability.available:
            return CommandResult(
                action=action,
                requested_value="",
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=self.profile_capability.reason,
                timed_out=False,
                payload=None,
            )

        try:
            with self._runtime_env():
                runtime_profile = self._import_tool("runtime_profile")
                state_file = runtime_profile.resolve_state_file(None)
                payload = runtime_profile.reload_profile_state(state_file)
                stdout = json.dumps(payload, sort_keys=True)
        except Exception as exc:
            return CommandResult(
                action=action,
                requested_value="",
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )

        return CommandResult(
            action=action,
            requested_value="",
            status="ok",
            returncode=0,
            stdout=stdout,
            stderr="",
            timed_out=False,
            payload=payload,
        )

    def _prime_voice_state(self) -> None:
        if not self.voice_capability.available:
            return
        try:
            # Check voice status (fast, keep synchronous)
            with self._runtime_env(include_voice_python=True):
                runtime_voice = self._import_tool("runtime_voice")
                runtime_file = runtime_voice.resolve_voice_runtime_file(None)
                state_file = runtime_voice.resolve_state_file(None)
                if runtime_voice.use_python_voice():
                    runtime_voice.handle_status_python()
                else:
                    runtime_voice.sync_voice_runtime(runtime_file, state_file)
        except Exception:
            return
        # Background prewarm voice workers so UI startup isn't blocked
        threading.Thread(target=self._background_prewarm_voice, daemon=True).start()

    def _background_warmup_ollama(self) -> None:
        """Send a dummy prompt to Ollama to pre-load the model and reduce first-token latency."""
        model = self._resolve_current_model()
        self._warmup_ollama_model(model)

    def _warmup_ollama_model(self, model: str) -> None:
        """Send a lightweight generate request to load the given model into Ollama.

        This is used both at startup and after a model switch so the HMI's
        active-model probe reflects the newly selected model as quickly as
        possible instead of lingering on the previously loaded model.
        """
        api_url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
        keep_alive = os.environ.get("LUCY_LOCAL_KEEP_ALIVE", "10m")
        body = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_predict": 0},
        }
        try:
            request = urllib.request.Request(
                api_url,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=60.0) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

    def _unload_ollama_model(self, model: str) -> None:
        """Unload a model from Ollama to free VRAM before loading another.

        Uses the Ollama HTTP API (keep_alive=0), then polls /api/ps briefly to
        confirm the model is gone. Failures are ignored — the model may already
        be unloaded or Ollama may not be running.
        """
        if not model or model.lower() == "auto":
            return

        api_url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434")

        # Primary: generate request with keep_alive=0. Some Ollama versions
        # unload more reliably via the API, especially while a model is busy.
        body = {
            "model": model,
            "prompt": "",
            "stream": False,
            "keep_alive": 0,
            "options": {"num_predict": 0},
        }
        try:
            request = urllib.request.Request(
                f"{api_url}/api/generate",
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=15.0) as response:
                response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            pass

        # Verify: poll /api/ps for a few seconds until the model disappears.
        # This prevents the HMI from reporting stale loaded state.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{api_url}/api/ps", timeout=5.0) as response:
                    data = json.loads(response.read().decode("utf-8"))
                still_loaded = any(
                    self._is_same_ollama_model(
                        model, entry.get("name", "") or entry.get("model", "")
                    )
                    for entry in data.get("models", [])
                )
                if not still_loaded:
                    return
            except Exception:
                return
            time.sleep(0.5)

    @staticmethod
    def _is_same_ollama_model(a: str, b: str) -> bool:
        """Compare two Ollama model names tolerating ':latest' and similar tags."""
        if not a or not b:
            return False
        a_norm = a.strip().lower()
        b_norm = b.strip().lower()
        if a_norm == b_norm:
            return True
        # Strip ':latest' and compare base names.
        a_base = a_norm.split(":")[0]
        b_base = b_norm.split(":")[0]
        return a_base == b_base or b_norm.startswith(a_norm + ":")

    def _unload_other_ollama_models(self, keep_model: str) -> None:
        """Query Ollama for loaded models and unload any that are not *keep_model*."""
        if not keep_model or keep_model.lower() == "auto":
            return
        api_url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434")
        try:
            with urllib.request.urlopen(f"{api_url}/api/ps", timeout=5.0) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception:
            return
        for entry in data.get("models", []):
            name = entry.get("name", "") or entry.get("model", "")
            if not name:
                continue
            if self._is_same_ollama_model(keep_model, name):
                continue
            self._unload_ollama_model(name)

    def _background_warmup_router(self) -> None:
        """Eagerly load the embedding router (ModernBERT) so first query isn't penalized.

        On a cold start the router can take ~4s to load tokenizer, model, and
        embeddings.  By prewarming in a background thread during UI startup, the
        first user query gets the fast (~30ms) path.
        """
        try:
            tools_dir = self.snapshot_root / "tools"
            if str(tools_dir) not in sys.path:
                sys.path.insert(0, str(tools_dir))
            from router_py.classify import prewarm_router

            prewarm_router()
        except Exception:
            pass

    def _background_prewarm_voice(self) -> None:
        """Prewarm TTS and STT workers in the background to eliminate cold-start latency."""
        try:
            with self._runtime_env(include_voice_python=True):
                runtime_voice = self._import_tool("runtime_voice")
                runtime_file = runtime_voice.resolve_voice_runtime_file(None)
                state_file = runtime_voice.resolve_state_file(None)

                # Prewarm Kokoro TTS worker (~2s on cold start)
                try:
                    backend = runtime_voice.detect_backend()
                    if backend.tts_engine == "kokoro":
                        runtime_voice.prewarm_kokoro_worker()
                        # Update voice runtime state so UI reflects the detected TTS backend
                        if backend.tts_engine != "none":
                            try:
                                with runtime_voice.locked_state_file(runtime_file):
                                    runtime_state = runtime_voice.load_voice_runtime_locked(
                                        runtime_file
                                    )
                                    runtime_state["tts"] = backend.tts_engine
                                    runtime_state["tts_device"] = backend.tts_device
                                    runtime_state["audio_player"] = backend.audio_player
                                    runtime_state["last_updated"] = runtime_voice.iso_now()
                                    runtime_voice.write_voice_runtime(runtime_file, runtime_state)
                            except Exception:
                                pass
                except Exception:
                    pass

                # Prewarm Whisper STT server (~3-5s on cold start for CPU mode)
                try:
                    backend = runtime_voice.detect_backend(include_tts=False)
                    ensure_whisper_worker = getattr(runtime_voice, "ensure_whisper_worker", None)
                    if (
                        ensure_whisper_worker is not None
                        and backend.stt_engine == "whisper"
                        and backend.available
                    ):
                        model_path = runtime_voice.resolve_whisper_model_path()
                        ensure_whisper_worker(model_path)
                except Exception:
                    pass
        except Exception:
            pass

    def _run_submit_request(
        self,
        requested_value: str,
        *,
        action: str,
        augmented_direct_once: bool,
        self_review: bool = False,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """
        Submit a request to the backend.

        Phase 3: Direct Python execution only (flattened chain).
        Bypasses subprocess hops for better performance and reliability.

        Previous: runtime_bridge → runtime_request.py → lucy_chat.sh → hybrid_wrapper.sh → main.py
        Current:  runtime_bridge → ExecutionEngine (direct Python call)
        """
        return self._run_submit_request_direct(
            requested_value,
            action=action,
            augmented_direct_once=augmented_direct_once,
            self_review=self_review,
            context=context,
        )

    def _extract_payload(self, stdout: str | None) -> dict[str, Any] | None:
        text = (stdout or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _run_submit_request_direct(
        self,
        requested_value: str,
        *,
        action: str,
        augmented_direct_once: bool,
        self_review: bool = False,
        context: dict[str, Any] | None = None,
    ) -> CommandResult:
        """
        Direct Python execution path via main.py — unified entry point.

        Before: runtime_bridge → ExecutionEngine (direct, bypassed main.py)
        After:  runtime_bridge → main.run() → ExecutionEngine

        This ensures all execution goes through the single entry point,
        preserving state resolution, feedback detection, locking, and telemetry.
        """
        request_text = requested_value if requested_value is not None else ""
        if not request_text.strip():
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr="empty submit text",
                timed_out=False,
                payload=None,
            )

        # Add router_py to path for imports
        router_py_path = str(self.snapshot_root / "tools")
        if router_py_path not in sys.path:
            sys.path.insert(0, router_py_path)

        try:
            from router_py.main import execute_plan_python
            from router_py.policy import normalize_augmentation_policy
        except ImportError as e:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=f"Direct execution import failed: {e}. Fallback to subprocess path.",
                timed_out=False,
                payload=None,
            )

        # Phase 3: shadow-mode automatic model selection.
        try:
            from router_py.model_selector import select_model, is_auto_model
            from router_py import metrics as router_metrics
        except Exception:
            select_model = None  # type: ignore[assignment]
            is_auto_model = None  # type: ignore[assignment]
            router_metrics = None  # type: ignore[assignment]

        manual_model = self._resolve_current_model()
        effective_model = manual_model
        recommendation: dict[str, Any] | None = None
        if select_model is not None:
            try:
                recommendation = select_model(
                    request_text,
                    route=None,
                    intent_family=None,
                    manual_model=manual_model,
                )
                if is_auto_model(manual_model):
                    effective_model = recommendation["recommended"]
            except Exception:
                recommendation = None

        # Phase 7: ensure only the model we are about to use stays loaded.
        # With only 12 GB VRAM there is no room for two models. Evict every
        # other loaded model whether the user selected manually or the Auto
        # selector chose a model. Skip only if we genuinely do not know which
        # model will be used.
        if effective_model and effective_model.lower() != "auto":
            self._unload_other_ollama_models(effective_model)

        # Get augmentation policy from environment
        policy = normalize_augmentation_policy(
            os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
        )

        start_time = os.times()[0]  # User CPU time

        try:
            # Call unified entry point directly (main.run() is a thin
            # pass-through; using execute_plan_python eliminates one
            # wrapper hop and aligns with the consolidated bridge).
            outcome = execute_plan_python(
                question=request_text,
                policy=policy,
                timeout=self.request_timeout_seconds,
                surface="hmi",
                augmented_direct_once=augmented_direct_once,
                self_review=self_review,
                context=context,
                model=effective_model,
            )

            # Calculate execution time
            execution_time_ms = int((os.times()[0] - start_time) * 1000)

            # Build payload directly from RouterOutcome — no reconstruction.
            # The HMI is a display layer only; it must reflect the core's
            # exact output without reinterpretation.
            payload = self._build_payload_from_outcome(
                outcome=outcome,
                request_text=request_text,
                execution_time_ms=execution_time_ms,
            )

            # Phase 3: expose the recommendation to the HMI and log shadow metrics.
            if recommendation is not None:
                payload["model_recommendation"] = recommendation["recommended"]
                payload["model_recommendation_reason"] = recommendation["reason"]
                if router_metrics is not None:
                    try:
                        router_metrics.record_model_selection_shadow(
                            request_id=outcome.request_id or "",
                            query=request_text,
                            route=outcome.route or "",
                            manual_model=manual_model,
                            recommended_model=recommendation["recommended"],
                            competing_model=recommendation["competing"],
                            reason=recommendation["reason"],
                            confidence=recommendation["confidence"],
                        )
                        router_metrics.record_model_latency(
                            request_id=outcome.request_id or "",
                            model=effective_model,
                            latency_ms=execution_time_ms,
                            extra={
                                "route": outcome.route,
                                "outcome_code": outcome.outcome_code,
                            },
                        )
                    except Exception:
                        pass

            # Phase 7: keep the most-likely-next model warm (non-blocking).
            # Use the selector's recommendation if available; otherwise warm the
            # model that just handled this request.
            if os.environ.get("LUCY_KEEP_MODEL_WARM", "1").lower() in (
                "1",
                "true",
                "yes",
                "on",
            ):
                warmup_model = recommendation["recommended"] if recommendation else effective_model
                threading.Thread(
                    target=self._warmup_ollama_model,
                    args=(warmup_model,),
                    daemon=True,
                ).start()

            # Track the model that was actually used so the next manual switch
            # can unload it. Skip tracking in Auto mode.
            if is_auto_model is not None and not is_auto_model(manual_model):
                self._last_used_model = effective_model

            # NOTE: We do NOT write history entries here.
            # The core ExecutionEngine's StateWriter already writes the
            # canonical entry to request_history.jsonl using the SAME
            # request_id. Dual writes caused duplicate entries and data
            # divergence (runtime_bridge used a different ID schema).
            # The HMI reads from that file via load_recent_request_history().

            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="ok" if outcome.status == "completed" else outcome.status,
                returncode=0 if outcome.status == "completed" else 1,
                stdout=outcome.response_text,
                stderr=outcome.error_message or "",
                timed_out=False,
                payload=payload,
            )

        except Exception as e:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=f"Direct execution failed: {e}",
                timed_out=False,
                payload=None,
            )

    def _build_payload_from_outcome(
        self,
        outcome: Any,
        request_text: str,
        execution_time_ms: int,
    ) -> dict[str, Any]:
        """
        Build JSON payload from RouterOutcome — faithful, no reinterpretation.

        The HMI is a display layer; it must show exactly what the core
        pipeline produced.  All fields are copied directly from the
        RouterOutcome dataclass.
        """
        # Use the core's request_id (propagated from main.py via pipeline)
        request_id = outcome.request_id or ""

        control_state = {
            "mode": os.environ.get("LUCY_MODE", "offline"),
            "conversation": os.environ.get("LUCY_CONVERSATION_MODE", "off"),
            "memory": os.environ.get("LUCY_SESSION_MEMORY", "1"),
            "evidence": os.environ.get("LUCY_EVIDENCE_ENABLED", "0"),
            "voice": os.environ.get("LUCY_VOICE_ENABLED", "0"),
            "augmentation_policy": os.environ.get("LUCY_AUGMENTATION_POLICY", "auto"),
            "augmented_provider": os.environ.get("LUCY_AUGMENTED_PROVIDER", "auto"),
            "model": os.environ.get("LUCY_MODEL", "local"),
            "profile": os.environ.get("LUCY_PROFILE", "default"),
        }

        is_augmented = (outcome.route or "") == "AUGMENTED"
        is_completed = (outcome.status or "") == "completed"
        meta = outcome.metadata or {}

        route_payload = {
            "mode": outcome.route or "LOCAL",
            "intent_family": outcome.intent_family or "unknown",
            "confidence": outcome.confidence or 0.0,
            "reason": outcome.evidence_reason or outcome.policy_reason or "unknown",
            "route_reason": outcome.policy_reason or "unknown",
            "evidence_reason": outcome.evidence_reason or "",
            "provider": outcome.provider or "local",
            "provider_usage_class": outcome.provider_usage_class or "local",
            "final_mode": outcome.route or "LOCAL",
            "is_medical": meta.get("is_medical_query", False),
        }

        outcome_payload = {
            "outcome_code": outcome.outcome_code or "completed",
            "fallback_used": "false" if is_completed else "true",
            "fallback_reason": outcome.error_message or "none",
            "trust_class": meta.get("trust_class", "local") or "local",
            "error_message": outcome.error_message or "",
            "execution_time_ms": execution_time_ms,
            "augmented_provider_used": outcome.provider if is_augmented else "none",
            "augmented_provider_usage_class": outcome.provider_usage_class or "local",
            "augmented_provider_call_reason": (
                "direct"
                if is_augmented and outcome.outcome_code == "augmented_answer"
                else "fallback"
                if is_augmented and outcome.outcome_code == "augmented_fallback"
                else "error"
                if is_augmented and not is_completed
                else "not_needed"
            ),
            "augmented_provider_status": (
                "available"
                if is_augmented and is_completed
                else "error"
                if is_augmented
                else "none"
            ),
            "augmented_paid_provider_invoked": (
                "true" if is_augmented and outcome.provider_usage_class == "paid" else "false"
            ),
            "augmented_direct_request": "",
        }

        return {
            "accepted": True,
            "authority": {
                "runtime_authority_root": str(self.snapshot_root),
                "ui_authority_root": str(self.snapshot_root),
            },
            "completed_at": self._iso_now(),
            "control_state": control_state,
            "error": outcome.error_message or "",
            "outcome": outcome_payload,
            "metadata": meta,
            "request_id": request_id,
            "request_text": request_text,
            "response_text": outcome.response_text,
            "route": route_payload,
            "status": "completed" if outcome.status == "completed" else outcome.status,
        }

    def _iso_now(self) -> str:
        """Return ISO format current timestamp."""
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _resolve_current_model(self) -> str:
        """Read the active model from runtime state file."""
        raw_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip()
        if raw_state_file:
            state_file = Path(raw_state_file).expanduser()
        else:
            namespace_root = Path(os.environ.get(self.runtime_namespace_env, "")).expanduser()
            if not namespace_root:
                return "auto"
            state_file = namespace_root / "state" / "current_state.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            return state.get("model") or state.get("active_model") or "auto"
        except (OSError, json.JSONDecodeError):
            return "auto"

    def _resolve_augmented_provider(self) -> str:
        """Read the active augmented provider from runtime state file."""
        raw_state_file = os.environ.get("LUCY_RUNTIME_STATE_FILE", "").strip()
        if raw_state_file:
            state_file = Path(raw_state_file).expanduser()
        else:
            namespace_root = Path(os.environ.get(self.runtime_namespace_env, "")).expanduser()
            if not namespace_root:
                return os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")
            state_file = namespace_root / "state" / "current_state.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            return state.get("augmented_provider") or os.environ.get(
                "LUCY_AUGMENTED_PROVIDER", "auto"
            )
        except (OSError, json.JSONDecodeError):
            return os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")

    def _resolve_history_file(self) -> Path:
        """Resolve the history file path (same logic as runtime_request.py)."""
        raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE")
        if raw:
            return Path(raw).expanduser()
        # Default path matching runtime_request.py
        home = Path.home()
        workspace_home = (
            home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        )
        return (
            workspace_home
            / ".codex-api-home"
            / "lucy"
            / "runtime-v10"
            / "state"
            / "request_history.jsonl"
        )

    def _run_lifecycle_action(self, action: str, requested_value: str) -> CommandResult:
        expected_value = "start" if action == "runtime_start" else "stop"
        if requested_value != expected_value:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=f"invalid value '{requested_value}' for {action}",
                timed_out=False,
                payload=None,
            )

        if not self.lifecycle_capability.available:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=self.lifecycle_capability.reason,
                timed_out=False,
                payload=None,
            )

        try:
            with self._runtime_env():
                runtime_lifecycle = self._import_tool("runtime_lifecycle")
                lifecycle_file = runtime_lifecycle.resolve_lifecycle_file(None)
                if expected_value == "start":
                    payload = runtime_lifecycle.start_runtime(
                        lifecycle_file=lifecycle_file,
                        launcher_path=runtime_lifecycle.resolve_launcher_path(None),
                        log_file=runtime_lifecycle.resolve_log_file(None),
                    )
                else:
                    payload = runtime_lifecycle.stop_runtime(lifecycle_file)
                stdout = json.dumps(payload, sort_keys=True)
                returncode = 0 if payload.get("status") in {"running", "stopped"} else 1
        except Exception as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )

        status = "ok" if returncode == 0 else "failed"
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status=status,
            returncode=returncode,
            stdout=stdout,
            stderr="",
            timed_out=False,
            payload=payload,
        )

    def _run_voice_action(self, action: str, requested_value: str) -> CommandResult:
        command_name = {
            "voice_status": "status",
            "voice_ptt_start": "ptt-start",
            "voice_ptt_stop": "ptt-stop",
        }.get(action, "")
        if not command_name:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=f"unknown voice action {action}",
                timed_out=False,
                payload=None,
            )

        if not self.voice_capability.available:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=self.voice_capability.reason,
                timed_out=False,
                payload=None,
            )

        try:
            with self._runtime_env(include_voice_python=True):
                runtime_voice = self._import_tool("runtime_voice")
                RuntimeVoiceExit = runtime_voice.RuntimeVoiceExit
                runtime_file = runtime_voice.resolve_voice_runtime_file(None)
                state_file = runtime_voice.resolve_state_file(None)
                capture_dir = runtime_voice.resolve_capture_directory(None)

                if action == "voice_status":
                    if runtime_voice.use_python_voice():
                        payload = runtime_voice.handle_status_python()
                    else:
                        payload = runtime_voice.sync_voice_runtime(runtime_file, state_file)
                elif action == "voice_ptt_start":
                    if runtime_voice.use_python_voice():
                        payload = runtime_voice.handle_ptt_start_python(
                            runtime_file, state_file, capture_dir
                        )
                    else:
                        payload = runtime_voice.handle_ptt_start(
                            runtime_file, state_file, capture_dir
                        )
                elif action == "voice_ptt_stop":
                    if runtime_voice.use_python_voice():
                        payload = runtime_voice.handle_ptt_stop_python(
                            runtime_file, state_file, capture_dir
                        )
                    else:
                        payload = runtime_voice.handle_ptt_stop(
                            runtime_file, state_file, capture_dir
                        )
                else:
                    payload = {}

                stdout = json.dumps(payload, sort_keys=True)
                stderr = ""
                returncode = 0
        except RuntimeVoiceExit as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=exc.exit_code,
                stdout="",
                stderr=exc.message,
                timed_out=False,
                payload=None,
            )
        except Exception as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )

        return CommandResult(
            action=action,
            requested_value=requested_value,
            status="ok",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            payload=payload,
        )

    def _run_clear_persona_action(self) -> CommandResult:
        """Clear the active user identity/persona via the memory service."""
        try:
            with self._runtime_env():
                memory_service = self._import_tool("memory.memory_service")
                memory_service.clear_current_user_identity()
                stdout = "Current user identity cleared.\n"
                stderr = ""
                returncode = 0
        except Exception as exc:
            return CommandResult(
                action="persona_clear",
                requested_value=None,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )
        return CommandResult(
            action="persona_clear",
            requested_value=None,
            status="ok",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            payload=None,
        )

    def _run_set_persona_action(self, requested_value: str) -> CommandResult:
        """Set the active user identity/persona via the memory service."""
        canonical = requested_value.strip().lower()
        if canonical not in {"michael"}:
            return CommandResult(
                action="persona_set",
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr="Persona must be 'michael'",
                timed_out=False,
                payload=None,
            )
        try:
            with self._runtime_env():
                memory_service = self._import_tool("memory.memory_service")
                row_id = memory_service.set_current_user_identity(canonical.capitalize())
                stdout = f"Current user identity set to: {canonical.capitalize()} (row {row_id})\n"
                stderr = ""
                returncode = 0
        except ValueError as exc:
            return CommandResult(
                action="persona_set",
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )
        except Exception as exc:
            return CommandResult(
                action="persona_set",
                requested_value=requested_value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )
        return CommandResult(
            action="persona_set",
            requested_value=requested_value,
            status="ok",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            payload=None,
        )

    def _run_speak_action(self, text: str) -> CommandResult:
        """Run TTS speak action via voice tool."""
        if not self.voice_capability.available:
            return CommandResult(
                action="speak",
                requested_value=text,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=self.voice_capability.reason,
                timed_out=False,
                payload=None,
            )
        try:
            with self._runtime_env(include_voice_python=True):
                runtime_voice = self._import_tool("runtime_voice")
                backend = runtime_voice.detect_backend()
                stderr_capture = io.StringIO()
                with contextlib.redirect_stderr(stderr_capture):
                    tts_status = runtime_voice.speak_response(backend, text)
                ok = tts_status == "completed"
                payload = {"ok": ok, "tts_status": tts_status}
                stdout = json.dumps(payload, sort_keys=True)
                stderr = stderr_capture.getvalue()
                returncode = 0 if ok else 1
        except Exception as exc:
            return CommandResult(
                action="speak",
                requested_value=text,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                payload=None,
            )
        return CommandResult(
            action="speak",
            requested_value=text,
            status="ok" if returncode == 0 else "failed",
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            timed_out=False,
            payload=payload,
        )
