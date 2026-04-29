#!/usr/bin/env python3
"""Local LLM answer generator - Python replacement for local_answer.sh.

This module provides:
- Async Ollama API client with connection pooling
- Query classification and policy enforcement
- Session memory management
- Response caching
- Identity/policy response handling
- Prompt building with various modes
- Latency profiling
- Conversation mode support
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

logger = logging.getLogger(__name__)


# Fixed policy responses
FIXED_POLICY_RESPONSES: Dict[str, str] = {
    "familiarity_chatgpt": "Yes. ChatGPT is OpenAI's conversational AI assistant.\nA concise summary is: it is a general-purpose language model interface used for question answering, writing, coding help, and analysis.",
    "definition_chatgpt": "ChatGPT is OpenAI's conversational AI assistant built on large language models.\nIt is commonly used for question answering, writing, coding help, brainstorming, and analysis.",
    "definition_python": "Python is a high-level programming language designed to be readable and versatile.",
    "definition_linux": "Linux is a Unix-like operating system kernel, and the name is also commonly used for operating systems built around that kernel.",
    "definition_git": "Git is a distributed version control system used to track changes in code and other files.",
    "emotion_state_unknown": "I don't have evidence about your current emotional state. If you want to describe how you're feeling, I can help think it through.",
    "context_loss_explanation": "Because I failed to carry forward the relevant local context from the previous turn.\nThat was a context-handling mistake, not a need for more facts.",
    "technical_ohms_law": "Ohm's law says that voltage, current, and resistance are related by V = I x R.\nIf resistance stays constant, increasing voltage increases current proportionally.",
    "media_reliability_bbc": "The BBC is not a newspaper; it is a public broadcaster. It is not literally unbiased, but it is generally regarded as a mainstream outlet with formal editorial standards.\nA fair summary is: broadly reliable for straight reporting, but still worth cross-checking on politically charged topics.",
    "media_reliability_reuters": "Reuters is generally regarded as one of the more neutral mainstream wire services. That does not make it bias-free, but its reporting style is usually more restrained and less opinion-driven than many broadcasters or opinion outlets.",
    "media_reliability_fox_news": "Fox News is not well described as unbiased. Its straight reporting and its opinion programming are different products, and the opinion side is widely seen as clearly partisan.\nA conservative summary is: some factual reporting exists there, but for contested political topics it should be cross-checked against less partisan outlets.",
    "media_reliability_guardian": "The Guardian is generally regarded as a serious mainstream newspaper with a center-left or left-liberal editorial slant. That does not make it unreliable, but it does mean neutrality is not the right description.\nA fair summary is: useful reporting, but cross-check important political framing against outlets with different editorial priors.",
    "component_2n3055": "The 2N3055 is a classic silicon NPN power transistor, commonly used in older power supplies and power amplifier output stages.",
    "component_bc547": "The BC547 is a small-signal NPN bipolar transistor, commonly used for low-power switching and amplification.",
    "component_lm317": "The LM317 is an adjustable linear voltage regulator. It is commonly used for adjustable power supplies and can also be configured as a constant-current source.",
    "component_ne555": "The 555, often labeled NE555, is a timer IC used for delays, pulses, oscillators, and simple timing circuits.",
    "tube_807_identity": "The 807 is a beam power tetrode vacuum tube. It was widely used in RF transmitters and older audio power stages.",
    "ambiguity_ic3055": "The label 'IC 3055' is ambiguous. If you mean 2N3055, that is a power transistor, not an integrated circuit.",
    "fact_capital_france": "The capital of France is Paris.",
    "racheli_presence_ack": "Understood. Racheli is your life partner, and I will keep responses grounded, warm, and respectful to both of you.",
    "greeting_generic": "Hello. I'm here and functioning normally. What would you like help with?",
    "recursion_one_sentence": "Recursion is solving a problem by reducing it to smaller versions of itself until a simple base case stops the loop.",
    "pet_stress_blasts": "Move your dog to the quietest interior room, close blinds, and run steady white noise to mask blasts.\nStay close, speak calmly, and offer a familiar blanket or crate; avoid forcing contact if your dog wants distance.\nIf panic is severe or persistent, contact a veterinarian for a short-term anxiety plan.",
    "tube_807_pp_ab1_output_400v": "For a pair of 807s in push-pull class AB1 at about 400 V plate, expect roughly 25-35 W total output (around 30 W typical). This is pair total, not per-tube.",
    "tube_807_pp_ab1_output": "For a pair of 807s in push-pull class AB1, expect roughly 25-35 W total output for the pair under typical conditions. This is pair total, not per-tube.",
}


WATER_WET_RESPONSE = """Facts:
- "Wet" usually means liquid is present on a surface.
- Water contacting another surface makes that surface wet.
Assumptions:
- We use the common everyday definition of "wet."
External dependencies:
- None required for this conceptual question.
"""


@dataclass
class LocalAnswerConfig:
    """Configuration for LocalAnswer."""
    model: str = "local-lucy"
    ollama_url: str = "http://127.0.0.1:11434/api/generate"
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 7
    keep_alive: str = "10m"
    num_predict_default: int = 96
    num_predict_chat: int = 192
    num_predict_conversation: int = 96
    num_predict_brief: int = 48
    num_predict_detail: int = 768
    num_predict_clarify: int = 48
    num_predict_augmented_default: int = 128
    num_predict_augmented_brief: int = 64
    num_predict_augmented_detail: int = 512
    num_predict_augmented_background: int = 128
    max_context_chars: int = 1200
    prompt_guard_tokens: int = 700
    cache_enabled: bool = True
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".cache" / "lucy" / "local_repeat")
    cache_ttl_seconds: int = 60
    cache_max_entries: int = 5
    root_path: Path = field(default_factory=lambda: Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev")
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
        root = Path(os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT", 
                                   os.environ.get("LUCY_ROOT", 
                                                  str(Path.home() / "lucy-v8" / "snapshots" / "opt-experimental-v8-dev"))))
        cache_dir = os.environ.get("LUCY_LOCAL_REPEAT_CACHE_DIR")
        return cls(
            model=os.environ.get("LUCY_LOCAL_MODEL", "local-lucy"),
            ollama_url=os.environ.get("LUCY_OLLAMA_API_URL", "http://127.0.0.1:11434/api/generate"),
            temperature=float(os.environ.get("LUCY_LOCAL_TEMPERATURE", "0")),
            top_p=float(os.environ.get("LUCY_LOCAL_TOP_P", "1")),
            seed=int(os.environ.get("LUCY_LOCAL_SEED", "7")),
            keep_alive=os.environ.get("LUCY_LOCAL_KEEP_ALIVE", "10m"),
            num_predict_default=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_DEFAULT", "128")),
            num_predict_chat=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_CHAT", "256")),
            num_predict_conversation=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_CONVERSATION", "128")),
            num_predict_brief=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_BRIEF", "64")),
            num_predict_detail=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_DETAIL", "768")),
            num_predict_clarify=int(os.environ.get("LUCY_LOCAL_NUM_PREDICT_CLARIFY", "64")),
            prompt_guard_tokens=int(os.environ.get("LUCY_LOCAL_PROMPT_GUARD_TOKENS", "700")),
            cache_enabled=os.environ.get("LUCY_LOCAL_REPEAT_CACHE", "1").lower() in ("1", "true", "yes", "on"),
            cache_dir=Path(cache_dir) if cache_dir else (root / "cache" / "local_repeat"),
            cache_ttl_seconds=int(os.environ.get("LUCY_LOCAL_REPEAT_CACHE_TTL_S", "60")),
            cache_max_entries=int(os.environ.get("LUCY_LOCAL_REPEAT_CACHE_MAX_ENTRIES", "5")),
            root_path=root,
            conversation_mode_active=os.environ.get("LUCY_CONVERSATION_MODE_ACTIVE", "").lower() in ("1", "true", "yes", "on"),
            conversation_mode_force=os.environ.get("LUCY_CONVERSATION_MODE_FORCE", "").lower() in ("1", "true", "yes", "on"),
            conversation_system_block=os.environ.get("LUCY_CONVERSATION_SYSTEM_BLOCK", "").lower() in ("1", "true", "yes", "on"),
            diag_file=Path(os.environ.get("LUCY_LOCAL_DIAG_FILE", "")) if os.environ.get("LUCY_LOCAL_DIAG_FILE") else None,
            diag_run_id=os.environ.get("LUCY_LOCAL_DIAG_RUN_ID"),
            latency_profile_file=Path(os.environ.get("LUCY_LATENCY_PROFILE_FILE", "")) if os.environ.get("LUCY_LATENCY_PROFILE_FILE") else None,
            identity_trace_file=Path(os.environ.get("LUCY_IDENTITY_TRACE_FILE", "")) if os.environ.get("LUCY_IDENTITY_TRACE_FILE") else None,
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


class LocalAnswer:
    """Main class for generating local LLM answers."""
    
    # Medical/high-risk keywords
    MEDICAL_KEYWORDS = [
        'tadalafil', 'tadalifil', 'cialis', 'viagra', 'sildenafil', 'vardenafil',
        'metformin', 'statin', 'insulin', 'arrhythmia', 'afib', 'qt', 'palpitations',
        'dose', 'dosage', 'mg', 'side effect', 'side effects', 'contraindication',
        'contraindications', 'interaction', 'interactions', 'medication', 'drug',
        'drugs', 'alcohol', 'tadafil', 'tadalfil', 'aritmia', 'arritmia'
    ]
    
    # Time-sensitive keywords
    TIME_SENSITIVE_KEYWORDS = [
        'latest', 'today', 'price', 'prices', 'cost', 'schedule', 'news', 'headline',
        'headlines', 'verify', 'source', 'sources', 'citation', 'citations',
        'exchange rate', 'currency', 'fx', 'usd', 'ils', 'eur', 'gbp', 'jpy'
    ]
    
    def __init__(self, config: Optional[LocalAnswerConfig] = None):
        self.config = config or LocalAnswerConfig.from_env()
        self._session: Optional[Any] = None
        self._lat_metrics = LatencyMetrics()
        self._total_start_time: Optional[float] = None
        
    def _now_ms(self) -> int:
        """Current time in milliseconds."""
        return int(time.time() * 1000)
    
    async def _get_session(self) -> Any:
        """Get or create aiohttp session."""
        if not HAS_AIOHTTP:
            raise ImportError("aiohttp is required for async operations")
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
            timeout = aiohttp.ClientTimeout(total=120)
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"Content-Type": "application/json"}
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
        q = re.sub(r'\s+', ' ', q)
        q = q.lower()
        return q
    
    def _contains_word(self, text: str, word: str) -> bool:
        """Check if word appears as whole word in text."""
        pattern = rf'(^|[^a-z0-9]){re.escape(word)}([^a-z0-9]|$)'
        return bool(re.search(pattern, text, re.IGNORECASE))
    
    def _is_memory_context_allowed(self, query: str) -> bool:
        """Check if memory context should be used for this query."""
        q = query.strip().lower()
        backchannel_pattern = r'^[\s]*(?:hmm+|hm+|uh+h*|uh-?huh|huh+|ok|okay|k|right|sure|thanks|thank you|cool|nice|interesting|weird|ugh|meh|useless)[\s]*$'
        if re.match(backchannel_pattern, q, re.IGNORECASE):
            return False
        vague_patterns = [
            r'^[\s]*(?:that(?: is|\'s)? annoying|that annoyed me|what(?:\'s| is) happening)[\s]*$'
        ]
        for pattern in vague_patterns:
            if re.match(pattern, q, re.IGNORECASE):
                return False
        return True
    
    def _context_reset_requested(self, query: str) -> bool:
        """Check if user wants to reset context."""
        pattern = r'(^|[^\w_])(new question|another question|unrelated|separately|different topic|switch topic|change topic|start over|reset context)([^\w_]|$)'
        return bool(re.search(pattern, query, re.IGNORECASE))
    
    def _context_followup_requested(self, query: str) -> bool:
        """Check if this is a context followup query."""
        if self._context_reset_requested(query):
            return False
        q = query.strip().lower()
        if re.match(r'^[\s]*(and|also|then|so)\s+', q):
            return True
        followup_phrases = [
            r'^[\s]*(what about|how about|about that|on that|on this|regarding that|regarding this|more on that|tell me more about that|continue|go on|elaborate|expand|follow up|follow-up)\b',
            # Additional patterns for "more detail" type followups
            r'(be more|give me more|include|add|what are the|can you be more)\s+(detailed|detail|details|specific|specifics|quantities|quantity|information|info)',
            r'(more\s+(details|detail|information|info|specifics|context|quantities))',
            r'(be more|more)\s+(specific|detailed|precise)',
            # Personal reference patterns - user asking about themselves
            r'^[\s]*(what is my|what are my|what\'s my|who am i|do you know my|remember my|you said my)',
            r'^[\s]*(my name|my favorite|my preference|my choice|my color|my age|my location)',
        ]
        for pattern in followup_phrases:
            if re.search(pattern, q):
                return True
        if re.search(r'(^|[^\w_])(previous answer|last answer|last response|earlier answer|as you said|you said earlier|same topic)([^\w_]|$)', q):
            return True
        return False
    
    def _is_identity_query(self, query: str) -> bool:
        """Check if query is about identity/capabilities."""
        q = self._normalize_query(query)
        identity_patterns = [
            r'(^|[^\w_])(who are you|who am i|do you know who|what are you|what can you do|internet access|tool access|browse|web access)([^\w_]|$)'
        ]
        for pattern in identity_patterns:
            if re.search(pattern, q):
                return True
        return False
    
    def _is_medical_high_risk(self, query: str) -> bool:
        """Check if query is medical/high-risk."""
        q = self._normalize_query(query)
        for keyword in self.MEDICAL_KEYWORDS:
            if self._contains_word(q, keyword):
                return True
        return False
    
    def _is_time_sensitive(self, query: str) -> bool:
        """Check if query is time-sensitive."""
        q = self._normalize_query(query)
        for keyword in self.TIME_SENSITIVE_KEYWORDS:
            if self._contains_word(q, keyword):
                return True
        if re.search(r'\bcurrent\s+(news|headline|headlines|events?|price|prices|cost|schedule|status|availability|stock)\b', q):
            return True
        return False
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate token count."""
        if not text:
            return 0
        return (len(text) + 3) // 4
    
    def _sanitize_model_output(self, text: str) -> str:
        """Sanitize model output."""
        text = text.replace('\r', '')
        lines = []
        for line in text.split('\n'):
            if not re.match(r'^[\s]*(User|Assistant):[\s]', line, re.IGNORECASE):
                lines.append(line)
        text = '\n'.join(lines)
        text = re.sub(r'\s*User:[\s].*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*Assistant:[\s].*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = text.rstrip()
        return text
    
    def _strip_identity_preamble(self, text: str) -> str:
        """Strip identity preamble from response."""
        # Remove common self-intro boilerplate
        text = re.sub(r"^I am Local Lucy[^.]*\.\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"^I will do my best[^.]*\.\s*", "", text, flags=re.IGNORECASE)
        text = text.strip()
        return text

    def _sanitize_identity_memory_fragment(self, text: str) -> str:
        """Sanitize identity memory fragment."""
        text = re.sub(r'\s+what would you like to know or discuss about (him|her|them)\??\.?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+what would you like to know\??\.?', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+could you provide more context.*$', '', text, flags=re.IGNORECASE)
        text = re.sub(r"\s+i don't have any information.*$", '', text, flags=re.IGNORECASE)
        text = re.sub(r'[.!?]+$', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
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
            snippet = text[:match.end()].strip()
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
    
    def _cache_key(self, query: str, variant: str) -> str:
        """Generate cache key."""
        key_string = f"{self.config.model}|{variant}|{query}"
        return hashlib.sha256(key_string.encode()).hexdigest()
    
    def _cache_load(self, query: str, variant: str) -> Optional[Tuple[str, int]]:
        """Load from cache."""
        if not self.config.cache_enabled:
            return None
        key = self._cache_key(query, variant)
        meta_file = self.config.cache_dir / f"{key}.meta"
        text_file = self.config.cache_dir / f"{key}.txt"
        if not meta_file.exists() or not text_file.exists():
            return None
        try:
            meta = {}
            with open(meta_file, 'r') as f:
                for line in f:
                    if '=' in line:
                        k, v = line.strip().split('=', 1)
                        meta[k] = v
            created_ts = int(meta.get('CREATED_TS', 0))
            cached_model = meta.get('MODEL', '')
            if cached_model != self.config.model:
                return None
            now = int(time.time())
            age_s = now - created_ts
            if age_s >= self.config.cache_ttl_seconds:
                meta_file.unlink(missing_ok=True)
                text_file.unlink(missing_ok=True)
                return None
            with open(text_file, 'r') as f:
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
    
    def _cache_store(self, query: str, variant: str, text: str) -> None:
        """Store in cache."""
        if not self.config.cache_enabled or not text.strip():
            return
        try:
            self.config.cache_dir.mkdir(parents=True, exist_ok=True)
            key = self._cache_key(query, variant)
            meta_file = self.config.cache_dir / f"{key}.meta"
            text_file = self.config.cache_dir / f"{key}.txt"
            with open(meta_file, 'w') as f:
                f.write(f"CREATED_TS={int(time.time())}\n")
                f.write(f"MODEL={self.config.model}\n")
            with open(text_file, 'w') as f:
                f.write(text)
            self._cache_prune()
        except Exception as e:
            logger.debug(f"Cache store failed: {e}")
    
    def _cache_prune(self) -> None:
        """Prune old cache entries."""
        try:
            if not self.config.cache_dir.exists():
                return
            meta_files = sorted(
                self.config.cache_dir.glob("*.meta"),
                key=lambda p: p.stat().st_mtime,
                reverse=True
            )
            for meta_file in meta_files[self.config.cache_max_entries:]:
                text_file = meta_file.with_suffix(".txt")
                meta_file.unlink(missing_ok=True)
                text_file.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Cache prune failed: {e}")
    
    def _write_identity_trace(self, loaded: str, source: str) -> None:
        """Write identity trace file."""
        if not self.config.identity_trace_file:
            return
        try:
            self.config.identity_trace_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.identity_trace_file, 'w') as f:
                f.write(f"IDENTITY_CONTEXT_LOADED={loaded}\n")
                f.write(f"IDENTITY_CONTEXT_SOURCE={source}\n")
        except Exception as e:
            logger.debug(f"Identity trace write failed: {e}")
    
    def _get_identity_response(self, query: str, session_memory: str) -> Optional[str]:
        """Get identity response if query is about identity."""
        q = self._normalize_query(query)
        asks_lucy = "who are you" in q or "who is lucy" in q
        asks_michael = "who is michael" in q or "who am i" in q
        asks_racheli = "who is racheli" in q
        asks_relationship = "who are we" in q or "our relationship" in q
        asks_oscar = "who is oscar" in q or ("oscar" in q.split() and "who" in q)
        
        identity_loaded = "yes" if (asks_lucy or asks_michael or asks_racheli or asks_relationship) else "no"
        identity_source = "profile_default"
        responses = []
        
        if asks_lucy:
            lucy_mem = re.search(r'\b(i am lucy:[^.]*)\.?', session_memory, re.IGNORECASE)
            if lucy_mem:
                mem_text = lucy_mem.group(1).strip()
                mem_text = self._sanitize_identity_memory_fragment(mem_text)
                identity_source = "personal_identity_memory"
                responses.append(f"{mem_text}.")
            else:
                responses.append("I am Lucy: a local-first, truth-first assistant with controlled warmth, explicit tool/evidence boundaries, and deterministic behavior.")
        
        if asks_michael:
            michael_mem = re.search(r'\b(you are michael:[^.]*|michael is [^.]*)\.?', session_memory, re.IGNORECASE)
            if michael_mem:
                mem_text = michael_mem.group(1).strip()
                mem_text = self._sanitize_identity_memory_fragment(mem_text)
                identity_source = "personal_identity_memory"
                if "you are michael" in mem_text.lower():
                    responses.append(f"{mem_text}.")
                else:
                    responses.append(f"Michael is {mem_text}.")
            else:
                responses.append("You are Michael: an engineer-philosopher user who prioritizes determinism, reproducibility, auditable behavior, and practical engineering value.")
        
        if asks_racheli:
            racheli_mem = re.search(r'\b(racheli is[^.]*)\.?', session_memory, re.IGNORECASE)
            if racheli_mem:
                mem_text = racheli_mem.group(1).strip()
                mem_text = self._sanitize_identity_memory_fragment(mem_text)
                identity_source = "personal_identity_memory"
                responses.append(f"{mem_text}.")
            else:
                responses.append("Racheli is your life partner and the love of your life. She is central in your relationship context, not a third-party mention.")
                responses.append("Known relationship dynamic: she brings emotional texture and narrative awareness, while you bring stability and structure.")
        
        if asks_relationship:
            responses.append("You are Michael, and I am Lucy. We work together on your local assistant system.")
        
        if responses:
            self._write_identity_trace(identity_loaded, identity_source)
            return "\n".join(responses)
        
        if asks_oscar:
            oscar_mem = re.search(r'\b[Oo]scar\s+is\s+([^.]*)\.?', session_memory)
            if oscar_mem:
                mem_text = oscar_mem.group(1).strip()
                mem_text = self._sanitize_identity_memory_fragment(mem_text)
                self._write_identity_trace("yes", "personal_identity_memory")
                return f"Oscar is {mem_text}."
            else:
                self._write_identity_trace("yes", "local_profile_default")
                return "Oscar is your dog in this local context."
        
        return None
    
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
            r'(^|[^\w_])(in detail|detailed|deep dive|thorough|comprehensive|step by step|step-by-step|walk me through|with examples|give examples|more detail|more details|long answer|full answer|complete answer|full recipe|complete recipe|full guide|complete guide)([^\w_]|$)'
        ]
        return any(re.search(p, query, re.IGNORECASE) for p in patterns)


    def _set_generation_profile(self, route_mode: str, output_mode: str, query: str) -> Tuple[str, int, str]:
        """Set generation profile for request."""
        route = route_mode.upper()
        output = output_mode.upper()
        q = self._normalize_query(query)
        
        detail_patterns = [r'(in detail|detailed|deep dive|thorough|comprehensive|step by step|step-by-step|walk me through|with examples|give examples|more detail|more details|long answer|full answer|complete answer|full recipe|complete recipe|full guide|complete guide)']
        requests_detail = any(re.search(p, q) for p in detail_patterns)
        
        brief_patterns = [r'(briefly|brief|concise|short answer|one sentence|single sentence|two sentences|summarize|short paragraph)']
        requests_brief = any(re.search(p, q) for p in brief_patterns)
        
        if route == "AUGMENTED":
            if requests_detail:
                return ("augmented_detail", self.config.num_predict_augmented_detail, "- Give provisional answer from tentative background.")
            elif requests_brief:
                return ("augmented_brief", self.config.num_predict_augmented_brief, "- Give short provisional answer.")
            elif self._is_background_overview_request(q):
                return ("augmented_background", self.config.num_predict_augmented_background, "- Give provisional answer from background.")
            else:
                return ("augmented", self.config.num_predict_augmented_default, "- Give provisional answer from tentative background.")
        
        if requests_detail:
            return ("detail", self.config.num_predict_detail, "- Answer clearly, but stay focused.")
        
        if route == "CLARIFY":
            return ("clarify", self.config.num_predict_clarify, "- Ask one short clarifying question only.")
        
        if output == "BRIEF" or requests_brief:
            return ("brief", self.config.num_predict_brief, "- Prefer one short sentence if possible.")
        
        if output == "CONVERSATION":
            return ("conversation", self.config.num_predict_conversation, "- Prefer two or three short sentences.")
        
        return ("chat", self.config.num_predict_chat, "- Prefer at most two short sentences.")
    
    def _is_background_overview_request(self, query: str) -> bool:
        """Check if query is a background/overview request."""
        q = query.lower()
        # Only match specific patterns, not simple "what is X" questions
        overview_starts = ['who is ', 'who was ', 'tell me about ', 'give me an overview of ', 
                          'overview of ', 'background on ', 'history of ', 'biography of ']
        for start in overview_starts:
            if q.startswith(start):
                return True
        return False
    
    def _check_807_question(self, query: str) -> Optional[str]:
        """Check for 807 tube question."""
        q = self._normalize_query(query)
        if (re.search(r'807', q) and re.search(r'(pair|two|2)', q) and 
            re.search(r'(push[ -]?pull|pp)', q) and re.search(r'(class )?ab1', q) and
            re.search(r'(power|output|watt)', q)):
            if re.search(r'400', q):
                return "For a pair of 807s in push-pull class AB1 at about 400 V plate, expect roughly 25-35 W total output (around 30 W typical). This is pair total, not per-tube."
            else:
                return "For a pair of 807s in push-pull class AB1, expect roughly 25-35 W total output for the pair under typical conditions. This is pair total, not per-tube."
        return None
    
    def _is_budget_brief(self, query: str) -> bool:
        """Check if query requests brief answer."""
        patterns = [r'(briefly|brief|concise|short answer|one sentence|single sentence|two sentences|summarize|short paragraph)']
        return any(re.search(p, query, re.IGNORECASE) for p in patterns)
    
    def _build_prompt(self, query: str, session_memory: str, generation_profile: str, budget_instruction: str, conversation_mode_active: bool, conversation_system_block: bool, augmented_context: str = "") -> str:
        """Build the prompt for Ollama."""
        memory_block = ""
        if session_memory.strip():
            memory_block = f"{session_memory}\n\n---\n\n"
        
        conversation_block = ""
        if conversation_mode_active and conversation_system_block:
            conversation_block = "[CONVERSATION_MODE: calibrated_sharp]\n\nTone rules: Take a position early. Avoid therapy language. Use no more than one hedge phrase. Include one concrete example. End with a clear takeaway.\n\n"
        
        # If augmented context is provided, use it to answer (evidence mode)
        if augmented_context.strip():
            context_block = f"Background context (from verified sources):\n{augmented_context}\n\n"
            instruction = "You are Local Lucy with access to background context above. Answer the user's question using this context. Be concise and accurate."
        else:
            context_block = ""
            if session_memory.strip():
                instruction = "You are Local Lucy. Be concise and accurate."
            else:
                instruction = "You are Local Lucy running OFFLINE. Answer using stable general knowledge only. If the user asks for latest/current info, say: 'This requires evidence mode.' and stop."
        
        return f"{instruction}\n\nTone: Warm, calm, clear. Start with the answer directly. Be concise.\n{budget_instruction}\n\n{conversation_block}{memory_block}{context_block}User: {query}"
    
    def _apply_augmented_behavior_contract(self, user_question: str, background_context: str) -> str:
        """Apply augmented behavior contract and return answer shape."""
        q = self._normalize_query(user_question)
        word_count = len(q.split())
        
        currentness_patterns = [r'(current|currently|now|right now|at the moment|today|latest)', r'what (is|are) .* doing now', r'current (projects|status|focus)']
        implicit_currentness = any(re.search(p, q) for p in currentness_patterns)
        
        underspecified_pattern = r'(\bhe\b|\bshe\b|\bthey\b|\bhis\b|\bher\b|\btheir\b)'
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
        if re.search(r'(current|now|doing now|working on|projects|status)', q):
            return "Which person or company do you want the current status for?"
        return "Which person or company do you mean?"

    async def _call_ollama(self, prompt: str, num_predict: int) -> Tuple[str, int]:
        """Call Ollama API."""
        start_time = time.time()
        payload = {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.config.keep_alive,
            "options": {
                "temperature": self.config.temperature,
                "top_p": self.config.top_p,
                "seed": self.config.seed,
                "num_predict": num_predict,
                "stop": [
                    "\nUser:",
                    "\nAssistant:",
                    "\nUSER QUESTION:",
                    "\nBACKGROUND CONTEXT:"
                ]
            }
        }
        try:
            session = await self._get_session()
            async with session.post(self.config.ollama_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                text = data.get("response", "")
                duration_ms = int((time.time() - start_time) * 1000)
                return text, duration_ms
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Ollama API call failed: {e}")
            raise

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
        _local_answer_logger.info(f"local_answer.py called: query='{query[:50]}...' mode={route_mode}")
        start_time = time.time()
        self._total_start_time = start_time
        
        q_eval = augmented_user_question if route_mode == "AUGMENTED" and augmented_user_question else query
        q_norm = self._normalize_query(q_eval)
        
        conversation_active = self.config.conversation_mode_active or self.config.conversation_mode_force
        
        session_memory = session_memory.replace('\r', ' ').rstrip()
        # Always include session memory when available (memory toggle controls loading)
        # The model can decide whether to use it based on query relevance
        if session_memory.strip():
            self._diag_append("context_relevance_gate", "reuse_context")
        
        if not self._is_memory_context_allowed(q_eval):
            session_memory = ""
        
        if len(session_memory) > self.config.max_context_chars:
            session_memory = session_memory[:self.config.max_context_chars]
        
        is_identity = self._is_identity_query(q_eval)
        if policy_response_id.startswith("identity_"):
            is_identity = True
        
        self._diag_append("cache_hit", "0")
        
        identity_response = self._get_identity_response(q_eval, session_memory)
        if identity_response:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=identity_response,
                from_cache=False,
                generation_profile="identity",
                duration_ms=duration_ms
            )
        
        policy_response = self._get_policy_response(policy_response_id)
        if policy_response:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=policy_response,
                from_cache=False,
                generation_profile="policy",
                duration_ms=duration_ms
            )
        
        # Medical queries require evidence UNLESS we have augmented context
        if self._is_medical_high_risk(q_eval) and route_mode != "AUGMENTED":
            return AnswerResult(
                text=f"This requires evidence mode.\nRun: run online: {q_eval}",
                generation_profile="medical_refusal",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        
        if route_mode != "AUGMENTED" and self._is_time_sensitive(q_eval):
            return AnswerResult(
                text=f"This requires evidence mode.\nRun: run online: {q_eval}",
                generation_profile="time_sensitive_refusal",
                duration_ms=int((time.time() - start_time) * 1000)
            )
        
        tube_answer = self._check_807_question(q_eval)
        if tube_answer:
            duration_ms = int((time.time() - start_time) * 1000)
            return AnswerResult(
                text=tube_answer,
                from_cache=False,
                generation_profile="807_fixed",
                duration_ms=duration_ms
            )
        
        profile_name, num_predict, budget_instruction = self._set_generation_profile(
            route_mode, output_mode, q_norm
        )
        
        cache_variant = f"{profile_name}:{num_predict}:{self.config.temperature}:{self.config.top_p}"
        
        self._diag_append("generation_route_mode", route_mode)
        self._diag_append("generation_output_mode", output_mode)
        self._diag_append("generation_profile", profile_name)
        self._diag_append("generation_num_predict", num_predict)
        
        cache_start = self._now_ms()
        cached = self._cache_load(q_norm, cache_variant)
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
                duration_ms=total_ms
            )
        
        local_stage_start = self._now_ms()
        # Use augmented context passed as parameter (from execution engine)
        augmented_context = augmented_background_context if route_mode == "AUGMENTED" else ""
        
        prompt = self._build_prompt(
            q_eval, session_memory, profile_name, budget_instruction,
            conversation_active, self.config.conversation_system_block,
            augmented_context
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
            api_text, api_duration_ms = await self._call_ollama(prompt, num_predict)
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
                duration_ms=duration_ms
            )
        
        parse_done = self._now_ms()
        self._latprof_append("local_answer", "api_parse", 0)
        
        post_start = self._now_ms()
        
        api_text_lower = api_text.lower()
        if (re.search(r'\b807s?\b', q_norm) and
            re.search(r'\b(pair|two|2)\b', q_norm) and
            re.search(r'\b(push[ -]?pull|pp)\b', q_norm) and
            re.search(r'\b(class )?ab1\b', q_norm) and
            re.search(r'\b(power|output|watt|watts)\b', q_norm)):
            
            numbers = [float(n) for n in re.findall(r'\d+(?:\.\d+)?', api_text_lower)]
            max_num = max(numbers) if numbers else 0
            
            if re.search(r'\bper[- ]?tube\b|\beach tube\b', api_text_lower) or max_num > 40:
                if re.search(r'\b400( ?v| ?volt| ?volts)?\b', q_norm):
                    api_text = "For a pair of 807s in push-pull class AB1 at about 400 V plate, expect roughly 25-35 W total output (around 30 W typical). This is pair total, not per-tube."
                else:
                    api_text = "For a pair of 807s in push-pull class AB1, expect roughly 25-35 W total output for the pair under typical conditions. This is pair total, not per-tube."
                
                duration_ms = int((time.time() - start_time) * 1000)
                self._diag_append("response_chars", len(api_text))
                self._diag_append("response_est_tokens", self._estimate_tokens(api_text))
                return AnswerResult(
                    text=api_text,
                    generation_profile=profile_name,
                    duration_ms=duration_ms
                )
        
        if not is_identity:
            api_text = self._strip_identity_preamble(api_text)
        
        api_text = self._sanitize_model_output(api_text)
        
        # Apply augmented completion guard for AUGMENTED routes
        if route_mode == "AUGMENTED":
            api_text, guard_triggered, guard_reason = self._apply_augmented_completion_guard(api_text)
            self._diag_append("augmented_completion_guard_triggered", "1" if guard_triggered else "0")
            self._diag_append("augmented_completion_guard_reason", guard_reason)
        
        post_done = self._now_ms()
        self._latprof_append("local_answer", "post_processing", post_done - post_start)
        
        self._diag_append("response_chars", len(api_text))
        self._diag_append("response_est_tokens", self._estimate_tokens(api_text))
        
        total_ms = int((time.time() - start_time) * 1000)
        self._latprof_append("local_answer", "total", total_ms)
        
        self._cache_store(q_norm, cache_variant, api_text)
        
        return AnswerResult(
            text=api_text,
            from_cache=False,
            generation_profile=profile_name,
            duration_ms=total_ms
        )

    async def close(self) -> None:
        """Close resources."""
        if self._session and not self._session.closed:
            await self._session.close()
    
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
class LocalAnswerLogger:
    """Logger for LocalAnswer operations."""
    
    def __init__(self):
        # ISOLATION: Use V8-specific logs if available, otherwise default
        import os
        v8_logs = os.environ.get("LUCY_LOGS_DIR")
        if v8_logs:
            self.log_dir = Path(v8_logs)
        else:
            self.log_dir = Path.home() / ".local" / "share" / "lucy-v8" / "logs"
        self.log_file = self.log_dir / "local_answer_py.log"
        self._ensure_log_dir()
    
    def _ensure_log_dir(self):
        """Ensure log directory exists."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def log(self, level: str, message: str) -> None:
        """Write log entry."""
        timestamp = datetime.now().isoformat()
        entry = f"{timestamp} [{level}] {message}\n"
        try:
            with open(self.log_file, "a") as f:
                f.write(entry)
        except Exception:
            pass  # Silently fail if logging fails
    
    def info(self, message: str) -> None:
        self.log("INFO", message)
    
    def debug(self, message: str) -> None:
        self.log("DEBUG", message)
    
    def error(self, message: str) -> None:
        self.log("ERROR", message)


# Create global logger instance
_local_answer_logger = LocalAnswerLogger()
