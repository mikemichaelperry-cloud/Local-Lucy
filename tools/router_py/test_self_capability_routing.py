"""Regression tests for subject-aware self-capability routing.

These tests ensure that questions about Lucy itself — its identity, version,
capabilities, providers, and configuration — route LOCAL with SELF_KNOWLEDGE
injected rather than being sent to external providers.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def isolated_namespace(monkeypatch, tmp_path):
    """Use a temporary namespace root so tests do not pollute global state."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    yield tmp_path


class TestSelfCapabilityQueries:
    """Capability-overview questions must stay LOCAL."""

    @pytest.mark.parametrize(
        "query",
        [
            "What can you do?",
            "What can Local Lucy do?",
            "What can lucy do?",
            "What do you do?",
            "What are you able to do?",
            "What are your capabilities?",
            "What can you help me with?",
        ],
    )
    def test_capability_overview_routes_local(self, query, isolated_namespace):
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            query,
            policy="fallback_only",
            timeout=30,
            surface="cli",
            context={"request_id": f"test_cap_{hash(query) & 0xFFFFFFFF}"},
        )
        assert outcome.route == "LOCAL", f"{query!r} routed {outcome.route}"
        assert outcome.status == "completed"


class TestSelfWebSearchCapabilityQueries:
    """Questions about web-search capability must stay LOCAL."""

    @pytest.mark.parametrize(
        "query",
        [
            "Can you search the web?",
            "Can you browse the internet?",
            "Do you search the web?",
            "Are you able to search online?",
        ],
    )
    def test_web_search_capability_routes_local(self, query, isolated_namespace):
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            query,
            policy="fallback_only",
            timeout=30,
            surface="cli",
            context={"request_id": f"test_webcap_{hash(query) & 0xFFFFFFFF}"},
        )
        assert outcome.route == "LOCAL", f"{query!r} routed {outcome.route}"
        assert outcome.status == "completed"


class TestSelfIdentityQueries:
    """Identity/version questions already have guards; ensure they still hold."""

    @pytest.mark.parametrize(
        "query",
        [
            "Who are you?",
            "What model are you?",
            "What version are you?",
            "What is your name?",
        ],
    )
    def test_identity_queries_routes_local(self, query, isolated_namespace):
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            query,
            policy="fallback_only",
            timeout=30,
            surface="cli",
            context={"request_id": f"test_id_{hash(query) & 0xFFFFFFFF}"},
        )
        assert outcome.route == "LOCAL", f"{query!r} routed {outcome.route}"
        assert outcome.status == "completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
