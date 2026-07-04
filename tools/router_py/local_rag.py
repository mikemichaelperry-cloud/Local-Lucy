#!/usr/bin/env python3
"""Local light-RAG retriever for Local Lucy.

Checks persistent facts and approved memory notes before escalating a query to
an augmented provider. The retriever is intentionally lightweight: it reuses
the existing MiniLM-backed persistent-fact store and uses simple keyword overlap
for approved memory notes, so it adds no new embedding infrastructure.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Persistent facts lookup. Mirror the import fallback used by local_answer.py
# so this module stays usable in standalone/router tests.
try:
    from memory.memory_service import get_relevant_persistent_facts as _get_relevant_persistent_facts
except ImportError:
    try:
        from tools.memory.memory_service import (
            get_relevant_persistent_facts as _get_relevant_persistent_facts,
        )
    except ImportError:

        def _get_relevant_persistent_facts(
            query: str,
            category: str | None = None,
            limit: int = 3,
            threshold: float = 0.30,
        ) -> list[str]:
            return []


# Very common words that hurt note-scoring signal/noise ratio.
_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "can",
        "shall",
        "to",
        "of",
        "in",
        "on",
        "at",
        "for",
        "with",
        "from",
        "by",
        "about",
        "as",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "my",
        "your",
        "his",
        "her",
        "our",
        "their",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", re.IGNORECASE)


def _tokenize(text: str) -> set[str]:
    """Return lowercase content tokens (≥3 chars, not stopwords)."""
    tokens = set()
    for match in _TOKEN_RE.finditer(text):
        token = match.group(0).lower()
        if len(token) >= 3 and token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _extract_note_body(text: str) -> str:
    """Strip memory-note frontmatter and return the human-written body."""
    parts = text.split("\n\n", 1)
    if len(parts) == 2:
        return parts[1].strip()
    return text.strip()


class LocalRAGRetriever:
    """Retrieve relevant local context (facts + notes) for a user query."""

    def __init__(
        self,
        memory_notes_dir: Path | str | None = None,
        fact_limit: int = 3,
        fact_threshold: float = 0.30,
        note_limit: int = 3,
        max_results: int = 5,
    ) -> None:
        if memory_notes_dir is None:
            # Default: project_root/memory/approved
            here = Path(__file__).resolve().parent.parent.parent
            memory_notes_dir = here / "memory" / "approved"
        self.memory_notes_dir = Path(memory_notes_dir)
        self.fact_limit = fact_limit
        self.fact_threshold = fact_threshold
        self.note_limit = note_limit
        self.max_results = max_results

    def _score_notes(self, query: str) -> list[tuple[float, str, str]]:
        """Score approved memory notes by keyword overlap with the query."""
        if not self.memory_notes_dir.is_dir():
            return []

        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, str, str]] = []
        for note_path in self.memory_notes_dir.glob("*.txt"):
            try:
                text = note_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            body = _extract_note_body(text)
            if not body:
                continue
            body_lower = body.lower()
            note_tokens = _tokenize(body)
            if not note_tokens:
                continue
            # Count query tokens that overlap with any note token in either
            # direction. This handles simple stems/plurals ("cats" ↔ "cat",
            # "bananas" ↔ "banana") without adding a stemmer dependency.
            overlap = 0
            for q_token in query_tokens:
                for n_token in note_tokens:
                    if q_token == n_token or q_token in n_token or n_token in q_token:
                        overlap += 1
                        break
            if overlap == 0:
                continue
            # Normalise by query size so short queries are not over-penalised.
            score = overlap / max(len(query_tokens), 1)
            # Source identifier is the filename stem.
            source = note_path.stem
            scored.append((score, source, body))

        scored.sort(key=lambda item: (-item[0], item[1]))
        return scored[: self.note_limit]

    def _retrieve_facts(self, query: str) -> list[tuple[str, str]]:
        """Return (source, text) tuples from the persistent-fact store."""
        facts = _get_relevant_persistent_facts(
            query,
            category=None,
            limit=self.fact_limit,
            threshold=self.fact_threshold,
        )
        return [("persistent_fact", fact) for fact in facts]

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        """Return a ranked, deduplicated list of local context snippets.

        Each result is a dict with keys: `source`, `text`, `score`.
        """
        if not query or not query.strip():
            return []

        results: list[dict[str, Any]] = []
        seen_texts: set[str] = set()

        # 1. Persistent facts (semantic, higher confidence)
        for source, text in self._retrieve_facts(query):
            key = text.strip().lower()
            if key and key not in seen_texts:
                seen_texts.add(key)
                results.append({"source": source, "text": text, "score": 1.0})

        # 2. Approved memory notes (keyword overlap)
        for score, source, text in self._score_notes(query):
            key = text.strip().lower()
            if key and key not in seen_texts:
                seen_texts.add(key)
                results.append({"source": f"memory_note:{source}", "text": text, "score": score})

        return results[: self.max_results]

    def has_results(self, query: str) -> bool:
        """Cheap check for whether any local context exists."""
        return bool(self.retrieve(query))

    def format_context(self, query: str) -> tuple[str, list[str]] | tuple[None, None]:
        """Format retrieved snippets as an augmented background context block.

        Returns (context_text, sources) or (None, None) if nothing was found.
        """
        results = self.retrieve(query)
        if not results:
            return None, None

        entries: list[str] = []
        sources: list[str] = []
        for i, result in enumerate(results, start=1):
            source = result["source"]
            text = result["text"].strip()
            if not text:
                continue
            entries.append(f"{i}. {source}\n{text}")
            sources.append(source)

        if not entries:
            return None, None
        return "\n\n".join(entries), sources


def is_local_rag_enabled() -> bool:
    """Return True unless the user explicitly disabled local RAG."""
    env = os.environ.get("LUCY_ENABLE_LOCAL_RAG", "").lower()
    return env not in ("0", "false", "no", "off")
