"""
Direct Python provider implementations for Local Lucy v8.

This module provides direct Python implementations of provider calls,
eliminating the need for subprocess calls to provider tools.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderResult:
    """Result from a provider call."""
    ok: bool
    provider: str
    text: str
    url: str = ""
    error: str = ""
    provider_class: str = ""


def _clean_text(text: str) -> str:
    """Clean and normalize response text."""
    return re.sub(r"\s+", " ", text).strip()


class OpenAIProvider:
    """Direct Python OpenAI provider."""
    
    DEFAULT_API_BASE = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-4o-mini"
    TIMEOUT = 30.0  # Longer timeout than subprocess for reliability
    
    SYSTEM_PROMPT = (
        "Provide a concise, high-level background summary for a user question. "
        "Do not claim verification, do not provide evidence citations, and keep under 120 words."
    )
    
    @classmethod
    def call(cls, question: str, **kwargs) -> ProviderResult:
        """
        Call OpenAI API directly.
        
        Args:
            question: User question to ask
            **kwargs: Override defaults (api_key, api_base, model, temperature)
            
        Returns:
            ProviderResult with response or error
        """
        # Check for mock mode (testing)
        mock_text = os.environ.get("LUCY_OPENAI_MOCK_TEXT", "").strip()
        mock_url = os.environ.get("LUCY_OPENAI_MOCK_URL", "").strip()
        if mock_text:
            return ProviderResult(
                ok=True,
                provider="openai",
                text=_clean_text(mock_text),
                url=mock_url,
                provider_class="openai_general"
            )
        
        # Get configuration
        api_key = kwargs.get("api_key") or os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="missing_openai_configuration"
            )
        
        api_base = kwargs.get("api_base") or os.environ.get(
            "OPENAI_BASE_URL", cls.DEFAULT_API_BASE
        ).strip().rstrip("/")
        model = kwargs.get("model") or os.environ.get("OPENAI_MODEL", cls.DEFAULT_MODEL).strip()
        temperature = kwargs.get("temperature", 0.2)
        
        if not api_base or not model:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="missing_openai_configuration"
            )
        
        # Build request
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": cls.SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": temperature,
        }
        
        request_body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{api_base}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        
        # Make request
        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="openai_http_error"
            )
        except urllib.error.URLError:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="openai_network_error"
            )
        except Exception:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="openai_request_failed"
            )
        
        # Parse response
        try:
            parsed = json.loads(raw)
        except Exception:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="openai_bad_payload"
            )
        
        text = ""
        if isinstance(parsed, dict):
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        text = str(msg.get("content", "")).strip()
        
        text = _clean_text(text)
        if not text:
            return ProviderResult(
                ok=False,
                provider="openai",
                text="",
                error="openai_no_text"
            )
        
        return ProviderResult(
            ok=True,
            provider="openai",
            text=text,
            url="",
            provider_class="openai_general"
        )


class KimiProvider:
    """Direct Python Kimi provider (Moonshot AI)."""
    
    DEFAULT_API_BASE = "https://api.moonshot.cn/v1"
    DEFAULT_MODEL = "moonshot-v1-8k"
    TIMEOUT = 30.0
    
    SYSTEM_PROMPT = (
        "Provide a concise, high-level background summary for a user question. "
        "Do not claim verification, do not provide evidence citations, and keep under 120 words."
    )
    
    @classmethod
    def call(cls, question: str, **kwargs) -> ProviderResult:
        """
        Call Kimi API directly.
        
        Args:
            question: User question to ask
            **kwargs: Override defaults (api_key, api_base, model, temperature)
            
        Returns:
            ProviderResult with response or error
        """
        # Check for mock mode (testing)
        mock_text = os.environ.get("LUCY_KIMI_MOCK_TEXT", "").strip()
        mock_url = os.environ.get("LUCY_KIMI_MOCK_URL", "").strip()
        if mock_text:
            return ProviderResult(
                ok=True,
                provider="kimi",
                text=_clean_text(mock_text),
                url=mock_url,
                provider_class="kimi_general"
            )
        
        # Get configuration
        api_key = kwargs.get("api_key") or os.environ.get("KIMI_API_KEY", "").strip()
        if not api_key:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="missing_kimi_configuration"
            )
        
        api_base = kwargs.get("api_base") or os.environ.get(
            "KIMI_API_BASE_URL", cls.DEFAULT_API_BASE
        ).strip().rstrip("/")
        model = kwargs.get("model") or os.environ.get("KIMI_MODEL", cls.DEFAULT_MODEL).strip()
        temperature = kwargs.get("temperature", 0.2)
        
        if not api_base or not model:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="missing_kimi_configuration"
            )
        
        # Build request
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": cls.SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            "temperature": temperature,
        }
        
        request_body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{api_base}/chat/completions",
            data=request_body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        
        # Make request
        try:
            with urllib.request.urlopen(request, timeout=cls.TIMEOUT) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="kimi_http_error"
            )
        except urllib.error.URLError:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="kimi_network_error"
            )
        except Exception:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="kimi_request_failed"
            )
        
        # Parse response
        try:
            parsed = json.loads(raw)
        except Exception:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="kimi_bad_payload"
            )
        
        text = ""
        if isinstance(parsed, dict):
            choices = parsed.get("choices")
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    msg = first.get("message")
                    if isinstance(msg, dict):
                        text = str(msg.get("content", "")).strip()
        
        text = _clean_text(text)
        if not text:
            return ProviderResult(
                ok=False,
                provider="kimi",
                text="",
                error="kimi_no_text"
            )
        
        return ProviderResult(
            ok=True,
            provider="kimi",
            text=text,
            url="",
            provider_class="kimi_general"
        )


class WikipediaProvider:
    """
    Direct Python Wikipedia provider.
    
    Uses evidence fetching directly rather than subprocess.
    """
    
    @classmethod
    def call(cls, question: str, evidence: dict[str, Any] | None = None) -> ProviderResult:
        """
        Format Wikipedia evidence as response.
        
        Args:
            question: Original user question
            evidence: Evidence dictionary from _fetch_evidence
            
        Returns:
            ProviderResult with formatted response
        """
        if not evidence:
            return ProviderResult(
                ok=True,
                provider="wikipedia",
                text="No Wikipedia information available for this query.",
                provider_class="wikipedia_general"
            )
        
        context_text = evidence.get("context", "")
        title = evidence.get("title", "")
        url = evidence.get("url", "")
        
        if not context_text:
            return ProviderResult(
                ok=True,
                provider="wikipedia",
                text="No information found on Wikipedia for this topic.",
                provider_class="wikipedia_general"
            )
        
        # Format response with attribution
        response_parts = [context_text]
        
        if title or url:
            response_parts.append("\n\n---")
            if title:
                response_parts.append(f"Source: Wikipedia - {title}")
            if url:
                response_parts.append(f"Read more: {url}")
        
        return ProviderResult(
            ok=True,
            provider="wikipedia",
            text="\n".join(response_parts),
            url=url,
            provider_class="wikipedia_general"
        )


def call_provider(provider: str, question: str, **kwargs) -> ProviderResult:
    """
    Call any provider by name.
    
    Args:
        provider: Provider name ("openai", "kimi", "wikipedia")
        question: User question
        **kwargs: Additional arguments for specific providers
        
    Returns:
        ProviderResult with response
    """
    providers = {
        "openai": OpenAIProvider,
        "kimi": KimiProvider,
        "wikipedia": WikipediaProvider,
    }
    
    provider_class = providers.get(provider)
    if not provider_class:
        return ProviderResult(
            ok=False,
            provider=provider,
            text="",
            error=f"unknown_provider: {provider}"
        )
    
    return provider_class.call(question, **kwargs)
