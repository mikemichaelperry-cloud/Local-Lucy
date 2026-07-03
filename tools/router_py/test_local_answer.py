#!/usr/bin/env python3
"""Tests for local_answer.py module."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from local_answer import (
    LocalAnswer,
    LocalAnswerConfig,
    _OllamaWarmupThread,
)


class TestLocalAnswerConfig(unittest.TestCase):
    """Test LocalAnswerConfig class."""

    def test_default_config(self):
        """Test default configuration."""
        config = LocalAnswerConfig()
        self.assertEqual(config.model, "local-lucy-llama31")
        self.assertEqual(config.temperature, 0.0)
        self.assertEqual(config.seed, 7)
        self.assertTrue(config.cache_enabled)

    def test_config_from_env(self):
        """Test configuration from environment variables."""
        with patch.dict(
            os.environ,
            {
                "LUCY_LOCAL_MODEL": "test-model",
                "LUCY_LOCAL_TEMPERATURE": "0.5",
                "LUCY_LOCAL_SEED": "42",
                "LUCY_LOCAL_REPEAT_CACHE": "false",
            },
        ):
            config = LocalAnswerConfig.from_env()
            self.assertEqual(config.model, "test-model")
            self.assertEqual(config.temperature, 0.5)
            self.assertEqual(config.seed, 42)
            self.assertFalse(config.cache_enabled)


class TestQueryClassification(unittest.TestCase):
    """Test query classification methods."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        """Clean up resources."""
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_normalize_query(self):
        """Test query normalization."""
        self.assertEqual(self.answer._normalize_query("  Hello   World  "), "hello world")
        self.assertEqual(self.answer._normalize_query("UPPER CASE"), "upper case")

    def test_is_memory_context_allowed(self):
        """Test memory context allowed detection."""
        self.assertFalse(self.answer._is_memory_context_allowed("Hmm"))
        self.assertFalse(self.answer._is_memory_context_allowed("ok"))
        self.assertFalse(self.answer._is_memory_context_allowed("thanks"))
        self.assertTrue(self.answer._is_memory_context_allowed("What is Python?"))
        self.assertTrue(self.answer._is_memory_context_allowed("Tell me about AI"))

    def test_context_reset_requested(self):
        """Test context reset detection."""
        self.assertTrue(self.answer._context_reset_requested("new question"))
        self.assertTrue(self.answer._context_reset_requested("different topic"))
        self.assertTrue(self.answer._context_reset_requested("reset context"))
        self.assertFalse(self.answer._context_reset_requested("continue"))

    def test_context_followup_requested(self):
        """Test context followup detection."""
        self.assertTrue(self.answer._context_followup_requested("and what about that?"))
        self.assertTrue(self.answer._context_followup_requested("tell me more about that"))
        self.assertTrue(self.answer._context_followup_requested("as you said earlier"))
        self.assertFalse(self.answer._context_followup_requested("new question"))

    def test_is_budget_brief(self):
        """Test brief budget detection."""
        self.assertTrue(self.answer._is_budget_brief("brief answer"))
        self.assertTrue(self.answer._is_budget_brief("one sentence summary"))
        self.assertFalse(self.answer._is_budget_brief("explain in detail"))

    def test_is_budget_detail(self):
        """Test detail budget detection."""
        self.assertTrue(self.answer._is_budget_detail("explain in detail"))
        self.assertTrue(self.answer._is_budget_detail("step by step guide"))
        self.assertFalse(self.answer._is_budget_detail("brief answer"))

    def test_memory_instruction_treats_memory_as_context_not_source(self):
        """Session memory must not be treated as the primary answer source."""
        prompt = self.answer._build_prompt(
            query="What are interesting towns in Tokyo in December?",
            session_memory=(
                "User: What are the main tourist attractions in Japan?\n"
                "Assistant: Tourism in China is a growing industry..."
            ),
            generation_profile="chat",
            budget_instruction="",
            conversation_mode_active=False,
            conversation_system_block=False,
            augmented_context="",
        )
        self.assertIn("context only", prompt)
        self.assertIn("ignore any unrelated prior turns", prompt)
        self.assertNotIn("Answer from the session memory facts above", prompt)


class TestSanitization(unittest.TestCase):
    """Test text sanitization methods."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        """Clean up resources."""
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_sanitize_model_output(self):
        """Test model output sanitization."""
        # Test User:/Assistant: removal
        text = "Hello\nUser: What about Python?\nMore text"
        result = self.answer._sanitize_model_output(text)
        self.assertNotIn("User:", result)

        # Test blank line collapse
        text = "Line 1\n\n\n\nLine 2"
        result = self.answer._sanitize_model_output(text)
        self.assertEqual(result.count("\n\n"), 1)

    def test_strip_identity_preamble(self):
        """Test identity preamble stripping."""
        text = "I am Local Lucy, your AI assistant. Here is the answer."
        result = self.answer._strip_identity_preamble(text)
        self.assertNotIn("I am Local Lucy", result)
        self.assertIn("Here is the answer", result)

    def test_strip_identity_preamble_preserves_when_asked(self):
        """Identity preamble is kept when user explicitly asks who we are."""
        text = "I am Local Lucy. I can help with many things."
        result = self.answer._strip_identity_preamble(text, "Who are you?")
        self.assertIn("I am Local Lucy", result)
        self.assertIn("I can help with many things", result)

    def test_sanitize_identity_memory_fragment(self):
        """Test identity memory fragment sanitization."""
        text = "Michael is an engineer. What would you like to know?"
        result = self.answer._sanitize_identity_memory_fragment(text)
        self.assertNotIn("What would you like to know", result)
        self.assertIn("Michael is an engineer", result)


class TestCache(unittest.TestCase):
    """Test caching functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = LocalAnswerConfig(
            cache_dir=Path(self.temp_dir), cache_enabled=True, cache_ttl_seconds=60
        )
        self.answer = LocalAnswer(self.config)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_key_consistency(self):
        """Test cache key generation is consistent."""
        key1 = self.answer._cache_key("test query", "variant1")
        key2 = self.answer._cache_key("test query", "variant1")
        key3 = self.answer._cache_key("different query", "variant1")

        self.assertEqual(key1, key2)
        self.assertNotEqual(key1, key3)

    def test_cache_store_and_load(self):
        """Test cache store and load."""
        query = "test query"
        variant = "test:variant"
        text = "cached response"

        # Store
        self.answer._cache_store(query, variant, text)

        # Load
        cached = self.answer._cache_load(query, variant)
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], text)

    def test_cache_ttl_expiration(self):
        """Test cache TTL expiration."""
        query = "test query"
        variant = "test:variant"
        text = "cached response"

        # Store
        self.answer._cache_store(query, variant, text)

        # Set TTL to 0 to force expiration
        self.answer.config.cache_ttl_seconds = 0

        # Load should return None (expired)
        cached = self.answer._cache_load(query, variant)
        self.assertIsNone(cached)

    def test_807_general_question(self):
        """Test general 807 question."""
        answer = self.answer._check_807_question("807 pair push-pull class AB1 power output")
        self.assertIsNotNone(answer)
        self.assertIn("25-35 W", answer)
        self.assertNotIn("400 V", answer)

    def test_non_807_question(self):
        """Test non-807 question."""
        answer = self.answer._check_807_question("what is Python")
        self.assertIsNone(answer)


