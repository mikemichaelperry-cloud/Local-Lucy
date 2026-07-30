#!/usr/bin/env python3
"""Local LLM answer engine implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.local_answer_core.config import AnswerResult, LatencyMetrics, LocalAnswerConfig
from router_py.local_answer_core.self_knowledge import (
    FIXED_POLICY_RESPONSES,
    WATER_WET_RESPONSE,
    _MODEL_IDENTITIES,
    _get_active_persona_fragment,
    _get_current_context,
    _get_current_user_identity,
    _is_personal_fact_query,
    _load_family_facts_direct,
    get_self_knowledge,
)
from router_py.local_answer_core.facts import _get_relevant_persistent_facts
from router_py.local_answer_core.utils import _OllamaWarmupThread, get_gpu_free_vram_mb
from router_py.ollama_cleanup import unload_other_lucy_models

try:
    from router_py.context_guard import filter_memory_context
except ImportError:
    try:
        from context_guard import filter_memory_context
    except ImportError:

        def filter_memory_context(question: str, memory_text: str, threshold: float = 0.3) -> str:  # type: ignore[misc]
            return memory_text


def _logger():
    """Return the facade module logger dynamically to avoid circular imports."""
    import sys

    la = sys.modules.get("router_py.local_answer")
    if la is None:
        import router_py.local_answer as la
    return la._local_answer_logger


def _start_heartbeat(model: str) -> None:
    """Start the Ollama heartbeat via the facade module."""
    import sys

    la = sys.modules.get("router_py.local_answer")
    if la is None:
        import router_py.local_answer as la
    la.start_ollama_heartbeat(model)


logger = logging.getLogger(__name__)

# Import tube database (with fallback for standalone execution)
_tube_db = None
try:
    _TUBES_PATH = str(Path(__file__).resolve().parents[2] / "data" / "tubes")
    if _TUBES_PATH not in sys.path:
        sys.path.insert(0, _TUBES_PATH)
    import tube_database

    _tube_db = tube_database
except Exception:
    _tube_db = None

try:
    import aiohttp

    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    from router_py.classify import _is_capability_query
except ImportError:
    try:
        from classify import _is_capability_query
    except ImportError:

        def _is_capability_query(query: str) -> bool:
            return False


class LocalAnswer:
    """Main class for generating local LLM answers."""

    _warmup_done = False
    _warmup_thread: Optional[threading.Thread] = None

    def __init__(self, config: Optional[LocalAnswerConfig] = None):
        self.config = config or LocalAnswerConfig.from_env()
        self._session: Optional[Any] = None
        self._lat_metrics = LatencyMetrics()
        self._total_start_time: Optional[float] = None
        # Start Ollama keep-alive heartbeat to prevent cold-start unload
        _start_heartbeat(self.config.model)

    _semantic_warmup_done = False

    @classmethod
    def warmup_ollama(cls, config: Optional[LocalAnswerConfig] = None) -> None:
        """Send a lightweight request to Ollama to keep the model loaded.

        This runs in a background thread so the caller is not blocked.
        The warmup is skipped if it has already been triggered in this process.
        """
        if cls._warmup_done:
            return
        cls._warmup_done = True
        cfg = config or LocalAnswerConfig.from_env()
        if not cfg.model:
            return
        api_url = os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate")
        keep_alive = os.environ.get("LUCY_LOCAL_KEEP_ALIVE", "10m")
        body = {
            "model": cfg.model,
            "prompt": "",
            "stream": False,
            "keep_alive": keep_alive,
            "options": {"num_predict": 0},
        }

        def _ping():
            try:
                req = urllib.request.Request(
                    api_url,
                    data=json.dumps(body).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=60.0) as resp:
                    resp.read()
            except Exception:
                pass

        threading.Thread(target=_ping, daemon=True).start()

        # Also warm up the semantic classifier in the background so the first
        # real query does not pay the MiniLM import/load cost.
        cls._warmup_semantic_model()

    @classmethod
    def _warmup_semantic_model(cls) -> None:
        """Load the MiniLM semantic model in a daemon thread.

        The model is used by the policy router to detect personal/family,
        medical, and veterinary queries.  Loading it eagerly on startup hides
        the ~6 s import/initialization cost from the first user query.
        """
        if cls._semantic_warmup_done:
            return
        cls._semantic_warmup_done = True

        def _load():
            try:
                from router_py.policy import _get_semantic_model

                _get_semantic_model()
            except Exception:
                pass

        threading.Thread(target=_load, daemon=True, name="semantic-model-warmup").start()

    @classmethod
    def start_recurring_warmup(cls, config: Optional[LocalAnswerConfig] = None) -> None:
        """Start a background thread that pings Ollama periodically.

        This keeps the local model loaded in VRAM between queries, eliminating
        the ~2.7 s cold-start latency after idle periods.

        Environment variables:
            LUCY_WARMUP_ENABLED: "1" (default) or "0" to disable.
            LUCY_WARMUP_INTERVAL_S: Seconds between pings (default 300 = 5 min).
            LUCY_WARMUP_KEEP_ALIVE: keep_alive string passed to Ollama
                (default: same as LUCY_LOCAL_KEEP_ALIVE or "10m").

        The thread is a daemon, so it will not block process exit.
        Calling this method multiple times with the same model is safe — only
        one thread is started. Calling it with a different model stops the old
        thread and starts a new one for the new model, so the previous model is
        not kept warm after a switch.
        """
        enabled = os.environ.get("LUCY_WARMUP_ENABLED", "1").lower() in ("1", "true", "yes", "on")
        if not enabled:
            return

        interval_s = int(os.environ.get("LUCY_WARMUP_INTERVAL_S", "300"))
        if interval_s <= 0:
            return

        cfg = config or LocalAnswerConfig.from_env()
        if not cfg.model:
            return

        if (
            cls._warmup_thread is not None
            and cls._warmup_thread.is_alive()
            and cls._warmup_thread.model == cfg.model
        ):
            return

        if cls._warmup_thread is not None:
            cls._warmup_thread.stop()
            cls._warmup_thread.join(timeout=1.0)

        api_url = os.environ.get("LUCY_OLLAMA_API_URL", cfg.ollama_url)
        keep_alive = os.environ.get(
            "LUCY_WARMUP_KEEP_ALIVE",
            os.environ.get("LUCY_LOCAL_KEEP_ALIVE", cfg.keep_alive),
        )

        thread = _OllamaWarmupThread(
            interval_s=interval_s,
            model=cfg.model,
            api_url=api_url,
            keep_alive=keep_alive,
        )
        cls._warmup_thread = thread
        thread.start()

    def _now_ms(self) -> int:
        """Current time in milliseconds."""
        return int(time.time() * 1000)

    async def _get_session(self) -> Any:
        """Get or create aiohttp session."""
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp is required for async operations")
        # Recreate session if it was closed or its event loop died
        # (e.g. pytest-asyncio creates a new loop per test)
        loop_closed = (
            self._session is not None
            and hasattr(self._session, "_loop")
            and self._session._loop.is_closed()
        )
        if self._session is None or self._session.closed or loop_closed:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(
                connector=connector, timeout=timeout, headers={"Content-Type": "application/json"}
            )
        return self._session

    def _diag_append(self, metric: str, value: Any) -> None:
        """Append diagnostic metric."""
        if self.config.diag_file and self.config.diag_run_id:
            try:
                self.config.diag_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config.diag_file, "a") as f:
                    f.write(f"run={self.config.diag_run_id}\tmetric={metric}\tvalue={value}\n")
            except Exception as e:
                logger.debug(f"Failed to write diag: {e}")

    def _latprof_append(self, stage: str, substage: str, duration_ms: int) -> None:
        """Append latency profile data."""
        if self.config.latency_profile_file:
            try:
                self.config.latency_profile_file.parent.mkdir(parents=True, exist_ok=True)
                with open(self.config.latency_profile_file, "a") as f:
                    f.write(f"{stage}\t{substage}\t{duration_ms}\n")
            except Exception as e:
                logger.debug(f"Failed to write latprof: {e}")

    def _normalize_query(self, query: str) -> str:
        """Normalize query for matching."""
        q = query.strip()
        q = re.sub(r"\s+", " ", q)
        q = q.lower()
        return q

    def _contains_word(self, text: str, word: str) -> bool:
        """Check if word appears as whole word in text.

        DEPRECATED: use pre-compiled pattern tuples (_MEDICAL_PATTERNS,
        _TIME_SENSITIVE_PATTERNS) for hot paths.
        """
        pattern = rf"(^|[^a-z0-9]){re.escape(word)}([^a-z0-9]|$)"
        return bool(re.search(pattern, text, re.IGNORECASE))

    def _is_memory_context_allowed(self, query: str) -> bool:
        """Check if memory context should be used for this query."""
        q = query.strip().lower()
        backchannel_pattern = r"^[\s]*(?:hmm+|hm+|uh+h*|uh-?huh|huh+|ok|okay|k|right|sure|thanks|thank you|cool|nice|interesting|weird|ugh|meh|useless)[\s]*$"
        if re.match(backchannel_pattern, q, re.IGNORECASE):
            return False
        vague_patterns = [
            r"^[\s]*(?:that(?: is|\'s)? annoying|that annoyed me|what(?:\'s| is) happening)[\s]*$"
        ]
        for pattern in vague_patterns:
            if re.match(pattern, q, re.IGNORECASE):
                return False
        return True

    def _is_explicit_memory_query(self, query: str) -> bool:
        """Return True when the user is explicitly asking about prior conversation."""
        q = query.strip().lower()
        memory_phrases = (
            r"\bwhat\s+did\s+we\s+(discuss|talk|chat)\s+(earlier|before|about)",
            r"\bwhat\s+were\s+we\s+(discussing|talking|chatting)\s+(about|earlier|before)",
            r"\bwhat\s+did\s+i\s+(say|mention|ask)\s+(earlier|before)",
            r"\bwhat\s+did\s+you\s+(say|mention|tell\s+me)\s+(earlier|before)",
            r"\bwhat\s+was\s+(i|we)\s+(saying|talking|discussing)\s+(about|earlier|before)",
            r"\bremind\s+me\s+what\s+we\s+(discussed|talked|chatted)\s+(about|earlier|before)",
            r"\bwhat\s+was\s+our\s+(conversation|discussion)\s+about",
            r"\bwhat\s+have\s+we\s+been\s+(discussing|talking)\s+about",
        )
        return any(re.search(p, q) for p in memory_phrases)

    def _context_reset_requested(self, query: str) -> bool:
        """Check if user wants to reset context."""
        pattern = r"(^|[^\w_])(new question|another question|unrelated|separately|different topic|switch topic|change topic|start over|reset context)([^\w_]|$)"
        return bool(re.search(pattern, query, re.IGNORECASE))

    def _context_followup_requested(self, query: str) -> bool:
        """Check if this is a context followup query."""
        if self._context_reset_requested(query):
            return False
        q = query.strip().lower()
        if re.match(r"^[\s]*(and|also|then|so)\s+", q):
            return True
        followup_phrases = [
            r"^[\s]*(what about|how about|about that|on that|on this|regarding that|regarding this|more on that|tell me more about that|continue|go on|elaborate|expand|follow up|follow-up)\b",
            # Additional patterns for "more detail" type followups
            r"(be more|give me more|include|add|what are the|can you be more)\s+(detailed|detail|details|specific|specifics|quantities|quantity|information|info)",
            r"(more\s+(details|detail|information|info|specifics|context|quantities))",
            r"(be more|more)\s+(specific|detailed|precise)",
            # Personal reference patterns - user asking about themselves
            r"^[\s]*(what is my|what are my|what\'s my|who am i|do you know my|remember my|you said my)",
            r"^[\s]*(my name|my favorite|my preference|my choice|my color|my age|my location)",
        ]
        for pattern in followup_phrases:
            if re.search(pattern, q):
                return True
        if re.search(
            r"(^|[^\w_])(previous answer|last answer|last response|earlier answer|as you said|you said earlier|same topic)([^\w_]|$)",
            q,
        ):
            return True
        return False

    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count."""
        if not text:
            return 0
        return (len(text) + 3) // 4

    def _sanitize_model_output(self, text: str) -> str:
        """Sanitize model output."""
        text = text.replace("\r", "")
        lines = []
        for line in text.split("\n"):
            if not re.match(r"^[\s]*(User|Assistant):[\s]", line, re.IGNORECASE):
                lines.append(line)
        text = "\n".join(lines)
        text = re.sub(r"\s*User:[\s].*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*Assistant:[\s].*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.rstrip()
        return text

    def _strip_identity_preamble(self, text: str, query: str = "") -> str:
        """Strip identity preamble from response — except when asked about identity."""
        # Don't strip if the user explicitly asked who we are
        identity_queries = [
            r"\bwho\s+are\s+you",
            r"\bwhat\s+is\s+your\s+name",
            r"\bwhat\s+are\s+you",
            r"\btell\s+me\s+about\s+yourself",
            r"\bintroduce\s+yourself",
        ]
        q_lower = query.lower()
        if any(re.search(p, q_lower) for p in identity_queries):
            return text.strip()
        # Remove common self-intro boilerplate
        text = re.sub(r"^I am Local Lucy[^.]*\.\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^I will do my best[^.]*\.\s*", "", text, flags=re.IGNORECASE)
        text = text.strip()
        return text

    def _sanitize_identity_memory_fragment(self, text: str) -> str:
        """Sanitize identity memory fragment."""
        text = re.sub(
            r"\s+what would you like to know or discuss about (him|her|them)\??\.?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"\s+what would you like to know\??\.?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+could you provide more context.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+i don't have any information.*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[.!?]+$", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ------------------------------------------------------------------
    # Deterministic personal/family/pet fact resolver
    # ------------------------------------------------------------------

    def _is_personal_family_query(self, query: str) -> bool:
        """Return True if the query is a direct factual lookup about stored
        personal/family/pet facts (NOT a medical symptom, advice request, or
        open-ended reflection)."""
        q = query.strip().lower()
        # Must contain one of these ownership/identity anchors
        has_anchor = any(
            k in q
            for k in (
                "my children",
                "my child",
                "my son",
                "my daughter",
                "my kids",
                "my grandchild",
                "my grandson",
                "my granddaughter",
                "my dog",
                "my pet",
                "my partner",
                "my wife",
                "my husband",
                "my spouse",
                "who is ",
                "who is rachel",
                "who am i",
                "my name",
                "do i have children",
                "do i have grandchildren",
                "do i have a dog",
                "do i have a pet",
                "who is my partner",
                "who is my life partner",
            )
        )
        if not has_anchor:
            return False
        # Reject medical/vet symptom queries that happen to contain pet keywords
        symptom_guard = any(
            k in q
            for k in (
                "vomiting",
                "vomit",
                "diarrhea",
                "sick",
                "ill",
                "hurt",
                "injured",
                "bleeding",
                "cough",
                "fever",
                "pain",
                "symptom",
                "what should i do",
                "what do i do",
                "help me",
                "emergency",
                "vet ",
                "veterinar",
                "doctor",
                "medicine",
                "medication",
            )
        )
        if symptom_guard:
            return False
        # Reject broad conversational / open-ended / creative patterns
        broad_guard = any(
            k in q
            for k in (
                "tell me a story",
                "tell me about",
                "write a",
                "compose a",
                "how are my",
                "how is my",
                "what do you think about my",
                "advice",
                "suggest",
                "recommend",
                "feeling",
                "doing lately",
                "up to",
            )
        )
        if broad_guard:
            return False
        return True

    def _resolve_personal_family_fact(self, query: str) -> Optional[str]:
        """Deterministic resolver for direct personal/family/pet fact queries.

        Loads family facts from SQLite and returns a template answer when the
        query is a straightforward factual lookup.  Returns None for all other
        queries so normal LLM generation proceeds.
        """
        if not self._is_personal_family_query(query):
            return None

        facts = _load_family_facts_direct()
        if not facts:
            return None

        q = query.strip().lower()

        # --- Children ---
        if any(
            k in q
            for k in (
                "my children",
                "my child",
                "my son",
                "my daughter",
                "my kids",
                "do i have children",
                "do i have kids",
            )
        ):
            child_facts = [
                f
                for f in facts
                if any(k in f.lower() for k in ("children", "son", "daughter", "child"))
            ]
            if not child_facts:
                return None
            if "do i have" in q:
                return "Yes. " + " ".join(child_facts)
            return " ".join(child_facts)

        # --- Grandchildren ---
        if any(
            k in q
            for k in ("my grandchild", "my grandson", "my granddaughter", "do i have grandchildren")
        ):
            grand_facts = [
                f
                for f in facts
                if any(k in f.lower() for k in ("grandchild", "grandson", "granddaughter"))
            ]
            if not grand_facts:
                return None
            if "do i have" in q:
                return "Yes. " + " ".join(grand_facts)
            return " ".join(grand_facts)

        # --- Dog / Pet ---
        if any(k in q for k in ("my dog", "my pet", "do i have a dog", "do i have a pet")):
            pet_facts = [f for f in facts if any(k in f.lower() for k in ("dog", "pet"))]
            if not pet_facts:
                return None
            if "do i have" in q:
                return "Yes. " + " ".join(pet_facts)
            return " ".join(pet_facts)

        # --- Partner / Spouse ---
        if any(
            k in q
            for k in (
                "my partner",
                "my wife",
                "my husband",
                "my spouse",
                "who is my partner",
                "who is my life partner",
            )
        ):
            partner_facts = [
                f
                for f in facts
                if any(k in f.lower() for k in ("partner", "wife", "husband", "spouse"))
                and "dog" not in f.lower()
            ]
            if not partner_facts:
                return None
            return " ".join(partner_facts)

        # --- Specific person lookup ("Who is Sarah?") ---
        if "who is " in q:
            # Extract the name after "who is"
            m = re.search(r"who is\s+([a-zA-Z]+)", q)
            if m:
                name = m.group(1).lower()
                person_facts = [f for f in facts if name in f.lower()]
                if person_facts:
                    return " ".join(person_facts)

        # --- Identity ("Who am I?") ---
        if "who am i" in q or "my name" in q:
            identity_facts = [
                f for f in facts if any(k in f.lower() for k in ("name is", "you are", "your name"))
            ]
            if identity_facts:
                return " ".join(identity_facts)

        # No deterministic match — fall through to LLM
        return None

    def _apply_augmented_completion_guard(self, text: str) -> tuple[str, bool, str]:
        """
        Post-process AUGMENTED route responses to ensure complete sentences.

        Ported from shell: finalize_augmented_output_contract + apply_augmented_completion_guard

        Returns:
            Tuple of (finalized_text, triggered, reason)
            - triggered: True if guard modified the text
            - reason: one of 'none', 'removed_dangling_conjunction',
                     'trimmed_to_last_complete_sentence', 'closed_truncated_fragment'
        """
        import re

        if not text:
            return ("", False, "empty")

        original = text
        reason = "none"

        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Remove dangling conjunctions: ", and." -> ".", ", or." -> "."
        cleaned = re.sub(r",\s*(and|or)\.$", ".", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+(and|or)\.$", ".", cleaned, flags=re.IGNORECASE)
        if cleaned != text:
            reason = "removed_dangling_conjunction"
            text = cleaned

        # Check if text already ends with sentence terminator
        if re.search(r'[.!?](?:["\'\)\]]+)?$', text):
            triggered = text != original
            return (text, triggered, reason)

        # Find last complete sentence (>=40 chars)
        matches = list(re.finditer(r'[.!?](?:["\'\)\]]+)?(?:\s|$)', text))
        candidate = ""
        for match in matches:
            snippet = text[: match.end()].strip()
            if len(snippet) >= 40:
                candidate = snippet

        if candidate:
            # Clean up the candidate
            candidate = re.sub(r",\s*(and|or)\.$", ".", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"\s+(and|or)\.$", ".", candidate, flags=re.IGNORECASE)
            if candidate != original:
                reason = "trimmed_to_last_complete_sentence"
            return (candidate, True, reason)

        # No complete sentence found - close the fragment
        text = text.rstrip(" ,;:-") + "."
        text = re.sub(r",\s*(and|or)\.$", ".", text, flags=re.IGNORECASE)
        text = re.sub(r"\s+(and|or)\.$", ".", text, flags=re.IGNORECASE)
        if text != original:
            reason = "closed_truncated_fragment"
        return (text, True, reason)

    def _cache_key(self, query: str, variant: str, fact_revision: str = "") -> str:
        """Generate cache key. Includes SELF_KNOWLEDGE hash so prompt
        changes automatically invalidate old cached entries.
        For personal/family/pet queries, also includes a fact revision
        so adding/editing/deleting facts busts the cache.
        For persona queries, includes the active identity so switching
        personas does not reuse a differently-styled cached response."""
        # Hash the self-knowledge text so any prompt-template change
        # busts the cache without manual cleanup.
        sk_text = get_self_knowledge(self.config.model)
        sk_hash = hashlib.sha256(sk_text.encode()).hexdigest()[:16]
        active_identity = _get_current_user_identity() or ""
        key_string = f"{self.config.model}|{sk_hash}|{active_identity}|{variant}|{query}"
        if fact_revision:
            key_string += f"|{fact_revision}"
        return hashlib.sha256(key_string.encode()).hexdigest()

    def _cache_load(
        self, query: str, variant: str, fact_revision: str = ""
    ) -> Optional[Tuple[str, int]]:
        """Load from cache."""
        if not self.config.cache_enabled:
            return None
        key = self._cache_key(query, variant, fact_revision)
        meta_file = self.config.cache_dir / f"{key}.meta"
        text_file = self.config.cache_dir / f"{key}.txt"
        if not meta_file.exists() or not text_file.exists():
            return None
        try:
            meta = {}
            with open(meta_file, "r") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        meta[k] = v
            created_ts = int(meta.get("CREATED_TS", 0))
            cached_model = meta.get("MODEL", "")
            if cached_model != self.config.model:
                return None
            now = int(time.time())
            age_s = now - created_ts
            if age_s >= self.config.cache_ttl_seconds:
                meta_file.unlink(missing_ok=True)
                text_file.unlink(missing_ok=True)
                return None
            with open(text_file, "r") as f:
                text = f.read()
            if not text.strip():
                return None
            now_ts = time.time()
            os.utime(meta_file, (now_ts, now_ts))
            os.utime(text_file, (now_ts, now_ts))
            return (text, age_s * 1000)
        except Exception as e:
            logger.debug(f"Cache load failed: {e}")
            return None

    def _cache_store(
        self,
        query: str,
        variant: str,
        text: str,
        fact_revision: str = "",
    ) -> None:
        """Store in cache."""
        if not self.config.cache_enabled or not text.strip():
            return
        try:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
            key = self._cache_key(query, variant, fact_revision)
            meta_file = self.config.cache_dir / f"{key}.meta"
            text_file = self.config.cache_dir / f"{key}.txt"
            with open(meta_file, "w") as f:
                f.write(f"CREATED_TS={int(time.time())}\n")
                f.write(f"MODEL={self.config.model}\n")
            with open(text_file, "w") as f:
                f.write(text)
            self._cache_prune()
        except Exception as e:
            logger.debug(f"Cache store failed: {e}")

    def _cache_prune(self) -> None:
        """Prune old cache entries by count and total byte size."""
        try:
            if not self.config.cache_dir.exists():
                return
            meta_files = sorted(
                self.config.cache_dir.glob("*.meta"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            # Prune by entry count
            for meta_file in meta_files[self.config.cache_max_entries :]:
                text_file = meta_file.with_suffix(".txt")
                meta_file.unlink(missing_ok=True)
                text_file.unlink(missing_ok=True)
            # Prune by total byte size (oldest first)
            all_meta = sorted(
                self.config.cache_dir.glob("*.meta"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            total_bytes = 0
            to_remove = []
            for mf in all_meta:
                tf = mf.with_suffix(".txt")
                size = mf.stat().st_size + (tf.stat().st_size if tf.exists() else 0)
                total_bytes += size
                if total_bytes > self.config.cache_max_bytes:
                    to_remove.append((mf, tf))
            for mf, tf in to_remove:
                mf.unlink(missing_ok=True)
                tf.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Cache prune failed: {e}")

    def _write_identity_trace(self, loaded: str, source: str) -> None:
        """Write identity trace file."""
        if not self.config.identity_trace_file:
            return
        try:
            self.config.identity_trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.identity_trace_file, "w") as f:
                f.write(f"IDENTITY_CONTEXT_LOADED={loaded}\n")
                f.write(f"IDENTITY_CONTEXT_SOURCE={source}\n")
        except Exception as e:
            logger.debug(f"Identity trace write failed: {e}")

    def _get_policy_response(self, policy_id: str) -> Optional[str]:
        """Get fixed policy response if applicable."""
        if policy_id in FIXED_POLICY_RESPONSES:
            return FIXED_POLICY_RESPONSES[policy_id]
        if policy_id == "water_wet_structured":
            return WATER_WET_RESPONSE
        return None

    def _is_budget_detail(self, query: str) -> bool:
        """Check if query requests detailed answer."""
        patterns = [
            r"(^|[^\w_])(in detail|detailed|deep dive|thorough|comprehensive|step by step|step-by-step|walk me through|with examples|give examples|more detail|more details|long answer|full answer|complete answer|full recipe|complete recipe|full guide|complete guide)([^\w_]|$)"
        ]
        return any(re.search(p, query, re.IGNORECASE) for p in patterns)

    def _set_generation_profile(
        self, route_mode: str, output_mode: str, query: str
    ) -> Tuple[str, int, str]:
        """Set generation profile and token budget for the request."""
        route = route_mode.upper()
        output = output_mode.upper()
        q = self._normalize_query(query)
        is_creative = self._is_creative_writing_query(q)

        if route == "SELF_REVIEW":
            return (
                "self_review",
                self.config.code_review_max_tokens,
                "- Provide a thorough, broad, balanced code review. "
                "Coverage before depth. Identify components, audit broadly, "
                "then investigate the most consequential findings.",
            )

        # Phase 7: per-route token budgets from environment/config.
        local_budget = self.config.local_max_tokens
        augmented_budget = self.config.augmented_max_tokens
        evidence_budget = self.config.evidence_max_tokens
        creative_budget = self.config.creative_max_tokens

        # Detect explicit word-count requests (e.g., "500-word story", "1000 words")
        word_match = re.search(r"(\d+)[\s\-]*(?:word|words)", q)
        if word_match:
            requested_words = int(word_match.group(1))
            # Token estimate: ~4x headroom for visible output. Some models (e.g.
            # Gemma 4) use a richer tokenizer or emit formatting tokens, so the
            # previous 2.5x estimate was insufficient for creative writing.
            if route in {"AUGMENTED", "EVIDENCE"}:
                max_tokens = evidence_budget if route == "EVIDENCE" else augmented_budget
            elif is_creative:
                max_tokens = creative_budget
            else:
                max_tokens = self.config.num_predict_long
            num_predict = min(int(requested_words * 4.0), max_tokens)
            return ("chat_long", num_predict, f"- Write approximately {requested_words} words.")

        detail_patterns = [
            r"(in detail|detailed|deep dive|thorough|comprehensive|step by step|step-by-step|walk me through|with examples|give examples|more detail|more details|long answer|full answer|complete answer|full recipe|complete recipe|full guide|complete guide)",
        ]
        requests_detail = any(re.search(p, q) for p in detail_patterns)

        brief_patterns = [
            r"(briefly|brief|concise|short answer|one sentence|single sentence|two sentences|summarize|short paragraph)"
        ]
        requests_brief = any(re.search(p, q) for p in brief_patterns)

        if route in {"AUGMENTED", "EVIDENCE"}:
            max_tokens = evidence_budget if route == "EVIDENCE" else augmented_budget
            if requests_detail:
                return (
                    "augmented_detail",
                    min(self.config.num_predict_augmented_detail, max_tokens),
                    "- Give provisional answer from tentative background.",
                )
            elif requests_brief:
                return (
                    "augmented_brief",
                    min(self.config.num_predict_augmented_brief, max_tokens),
                    "- Give short provisional answer.",
                )
            elif self._is_background_overview_request(q):
                return (
                    "augmented_background",
                    min(self.config.num_predict_augmented_background, max_tokens),
                    "- Give provisional answer from background.",
                )
            else:
                # Default route budget from the Phase 7 env values.
                return (
                    "augmented",
                    max_tokens,
                    "- Give provisional answer from tentative background.",
                )

        if route == "CLARIFY":
            return (
                "clarify",
                self.config.num_predict_clarify,
                "- Ask one short clarifying question only.",
            )

        if output == "BRIEF" or requests_brief:
            return (
                "brief",
                min(self.config.num_predict_brief, local_budget),
                "- Prefer one short sentence if possible.",
            )

        if output == "CONVERSATION":
            return (
                "conversation",
                min(self.config.num_predict_conversation, local_budget),
                "- Prefer two or three short sentences.",
            )

        if is_creative:
            return (
                "chat",
                creative_budget,
                "- Prefer at most two short sentences.",
            )

        # Default LOCAL simple Q&A uses the Phase 7 local token budget.
        return ("chat", local_budget, "- Prefer at most two short sentences.")

    def _is_background_overview_request(self, query: str) -> bool:
        """Check if query is a background/overview request."""
        q = query.lower()
        # Only match specific patterns, not simple "what is X" questions
        overview_starts = [
            "who is ",
            "who was ",
            "tell me about ",
            "give me an overview of ",
            "overview of ",
            "background on ",
            "history of ",
            "biography of ",
        ]
        for start in overview_starts:
            if q.startswith(start):
                return True
        return False

    def _check_807_question(self, query: str) -> Optional[str]:
        """Check for 807 tube question."""
        q = self._normalize_query(query)
        if (
            re.search(r"807", q)
            and re.search(r"(pair|two|2)", q)
            and re.search(r"(push[ -]?pull|pp)", q)
            and re.search(r"(class )?ab1", q)
            and re.search(r"(power|output|watt)", q)
        ):
            if re.search(r"400", q):
                return "For a pair of 807s in push-pull class AB1 at about 400 V plate, expect roughly 25-35 W total output (around 30 W typical). This is pair total, not per-tube."
            else:
                return "For a pair of 807s in push-pull class AB1, expect roughly 25-35 W total output for the pair under typical conditions. This is pair total, not per-tube."
        return None

    def _is_tube_token_match(self, q: str, tube_type: str) -> bool:
        """Check if tube_type appears as a standalone token in q, not a substring.

        Prevents false positives like tube '50' matching '500 word story'.
        """
        t_lower = tube_type.lower()
        idx = q.find(t_lower)
        while idx != -1:
            before_ok = idx == 0 or not q[idx - 1].isalnum()
            after_ok = idx + len(t_lower) == len(q) or not q[idx + len(t_lower)].isalnum()
            if before_ok and after_ok:
                return True
            idx = q.find(t_lower, idx + 1)
        return False

    def _lookup_tube_database(self, query: str) -> Optional[str]:
        """Look up tube parameters from the local tube database.

        If the query mentions a known tube type, return formatted specs.
        Falls back silently if the database is missing or the tube is unknown.
        Uses the longest match to disambiguate suffixes (e.g. 6V6GT > 6V6).
        """
        if _tube_db is None:
            return None

        db_path = _tube_db.get_db_path()
        if not db_path.exists():
            return None

        try:
            conn = _tube_db.init_db()
            all_types = _tube_db.list_all_types(conn, verified_only=True)
        except Exception:
            return None

        q = self._normalize_query(query)

        # Skip tube lookup for word-count requests (e.g. "500 word story",
        # "6550 word essay") where numbers are word counts, not tube types.
        if re.search(r"\d+\s*(?:word|words)", q):
            conn.close()
            return None

        # Find the longest matching tube type that appears as a standalone token
        # (e.g. "50" must not match "500 word story")
        matches = [t for t in all_types if self._is_tube_token_match(q, t)]
        if not matches:
            conn.close()
            return None
        matches.sort(key=len, reverse=True)
        tube_type = matches[0]

        try:
            tube = _tube_db.lookup_tube(conn, tube_type, verified_only=True)
        except Exception:
            tube = None
        finally:
            conn.close()

        if not tube:
            return None
        return _tube_db.format_tube_for_model(tube)

    def _is_budget_brief(self, query: str) -> bool:
        """Check if query requests brief answer."""
        patterns = [
            r"(briefly|brief|concise|short answer|one sentence|single sentence|two sentences|summarize|short paragraph)"
        ]
        return any(re.search(p, query, re.IGNORECASE) for p in patterns)

    def _is_creative_writing_query(self, query: str) -> bool:
        """Detect creative-writing requests that must bypass all short-circuits.

        Prevents tube-database, 807-fixed, and policy overrides from hijacking
        stories, poems, fiction, etc.
        """
        q = query.lower()
        creative_verbs = [
            "write",
            "compose",
            "craft",
            "create",
            "draft",
            "pen",
            "tell me",
            "read me",
            "share",
            "make up",
            "imagine",
        ]
        creative_nouns = [
            "story",
            "poem",
            "essay",
            "novel",
            "fiction",
            "script",
            "play",
            "song",
            "tale",
            "narrative",
            "fable",
            "myth",
            "legend",
            "fanfic",
            "novella",
            "short story",
            "screenplay",
            "script",
            "lyric",
            "rap",
            "haiku",
            "limerick",
            "sonnet",
            "ballad",
            "epic",
        ]
        has_verb = any(v in q for v in creative_verbs)
        has_noun = any(n in q for n in creative_nouns)
        return has_verb and has_noun

    def _build_prompt(
        self,
        query: str,
        session_memory: str,
        generation_profile: str,
        budget_instruction: str,
        conversation_mode_active: bool,
        conversation_system_block: bool,
        augmented_context: str = "",
    ) -> str:
        """Build the prompt for Ollama.

        The Modelfile SYSTEM prompt already covers identity, first-person rules,
        and hard constraints.  This runtime prompt adds only query-specific
        context: memory, augmented evidence, tone, and budget.
        """
        # Persistent facts are authoritative ONLY for questions about the user,
        # their family, or their pets. For general-knowledge questions we skip
        # them entirely so a semantically-similar fact (e.g. "Mike is 66") does
        # not trick the model into saying "I don't know" about Bill Clinton.
        is_personal_query = _is_personal_fact_query(query)
        persistent_facts: list[str] = []

        if is_personal_query:
            try:
                persistent_facts = _get_relevant_persistent_facts(query, limit=3)
                logger.info(
                    f"[FACTS] Retrieved {len(persistent_facts)} persistent facts for query: {query[:60]}"
                )
                for i, f in enumerate(persistent_facts):
                    logger.info(f"[FACTS]  #{i + 1}: {f[:100]}")
            except Exception as e:
                persistent_facts = []
                logger.warning(
                    f"[FACTS] Failed to load relevant persistent facts: {e}", exc_info=True
                )

            # Fallback: if semantic retrieval returned nothing, try direct SQLite load
            # for family/personal queries. This bypasses embedding failures.
            if not persistent_facts:
                persistent_facts = _load_family_facts_direct()
                logger.info(
                    f"[FACTS] Direct fallback loaded {len(persistent_facts)} facts for personal/family query"
                )

            # Guard against session-memory poisoning for personal/family queries.
            # When explicit persistent facts are loaded, previous assistant turns
            # in session memory may contain hallucinated answers that the model
            # will repeat.  Suppress session memory for these queries so the
            # model answers ONLY from the authoritative facts.
            if persistent_facts and session_memory.strip():
                logger.info(
                    "[GUARD] Suppressing session memory for personal/family query with loaded facts"
                )
                session_memory = ""

        parts: list[str] = []

        # Memory block (only when memory is active)
        if session_memory.strip():
            parts.append(
                "The user has enabled session memory. Use the facts below to answer follow-up questions.\n\n"
                f"{session_memory}"
            )

        # Conversation mode directive
        if conversation_mode_active and conversation_system_block:
            parts.append(
                "[CONVERSATION_MODE: sharp]\n"
                "Take a position early. One hedge max. One concrete example. Clear takeaway."
            )

        if persistent_facts:
            facts_block = "\n".join(f"- {f}" for f in persistent_facts)
            parts.append(
                "[PERSISTENT FACTS — user-provided, authoritative]\n"
                "These facts were supplied by the user. Answer questions about the user, "
                "their family, and their pets using ONLY these facts. Do not blend with "
                "outside knowledge. If the facts do not answer the question, say so.\n"
                "CRITICAL: State the facts directly. Do NOT apologize, hedge, or claim you "
                "do not have the information. The user explicitly provided these facts.\n\n"
                f"{facts_block}"
            )

        # Self-knowledge (always injected for LOCAL mode so the model knows
        # its own architecture, capabilities, limitations, and guards)
        parts.append(get_self_knowledge(self.config.model))

        # Active persona injection. This applies to every local model (Llama,
        # Gemma, etc.) because it is added at prompt-build time. It is NOT
        # injected for SELF_REVIEW, which must remain neutral and focused on
        # code quality rather than user persona style.
        persona_fragment = _get_active_persona_fragment()
        if persona_fragment and generation_profile != "self_review":
            parts.append(persona_fragment)

        # Current date/time/location context (for age calculations, relative time,
        # location-aware queries, and holiday references)
        current_context = _get_current_context()
        if current_context:
            parts.append(current_context)

        # Build instruction based on what context is available
        if augmented_context.strip():
            parts.append(f"Context:\n{augmented_context}")
            instruction = "Answer from the context above."
            if session_memory.strip():
                instruction += " Also use the session memory facts."
        elif session_memory.strip():
            if self._context_followup_requested(query):
                # Obvious continuations should lean on the prior conversation.
                instruction = (
                    "The user's query is a continuation of the prior conversation. "
                    "Use the session memory above to answer the follow-up in context."
                )
            else:
                # Session memory is context, not a script. The model must answer the
                # current query from its own knowledge unless the query is clearly a
                # follow-up to the prior conversation. This prevents a stale or wrong
                # prior turn (e.g. a mis-retrieved evidence article) from dominating
                # the response to an unrelated or poorly-transcribed question.
                instruction = (
                    "Session memory is provided above for context only. "
                    "If the current query is a follow-up to the prior conversation, you may use it. "
                    "Otherwise answer from your own knowledge and ignore any unrelated prior turns. "
                    "Do not assume the previous topic still applies unless the user explicitly continues it."
                )
        elif is_personal_query and persistent_facts:
            instruction = (
                "Answer using the [PERSISTENT FACTS] block above. "
                "Those facts are the user's own statements about themselves. "
                "Use them exactly as written. Do not add outside information. "
                "When the facts distinguish between biological children and stepchildren, "
                "preserve that distinction in your answer."
            )
        elif is_personal_query and not persistent_facts:
            instruction = (
                "The user is asking about themselves, their family, or their pets, "
                "but no persistent facts are available. Say clearly that you do not "
                "have that information. Do not invent or guess."
            )
        else:
            instruction = (
                "Answer from your own knowledge. "
                "If the user asks for live data (news, weather, time, stock prices), answer from what you know. "
                "The router decides whether to fetch live data; your job is to answer the query you received."
            )

        # Tone
        if generation_profile in ("chat_long", "detail", "augmented_detail"):
            tone = "Tone: warm, direct, thorough."
        else:
            tone = "Tone: warm, direct, concise."

        # Reinforce first-person framing for perspective-seeking questions
        # (e.g. "What does X mean to you?") that models otherwise answer in
        # generic third person. This is a targeted prompt steering fix.
        q_lower = query.lower()
        is_open_minded = "open-minded" in q_lower and "mean to you" in q_lower
        perspective_patterns = [
            r"what\s+.*\s+mean\s+to\s+you",
            r"what\s+.*\s+is\s+.*\s+to\s+you",
            r"what\s+do\s+you\s+think\s+about",
            r"how\s+do\s+you\s+feel\s+about",
        ]
        is_perspective_seeking = is_open_minded or any(
            re.search(p, q_lower) for p in perspective_patterns
        )
        if is_open_minded:
            first_person_hint = "Start your answer with 'To me, being open-minded means' and continue in first person."
        elif is_perspective_seeking:
            first_person_hint = "You are Local Lucy. Answer using first person ('I' / 'my')."
        else:
            first_person_hint = ""

        # When the user explicitly asks for reasoning, nudge the model to use
        # signal words (because, since, therefore, depends on) so the answer
        # shows step-by-step structure instead of a bare assertion.
        is_reasoning_request = "explain your reasoning" in q_lower or "why do you think" in q_lower
        reasoning_hint = ""
        if is_reasoning_request:
            reasoning_hint = (
                "Explain your reasoning step by step using words like because, since, therefore, or depends on. "
                "Take a clear position and keep the explanation concise; do not say 'I don't know'."
            )

        parts.append(f"{instruction}\n{tone}\n{budget_instruction}\n{first_person_hint}".rstrip())

        prompt_body = "\n\n".join(parts)
        # Attach reasoning hint directly to the user turn so it sits immediately
        # before the Assistant response, maximizing the chance the model follows it.
        user_turn = query
        if reasoning_hint:
            user_turn = f"{query}\n\n{reasoning_hint}"
        return f"{prompt_body}\n\nUser: {user_turn}\n\nAssistant:"

    def _apply_augmented_behavior_contract(
        self, user_question: str, background_context: str
    ) -> str:
        """Apply augmented behavior contract and return answer shape."""
        q = self._normalize_query(user_question)
        word_count = len(q.split())

        currentness_patterns = [
            r"(current|currently|now|right now|at the moment|today|latest)",
            r"what (is|are) .* doing now",
            r"current (projects|status|focus)",
        ]
        implicit_currentness = any(re.search(p, q) for p in currentness_patterns)

        underspecified_pattern = r"(\bhe\b|\bshe\b|\bthey\b|\bhis\b|\bher\b|\btheir\b)"
        underspecified_subject = bool(re.search(underspecified_pattern, q))

        has_anchor = self._augmented_background_has_anchor(background_context)

        if underspecified_subject and implicit_currentness and not has_anchor and word_count <= 8:
            return "clarify_question"

        if implicit_currentness:
            return "currentness_cautious"

        return "stable_summary"

    def _augmented_background_has_anchor(self, background: str) -> bool:
        """Check if background context has proper anchor entities."""
        ignore = {"Current", "Public", "Framing", "This", "That", "These", "Those", "AI"}
        # Find capitalized words (names)
        tokens = re.findall(r"[A-Z][A-Za-z0-9]+", background)
        tokens = [t for t in tokens if t not in ignore]
        # Check for multi-word names (First Last)
        has_multiword = bool(re.search(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", background))
        has_mixed_case = bool(re.search(r"[a-z][A-Z]", background))
        return has_multiword or has_mixed_case or len(tokens) >= 2

    def _build_clarification_question(self, user_question: str) -> str:
        """Build clarification question for underspecified entity."""
        q = self._normalize_query(user_question)
        if re.search(r"(current|now|doing now|working on|projects|status)", q):
            return "Which person or company do you want the current status for?"
        return "Which person or company do you mean?"

    # Exact tags known to emit an internal 'thinking' block. Substring checks
    # below catch families such as qwen3, deepseek-r1, and gemma4. Gemma 4 is
    # tagged by Ollama as a thinking-capable model and can consume part of its
    # output budget on internal reasoning before emitting visible text, so it
    # needs the thinking-model token headroom.
    _THINKING_MODEL_TAGS: frozenset[str] = frozenset()

    def _is_thinking_model(self) -> bool:
        """Detect models that emit an internal 'thinking' block.

        Checks both the configured tag and common architecture substrings.
        """
        model = (self.config.model or "").lower().split(":")[0]
        if model in self._THINKING_MODEL_TAGS:
            return True
        return any(
            name in model for name in ("qwen3", "deepseek-r1", "o3", "o1", "gemma4", "gemma-4")
        )

    def _thinking_model_token_multiplier(self) -> int:
        """Return multiplier for num_predict on thinking models."""
        return 4 if self._is_thinking_model() else 1

    async def _call_ollama(
        self,
        prompt: str,
        num_predict: int,
        temperature: Optional[float] = None,
        route_mode: str = "LOCAL",
    ) -> Tuple[str, int]:
        """Call Ollama API with retry for model-load transitions."""
        start_time = time.time()
        # Thinking models need extra token headroom so reasoning does not swallow
        # the visible response. Cap at a sane maximum to protect latency, but do
        # not reduce a deliberately large request below what the caller asked
        # for. SELF_REVIEW and explicit word-count routes (e.g. creative writing)
        # may exceed the usual num_predict_long cap when the generation profile
        # deliberately requested a larger budget.
        max_num_predict = max(self.config.num_predict_long, num_predict)
        effective_num_predict = min(
            num_predict * self._thinking_model_token_multiplier(),
            max_num_predict,
        )
        options = {
            "temperature": temperature if temperature is not None else self.config.temperature,
            "top_p": self.config.top_p,
            "seed": self.config.seed,
            "num_predict": effective_num_predict,
            "stop": ["\nUser:", "\nAssistant:", "\nUSER QUESTION:", "\nBACKGROUND CONTEXT:"],
        }
        if route_mode.upper() == "SELF_REVIEW":
            options["temperature"] = self.config.code_review_temperature
            options["top_p"] = self.config.code_review_top_p
            options["top_k"] = self.config.code_review_top_k
            # Code-review prompts can be long (file source + staged instructions).
            # Expand the context window so the output budget is not truncated by
            # the default 8192-token Modelfile setting. The value is capped by the
            # model's own limit and by available VRAM; Ollama offloads to system
            # RAM automatically when VRAM is tight.
            options["num_ctx"] = self.config.code_review_context_target
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": options,
        }
        # On a 12 GB GPU two large local models cannot both be resident.
        # Unload any other Local Lucy model before loading the target.
        try:
            await asyncio.to_thread(unload_other_lucy_models, self.config.model)
        except Exception:
            pass

        # Retry with exponential backoff for model-load transitions.
        max_attempts = 3
        base_delay = 0.5
        thinking_retry_done = False
        for attempt in range(max_attempts):
            try:
                session = await self._get_session()
                async with session.post(self.config.ollama_url, json=payload) as response:
                    response.raise_for_status()
                    data = await response.json()
                    text = data.get("response", "")
                    # Qwen3 and similar thinking models may emit reasoning in
                    # 'thinking' while leaving 'response' empty when token budget
                    # is consumed by the thinking phase. Retry once with a larger
                    # budget before falling back to the thinking text.
                    if not text and data.get("thinking"):
                        if not thinking_retry_done:
                            thinking_retry_done = True
                            payload["options"]["num_predict"] = min(
                                payload["options"]["num_predict"] * 4,
                                max_num_predict,
                            )
                            logger.warning(
                                f"Ollama response empty but thinking present for {self.config.model}; "
                                f"retrying with num_predict={payload['options']['num_predict']}"
                            )
                            continue
                        # The visible response is empty even after the retry,
                        # so use the thinking text as a last resort.  Trim it to
                        # a reasonable length because raw reasoning can be
                        # thousands of tokens and break downstream checks/UI.
                        thinking_text = data["thinking"].strip()
                        max_thinking_fallback_chars = min(480, num_predict * 2)
                        if len(thinking_text) > max_thinking_fallback_chars:
                            thinking_text = (
                                thinking_text[:max_thinking_fallback_chars].rsplit(" ", 1)[0] + "…"
                            )
                        text = thinking_text
                        if text:
                            logger.warning(
                                f"Ollama response empty but thinking present for {self.config.model}; using thinking as fallback"
                            )
                    duration_ms = int((time.time() - start_time) * 1000)
                    if text:
                        return text, duration_ms
                    if attempt == max_attempts - 1:
                        logger.error(
                            f"Ollama returned empty response for {self.config.model} after {max_attempts} attempts"
                        )
                        return "", duration_ms
                    # Empty response: Ollama likely mid-load/unload.
                    delay = base_delay * (2**attempt)
                    logger.warning(
                        f"Ollama returned empty response for {self.config.model}, retrying in {delay}s... (attempt {attempt + 1}/{max_attempts})"
                    )
                    await asyncio.sleep(delay)
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                logger.error(f"Ollama API call failed: {e}")
                raise
        return "", int((time.time() - start_time) * 1000)

    async def generate_answer(
        self,
        query: str,
        session_memory: str = "",
        route_mode: str = "LOCAL",
        output_mode: str = "CHAT",
        augmented_user_question: str = "",
        augmented_background_context: str = "",
        policy_response_id: str = "",
    ) -> AnswerResult:
        """Generate answer for query."""
        _logger().info(f"local_answer.py called: query='{query[:50]}...' mode={route_mode}")
        start_time = time.time()
        self._total_start_time = start_time

        q_eval = (
            augmented_user_question
            if route_mode == "AUGMENTED" and augmented_user_question
            else query
        )
        q_norm = self._normalize_query(q_eval)
        is_self_review = route_mode.upper() == "SELF_REVIEW"
        cache_bypass = is_self_review

        conversation_active = (
            self.config.conversation_mode_active or self.config.conversation_mode_force
        )

        session_memory = session_memory.replace("\r", " ").rstrip()

        if not self._is_memory_context_allowed(q_eval):
            session_memory = ""
        elif session_memory.strip():
            # If the user is explicitly asking about prior conversation, or if
            # the query is an obvious continuation ("what about...", "how about..."),
            # keep the memory unfiltered. Semantic filtering tends to drop these
            # short follow-ups because they share few keywords with the prior topic.
            if not self._is_explicit_memory_query(q_eval) and not self._context_followup_requested(
                q_eval
            ):
                session_memory = filter_memory_context(q_eval, session_memory)
            if session_memory.strip():
                self._diag_append("context_relevance_gate", "reuse_context")

        if len(session_memory) > self.config.max_context_chars:
            session_memory = session_memory[: self.config.max_context_chars]

        self._diag_append("cache_hit", "0")

        # Creative-writing guard: bypass ALL short-circuits (policy, 807, tube DB)
        # so stories, poems, and fiction always reach the LLM.
        is_creative = self._is_creative_writing_query(q_eval)
        if is_creative:
            self._diag_append("creative_writing_guard", "active")

        policy_response = self._get_policy_response(policy_response_id)
        if policy_response and not is_creative and not is_self_review:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=policy_response,
                from_cache=False,
                generation_profile="policy",
                duration_ms=duration_ms,
            )

        tube_answer = self._check_807_question(q_eval)
        if tube_answer and not is_creative and not is_self_review:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=tube_answer,
                from_cache=False,
                generation_profile="807_fixed",
                duration_ms=duration_ms,
            )

        # Tube database lookup: return exact specs for known tubes
        tube_db_answer = self._lookup_tube_database(q_eval)
        if tube_db_answer and not is_creative and not is_self_review:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=tube_db_answer,
                from_cache=False,
                generation_profile="tube_database",
                duration_ms=duration_ms,
            )

        # Deterministic personal/family/pet fact resolver
        # for direct factual ownership/identity queries when SQLite facts exist.
        if not is_creative and not is_self_review and route_mode in ("LOCAL", "CHAT"):
            fact_answer = self._resolve_personal_family_fact(q_eval)
            if fact_answer:
                duration_ms = int((time.time() - start_time) * 1000)
                self._diag_append("response_chars", len(fact_answer))
                self._diag_append("response_est_tokens", self._estimate_tokens(fact_answer))
                return AnswerResult(
                    text=fact_answer,
                    from_cache=False,
                    generation_profile="personal_fact_direct",
                    duration_ms=duration_ms,
                )

        profile_name, num_predict, budget_instruction = self._set_generation_profile(
            route_mode, output_mode, q_norm
        )

        cache_variant = (
            f"{profile_name}:{num_predict}:{self.config.temperature}:{self.config.top_p}"
        )

        self._diag_append("generation_route_mode", route_mode)
        self._diag_append("generation_output_mode", output_mode)
        self._diag_append("generation_profile", profile_name)
        self._diag_append("generation_num_predict", num_predict)

        # For personal/family queries, include a fact-revision token in the cache
        # key so that adding/editing/deleting facts automatically busts stale
        # cached answers.
        fact_revision = ""
        if self._is_personal_family_query(q_eval):
            try:
                fact_revision = _get_persistent_facts_revision("family")
            except Exception:
                pass

        cache_start = self._now_ms()
        cached = None
        if not cache_bypass:
            cached = self._cache_load(q_norm, cache_variant, fact_revision)
        cache_end = self._now_ms()
        self._latprof_append("local_answer", "cache_lookup", cache_end - cache_start)

        if cached:
            text, age_ms = cached
            self._latprof_append("local_answer", "prompt_assembly", 0)
            self._latprof_append("local_answer", "payload_build", 0)
            self._latprof_append("local_answer", "pre_model", cache_end - cache_start)
            self._latprof_append("local_answer", "ollama_api_call", 0)
            self._latprof_append("local_answer", "api_call", 0)
            self._latprof_append("local_answer", "model_or_fetch", 0)
            self._latprof_append("local_answer", "api_parse", 0)
            self._latprof_append("local_answer", "post_processing", 0)
            total_ms = cache_end - cache_start
            self._latprof_append("local_answer", "total", total_ms)
            self._diag_append("response_chars", len(text))
            self._diag_append("response_est_tokens", self._estimate_tokens(text))
            return AnswerResult(
                text=text,
                from_cache=True,
                cache_age_ms=age_ms,
                generation_profile=profile_name,
                duration_ms=total_ms,
            )

        local_stage_start = self._now_ms()
        # Use augmented context passed as parameter (from execution engine)
        augmented_context = (
            augmented_background_context if route_mode in {"AUGMENTED", "EVIDENCE"} else ""
        )

        prompt = self._build_prompt(
            q_eval,
            session_memory,
            profile_name,
            budget_instruction,
            conversation_active,
            self.config.conversation_system_block,
            augmented_context,
        )

        prompt_chars = len(prompt)
        prompt_tokens = self._estimate_tokens(prompt)
        context_tokens = self._estimate_tokens(session_memory)
        prompt_guard_exceeded = 1 if prompt_tokens > self.config.prompt_guard_tokens else 0

        self._diag_append("prompt_chars", prompt_chars)
        self._diag_append("prompt_est_tokens", prompt_tokens)
        self._diag_append("context_est_tokens", context_tokens)
        self._diag_append("prompt_guard_exceeded", prompt_guard_exceeded)

        prompt_done = self._now_ms()
        self._latprof_append("local_answer", "prompt_assembly", prompt_done - local_stage_start)

        payload_start = self._now_ms()
        self._latprof_append("local_answer", "payload_build", 0)
        pre_model_ms = payload_start - local_stage_start
        self._latprof_append("local_answer", "pre_model", pre_model_ms)

        try:
            # Use higher temperature for creative/detail requests so the model
            # can actually generate varied, imaginative text instead of getting
            # stuck in deterministic instruction-echo mode.
            temp_override = None
            if profile_name in ("detail", "chat_long"):
                temp_override = 0.7
            api_text, api_duration_ms = await self._call_ollama(
                prompt, num_predict, temp_override, route_mode=route_mode
            )
            api_done = self._now_ms()

            self._latprof_append("local_answer", "ollama_api_call", api_duration_ms)
            self._latprof_append("local_answer", "api_call", api_duration_ms)
            self._latprof_append("local_answer", "model_or_fetch", api_duration_ms)

            if not api_text:
                raise ValueError("Empty response from Ollama")
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=f"ERROR: Failed to get response from local model: {e}",
                error=str(e),
                generation_profile=profile_name,
                duration_ms=duration_ms,
            )

        parse_done = self._now_ms()
        self._latprof_append("local_answer", "api_parse", 0)

        post_start = self._now_ms()

        api_text_lower = api_text.lower()
        if (
            not is_self_review
            and re.search(r"\b807s?\b", q_norm)
            and re.search(r"\b(pair|two|2)\b", q_norm)
            and re.search(r"\b(push[ -]?pull|pp)\b", q_norm)
            and re.search(r"\b(class )?ab1\b", q_norm)
            and re.search(r"\b(power|output|watt|watts)\b", q_norm)
        ):
            numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", api_text_lower)]
            max_num = max(numbers) if numbers else 0

            if re.search(r"\bper[- ]?tube\b|\beach tube\b", api_text_lower) or max_num > 40:
                if re.search(r"\b400( ?v| ?volt| ?volts)?\b", q_norm):
                    api_text = "For a pair of 807s in push-pull class AB1 at about 400 V plate, expect roughly 25-35 W total output (around 30 W typical). This is pair total, not per-tube."
                else:
                    api_text = "For a pair of 807s in push-pull class AB1, expect roughly 25-35 W total output for the pair under typical conditions. This is pair total, not per-tube."

                duration_ms = int((time.time() - start_time) * 1000)
                self._diag_append("response_chars", len(api_text))
                self._diag_append("response_est_tokens", self._estimate_tokens(api_text))
                return AnswerResult(
                    text=api_text, generation_profile=profile_name, duration_ms=duration_ms
                )

        api_text = self._strip_identity_preamble(api_text, q_eval)
        api_text = self._sanitize_model_output(api_text)

        # Apply augmented completion guard for AUGMENTED routes
        if route_mode in {"AUGMENTED", "EVIDENCE"}:
            api_text, guard_triggered, guard_reason = self._apply_augmented_completion_guard(
                api_text
            )
            self._diag_append(
                "augmented_completion_guard_triggered", "1" if guard_triggered else "0"
            )
            self._diag_append("augmented_completion_guard_reason", guard_reason)

        post_done = self._now_ms()
        self._latprof_append("local_answer", "post_processing", post_done - post_start)

        self._diag_append("response_chars", len(api_text))
        self._diag_append("response_est_tokens", self._estimate_tokens(api_text))

        total_ms = int((time.time() - start_time) * 1000)
        self._latprof_append("local_answer", "total", total_ms)

        if not cache_bypass:
            self._cache_store(q_norm, cache_variant, api_text, fact_revision)

        return AnswerResult(
            text=api_text, from_cache=False, generation_profile=profile_name, duration_ms=total_ms
        )

    async def close(self) -> None:
        """Close resources."""
        if self._session and not self._session.closed:
            try:
                await self._session.close()
            except RuntimeError:
                # Event loop may already be closed (e.g. pytest-asyncio teardown)
                pass

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


# CLI Interface
async def run_cli() -> int:
    """Run CLI interface."""
    import argparse

    parser = argparse.ArgumentParser(description="Local Lucy answer generator")
    parser.add_argument("query", nargs="+", help="Query to answer")
    parser.add_argument("--model", default=None, help="Model name")
    parser.add_argument("--route-mode", default="LOCAL", help="Route mode")
    parser.add_argument("--output-mode", default="CHAT", help="Output mode")
    parser.add_argument("--session-memory", default="", help="Session memory")
    parser.add_argument("--no-cache", action="store_true", help="Disable cache")
    parser.add_argument("--json", action="store_true", help="Output JSON")

    args = parser.parse_args()
    query = " ".join(args.query)

    config = LocalAnswerConfig.from_env()
    if args.model:
        config.model = args.model
    if args.no_cache:
        config.cache_enabled = False

    async with LocalAnswer(config) as answer_gen:
        result = await answer_gen.generate_answer(
            query=query,
            session_memory=args.session_memory,
            route_mode=args.route_mode,
            output_mode=args.output_mode,
        )

    if args.json:
        output = {
            "text": result.text,
            "from_cache": result.from_cache,
            "cache_age_ms": result.cache_age_ms,
            "generation_profile": result.generation_profile,
            "duration_ms": result.duration_ms,
        }
        if result.error:
            output["error"] = result.error
        print(json.dumps(output))
    else:
        print(result.text)

    return 0 if not result.error else 1


if __name__ == "__main__":
    asyncio.run(run_cli())


# Logging setup
