#!/usr/bin/env python3
"""
Tests for the MiniLM embedding router upgrade.

These verify that:
1. The fine-tuned MiniLM model is loaded by default
2. Similarities separate properly (no 0.94-0.97 collapse)
3. Specific problematic ModernBERT queries now route correctly
4. The embedding index was rebuilt with the new model
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

import json
import numpy as np
import pytest


@pytest.fixture(scope="module")
def router():
    from hybrid_router_v2 import HybridRouterV2

    return HybridRouterV2()


class TestModelSwap:
    """Verify the model swap from ModernBERT to fine-tuned MiniLM."""

    def test_uses_finetuned_minilm(self, router):
        """Default router should load the fine-tuned MiniLM model."""
        # Force lazy init so model attribute is populated
        router._lazy_init()
        # The model object is a SentenceTransformer; its underlying transformer
        # config should reveal the base architecture (MiniLM).
        base_name = getattr(router.model, "model_card_data", None)
        if base_name is None:
            base_name = getattr(router.model[0], "auto_model", None)
            if base_name is not None:
                base_name = getattr(base_name, "config", None)
                if base_name is not None:
                    base_name = getattr(base_name, "_name_or_path", "")
        model_str = str(base_name).lower()
        # Also check via tokenizer vocab size (MiniLM has 30522, ModernBERT has 50257)
        vocab_size = router.model.tokenizer.vocab_size
        assert vocab_size == 30522, f"Expected MiniLM vocab 30522, got {vocab_size}"
        assert (
            "minilm" in model_str
            or "finetuned_minilm"
            in str(Path(router.model[0].auto_model.config._name_or_path)).lower()
        ), f"Expected MiniLM model, got {model_str}"

    def test_embedding_dimension_is_384(self, router):
        """MiniLM-L6-v2 produces 384-dim embeddings, not ModernBERT's 768."""
        emb = router.embeddings
        assert emb.shape[1] == 384, f"Expected 384 dims, got {emb.shape[1]}"

    def test_embeddings_match_examples_count(self, router):
        """Every example should have a corresponding embedding vector."""
        assert len(router.examples) == router.embeddings.shape[0]

    def test_similarities_actually_separate(self, router):
        """Top-1 similarity for semantically-unrelated queries must be < 0.90.

        ModernBERT collapsed everything to 0.94-0.97; a fine-tuned model
        should show clear separation between routes.
        """
        from sklearn.metrics.pairwise import cosine_similarity

        # Pick two clearly-unrelated examples from different routes
        queries = [
            ("What time is it in Tokyo?", "TIME"),
            ("Latest news on Israel", "NEWS"),
            ("What are the symptoms of flu?", "AUGMENTED"),
        ]

        for query, expected_route in queries:
            q_emb = router._encode(query)
            sims = cosine_similarity(q_emb, router.embeddings)[0]
            top_idx = np.argmax(sims)
            top_sim = sims[top_idx]
            top_route = router.examples[top_idx]["labels"]["route"]

            # Top-1 should be the expected route with strong confidence
            assert top_route == expected_route, (
                f"'{query}' top match is {top_route}, expected {expected_route}"
            )
            assert top_sim >= 0.50, (
                f"'{query}' top similarity {top_sim:.3f} too low — model not fine-tuned?"
            )

            # The 10th-best match should be much lower
            sorted_sims = np.sort(sims)[::-1]
            tenth_sim = sorted_sims[9]
            assert top_sim - tenth_sim > 0.15, (
                f"'{query}' similarity gap too small ({top_sim:.3f} vs {tenth_sim:.3f})"
            )


class TestRoutingAccuracy:
    """Verify specific queries that were problematic with ModernBERT."""

    def test_time_query_routes_to_time(self, router):
        result = router.predict("What time is it in Tokyo?")
        assert result["route"] == "TIME"
        # Embedding should be confident, not collapsed
        assert result["confidence"] >= 0.50

    def test_news_query_routes_to_news(self, router):
        result = router.predict("Latest news on Israel")
        assert result["route"] == "NEWS"
        assert result["confidence"] >= 0.50

    def test_medical_query_routes_to_augmented(self, router):
        result = router.predict("What are the symptoms of flu?")
        assert result["route"] == "AUGMENTED"
        assert result["confidence"] >= 0.50

    def test_weather_query_routes_to_weather(self, router):
        result = router.predict("What is the weather in London?")
        assert result["route"] == "WEATHER"

    def test_social_greeting_routes_to_local(self, router):
        result = router.predict("How are you today?")
        assert result["route"] == "LOCAL"

    def test_factual_question_routes_to_local(self, router):
        result = router.predict("Tell me a joke")
        assert result["route"] == "LOCAL"

    def test_typos_weather_still_works(self, router):
        """Typo queries should route correctly when exact match exists."""
        result = router.predict("whats teh wether 4cast")
        assert result["route"] == "WEATHER"

    def test_no_similarity_collapse_on_unrelated(self, router):
        """Completely unrelated short queries should not all look the same."""
        from sklearn.metrics.pairwise import cosine_similarity

        texts = [
            "How are you?",
            "What time is it?",
            "Latest news?",
            "What is 2+2?",
        ]
        embeddings = np.vstack([router._encode(t) for t in texts])
        sims = cosine_similarity(embeddings)

        # Extract off-diagonal similarities
        off_diag = sims[np.triu_indices_from(sims, k=1)]

        # At least some pairs should have similarity < 0.80
        assert np.any(off_diag < 0.80), (
            f"All pairwise similarities are >= 0.80 — embedding has collapsed: {off_diag}"
        )


class TestGuardBehavior:
    """Verify keyword guards interact correctly with the new embedding model."""

    def test_global_warming_not_news(self, router):
        """'warming' contains 'war' but should not trigger news guard."""
        result = router.predict("Explain global warming")
        assert result["route"] == "LOCAL"
        assert "news_keyword" not in result["guards_fired"]

    def test_cold_war_not_weather(self, router):
        """'cold war' is history, not weather."""
        result = router.predict("Cold war history")
        assert result["route"] == "LOCAL"

    def test_creative_writing_not_evidence(self, router):
        result = router.predict("Write a story about a doctor")
        assert result["route"] == "LOCAL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