class TestAugmentedMode(unittest.TestCase):
    """Test augmented mode functionality."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        """Clean up resources."""
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_augmented_behavior_contract_clarify(self):
        """Test clarify answer shape."""
        shape = self.answer._apply_augmented_behavior_contract("what is he doing now", "")
        self.assertEqual(shape, "clarify_question")

    def test_augmented_behavior_contract_currentness(self):
        """Test currentness cautious shape."""
        shape = self.answer._apply_augmented_behavior_contract(
            "what are the current projects", "Some Company Inc is working on AI"
        )
        self.assertEqual(shape, "currentness_cautious")

    def test_augmented_background_has_anchor(self):
        """Test background anchor detection."""
        # Has multi-word name
        self.assertTrue(self.answer._augmented_background_has_anchor("John Smith is working on AI"))
        # Has camelCase
        self.assertTrue(
            self.answer._augmented_background_has_anchor("SomeCompany is working on AI")
        )
        # No anchor
        self.assertFalse(
            self.answer._augmented_background_has_anchor("This is about general topics")
        )

    def test_build_clarification_question(self):
        """Test clarification question building."""
        q = self.answer._build_clarification_question("what is he doing now")
        self.assertIn("current status", q)

        q = self.answer._build_clarification_question("what about him")
        self.assertIn("Which person", q)


class TestPromptBuilding(unittest.TestCase):
    """Test prompt building."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        """Clean up resources."""
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_build_basic_prompt(self):
        """Test basic prompt building."""
        # Mock away persistent facts so the test is deterministic
        with patch("local_answer._get_relevant_persistent_facts", return_value=[]):
            prompt = self.answer._build_prompt(
                "what is Python", "", "chat", "- Be concise.", False, False
            )
        self.assertIn("what is Python", prompt)
        self.assertIn("Answer from your own knowledge", prompt)

    def test_build_prompt_with_memory(self):
        """Test prompt building with session memory."""
        with patch("local_answer._get_relevant_persistent_facts", return_value=[]):
            prompt = self.answer._build_prompt(
                "what about that",
                "Previously discussed Python.",
                "chat",
                "- Be concise.",
                False,
                False,
            )
        self.assertIn("memory", prompt.lower())
        self.assertIn("Previously discussed Python", prompt)

    def test_build_prompt_conversation_mode(self):
        """Test prompt building with conversation mode."""
        with patch("local_answer._get_relevant_persistent_facts", return_value=[]):
            prompt = self.answer._build_prompt(
                "what is Python", "", "chat", "- Be concise.", True, True
            )
        self.assertIn("CONVERSATION_MODE", prompt)
        self.assertIn("sharp", prompt)

    def test_build_prompt_injects_only_relevant_pet_fact(self):
        """Test only relevant persistent facts are injected for a pet query."""
        with patch(
            "local_answer._get_relevant_persistent_facts", return_value=["Rex is your dog."]
        ):
            prompt = self.answer._build_prompt(
                "What is my dog's name?", "", "chat", "- Be concise.", False, False
            )
        self.assertIn("Rex is your dog.", prompt)
        self.assertNotIn("Your daughter Anna lives in Haifa.", prompt)
        self.assertIn("Answer using the [PERSISTENT FACTS] block above.", prompt)

    def test_build_prompt_injects_only_relevant_family_fact(self):
        """Test family query gets family facts rather than unrelated ones."""
        with patch(
            "local_answer._get_relevant_persistent_facts",
            return_value=["Your daughter Anna lives in Haifa."],
        ):
            prompt = self.answer._build_prompt(
                "Where does my daughter live?", "", "chat", "- Be concise.", False, False
            )
        self.assertIn("Your daughter Anna lives in Haifa.", prompt)
        self.assertNotIn("Rex is your dog.", prompt)

    def test_build_prompt_skips_persistent_facts_when_retrieval_fails(self):
        """Test retrieval failure falls back to direct SQLite load for family queries."""
        with patch(
            "local_answer._get_relevant_persistent_facts", side_effect=RuntimeError("embed failed")
        ):
            prompt = self.answer._build_prompt(
                "What is my dog's name?", "", "chat", "- Be concise.", False, False
            )
        # Fallback loads family facts directly from SQLite when embeddings fail
        self.assertIn("[PERSISTENT FACTS", prompt)
        self.assertIn("Oscar is Mike's dog", prompt)

    def test_build_prompt_general_knowledge_skips_personal_facts(self):
        """General-knowledge queries must not be restricted by retrieved personal facts."""
        with patch(
            "local_answer._get_relevant_persistent_facts",
            return_value=["Mike is 66 years old."],
        ):
            prompt = self.answer._build_prompt(
                "How old is Bill Clinton?", "", "chat", "- Be concise.", False, False
            )
        # The retrieved personal fact should not appear, and the model should be
        # instructed to use its own knowledge so it can answer the general query.
        self.assertNotIn("Mike is 66 years old.", prompt)
        self.assertNotIn("[PERSISTENT FACTS", prompt)
        self.assertIn("Answer from your own knowledge", prompt)


class TestCompletionGuards(unittest.TestCase):
    """Test completion guard functionality."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        """Clean up resources."""
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_remove_dangling_conjunction(self):
        """Test removal of dangling conjunctions."""
        text, triggered, reason = self.answer._apply_augmented_completion_guard(
            "This is a test and."
        )
        self.assertEqual(text, "This is a test.")
        self.assertTrue(triggered)
        self.assertEqual(reason, "removed_dangling_conjunction")

        text, triggered, reason = self.answer._apply_augmented_completion_guard(
            "This is a test, or."
        )
        self.assertEqual(text, "This is a test.")

    def test_close_truncated(self):
        """Test closing truncated sentences."""
        text, triggered, reason = self.answer._apply_augmented_completion_guard(
            "This is incomplete"
        )
        self.assertTrue(text.endswith("."))
        self.assertTrue(triggered)
        self.assertEqual(reason, "closed_truncated_fragment")

    def test_trim_to_sentence(self):
        """Test trimming to last complete sentence."""
        text, triggered, reason = self.answer._apply_augmented_completion_guard(
            "First sentence here. Second sentence that is long enough to be kept. Extra incomplete"
        )
        self.assertIn("Second sentence", text)
        self.assertNotIn("Extra incomplete", text)
        self.assertTrue(triggered)
        self.assertEqual(reason, "trimmed_to_last_complete_sentence")


class TestWarmup(unittest.TestCase):
    """Test Ollama warmup thread and recurring warmup starter."""

    def tearDown(self):
        """Stop any leftover warmup threads."""
        if LocalAnswer._warmup_thread is not None:
            try:
                LocalAnswer._warmup_thread.stop()
                LocalAnswer._warmup_thread.join(timeout=1.0)
            except Exception:
                pass
            LocalAnswer._warmup_thread = None
        LocalAnswer._warmup_done = False

    def test_warmup_thread_ping_success(self):
        """Test _OllamaWarmupThread._ping sends the expected payload."""
        thread = _OllamaWarmupThread(
            interval_s=300,
            model="test-model",
            api_url="http://127.0.0.1:11434/api/generate",
            keep_alive="5m",
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"{}"
            mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
            mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
            thread._ping()

            mock_urlopen.assert_called_once()
            req = mock_urlopen.call_args[0][0]
            self.assertEqual(req.full_url, "http://127.0.0.1:11434/api/generate")
            self.assertEqual(req.method, "POST")
            body = json.loads(req.data)
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["prompt"], "")
            self.assertEqual(body["keep_alive"], "5m")
            self.assertEqual(body["options"]["num_predict"], 0)

    def test_warmup_thread_ping_failure_is_silent(self):
        """Test _OllamaWarmupThread._ping does not raise on failure."""
        thread = _OllamaWarmupThread(
            interval_s=300,
            model="test-model",
            api_url="http://127.0.0.1:11434/api/generate",
            keep_alive="5m",
        )
        with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
            # Should not raise
            thread._ping()

    def test_warmup_thread_respects_stop(self):
        """Test _OllamaWarmupThread stops promptly."""
        thread = _OllamaWarmupThread(
            interval_s=3600,  # Long interval so it won't ping during test
            model="test-model",
            api_url="http://127.0.0.1:11434/api/generate",
            keep_alive="5m",
        )
        thread.start()
        self.assertTrue(thread.is_alive())
        thread.stop()
        thread.join(timeout=2.0)
        self.assertFalse(thread.is_alive())

    def test_start_recurring_warmup_respects_disabled_env(self):
        """Test LUCY_WARMUP_ENABLED=0 prevents thread start."""
        with patch.dict(os.environ, {"LUCY_WARMUP_ENABLED": "0"}):
            LocalAnswer.start_recurring_warmup(config=LocalAnswerConfig(model="test-model"))
            self.assertIsNone(LocalAnswer._warmup_thread)

    def test_start_recurring_warmup_idempotent(self):
        """Test start_recurring_warmup only starts one thread."""
        with patch.dict(os.environ, {"LUCY_WARMUP_ENABLED": "1"}):
            cfg = LocalAnswerConfig(model="test-model")
            LocalAnswer.start_recurring_warmup(config=cfg)
            first_thread = LocalAnswer._warmup_thread
            self.assertIsNotNone(first_thread)
            self.assertTrue(first_thread.is_alive())

            # Second call should be a no-op
            LocalAnswer.start_recurring_warmup(config=cfg)
            self.assertIs(LocalAnswer._warmup_thread, first_thread)

    def test_start_recurring_warmup_zero_interval_is_noop(self):
        """Test interval <= 0 prevents thread start."""
        with patch.dict(
            os.environ,
            {
                "LUCY_WARMUP_ENABLED": "1",
                "LUCY_WARMUP_INTERVAL_S": "0",
            },
        ):
            LocalAnswer.start_recurring_warmup(config=LocalAnswerConfig(model="test-model"))
            self.assertIsNone(LocalAnswer._warmup_thread)

    def test_start_recurring_warmup_no_model_is_noop(self):
        """Test missing model name prevents thread start."""
        LocalAnswer.start_recurring_warmup(config=LocalAnswerConfig(model=""))
        self.assertIsNone(LocalAnswer._warmup_thread)


class TestIntegration(unittest.TestCase):
    """Integration tests with mocked Ollama API."""

    async def async_test_policy_query(self):
        """Test policy query returns without API call."""
        answer = LocalAnswer()

        with patch.object(answer, "_call_ollama") as mock_call:
            mock_call.side_effect = Exception("Should not be called")

            result = await answer.generate_answer(
                "what is Python", policy_response_id="definition_python"
            )

            self.assertFalse(mock_call.called)
            self.assertIn("programming language", result.text)

    async def async_test_cache_hit(self):
        """Test cache hit returns cached response."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = LocalAnswerConfig(cache_dir=Path(temp_dir), cache_enabled=True)
            answer = LocalAnswer(config)

            # Pre-populate cache
            q_norm = answer._normalize_query("test query for cache")
            answer._cache_store(q_norm, "chat:192:0.0:1.0", "cached response")

            with patch.object(answer, "_call_ollama") as mock_call:
                mock_call.side_effect = Exception("Should not be called")

                result = await answer.generate_answer("test query for cache")

                self.assertFalse(mock_call.called)
                self.assertTrue(result.from_cache)
                self.assertEqual(result.text, "cached response")

    def test_integration(self):
        """Run async integration tests."""
        asyncio.run(self.async_test_policy_query())
        asyncio.run(self.async_test_cache_hit())


