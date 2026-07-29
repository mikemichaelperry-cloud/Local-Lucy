"""Text-processing helpers for the context relevance guard."""

from __future__ import annotations

import re
from typing import Optional

from .config import KEYWORD_RE, PLACE_TAIL_RE, STOP_WORDS


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def extract_keywords(text: str) -> set[str]:
    keywords: set[str] = set()
    for w in KEYWORD_RE.findall(normalize(text)):
        if len(w) > 3 and w not in STOP_WORDS:
            keywords.add(w)
    return keywords


def extract_place_tail(text: str) -> Optional[str]:
    match = PLACE_TAIL_RE.search(text)
    if not match:
        return None
    tail = match.group(1).strip()
    tail = re.sub(r"^(?:the|a|an)\s+", "", tail, flags=re.IGNORECASE).strip()
    return tail if tail else None


def contains_tail(text: str, tail: str) -> bool:
    if not tail:
        return False
    norm = normalize(text)
    tail_norm = normalize(tail)
    if tail_norm in norm:
        return True
    parts = [p for p in tail_norm.split() if p]
    if len(parts) > 1 and all(part in norm for part in parts):
        return True
    return False


def extract_named_entities(text: str) -> set[str]:
    """Extract simple named-entity candidates (capitalised word sequences)."""
    if not text:
        return set()

    # Split into sentences so we can ignore sentence-initial single words.
    sentences = re.split(r"[.!?]\s+", text)
    entities: set[str] = set()
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for match in re.finditer(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b", sentence):
            entity = match.group(1)
            start = match.start()
            # Ignore a single capitalised word that starts the sentence.
            if start == 0 and " " not in entity:
                continue
            entities.add(entity.lower())
    return entities
