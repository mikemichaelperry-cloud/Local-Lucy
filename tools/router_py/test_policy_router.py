#!/usr/bin/env python3
"""Unit tests for the deterministic policy-router gates.

These tests do not load the embedding model; they exercise each policy gate
in isolation using a bare ``ClassificationResult``.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import pytest

from router_py.policy_router import PolicyRouter
from router_py.request_types import ClassificationResult


def _clf(evidence_reason: str = "", evidence_mode: str = "") -> ClassificationResult:
    """Build a minimal ClassificationResult for gate testing."""
    return ClassificationResult(
        intent="unknown",
        intent_family="local_answer",
        evidence_reason=evidence_reason,
        evidence_mode=evidence_mode,
    )


@pytest.fixture
def router() -> PolicyRouter:
    return PolicyRouter()


class TestPersonalFamilyGate:
    def test_my_daughter_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply("How old is my daughter?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:personal_family"

    def test_my_dog_with_vet_symptoms_is_evidence(self, router: PolicyRouter) -> None:
        decision = router.apply("My dog is limping", _clf(evidence_reason="veterinary_context"))
        # Personal-family gate must defer to medical/vet gate.
        assert decision is not None
        assert decision.route == "EVIDENCE"


class TestMedicalVetGate:
    def test_medication_side_effects_is_evidence(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "What are the side effects of metformin?",
            _clf(evidence_reason="medical_context", evidence_mode="required"),
        )
        assert decision is not None
        assert decision.route == "EVIDENCE"
        assert decision.provider == "trusted"

    def test_veterinary_query_is_evidence(self, router: PolicyRouter) -> None:
        decision = router.apply("My cat is vomiting", _clf(evidence_reason="veterinary_context"))
        assert decision is not None
        assert decision.route == "EVIDENCE"


class TestRecreationalPetGate:
    def test_english_dog_walk_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply("Do you think I should take my dog for a walk?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code in {"policy:recreational_pet", "policy:personal_family"}


class TestFinanceGate:
    def test_stock_price_is_finance(self, router: PolicyRouter) -> None:
        decision = router.apply("Current stock price of Apple", _clf())
        assert decision is not None
        assert decision.route == "FINANCE"
        assert decision.reason_code == "policy:finance_ephemeral"


class TestTimeWeatherNewsGates:
    def test_time_query(self, router: PolicyRouter) -> None:
        decision = router.apply("What time is it in Tokyo?", _clf())
        assert decision is not None
        assert decision.route == "TIME"

    def test_weather_query(self, router: PolicyRouter) -> None:
        decision = router.apply("Weather forecast for London", _clf())
        assert decision is not None
        assert decision.route == "WEATHER"

    def test_news_query(self, router: PolicyRouter) -> None:
        decision = router.apply("Latest world news headlines", _clf())
        assert decision is not None
        assert decision.route == "NEWS"


class TestEvidenceRequestGate:
    def test_verify_this(self, router: PolicyRouter) -> None:
        decision = router.apply("Verify this claim for me", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.requires_evidence is True
        assert decision.reason_code == "policy:evidence_request"

    def test_cite_sources(self, router: PolicyRouter) -> None:
        decision = router.apply("Cite your sources", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"


class TestConflictAnalysisGate:
    def test_will_russia_win(self, router: PolicyRouter) -> None:
        decision = router.apply("Will Russia win in Ukraine?", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:conflict_analysis"


class TestPublicFigureAgeGate:
    def test_bill_clinton_age(self, router: PolicyRouter) -> None:
        decision = router.apply("How old is Bill Clinton?", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:public_figure_age"


class TestCurrentInformationGate:
    def test_current_president(self, router: PolicyRouter) -> None:
        decision = router.apply("Who is the current president of the United States?", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:current_information"

    def test_latest_iphone(self, router: PolicyRouter) -> None:
        decision = router.apply("Latest iPhone release date", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:current_information"

    def test_historical_query_not_current(self, router: PolicyRouter) -> None:
        decision = router.apply("Who was president in 1995?", _clf())
        # No gate should fire; embedding router would decide.
        assert decision is None


class TestRecipeGate:
    def test_recipe_request(self, router: PolicyRouter) -> None:
        decision = router.apply("Best recipe for chocolate cake", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:recipe_request"


class TestTravelTourismGate:
    def test_japan_travel(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "What places would you suggest we visit in Japan in december?", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:travel_tourism"

    def test_spain_tourist_attractions(self, router: PolicyRouter) -> None:
        decision = router.apply("What are the main tourist attractions in Spain?", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:travel_tourism"

    def test_travel_guide_not_medical(self, router: PolicyRouter) -> None:
        # "pain" is a medical keyword, but "Spain" must not trigger the medical gate.
        decision = router.apply("travel guide for Spain", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:travel_tourism"


class TestNegativeCases:
    def test_stable_fact_routes_local(self, router: PolicyRouter) -> None:
        # Stable scientific concepts are handled well by the local model.
        decision = router.apply("What is the theory of relativity?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:stable_knowledge"

    def test_diy_no_gate(self, router: PolicyRouter) -> None:
        decision = router.apply("How do I change a car tire?", _clf())
        assert decision is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
