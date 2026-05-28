#!/usr/bin/env python3
"""
End-to-end simulation test for the background learner pipeline.

Runs entirely in a temp directory — never touches production router files.

What it tests:
  1. learn_once() ingests user feedback and auto-feedback
  2. Deduplication works (same query overwritten)
  3. Version snapshots are created before mutation
  4. Index, embeddings, and examples are updated
  5. Feedback files are moved to .processed
  6. maybe_auto_learn() triggers when threshold is met
  7. Kill-switch (.learner_disable) pauses learning

Safety: Every file path is patched to tmp_path. HybridRouterV2 is mocked.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Ensure router modules are importable
ROUTER_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(ROUTER_DIR))
sys.path.insert(0, str(ROUTER_DIR.parent.parent / "tools" / "router_py"))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_learner(tmp_path: Path, monkeypatch):
    """Patch all background_learner paths to tmp_path."""
    import background_learner as bl
    import auto_feedback as af

    monkeypatch.setattr(bl, "ROUTER_DIR", tmp_path)
    monkeypatch.setattr(bl, "INDEX_PATH", tmp_path / "comprehensive_index.jsonl")
    monkeypatch.setattr(bl, "EMBEDDINGS_PATH", tmp_path / "comprehensive_embeddings.npy")
    monkeypatch.setattr(bl, "EXAMPLES_PATH", tmp_path / "comprehensive_examples.json")
    monkeypatch.setattr(bl, "FEEDBACK_PATH", tmp_path / "user_feedback.jsonl")
    monkeypatch.setattr(bl, "LEARNED_PATH", tmp_path / "learned_examples.jsonl")
    monkeypatch.setattr(bl, "LOCK_PATH", tmp_path / ".learner_lock")
    monkeypatch.setattr(bl, "DISABLE_FLAG", tmp_path / ".learner_disable")
    monkeypatch.setattr(bl, "VERSIONS_DIR", tmp_path / "versions")
    monkeypatch.setattr(bl, "LOG_PROGRESS_PATH", tmp_path / ".router_log_progress")

    monkeypatch.setattr(af, "AUTO_FEEDBACK_PATH", tmp_path / "auto_feedback.jsonl")

    # Ensure versions dir exists
    bl.VERSIONS_DIR.mkdir(exist_ok=True)

    # Ensure auto-learn is enabled
    monkeypatch.delenv("LUCY_AUTO_LEARN", raising=False)
    if bl.DISABLE_FLAG.exists():
        bl.DISABLE_FLAG.unlink()

    return bl


@pytest.fixture
def mock_embedding_router(monkeypatch):
    """Replace HybridRouterV2 with a dummy that returns deterministic embeddings."""

    class DummyHybridRouterV2:
        def __init__(self, base_model: str = "") -> None:
            self.embeddings = np.array([])
            self.examples: list[dict] = []

        def fit(self, examples: list[dict]) -> None:
            self.examples = examples
            n = len(examples)
            # Deterministic dummy embeddings — shape (n, 384)
            rng = np.random.default_rng(42)
            self.embeddings = rng.random((n, 384)).astype(np.float32)

    monkeypatch.setattr(
        "background_learner.HybridRouterV2",
        DummyHybridRouterV2,
    )
    return DummyHybridRouterV2


@pytest.fixture
def starter_index(isolated_learner):
    """Seed a minimal starter index."""
    examples = [
        {
            "query": "What is 2+2?",
            "labels": {
                "intent_family": "local_answer",
                "evidence_mode": "not_required",
                "route": "LOCAL",
                "policy_override": "none",
            },
            "metadata": {"source": "seed", "timestamp": "2026-01-01T00:00:00Z"},
        },
        {
            "query": "What is the weather in Paris?",
            "labels": {
                "intent_family": "current_evidence",
                "evidence_mode": "required",
                "route": "WEATHER",
                "policy_override": "none",
            },
            "metadata": {"source": "seed", "timestamp": "2026-01-01T00:00:00Z"},
        },
    ]
    isolated_learner.save_index(examples)
    return examples


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLearnOnce:
    """End-to-end simulation of a single learning iteration."""

    def test_ingests_user_feedback(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """User feedback is read, index grows, embeddings rebuilt."""
        bl = isolated_learner

        # Write user feedback
        feedback = [
            {
                "timestamp": "2026-05-13T10:00:00Z",
                "query": "Tell me a joke",
                "correct_route": "LOCAL",
                "feedback_type": "correction",
            }
        ]
        bl.FEEDBACK_PATH.write_text("\n".join(json.dumps(f) for f in feedback) + "\n")

        result = bl.learn_once(verbose=False)

        assert result["added"] == 1
        assert result["total"] == 3  # 2 seed + 1 new
        assert result["new_from_feedback"] == 1

        # Verify index on disk
        index = bl.load_index()
        assert len(index) == 3
        queries = {ex["query"] for ex in index}
        assert "Tell me a joke" in queries

        # Verify embeddings exist
        assert bl.EMBEDDINGS_PATH.exists()
        embeddings = np.load(bl.EMBEDDINGS_PATH)
        assert embeddings.shape == (3, 384)

        # Verify examples JSON
        assert bl.EXAMPLES_PATH.exists()
        with open(bl.EXAMPLES_PATH) as f:
            saved = json.load(f)
        assert len(saved) == 3

        # Verify versioning
        versions = list(bl.VERSIONS_DIR.glob("v_*"))
        assert len(versions) == 1

        # Verify feedback was moved to .processed
        assert not bl.FEEDBACK_PATH.exists()
        assert bl.FEEDBACK_PATH.with_suffix(".processed").exists()

    def test_ingests_auto_feedback(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """Auto-feedback is read and ingested."""
        bl = isolated_learner
        import auto_feedback as af

        # Write auto-feedback
        auto_fb = [
            {
                "timestamp": "2026-05-13T10:00:00Z",
                "source": "auto_feedback",
                "query": "What is the capital of Germany?",
                "correct_route": "AUGMENTED",
                "reason": "augmented_answer_incomplete",
                "confidence": 0.7,
                "details": "AUGMENTED answer contained admission of ignorance",
                "feedback_type": "auto_correction",
            }
        ]
        af.AUTO_FEEDBACK_PATH.write_text(
            "\n".join(json.dumps(f) for f in auto_fb) + "\n"
        )

        result = bl.learn_once(verbose=False)

        assert result["added"] == 1
        assert result["new_from_auto"] == 1

        index = bl.load_index()
        assert any(
            ex["query"] == "What is the capital of Germany?"
            and ex["labels"]["route"] == "AUGMENTED"
            for ex in index
        )

    def test_deduplication_overwrites_old(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """Same query with different route overwrites previous entry."""
        bl = isolated_learner

        feedback = [
            {
                "timestamp": "2026-05-13T10:00:00Z",
                "query": "What is 2+2?",
                "correct_route": "AUGMENTED",
                "feedback_type": "correction",
            }
        ]
        bl.FEEDBACK_PATH.write_text("\n".join(json.dumps(f) for f in feedback) + "\n")

        result = bl.learn_once(verbose=False)
        print(f"DEBUG result: {result}")

        # 2 seed examples, but "What is 2+2?" is overwritten → still 2 total
        assert result["added"] == 0
        assert result["total"] == 2

        index = bl.load_index()
        for ex in index:
            print(f"DEBUG index: {ex['query']} -> {ex['labels']['route']}")
        entry = next(ex for ex in index if ex["query"] == "What is 2+2?")
        assert entry["labels"]["route"] == "AUGMENTED"
        assert entry["metadata"]["source"] == "user_feedback"

    def test_no_new_data_is_noop(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """When no feedback or logs exist, learn_once is a no-op."""
        bl = isolated_learner

        result = bl.learn_once(verbose=False)

        assert result["added"] == 0
        assert result["new_from_feedback"] == 0
        assert result["new_from_auto"] == 0
        # No version snapshot when nothing changed
        versions = list(bl.VERSIONS_DIR.glob("v_*"))
        assert len(versions) == 0

    def test_kill_switch_stops_learning(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """.learner_disable file prevents learning."""
        bl = isolated_learner

        bl.DISABLE_FLAG.write_text("paused")
        result = bl.learn_once(verbose=False)

        assert result["status"] == "disabled"
        assert result["added"] == 0

    def test_env_disable_stops_learning(
        self, isolated_learner, mock_embedding_router, starter_index, monkeypatch
    ):
        """LUCY_AUTO_LEARN=0 prevents learning."""
        monkeypatch.setenv("LUCY_AUTO_LEARN", "0")
        result = isolated_learner.learn_once(verbose=False)

        assert result["status"] == "disabled"
        assert result["added"] == 0


class TestMaybeAutoLearn:
    """Simulation of the auto-trigger mechanism."""

    def test_triggers_when_threshold_met(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """maybe_auto_learn returns True and spawns a thread when enough feedback."""
        bl = isolated_learner

        # Seed 3 feedback entries
        entries = [
            {
                "timestamp": "2026-05-13T10:00:00Z",
                "query": f"Query {i}",
                "correct_route": "LOCAL",
                "feedback_type": "correction",
            }
            for i in range(3)
        ]
        bl.FEEDBACK_PATH.write_text(
            "\n".join(json.dumps(e) for e in entries) + "\n"
        )

        with patch.object(bl, "learn_once", return_value={"added": 3}) as mock_learn:
            result = bl.maybe_auto_learn(min_entries=3)

        assert result is True
        mock_learn.assert_called_once()

        # The thread spawned is daemon; give it a moment
        time.sleep(0.1)

    def test_no_trigger_below_threshold(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """maybe_auto_learn returns False when not enough feedback."""
        bl = isolated_learner

        # Only 1 entry
        bl.FEEDBACK_PATH.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "query": "Only one",
                    "correct_route": "LOCAL",
                    "feedback_type": "correction",
                }
            )
            + "\n"
        )

        result = bl.maybe_auto_learn(min_entries=3)

        assert result is False

    def test_counts_user_plus_auto_feedback(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """Counts both user_feedback and auto_feedback toward threshold."""
        bl = isolated_learner
        import auto_feedback as af

        # 1 user + 2 auto = 3 total
        bl.FEEDBACK_PATH.write_text(
            json.dumps(
                {
                    "timestamp": "2026-05-13T10:00:00Z",
                    "query": "User feedback",
                    "correct_route": "LOCAL",
                    "feedback_type": "correction",
                }
            )
            + "\n"
        )
        af.AUTO_FEEDBACK_PATH.write_text(
            "\n".join(
                json.dumps(
                    {
                        "timestamp": "2026-05-13T10:00:00Z",
                        "source": "auto_feedback",
                        "query": f"Auto {i}",
                        "correct_route": "AUGMENTED",
                        "reason": "test",
                        "confidence": 0.7,
                        "details": "",
                        "feedback_type": "auto_correction",
                    }
                )
                for i in range(2)
            )
            + "\n"
        )

        with patch.object(bl, "learn_once", return_value={"added": 3}) as mock_learn:
            result = bl.maybe_auto_learn(min_entries=3)

        assert result is True


class TestEndToEnd:
    """Full pipeline simulation — closest thing to production without touching real files."""

    def test_full_pipeline(
        self, isolated_learner, mock_embedding_router, starter_index
    ):
        """
        Simulate a realistic scenario:
        - 2 seed examples in the index
        - 2 user corrections + 1 auto-feedback
        - learn_once() processes all, deduplicates, versions, rebuilds
        - Verify final state
        """
        bl = isolated_learner
        import auto_feedback as af

        # Seed feedback
        user_entries = [
            {
                "timestamp": "2026-05-13T10:00:00Z",
                "query": "What is the capital of France?",
                "correct_route": "AUGMENTED",
                "feedback_type": "correction",
            },
            {
                "timestamp": "2026-05-13T10:01:00Z",
                "query": "Tell me the news",
                "correct_route": "NEWS",
                "feedback_type": "correction",
            },
        ]
        bl.FEEDBACK_PATH.write_text(
            "\n".join(json.dumps(e) for e in user_entries) + "\n"
        )

        auto_entries = [
            {
                "timestamp": "2026-05-13T10:02:00Z",
                "source": "auto_feedback",
                "query": "What is quantum computing?",
                "correct_route": "AUGMENTED",
                "reason": "augmented_answer_incomplete",
                "confidence": 0.75,
                "details": "Local answer was too short",
                "feedback_type": "auto_correction",
            }
        ]
        af.AUTO_FEEDBACK_PATH.write_text(
            "\n".join(json.dumps(e) for e in auto_entries) + "\n"
        )

        result = bl.learn_once(verbose=False)

        # 2 seed + 2 user + 1 auto = 5 total
        assert result["added"] == 3
        assert result["total"] == 5
        assert result["new_from_feedback"] == 2
        assert result["new_from_auto"] == 1

        # Verify all expected queries are in the final index
        index = bl.load_index()
        queries = {ex["query"] for ex in index}
        assert queries == {
            "What is 2+2?",
            "What is the weather in Paris?",
            "What is the capital of France?",
            "Tell me the news",
            "What is quantum computing?",
        }

        # Verify routes are correct
        route_map = {ex["query"]: ex["labels"]["route"] for ex in index}
        assert route_map["What is the capital of France?"] == "AUGMENTED"
        assert route_map["Tell me the news"] == "NEWS"
        assert route_map["What is quantum computing?"] == "AUGMENTED"

        # Verify embeddings shape
        embeddings = np.load(bl.EMBEDDINGS_PATH)
        assert embeddings.shape == (5, 384)
        assert embeddings.dtype == np.float32

        # Verify version snapshot
        versions = sorted(bl.VERSIONS_DIR.glob("v_*"))
        assert len(versions) == 1
        vdir = versions[0]
        assert (vdir / "version.json").exists()
        assert (vdir / "comprehensive_index.jsonl").exists()

        # Verify cleanup
        assert not bl.FEEDBACK_PATH.exists()
        assert bl.FEEDBACK_PATH.with_suffix(".processed").exists()


class TestTimestampStripping:
    """Verify that mutable timestamps are kept out of the tracked examples file."""

    def test_rebuild_embeddings_strips_timestamps(self, isolated_learner, tmp_path):
        bl = isolated_learner

        # Seed examples with timestamps (simulating user_feedback entries)
        seed = [
            {
                "query": "What is 2+2?",
                "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
                "metadata": {"source": "router_log", "timestamp": "2026-05-13T18:16:42.043684+00:00"},
            },
            {
                "query": "What time is it?",
                "labels": {"intent_family": "time_query", "evidence_mode": "not_required", "route": "TIME", "policy_override": "none"},
                "metadata": {"source": "user_feedback", "timestamp": "2026-05-14T10:00:00Z"},
            },
        ]
        bl.save_index(seed)

        with patch.object(bl, "HybridRouterV2", return_value=MagicMock(
            fit=lambda ex: None,
            examples=seed,
            embeddings=np.zeros((2, 384), dtype=np.float32),
        )):
            bl.rebuild_embeddings(seed)

        # Tracked examples file must NOT contain timestamps
        with open(bl.EXAMPLES_PATH) as f:
            saved = json.load(f)
        for ex in saved:
            assert "timestamp" not in ex.get("metadata", {}), f"timestamp leaked into tracked file for: {ex['query']}"

        # Metadata file MUST contain the runtime timestamp
        assert bl.EXAMPLES_METADATA_PATH.exists()
        with open(bl.EXAMPLES_METADATA_PATH) as f:
            meta = json.load(f)
        assert "last_rebuilt" in meta
        assert meta["example_count"] == 2

    def test_examples_file_is_stable_after_rebuild(self, isolated_learner, tmp_path):
        bl = isolated_learner

        seed = [
            {
                "query": "What is 2+2?",
                "labels": {"intent_family": "local_answer", "evidence_mode": "not_required", "route": "LOCAL", "policy_override": "none"},
                "metadata": {"source": "router_log"},
            },
        ]
        bl.save_index(seed)

        with patch.object(bl, "HybridRouterV2", return_value=MagicMock(
            fit=lambda ex: None,
            examples=seed,
            embeddings=np.zeros((1, 384), dtype=np.float32),
        )):
            bl.rebuild_embeddings(seed)

        # Read first write
        with open(bl.EXAMPLES_PATH) as f:
            first = f.read()

        # Rebuild again with identical data
        with patch.object(bl, "HybridRouterV2", return_value=MagicMock(
            fit=lambda ex: None,
            examples=seed,
            embeddings=np.zeros((1, 384), dtype=np.float32),
        )):
            bl.rebuild_embeddings(seed)

        # Read second write
        with open(bl.EXAMPLES_PATH) as f:
            second = f.read()

        assert first == second, "Tracked examples file drifted between identical rebuilds"
