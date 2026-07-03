# Context-Injection Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the keyword-only context guard in `tools/router_py/context_guard.py` with a hybrid semantic relevance layer (cross-encoder for evidence, bi-encoder for memory) while keeping a keyword fallback and remaining independent of the active LLM model.

**Architecture:** Two lazy-loaded `sentence-transformers` models score evidence and memory turns locally. A retained keyword/entity scorer acts as fallback if models are missing or fail. Callers in `execution_engine.py` and `local_answer.py` filter context before injecting it into prompts.

**Tech Stack:** Python 3.10, `sentence-transformers` 5.5.1, `torch` 2.12.0, `pytest`.

## Global Constraints

- English-only; do not re-introduce Hebrew/multilingual models.
- No API key; all scoring runs locally on CPU.
- Must work regardless of which LLM model (llama3.1, mistral, qwen3, etc.) is loaded by Ollama.
- Lazy-load models on first guard call; no startup-time penalty.
- Keep unrelated WIP out of commits (only `context_guard.py`, its test, and two caller touch-points).
- Target Python 3.10 type syntax and the existing codebase style.

---

### Task 1: Rewrite `context_guard.py` with semantic scorers and keyword fallback

**Files:**
- Modify: `tools/router_py/context_guard.py`
- Test: `tools/router_py/test_context_guard.py` (updated in Task 2)

**Interfaces:**
- Consumes: `sentence-transformers` `CrossEncoder` and `SentenceTransformer` (optional; fallback if missing).
- Produces:
  - `score_evidence_relevance(question: str, evidence: dict[str, Any]) -> float`
  - `is_evidence_relevant(question: str, evidence: dict[str, Any], threshold: float = 0.5) -> bool`
  - `score_memory_relevance(question: str, turn: str) -> float`
  - `filter_memory_context(question: str, memory_text: str, threshold: float = 0.2) -> str`

- [ ] **Step 1: Open `tools/router_py/context_guard.py` and replace the module body**

Keep the existing keyword helpers (`_STOP_WORDS`, `_extract_keywords`, `_extract_place_tail`, `_contains_tail`) as the fallback implementation. Add the semantic layer on top.

