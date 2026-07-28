#!/usr/bin/env python3
"""MiniLM semantic guard for policy decisions."""

import os
import re
import threading
import warnings
from collections import OrderedDict
from typing import Literal

# Suppress noisy transformers/sentence-transformers progress bars during model
# load. Policy module loads its own MiniLM instance if semantic checks are used.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

# ---------------------------------------------------------------------------
# Semantic guard — MiniLM-based classification for personal/family vs
# medical/veterinary queries.  Runs before keyword-based veterinary Tier 1
# so that queries like "Where is my cat?" are not incorrectly flagged as
# veterinary_context just because they contain an animal species word.
# ---------------------------------------------------------------------------

_SEMANTIC_MODEL = None  # Lazy-loaded SentenceTransformer or False if unavailable

# Reference queries for each category — used to compute centroid embeddings
_SEMANTIC_REFS = {
    "personal_family_context": [
        "how old is my daughter",
        "how old is my son",
        "what is my daughter's name",
        "what is my dog's name",
        "tell me about my son",
        "tell me about my daughter",
        "do i have any children",
        "how many kids do i have",
        "who is my wife",
        "who is my husband",
        "where is my cat",
        "where is my dog",
        "is my cat hungry",
        "when did i get my dog",
        "my wife's birthday",
        "my dog likes to play",
        "my cat sleeps all day",
        "who are my children",
        "what is my wife's name",
        "do i have a pet",
    ],
    "medical_context": [
        "my daughter has a fever",
        "my child has stomach pain",
        "my son is vomiting",
        "my wife has chest pain",
        "my husband has a headache",
        "my mother has diabetes",
        "my father has heart disease",
        "i have a fever",
        "my head hurts",
        "i am feeling sick",
        "what are the symptoms of flu",
        "how to treat a headache",
        "diabetes medication",
        "heart attack symptoms",
    ],
    "veterinary_context": [
        "my dog has diarrhea",
        "my cat is vomiting",
        "my dog is not eating",
        "my cat has a fever",
        "my dog is limping",
        "my dog has been vomiting",
        "my dog may have eaten chocolate",
        "my cat is refusing food",
        "my dog has a lump",
        "my cat has worms",
        "my dog is coughing",
        "my cat is lethargic",
        "my dog is scratching",
        "my cat is losing hair",
    ],
}

_SEMANTIC_EMBEDDINGS: dict[str, "numpy.ndarray | None"] = {k: None for k in _SEMANTIC_REFS}

# Thread-safe LRU cache for per-query MiniLM embeddings (Phase 7).
# Key is the normalized query string; value is the normalized embedding vector.
_EMBEDDING_CACHE: OrderedDict[str, "numpy.ndarray"] = OrderedDict()
_EMBEDDING_CACHE_LOCK = threading.Lock()


def _embedding_cache_size() -> int:
    """Return the configured LRU cache size."""
    try:
        return max(1, int(os.environ.get("LUCY_EMBEDDING_CACHE_SIZE", "1024")))
    except Exception:
        return 1024


def _get_cached_embedding(query: str) -> "numpy.ndarray | None":
    """Return a cached normalized embedding if present; updates LRU order."""
    key = query.lower().strip()
    with _EMBEDDING_CACHE_LOCK:
        embedding = _EMBEDDING_CACHE.get(key)
        if embedding is not None:
            _EMBEDDING_CACHE.move_to_end(key)
        return embedding


def _set_cached_embedding(query: str, embedding: "numpy.ndarray") -> None:
    """Store a normalized embedding in the LRU cache."""
    key = query.lower().strip()
    max_size = _embedding_cache_size()
    with _EMBEDDING_CACHE_LOCK:
        _EMBEDDING_CACHE[key] = embedding
        _EMBEDDING_CACHE.move_to_end(key)
        while len(_EMBEDDING_CACHE) > max_size:
            _EMBEDDING_CACHE.popitem(last=False)


def _get_semantic_model():
    """Lazy-load the MiniLM model; returns None if unavailable.

    Uses CUDA if available (~22MB VRAM, ~10× faster than CPU).
    Falls back to CPU gracefully.  ``local_files_only=True`` avoids a blocking
    Hugging Face Hub update check on every cold start.
    """
    global _SEMANTIC_MODEL
    if _SEMANTIC_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            import torch

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    cuda_ok = torch.cuda.is_available()
            except Exception:
                cuda_ok = False
            device = "cuda" if cuda_ok else "cpu"
            _SEMANTIC_MODEL = SentenceTransformer(
                "sentence-transformers/all-MiniLM-L6-v2",
                device=device,
                local_files_only=True,
            )
        except Exception:
            _SEMANTIC_MODEL = False
    return _SEMANTIC_MODEL if _SEMANTIC_MODEL is not False else None


def _get_semantic_embeddings(category: str):
    """Return normalized reference embeddings for a category (cached)."""
    global _SEMANTIC_EMBEDDINGS
    cache = _SEMANTIC_EMBEDDINGS.get(category)
    if cache is not None:
        return cache
    model = _get_semantic_model()
    if model is None:
        return None
    import numpy as np

    embeddings = model.encode(_SEMANTIC_REFS[category], convert_to_numpy=True)
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-9
    cache = embeddings / norms
    _SEMANTIC_EMBEDDINGS[category] = cache
    return cache


def _semantic_classify(query: str) -> str | None:
    """
    Use MiniLM embeddings to classify a query as personal_family_context,
    medical_context, or veterinary_context.

    Returns the category with the highest max-similarity score, but only
    if the top score exceeds a threshold (indicating reasonable confidence).
    Returns None if the model is unavailable or confidence is too low.

    Query embeddings are cached in a thread-safe LRU cache keyed by the
    normalized query string to avoid redundant MiniLM encode() calls.
    """
    model = _get_semantic_model()
    if model is None:
        return None
    import numpy as np

    q_embed = _get_cached_embedding(query)
    if q_embed is None:
        q_embed = model.encode(query.lower().strip(), convert_to_numpy=True)
        q_embed = q_embed / (np.linalg.norm(q_embed) + 1e-9)
        _set_cached_embedding(query, q_embed)
    scores = {}
    for category in _SEMANTIC_REFS:
        ref_embeds = _get_semantic_embeddings(category)
        if ref_embeds is None:
            continue
        scores[category] = float(np.max(np.dot(ref_embeds, q_embed)))
    if not scores:
        return None
    top_cat = max(scores, key=scores.get)
    if scores[top_cat] < 0.40:
        return None
    return top_cat
