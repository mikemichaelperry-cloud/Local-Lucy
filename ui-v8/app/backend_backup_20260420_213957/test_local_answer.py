#!/usr/bin/env python3
"""Tests for local_answer.py module."""

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from local_answer import (
    LocalAnswer,
    LocalAnswerConfig,
    AnswerResult,
    FIXED_POLICY_RESPONSES,
    WATER_WET_RESPONSE,
)


class TestLocalAnswerConfig(unittest.TestCase):
    """Test LocalAnswerConfig class."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = LocalAnswerConfig()
        self.assertEqual(config.model, "local-lucy")
        self.assertEqual(config.temperature, 0.0)
        self.assertEqual(config.seed, 7)
        self.assertTrue(config.cache_enabled)
    
    def test_config_from_env(self):
        """Test configuration from environment variables."""
        with patch.dict(os.environ, {
            "LUCY_LOCAL_MODEL": "test-model",
            "LUCY_LOCAL_TEMPERATURE": "0.5",
            "LUCY_LOCAL_SEED": "42",
            "LUCY_LOCAL_REPEAT_CACHE": "false",
        }):
            config = LocalAnswerConfig.from_env()
            self.assertEqual(config.model, "test-model")
            self.assertEqual(config.temperature, 0.5)
            self.assertEqual(config.seed, 42)
            self.assertFalse(config.cache_enabled)


class TestQueryClassification(unittest.TestCase):
    """Test query classification methods."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_normalize_query(self):
        """Test query normalization."""
        self.assertEqual(
            self.answer._normalize_query("  Hello   World  "),
            "hello world"
        )
        self.assertEqual(
            self.answer._normalize_query("UPPER CASE"),
            "upper case"
        )
    
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
    
    def test_is_identity_query(self):
        """Test identity query detection."""
        self.assertTrue(self.answer._is_identity_query("who are you"))
        self.assertTrue(self.answer._is_identity_query("what can you do"))
        self.assertTrue(self.answer._is_identity_query("do you have internet access"))
        self.assertFalse(self.answer._is_identity_query("what is Python"))
    
    def test_is_medical_high_risk(self):
        """Test medical query detection."""
        self.assertTrue(self.answer._is_medical_high_risk("what is the dosage of viagra"))
        self.assertTrue(self.answer._is_medical_high_risk("metformin side effects"))
        self.assertFalse(self.answer._is_medical_high_risk("what is Python"))
    
    def test_is_time_sensitive(self):
        """Test time-sensitive query detection."""
        self.assertTrue(self.answer._is_time_sensitive("latest news"))
        self.assertTrue(self.answer._is_time_sensitive("current price of bitcoin"))
        self.assertTrue(self.answer._is_time_sensitive("USD to EUR exchange rate"))
        self.assertFalse(self.answer._is_time_sensitive("what is Python"))
    
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


class TestSanitization(unittest.TestCase):
    """Test text sanitization methods."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
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
            cache_dir=Path(self.temp_dir),
            cache_enabled=True,
            cache_ttl_seconds=60
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


class TestIdentityResponses(unittest.TestCase):
    """Test identity response handling."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_who_are_you(self):
        """Test 'who are you' response."""
        response = self.answer._get_identity_response("who are you", "")
        self.assertIsNotNone(response)
        self.assertIn("Lucy", response)
    
    def test_who_is_michael(self):
        """Test 'who is michael' response."""
        response = self.answer._get_identity_response("who is Michael", "")
        self.assertIsNotNone(response)
        self.assertIn("Michael", response)
    
    def test_who_is_michael_with_memory(self):
        """Test 'who is michael' with session memory."""
        memory = "You are Michael: a software engineer"
        response = self.answer._get_identity_response("who is Michael", memory)
        self.assertIsNotNone(response)
        self.assertIn("software engineer", response)
    
    def test_who_is_racheli(self):
        """Test 'who is racheli' response."""
        response = self.answer._get_identity_response("who is Racheli", "")
        self.assertIsNotNone(response)
        self.assertIn("Racheli", response)
    
    def test_who_is_oscar(self):
        """Test 'who is oscar' response."""
        response = self.answer._get_identity_response("who is Oscar", "")
        self.assertIsNotNone(response)
        self.assertIn("dog", response)