```python
"""Context relevance guard.

Hybrid semantic + keyword/entity scoring for retrieved evidence and
session-memory turns. The goal is to stop obviously irrelevant context
(e.g. a Wikipedia article about China for a Japan query, or a stale wrong
assistant turn) from reaching the LLM prompt.

Semantic models are loaded lazily on first use. If sentence-transformers is
not installed or a model fails to load, the guard falls back to deterministic
keyword overlap so requests never crash.
"""
from __future__ import annotations

import logging
import math
import re
from typing import Any

logger = logging.getLogger(__name__)

_EVIDENCE_THRESHOLD = 0.50
_MEMORY_THRESHOLD = 0.20

_EVIDENCE_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MEMORY_BI_ENCODER = "sentence-transformers/all-MiniLM-L6-v2"

# Lazy-loaded singletons. A truthy value means "loaded", False means
# "tried and failed" so we don't retry on every call.
_ce_model: Any | None = None
_bi_model: Any | None = None


def _sigmoid(x: float) -> float:
    """Map an unbounded logit to [0.0, 1.0]."""
    try:
        return 1.0 / (1.0 + math.exp(-float(x)))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


def _load_ce_model() -> Any | None:
    """Lazy-load the evidence cross-encoder."""
    global _ce_model
    if _ce_model is None:
        try:
            from sentence_transformers import CrossEncoder

            _ce_model = CrossEncoder(
                _EVIDENCE_CROSS_ENCODER,
                max_length=512,
                device="cpu",
            )
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load evidence cross-encoder %s: %s. "
                "Falling back to keyword relevance.",
                _EVIDENCE_CROSS_ENCODER,
                exc,
            )
            _ce_model = False
    return _ce_model if _ce_model else None


def _load_bi_model() -> Any | None:
    """Lazy-load the memory bi-encoder."""
    global _bi_model
    if _bi_model is None:
        try:
            from sentence_transformers import SentenceTransformer

            _bi_model = SentenceTransformer(_MEMORY_BI_ENCODER, device="cpu")
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning(
                "Could not load memory bi-encoder %s: %s. "
                "Falling back to keyword relevance.",
                _MEMORY_BI_ENCODER,
                exc,
            )
            _bi_model = False
    return _bi_model if _bi_model else None


def _evidence_text(evidence: dict[str, Any]) -> str:
    """Assemble a single text string from an evidence dict."""
    if not evidence:
        return ""
    title = str(evidence.get("title", "") or "")
    body = str(
        evidence.get("context")
        or evidence.get("content")
        or evidence.get("formatted")
        or ""
    )
    return f"{title} {body}".strip()


def _keyword_evidence_score(question: str, evidence: dict[str, Any]) -> float:
    """Fallback keyword/entity scorer for evidence."""
    text = _evidence_text(evidence)
    if not text:
        return 0.0

    question_norm = _normalize(question)
    combined = _normalize(text)

    tail = _extract_place_tail(question)
    if tail and not _contains_tail(combined, tail):
        return 0.0

    keywords = _extract_keywords(question)
    if not keywords:
        return 0.3 if combined else 0.0

    matched = sum(1 for kw in keywords if kw in combined)
    return matched / len(keywords)


def _keyword_memory_score(question: str, turn: str) -> float:
    """Fallback keyword/entity scorer for a memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    turn_norm = _normalize(turn)

    tail = _extract_place_tail(question)
    if tail and _contains_tail(turn_norm, tail):
        return 0.9

    keywords = _extract_keywords(question)
    if not keywords:
        return 0.0

    matched = sum(1 for kw in keywords if kw in turn_norm)
    return matched / len(keywords)


def score_evidence_relevance(question: str, evidence: dict[str, Any]) -> float:
    """Return a 0.0-1.0 relevance score for *evidence* against *question*."""
    if not evidence:
        return 0.0

    text = _evidence_text(evidence)
    if not text:
        return 0.0

    model = _load_ce_model()
    if model is not None:
        try:
            raw = model.predict(
                [(question, text)],
                show_progress_bar=False,
            )[0]
            return _sigmoid(raw)
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Evidence semantic scoring failed: %s", exc)

    return _keyword_evidence_score(question, evidence)


def is_evidence_relevant(
    question: str,
    evidence: dict[str, Any],
    threshold: float = _EVIDENCE_THRESHOLD,
) -> bool:
    """Return True if *evidence* is relevant enough to inject into the prompt."""
    return score_evidence_relevance(question, evidence) >= threshold


def score_memory_relevance(question: str, turn: str) -> float:
    """Return a 0.0-1.0 relevance score for a single memory turn."""
    if not question.strip() or not turn.strip():
        return 0.0

    model = _load_bi_model()
    if model is not None:
        try:
            import numpy as np

            q_emb = model.encode(
                [question],
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            t_emb = model.encode(
                [turn],
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            q_norm = np.linalg.norm(q_emb, axis=1)
            t_norm = np.linalg.norm(t_emb, axis=1)
            sim = np.sum(q_emb * t_emb, axis=1) / (q_norm * t_norm)
            return float(sim[0])
        except Exception as exc:  # pragma: no cover - fallback path
            logger.warning("Memory semantic scoring failed: %s", exc)

    return _keyword_memory_score(question, turn)


def filter_memory_context(
    question: str,
    memory_text: str,
    threshold: float = _MEMORY_THRESHOLD,
) -> str:
    """Return only memory turns plausibly relevant to *question*.

    Turns are separated by blank lines. If nothing survives filtering, returns
    an empty string so callers can skip memory injection entirely.
    """
    if not memory_text.strip():
        return ""

    turns = [t.strip() for t in memory_text.split("\n\n") if t.strip()]
    kept: list[str] = []
    for turn in turns:
        score = score_memory_relevance(question, turn)
        if score >= threshold:
            kept.append(turn)

    return "\n\n".join(kept)


# --- retained keyword helpers (unchanged logic, only minor renames) ---

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "used",
    "to", "of", "in", "on", "at", "by", "for", "with", "about", "from",
    "up", "down", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "any",
    "both", "each", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very", "just",
    "now", "what", "which", "who", "whom", "whose", "this", "that", "these",
    "those", "i", "you", "he", "she", "it", "we", "they", "me", "him", "her",
    "us", "them", "my", "your", "his", "its", "our", "their", "and", "but",
    "or", "yet", "so", "if", "because", "although", "though", "while", "whereas",
    "main", "popular", "famous", "best", "top", "list", "tell", "give",
}

_KEYWORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9]*")
_PLACE_TAIL_RE = re.compile(r"\b(?:in|of)\s+([A-Za-z][A-Za-z\s]*?)\s*(?:[?.!])?\s*$")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower().strip())


def _extract_keywords(text: str) -> set[str]:
    return {
        w for w in _KEYWORD_RE.findall(_normalize(text))
        if len(w) > 3 and w not in _STOP_WORDS
    }


def _extract_place_tail(text: str) -> str | None:
    match = _PLACE_TAIL_RE.search(text)
    if not match:
        return None
    tail = match.group(1).strip()
    tail = re.sub(r"^(?:the|a|an)\s+", "", tail, flags=re.IGNORECASE).strip()
    return tail if tail else None


def _contains_tail(text: str, tail: str) -> bool:
    if not tail:
        return False
    norm = _normalize(text)
    tail_norm = _normalize(tail)
    if tail_norm in norm:
        return True
    parts = [p for p in tail_norm.split() if p]
    if len(parts) > 1 and all(part in norm for part in parts):
        return True
    return False
```

