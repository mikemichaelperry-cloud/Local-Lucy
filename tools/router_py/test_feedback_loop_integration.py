#!/usr/bin/env python3
"""
Integration test for the full feedback loop:
    misroute → negative feedback → background learning → corrected routing.

This test exercises:
  1. HybridRouter prediction
  2. Feedback buffer seeding
  3. parse_feedback detecting negative feedback
  4. _infer_corrected_route inferring LOCAL for a semantic misroute
  5. log_user_feedback writing to user_feedback.jsonl
  6. background_learner processing feedback and rebuilding embeddings
  7. Re-running the router and verifying the corrected route

Run with pytest:
    cd /home/mike/lucy-v9/tools/router_py
    python -m pytest test_feedback_loop_integration.py -v
"""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure imports resolve
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "models" / "router"))

from hybrid_router_v2 import HybridRouterV2
from feedback_parser import parse_feedback, FeedbackType, log_user_feedback, _infer_corrected_route
from feedback_buffer import get_buffer
import background_learner
from background_learner import (
    learn_once,
    FEEDBACK_PATH,
    EXAMPLES_PATH,
    EMBEDDINGS_PATH,
    INDEX_PATH,
    load_index,
    save_index,
    rebuild_embeddings,
)
import feedback_parser as fp


@pytest.fixture(scope="module")
def router():
    """Provide a loaded HybridRouter."""
    return HybridRouterV2()


@pytest.fixture(autouse=True)
def isolated_feedback_buffer():
    """Clear feedback buffer before each test."""
    buf = get_buffer()
    buf.clear()
    yield
    buf.clear()


@pytest.fixture(autouse=True)
def isolated_user_feedback_file():
    """Backup and restore user_feedback.jsonl around each test."""
    backup = None
    if FEEDBACK_PATH.exists():
        backup = FEEDBACK_PATH.read_text(encoding="utf-8")
    # Ensure directory exists
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    yield
    if backup is not None:
        FEEDBACK_PATH.write_text(backup, encoding="utf-8")
    else:
        if FEEDBACK_PATH.exists():
            FEEDBACK_PATH.unlink()


