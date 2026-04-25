#!/usr/bin/env python3
import re
from typing import Optional


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def match_local_response_id(question: str, intent: str = "") -> Optional[str]:
    qn = _norm_text(question)
    intent_upper = (intent or "").strip().upper()

    if re.search(
        r"(^|[^a-z0-9_])(who are you|what are you|what is your name|what's your name|whats your name|do you know who you are)([^a-z0-9_]|$)",
        qn,
    ):
        return "identity_lucy"
    if re.search(r"(^|[^a-z0-9_])(who am i|who i am|do you know who i am|who is (mike|michael))([^a-z0-9_]|$)", qn):
        return "identity_michael"
    if re.search(
        r"(^|[^a-z0-9_])((who is|tell me about)\s+(racheli|rachele|rachel|rakheli|rakhali|rakhili|rakhiri|rahali|rachaeli)|(and|and what about|what about)\s+(racheli|rachele|rachel|rakheli|rakhali|rakhili|rakhiri|rahali|rachaeli))([^a-z0-9_]|$)",
        qn,
    ):
        return "identity_racheli"
    if re.search(
        r"(^|[^a-z0-9_])(what is our relationship|what's our relationship|whats our relationship|who are we to each other|how do we work together)([^a-z0-9_]|$)",
        qn,
    ):
        return "identity_relationship"
    if re.search(
        r"(^|[^a-z0-9_])((who is|tell me about)\s+oscar|(and|and what about|what about)\s+oscar)([^a-z0-9_]|$)",
        qn,
    ):
        return "identity_oscar"
    if re.search(r"^are you familiar with\s+chatgpt[\s.!?]*$", qn):
        return "familiarity_chatgpt"
    if re.search(r"^(what is|what's|whats)\s+chatgpt[\s.!?]*$", qn):
        return "definition_chatgpt"
    if re.search(r"^(what is|what's|whats)\s+python[\s.!?]*$", qn):
        return "definition_python"
    if re.search(r"^(what is|what's|whats)\s+linux[\s.!?]*$", qn):
        return "definition_linux"
    if re.search(r"^(what is|what's|whats)\s+git[\s.!?]*$", qn):
        return "definition_git"
    if re.search(r"^(how do i feel|what am i feeling|how am i feeling|how am i doing emotionally|what is my emotional state)[\s.!?]*$", qn):
        return "emotion_state_unknown"
    if re.search(r"^(so\s+)?why did you ask .*question[\s.!?]*$", qn):
        return "context_loss_explanation"
    if re.search(r"^(explain|what is|what's|whats)\s+ohm'?s?\s+law[\s.!?]*$", qn):
        return "technical_ohms_law"
    if re.search(r"\b(bias|biased|unbiased|neutral|objective|balanced|fair|trustworthy|credible|reliable|factual|propaganda|slant|partisan)\b", qn):
        if re.search(r"\bbbc\b", qn):
            return "media_reliability_bbc"
        if re.search(r"\breuters\b", qn):
            return "media_reliability_reuters"
        if re.search(r"\bfox news\b", qn):
            return "media_reliability_fox_news"
        if re.search(r"\bguardian\b", qn):
            return "media_reliability_guardian"
    if re.search(r"(^|[^a-z0-9_])2n3055([^a-z0-9_]|$)", qn):
        return "component_2n3055"
    if re.search(r"(^|[^a-z0-9_])bc547([^a-z0-9_]|$)", qn):
        return "component_bc547"
    if re.search(r"(^|[^a-z0-9_])lm317([^a-z0-9_]|$)", qn):
        return "component_lm317"
    if re.search(r"(^|[^a-z0-9_])(ne)?555([^a-z0-9_]|$)", qn):
        return "component_ne555"
    if re.search(r"\bic\s+3055\b", qn):
        return "ambiguity_ic3055"
    if (
        re.search(r"\b807s?\b", qn)
        and re.search(r"\b(power tube|vacuum tube|tube|valve)\b", qn)
        and not re.search(r"\b(amplifier|plate|screen|anode|cathode|grid|bias|class a|class ab1|voltage|current|load|impedance|operating point|quiescent)\b", qn)
    ):
        return "tube_807_identity"
    if re.search(r"\b807s?\b", qn) and re.search(r"\b(pair|two|2)\b", qn) and re.search(r"\b(push[ -]?pull|pp)\b", qn) and re.search(r"\b(class )?ab1\b", qn) and re.search(r"\b(power|output|watt|watts)\b", qn):
        if re.search(r"\b400( ?v| ?volt| ?volts)?\b", qn):
            return "tube_807_pp_ab1_output_400v"
        return "tube_807_pp_ab1_output"
    if qn == "what is the capital of france?":
        return "fact_capital_france"
    if qn == "racheli is here with me right now.":
        return "racheli_presence_ack"
    if re.search(r"^(hi|hello|hey|good (morning|afternoon|evening))(,? lucy)?[.!?]*$", qn):
        return "greeting_generic"
    if re.search(r"\bexplain recursion\b", qn) and re.search(r"\bone sentence\b", qn):
        return "recursion_one_sentence"
    if re.search(r"\b(facts|assumptions|external dependencies)\b", qn) and re.search(r"\bis water wet\b", qn):
        return "water_wet_structured"
    if re.search(r"(^|[^a-z0-9_])(dog|dogs|pet|puppy)([^a-z0-9_]|$)", qn) and re.search(r"(^|[^a-z0-9_])(rocket|rockets|attack|attacks|explosion|explosions|blast|blasts|bomb|bombing|siren|sirens|firework|fireworks|shelling|missile|missiles)([^a-z0-9_]|$)", qn):
        return "pet_stress_blasts"

    if intent_upper in {"IDENTITY_SELF", "IDENTITY_USER", "IDENTITY_RELATIONSHIP"}:
        mapping = {
            "IDENTITY_SELF": "identity_lucy",
            "IDENTITY_USER": "identity_michael",
            "IDENTITY_RELATIONSHIP": "identity_relationship",
        }
        return mapping[intent_upper]

    return None


def is_local_policy_query(question: str, intent: str = "") -> bool:
    return match_local_response_id(question, intent) is not None
