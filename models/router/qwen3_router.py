#!/usr/bin/env python3
"""Qwen3-based intelligent router using Ollama API.

Qwen3 outputs reasoning in 'thinking' field. We extract classification
from either content or thinking field.
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import requests

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "tools" / "router_py"))
from policy import requires_evidence_mode


SYSTEM_PROMPT = (
    "You are a query router for AI assistant Local Lucy. "
    "Classify the query into JSON with keys: intent_family, needs_web, evidence_mode, route. "
    "intent_family: local_answer|background_overview|technical_explanation|current_evidence|news_request|time_query|creative_writing|clarification. "
    "needs_web: true|false. evidence_mode: required|not_required. "
    "route: LOCAL|LOCAL_WITH_FALLBACK|AUGMENTED|NEWS|TIME|CLARIFY."
)


class Qwen3Router:
    """Router using qwen3 14B via Ollama chat API."""

    def __init__(self, api_url: str | None = None, model: str = "local-lucy"):
        self.api_url = api_url or "http://127.0.0.1:11434/api/chat"
        self.model = model

    def classify(self, query: str, timeout: int = 15) -> dict[str, Any]:
        """Classify a query using qwen3."""
        try:
            resp = requests.post(
                self.api_url,
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": f'Query: {query}\nJSON:'},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.1, "num_predict": 200},
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            msg = data.get("message", {})

            # Qwen3 puts reasoning in 'thinking' field, actual response in 'content'
            content = msg.get("content", "").strip()
            thinking = msg.get("thinking", "").strip()

            # Try to extract JSON from content first, then thinking
            result = self._extract_json(content) or self._extract_json(thinking)

            if result is None:
                raise ValueError(f"No JSON found. Content: {content!r}, Thinking: {thinking!r}")

            # Safety override with keyword-based evidence
            requires_evidence, evidence_reason = requires_evidence_mode(query)
            if requires_evidence and result.get("evidence_mode") != "required":
                result["evidence_mode"] = "required"
                result["evidence_reason"] = evidence_reason
                result["route"] = "AUGMENTED"

            result["confidence"] = 0.92
            result["source"] = "qwen3"
            return result

        except Exception as e:
            return self._fallback_classify(query, str(e))

    def _extract_json(self, text: str) -> dict[str, Any] | None:
        """Extract JSON object from text."""
        if not text:
            return None

        # Try direct JSON parse
        try:
            # Find first { and last }
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass

        # Try to find key=value patterns in thinking text
        result: dict[str, Any] = {}
        patterns = {
            "intent_family": r'intent_family["\']?\s*[:=]\s*["\']?([a-z_]+)',
            "needs_web": r'needs_web["\']?\s*[:=]\s*(true|false)',
            "evidence_mode": r'evidence_mode["\']?\s*[:=]\s*["\']?(required|not_required)',
            "route": r'route["\']?\s*[:=]\s*["\']?([A-Z_]+)',
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                val = match.group(1).lower()
                if key == "needs_web":
                    result[key] = val == "true"
                else:
                    result[key] = val

        return result if result else None

    def _fallback_classify(self, query: str, error: str) -> dict[str, Any]:
        """Keyword-based fallback when LLM is unavailable."""
        q = query.lower()
        requires_evidence, evidence_reason = requires_evidence_mode(query)

        if any(k in q for k in ["news", "headlines", "breaking"]):
            return {"intent_family": "news_request", "needs_web": True, "evidence_mode": "not_required", "route": "NEWS", "confidence": 0.7, "source": "fallback", "error": error}
        elif "time" in q or "current time" in q:
            return {"intent_family": "time_query", "needs_web": True, "evidence_mode": "not_required", "route": "TIME", "confidence": 0.7, "source": "fallback", "error": error}
        elif requires_evidence:
            return {"intent_family": "current_evidence", "needs_web": True, "evidence_mode": "required", "route": "AUGMENTED", "confidence": 0.7, "source": "fallback", "error": error}
        elif any(k in q for k in ["story", "poem", "write", "creative"]):
            return {"intent_family": "creative_writing", "needs_web": False, "evidence_mode": "not_required", "route": "LOCAL", "confidence": 0.7, "source": "fallback", "error": error}
        elif any(k in q for k in ["how to", "how do i", "install", "debug"]):
            return {"intent_family": "technical_explanation", "needs_web": False, "evidence_mode": "not_required", "route": "LOCAL", "confidence": 0.7, "source": "fallback", "error": error}
        else:
            return {"intent_family": "background_overview", "needs_web": True, "evidence_mode": "not_required", "route": "LOCAL_WITH_FALLBACK", "confidence": 0.6, "source": "fallback", "error": error}


def test_router():
    router = Qwen3Router()
    test_queries = [
        "What are the symptoms of flu?",
        "Who was Ada Lovelace?",
        "What time is it in Tokyo?",
        "Latest news on Israel",
        "Write a story about a robot",
        "What is 2+2?",
        "How do I install Python?",
        "Breaking news about earthquake",
        "Stock price of Apple",
        "Is it legal to ride a bike on the sidewalk?",
        "Explain quantum computing",
        "Tell me a joke",
        "What is the treatment for diabetes?",
        "Current bitcoin price",
        "Latest Supreme Court ruling",
    ]

    print("Qwen3 Router Test")
    print("=" * 90)
    for query in test_queries:
        try:
            result = router.classify(query)
            source = result.get('source', '?')
            print(f"[{source:8s}] {query:50s} -> {result['route']:15s} intent={result['intent_family']:20s} evidence={result['evidence_mode']}")
        except Exception as e:
            print(f"[ERROR]  {query:50s} -> {e}")


if __name__ == "__main__":
    test_router()