- [ ] **Step 2: Verify the file imports cleanly in the venv**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
python -c "import tools.router_py.context_guard as cg; print(cg._EVIDENCE_THRESHOLD, cg._MEMORY_THRESHOLD)"
```

Expected: prints `0.5 0.2` with no import error.

- [ ] **Step 3: Run the existing guard tests to confirm fallback behavior still passes**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/test_context_guard.py -v
```

Expected: some tests pass via keyword fallback; semantic-memory tests fail (they will be fixed in Task 2).

- [ ] **Step 4: Commit the guard rewrite**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/context_guard.py
git commit -m "feat: add semantic evidence and memory scorers with keyword fallback"
```

---

### Task 2: Update `test_context_guard.py` for semantic behavior

**Files:**
- Modify: `tools/router_py/test_context_guard.py`

**Interfaces:**
- Consumes: `score_evidence_relevance`, `is_evidence_relevant`, `score_memory_relevance`, `filter_memory_context` from `context_guard.py`.
- Produces: passing tests that verify semantic scoring and fallback paths.

- [ ] **Step 1: Replace `tools/router_py/test_context_guard.py` with the expanded test suite**

```python
"""Tests for the context relevance guard."""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from context_guard import (
    filter_memory_context,
    is_evidence_relevant,
    score_evidence_relevance,
    score_memory_relevance,
)


# ---------------------------------------------------------------------------
# Evidence relevance
# ---------------------------------------------------------------------------

def test_japan_tourism_rejects_china_evidence():
    evidence = {
        "title": "Tourism in China",
        "context": "Tourism in China is a growing industry...",
        "provider": "wikipedia",
    }
    score = score_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    )
    assert score == 0.0
    assert (
        is_evidence_relevant(
            "What are the main tourist attractions in Japan?", evidence
        )
        is False
    )


def test_japan_tourism_accepts_japan_evidence():
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry and contributor to the Japanese economy.",
        "provider": "wikipedia",
    }
    score = score_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    )
    assert score >= 0.6
    assert (
        is_evidence_relevant(
            "What are the main tourist attractions in Japan?", evidence
        )
        is True
    )


def test_query_without_place_uses_keyword_overlap():
    evidence = {
        "title": "Quantum computing",
        "context": "Quantum computing uses qubits which can exist in superposition.",
        "provider": "wikipedia",
    }
    assert is_evidence_relevant("What is quantum computing?", evidence) is True


def test_empty_evidence_is_irrelevant():
    assert score_evidence_relevance("What is Python?", {}) == 0.0
    assert is_evidence_relevance("What is Python?", {}) is False


def test_evidence_semantic_scorer_rejects_wrong_entity():
    """Cross-encoder path: Japan question vs China article."""
    fake_model = MagicMock()
    fake_model.predict.return_value = [-7.5]
    evidence = {
        "title": "Tourism in China",
        "context": "Tourism in China is a growing industry...",
    }
    with patch("context_guard._load_ce_model", return_value=fake_model):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score < 0.01
    assert is_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    ) is False


def test_evidence_semantic_scorer_accepts_relevant_doc():
    """Cross-encoder path: Japan question vs Japan article."""
    fake_model = MagicMock()
    fake_model.predict.return_value = [3.4]
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry...",
    }
    with patch("context_guard._load_ce_model", return_value=fake_model):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score >= 0.95
    assert is_evidence_relevance(
        "What are the main tourist attractions in Japan?", evidence
    ) is True


# ---------------------------------------------------------------------------
# Memory relevance
# ---------------------------------------------------------------------------

def test_memory_filter_drops_stale_china_turn():
    memory = (
        "User: What are the main tourist attractions in Japan?\n\n"
        "Assistant: Tourism in China is a growing industry..."
    )
    filtered = filter_memory_context(
        "What are interesting towns in Tokyo?", memory
    )
    assert "Tourism in China" not in filtered
    assert "User: What are the main tourist attractions in Japan?" in filtered


