from __future__ import annotations

# ROLE: PERMITTED GLOBAL CONTROL-PLANE EXCEPTION
# This HMI bridge intentionally lives in the shared UI tree outside any single
# snapshot. Runtime authority remains pinned to snapshot-local backend tools.

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


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
    def __init__(self, bridge: "RuntimeBridge", action: str, requested_value: str) -> None:
        super().__init__()
        self._bridge = bridge
        self._action = action
        self._requested_value = requested_value
        self.signals = RuntimeActionTaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._bridge.run_action(self._action, self._requested_value)
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
        self._enforce_authority_contract()
        self.snapshot_root = self._resolve_snapshot_root()
        self.control_tool_path = self.snapshot_root / "tools" / "runtime_control.py"
        self.profile_tool_path = self.snapshot_root / "tools" / "runtime_profile.py"
        self.lifecycle_tool_path = self.snapshot_root / "tools" / "runtime_lifecycle.py"
        self.request_tool_path = self.snapshot_root / "tools" / "runtime_request.py"
        self.voice_tool_path = self.snapshot_root / "tools" / "runtime_voice.py"
        self.voice_python_bin = self._resolve_voice_python_hint()
        self.capabilities = self._discover_capabilities()
        self.profile_capability = self._discover_profile_capability()
        self.lifecycle_capability = self._discover_lifecycle_capability()
        self.request_capability = self._discover_request_capability()
        self.voice_capability = self._discover_voice_capability()
        self._prime_voice_state()

    def _workspace_root(self) -> Path:
        return self.snapshot_root.parent.parent

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
        if ui_root.name not in ("ui-v7", "ui-v8") or not ui_root.exists() or not ui_root.is_dir():
            raise RuntimeError(f"invalid UI root in authority contract: {ui_root}")
        if authority_root.name not in ("opt-experimental-v7-dev", "opt-experimental-v8-dev", "lucy-v8"):
            raise RuntimeError(f"invalid authority root in authority contract: {authority_root}")
        if not runtime_ns_root.is_absolute():
            raise RuntimeError(f"invalid runtime namespace root in authority contract: {runtime_ns_root}")
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

        adapter_tool = self.snapshot_root / "tools" / "voice" / "tts_adapter.py"
        candidates = [
            self._workspace_root() / "ui-v8" / ".venv" / "bin" / "python3",
            self._workspace_root() / "ui-v7" / ".venv" / "bin" / "python3",
        ]
        for candidate in candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            if adapter_tool.exists():
                try:
                    completed = subprocess.run(
                        [str(candidate), str(adapter_tool), "probe", "--engine", "kokoro"],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                        shell=False,
                    )
                    payload = self._extract_payload(completed.stdout)
                    if isinstance(payload, dict) and payload.get("ok") and payload.get("engine") == "kokoro":
                        return str(candidate)
                except (OSError, subprocess.TimeoutExpired):
                    continue
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return str(candidate)
        return ""

    def _command_env(self, *, include_voice_python: bool = False) -> dict[str, str]:
        """Build command environment with Python router settings."""
        env = os.environ.copy()
        if include_voice_python and self.voice_python_bin:
            env.setdefault("LUCY_VOICE_PYTHON_BIN", self.voice_python_bin)
        # Always include Python router settings so they're propagated to subprocesses
        # These are only active when LUCY_ROUTER_PY=1
        env.setdefault("LUCY_ROUTER_PY", os.environ.get("LUCY_ROUTER_PY", "0"))
        env.setdefault("LUCY_ROUTER_PY_PERCENTAGE", os.environ.get("LUCY_ROUTER_PY_PERCENTAGE", "0"))
        env.setdefault("LUCY_ROUTER_PY_DETERMINISTIC", os.environ.get("LUCY_ROUTER_PY_DETERMINISTIC", "true"))
        env.setdefault("LUCY_ROUTER_PY_EMERGENCY_KILL", os.environ.get("LUCY_ROUTER_PY_EMERGENCY_KILL", "0"))
        # Python Voice Pipeline toggle (V8)
        # Set LUCY_VOICE_PY=1 to use Python-native voice pipeline instead of shell
        env.setdefault("LUCY_VOICE_PY", os.environ.get("LUCY_VOICE_PY", "0"))
        # Propagate evidence/control settings from HMI to voice subprocesses
        env.setdefault("LUCY_EVIDENCE_ENABLED", os.environ.get("LUCY_EVIDENCE_ENABLED", "0"))
        env.setdefault("LUCY_AUGMENTATION_POLICY", os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only"))
        env.setdefault("LUCY_CONVERSATION_MODE_FORCE", os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "0"))
        env.setdefault("LUCY_SESSION_MEMORY", os.environ.get("LUCY_SESSION_MEMORY", "0"))
        return env

    def _resolve_snapshot_root(self) -> Path:
        override = (os.environ.get(self.authority_root_env) or "").strip()
        if override:
            return Path(override).expanduser().resolve()
        # Always fail loudly - no silent fallbacks allowed
        raise RuntimeError(
            f"missing required {self.authority_root_env}. "
            f"Set it explicitly to the snapshot root (e.g., /home/mike/lucy/snapshots/opt-experimental-v7-dev)"
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
                allowed_values=("local-lucy", "local-lucy-qwen3"),
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

    def run_action(self, action: str, requested_value: str) -> CommandResult:
        if action == "submit_request":
            return self._run_submit_request(requested_value, action=action, augmented_direct_once=False)
        if action == "submit_request_force_augmented_once":
            return self._run_submit_request(requested_value, action=action, augmented_direct_once=True)
        if action == "submit_self_review_request":
            return self._run_submit_request(
                requested_value,
                action=action,
                augmented_direct_once=False,
                self_review=True,
            )
        if action == "reload_profile":
            return self._run_profile_action(action)
        if action in {"runtime_start", "runtime_stop"}:
            return self._run_lifecycle_action(action, requested_value)
        if action in {"voice_ptt_start", "voice_ptt_stop", "voice_status"}:
            return self._run_voice_action(action, requested_value)
        if action == "speak":
            return self._run_speak_action(requested_value)

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

        command = self._build_command(action, requested_value)
        if command is None:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="unavailable",
                returncode=None,
                stdout="",
                stderr=f"no command mapping for {action}",
                timed_out=False,
                payload=None,
            )

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.control_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="timeout",
                returncode=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
                payload=None,
            )

        status = "ok" if completed.returncode == 0 else "failed"
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            payload=self._extract_payload(completed.stdout),
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

        command = ["python3", str(self.profile_tool_path), "reload"]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.profile_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action=action,
                requested_value="",
                status="timeout",
                returncode=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
                payload=None,
            )

        status = "ok" if completed.returncode == 0 else "failed"
        return CommandResult(
            action=action,
            requested_value="",
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            payload=self._extract_payload(completed.stdout),
        )

    def _prime_voice_state(self) -> None:
        if not self.voice_capability.available:
            return
        try:
            # Check voice status
            subprocess.run(
                ["python3", str(self.voice_tool_path), "status"],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.voice_status_timeout_seconds,
                shell=False,
                env=self._command_env(include_voice_python=True),
            )
            # Prewarm Kokoro TTS worker to reduce latency on first use
            # This prevents the 2-5s cold-start delay
            subprocess.run(
                ["python3", str(self.voice_tool_path), "internal-prewarm-tts"],
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
                shell=False,
                env=self._command_env(include_voice_python=True),
            )
        except (OSError, subprocess.TimeoutExpired):
            return

    def _build_command(self, action: str, requested_value: str) -> list[str] | None:
        command_map = {
            "mode_selection": ["python3", str(self.control_tool_path), "set-mode", "--value", requested_value],
            "conversation_toggle": ["python3", str(self.control_tool_path), "set-conversation", "--value", requested_value],
            "memory_toggle": ["python3", str(self.control_tool_path), "set-memory", "--value", requested_value],
            "evidence_toggle": ["python3", str(self.control_tool_path), "set-evidence", "--value", requested_value],
            "voice_toggle": ["python3", str(self.control_tool_path), "set-voice", "--value", requested_value],
            "augmentation_policy": ["python3", str(self.control_tool_path), "set-augmentation", "--value", requested_value],
            "augmented_provider": ["python3", str(self.control_tool_path), "set-augmented-provider", "--value", requested_value],
            "model_selection": ["python3", str(self.control_tool_path), "set-model", "--value", requested_value],
        }
        return command_map.get(action)

    def _run_submit_request(
        self,
        requested_value: str,
        *,
        action: str,
        augmented_direct_once: bool,
        self_review: bool = False,
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
    ) -> CommandResult:
        """
        Direct Python execution path - bypasses subprocess hops.
        
        Phase 1: Flattened execution chain
        Before: runtime_bridge → runtime_request.py → lucy_chat.sh → hybrid_wrapper.sh → main.py
        After:  runtime_bridge → ExecutionEngine (direct Python call)
        
        This eliminates 3 subprocess hops and reduces latency.
        
        Args:
            requested_value: The user's query text
            action: The action name (e.g., "submit_request")
            augmented_direct_once: Whether to force augmented mode
            self_review: Whether this is a self-review request
            
        Returns:
            CommandResult with same format as subprocess path
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
            from router_py.classify import classify_intent, select_route
            from router_py.execution_engine import ExecutionEngine
            from router_py.policy import normalize_augmentation_policy
            from router_py.state_manager import get_state_manager
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
        
        # Build execution context
        context = {"question": request_text}
        if augmented_direct_once:
            context["augmented_direct_once"] = True
        if self_review:
            context["self_review"] = True
        
        # Get augmentation policy from environment
        policy = normalize_augmentation_policy(
            os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
        )
        
        start_time = os.times()[0]  # User CPU time
        
        try:
            # Step 1: Classify intent
            classification = classify_intent(request_text, surface="hmi")
            
            # Step 2: Select route
            decision = select_route(classification, policy=policy)
            
            # Step 3: Execute via ExecutionEngine (Python-native path)
            engine = ExecutionEngine(config={
                "timeout": self.request_timeout_seconds,
                "use_sqlite_state": True,
                "model": self._resolve_current_model(),
            })
            
            result = engine.execute(
                intent=classification,
                route=decision,
                context=context,
                use_python_path=True,  # KEY: Skip shell entirely
            )
            
            engine.close()
            
            # Calculate execution time
            execution_time_ms = int((os.times()[0] - start_time) * 1000)
            
            # Step 4: Build payload from result directly
            # Note: ExecutionEngine uses unique namespace per instance, so we
            # use the result object directly instead of reading from StateManager
            # to ensure we get the correct data for this execution.
            route_data = {
                "intent": classification.intent_family if classification else "unknown",
                "confidence": decision.confidence if decision else 0.0,
                "strategy": decision.route if decision else "LOCAL",
                "metadata": result.metadata or {},
            }
            outcome_data = {
                "success": result.status == "completed",
                "duration_ms": result.execution_time_ms,
                "result": {
                    "outcome_code": result.outcome_code,
                    "route": result.route,
                    "provider": result.provider,
                },
                "error_message": result.error_message or "",
            }
            
            # Build payload matching subprocess format
            payload = self._build_payload_from_result(
                result=result,
                route_data=route_data,
                outcome_data=outcome_data,
                request_text=request_text,
                execution_time_ms=execution_time_ms,
            )
            
            # Write to history file for HMI display (same as voice path)
            try:
                self._write_history_entry(payload)
            except Exception as hist_exc:
                # Log but don't fail the request if history write fails
                print(f"[runtime_bridge] Warning: failed to write history entry: {hist_exc}", file=sys.stderr)
            
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="ok" if result.status == "completed" else result.status,
                returncode=0 if result.status == "completed" else 1,
                stdout=result.response_text,
                stderr=result.error_message or "",
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
    
    def _build_payload_from_result(
        self,
        result: Any,
        route_data: dict,
        outcome_data: dict,
        request_text: str,
        execution_time_ms: int,
    ) -> dict[str, Any]:
        """
        Build JSON payload matching runtime_request.py format.
        
        Args:
            result: ExecutionResult from ExecutionEngine
            route_data: Route data from StateManager
            outcome_data: Outcome data from StateManager
            request_text: Original request text
            execution_time_ms: Execution time in milliseconds
            
        Returns:
            Payload dict matching subprocess path format
        """
        import hashlib
        import time
        
        request_id = f"direct_{hashlib.sha256(request_text.encode()).hexdigest()[:16]}_{time.time_ns()}"
        
        # Build control state from environment
        control_state = {
            "mode": os.environ.get("LUCY_MODE", "offline"),
            "conversation": os.environ.get("LUCY_CONVERSATION_MODE", "off"),
            "memory": os.environ.get("LUCY_SESSION_MEMORY", "1"),
            "evidence": os.environ.get("LUCY_EVIDENCE_ENABLED", "0"),
            "voice": os.environ.get("LUCY_VOICE_ENABLED", "0"),
            "augmentation_policy": os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only"),
            "augmented_provider": os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia"),
            "model": os.environ.get("LUCY_MODEL", "local"),
            "profile": os.environ.get("LUCY_PROFILE", "default"),
        }
        
        # Build route payload
        route_payload = {
            "mode": result.route if result.route else "LOCAL",
            "intent_family": getattr(result, 'intent_family', 'unknown'),
            "confidence": getattr(result, 'confidence', 0.0),
            "route_reason": route_data.get("metadata", {}).get("final_mode", "direct_execution"),
            "provider": result.provider if result.provider else "local",
            "provider_usage_class": result.provider_usage_class if result.provider_usage_class else "local",
            "requested_mode": route_data.get("strategy", result.route),
            "final_mode": result.route if result.route else "LOCAL",
            "is_medical": route_data.get("metadata", {}).get("is_medical_query", False),
        }
        
        # Build outcome payload
        outcome_payload = {
            "outcome_code": result.outcome_code if result.outcome_code else "completed",
            "fallback_used": "false" if result.status == "completed" else "true",
            "fallback_reason": result.error_message or "none",
            "trust_class": result.metadata.get("trust_class", "local") if result.metadata else "local",
            "error_message": result.error_message or "",
            "execution_time_ms": execution_time_ms,
        }
        
        return {
            "accepted": True,
            "authority": {
                "runtime_authority_root": str(self.snapshot_root),
                "ui_authority_root": str(self.snapshot_root),
            },
            "completed_at": self._iso_now(),
            "control_state": control_state,
            "error": result.error_message or "",
            "outcome": outcome_payload,
            "request_id": request_id,
            "request_text": request_text,
            "response_text": result.response_text,
            "route": route_payload,
            "status": "completed" if result.status == "completed" else result.status,
        }
    
    def _iso_now(self) -> str:
        """Return ISO format current timestamp."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def _write_history_entry(self, payload: dict[str, Any]) -> None:
        """Write a history entry to the jsonl file for HMI display."""
        from datetime import datetime, timezone
        
        # Resolve history file path (same logic as runtime_request.py)
        history_file = self._resolve_history_file()
        
        # Build entry matching runtime_request.py format
        entry = {
            "authority": payload.get("authority", {}),
            "completed_at": payload.get("completed_at", self._iso_now()),
            "control_state": payload.get("control_state", {}),
            "error": payload.get("error", ""),
            "outcome": payload.get("outcome", {}),
            "request_id": payload.get("request_id", ""),
            "request_text": payload.get("request_text", ""),
            "response_text": payload.get("response_text", ""),
            "route": payload.get("route", {}),
            "status": payload.get("status", "unknown"),
        }
        
        # Write to file
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True))
            f.write("\n")

    def _resolve_current_model(self) -> str:
        """Read the active model from runtime state file."""
        namespace_root = Path(os.environ.get(self.runtime_namespace_env, "")).expanduser()
        if not namespace_root:
            return "local-lucy"
        state_file = namespace_root / "state" / "current_state.json"
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
            return state.get("model") or state.get("active_model") or "local-lucy"
        except (OSError, json.JSONDecodeError):
            return "local-lucy"

    def _resolve_history_file(self) -> Path:
        """Resolve the history file path (same logic as runtime_request.py)."""
        raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE")
        if raw:
            return Path(raw).expanduser()
        # Default path matching runtime_request.py
        home = Path.home()
        workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
        return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "request_history.jsonl"

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

        command = ["python3", str(self.lifecycle_tool_path), expected_value]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self.lifecycle_timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="timeout",
                returncode=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
                payload=self._extract_payload(exc.stdout),
            )

        status = "ok" if completed.returncode == 0 else "failed"
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            payload=self._extract_payload(completed.stdout),
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

        timeout_seconds = self.voice_status_timeout_seconds
        if action == "voice_ptt_start":
            timeout_seconds = self.voice_start_timeout_seconds
        elif action == "voice_ptt_stop":
            timeout_seconds = self.voice_stop_timeout_seconds

        try:
            completed = subprocess.run(
                ["python3", str(self.voice_tool_path), command_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                shell=False,
                env=self._command_env(include_voice_python=True),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="timeout",
                returncode=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
                payload=self._extract_payload(exc.stdout),
            )

        status = "ok" if completed.returncode == 0 else "failed"
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            payload=self._extract_payload(completed.stdout),
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
            completed = subprocess.run(
                ["python3", str(self.voice_tool_path), "speak", "--text", text],
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                shell=False,
                env=self._command_env(include_voice_python=True),
            )
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                action="speak",
                requested_value=text,
                status="timeout",
                returncode=None,
                stdout=exc.stdout or "",
                stderr=exc.stderr or "",
                timed_out=True,
                payload=self._extract_payload(exc.stdout),
            )
        status = "ok" if completed.returncode == 0 else "failed"
        return CommandResult(
            action="speak",
            requested_value=text,
            status=status,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
            payload=self._extract_payload(completed.stdout),
        )
