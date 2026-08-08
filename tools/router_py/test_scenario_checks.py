from types import SimpleNamespace

from router_py.scenario_checks import evaluate_response


def _outcome(route="LOCAL", text=""):
    return SimpleNamespace(route=route, response_text=text)


def test_required_concepts_all_of():
    sc = {"expected_route": "LOCAL", "required_answer_concepts": ["Local Lucy", "assistant"]}
    assert evaluate_response(sc, _outcome(text="I am Local Lucy, your assistant")) == (True, [])
    passed, notes = evaluate_response(sc, _outcome(text="I am your assistant"))
    assert not passed and notes == ["missing required concept: Local Lucy"]


def test_required_concepts_any_of():
    sc = {"required_answer_concepts_any": ["because", "since", "therefore"]}
    assert evaluate_response(sc, _outcome(text="Sky is blue since..."))[0] is True
    passed, notes = evaluate_response(sc, _outcome(text="Sky is blue."))
    assert not passed and "any of" in notes[0]


def test_expected_route_accepts_list():
    sc = {"expected_route": ["AUGMENTED", "LOCAL"]}
    assert evaluate_response(sc, _outcome(route="LOCAL", text="x"))[0] is True
    assert evaluate_response(sc, _outcome(route="WEATHER", text="x"))[0] is False


def test_forbidden_claims_and_haiku():
    sc = {"forbidden_answer_claims": ["OpenAI"]}
    assert evaluate_response(sc, _outcome(text="made by OpenAI"))[0] is False
    haiku = {"required_structure": "haiku"}
    assert evaluate_response(haiku, _outcome(text="one\ntwo\nthree"))[0] is True
    assert evaluate_response(haiku, _outcome(text="one\ntwo"))[0] is False
