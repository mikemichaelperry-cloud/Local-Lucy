"""Regression tests for request-scoped capability constraints and parity.

These tests enforce that explicit user restrictions ("do not use network access",
"do not use tools", etc.) become deterministic capability constraints before
route selection or evidence planning, and that fabricated URLs cannot be fetched.
"""

from __future__ import annotations

import pytest

from router_py.request_types import ClassificationResult, PipelineContext, RoutingDecision


class TestExtractRequestConstraints:
    """Request-scoped capability constraints are extracted from natural-language
    instructions before any model-dependent processing."""

    def test_reference_request_extracts_no_network_and_no_tools(self):
        from router_py.request_constraints import extract_request_constraints

        question = (
            "This is an internal consistency exercise. Use only the information "
            "already available to you. Do not use tools, network access, files, "
            "or memory-writing functions. Consider these statements..."
        )
        constraints = extract_request_constraints(question)
        assert constraints.network is False
        assert constraints.tools is False
        assert constraints.file_read is False
        assert constraints.file_write is False
        assert constraints.memory_write is False
        assert constraints.local_only is True

    @pytest.mark.parametrize(
        "phrase,expected",
        [
            ("do not use network access", {"network": False}),
            ("do not browse the web", {"network": False}),
            ("no internet", {"network": False}),
            ("do not use tools", {"tools": False}),
            ("do not access files", {"file_read": False}),
            ("do not write memory", {"memory_write": False}),
            ("do not store this", {"memory_write": False}),
            ("use only currently available information", {"local_only": True}),
            ("answer only from current local context", {"local_only": True}),
        ],
    )
    def test_individual_restriction_phrases(self, phrase, expected):
        from router_py.request_constraints import extract_request_constraints

        constraints = extract_request_constraints(phrase)
        for key, value in expected.items():
            assert getattr(constraints, key) is value, f"{key} for {phrase!r}"

    def test_no_restriction_defaults_to_none(self):
        from router_py.request_constraints import extract_request_constraints

        constraints = extract_request_constraints("What is the capital of France?")
        assert constraints.network is None
        assert constraints.tools is None
        assert constraints.local_only is None


class TestRequestConstraintsEnforcement:
    """A request-scoped network=False constraint must block external routes
    regardless of what the classifier or model would otherwise choose."""

    def test_network_false_blocks_evidence_route(self):
        from router_py.request_constraints import RequestConstraints
        from router_py.execution_engine import ExecutionEngine

        constraints = RequestConstraints(network=False)
        engine = ExecutionEngine()
        # A medical query would normally route EVIDENCE; with network=False it
        # must be rejected before any fetch occurs.
        assert engine.is_capability_allowed("EVIDENCE", constraints) is False
        assert engine.is_capability_allowed("NEWS", constraints) is False
        assert engine.is_capability_allowed("AUGMENTED", constraints) is False
        assert engine.is_capability_allowed("LOCAL", constraints) is True

    def test_tools_false_blocks_tool_routes(self):
        from router_py.request_constraints import RequestConstraints
        from router_py.execution_engine import ExecutionEngine

        constraints = RequestConstraints(tools=False)
        engine = ExecutionEngine()
        assert engine.is_capability_allowed("TIME", constraints) is False
        assert engine.is_capability_allowed("WEATHER", constraints) is False
        assert engine.is_capability_allowed("FINANCE", constraints) is False
        assert engine.is_capability_allowed("LOCAL", constraints) is True

    def test_memory_write_false_blocks_memory_persistence(self):
        from router_py.request_constraints import RequestConstraints
        from router_py.main import _persist_memory_turn

        constraints = RequestConstraints(memory_write=False)
        # _persist_memory_turn must accept constraints and skip writes when
        # memory_write is explicitly denied.
        _persist_memory_turn("question", "response", constraints=constraints)
        # No exception and no write; assertion is that the signature accepts it.