class TestPersonalFamilyFactResolver(unittest.TestCase):
    """Tests for the deterministic personal/family/pet fact resolver."""

    def setUp(self):
        self.answer = LocalAnswer()

    def tearDown(self):
        if hasattr(self, "answer") and self.answer:
            import asyncio

            try:
                asyncio.run(self.answer.close())
            except Exception:
                pass

    def test_is_personal_family_query_detects_children(self):
        self.assertTrue(self.answer._is_personal_family_query("Who are my children?"))

    def test_is_personal_family_query_detects_grandchildren(self):
        self.assertTrue(self.answer._is_personal_family_query("Do I have grandchildren?"))

    def test_is_personal_family_query_detects_dog(self):
        self.assertTrue(self.answer._is_personal_family_query("What is my dog's name?"))

    def test_is_personal_family_query_rejects_medical(self):
        self.assertFalse(
            self.answer._is_personal_family_query("My dog is vomiting, what should I do?")
        )

    def test_is_personal_family_query_rejects_general(self):
        self.assertFalse(self.answer._is_personal_family_query("What is Python?"))

    def test_resolve_children_from_facts(self):
        with patch(
            "local_answer._load_family_facts_direct",
            return_value=[
                "Your biological children are Tom, Sahar, and Kim.",
            ],
        ):
            result = self.answer._resolve_personal_family_fact("Who are my children?")
        self.assertIn("Tom", result or "")
        self.assertIn("Sahar", result or "")

    def test_resolve_grandchildren_from_facts(self):
        with patch(
            "local_answer._load_family_facts_direct",
            return_value=[
                "Your grandchildren are Nibar and Arbel.",
            ],
        ):
            result = self.answer._resolve_personal_family_fact("Who are my grandchildren?")
        self.assertIn("Nibar", result or "")
        self.assertIn("Arbel", result or "")

    def test_resolve_dog_name_from_facts(self):
        with patch(
            "local_answer._load_family_facts_direct",
            return_value=[
                "Your dog's name is Oscar.",
            ],
        ):
            result = self.answer._resolve_personal_family_fact("What is my dog's name?")
        self.assertIn("Oscar", result or "")

    def test_resolve_partner_from_facts(self):
        with patch(
            "local_answer._load_family_facts_direct",
            return_value=[
                "Racheli is your life partner.",
            ],
        ):
            result = self.answer._resolve_personal_family_fact("Who is my partner?")
        self.assertIn("Racheli", result or "")

    def test_resolve_specific_person_from_facts(self):
        with patch(
            "local_answer._load_family_facts_direct",
            return_value=[
                "Racheli is your life partner.",
            ],
        ):
            result = self.answer._resolve_personal_family_fact("Who is Racheli?")
        self.assertIn("Racheli", result or "")

    def test_resolve_returns_none_for_unknown(self):
        with patch("local_answer._load_family_facts_direct", return_value=[]):
            result = self.answer._resolve_personal_family_fact("Who are my children?")
        self.assertIsNone(result)

    def test_resolve_returns_none_for_non_fact_query(self):
        result = self.answer._resolve_personal_family_fact("Tell me a story about my children")
        self.assertIsNone(result)


