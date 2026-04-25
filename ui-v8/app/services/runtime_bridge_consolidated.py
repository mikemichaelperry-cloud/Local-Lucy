"""
Consolidated Runtime Bridge - Direct Python calls, no subprocess overhead.
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from datetime import datetime

# Add app to path for backend_wrapper
APP_DIR = Path(__file__).parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

# Import via wrapper
try:
    import backend_wrapper
    BACKEND_AVAILABLE = True
except ImportError as e:
    print(f"[ConsolidatedBridge] Backend import failed: {e}", file=sys.stderr)
    BACKEND_AVAILABLE = False

# Import voice components
try:
    sys.path.insert(0, str(APP_DIR / "backend"))
    sys.path.insert(0, str(APP_DIR / "backend" / "voice"))
    from voice_tool import VoicePipeline, VoiceResult
    from voice import tts_adapter
    VOICE_AVAILABLE = True
except ImportError as e:
    print(f"[ConsolidatedBridge] Voice import failed: {e}", file=sys.stderr)
    VOICE_AVAILABLE = False


@dataclass(frozen=True)
class ActionCapability:
    """Mirror of runtime_bridge.ActionCapability for API compatibility."""
    name: str
    available: bool
    allowed_values: tuple[str, ...]
    reason: str


class ConsolidatedRuntimeBridge:
    """Unified runtime bridge - backend loaded as Python modules."""
    
    def __init__(self):
        if not BACKEND_AVAILABLE:
            raise RuntimeError("Backend not available")
        self.available = True
        self._setup_environment()
        
        # Voice state
        self._voice_listening = False
        self._voice_processing = False
        self._voice_pipeline: Any = None
        self._voice_temp_file: Path | None = None
        self._voice_recorder = None
        
        # Tool paths (for lifecycle, voice, etc.) - MUST be set before discovering capabilities
        authority_root = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", 
            str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev")))
        self.lifecycle_tool_path = authority_root / "tools" / "runtime_lifecycle.py"
        
        # Initialize capabilities for API compatibility with legacy bridge
        self.capabilities = self._discover_capabilities()
        self.profile_capability = self._discover_profile_capability()
        self.lifecycle_capability = self._discover_lifecycle_capability()
        self.request_capability = self._discover_request_capability()
        self.voice_capability = self._discover_voice_capability()
        
        # Timeout configuration (mirror legacy bridge)
        self.control_timeout_seconds = 5
        self.profile_timeout_seconds = 5
        self.lifecycle_timeout_seconds = 15
        self.request_timeout_seconds = 125
        self.voice_status_timeout_seconds = 5
        self.voice_start_timeout_seconds = 5
        self.voice_stop_timeout_seconds = 300
    
    def _setup_environment(self):
        """Set required environment variables."""
        os.environ.setdefault("LUCY_RUNTIME_AUTHORITY_ROOT", 
            str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))
        os.environ.setdefault("LUCY_RUNTIME_NAMESPACE_ROOT", 
            str(Path.home() / ".codex-api-home" / "lucy" / "runtime-v8"))
        os.environ.setdefault("LUCY_UI_ROOT", 
            str(Path(__file__).parent.parent.parent))
        os.environ.setdefault("LUCY_ROUTER_PY", "1")
        os.environ.setdefault("LUCY_EXEC_PY", "1")  # Use Python execution by default
    
    def _discover_capabilities(self) -> dict[str, ActionCapability]:
        """Discover available capabilities."""
        return {
            "mode_selection": ActionCapability(
                name="mode_selection",
                available=True,
                allowed_values=("local", "augmented", "auto"),
                reason="Consolidated bridge supports all modes"
            ),
            "memory_toggle": ActionCapability(
                name="memory_toggle",
                available=True,
                allowed_values=("on", "off"),
                reason="Session memory supported"
            ),
            "evidence_toggle": ActionCapability(
                name="evidence_toggle",
                available=True,
                allowed_values=("on", "off"),
                reason="Evidence mode supported"
            ),
        }
    
    def _discover_request_capability(self) -> ActionCapability:
        """Discover request submission capability."""
        return ActionCapability(
            name="request",
            available=True,
            allowed_values=(),
            reason="Direct Python execution available"
        )
    
    def _discover_profile_capability(self) -> ActionCapability:
        """Discover profile capability."""
        return ActionCapability(
            name="profile",
            available=False,  # Not yet implemented in consolidated bridge
            allowed_values=(),
            reason="Profile management not yet implemented in consolidated bridge"
        )
    
    def _discover_lifecycle_capability(self) -> ActionCapability:
        """Discover lifecycle capability."""
        available = self.lifecycle_tool_path.exists() and self.lifecycle_tool_path.is_file()
        reason = (
            f"Live: authoritative runtime lifecycle via {self.lifecycle_tool_path}"
            if available
            else f"Unavailable: missing backend lifecycle tool {self.lifecycle_tool_path}"
        )
        return ActionCapability(
            name="lifecycle",
            available=available,
            allowed_values=("start", "stop"),
            reason=reason
        )
    
    def _discover_voice_capability(self) -> ActionCapability:
        """Discover voice capability."""
        if not VOICE_AVAILABLE:
            return ActionCapability(
                name="voice",
                available=False,
                allowed_values=(),
                reason="Voice components not available (import failed)"
            )
        
        # Check if voice backend is functional
        try:
            pipeline = VoicePipeline()
            backend_info = pipeline._detect_backend()
            if backend_info.available:
                return ActionCapability(
                    name="voice",
                    available=True,
                    allowed_values=(),
                    reason=f"Voice ready ({backend_info.recorder_engine} recorder, {backend_info.stt_engine} STT)"
                )
            else:
                return ActionCapability(
                    name="voice",
                    available=False,
                    allowed_values=(),
                    reason=f"Voice backend unavailable: {backend_info.reason}"
                )
        except Exception as e:
            return ActionCapability(
                name="voice",
                available=False,
                allowed_values=(),
                reason=f"Voice detection failed: {e}"
            )
    
    def capability_notes(self) -> dict[str, str]:
        """Get capability notes for display."""
        return {
            "mode_selection": self.capabilities["mode_selection"].reason,
            "feature_toggles": self.capabilities["memory_toggle"].reason,
            "lifecycle_controls": self.lifecycle_capability.reason,
            "profile_reload": self.profile_capability.reason,
            "voice_ptt": self.voice_capability.reason,
        }
    
    def request_available(self) -> bool:
        """Check if request submission is available."""
        return self.request_capability.available
    
    def profile_available(self) -> bool:
        """Check if profile operations are available."""
        return self.profile_capability.available
    
    def lifecycle_available(self) -> bool:
        """Check if lifecycle operations are available."""
        return self.lifecycle_capability.available
    
    def voice_available(self) -> bool:
        """Check if voice operations are available."""
        return self.voice_capability.available
    
    def submit_request(self, text: str, *, force_augmented: bool = False) -> dict[str, Any]:
        """Submit a request to the backend."""
        try:
            policy = backend_wrapper.normalize_augmentation_policy(
                os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")
            )
            
            result = backend_wrapper.execute_plan_python(text, policy, timeout=130)
            
            # Build full result dict
            response = {
                "accepted": True,
                "request_id": result.request_id or "direct",
                "status": "completed" if result.status == "completed" else "failed",
                "response_text": result.response_text,
                "error": result.error_message,
                "outcome": {
                    "outcome_code": result.outcome_code,
                    "final_mode": result.route,
                    "provider_used": result.provider,
                }
            }
            
            # Write to history file for HMI display
            try:
                self._write_history_entry(text, response)
            except Exception as hist_exc:
                print(f"[ConsolidatedBridge] Warning: failed to write history: {hist_exc}", file=sys.stderr)
            
            return response
        except Exception as e:
            import traceback
            return {
                "accepted": False,
                "error": str(e) + "\n" + traceback.format_exc(),
                "status": "failed",
            }
    
    def _get_voice_status(self) -> dict[str, Any]:
        """Get current voice runtime status."""
        if not VOICE_AVAILABLE:
            return {
                "available": False,
                "status": "unavailable",
                "listening": False,
                "processing": False,
                "reason": "Voice components not available"
            }
        
        try:
            pipeline = VoicePipeline()
            backend = pipeline._detect_backend()
            
            return {
                "available": backend.available,
                "status": "listening" if self._voice_listening else "processing" if self._voice_processing else "idle",
                "listening": self._voice_listening,
                "processing": self._voice_processing,
                "recorder": backend.recorder_engine,
                "stt": backend.stt_engine,
                "tts": backend.tts_engine,
                "tts_device": backend.tts_device,
                "last_error": ""
            }
        except Exception as e:
            return {
                "available": False,
                "status": "fault",
                "listening": False,
                "processing": False,
                "reason": str(e),
                "last_error": str(e)
            }
    
    def _start_voice_ptt(self) -> dict[str, Any]:
        """Start voice PTT recording using subprocess to runtime_voice.py."""
        import subprocess
        
        runtime_voice_path = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", 
            str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))) / "tools" / "runtime_voice.py"
        
        if not runtime_voice_path.exists():
            return {"status": "failed", "error": f"runtime_voice.py not found at {runtime_voice_path}"}
        
        try:
            result = subprocess.run(
                ["python3", str(runtime_voice_path), "ptt-start"],
                capture_output=True,
                text=True,
                timeout=self.voice_start_timeout_seconds,
                env=os.environ.copy()
            )
            
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout)
                    self._voice_listening = True
                    return payload
                except json.JSONDecodeError:
                    return {"status": "failed", "error": f"Invalid JSON response: {result.stdout}"}
            else:
                return {"status": "failed", "error": result.stderr or f"Exit code {result.returncode}"}
                
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Voice start timed out"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    
    def _stop_voice_ptt(self) -> dict[str, Any]:
        """Stop voice PTT using subprocess to runtime_voice.py."""
        import subprocess
        
        runtime_voice_path = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", 
            str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))) / "tools" / "runtime_voice.py"
        
        if not runtime_voice_path.exists():
            return {"status": "failed", "error": f"runtime_voice.py not found at {runtime_voice_path}"}
        
        try:
            result = subprocess.run(
                ["python3", str(runtime_voice_path), "ptt-stop"],
                capture_output=True,
                text=True,
                timeout=self.voice_stop_timeout_seconds,
                env=os.environ.copy()
            )
            
            self._voice_listening = False
            
            if result.returncode == 0:
                try:
                    payload = json.loads(result.stdout)
                    return payload
                except json.JSONDecodeError:
                    return {"status": "completed", "transcript": "", "no_transcript": True}
            else:
                return {"status": "failed", "error": result.stderr or f"Exit code {result.returncode}"}
                
        except subprocess.TimeoutExpired:
            return {"status": "timeout", "error": "Voice stop timed out"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    
    def _prewarm_tts(self) -> dict[str, Any]:
        """Prewarm TTS worker using subprocess."""
        import subprocess
        
        runtime_voice_path = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", 
            str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))) / "tools" / "runtime_voice.py"
        
        if not runtime_voice_path.exists():
            return {"ok": False, "engine": "none", "prewarmed": False}
        
        try:
            result = subprocess.run(
                ["python3", str(runtime_voice_path), "internal-prewarm-tts"],
                capture_output=True,
                text=True,
                timeout=10,
                env=os.environ.copy()
            )
            
            if result.returncode == 0:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {"ok": False, "engine": "none", "prewarmed": False}
            else:
                return {"ok": False, "engine": "none", "prewarmed": False}
                
        except Exception:
            return {"ok": False, "engine": "none", "prewarmed": False}
    
    def _run_lifecycle_action(self, action: str, requested_value: str) -> Any:
        """Run lifecycle start/stop action using runtime_lifecycle.py."""
        from app.services.runtime_bridge import CommandResult
        import subprocess
        
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
    
    def _extract_payload(self, stdout: str) -> dict[str, Any] | None:
        """Extract JSON payload from command stdout."""
        if not stdout:
            return None
        try:
            # Try to find JSON in the output
            lines = stdout.strip().split('\n')
            for line in lines:
                line = line.strip()
                if line and (line.startswith('{') or line.startswith('[')):
                    return json.loads(line)
            return None
        except json.JSONDecodeError:
            return None
    
    # Legacy bridge method stubs for API compatibility
    def run_action(self, action: str, requested_value: str = "") -> Any:
        """
        Run an action - legacy bridge compatibility method.
        
        In consolidated bridge, most actions are handled via submit_request.
        This method provides compatibility with the legacy bridge API.
        """
        from app.services.runtime_bridge import CommandResult
        
        # Map legacy actions to consolidated implementations
        if action == "submit_request":
            result = self.submit_request(requested_value)
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="success" if result.get("accepted") else "failed",
                returncode=0 if result.get("accepted") else 1,
                stdout=result.get("response_text", ""),
                stderr=result.get("error", ""),
                timed_out=False,
                payload=result.get("outcome")
            )
        
        # Voice actions
        if action == "voice_status":
            payload = self._get_voice_status()
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="ok",
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
                timed_out=False,
                payload=payload
            )
        
        if action == "voice_ptt_start":
            payload = self._start_voice_ptt()
            status = "ok" if payload.get("status") in ("listening", "already_listening") else "failed"
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status=status,
                returncode=0 if status == "ok" else 1,
                stdout=json.dumps(payload),
                stderr=payload.get("error", ""),
                timed_out=False,
                payload=payload
            )
        
        if action == "voice_ptt_stop":
            payload = self._stop_voice_ptt()
            status = "ok" if payload.get("status") == "completed" else "failed"
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status=status,
                returncode=0 if status == "ok" else 1,
                stdout=json.dumps(payload),
                stderr=payload.get("error", ""),
                timed_out=False,
                payload=payload
            )
        
        if action == "internal-prewarm-tts":
            payload = self._prewarm_tts()
            return CommandResult(
                action=action,
                requested_value=requested_value,
                status="ok",
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
                timed_out=False,
                payload=payload
            )
        
        # State toggle actions - update runtime state file
        if action == "evidence_toggle":
            return self._set_state_field("evidence", requested_value)
        
        if action == "augmentation_policy":
            return self._set_state_field("augmentation_policy", requested_value)
        
        if action == "augmented_provider":
            return self._set_state_field("augmented_provider", requested_value)
        
        if action == "mode_selection":
            return self._set_state_field("mode", requested_value)
        
        if action == "conversation_toggle":
            return self._set_state_field("conversation", requested_value)
        
        if action == "memory_toggle":
            return self._set_state_field("memory", requested_value)
        
        if action == "voice_toggle":
            return self._set_state_field("voice", requested_value)
        
        # Lifecycle actions
        if action in {"runtime_start", "runtime_stop"}:
            return self._run_lifecycle_action(action, requested_value)
        
        # Other actions not yet implemented in consolidated bridge
        return CommandResult(
            action=action,
            requested_value=requested_value,
            status="not_implemented",
            returncode=1,
            stdout="",
            stderr=f"Action '{action}' not implemented in consolidated bridge. Use legacy bridge (LUCY_USE_CONSOLIDATED_BRIDGE=0) if needed.",
            timed_out=False,
            payload=None
        )
    
    def _set_state_field(self, field: str, value: str) -> Any:
        """Set a field in the runtime state file.
        
        Mirrors functionality of runtime_control.py's update_state_field.
        Updates both state file AND environment variables that backend uses.
        """
        from app.services.runtime_bridge import CommandResult
        from pathlib import Path
        from datetime import datetime, timezone
        import json
        
        # Resolve state file path
        state_file = self._resolve_state_file()
        
        try:
            # Read current state
            if state_file.exists():
                with open(state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)
            else:
                state = {}
            
            # Update the field
            state[field] = value
            state["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Update environment variables that the backend ACTUALLY uses
            # These must match what ensure_control_env() and execution engine expect
            env_var_map = {
                "evidence": ("LUCY_EVIDENCE_ENABLED", lambda v: "1" if v in ("on", "true", "1") else "0"),
                "augmentation_policy": ("LUCY_AUGMENTATION_POLICY", lambda v: v),
                "augmented_provider": ("LUCY_AUGMENTED_PROVIDER", lambda v: v),
                "mode": ("LUCY_MODE", lambda v: v),
                "conversation": ("LUCY_CONVERSATION_MODE_FORCE", lambda v: "1" if v in ("on", "true", "1") else "0"),
                "memory": ("LUCY_SESSION_MEMORY", lambda v: "1" if v in ("on", "true", "1") else "0"),
                "voice": ("LUCY_VOICE_ENABLED", lambda v: "1" if v in ("on", "true", "1") else "0"),
                "approval_required": ("LUCY_APPROVAL_REQUIRED", lambda v: "1" if v in ("on", "true", "1") else "0"),
            }
            if field in env_var_map:
                env_var, transform = env_var_map[field]
                os.environ[env_var] = transform(value)
            
            # Write state back
            state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(state_file, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, sort_keys=True)
            
            return CommandResult(
                action=f"set_{field}",
                requested_value=value,
                status="ok",
                returncode=0,
                stdout=json.dumps({"status": "ok", field: value}),
                stderr="",
                timed_out=False,
                payload={"status": "ok", field: value}
            )
        except Exception as e:
            return CommandResult(
                action=f"set_{field}",
                requested_value=value,
                status="failed",
                returncode=1,
                stdout="",
                stderr=str(e),
                timed_out=False,
                payload=None
            )
    
    def _resolve_state_file(self) -> Path:
        """Resolve the runtime state file path.
        
        IMPORTANT: Must match state_store.py's STATE_FILES["current_state"] exactly!
        The UI reads from current_state.json, so we must write to the same file.
        """
        from pathlib import Path
        
        # Check explicit state file override first
        raw = os.environ.get("LUCY_RUNTIME_STATE_FILE")
        if raw:
            return Path(raw).expanduser()
        
        # Check runtime namespace root (must be honored if set)
        runtime_ns = os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT")
        if runtime_ns:
            return Path(runtime_ns).expanduser() / "state" / "current_state.json"
        
        # Fallback: derive from home directory
        home = Path.home()
        if home.name in {".codex-api-home", ".codex-plus-home"}:
            workspace_home = home.parent
        else:
            workspace_home = home
        
        return workspace_home / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "current_state.json"
    
    def _write_history_entry(self, request_text: str, result: dict[str, Any]) -> None:
        """Write a history entry to the jsonl file for HMI display."""
        from datetime import datetime, timezone
        from pathlib import Path
        import json
        
        # Resolve history file path
        raw = os.environ.get("LUCY_RUNTIME_REQUEST_HISTORY_FILE")
        if raw:
            history_file = Path(raw).expanduser()
        else:
            home = Path.home()
            workspace_home = home.parent if home.name in {".codex-api-home", ".codex-plus-home"} else home
            history_file = workspace_home / ".codex-api-home" / "lucy" / "runtime-v8" / "state" / "request_history.jsonl"
        
        # Read ACTUAL current state from file (not hardcoded values)
        state_file = self._resolve_state_file()
        current_state = {}
        if state_file.exists():
            try:
                with open(state_file, "r", encoding="utf-8") as f:
                    current_state = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        # Build entry matching runtime_request.py format with ACTUAL state
        entry = {
            "authority": {
                "active_root": os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", ""),
                "authority_root": os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", ""),
                "runtime_namespace_root": os.environ.get("LUCY_RUNTIME_NAMESPACE_ROOT", ""),
            },
            "completed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "control_state": {
                "augmentation_policy": current_state.get("augmentation_policy", os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only")),
                "augmented_provider": current_state.get("augmented_provider", os.environ.get("LUCY_AUGMENTED_PROVIDER", "wikipedia")),
                "conversation": current_state.get("conversation", "off"),
                "evidence": current_state.get("evidence", "off"),
                "memory": current_state.get("memory", "off"),
                "mode": current_state.get("mode", os.environ.get("LUCY_MODE", "auto")),
                "model": current_state.get("model", "local-lucy"),
                "profile": current_state.get("profile", "opt-experimental-v8-dev"),
                "status": current_state.get("status", "ready"),
                "voice": current_state.get("voice", "off"),
            },
            "error": result.get("error", ""),
            "outcome": {
                "augmented_provider_used": result.get("outcome", {}).get("provider_used", "none"),
                "outcome_code": result.get("outcome", {}).get("outcome_code", "unknown"),
            },
            "request_id": result.get("request_id", "direct"),
            "request_text": request_text,
            "response_text": result.get("response_text", ""),
            "route": {
                "final_mode": result.get("outcome", {}).get("final_mode", "LOCAL"),
                "mode": "online" if result.get("status") == "completed" else "offline",
            },
            "status": result.get("status", "unknown"),
        }
        
        # Write to file
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, sort_keys=True) + "\n")
            f.write("\n")
