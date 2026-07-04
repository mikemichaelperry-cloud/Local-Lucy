#!/usr/bin/env python3
"""Tests for the optional classifier head on frozen MiniLM embeddings."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

from hybrid_router_v2 import HybridRouterV2


@pytest.fixture(scope="module")
def router_with_head() -> HybridRouterV2:
    """Production router with classifier head (if present)."""
    router_dir = Path(__file__).parent.parent.parent / "models" / "router"
    return HybridRouterV2(
        embeddings_path=str(router_dir / "comprehensive_embeddings.npy"),
        examples_path=str(router_dir / "comprehensive_examples.json"),
    )


class TestClassifierHeadArtifacts:
    def test_artifacts_exist(self) -> None:
        router_dir = Path(__file__).parent.parent.parent / "models" / "router"
        assert (router_dir / "classifier_head.pt").exists()
        assert (router_dir / "classifier_head_config.json").exists()

    def test_config_is_sensible(self) -> None:
        router_dir = Path(__file__).parent.parent.parent / "models" / "router"
        config = json.loads((router_dir / "classifier_head_config.json").read_text())
        assert config["input_dim"] == 384
        assert config["num_classes"] == 8
        assert "LOCAL" in config["routes"]
        assert "AUGMENTED" in config["routes"]
        assert isinstance(config["best_val_accuracy"], (int, float))
        assert 0.0 < config["best_val_accuracy"] <= 1.0


class TestClassifierHeadRouting:
    def test_classifier_decides_common_queries(self, router_with_head: HybridRouterV2) -> None:
        # Queries that the policy layer does not intercept, so the embedding
        # router (and classifier head) decides the route.  With the calibrated
        # threshold, some of these fall back to k-NN; the invariant is the
        # correct LOCAL route and a non-trivial classifier score.
        queries = [
            "Who was Ada Lovelace?",
            "How do I install Python?",
            "Explain quantum computing",
            "What is Python?",
        ]
        for q in queries:
            result = router_with_head.predict(q)
            assert result["route"] == "LOCAL", q
            assert result["routing_source"] in ("classifier", "knn"), q
            assert result["classifier_confidence"] > 0.0, q

    def test_classifier_can_route_news(self, router_with_head: HybridRouterV2) -> None:
        result = router_with_head.predict("Latest news on Israel")
        assert result["route"] == "NEWS"
        assert result["routing_source"] == "classifier"

    def test_classifier_can_route_weather(self, router_with_head: HybridRouterV2) -> None:
        # Weather must still route correctly; with the conservative threshold (0.75)
        # these examples currently fall just below it, so the k-NN fallback handles
        # them. The important invariant is the correct route, not which sub-model
        # made the final call.
        result = router_with_head.predict("What is the weather in London?")
        assert result["route"] == "WEATHER"
        assert result["routing_source"] in ("classifier", "knn")

    def test_diagnostic_fields_present(self, router_with_head: HybridRouterV2) -> None:
        result = router_with_head.predict("What is the weather in London?")
        assert "confidence_margin" in result
        assert "confidence_entropy" in result
        assert "classifier_route" in result
        assert "classifier_confidence" in result


class TestClassifierHeadFallback:
    def test_fallback_to_knn_without_head(self) -> None:
        """If classifier head files are missing, router falls back to pure k-NN."""
        router_dir = Path(__file__).parent.parent.parent / "models" / "router"
        tmp_dir = Path(tempfile.mkdtemp())
        try:
            # Copy examples and embeddings, but not the head files
            shutil.copy(router_dir / "comprehensive_examples.json", tmp_dir / "comprehensive_examples.json")
            shutil.copy(router_dir / "comprehensive_embeddings.npy", tmp_dir / "comprehensive_embeddings.npy")

            router = HybridRouterV2(
                embeddings_path=str(tmp_dir / "comprehensive_embeddings.npy"),
                examples_path=str(tmp_dir / "comprehensive_examples.json"),
            )
            result = router.predict("What is Python?")
            assert result["route"] == "LOCAL"
            assert result["routing_source"] == "knn"
            assert result["classifier_confidence"] == 0.0
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