class TestCacheFactRevision(unittest.TestCase):
    """Tests that cache keys include fact revision for personal/family queries."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.config = LocalAnswerConfig(
            cache_dir=Path(self.temp_dir), cache_enabled=True, cache_ttl_seconds=3600
        )
        self.answer = LocalAnswer(self.config)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cache_key_changes_with_fact_revision(self):
        key_without = self.answer._cache_key("who are my children", "chat:192:0.0:1.0")
        key_with = self.answer._cache_key(
            "who are my children", "chat:192:0.0:1.0", fact_revision="3:5:2026-06-01"
        )
        self.assertNotEqual(key_without, key_with)

    def test_cache_store_and_load_with_revision(self):
        query = "who are my children"
        variant = "chat:192:0.0:1.0"
        text = "deterministic answer"
        rev1 = "3:5:2026-06-01"
        rev2 = "4:6:2026-06-02"

        # Store with rev1
        self.answer._cache_store(query, variant, text, fact_revision=rev1)
        cached = self.answer._cache_load(query, variant, fact_revision=rev1)
        self.assertIsNotNone(cached)
        self.assertEqual(cached[0], text)

        # Load with different rev2 should miss
        cached2 = self.answer._cache_load(query, variant, fact_revision=rev2)
        self.assertIsNone(cached2)


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestLocalAnswerConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestQueryClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestCache))
    # Note: TestIdentityResponses, TestPolicyResponses, TestSocialGreetingResponses,
    # TestGenerationProfiles, Test807Questions referenced here historically but are
    # not present in this file; they may exist in other test files.
    suite.addTests(loader.loadTestsFromTestCase(TestAugmentedMode))
    suite.addTests(loader.loadTestsFromTestCase(TestPromptBuilding))
    suite.addTests(loader.loadTestsFromTestCase(TestCompletionGuards))
    suite.addTests(loader.loadTestsFromTestCase(TestWarmup))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPersonalFamilyFactResolver))
    suite.addTests(loader.loadTestsFromTestCase(TestCacheFactRevision))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
