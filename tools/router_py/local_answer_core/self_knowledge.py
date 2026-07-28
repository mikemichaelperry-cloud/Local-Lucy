#!/usr/bin/env python3
"""Self-knowledge, persona, and context helpers for local answer."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_memory_db_path, lucy_runtime_namespace_root

logger = logging.getLogger(__name__)

# Import persistent facts and active identity from SQL memory service (with fallback)
try:
    from memory.memory_service import (
        get_current_user_identity as _get_current_user_identity,
        get_persistent_facts_revision as _get_persistent_facts_revision,
        get_relevant_persistent_facts as _get_relevant_persistent_facts,
    )

    logger.info("[FACTS] Imported memory service helpers from memory.memory.service")
except ImportError as _e1:
    logger.warning(f"[FACTS] Failed to import from memory.memory_service: {_e1}")
    try:
        from tools.memory.memory_service import (
            get_current_user_identity as _get_current_user_identity,
            get_persistent_facts_revision as _get_persistent_facts_revision,
            get_relevant_persistent_facts as _get_relevant_persistent_facts,
        )

        logger.info("[FACTS] Imported memory service helpers from tools.memory.memory_service")
    except ImportError as _e2:
        logger.error(
            f"[FACTS] Failed to import memory service helpers: {_e2}. Using fallback no-ops."
        )

        def _get_relevant_persistent_facts(query, category=None, limit=3, threshold=0.35):  # type: ignore[misc]
            return []

        def _get_persistent_facts_revision(category=None):  # type: ignore[misc]
            return ""

        def _get_current_user_identity() -> str | None:  # type: ignore[misc]
            return None


def _load_family_facts_direct() -> list[str]:
    """Direct SQLite fallback: load all family-category persistent facts.

    Bypasses embedding-based retrieval so facts are always available
    for personal/family queries even when MiniLM or Ollama embeddings fail.
    """
    try:
        import sqlite3

        db_path = os.environ.get("LUCY_MEMORY_DB_PATH", "")
        if not db_path:
            db_path = str(lucy_memory_db_path())
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.execute(
            "SELECT fact_text FROM persistent_facts WHERE category = 'family' OR category IS NULL OR category = '' ORDER BY id"
        )
        facts = [row[0] for row in cursor.fetchall()]
        conn.close()
        logger.info(f"[FACTS] Direct SQLite load returned {len(facts)} family facts")
        return facts
    except Exception as e:
        logger.warning(f"[FACTS] Direct SQLite fallback failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Persona fragments: loaded from config/personas/<name>.txt and injected
# into the local prompt when that identity is active. This applies to any
# local model (Llama, Gemma, etc.) because it is added at prompt-build time.
# ---------------------------------------------------------------------------
_PERSONA_FRAGMENTS: dict[str, str] | None = None


def _load_persona_fragments() -> dict[str, str]:
    """Load persona prompt fragments from config/personas/*.txt.

    The basename (lower-cased) is the canonical persona key. Missing or
    unreadable files are skipped gracefully.
    """
    global _PERSONA_FRAGMENTS
    if _PERSONA_FRAGMENTS is not None:
        return _PERSONA_FRAGMENTS
    fragments: dict[str, str] = {}
    personas_dir = Path(__file__).resolve().parents[2] / "config" / "personas"
    try:
        for path in sorted(personas_dir.glob("*.txt")):
            name = path.stem.lower()
            try:
                fragments[name] = path.read_text(encoding="utf-8").strip()
                logger.info(f"[PERSONA] Loaded fragment for '{name}' from {path}")
            except Exception as exc:
                logger.warning(f"[PERSONA] Failed to read {path}: {exc}")
    except Exception as exc:
        logger.warning(f"[PERSONA] Failed to load persona fragments: {exc}")
    _PERSONA_FRAGMENTS = fragments
    return fragments


def _get_active_persona_fragment() -> str | None:
    """Return the prompt fragment for the currently active user identity, if any."""
    identity = _get_current_user_identity()
    if not identity:
        return None
    name = identity.strip().lower()
    fragment = _load_persona_fragments().get(name)
    if fragment:
        return f"[PERSONA: {identity}]\n{fragment}"
    logger.debug(f"[PERSONA] No fragment found for active identity '{identity}'")
    return None


# Keywords that indicate the user is asking about themselves, their family,
# or their pets. Only these queries should receive the restrictive
# [PERSISTENT FACTS] block; general-knowledge questions should use the model's
# own knowledge even if a retrieved fact happens to be semantically similar.
_PERSONAL_FACT_KEYWORDS = (
    "my children",
    "my son",
    "my daughter",
    "my wife",
    "my husband",
    "my dog",
    "my pet",
    "my family",
    "who am i",
    "grandchildren",
    "stepchildren",
    "my mother",
    "my father",
    "my sister",
    "my brother",
    "my granddaughter",
    "my grandson",
    "my grandchild",
)


def _is_personal_fact_query(query: str) -> bool:
    """Return True if the query is about the user's own facts/family/pets."""
    normalized = query.lower()
    return any(k in normalized for k in _PERSONAL_FACT_KEYWORDS)


# Self-knowledge: identity, capabilities, limitations.
# Injected on every LOCAL answer.  Kept short (~200 tokens) because the local
# model has a 2048-token context window and long system blocks get ignored.
# This is now a function so the identity string adapts to the active model.


def _lucy_version_label() -> str:
    """Return the version label injected into the local model self-knowledge prompt."""
    return os.environ.get("LUCY_VERSION_LABEL", "V11").strip() or "V11"


_SELF_KNOWLEDGE_TEMPLATE = (
    "You are Local Lucy {version_label}, an AI assistant running on the user's computer via Ollama "
    "({model_identity}).\n"
    "Architecture: PySide6/Qt6 HMI (Python 3.10); Ollama LLM backend; "
    "MiniLM-L6-v2 embedding router (384-dim, k=3) with deterministic policy guards; "
    "Whisper STT + Kokoro TTS voice stack; SQLite session memory and persistent facts.\n"
    "Routing is automatic: LOCAL (default), AUGMENTED (Wikipedia evidence with "
    "optional synthesis by OpenAI/Kimi), NEWS, TIME, WEATHER. "
    "Do not ask the user to pick a mode.\n"
    "Capabilities: coding, writing, reasoning, voice, "
    "tube database (648 types), live data via AUGMENTED/NEWS/WEATHER.\n"
    "Language: I am an English-only assistant. I do not translate to or from other languages.\n"
    "Limitations: training-data cutoff; {param_count} model so niche details may be wrong; "
    "cannot browse the web on your own — only when the router fetches it; "
    "cannot read files on the computer unless explicitly provided in context.\n"
    "Safety: medical/vet/legal → AUGMENTED with citations; stories/poems → LOCAL.\n"
    "If asked who you are or what version you are, say 'I am Local Lucy {version_label}.' "
    "If asked about capabilities, list them truthfully. If asked about your architecture, "
    "describe the {version_label} stack above. "
    "If asked about fallback providers or evidence sources (e.g., OpenAI, Kimi, Wikipedia), "
    "say that Wikipedia is the primary augmented source, OpenAI/Kimi may synthesize evidence "
    "when the router activates AUGMENTED mode, and your default knowledge source is the local "
    "Ollama LLM's parametric knowledge. Do not claim to be a different AI."
)

# Model-specific identity strings. Add new models here.
_MODEL_IDENTITIES: dict[str, tuple[str, str]] = {
    # backend_name -> (ollama_model_name, parameter_description)
    "local-lucy-llama31": ("llama3.1:8b", "~8B parameters, 4096-token context"),
    "local-lucy-llama31:latest": ("llama3.1:8b", "~8B parameters, 4096-token context"),
    "local-lucy-gemma4": ("gemma4:12b-it-qat", "~12B parameters, 128k-token context"),
    "local-lucy-gemma4:latest": ("gemma4:12b-it-qat", "~12B parameters, 128k-token context"),
    "gemma4:12b-it-qat": ("gemma4:12b-it-qat", "~12B parameters, 128k-token context"),
    "gemma4_code_review_agentic": (
        "hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M",
        "~12B parameters, 128k-token context, code-review specialist",
    ),
}


def get_self_knowledge(model_name: str = "local-lucy-llama31") -> str:
    """Return the SELF_KNOWLEDGE string for the given backend model name.

    Defaults to llama3.1:8b identity for unknown models.
    """
    ollama_name, params = _MODEL_IDENTITIES.get(model_name, _MODEL_IDENTITIES["local-lucy-llama31"])
    version_label = _lucy_version_label()
    return _SELF_KNOWLEDGE_TEMPLATE.format(
        model_identity=f"{ollama_name}, {params}",
        param_count=params.split(",")[0].strip().replace("~", ""),
        version_label=version_label,
    )


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


# ---------------------------------------------------------------------------
# Current context: date, time, timezone, location
# Injected into every LOCAL prompt so the model can answer age calculations,
# relative time references, and location-aware queries accurately.
# ---------------------------------------------------------------------------

# Timezone-to-location mapping (best-effort, covers common zones)
_TZ_TO_LOCATION: Dict[str, str] = {
    "asia/jerusalem": "Israel",
    "asia/tokyo": "Japan",
    "asia/shanghai": "China",
    "asia/singapore": "Singapore",
    "asia/dubai": "United Arab Emirates",
    "asia/kolkata": "India",
    "asia/seoul": "South Korea",
    "europe/london": "United Kingdom",
    "europe/paris": "France",
    "europe/berlin": "Germany",
    "europe/rome": "Italy",
    "europe/madrid": "Spain",
    "europe/amsterdam": "Netherlands",
    "europe/moscow": "Russia",
    "america/new_york": "United States (Eastern)",
    "america/chicago": "United States (Central)",
    "america/denver": "United States (Mountain)",
    "america/los_angeles": "United States (Pacific)",
    "america/toronto": "Canada (Eastern)",
    "america/vancouver": "Canada (Pacific)",
    "america/sao_paulo": "Brazil",
    "america/buenos_aires": "Argentina",
    "australia/sydney": "Australia (Eastern)",
    "pacific/auckland": "New Zealand",
    "africa/cairo": "Egypt",
    "africa/johannesburg": "South Africa",
    "utc": "UTC",
    "gmt": "United Kingdom",
}


def _get_local_timezone_name() -> str:
    """Return the system IANA timezone name using only standard library.

    Falls back to an empty string if the timezone cannot be determined.
    """
    # 1. Explicit TZ environment variable
    tz = os.environ.get("TZ", "").strip()
    if tz:
        return tz

    # 2. Debian/Ubuntu /etc/timezone file
    try:
        tz_path = Path("/etc/timezone")
        if tz_path.exists():
            return tz_path.read_text(encoding="utf-8").strip()
    except Exception:
        pass

    # 3. /etc/localtime symlink pointing into /usr/share/zoneinfo
    try:
        localtime = Path("/etc/localtime")
        if localtime.is_symlink():
            target = localtime.resolve()
            zoneinfo_root = Path("/usr/share/zoneinfo")
            try:
                return str(target.relative_to(zoneinfo_root))
            except ValueError:
                pass
    except Exception:
        pass

    return ""


def _get_current_context() -> str:
    """Return current date, time, timezone and approximate location.

    This gives the model ground truth for:
    - Age calculations ("How old is X?" needs current year)
    - Relative time ("yesterday", "next week", "in 3 days")
    - Location-aware queries ("What's the weather like here?")
    - Holiday references ("Is it a holiday today?")
    """
    try:
        now = datetime.now().astimezone()
        tz_name = str(now.tzinfo).lower()
        # Try to get a cleaner IANA timezone name without shelling out
        try:
            detected = _get_local_timezone_name()
            if detected:
                tz_name = detected.lower()
        except Exception:
            pass

        location = _TZ_TO_LOCATION.get(tz_name, "Unknown")
        # Fallback: try to extract region from timezone name (e.g. "Asia/Jerusalem")
        if location == "Unknown" and "/" in tz_name:
            region = tz_name.split("/")[1].replace("_", " ").title()
            location = region

        offset = now.strftime("%z")
        offset_str = f"UTC{offset[:3]}:{offset[3:]}" if len(offset) >= 5 else "UTC"

        return (
            f"Current context:\n"
            f"- Date and time: {now.strftime('%A, %Y-%m-%d %H:%M:%S')} ({offset_str})\n"
            f"- Timezone: {tz_name}\n"
            f"- Location: {location}\n"
        )
    except Exception:
        return ""
