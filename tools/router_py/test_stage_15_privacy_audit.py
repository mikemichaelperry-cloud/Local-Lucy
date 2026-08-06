#!/usr/bin/env python3
"""STAGE_15 — File, tool, privacy and audit controls.

Static tests verifying that untrusted web sources do not leak into production
memory and that sensitive query text is redacted from log-safe source strings.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from router_py.privacy import redact_untrusted_log_source
from router_py.main import _persist_memory_turn


class TestUntrustedSourcePrivacy:
    """Untrusted web sources must not leak into memory or logs verbatim."""

    def test_memory_turn_does_not_store_untrusted_source(self, monkeypatch, tmp_path):
        """S15-UW-001: untrusted URL/title are not written to chat memory."""
        monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))

        sensitive_question = "Why do I have a rash on my left arm?"
        response_with_untrusted_suggestion = (
            "Common causes include contact dermatitis. "
            "Web sources found (untrusted): SomeHealthBlog — https://example.com/why-do-i-have-a-rash"
        )

        _persist_memory_turn(
            sensitive_question,
            response_with_untrusted_suggestion,
            session_id="test-session",
        )

        mem_file = tmp_path / "state" / "chat_session_memory.txt"
        assert mem_file.exists()
        contents = mem_file.read_text(encoding="utf-8")
        assert sensitive_question in contents
        # The response text is stored, but the untrusted source URL must not be.
        assert "https://example.com/why-do-i-have-a-rash" not in contents

    def test_redact_untrusted_source_strips_query_terms_from_title(self):
        """S15-UW-002: title is redacted when it contains query terms."""
        title, url = redact_untrusted_log_source(
            title="Why do I have a rash on my left arm?",
            url="https://example.com/why-do-i-have-a-rash",
            query="Why do I have a rash on my left arm?",
        )
        assert title == "[untrusted source title redacted]"
        assert url == "example.com"

    def test_redact_untrusted_source_allows_benign_title(self):
        """S15-UW-002: titles without query terms are preserved."""
        title, url = redact_untrusted_log_source(
            title="Mayo Clinic",
            url="https://www.mayoclinic.org/diseases-conditions/rash",
            query="Why do I have a rash on my left arm?",
        )
        assert title == "Mayo Clinic"
        assert url == "mayoclinic.org"

    def test_redact_untrusted_source_returns_domain_only(self):
        """URL is reduced to its domain regardless of title content."""
        title, url = redact_untrusted_log_source(
            title="Some article",
            url="https://sub.example.com/path?secret=123",
            query="capital of France",
        )
        assert url == "sub.example.com"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