class TestPolicyResponses(unittest.TestCase):
    """Test policy response handling."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_fixed_responses(self):
        """Test fixed policy responses."""
        for policy_id, expected_response in FIXED_POLICY_RESPONSES.items():
            response = self.answer._get_policy_response(policy_id)
            self.assertIsNotNone(response)
            self.assertEqual(response, expected_response)
    
    def test_water_wet_response(self):
        """Test water wet response."""
        response = self.answer._get_policy_response("water_wet_structured")
        self.assertEqual(response, WATER_WET_RESPONSE)
    
    def test_unknown_policy_id(self):
        """Test unknown policy ID returns None."""
        response = self.answer._get_policy_response("unknown_policy")
        self.assertIsNone(response)


class TestGenerationProfiles(unittest.TestCase):
    """Test generation profile selection."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_local_chat_profile(self):
        """Test LOCAL/CHAT profile."""
        name, num_predict, instruction = self.answer._set_generation_profile(
            "LOCAL", "CHAT", "what is Python"
        )
        self.assertEqual(name, "chat")
        self.assertEqual(num_predict, 192)  # Default num_predict_chat
    
    def test_brief_profile(self):
        """Test brief request profile."""
        name, num_predict, instruction = self.answer._set_generation_profile(
            "LOCAL", "CHAT", "brief answer please"
        )
        self.assertEqual(name, "brief")
        self.assertEqual(num_predict, 48)  # Default num_predict_brief
    
    def test_detail_profile(self):
        """Test detail request profile."""
        name, num_predict, instruction = self.answer._set_generation_profile(
            "LOCAL", "CHAT", "explain in detail"
        )
        self.assertEqual(name, "detail")
        self.assertEqual(num_predict, 384)  # Default num_predict_detail
    
    def test_augmented_profile(self):
        """Test AUGMENTED route profile."""
        name, num_predict, instruction = self.answer._set_generation_profile(
            "AUGMENTED", "CHAT", "what is Python"
        )
        self.assertEqual(name, "augmented")
        self.assertEqual(num_predict, 32)  # Default num_predict_augmented_default


