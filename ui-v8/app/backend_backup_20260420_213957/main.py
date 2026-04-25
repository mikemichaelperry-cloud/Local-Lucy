#!/usr/bin/env python3
"""
Local Lucy Router - Python Main Orchestrator (Phase 4 Strangler Fig)

This is the Python entry point for the router migration.
It provides a hybrid execution mode:
- LUCY_ROUTER_PY=0: Use shell implementation (default, safe)
- LUCY_ROUTER_PY=1: Use Python implementation (new, tested)
- LUCY_ROUTER_PY=shadow: Run both, compare, log differences

Execution Engine Toggle (LUCY_EXEC_PY):
- LUCY_EXEC_PY=0 or unset: Use shell execute_plan.sh (default, safe)
- LUCY_EXEC_PY=1: Use Python ExecutionEngine (new)
- LUCY_EXEC_PY=shadow: Run both, compare, log differences to /tmp/exec_shadow_diffs.log

CRITICAL DESIGN PRINCIPLE:
The Python router makes routing decisions but DELEGATES execution to the
existing governed execution path. It does NOT invent new provider calls.
This preserves authority semantics and truth metadata.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Add parent to path for imports
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT_DIR / "tools"))

from backend.classify import ClassificationResult, RoutingDecision, classify_intent, select_route
from backend.policy import normalize_augmentation_policy, provider_usage_class_for
from backend.utils import sha256_text
from backend.execution_engine import ExecutionEngine, ExecutionResult


# Configuration
SHADOW_LOG_DIR = ROOT_DIR / "logs" / "router_py_shadow"
SHELL_EXECUTE_PLAN = ROOT_DIR / "tools" / "router" / "execute_plan.sh"
SHELL_LUCY_CHAT = ROOT_DIR / "lucy_chat.sh"
DEFAULT_TIMEOUT = 130


def resolve_state_dir(root: Path) -> Path:
    """Resolve state directory, respecting LUCY_SHARED_STATE_NAMESPACE like shell does."""
    namespace = os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "")
    if namespace:
        # Sanitize: s/[^A-Za-z0-9._-]+/_/g; s/^_+|_+$//
        sanitized = re.sub(r'[^A-Za-z0-9._-]+', '_', namespace)
        sanitized = sanitized.strip('_')
        if sanitized:
            return root / "state" / "namespaces" / sanitized
    # Default: use "default" namespace (consistent with shell behavior)
    return root / "state" / "namespaces" / "default"


# State files (same as runtime_request.py uses)
STATE_DIR = resolve_state_dir(ROOT_DIR)
LAST_ROUTE_FILE = STATE_DIR / "last_route.env"
LAST_OUTCOME_FILE = STATE_DIR / "last_outcome.env"


def load_state_from_file() -> dict[str, Any]:
    """Load control state from state file (fallback when env vars not set)."""
    try:
        # Try to find state file similar to runtime_request.py
        state_file = ROOT_DIR / "state" / "state" / "current_state.json"
        if state_file.exists():
            import json
            with open(state_file) as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def ensure_control_env() -> None:
    """
    Ensure control environment variables are set from state file if not in environment.
    This matches behavior of runtime_request.py's build_request_env.
    """
    if os.environ.get("LUCY_EVIDENCE_ENABLED") and os.environ.get("LUCY_AUGMENTATION_POLICY"):
        # Already set, nothing to do
        return
    
    state = load_state_from_file()
    if not state:
        return
    
    # Set from state file if not already in environment
    if "LUCY_EVIDENCE_ENABLED" not in os.environ:
        evidence = state.get("evidence", "off")
        os.environ["LUCY_EVIDENCE_ENABLED"] = "1" if evidence in ("on", "true", "1") else "0"
    
    if "LUCY_ENABLE_INTERNET" not in os.environ:
        # Mirror LUCY_EVIDENCE_ENABLED
        os.environ["LUCY_ENABLE_INTERNET"] = os.environ.get("LUCY_EVIDENCE_ENABLED", "0")
    
    if "LUCY_AUGMENTATION_POLICY" not in os.environ:
        policy = state.get("augmentation_policy", "disabled")
        os.environ["LUCY_AUGMENTATION_POLICY"] = policy
    
    if "LUCY_AUGMENTED_PROVIDER" not in os.environ:
        provider = state.get("augmented_provider", "wikipedia")
        os.environ["LUCY_AUGMENTED_PROVIDER"] = provider
    
    if "LUCY_CONVERSATION_MODE_FORCE" not in os.environ:
        conv = state.get("conversation", "off")
        os.environ["LUCY_CONVERSATION_MODE_FORCE"] = "1" if conv in ("on", "true", "1") else "0"
    
    if "LUCY_SESSION_MEMORY" not in os.environ:
        mem = state.get("memory", "off")
        os.environ["LUCY_SESSION_MEMORY"] = "1" if mem in ("on", "true", "1") else "0"
    
    if "LUCY_VOICE_ENABLED" not in os.environ:
        voice = state.get("voice", "off")
        os.environ["LUCY_VOICE_ENABLED"] = "1" if voice in ("on", "true", "1") else "0"
    
    if "LUCY_MODE" not in os.environ:
        mode = state.get("mode", "auto")
        os.environ["LUCY_MODE"] = mode


@dataclass(frozen=True)
class RouterOutcome:
    """Structured outcome from router execution."""
    
    status: str
    outcome_code: str
    route: str
    provider: str
    provider_usage_class: str
    intent_family: str
    confidence: float
    response_text: str = ""
    error_message: str = ""
    execution_time_ms: int = 0
    request_id: str = ""
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "outcome_code": self.outcome_code,
            "route": self.route,
            "provider": self.provider,
            "provider_usage_class": self.provider_usage_class,
            "intent_family": self.intent_family,
            "confidence": self.confidence,
            "response_text": self.response_text,
            "error_message": self.error_message,
            "execution_time_ms": self.execution_time_ms,
            "request_id": self.request_id,
        }


@dataclass
class ShadowComparison:
    """Result of shadow mode comparison."""
    
    query: str
    shell_result: RouterOutcome | None
    python_result: RouterOutcome | None
    match: bool
    differences: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    classification: str = ""  # "true_parity", "intended_improvement", "suspicious_drift", "hard_regression"
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "query": self.query,
            "match": self.match,
            "classification": self.classification,
            "differences": self.differences,
            "shell": self.shell_result.to_dict() if self.shell_result else None,
            "python": self.python_result.to_dict() if self.python_result else None,
        }


def query_sha256(query: str) -> str:
    """Compute SHA256 hash of query for matching."""
    return hashlib.sha256(query.encode("utf-8")).hexdigest().lower()


def file_signature(path: Path) -> tuple[int, int, int] | None:
    """Get file signature for change detection."""
    try:
        stat = path.stat()
        return (stat.st_ino, stat.st_size, int(stat.st_mtime))
    except (OSError, FileNotFoundError):
        return None


def load_env_file(path: Path) -> dict[str, str]:
    """Load env file into dict."""
    values = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, _, val = line.partition("=")
                    values[key] = val
    except (OSError, FileNotFoundError):
        pass
    return values


def load_fresh_env_file(
    path: Path,
    previous_signature: tuple[int, int, int] | None,
    expected_query: str
) -> dict[str, str]:
    """Load env file if it has changed and matches query."""
    current_signature = file_signature(path)
    if current_signature is None or current_signature == previous_signature:
        return {}
    
    values = load_env_file(path)
    expected_hash = query_sha256(expected_query)
    actual_hash = values.get("QUERY_SHA256", "").strip().lower()
    
    query_matches = actual_hash == expected_hash if actual_hash else values.get("QUERY", "") == expected_query
    if not query_matches:
        return {}
    
    values["QUERY"] = expected_query
    values["QUERY_SHA256"] = expected_hash
    return values


def strip_validated_text(text: str) -> str:
    """Strip VALIDATED markers from response text."""
    lines = text.splitlines()
    result = []
    skip = False
    for line in lines:
        if line.strip() == "--- VALIDATED BEGIN ---":
            skip = True
            continue
        if line.strip() == "--- VALIDATED END ---":
            skip = False
            continue
        if not skip:
            result.append(line)
    return "\n".join(result).strip()


def _enhance_response_with_context(
    response_text: str,
    outcome_code: str,
    provider: str,
    trust_class: str,
    evidence_mode: str,
    final_mode: str,
) -> str:
    """
    Enhance responses with context for unverified or low-confidence answers.
    
    This improves UX by explaining what sources were consulted and why
    the answer may be limited.
    """
    # Don't modify empty responses
    if not response_text or not response_text.strip():
        return response_text
    
    # Check if response is already detailed enough (has sources listed)
    has_source_detail = "sources:" in response_text.lower() or "- " in response_text and any(domain in response_text for domain in [".com", ".org", ".net", ".gov"])
    if has_source_detail and len(response_text) > 300:
        return response_text
    
    # Build context footer for unverified/augmented responses
    context_parts = []
    
    # Add route info if not local
    if final_mode and final_mode != "LOCAL":
        context_parts.append(f"Route: {final_mode}")
    
    # Add provider context if external sources were used
    if provider and provider != "local" and provider != "none":
        context_parts.append(f"Provider: {provider}")
    
    # Add trust/context information for non-verified responses
    if trust_class and trust_class not in ("local", "verified", ""):
        context_parts.append(f"Trust: {trust_class}")
    
    # Add evidence mode info if applicable
    if evidence_mode and evidence_mode not in ("none", ""):
        context_parts.append(f"Evidence: {evidence_mode}")
    
    # If we have context to add, append it
    if context_parts:
        # Remove vague prefix lines that don't add value
        lines = response_text.split("\n")
        new_lines = []
        skip_patterns = [
            "augmented fallback",
            "give me one concrete detail",
            "i will respond precisely",
            "best-effort recovery",
            "not source-backed"
        ]
        
        for line in lines:
            # Skip vague prefix lines but keep the actual content
            if any(vague in line.lower() for vague in skip_patterns):
                continue
            new_lines.append(line)
        
        response_text = "\n".join(new_lines).strip()
        
        # Append context footer
        if response_text:
            response_text += f"\n\n[{' | '.join(context_parts)}]"
    
    return response_text


def execute_plan_python(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
) -> RouterOutcome:
    """
    Execute routing plan using Python implementation.
    
    CRITICAL: This makes routing decisions using Python, but DELEGATES
    execution to the existing governed shell path. It does NOT call
    providers directly.
    """
    # Debug logging
    def _debug_log(msg):
        try:
            with open("/tmp/lucy_memory_debug.log", "a") as f:
                from datetime import datetime
                f.write(f"{datetime.now().isoformat()} {msg}\n")
        except Exception:
            pass
    _debug_log(f"execute_plan_python called with question='{question[:50]}...'")
    
    # Ensure control environment is set from state file if not in env
    ensure_control_env()
    
    start_time = time.time()
    request_id = sha256_text(question)[:16]
    
    try:
        # Step 1: Classify intent (Phase 3)
        classification = classify_intent(question, surface="cli")
        
        # Step 2: Select route (Phase 3)
        decision = select_route(classification, policy=policy)
        
        # Step 3: DELEGATE execution to governed path
        # This preserves authority semantics and truth metadata
        # Uses LUCY_EXEC_PY to control whether to use shell or Python execution
        result = _delegate_execution(question, decision, timeout, classification)
        
        # Override with Python's classification for accurate intent_family
        # (The shell may leave this as "unknown")
        if result.intent_family == "unknown":
            result = RouterOutcome(
                status=result.status,
                outcome_code=result.outcome_code,
                route=result.route,
                provider=result.provider,
                provider_usage_class=result.provider_usage_class,
                intent_family=classification.intent_family,
                confidence=classification.confidence,
                response_text=result.response_text,
                error_message=result.error_message,
                execution_time_ms=result.execution_time_ms,
                request_id=request_id,
            )
        
        execution_time = int((time.time() - start_time) * 1000)
        return result.with_execution_time(execution_time).with_request_id(request_id)
        
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        return RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message=str(e),
            execution_time_ms=execution_time,
            request_id=request_id,
        )


def _delegate_execution(
    question: str,
    decision: RoutingDecision,
    timeout: int,
    classification: ClassificationResult | None = None,
) -> RouterOutcome:
    """
    Delegate execution to either Python ExecutionEngine or shell path.
    
    Controlled by LUCY_EXEC_PY environment variable:
    - LUCY_EXEC_PY=0 or unset: Use shell execute_plan.sh (default, safe)
    - LUCY_EXEC_PY=1: Use Python ExecutionEngine (new)
    - LUCY_EXEC_PY=shadow: Run both, compare, return shell result, log differences
    
    This preserves:
    - Authority chain
    - Truth metadata
    - Provider dispatch governance
    - Evidence mode handling
    """
    exec_mode = os.environ.get("LUCY_EXEC_PY", "0")
    
    if exec_mode == "1":
        # Use Python ExecutionEngine
        return _delegate_execution_to_python(question, decision, timeout, classification)
    elif exec_mode == "shadow":
        # Shadow mode: run both, compare, return shell result
        return _delegate_execution_shadow(question, decision, timeout, classification)
    else:
        # Default: use shell execution
        return _delegate_execution_to_shell(question, decision, timeout)


def _delegate_execution_to_shell(
    question: str,
    decision: RoutingDecision,
    timeout: int,
) -> RouterOutcome:
    """
    Delegate execution to the existing governed shell path.
    
    This preserves:
    - Authority chain
    - Truth metadata
    - Provider dispatch governance
    - Evidence mode handling
    """
    # Ensure state directory exists
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Capture file signatures before execution
    route_sig_before = file_signature(LAST_ROUTE_FILE)
    outcome_sig_before = file_signature(LAST_OUTCOME_FILE)
    
    env = os.environ.copy()
    env["LUCY_QUESTION"] = question
    # Preserve evidence/control settings from parent environment (set by runtime_request.py based on HMI state)
    # Only set defaults if not already present
    if "LUCY_AUGMENTATION_POLICY" not in env:
        env["LUCY_AUGMENTATION_POLICY"] = "fallback_only"
    if "LUCY_EVIDENCE_ENABLED" not in env:
        env["LUCY_EVIDENCE_ENABLED"] = "0"
    if "LUCY_ENABLE_INTERNET" not in env:
        env["LUCY_ENABLE_INTERNET"] = env.get("LUCY_EVIDENCE_ENABLED", "0")
    if "LUCY_CONVERSATION_MODE_FORCE" not in env:
        env["LUCY_CONVERSATION_MODE_FORCE"] = "0"
    if "LUCY_SESSION_MEMORY" not in env:
        env["LUCY_SESSION_MEMORY"] = "0"
    
    # Route to appropriate execution path based on decision
    if decision.route == "CLARIFY":
        # Clarification needed - return early
        return RouterOutcome(
            status="completed",
            outcome_code="clarification_requested",
            route="CLARIFY",
            provider="local",
            provider_usage_class="local",
            intent_family=decision.intent_family,
            confidence=decision.confidence,
            response_text="I need more information to answer this question. Could you clarify what you're looking for?",
        )
    
    # Use execute_plan.sh directly (NOT lucy_chat.sh to avoid circular dependency)
    # This goes through the full governed execution path
    try:
        result = subprocess.run(
            [str(SHELL_EXECUTE_PLAN), question],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(ROOT_DIR),
        )
        
        response_text = strip_validated_text(result.stdout)
        
        # Load metadata from state files (same as runtime_request.py)
        route_meta = load_fresh_env_file(LAST_ROUTE_FILE, route_sig_before, question)
        outcome_meta = load_fresh_env_file(LAST_OUTCOME_FILE, outcome_sig_before, question)
        
        # Extract outcome info
        outcome_code = outcome_meta.get("OUTCOME_CODE", "unknown")
        final_mode = outcome_meta.get("FINAL_MODE", "LOCAL")
        provider = outcome_meta.get("AUGMENTED_PROVIDER_USED", outcome_meta.get("PROVIDER", "local"))
        intent_family = outcome_meta.get("INTENT_FAMILY", decision.intent_family)
        trust_class = outcome_meta.get("TRUST_CLASS", "unknown")
        evidence_mode = outcome_meta.get("MANIFEST_EVIDENCE_MODE", "")
        
        # Enhance unverified/low-confidence responses with context
        response_text = _enhance_response_with_context(
            response_text, outcome_code, provider, trust_class, evidence_mode, final_mode
        )
        
        if result.returncode == 0:
            return RouterOutcome(
                status="completed",
                outcome_code=outcome_code,
                route=final_mode,
                provider=provider,
                provider_usage_class=provider_usage_class_for(provider),
                intent_family=intent_family,
                confidence=decision.confidence,
                response_text=response_text,
            )
        else:
            return RouterOutcome(
                status="failed",
                outcome_code=outcome_code or "execution_error",
                route=final_mode,
                provider=provider,
                provider_usage_class=provider_usage_class_for(provider),
                intent_family=intent_family,
                confidence=decision.confidence,
                response_text=response_text,
                error_message=result.stderr.strip() or "Execution failed",
            )
            
    except subprocess.TimeoutExpired as e:
        return RouterOutcome(
            status="timeout",
            outcome_code="timeout",
            route=decision.route,
            provider=decision.provider,
            provider_usage_class=decision.provider_usage_class,
            intent_family=decision.intent_family,
            confidence=decision.confidence,
            error_message="Request timed out",
        )
    except Exception as e:
        return RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route=decision.route,
            provider=decision.provider,
            provider_usage_class=decision.provider_usage_class,
            intent_family=decision.intent_family,
            confidence=decision.confidence,
            error_message=str(e),
        )


def _delegate_execution_to_python(
    question: str,
    decision: RoutingDecision,
    timeout: int,
    classification: ClassificationResult | None = None,
) -> RouterOutcome:
    """
    Delegate execution to Python ExecutionEngine.
    
    This uses the new Python-based execution engine instead of shell scripts.
    """
    try:
        # Create execution engine with configuration
        engine = ExecutionEngine(config={"timeout": timeout})
        
        # Build context for execution
        # Map mode setting to forced_mode for execution engine
        mode = os.environ.get("LUCY_MODE", "auto").lower()
        forced_mode_map = {
            "auto": "AUTO",
            "online": "FORCED_ONLINE",
            "offline": "FORCED_OFFLINE",
        }
        forced_mode = forced_mode_map.get(mode, "AUTO")
        
        context = {
            "question": question,
            "session_id": os.environ.get("LUCY_SESSION_ID", ""),
            "state_namespace": os.environ.get("LUCY_SHARED_STATE_NAMESPACE", "default"),
            "augmentation_policy": os.environ.get("LUCY_AUGMENTATION_POLICY", "fallback_only"),
            "evidence_enabled": os.environ.get("LUCY_EVIDENCE_ENABLED", "0") == "1",
            "conversation_mode_active": os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "0") == "1",
            "forced_mode": forced_mode,
        }
        
        # Execute using the engine
        # If we don't have classification, create a minimal one from decision
        if classification is None:
            from backend.classify import ClassificationResult
            classification = ClassificationResult(
                intent=decision.intent_family,
                intent_family=decision.intent_family,
                confidence=decision.confidence,
                surface="cli",
                needs_web=False,
            )
        
        result = engine.execute(classification, decision, context, use_python_path=True)
        
        # Persist chat memory turn if memory is enabled
        def _debug_log(msg):
            try:
                with open("/tmp/lucy_memory_debug.log", "a") as f:
                    from datetime import datetime
                    f.write(f"{datetime.now().isoformat()} {msg}\n")
            except Exception:
                pass
        session_mem_env = os.environ.get("LUCY_SESSION_MEMORY", "NOT_SET")
        _debug_log(f"main.py: LUCY_SESSION_MEMORY={session_mem_env}, has_response={bool(result.response_text)}")
        if os.environ.get("LUCY_SESSION_MEMORY") == "1" and result.response_text:
            try:
                # Check both runtime and standard env vars for memory file path
                mem_file = os.environ.get("LUCY_RUNTIME_CHAT_MEMORY_FILE", "").strip()
                if not mem_file:
                    mem_file = os.environ.get("LUCY_CHAT_MEMORY_FILE", "").strip()
                if not mem_file:
                    # Default path
                    mem_file = os.path.expanduser("~/.codex-api-home/lucy/runtime-v8/state/chat_session_memory.txt")
                _debug_log(f"main.py: Persisting to: {mem_file}")
                
                mem_path = Path(mem_file)
                mem_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Format assistant text (clean up markers, truncate)
                assistant_text = (
                    result.response_text.replace("BEGIN_VALIDATED", " ")
                    .replace("END_VALIDATED", " ")
                    .replace("\r", " ")
                    .replace("\n", " ")
                )
                assistant_text = re.sub(r"\s+", " ", assistant_text).strip()
                if len(assistant_text) > 500:
                    assistant_text = assistant_text[:500]
                
                # Read existing content
                existing = ""
                try:
                    existing = mem_path.read_text(encoding="utf-8")
                except FileNotFoundError:
                    pass
                
                # Build new block and append
                block = f"User: {question.strip()}\nAssistant: {assistant_text}\n\n"
                blocks = [item.strip() for item in re.split(r"\n\s*\n", existing) if item.strip()]
                blocks.append(block.strip())
                
                # Keep only last 6 turns
                max_turns = 6
                trimmed = "\n\n".join(blocks[-max_turns:]).strip()
                if trimmed:
                    trimmed += "\n\n"
                
                mem_path.write_text(trimmed, encoding="utf-8")
                _debug_log(f"main.py: Wrote {len(trimmed)} chars to memory file")
            except Exception as e:
                _debug_log(f"main.py: Failed to persist chat memory: {e}")
                logging.warning(f"Failed to persist chat memory: {e}")
        
        # Convert ExecutionResult to RouterOutcome
        return RouterOutcome(
            status=result.status,
            outcome_code=result.outcome_code,
            route=result.route,
            provider=result.provider,
            provider_usage_class=result.provider_usage_class,
            intent_family=classification.intent_family,
            confidence=classification.confidence,
            response_text=result.response_text,
            error_message=result.error_message,
            execution_time_ms=result.execution_time_ms,
        )
        
    except Exception as e:
        logging.error(f"ExecutionEngine failed: {e}")
        # Fall back to shell execution on error
        return _delegate_execution_to_shell(question, decision, timeout)


def _delegate_execution_shadow(
    question: str,
    decision: RoutingDecision,
    timeout: int,
    classification: ClassificationResult | None = None,
) -> RouterOutcome:
    """
    Shadow mode: run both shell and Python execution, compare results.
    
    Returns shell result (trusted) but logs any differences.
    """
    # Run shell execution first (trusted)
    shell_result = _delegate_execution_to_shell(question, decision, timeout)
    
    # Run Python execution
    python_result = _delegate_execution_to_python(question, decision, timeout, classification)
    
    # Compare and log differences
    _log_execution_shadow_diff(question, shell_result, python_result)
    
    # Return shell result (safety first)
    return shell_result


def _log_execution_shadow_diff(
    query: str,
    shell_outcome: RouterOutcome,
    python_outcome: RouterOutcome,
) -> None:
    """Log differences between shell and Python execution to shadow log file."""
    SHADOW_LOG_FILE = Path("/tmp/exec_shadow_diffs.log")
    
    # Determine if results match
    match = (
        shell_outcome.status == python_outcome.status and
        shell_outcome.outcome_code == python_outcome.outcome_code and
        shell_outcome.route == python_outcome.route and
        shell_outcome.provider == python_outcome.provider
    )
    
    # Build log entry
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    entry = {
        "timestamp": timestamp,
        "query": query,
        "shell_outcome": shell_outcome.to_dict(),
        "python_outcome": python_outcome.to_dict(),
        "match": match,
        "differences": []
    }
    
    # Record specific differences
    differences = []
    if shell_outcome.status != python_outcome.status:
        differences.append(f"status: shell={shell_outcome.status}, python={python_outcome.status}")
    if shell_outcome.outcome_code != python_outcome.outcome_code:
        differences.append(f"outcome_code: shell={shell_outcome.outcome_code}, python={python_outcome.outcome_code}")
    if shell_outcome.route != python_outcome.route:
        differences.append(f"route: shell={shell_outcome.route}, python={python_outcome.route}")
    if shell_outcome.provider != python_outcome.provider:
        differences.append(f"provider: shell={shell_outcome.provider}, python={python_outcome.provider}")
    if shell_outcome.response_text != python_outcome.response_text:
        # Truncate response for comparison
        shell_resp = shell_outcome.response_text[:100] + "..." if len(shell_outcome.response_text) > 100 else shell_outcome.response_text
        python_resp = python_outcome.response_text[:100] + "..." if len(python_outcome.response_text) > 100 else python_outcome.response_text
        differences.append(f"response_text differs: shell='{shell_resp}', python='{python_resp}'")
    
    entry["differences"] = differences
    
    # Append to log file
    try:
        with open(SHADOW_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        if not match:
            logging.warning(
                f"[EXEC_SHADOW] MISMATCH for '{query[:50]}...': {', '.join(differences)}"
            )
    except Exception as e:
        logging.error(f"[EXEC_SHADOW] Failed to log difference: {e}")


def execute_plan_shell(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
) -> RouterOutcome:
    """
    Execute routing plan using shell implementation.
    
    This calls lucy_chat.sh and reads metadata from state files.
    """
    start_time = time.time()
    
    # Ensure state directory exists
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Capture file signatures
    route_sig_before = file_signature(LAST_ROUTE_FILE)
    outcome_sig_before = file_signature(LAST_OUTCOME_FILE)
    
    env = os.environ.copy()
    env["LUCY_QUESTION"] = question
    env["LUCY_AUGMENTATION_POLICY"] = policy
    
    try:
        result = subprocess.run(
            [str(SHELL_LUCY_CHAT), question],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=str(ROOT_DIR),
        )
        
        execution_time = int((time.time() - start_time) * 1000)
        response_text = strip_validated_text(result.stdout)
        
        # Load metadata from state files
        route_meta = load_fresh_env_file(LAST_ROUTE_FILE, route_sig_before, question)
        outcome_meta = load_fresh_env_file(LAST_OUTCOME_FILE, outcome_sig_before, question)
        
        # Extract fields with fallbacks
        outcome_code = outcome_meta.get("OUTCOME_CODE", "unknown")
        final_mode = outcome_meta.get("FINAL_MODE", "LOCAL")
        provider = outcome_meta.get("AUGMENTED_PROVIDER_USED", outcome_meta.get("PROVIDER", "local"))
        intent_family = outcome_meta.get("INTENT_FAMILY", "unknown")
        confidence = float(outcome_meta.get("CONFIDENCE", "0")) if outcome_meta.get("CONFIDENCE") else 0.0
        
        return RouterOutcome(
            status="completed" if result.returncode == 0 else "failed",
            outcome_code=outcome_code,
            route=final_mode,
            provider=provider,
            provider_usage_class=provider_usage_class_for(provider),
            intent_family=intent_family,
            confidence=confidence,
            response_text=response_text,
            error_message=result.stderr.strip() if result.returncode != 0 else "",
            execution_time_ms=execution_time,
        )
        
    except subprocess.TimeoutExpired:
        execution_time = int((time.time() - start_time) * 1000)
        return RouterOutcome(
            status="timeout",
            outcome_code="timeout",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message="Request timed out",
            execution_time_ms=execution_time,
        )
    except Exception as e:
        execution_time = int((time.time() - start_time) * 1000)
        return RouterOutcome(
            status="failed",
            outcome_code="router_error",
            route="LOCAL",
            provider="local",
            provider_usage_class="local",
            intent_family="unknown",
            confidence=0.0,
            error_message=str(e),
            execution_time_ms=execution_time,
        )


def execute_plan_shadow(
    question: str,
    policy: str = "fallback_only",
    timeout: int = DEFAULT_TIMEOUT,
) -> RouterOutcome:
    """
    Execute in shadow mode - run both implementations and compare.
    
    Returns shell result (trusted) but logs any differences with classification.
    """
    # Run both implementations
    shell_result = execute_plan_shell(question, policy, timeout)
    python_result = execute_plan_python(question, policy, timeout)
    
    # Compare
    comparison = _compare_outcomes(question, shell_result, python_result)
    
    # Classify the difference
    classification = _classify_difference(comparison, shell_result, python_result)
    comparison.classification = classification
    
    # Log if different
    if not comparison.match:
        _log_shadow_difference(comparison)
    
    # Return shell result (safety first)
    return shell_result


def _compare_outcomes(
    query: str,
    shell: RouterOutcome,
    python: RouterOutcome,
) -> ShadowComparison:
    """Compare shell and Python outcomes."""
    differences = []
    
    if shell.status != python.status:
        differences.append(f"status: shell={shell.status}, python={python.status}")
    
    if shell.route != python.route:
        differences.append(f"route: shell={shell.route}, python={python.route}")
    
    if shell.provider != python.provider:
        differences.append(f"provider: shell={shell.provider}, python={python.provider}")
    
    if shell.intent_family != python.intent_family:
        differences.append(f"intent_family: shell={shell.intent_family}, python={python.intent_family}")
    
    if shell.outcome_code != python.outcome_code:
        differences.append(f"outcome_code: shell={shell.outcome_code}, python={python.outcome_code}")
    
    return ShadowComparison(
        query=query,
        shell_result=shell,
        python_result=python,
        match=len(differences) == 0,
        differences=differences,
    )


def _classify_difference(
    comparison: ShadowComparison,
    shell: RouterOutcome,
    python: RouterOutcome,
) -> str:
    """
    Classify the difference between shell and Python results.
    
    Categories:
    - true_parity: Results are functionally equivalent
    - intended_improvement: Python is better by design (e.g., correct intent_family)
    - suspicious_drift: Unexpected difference that needs investigation
    - hard_regression: Python is worse than shell
    """
    if comparison.match:
        return "true_parity"
    
    # Check for known intended improvements
    # 1. intent_family correction: shell leaves as "unknown", Python sets correctly
    if ("intent_family: shell=unknown, python=" in str(comparison.differences) and
        shell.intent_family == "unknown" and
        python.intent_family != "unknown" and
        shell.route == python.route and
        shell.provider == python.provider and
        shell.status == python.status):
        return "intended_improvement"
    
    # 2. Check for hard regressions
    # Python fails but shell succeeds
    if python.status == "failed" and shell.status == "completed":
        return "hard_regression"
    
    # Python routes differently than shell (potential policy drift)
    if shell.route != python.route:
        # If shell went augmented but Python went local, that's suspicious
        if shell.route == "AUGMENTED" and python.route == "LOCAL":
            return "suspicious_drift"
        # If shell went local but Python went augmented, also suspicious
        if shell.route == "LOCAL" and python.route == "AUGMENTED":
            return "suspicious_drift"
    
    # Default: suspicious drift
    return "suspicious_drift"


def _log_shadow_difference(comparison: ShadowComparison) -> None:
    """Log shadow mode differences to file."""
    try:
        SHADOW_LOG_DIR.mkdir(parents=True, exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        query_hash = sha256_text(comparison.query)[:8]
        log_file = SHADOW_LOG_DIR / f"shadow_diff_{timestamp}_{query_hash}.json"
        
        with open(log_file, "w") as f:
            json.dump(comparison.to_dict(), f, indent=2, default=str)
        
        logging.warning(
            f"[SHADOW] {comparison.classification.upper()}: '{comparison.query[:50]}...': "
            f"{', '.join(comparison.differences)}"
        )
    except Exception as e:
        logging.error(f"[SHADOW] Failed to log difference: {e}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Local Lucy Router (Python)")
    parser.add_argument("question", nargs="?", help="User question")
    parser.add_argument("--policy", default="fallback_only", help="Augmentation policy")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="Request timeout")
    parser.add_argument("--mode", choices=["shell", "python", "shadow", "auto"], 
                        default="auto", help="Execution mode")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()
    
    # Get question from args or stdin
    question = args.question
    if not question:
        if not sys.stdin.isatty():
            question = sys.stdin.read().strip()
        else:
            parser.print_help()
            return 1
    
    # Determine execution mode
    mode = args.mode
    if mode == "auto":
        env_mode = os.environ.get("LUCY_ROUTER_PY", "0")
        if env_mode == "1":
            mode = "python"
        elif env_mode == "shadow":
            mode = "shadow"
        else:
            mode = "shell"
    
    # Determine policy: command line arg > environment variable > default
    policy = args.policy
    if policy == "fallback_only" and os.environ.get("LUCY_AUGMENTATION_POLICY"):
        # Use environment variable if set (from HMI/runtime_request.py)
        policy = os.environ.get("LUCY_AUGMENTATION_POLICY")
    
    # Execute
    if mode == "python":
        result = execute_plan_python(question, policy, args.timeout)
    elif mode == "shadow":
        result = execute_plan_shadow(question, policy, args.timeout)
    else:  # shell
        result = execute_plan_shell(question, policy, args.timeout)
    
    # Output
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        if result.status == "completed":
            print(result.response_text)
        else:
            print(f"Error: {result.error_message}", file=sys.stderr)
            return 1
    
    return 0


# Monkey patch for with_* methods on frozen dataclass
def _with_execution_time(self, ms: int) -> RouterOutcome:
    return RouterOutcome(
        status=self.status,
        outcome_code=self.outcome_code,
        route=self.route,
        provider=self.provider,
        provider_usage_class=self.provider_usage_class,
        intent_family=self.intent_family,
        confidence=self.confidence,
        response_text=self.response_text,
        error_message=self.error_message,
        execution_time_ms=ms,
        request_id=self.request_id,
    )


def _with_request_id(self, req_id: str) -> RouterOutcome:
    return RouterOutcome(
        status=self.status,
        outcome_code=self.outcome_code,
        route=self.route,
        provider=self.provider,
        provider_usage_class=self.provider_usage_class,
        intent_family=self.intent_family,
        confidence=self.confidence,
        response_text=self.response_text,
        error_message=self.error_message,
        execution_time_ms=self.execution_time_ms,
        request_id=req_id,
    )


RouterOutcome.with_execution_time = _with_execution_time
RouterOutcome.with_request_id = _with_request_id


if __name__ == "__main__":
    raise SystemExit(main())
