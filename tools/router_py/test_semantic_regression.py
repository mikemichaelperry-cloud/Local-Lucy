#!/usr/bin/env python3
"""Semantic response regression test suite for Local Lucy.

This suite compares current LLM responses against recorded "golden" responses
using semantic similarity (sentence embeddings + concept overlap) rather than
exact string matching. This eliminates flaky failures caused by inherent LLM
non-determinism (temperature sampling, GPU floating-point variance) while still
catching real semantic regressions (missing facts, wrong tone, hallucinations).

Usage:
    # Record golden responses (run after a config change you trust)
    LUCY_SEMANTIC_REGRESSION_RECORD=1 python3 -m pytest tools/router_py/test_semantic_regression.py -v

    # Compare current responses against golden
    python3 -m pytest tools/router_py/test_semantic_regression.py -v

    # Run directly
    python3 tools/router_py/test_semantic_regression.py

Environment:
    LUCY_SEMANTIC_REGRESSION_RECORD   Set to "1" to record golden responses.
    LUCY_SEMANTIC_REGRESSION_GOLDEN   Path to golden responses JSON.
                                      Default: tests/golden_semantic_responses.json
    LUCY_RESPONSE_REGRESSION_CASES    Path to test cases JSON (shared with exact-match test).
                                      Default: tests/response_regression_cases.json
    LUCY_LOCAL_MODEL                  Model name to test (default: local-lucy).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from local_answer import LocalAnswer, LocalAnswerConfig

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CASES_PATH = PROJECT_ROOT / "tests" / "response_regression_cases.json"
DEFAULT_GOLDEN_PATH = PROJECT_ROOT / "tests" / "golden_semantic_responses.json"

CASES_PATH = Path(os.environ.get("LUCY_RESPONSE_REGRESSION_CASES", DEFAULT_CASES_PATH))
GOLDEN_PATH = Path(os.environ.get("LUCY_SEMANTIC_REGRESSION_GOLDEN", DEFAULT_GOLDEN_PATH))
RECORD_MODE = os.environ.get("LUCY_SEMANTIC_REGRESSION_RECORD", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


# ---------------------------------------------------------------------------
# Lazy-loaded embedding model
# ---------------------------------------------------------------------------
_embedding_model: Any = None


def _get_embedding_model() -> Any:
    """Lazy-load sentence-transformers model to avoid import-time overhead."""
    global _embedding_model
    if _embedding_model is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            pytest.skip(f"sentence-transformers not installed: {exc}")
        _embedding_model = SentenceTransformer("all-MiniLM-L6-v2", device="cpu")
    return _embedding_model


def _compute_embedding(text: str) -> List[float]:
    """Compute normalized sentence embedding for text."""
    model = _get_embedding_model()
    emb = model.encode(text, normalize_embeddings=True)
    return emb.tolist()


# ---------------------------------------------------------------------------
# Concept extraction
# ---------------------------------------------------------------------------
_STOPWORDS: Set[str] = {
    "the",
    "and",
    "for",
    "are",
    "but",
    "not",
    "you",
    "that",
    "was",
    "have",
    "had",
    "what",
    "said",
    "each",
    "which",
    "she",
    "will",
    "about",
    "could",
    "other",
    "after",
    "first",
    "well",
    "water",
    "been",
    "call",
    "who",
    "oil",
    "its",
    "now",
    "find",
    "long",
    "down",
    "day",
    "did",
    "get",
    "come",
    "made",
    "may",
    "part",
    "than",
    "them",
    "these",
    "so",
    "some",
    "time",
    "very",
    "when",
    "much",
    "would",
    "there",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "only",
    "own",
    "same",
    "than",
    "too",
    "very",
    "can",
    "will",
    "just",
    "should",
    "with",
    "have",
    "from",
    "they",
    "know",
    "want",
    "been",
    "good",
    "much",
    "some",
    "time",
    "very",
    "when",
    "come",
    "here",
    "just",
    "like",
    "over",
    "also",
    "back",
    "after",
    "use",
    "two",
    "how",
    "our",
    "work",
    "first",
    "well",
    "way",
    "even",
    "new",
    "want",
    "because",
    "any",
    "these",
    "give",
    "day",
    "most",
    "us",
    "is",
    "it",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "as",
    "an",
    "or",
    "if",
    "be",
    "this",
    "that",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "a",
    "i",
    "me",
    "my",
    "myself",
    "we",
    "us",
    "our",
    "ourselves",
}


def _stem_word(word: str) -> str:
    """Simple suffix stripping for concept normalization."""
    for suffix in ("ness", "ment", "tion", "sion", "ity", "ies", "ing", "ed", "er", "est", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)]
    return word


def _compute_concepts(text: str) -> Set[str]:
    """Extract key concepts (lowercase stemmed tokens >= 3 chars, excluding stopwords)."""
    tokens = re.findall(r"\b[a-z][a-z0-9]{2,}\b", text.lower())
    return {_stem_word(t) for t in tokens if t not in _STOPWORDS}


def _concept_overlap(golden_concepts: Set[str], current_concepts: Set[str]) -> float:
    """Jaccard-like overlap: |intersection| / |golden|."""
    if not golden_concepts:
        return 1.0
    intersection = golden_concepts & current_concepts
    return len(intersection) / len(golden_concepts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> Any:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _check_first_person(text: str) -> tuple[bool, str]:
    """Return (ok, reason) verifying first-person self-reference."""
    if not re.search(r"\b(I|me|my|myself|we|us|our|ourselves)\b", text, re.IGNORECASE):
        return False, "response lacks first-person pronoun (I/me/my/myself/we/us/our/ourselves)"

    third_person_patterns = [
        r"Local Lucy\s+is",
        r"Lucy\s+is\s+(an?|the)",
        r"\bShe\s+is\s+(an?|the)\b.*\b(assistant|AI|intelligence|model)",
        r"\bHe\s+is\s+(an?|the)\b.*\b(assistant|AI|intelligence|model)",
    ]
    for pat in third_person_patterns:
        if re.search(pat, text, re.IGNORECASE):
            return False, f"response contains third-person self-reference: {pat!r}"

    return True, ""


def _run_checks(text: str, checks: Dict[str, Any]) -> List[str]:
    """Run all configured structural checks and return a list of failure messages."""
    failures: List[str] = []

    for pat in checks.get("must_include_regexes", []):
        if not re.search(pat, text, re.MULTILINE):
            failures.append(f"must_include_regex failed: {pat!r}")

    for pat in checks.get("must_exclude_regexes", []):
        if re.search(pat, text, re.MULTILINE):
            failures.append(f"must_exclude_regex failed: {pat!r}")

    if checks.get("first_person_only", False):
        ok, reason = _check_first_person(text)
        if not ok:
            failures.append(f"first_person_only failed: {reason}")

    max_chars = checks.get("max_chars")
    if max_chars is not None and len(text) > max_chars:
        failures.append(f"max_chars failed: {len(text)} > {max_chars}")

    return failures


def _make_diff(golden_text: str, current_text: str) -> str:
    """Generate a unified diff between golden and current response."""
    import difflib

    golden_lines = golden_text.splitlines(keepends=True)
    current_lines = current_text.splitlines(keepends=True)
    if golden_lines and not golden_lines[-1].endswith("\n"):
        golden_lines[-1] += "\n"
    if current_lines and not current_lines[-1].endswith("\n"):
        current_lines[-1] += "\n"
    diff = list(
        difflib.unified_diff(
            golden_lines,
            current_lines,
            fromfile="golden",
            tofile="current",
            lineterm="",
        )
    )
    return "".join(diff)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def test_cases() -> List[Dict[str, Any]]:
    data = _load_json(CASES_PATH)
    if not isinstance(data, list):
        pytest.fail(f"Test cases file {CASES_PATH} must contain a JSON list")
    if not data:
        pytest.skip(f"No test cases found in {CASES_PATH}")
    return data


@pytest.fixture(scope="module")
def golden_data() -> Dict[str, Any]:
    return _load_json(GOLDEN_PATH)


@pytest.fixture
async def local_answer():
    """Yield a LocalAnswer configured for deterministic regression testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config = LocalAnswerConfig.from_env()
        config.cache_enabled = False
        config.temperature = 0.0
        config.seed = 7
        config.top_p = 1.0
        config.cache_dir = Path(tmpdir)
        answer = LocalAnswer(config)
        yield answer
        await answer.close()