def test_memory_filter_keeps_relevant_turn():
    memory = (
        "User: What are the main tourist attractions in Japan?\n\n"
        "Assistant: Tourism in Japan is a major industry..."
    )
    filtered = filter_memory_context("What about Tokyo specifically?", memory)
    assert "Tourism in Japan" in filtered


def test_memory_relevance_uses_place_tail():
    turn = "User: What are the main tourist attractions in Japan?"
    assert score_memory_relevance("Tell me more about Japan", turn) >= 0.8


def test_filter_memory_returns_empty_when_nothing_relevant():
    memory = (
        "User: What is the weather in London?\n\n"
        "Assistant: It is rainy in London today."
    )
    filtered = filter_memory_context("Explain quantum computing", memory)
    assert filtered == ""


def test_memory_semantic_scorer_keeps_pronoun_reference():
    """Bi-encoder path: 'How does it work?' keeps the quantum computing turn."""
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts, {"How does it work?": [1.0, 0.0], "quantum": [0.9, 0.1]}
    )
    turn = "User: What is quantum computing?\nAssistant: Quantum computing uses qubits..."
    with patch("context_guard._load_bi_model", return_value=fake_model):
        score = score_memory_relevance("How does it work?", turn)
    assert score >= 0.8


def test_memory_semantic_scorer_drops_unrelated_topic():
    """Bi-encoder path: unrelated topic gets a low cosine score."""
    fake_model = MagicMock()
    fake_model.encode.side_effect = lambda texts, **_: _fake_embeddings(
        texts,
        {
            "Explain quantum computing": [1.0, 0.0],
            "London weather": [-0.5, 0.5],
        },
    )
    turn = "User: What is the weather in London?\nAssistant: It is rainy in London today."
    with patch("context_guard._load_bi_model", return_value=fake_model):
        score = score_memory_relevance("Explain quantum computing", turn)
    assert score < 0.2


def _fake_embeddings(texts, vectors):
    import numpy as np

    out = []
    for t in texts:
        key = next((k for k in vectors if k.lower() in t.lower()), None)
        out.append(vectors.get(key, [0.0, 1.0]))
    return np.array(out, dtype=float)


# ---------------------------------------------------------------------------
# Fallback paths
# ---------------------------------------------------------------------------

def test_evidence_fallback_to_keyword_when_model_missing():
    evidence = {
        "title": "Tourism in Japan",
        "context": "Tourism in Japan is a major industry...",
    }
    with patch("context_guard._load_ce_model", return_value=None):
        score = score_evidence_relevance(
            "What are the main tourist attractions in Japan?", evidence
        )
    assert score >= 0.6


def test_memory_fallback_to_keyword_when_model_missing():
    turn = "User: What are the main tourist attractions in Japan?"
    with patch("context_guard._load_bi_model", return_value=None):
        score = score_memory_relevance("Tell me more about Japan", turn)
    assert score >= 0.8
```

- [ ] **Step 2: Run the tests**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/test_context_guard.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit the test updates**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/test_context_guard.py
git commit -m "test: expand context guard tests for semantic scoring and fallback"
```

---

### Task 3: Wire evidence filtering into `execution_engine.py`

**Files:**
- Modify: `tools/router_py/execution_engine.py`

**Interfaces:**
- Consumes: `is_evidence_relevant` from `context_guard.py`.
- Produces: irrelevant evidence is dropped before `build_augmented_prompt` for AUGMENTED/EVIDENCE/FULL routes; direct-answer routes (WEATHER/TIME/FINANCE/NEWS) are unchanged.

- [ ] **Step 1: Add the import near the top of `execution_engine.py`**

Find the existing `from router_py...` imports and add:

```python
from router_py.context_guard import is_evidence_relevant
```

- [ ] **Step 2: Filter evidence after fetch for prompt-based routes**

After line 2391 (`evidence = await self._fetch_evidence(...)`), add:

```python
        # Filter retrieved evidence before it reaches any LLM prompt.
        # Direct-answer routes (WEATHER, TIME, FINANCE, NEWS) return evidence
        # as the response, so we skip filtering there to preserve completeness.
        if evidence and route.route in ("EVIDENCE", "FULL", "AUGMENTED"):
            if not is_evidence_relevant(question, evidence):
                self._logger.warning(
                    "Dropping irrelevant evidence for route %s: title=%r",
                    route.route,
                    evidence.get("title", "")[:60],
                )
                evidence = None
```