class Test807Questions(unittest.TestCase):
    """Test 807 tube question handling."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_807_400v_question(self):
        """Test 807 400V question."""
        answer = self.answer._check_807_question(
            "807 pair push-pull class AB1 400V power output"
        )
        self.assertIsNotNone(answer)
        self.assertIn("25-35 W", answer)
        self.assertIn("400 V", answer)
    
    def test_807_general_question(self):
        """Test general 807 question."""
        answer = self.answer._check_807_question(
            "807 pair push-pull class AB1 power output"
        )
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
    
    def test_augmented_behavior_contract_clarify(self):
        """Test clarify answer shape."""
        shape = self.answer._apply_augmented_behavior_contract(
            "what is he doing now", ""
        )
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
        self.assertTrue(
            self.answer._augmented_background_has_anchor("John Smith is working on AI")
        )
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
    
    def test_build_basic_prompt(self):
        """Test basic prompt building."""
        prompt = self.answer._build_prompt(
            "what is Python",
            "",
            "chat",
            "- Be concise.",
            False,
            False
        )
        self.assertIn("Local Lucy", prompt)
        self.assertIn("OFFLINE", prompt)
        self.assertIn("what is Python", prompt)
    
    def test_build_prompt_with_memory(self):
        """Test prompt building with session memory."""
        prompt = self.answer._build_prompt(
            "what about that",
            "Previously discussed Python.",
            "chat",
            "- Be concise.",
            False,
            False
        )
        self.assertIn("Session memory", prompt)
        self.assertIn("Previously discussed Python", prompt)
    
    def test_build_prompt_conversation_mode(self):
        """Test prompt building with conversation mode."""
        prompt = self.answer._build_prompt(
            "what is Python",
            "",
            "chat",
            "- Be concise.",
            True,
            True
        )
        self.assertIn("CONVERSATION_MODE", prompt)
        self.assertIn("calibrated_sharp", prompt)


class TestCompletionGuards(unittest.TestCase):
    """Test completion guard functionality."""
    
    def setUp(self):
        self.answer = LocalAnswer()
    
    def test_remove_dangling_conjunction(self):
        """Test removal of dangling conjunctions."""
        text = self.answer._apply_augmented_completion_guard("This is a test and.")
        self.assertEqual(text, "This is a test.")
        
        text = self.answer._apply_augmented_completion_guard("This is a test, or.")
        self.assertEqual(text, "This is a test.")
    
    def test_close_truncated(self):
        """Test closing truncated sentences."""
        text = self.answer._apply_augmented_completion_guard("This is incomplete")
        self.assertTrue(text.endswith("."))
    
    def test_trim_to_sentence(self):
        """Test trimming to last complete sentence."""
        text = self.answer._apply_augmented_completion_guard(
            "First sentence here. Second sentence that is long enough to be kept. Extra incomplete"
        )
        self.assertIn("Second sentence", text)
        self.assertNotIn("Extra incomplete", text)


class TestIntegration(unittest.TestCase):
    """Integration tests with mocked Ollama API."""
    
    async def async_test_identity_query(self):
        """Test identity query returns without API call."""
        answer = LocalAnswer()
        
        with patch.object(answer, '_call_ollama') as mock_call:
            mock_call.side_effect = Exception("Should not be called")
            
            result = await answer.generate_answer("who are you")
            
            self.assertFalse(mock_call.called)
            self.assertIn("Lucy", result.text)
    
    async def async_test_policy_query(self):
        """Test policy query returns without API call."""
        answer = LocalAnswer()
        
        with patch.object(answer, '_call_ollama') as mock_call:
            mock_call.side_effect = Exception("Should not be called")
            
            result = await answer.generate_answer(
                "what is Python",
                policy_response_id="definition_python"
            )
            
            self.assertFalse(mock_call.called)
            self.assertIn("programming language", result.text)
    
    async def async_test_medical_refusal(self):
        """Test medical query is refused."""
        answer = LocalAnswer()
        
        with patch.object(answer, '_call_ollama') as mock_call:
            mock_call.side_effect = Exception("Should not be called")
            
            result = await answer.generate_answer("what is the dosage of viagra")
            
            self.assertFalse(mock_call.called)
            self.assertIn("evidence mode", result.text)
    
    async def async_test_time_sensitive_refusal(self):
        """Test time-sensitive query is refused."""
        answer = LocalAnswer()
        
        with patch.object(answer, '_call_ollama') as mock_call:
            mock_call.side_effect = Exception("Should not be called")
            
            result = await answer.generate_answer("latest news headlines")
            
            self.assertFalse(mock_call.called)
            self.assertIn("evidence mode", result.text)
    
    async def async_test_cache_hit(self):
        """Test cache hit returns cached response."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = LocalAnswerConfig(
                cache_dir=Path(temp_dir),
                cache_enabled=True
            )
            answer = LocalAnswer(config)
            
            # Pre-populate cache
            q_norm = answer._normalize_query("test query for cache")
            answer._cache_store(q_norm, "chat:192:0.0:1.0", "cached response")
            
            with patch.object(answer, '_call_ollama') as mock_call:
                mock_call.side_effect = Exception("Should not be called")
                
                result = await answer.generate_answer("test query for cache")
                
                self.assertFalse(mock_call.called)
                self.assertTrue(result.from_cache)
                self.assertEqual(result.text, "cached response")
    
    def test_integration(self):
        """Run async integration tests."""
        asyncio.run(self.async_test_identity_query())
        asyncio.run(self.async_test_policy_query())
        asyncio.run(self.async_test_medical_refusal())
        asyncio.run(self.async_test_time_sensitive_refusal())
        asyncio.run(self.async_test_cache_hit())


def run_tests():
    """Run all tests."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestLocalAnswerConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestQueryClassification))
    suite.addTests(loader.loadTestsFromTestCase(TestSanitization))
    suite.addTests(loader.loadTestsFromTestCase(TestCache))
    suite.addTests(loader.loadTestsFromTestCase(TestIdentityResponses))
    suite.addTests(loader.loadTestsFromTestCase(TestPolicyResponses))
    suite.addTests(loader.loadTestsFromTestCase(TestGenerationProfiles))
    suite.addTests(loader.loadTestsFromTestCase(Test807Questions))
    suite.addTests(loader.loadTestsFromTestCase(TestAugmentedMode))
    suite.addTests(loader.loadTestsFromTestCase(TestPromptBuilding))
    suite.addTests(loader.loadTestsFromTestCase(TestCompletionGuards))
    suite.addTests(loader.loadTestsFromTestCase(TestIntegration))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_tests())