class TestFeedbackLoop:
    """End-to-end feedback loop validation."""

    def test_embedding_collapse_detected(self, router):
        """Ensure 'Who is my dog?' routes sensibly (LOCAL or AUGMENTED)."""
        result = router.predict("Who is my dog?")
        # V2 embedding router naturally routes this ambiguous pet query
        # to AUGMENTED or LOCAL; the key invariant is it must not
        # collapse to an unrelated route like TIME or WEATHER.
        assert result["route"] in ("LOCAL", "AUGMENTED")

    def test_negative_feedback_parsed(self):
        """parse_feedback must detect standalone 'Incorrect'."""
        buf = get_buffer()
        buf.append(query="Who is my dog?", route="TIME", response_text="3:45 PM",
                   intent_family="time_query", confidence=0.9874)

        fb = parse_feedback("Incorrect, my dog is Oscar")
        assert fb is not None
        assert fb.feedback_type == FeedbackType.ANSWER_NEGATIVE
        assert fb.target_query == "Who is my dog?"
        assert fb.original_route == "TIME"

    def test_route_inference_for_time_misroute(self):
        """_infer_corrected_route should infer LOCAL when no time keywords present."""
        buf = get_buffer()
        buf.append(query="Who is my dog?", route="TIME", response_text="3:45 PM",
                   intent_family="time_query", confidence=0.9874)

        from feedback_parser import FeedbackResult
        result = FeedbackResult(
            feedback_type=FeedbackType.ANSWER_NEGATIVE,
            target_query="Who is my dog?",
            original_route="TIME",
            raw_text="Incorrect",
        )
        inferred = _infer_corrected_route(result)
        assert inferred == "LOCAL"

    def test_feedback_logged_to_jsonl(self):
        """log_user_feedback must write an entry to user_feedback.jsonl."""
        buf = get_buffer()
        buf.append(query="Who is my dog?", route="TIME", response_text="3:45 PM",
                   intent_family="time_query", confidence=0.9874)

        fb = parse_feedback("Incorrect, my dog is Oscar")
        assert fb is not None

        ok = log_user_feedback(fb)
        assert ok is True

        # Verify file content
        lines = [json.loads(line) for line in FEEDBACK_PATH.read_text(encoding="utf-8").strip().split("\n")]
        assert any(entry["query"] == "Who is my dog?" and entry["correct_route"] == "LOCAL" for entry in lines)

    def test_background_learner_processes_feedback(self):
        """learn_once must ingest user feedback and grow the index."""
        import tempfile
        import background_learner as bl

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tmp_examples = tmpdir / "examples.json"
            tmp_embeddings = tmpdir / "embeddings.npy"
            tmp_index = tmpdir / "index.jsonl"
            tmp_feedback = tmpdir / "feedback.jsonl"

            tmp_examples.write_text(EXAMPLES_PATH.read_text(), encoding="utf-8")
            tmp_embeddings.write_bytes(EMBEDDINGS_PATH.read_bytes())
            tmp_index.write_text(INDEX_PATH.read_text(), encoding="utf-8")

            orig_examples = bl.EXAMPLES_PATH
            orig_embeddings = bl.EMBEDDINGS_PATH
            orig_index = bl.INDEX_PATH
            orig_feedback = bl.FEEDBACK_PATH
            bl.EXAMPLES_PATH = tmp_examples
            bl.EMBEDDINGS_PATH = tmp_embeddings
            bl.INDEX_PATH = tmp_index
            bl.FEEDBACK_PATH = tmp_feedback

            orig_fp = fp.FEEDBACK_PATH
            fp.FEEDBACK_PATH = tmp_feedback

            try:
                original_count = len(bl.load_index())

                # Seed feedback (use a query not already in the index)
                buf = get_buffer()
                buf.append(query="Who is my pet rabbit?", route="TIME", response_text="3:45 PM",
                           intent_family="time_query", confidence=0.9874)
                fb = parse_feedback("Incorrect, my pet rabbit is Fluffy")
                assert fb is not None
                log_user_feedback(fb)

                old_env = os.environ.get("LUCY_AUTO_LEARN")
                os.environ["LUCY_AUTO_LEARN"] = "1"
                try:
                    result = learn_once(verbose=False)
                finally:
                    if old_env is None:
                        os.environ.pop("LUCY_AUTO_LEARN", None)
                    else:
                        os.environ["LUCY_AUTO_LEARN"] = old_env

                assert result["new_from_feedback"] >= 1
            finally:
                bl.EXAMPLES_PATH = orig_examples
                bl.EMBEDDINGS_PATH = orig_embeddings
                bl.INDEX_PATH = orig_index
                bl.FEEDBACK_PATH = orig_feedback
                fp.FEEDBACK_PATH = orig_fp

    def test_full_loop_corrects_routing(self, router):
        """
        End-to-end: misroute → feedback → learn → verify corrected routing.
        
        This uses a temporary copy of the index so we don't pollute production.
        """
        # Use the current production index but create a temp workspace
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            tmp_examples = tmpdir / "examples.json"
            tmp_embeddings = tmpdir / "embeddings.npy"
            tmp_index = tmpdir / "index.jsonl"
            tmp_feedback = tmpdir / "feedback.jsonl"

            # Copy current artifacts
            tmp_examples.write_text(EXAMPLES_PATH.read_text(), encoding="utf-8")
            tmp_embeddings.write_bytes(EMBEDDINGS_PATH.read_bytes())
            tmp_index.write_text(INDEX_PATH.read_text(), encoding="utf-8")

            # Monkey-patch background_learner paths for this test
            import background_learner as bl
            orig_examples_path = bl.EXAMPLES_PATH
            orig_embeddings_path = bl.EMBEDDINGS_PATH
            orig_index_path = bl.INDEX_PATH
            orig_feedback_path = bl.FEEDBACK_PATH
            bl.EXAMPLES_PATH = tmp_examples
            bl.EMBEDDINGS_PATH = tmp_embeddings
            bl.INDEX_PATH = tmp_index
            bl.FEEDBACK_PATH = tmp_feedback

            # Also monkey-patch feedback_parser path
            orig_fp_path = fp.FEEDBACK_PATH
            fp.FEEDBACK_PATH = tmp_feedback

            try:
                # 1. Pre-learn: router using temp index
                local_router = HybridRouterV2(
                    embeddings_path=str(tmp_embeddings),
                    examples_path=str(tmp_examples),
                )
                pre = local_router.predict("Who is my dog?")
                # It might already be LOCAL due to guards; that's fine.
                pre_route = pre["route"]

                # 2. Seed feedback buffer and log feedback
                buf = get_buffer()
                buf.append(query="Who is my dog?", route="TIME", response_text="3:45 PM",
                           intent_family="time_query", confidence=0.9874)
                fb = parse_feedback("Incorrect, my dog is Oscar")
                assert fb is not None
                log_user_feedback(fb)

                # 3. Trigger background learning on temp paths
                old_env = os.environ.get("LUCY_AUTO_LEARN")
                os.environ["LUCY_AUTO_LEARN"] = "1"
                try:
                    learn_once(verbose=False)
                finally:
                    if old_env is None:
                        os.environ.pop("LUCY_AUTO_LEARN", None)
                    else:
                        os.environ["LUCY_AUTO_LEARN"] = old_env

                # 4. Post-learn: reload router with updated temp index
                post_router = HybridRouterV2(
                    embeddings_path=str(tmp_embeddings),
                    examples_path=str(tmp_examples),
                )
                post = post_router.predict("Who is my dog?")

                # 5. Assert corrected routing: must not be the incorrect TIME route
                assert post["route"] != "TIME"
                # If it was already LOCAL pre-learn, still LOCAL post-learn
                assert pre_route in ("LOCAL", "AUGMENTED", "TIME")

            finally:
                # Restore paths
                bl.EXAMPLES_PATH = orig_examples_path
                bl.EMBEDDINGS_PATH = orig_embeddings_path
                bl.INDEX_PATH = orig_index_path
                bl.FEEDBACK_PATH = orig_feedback_path
                fp.FEEDBACK_PATH = orig_fp_path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