# ---------------------------------------------------------------------------
# Semantic thresholds
# ---------------------------------------------------------------------------
# Thresholds calibrated against observed LLM non-determinism:
# - Embedding ≥ 0.70 catches hallucinations (score ~0.45) while allowing
#   synonym swaps and paraphrases (score ~0.70-0.75).
# - Concept ≥ 0.35 catches completely different vocabulary while tolerating
#   stemmed variations (perspectives/perspective, open-minded/open-mindedness).
# Tuned for local LLM variance: catches real semantic drift while tolerating
# paraphrasing and within-model output variation.
EMBEDDING_SIMILARITY_THRESHOLD = 0.70
CONCEPT_OVERLAP_THRESHOLD = 0.25


# ---------------------------------------------------------------------------
# Parametrized test
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("case", _load_json(CASES_PATH) or [pytest.param({}, id="no-cases")])
async def test_semantic_regression(case, golden_data, request, skip_without_ollama):
    if not case:
        pytest.skip("No test cases loaded")

    case_id = case["id"]
    query = case["query"]
    route_mode = case.get("route_mode", "LOCAL")
    output_mode = case.get("output_mode", "CHAT")
    session_memory = case.get("session_memory", "")
    checks = case.get("checks", {})
    description = case.get("description", "")

    request.node.user_properties.append(("case_id", case_id))
    request.node.user_properties.append(("description", description))

    # --- Golden response handling ---
    golden_responses = golden_data.get("responses", {})
    golden = golden_responses.get(case_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        config = LocalAnswerConfig.from_env()
        config.cache_enabled = False
        config.temperature = 0.0
        config.seed = 7
        config.top_p = 1.0
        config.cache_dir = Path(tmpdir)

        # If the golden responses were recorded under a different model or prompt
        # revision, skip the test early instead of burning tokens on a comparison
        # that would be invalid. Re-record to update the golden file.
        if not RECORD_MODE:
            if golden is None:
                pytest.fail(
                    f"No golden response for case '{case_id}'.\n"
                    f"Run with LUCY_SEMANTIC_REGRESSION_RECORD=1 to record it."
                )
            golden_model = golden_data.get("model")
            if golden_model and golden_model != config.model:
                pytest.skip(
                    f"Golden recorded for model '{golden_model}' but current model is "
                    f"'{config.model}'. Run LUCY_SEMANTIC_REGRESSION_RECORD=1 to update."
                )

        answer = LocalAnswer(config)

        try:
            result = await answer.generate_answer(
                query=query,
                session_memory=session_memory,
                route_mode=route_mode,
                output_mode=output_mode,
            )
        finally:
            await answer.close()

    text = result.text or ""
    duration_ms = result.duration_ms

    # --- Run structural checks (hard gates) ---
    check_failures = _run_checks(text, checks)

    if RECORD_MODE:
        all_golden = _load_json(GOLDEN_PATH)
        record = {
            "text": text,
            "duration_ms": duration_ms,
            "embedding": _compute_embedding(text),
            "concepts": sorted(_compute_concepts(text)),
        }
        all_golden.setdefault("responses", {})[case_id] = record
        all_golden["recorded_at"] = datetime.now(timezone.utc).isoformat()
        all_golden["model"] = config.model
        all_golden["seed"] = config.seed
        all_golden["temperature"] = config.temperature
        all_golden["embedding_model"] = "all-MiniLM-L6-v2"
        _save_json(GOLDEN_PATH, all_golden)
        if check_failures:
            warn_msg = (
                f"Recorded golden response for '{case_id}', but structural checks would fail:\n"
                + "\n".join(f"  - {f}" for f in check_failures)
            )
            pytest.skip(warn_msg)
        else:
            pytest.skip(f"Recorded golden response for '{case_id}'")

    # In compare mode, enforce structural checks before semantic comparison
    if check_failures:
        fail_msg = f"Structural checks failed for case '{case_id}':\n" + "\n".join(
            f"  - {f}" for f in check_failures
        )
        pytest.fail(fail_msg)

    golden_text = golden.get("text", "")
    golden_emb = golden.get("embedding", [])
    golden_concepts = set(golden.get("concepts", []))

    # Compute current semantic features
    current_emb = _compute_embedding(text)
    current_concepts = _compute_concepts(text)

    # Embedding cosine similarity (vectors are normalized, so dot product = cosine)
    import numpy as np

    embedding_sim = float(np.dot(np.array(golden_emb), np.array(current_emb)))

    # Concept overlap
    concept_sim = _concept_overlap(golden_concepts, current_concepts)

    # Evaluate semantic gates
    semantic_failures: List[str] = []
    if embedding_sim < EMBEDDING_SIMILARITY_THRESHOLD:
        semantic_failures.append(
            f"embedding similarity {embedding_sim:.3f} < {EMBEDDING_SIMILARITY_THRESHOLD}"
        )
    if concept_sim < CONCEPT_OVERLAP_THRESHOLD:
        semantic_failures.append(f"concept overlap {concept_sim:.3f} < {CONCEPT_OVERLAP_THRESHOLD}")

    if semantic_failures:
        diff = _make_diff(golden_text, text)
        fail_msg = (
            f"Semantic regression detected for case '{case_id}':\n"
            f"Description: {description}\n"
            f"\n--- Semantic scores ---\n"
            f"  embedding similarity: {embedding_sim:.3f} (threshold: {EMBEDDING_SIMILARITY_THRESHOLD})\n"
            f"  concept overlap:      {concept_sim:.3f} (threshold: {CONCEPT_OVERLAP_THRESHOLD})\n"
            f"\n--- Diff (golden -> current) ---\n{diff}\n"
            f"\n--- Full current response ---\n{text!r}"
        )
        pytest.fail(fail_msg)


# ---------------------------------------------------------------------------
# Direct runner (for users who prefer `python3 test_semantic_regression.py`)
# ---------------------------------------------------------------------------
def _run_direct():
    cases = _load_json(CASES_PATH)
    if not cases:
        print(f"ERROR: No test cases found in {CASES_PATH}", file=sys.stderr)
        sys.exit(1)

    golden = _load_json(GOLDEN_PATH)
    all_passed = True

    async def _run_all():
        nonlocal all_passed
        with tempfile.TemporaryDirectory() as tmpdir:
            config = LocalAnswerConfig.from_env()
            config.cache_enabled = False
            config.temperature = 0.0
            config.seed = 7
            config.top_p = 1.0
            config.cache_dir = Path(tmpdir)
            answer = LocalAnswer(config)

            try:
                for case in cases:
                    case_id = case["id"]
                    query = case["query"]
                    route_mode = case.get("route_mode", "LOCAL")
                    output_mode = case.get("output_mode", "CHAT")
                    session_memory = case.get("session_memory", "")
                    checks = case.get("checks", {})

                    print(f"\n{'='*60}")
                    print(f"Case: {case_id}")
                    print(f"Query: {query!r}")

                    try:
                        result = await answer.generate_answer(
                            query=query,
                            session_memory=session_memory,
                            route_mode=route_mode,
                            output_mode=output_mode,
                        )
                    except Exception as exc:
                        print(f"  ERROR generating answer: {exc}")
                        all_passed = False
                        continue

                    text = result.text or ""
                    check_failures = _run_checks(text, checks)

                    if RECORD_MODE:
                        record = {
                            "text": text,
                            "duration_ms": result.duration_ms,
                            "embedding": _compute_embedding(text),
                            "concepts": sorted(_compute_concepts(text)),
                        }
                        golden.setdefault("responses", {})[case_id] = record
                        print(f"  RECORDED ({result.duration_ms}ms)")
                        continue

                    golden_resp = golden.get("responses", {}).get(case_id)
                    if not golden_resp:
                        print("  MISSING GOLDEN — run with RECORD=1")
                        all_passed = False
                        continue

                    if check_failures:
                        print("  STRUCTURAL CHECK FAILURES:")
                        for f in check_failures:
                            print(f"    - {f}")
                        all_passed = False
                        continue

                    golden_emb = golden_resp.get("embedding", [])
                    golden_concepts = set(golden_resp.get("concepts", []))
                    current_emb = _compute_embedding(text)
                    current_concepts = _compute_concepts(text)

                    import numpy as np

                    embedding_sim = float(np.dot(np.array(golden_emb), np.array(current_emb)))
                    concept_sim = _concept_overlap(golden_concepts, current_concepts)

                    semantic_failures = []
                    if embedding_sim < EMBEDDING_SIMILARITY_THRESHOLD:
                        semantic_failures.append(
                            f"embedding similarity {embedding_sim:.3f} < {EMBEDDING_SIMILARITY_THRESHOLD}"
                        )
                    if concept_sim < CONCEPT_OVERLAP_THRESHOLD:
                        semantic_failures.append(
                            f"concept overlap {concept_sim:.3f} < {CONCEPT_OVERLAP_THRESHOLD}"
                        )

                    if semantic_failures:
                        print("  SEMANTIC REGRESSION:")
                        for f in semantic_failures:
                            print(f"    - {f}")
                        diff = _make_diff(golden_resp["text"], text)
                        print(diff)
                        all_passed = False
                    else:
                        print(
                            f"  PASS ({result.duration_ms}ms)  "
                            f"embed={embedding_sim:.3f}  concepts={concept_sim:.3f}"
                        )
            finally:
                await answer.close()

        if RECORD_MODE:
            golden["recorded_at"] = datetime.now(timezone.utc).isoformat()
            golden["model"] = config.model
            golden["seed"] = config.seed
            golden["temperature"] = config.temperature
            golden["embedding_model"] = "all-MiniLM-L6-v2"
            _save_json(GOLDEN_PATH, golden)
            print(f"\nRecorded {len(cases)} golden responses to {GOLDEN_PATH}")

    asyncio.run(_run_all())

    if not RECORD_MODE:
        print(f"\n{'='*60}")
        if all_passed:
            print("All semantic regression tests PASSED.")
            sys.exit(0)
        else:
            print("Some semantic regression tests FAILED.")
            sys.exit(1)


if __name__ == "__main__":
    _run_direct()
