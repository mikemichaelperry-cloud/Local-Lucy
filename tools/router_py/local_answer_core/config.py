#!/usr/bin/env python3
"""Local answer configuration and result types."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import sys

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root


@dataclass
class LocalAnswerConfig:
    """Configuration for LocalAnswer."""

    model: str = "local-lucy-llama31"
    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 7
    keep_alive: str = "10m"
    num_predict_default: int = 96
    num_predict_chat: int = 192
    num_predict_conversation: int = 96
    num_predict_brief: int = 128
    num_predict_detail: int = 768
    num_predict_long: int = 1536
    num_predict_clarify: int = 48
    num_predict_augmented_default: int = 512
    num_predict_augmented_brief: int = 64
    num_predict_augmented_detail: int = 512
    num_predict_augmented_background: int = 128
    local_max_tokens: int = 2048
    augmented_max_tokens: int = 1536
    evidence_max_tokens: int = 1536
    creative_max_tokens: int = 4096
    self_review_max_tokens: int = 4096
    self_review_context_chars: int = 200000
    # Code-review specialist model settings
    code_review_model: str = "local-lucy-gemma4"
    code_review_specialist_enabled: bool = True
    code_review_temperature: float = 1.0
    code_review_top_p: float = 0.95
    code_review_top_k: int = 64
    code_review_context_target: int = 16384
    code_review_max_tokens: int = 4096
    code_review_context_chars: int = 200000
    embedding_cache_size: int = 1024
    keep_model_warm: bool = True
    max_context_chars: int = 1200
    prompt_guard_tokens: int = 700
    cache_enabled: bool = True
    cache_dir: Path = field(
        default_factory=lambda: Path.home() / ".cache" / "lucy" / "local_repeat"
    )
    cache_ttl_seconds: int = 300
    cache_max_entries: int = 100
    cache_max_bytes: int = 10_000_000
    root_path: Path = field(default_factory=lambda: Path.home() / "lucy-v11")
    conversation_mode_active: bool = False
    conversation_mode_force: bool = False
    conversation_system_block: bool = False
    augmented_context_max_chars_default: int = 320
    augmented_context_max_chars_brief: int = 260
    augmented_context_max_chars_detail: int = 900
    augmented_context_max_chars_background: int = 180
    diag_file: Optional[Path] = None
    diag_run_id: Optional[str] = None
    latency_profile_file: Optional[Path] = None
    identity_trace_file: Optional[Path] = None

    @classmethod
    def from_env(cls) -> LocalAnswerConfig:
        root = Path(
            os.environ.get(
                "LUCY_RUNTIME_AUTHORITY_ROOT",
                os.environ.get("LUCY_ROOT", str(Path.home() / "lucy-v11")),
            )
        )
        cache_dir = os.environ.get("LUCY_LOCAL_REPEAT_CACHE_DIR")

        # If the env var is not set, read the last model selected in the HMI so
        # standalone callers (tests, scripts) report the same identity as the UI.
        model = os.environ.get("LUCY_LOCAL_MODEL", "")
        if not model:
            namespace = os.environ.get(
                "LUCY_RUNTIME_NAMESPACE_ROOT",
                str(lucy_runtime_namespace_root()),
            )
            state_file = Path(namespace) / "state" / "current_state.json"
            try:
                model = json.loads(state_file.read_text(encoding="utf-8")).get("model", "")
            except Exception:
                pass
        if not model or str(model).lower() == "auto":
            model = "local-lucy-llama31"

        return cls(
            model=model,
            ollama_url=os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate"),
            temperature=float(os.environ.get("LUCY_LOCAL_TEMPERATURE", "0")),
            top_p=float(os.environ.get("LUCY_LOCAL_TOP_P", "1")),
            seed=int(os.environ.get("LUCY_LOCAL_SEED", "7")),
            keep_alive=os.environ.get("LUCY_LOCAL_KEEP_ALIVE", "10m"),
            num_predict_default=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_DEFAULT", "128")),
            num_predict_chat=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_CHAT", "256")),
            num_predict_conversation=int(
                os.environ.get("LUCY_LOCAL_NUM_PREDICT_CONVERSATION", "128")
            ),
            num_predict_brief=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_BRIEF", "128")),
            num_predict_detail=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_DETAIL", "768")),
            num_predict_long=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_LONG", "1536")),
            num_predict_clarify=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_CLARIFY", "64")),
            local_max_tokens=int(os.environ.get("LUCY_LOCAL_MAX_TOKENS", "2048")),
            augmented_max_tokens=int(os.environ.get("LUCY_AUGMENTED_MAX_TOKENS", "1536")),
            evidence_max_tokens=int(os.environ.get("LUCY_EVIDENCE_MAX_TOKENS", "1536")),
            creative_max_tokens=int(os.environ.get("LUCY_CREATIVE_MAX_TOKENS", "4096")),
            self_review_max_tokens=int(os.environ.get("LUCY_SELF_REVIEW_MAX_TOKENS", "4096")),
            self_review_context_chars=int(
                os.environ.get("LUCY_SELF_REVIEW_CONTEXT_CHARS", "200000")
            ),
            code_review_model=os.environ.get("LUCY_CODE_REVIEW_MODEL", "local-lucy-gemma4"),
            code_review_specialist_enabled=os.environ.get(
                "LUCY_CODE_REVIEW_SPECIALIST_ENABLED", "1"
            ).lower()
            in ("1", "true", "yes", "on"),
            code_review_temperature=float(os.environ.get("LUCY_CODE_REVIEW_TEMPERATURE", "1.0")),
            code_review_top_p=float(os.environ.get("LUCY_CODE_REVIEW_TOP_P", "0.95")),
            code_review_top_k=int(os.environ.get("LUCY_CODE_REVIEW_TOP_K", "64")),
            code_review_context_target=int(
                os.environ.get("LUCY_CODE_REVIEW_CONTEXT_TARGET", "16384")
            ),
            code_review_max_tokens=int(os.environ.get("LUCY_CODE_REVIEW_MAX_TOKENS", "4096")),
            code_review_context_chars=int(
                os.environ.get("LUCY_CODE_REVIEW_CONTEXT_CHARS", "200000")
            ),
            embedding_cache_size=int(os.environ.get("LUCY_EMBEDDING_CACHE_SIZE", "1024")),
            keep_model_warm=os.environ.get("LUCY_KEEP_MODEL_WARM", "1").lower()
            in ("1", "true", "yes", "on"),
            prompt_guard_tokens=int(os.environ.get("LUCY_LOCAL_PROMPT_GUARD_TOKENS", "700")),
            cache_enabled=os.environ.get("LUCY_LOCAL_REPEAT_CACHE", "1").lower()
            in ("1", "true", "yes", "on"),
            cache_dir=Path(cache_dir) if cache_dir else (root / "cache" / "local_repeat"),
            cache_ttl_seconds=int(os.environ.get("LUCY_LOCAL_REPEAT_CACHE_TTL_S", "300")),
            cache_max_entries=int(os.environ.get("LUCY_LOCAL_REPEAT_CACHE_MAX_ENTRIES", "100")),
            cache_max_bytes=int(os.environ.get("LUCY_LOCAL_REPEAT_CACHE_MAX_BYTES", "10000000")),
            root_path=root,
            conversation_mode_active=os.environ.get("LUCY_CONVERSATION_MODE_ACTIVE", "").lower()
            in ("1", "true", "yes", "on"),
            conversation_mode_force=os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "").lower()
            in ("1", "true", "yes", "on"),
            conversation_system_block=os.environ.get("LUCY_CONVERSATION_SYSTEM_BLOCK", "").lower()
            in ("1", "true", "yes", "on"),
            diag_file=Path(os.environ.get("LUCY_LOCAL_DIAG_FILE", ""))
            if os.environ.get("LUCY_LOCAL_DIAG_FILE")
            else None,
            diag_run_id=os.environ.get("LUCY_LOCAL_DIAG_RUN_ID"),
            latency_profile_file=Path(os.environ.get("LUCY_LATENCY_PROFILE_FILE", ""))
            if os.environ.get("LUCY_LATENCY_PROFILE_FILE")
            else None,
            identity_trace_file=Path(os.environ.get("LUCY_IDENTITY_TRACE_FILE", ""))
            if os.environ.get("LUCY_IDENTITY_TRACE_FILE")
            else None,
        )


@dataclass
class AnswerResult:
    """Result from generating an answer."""

    text: str
    from_cache: bool = False
    cache_age_ms: int = 0
    generation_profile: str = "default"
    duration_ms: int = 0
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LatencyMetrics:
    """Latency tracking for various stages."""

    cache_lookup_ms: int = 0
    prompt_assembly_ms: int = 0
    payload_build_ms: int = 0
    pre_model_ms: int = 0
    ollama_api_call_ms: int = 0
    api_parse_ms: int = 0
    post_processing_ms: int = 0
    total_ms: int = 0
