#!/usr/bin/env python3
import re
from typing import Dict, List

ROUTE_PREFIXES = ("local", "news", "evidence")


def _collapse_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def normalize_text(text: str) -> str:
    text = (text or "")
    text = (
        text.replace("\u2019", "'")
        .replace("\u2018", "'")
        .replace("\u02bc", "'")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    text = _collapse_ws(text)
    out = text
    typo_map = (
        ("arrhythia", "arrhythmia"),
        ("aritmia", "arrhythmia"),
        ("arritmia", "arrhythmia"),
        ("iraeli", "israeli"),
        ("tadalifil", "tadalafil"),
        ("tadafil", "tadalafil"),
        ("tadalfil", "tadalafil"),
    )
    for wrong, right in typo_map:
        out = re.sub(rf"\b{re.escape(wrong)}\b", right, out, flags=re.IGNORECASE)
    out = re.sub(r"\bside affects\b", "side effects", out, flags=re.IGNORECASE)
    out = re.sub(r"\bside affect\b", "side effect", out, flags=re.IGNORECASE)
    return out


def split_route_prefix(text: str) -> Dict[str, str]:
    match = re.match(r"^\s*(local|news|evidence):\s*(.*)$", text or "", flags=re.IGNORECASE)
    if not match:
        return {"route_prefix": "", "question_text": text or ""}
    route_prefix = match.group(1).strip().lower()
    question_text = match.group(2).strip()
    return {"route_prefix": route_prefix, "question_text": question_text or (text or "")}


def detect_command_name(text: str) -> str:
    q = (text or "").strip().lower()
    command_map = {
        "/mode online": "mode_online",
        "/mode offline": "mode_offline",
        "/mode auto": "mode_auto",
        "/conversation on": "conversation_on",
        "/conversation off": "conversation_off",
        "/memory on": "memory_on",
        "/memory off": "memory_off",
        "/memory show": "memory_show",
        "/memory status": "memory_status",
        "/memory clear": "memory_clear",
        "/quit": "quit",
        "/exit": "quit",
    }
    if q in command_map:
        return command_map[q]
    spoken_map = {
        "mode online": "mode_online",
        "mode offline": "mode_offline",
        "mode auto": "mode_auto",
        "conversation on": "conversation_on",
        "conversation off": "conversation_off",
        "memory on": "memory_on",
        "memory off": "memory_off",
        "memory show": "memory_show",
        "memory status": "memory_status",
        "memory clear": "memory_clear",
        "quit voice": "quit",
        "exit voice": "quit",
    }
    return spoken_map.get(q, "")


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z0-9_'-]+", (text or "").lower())


def normalize_input(raw_text: str, surface: str = "cli") -> Dict[str, object]:
    normalized = normalize_text(raw_text)
    prefix_info = split_route_prefix(normalized)
    question_text = _collapse_ws(prefix_info["question_text"])
    lowered = question_text.lower()
    command_name = detect_command_name(normalized)
    return {
        "raw_input": raw_text or "",
        "normalized_input": normalized,
        "question_text": question_text,
        "question_text_lower": lowered,
        "surface": (surface or "cli").strip().lower() or "cli",
        "route_prefix": prefix_info["route_prefix"],
        "command_name": command_name,
        "is_command_control": bool(command_name),
        "tokens": tokenize(question_text),
        "has_url": bool(re.search(r"https?://", question_text, flags=re.IGNORECASE)),
        "has_news_terms": bool(re.search(r"\b(news|headline|headlines|breaking)\b", lowered)),
        "has_current_terms": bool(
            re.search(r"\b(latest|today|current|recent|right now|at the moment|now|this week|as of)\b", lowered)
        ),
        "has_source_terms": bool(
            re.search(r"\b(source|sources|citation|citations|cite|verify|evidence|url|link|wikipedia|wiki)\b", lowered)
        ),
    }