- [ ] **Step 3: Run the execution-engine tests**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/test_execution_engine_state.py -v -k evidence
```

Expected: existing tests still pass; no regressions.

- [ ] **Step 4: Commit the execution-engine wiring**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/execution_engine.py
git commit -m "feat: filter irrelevant evidence before prompt injection"
```

---

### Task 4: Wire memory filtering into `local_answer.py`

**Files:**
- Modify: `tools/router_py/local_answer.py`

**Interfaces:**
- Consumes: `filter_memory_context` from `context_guard.py`.
- Produces: session memory is pruned to relevant turns before prompt building.

- [ ] **Step 1: Add the import near the top of `local_answer.py`**

Find the existing imports in the file and add:

```python
from router_py.context_guard import filter_memory_context
```

- [ ] **Step 2: Filter session memory after the allowed check**

Around line 1960 (`if not self._is_memory_context_allowed(q_eval): session_memory = ""`), add the semantic filter when memory is present:

```python
        if session_memory.strip():
            session_memory = filter_memory_context(q_eval, session_memory)
            if session_memory.strip():
                self._diag_append("context_relevance_gate", "reuse_context")
```

Replace the existing unconditional `self._diag_append("context_relevance_gate", "reuse_context")` so the diagnostic only fires when memory actually survives filtering.

- [ ] **Step 3: Run the local-answer tests**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/test_local_answer.py -v -k memory
```

Expected: existing tests pass; memory-related assertions still hold.

- [ ] **Step 4: Commit the local-answer wiring**

```bash
cd /home/mike/lucy-v10
git add tools/router_py/local_answer.py
git commit -m "feat: filter session memory turns by semantic relevance"
```

---

### Task 5: Full verification and final commit

**Files:**
- Run: test suites across `tools/router_py`

- [ ] **Step 1: Run the focused guard and caller tests**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/test_context_guard.py tools/router_py/test_local_answer.py tools/router_py/test_execution_engine_state.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run the router_py test suite**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
pytest tools/router_py/ -q --ignore=tools/router_py/test_synthetic_adversarial.py
```

Expected: test suite passes or any failures are unrelated to the guard changes.

- [ ] **Step 3: Confirm no unrelated WIP is staged**

Run:
```bash
cd /home/mike/lucy-v10
git diff --stat --cached
```

Expected: only these files are in the commit set:
- `tools/router_py/context_guard.py`
- `tools/router_py/test_context_guard.py`
- `tools/router_py/execution_engine.py`
- `tools/router_py/local_answer.py`

If other files appear, reset them before committing.

- [ ] **Step 4: Final sanity check with a real model**

Run:
```bash
cd /home/mike/lucy-v10
source ui-v10/.venv/bin/activate
python - <<'PY'
from tools.router_py.context_guard import is_evidence_relevant, filter_memory_context

evidence = {
    "title": "Tourism in China",
    "context": "Tourism in China is a growing industry...",
}
print("China evidence for Japan query:", is_evidence_relevant(
    "What are the main tourist attractions in Japan?", evidence
))

memory = (
    "User: What are the main tourist attractions in Japan?\n\n"
    "Assistant: Tourism in China is a growing industry..."
)
print("Filtered memory:", filter_memory_context(
    "What are interesting towns in Tokyo?", memory
))
PY
```

Expected:
```
China evidence for Japan query: False
Filtered memory: User: What are the main tourist attractions in Japan?
```

- [ ] **Step 5: Push or finish the branch per project workflow**

No specific push command in this plan; follow the repository's normal branch workflow after verification.

---

## Self-review checklist

1. **Spec coverage**
   - Evidence scorer with cross-encoder → Task 1.
   - Memory scorer with bi-encoder → Task 1.
   - Keyword fallback → Task 1.
   - Lazy model loading → Task 1.
   - LLM-model independence → Tasks 3 and 4 only touch guard calls, not LLM backend.
   - English-only scope → Task 1 uses English-only models.
   - Integration into `execution_engine.py` → Task 3.
   - Integration into `local_answer.py` → Task 4.
   - Tests for semantic behavior and fallback → Task 2.

2. **Placeholder scan**
   - No "TBD", "TODO", or "implement later" strings.
   - Each step contains exact code or commands.

3. **Type consistency**
   - `score_evidence_relevance(question: str, evidence: dict[str, Any]) -> float` used throughout.
   - `filter_memory_context(question: str, memory_text: str, threshold: float = 0.2) -> str` used in Task 4.
   - `is_evidence_relevant(question: str, evidence: dict[str, Any], threshold: float = 0.5) -> bool` used in Task 3.

No gaps found.