class TestFetchURLValidation:
    """Search text and fetchable URLs are separate typed structures.
    Arbitrary prompt words must not become fetchable URLs."""

    def test_fabricated_medlineplus_path_rejected(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        result = validate_fetch_url(
            "https://medlineplus.gov/internal.html",
            URLProvenance.INVENTED_KEYWORD,
        )
        assert result is None

    def test_search_query_is_not_fetch_url(self):
        from router_py.url_provenance import SearchQuery, validate_fetch_url

        query = SearchQuery(text="internal consistency exercise SQLite memory")
        # A SearchQuery must never be accepted as a FetchURL.
        url = validate_fetch_url(query.text, None)
        assert url is None

    def test_user_supplied_url_accepted(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        result = validate_fetch_url(
            "https://medlineplus.gov/ency/article/000033.htm",
            URLProvenance.USER_SUPPLIED,
        )
        assert result is not None
        assert result.url == "https://medlineplus.gov/ency/article/000033.htm"

    def test_predefined_endpoint_accepted(self):
        from router_py.url_provenance import URLProvenance, validate_fetch_url

        result = validate_fetch_url(
            "https://medlineplus.gov/ency/article/000033.htm",
            URLProvenance.PREDEFINED_ENDPOINT,
        )
        assert result is not None


class TestPlannerOutputValidation:
    """Model-generated planner output must conform to a strict schema."""

    def test_isolated_words_rejected_as_search_plan(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        bad_plan = {
            "queries": ["internal", "consistency", "exercise", "information", "tools"],
            "urls": ["https://medlineplus.gov/internal.html"],
        }
        result = validator.validate(bad_plan)
        assert result.valid is False
        assert result.error_code == "invalid_query"

    def test_prose_rejected_where_structured_expected(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        bad_plan = "Please search the web for information about this topic."
        result = validator.validate(bad_plan)
        assert result.valid is False

    def test_valid_plan_accepted(self):
        from router_py.planner_validator import PlannerValidator

        validator = PlannerValidator()
        good_plan = {
            "queries": ["aspirin suspected heart attack recent evidence"],
            "urls": [],
        }
        result = validator.validate(good_plan)
        assert result.valid is True


class TestPipelineContextConstraints:
    """Constraints flow through PipelineContext and are enforced by the pipeline."""

    def test_pipeline_context_carries_constraints(self):
        from router_py.request_constraints import extract_request_constraints

        question = "Do not use network access; answer only from local context."
        constraints = extract_request_constraints(question)
        ctx = PipelineContext.from_env()
        ctx = ctx.with_constraints(constraints)
        assert ctx.request_constraints.network is False
        assert ctx.request_constraints.local_only is True

    def test_network_disabled_by_request_forces_local(self, isolated_namespace):
        from router_py.request_constraints import extract_request_constraints
        from router_py.request_pipeline import process

        question = (
            "Search current trusted sources for recent evidence about aspirin "
            "use during a suspected heart attack. Do not use network access."
        )
        result, classification, decision = process(
            question,
            policy="fallback_only",
            timeout=30,
            context={
                "request_id": "test_network_disabled",
                "request_constraints": extract_request_constraints(question),
            },
        )
        assert result.route == "LOCAL"
        assert result.policy_reason == "request_constraint_network_denied"
        assert result.outcome_code in ("answered", "operator_blocked", "capability_denied")


@pytest.fixture
def isolated_namespace(monkeypatch, tmp_path):
    """Use a temporary namespace root so tests do not pollute global state."""
    monkeypatch.setenv("LUCY_RUNTIME_NAMESPACE_ROOT", str(tmp_path))
    yield tmp_path


class TestMemoryControlRouting:
    """Explicit opt-out instructions about memory must route locally and avoid
    external fetches."""

    @pytest.mark.parametrize(
        "question",
        [
            "Do not store this message.",
            "Do not write this to memory.",
            "Forget this message.",
        ],
    )
    def test_negative_memory_instruction_routes_local(self, question, isolated_namespace):
        from router_py.main import execute_plan_python

        outcome = execute_plan_python(
            question,
            policy="fallback_only",
            timeout=30,
            surface="cli",
            context={"request_id": f"test_mem_ctrl_{hash(question) & 0xFFFFFFFF}"},
        )
        assert outcome.route == "LOCAL"
        assert outcome.status == "completed"


class TestTrustedFetchURLValidation:
    """The trusted-source direct-fetch fallback must not invent URLs from
    arbitrary prompt words."""

    def test_software_query_does_not_fetch_invented_medlineplus_urls(self, monkeypatch):
        import sys
        from pathlib import Path

        tools_dir = str(Path(__file__).resolve().parent.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)

        import unverified_context_trusted

        calls = []

        def fake_extract(url, *args, **kwargs):
            calls.append(url)
            return None

        monkeypatch.setattr(unverified_context_trusted, "extract_webpage", fake_extract)

        result = unverified_context_trusted._try_direct_fetch(
            "internal consistency exercise SQLite memory model weights",
            "medical",
        )
        assert result is None
        # The old behaviour would generate https://medlineplus.gov/internal.html etc.
        invented = [u for u in calls if "/internal.html" in u or "/consistency.html" in u]
        assert not invented, f"Invented URLs were fetched: {invented}"

    def test_medical_search_endpoint_may_still_be_used(self, monkeypatch):
        import sys
        from pathlib import Path

        tools_dir = str(Path(__file__).resolve().parent.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)

        import unverified_context_trusted

        calls = []

        def fake_extract(url, *args, **kwargs):
            calls.append(url)
            return None

        monkeypatch.setattr(unverified_context_trusted, "extract_webpage", fake_extract)

        unverified_context_trusted._try_direct_fetch(
            "aspirin heart attack",
            "medical",
        )
        # Search endpoints are predefined and allowed.
        assert any("medlineplus.gov/search" in u for u in calls)


class TestMedicalCognitiveSymptomRouting:
    """Cognitive and neurological symptoms must route to trusted medical evidence,
    not to general augmented lookup or local inference."""

    def test_cognitive_symptom_query_requires_medical_evidence(self):
        from router_py.policy import requires_evidence_mode

        question = (
            "I am experiencing worsening memory loss and confusion. "
            "What medical causes should be considered?"
        )
        requires_evidence, reason = requires_evidence_mode(question)
        assert requires_evidence is True
        assert reason == "medical_context"

    def test_cognitive_symptom_query_selects_evidence_route(self):
        from router_py.classify import classify_intent, select_route
        from router_py.request_pipeline import normalize_augmentation_policy

        question = (
            "I am experiencing worsening memory loss and confusion. "
            "What medical causes should be considered?"
        )
        classification = classify_intent(question, surface="cli")
        decision = select_route(
            classification,
            policy=normalize_augmentation_policy("fallback_only"),
            query=question,
            session_id="default",
        )
        assert decision.route == "EVIDENCE"
        assert decision.policy_reason == "evidence_required_medical_context"
