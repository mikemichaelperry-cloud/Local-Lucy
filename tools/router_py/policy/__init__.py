#!/usr/bin/env python3
"""Local Lucy router policy package."""

import os

# Suppress noisy transformers/sentence-transformers progress bars during model
# load. Policy module loads its own MiniLM instance if semantic checks are used.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")

from .core import (
    AugmentationPolicy,
    manifest_evidence_selection_label,
    normalize_augmentation_policy,
    provider_usage_class_for,
    requires_evidence_mode,
)
from .finance import _is_personal_finance_reasoning
from .historical import _is_historical_query
from .semantic import (
    _embedding_cache_size,
    _get_cached_embedding,
    _get_semantic_embeddings,
    _get_semantic_model,
    _semantic_classify,
    _set_cached_embedding,
)
from .utils import _phrase_in_text

__all__ = [
    "AugmentationPolicy",
    "normalize_augmentation_policy",
    "requires_evidence_mode",
    "provider_usage_class_for",
    "manifest_evidence_selection_label",
    "_phrase_in_text",
    "_get_semantic_model",
    "_get_semantic_embeddings",
    "_semantic_classify",
    "_embedding_cache_size",
    "_get_cached_embedding",
    "_set_cached_embedding",
    "_is_personal_finance_reasoning",
    "_is_historical_query",
]
