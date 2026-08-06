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


class TestExplicitAssistantInstructionGate:
    def test_self_model_correction_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "This is a self-model correction test. Do not modify memory or files. Answer only with four short sections.",
            _clf(),
        )
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:explicit_assistant_instruction"

    def test_internal_consistency_exercise_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "This is an internal consistency exercise. Use only the information already available to you. Do not use tools.",
            _clf(),
        )
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:explicit_assistant_instruction"

    def test_diagnostic_conversation_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "This is a diagnostic conversation only. Do not modify files, memory, code, settings, permissions, or external systems.",
            _clf(),
        )
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:explicit_assistant_instruction"

    def test_plain_factual_query_not_caught(self, router: PolicyRouter) -> None:
        # A normal question starting with "This is a" should not be forced LOCAL.
        decision = router.apply("This is a question about the moon.", _clf())
        assert decision is None


class TestScienceFactGate:
    def test_water_boiling_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply("At what temperature does water boil at sea level?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:science_fact"

    def test_speed_of_light_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply("What is the speed of light?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:science_fact"


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

    def test_news_with_restaurant_signal_yields_to_restaurant_dining(self, router: PolicyRouter) -> None:
        # "News about the best pizza place near me" is a restaurant lookup, not a
        # current-news request. The news guard must not override the restaurant signal.
        decision = router.apply("News about the best pizza place near me", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_travel_plan_with_weather_yields_to_travel_tourism(self, router: PolicyRouter) -> None:
        # Mixed travel-planning and weather should route as travel/tourism (AUGMENTED)
        # rather than being forced to WEATHER.
        decision = router.apply("Plan a trip to Paris and tell me the weather", _clf())
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:travel_tourism"

    def test_pure_weather_still_weather(self, router: PolicyRouter) -> None:
        decision = router.apply("Will it rain in Paris today?", _clf())
        assert decision is not None
        assert decision.route == "WEATHER"
        assert decision.reason_code == "policy:weather_query"


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

    def test_evidence_request_respects_local_only_restriction(self, router: PolicyRouter) -> None:
        # A trailing evidence imperative must not override an explicit local-only
        # or network-denial constraint.
        decision = router.apply("What is 2+2? Do not search the web.", _clf())
        assert decision is None or decision.route != "AUGMENTED"

    def test_evidence_request_respects_local_only_marker(self, router: PolicyRouter) -> None:
        decision = router.apply("Verify this claim using only currently available information.", _clf())
        assert decision is None or decision.route != "AUGMENTED"


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


class TestRestaurantDiningGate:
    def test_restaurant_near_me_routes_augmented(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "Hi Lucy, what is a good restaurant near me that is open on Saturdays?", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_restaurant_today_typo_routes_augmented(self, router: PolicyRouter) -> None:
        # "restraunt" typo and "today" must not be misrouted as TIME.
        decision = router.apply(
            "Search for restraunts in my area that are open today.", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_restaurant_near_location_routes_augmented(self, router: PolicyRouter) -> None:
        # "near kibbutz Magal" must not be misrouted as WEATHER.
        decision = router.apply(
            "I am looking for a good restaurant open today near kibbutz Magal.", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_restraurant_typo_near_location_routes_augmented(self, router: PolicyRouter) -> None:
        # "restraurant" (extra r) must still be caught and routed AUGMENTED, not WEATHER.
        decision = router.apply(
            "Can you please recommend a good restraurant near Hadera?", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_restraurant_typo_nere_qualifier_routes_augmented(self, router: PolicyRouter) -> None:
        # "restraurant" typo plus "nere" typo for "near" must not route to WEATHER.
        decision = router.apply(
            "Can you please recommend a good restraurant nere kibbutz Magal?", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_pet_food_not_restaurant(self, router: PolicyRouter) -> None:
        # Pet eating questions should not be caught by the restaurant gate.
        decision = router.apply("Can my dog eat chicken?", _clf())
        assert decision is None or decision.route != "AUGMENTED"


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


class TestConspiracyGate:
    def test_flat_earth_question_routes_local(self, router: PolicyRouter) -> None:
        decision = router.apply("Is the earth flat?", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.matched_rule == "local_reasoning"
        assert decision.policy_reason == "conspiracy_or_unsubstantiated_claim"

    def test_flat_earth_statement_routes_local(self, router: PolicyRouter) -> None:
        decision = router.apply("The earth is flat", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"


class TestGuardBoundaries:
    """Mixed-intent and edge cases for the recently modified guards."""

    def test_restaurant_plus_opening_time(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "What time does the Italian restaurant near me open on Saturdays?", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_restaurant_plus_weather(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "Is the patio restaurant open today and will it rain tonight?", _clf()
        )
        # Restaurant signal must dominate the weather terms.
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:restaurant_dining"

    def test_travel_planning_plus_weather(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "Plan a trip to Paris and tell me the weather", _clf()
        )
        assert decision is not None
        assert decision.route == "AUGMENTED"
        assert decision.reason_code == "policy:travel_tourism"

    def test_residence_statement_plus_weather(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "I live in Kibbutz Magal. What is the weather in Kibbutz Magal today?", _clf()
        )
        # This is a genuine weather question with an explicit place, not a standalone residence statement.
        assert decision is not None
        assert decision.route == "WEATHER"
        assert decision.reason_code == "policy:weather_query"

    def test_standalone_residence_statement_is_local(self, router: PolicyRouter) -> None:
        decision = router.apply("Actually I live in Kibbutz Magal in Israel.", _clf())
        assert decision is not None
        assert decision.route == "LOCAL"
        assert decision.reason_code == "policy:residence_statement"

    def test_arithmetic_with_evidence_imperative_stays_local(self, router: PolicyRouter) -> None:
        decision = router.apply("What is 2+2? Search the web.", _clf())
        assert decision is None or decision.route == "LOCAL"

    def test_medical_memory_recall_does_not_trigger_web_evidence(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "What did I say earlier about my blood pressure medication?", _clf()
        )
        # Explicit memory recall must stay LOCAL; evidence-request gate must not fire.
        assert decision is None or decision.route == "LOCAL"

    def test_local_only_current_information_request(self, router: PolicyRouter) -> None:
        decision = router.apply(
            "What is the latest version of Python? Use only currently available information.", _clf()
        )
        assert decision is None or decision.route == "LOCAL"


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
