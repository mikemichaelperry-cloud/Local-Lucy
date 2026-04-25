#!/usr/bin/env python3
import os
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

from medical_query_heuristics import detect_human_medication_query, has_human_medication_topic_query


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _has_re(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def _file_mtime_ns(path: str) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return -1


def _latest_user_context(root: str) -> Tuple[str, str]:
    mem_file = (os.environ.get("LUCY_CHAT_MEMORY_FILE") or "").strip()
    mem_last = ""
    mem_mtime_ns = -1
    if mem_file:
        try:
            last = ""
            with open(mem_file, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("User: "):
                        last = line[len("User: ") :].strip()
            if last:
                mem_last = last
                mem_mtime_ns = _file_mtime_ns(mem_file)
        except OSError:
            pass

    last_route = Path(root) / "state" / "last_route.env"
    route_last = ""
    try:
        with open(last_route, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("QUERY="):
                    route_last = line.split("=", 1)[1].strip()
                    break
    except OSError:
        pass
    route_mtime_ns = _file_mtime_ns(str(last_route))

    if route_last and route_mtime_ns > mem_mtime_ns:
        return route_last, "route"
    if mem_last:
        return mem_last, "memory"
    if route_last:
        return route_last, "route"
    return "", ""


def _latest_user_context_query(root: str) -> str:
    return _latest_user_context(root)[0]


def _is_short_followup_prompt(question: str) -> bool:
    qn = _norm_text(question)
    if len(qn.split()) > 7:
        return bool(
            re.search(
                r"^(what are (?:the )?(?:known )?(interactions|contraindications|side effects?)|"
                r"what(?:'s| is) (?:the )?dose)\b",
                qn,
                flags=re.IGNORECASE,
            )
        )
    if _has_re(qn, r"^(and|and what about|what about)\b"):
        return True
    if _has_re(
        qn,
        r"^(which one is better|explain (that|this|it) again|tell me more(?: about (that|this|it))?)[\s.!?]*$",
    ):
        return True
    return _has_re(
        qn,
        r"^(what are (?:the )?(?:known )?(interactions|contraindications|side effects?)|"
        r"what(?:'s| is) (?:the )?dose)[\s.!?]*$",
    )


def _media_followup_publication_name(question: str) -> str:
    qn = _norm_text(question)
    patterns = [
        (r"\bfox\s+news\b", "Fox News"),
        (r"\breuters\b", "Reuters"),
        (r"\bbbc\b", "BBC"),
        (r"\bcnn\b", "CNN"),
        (r"\bthe\s+guardian\b|\bguardian\b", "The Guardian"),
        (r"\bnew\s+york\s+times\b|\bnytimes\b|\bnyt\b", "The New York Times"),
        (r"\bwashington\s+post\b", "The Washington Post"),
        (r"\bwall\s+street\s+journal\b|\bwsj\b", "The Wall Street Journal"),
        (r"\bal\s+jazeera\b", "Al Jazeera"),
        (r"\babc\s+news\b|\babc\b", "ABC News"),
        (r"\bnbc\s+news\b|\bnbc\b", "NBC News"),
        (r"\bcbs\s+news\b|\bcbs\b", "CBS News"),
    ]
    for pattern, label in patterns:
        if _has_re(qn, pattern):
            return label
    return ""


def _is_media_reliability_topic(text: str) -> bool:
    qn = _norm_text(text)
    if not _has_re(
        qn,
        r"\b(bias|biased|unbiased|neutral|objective|balanced|fair|trustworthy|credible|reliable|factual|accuracy|propaganda|slant|partisan|can i trust|should i trust|media reliability|media bias|news source)\b",
    ):
        return False
    return _has_re(
        qn,
        r"\b(bbc|fox news|reuters|cnn|guardian|new york times|nytimes|nyt|washington post|wall street journal|wsj|al jazeera|abc news|nbc news|cbs news|publication|broadcaster|outlet|newspaper|news network)\b",
    )


def _is_travel_advisory_topic(text: str) -> bool:
    qn = _norm_text(text)
    return _has_re(qn, r"\b(travel|travelling|traveling|visit|trip|tourism|tourist)\b") and _has_re(
        qn, r"\b(safe|safety|advisory|warning|dangerous|risk|risky|unsafe|secure)\b"
    )


def _is_medical_topic(text: str) -> bool:
    return has_human_medication_topic_query(text)


def _is_news_topic(text: str) -> bool:
    qn = _norm_text(text)
    if _has_re(qn, r"\b(news|headline|headlines|breaking)\b"):
        return True
    if _has_re(qn, r"\b(latest|today|recent|right now|now|this week|as of|what happened)\b") and _has_re(
        qn,
        r"\b(war|conflict|military action|ceasefire|talks?|developments?|hostilities|fighting|stock market|market|election|protest|strike)\b",
    ):
        return True
    if _has_re(qn, r"\b(predict|prediction|outcome|forecast)\b") and _has_re(
        qn,
        r"\b(current|latest|today|recent|right now|now|this week|as of)\b",
    ) and _has_re(qn, r"\b(war|conflict|military action|ceasefire|hostilities|fighting)\b"):
        return True
    return False


def _news_anchor_topic(text: str) -> str:
    qn = _norm_text(text)
    patterns = [
        r"\b(war in [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(conflict in [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(military action in [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(war between [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(conflict between [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(military action between [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(latest on [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(developments? in [a-z0-9][a-z0-9 ,'\-]{1,60})\b",
        r"\b(stock market)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, qn, flags=re.IGNORECASE)
        if match:
            topic = re.sub(r"\b(today|right now|at the moment|currently|latest)\b", "", match.group(1), flags=re.IGNORECASE)
            topic = re.sub(r"\s+", " ", topic).strip(" ,.-")
            if topic:
                return topic
    return ""


def _followup_tail_text(question: str) -> str:
    text = re.sub(r"^\s*(?:and(?:\s+what\s+about)?|what\s+about)\b", "", question or "", flags=re.IGNORECASE)
    text = re.sub(r"^[\s:,\-]+", "", text)
    text = re.sub(r"[\s.?!]+$", "", text)
    return text.strip()


def _clean_candidate_subject(text: str) -> str:
    cleaned = re.sub(r"^[\s\"'`]+|[\s\"'`]+$", "", text or "")
    cleaned = re.sub(r"[\s.?!,:;]+$", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _has_multiple_subject_markers(text: str) -> bool:
    tn = _norm_text(text)
    if not tn:
        return True
    return any(
        marker in tn
        for marker in (
            ",",
            " vs ",
            " versus ",
            " and ",
            " or ",
        )
    )


def _comparison_pair_from_question(question: str) -> Optional[tuple[str, str]]:
    patterns = (
        r"^\s*(?:compare|comparing)\s+(.+?)\s+(?:vs\.?|versus|and)\s+(.+?)[\s.?!]*$",
        r"^\s*(?:what is )?(?:the )?difference between\s+(.+?)\s+(?:and|vs\.?|versus)\s+(.+?)[\s.?!]*$",
        r"^\s*(.+?)\s+vs\.?\s+(.+?)[\s.?!]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, question or "", flags=re.IGNORECASE)
        if not match:
            continue
        left = _clean_candidate_subject(match.group(1))
        right = _clean_candidate_subject(match.group(2))
        if not left or not right:
            continue
        if _has_multiple_subject_markers(left) or _has_multiple_subject_markers(right):
            continue
        if _norm_text(left) == _norm_text(right):
            continue
        return left, right
    return None


def _is_comparison_followup(question: str) -> bool:
    return _has_re(_norm_text(question), r"^which one is better[\s.!?]*$")


def _single_subject_from_question(question: str) -> str:
    patterns = (
        r"^\s*(?:what is|what's|whats|who is|explain|describe|define|tell me about|history of)\s+(.+?)[\s.?!]*$",
    )
    for pattern in patterns:
        match = re.search(pattern, question or "", flags=re.IGNORECASE)
        if not match:
            continue
        subject = _clean_candidate_subject(match.group(1))
        if not subject or _has_multiple_subject_markers(subject):
            continue
        if _has_re(subject, r"^(that|this|it|those|these)$"):
            continue
        return subject
    return ""


def _is_repeat_explanation_followup(question: str) -> bool:
    return _has_re(_norm_text(question), r"^explain (that|this|it) again[\s.!?]*$")


def _is_more_about_subject_followup(question: str) -> bool:
    return _has_re(_norm_text(question), r"^tell me more(?: about (that|this|it))?[\s.!?]*$")


def _medical_followup_subject_name(text: str) -> str:
    try:
        detected = detect_human_medication_query(text)
    except Exception:
        detected = {}
    candidate = _clean_candidate_subject(
        str(detected.get("candidate_medication") or detected.get("normalized_candidate") or "")
    ).lower()
    if re.fullmatch(r"[a-z][a-z0-9-]{1,31}", candidate):
        return candidate
    qn = _norm_text(text)
    subjects = [
        (r"\bamoxicillin\b", "amoxicillin"),
        (r"\btadalafil\b|\bcialis\b", "tadalafil"),
        (r"\bsildenafil\b|\bviagra\b", "sildenafil"),
        (r"\bvardenafil\b", "vardenafil"),
        (r"\bmetformin\b", "metformin"),
        (r"\blipitor\b", "lipitor"),
        (r"\batorvastatin\b", "atorvastatin"),
        (r"\bsimvastatin\b", "simvastatin"),
        (r"\brosuvastatin\b", "rosuvastatin"),
        (r"\bstatin\b", "statin"),
        (r"\binsulin\b", "insulin"),
    ]
    for pattern, label in subjects:
        if _has_re(qn, pattern):
            return label
    return ""


def _medical_followup_resolved_question(previous_question: str, tail: str) -> str:
    subject = _medical_followup_subject_name(previous_question)
    if not subject:
        return ""
    tail_norm = _norm_text(tail)
    if not tail_norm:
        return ""
    if _has_re(tail_norm, r"\b(interaction|interactions)\b"):
        return f"What are the known interactions of {subject}?"
    if _has_re(tail_norm, r"\b(contraindication|contraindications)\b"):
        return f"What are the contraindications of {subject}?"
    if _has_re(tail_norm, r"\b(side effect|side effects)\b"):
        return f"What are the known side effects of {subject}?"
    if _has_re(tail_norm, r"\b(dose|dosage|mg)\b"):
        return f"What is the dose of {subject}?"
    if tail_norm.startswith("for "):
        return f"What about {subject} {tail.strip()}?"
    if _has_re(
        tail_norm,
        r"^(alcohol|grapefruit|nitrates?|ibuprofen|acetaminophen|paracetamol|aspirin|metformin|statin|atorvastatin|lipitor)\b",
    ):
        return f"Is {subject} safe with {tail.strip()}?"
    return f"What about {subject} {tail.strip()}?"


def _pet_type_from_text(text: str) -> str:
    qn = _norm_text(text)
    if _has_re(qn, r"\b(cat|cats|kitten|kittens)\b"):
        return "cat"
    if _has_re(qn, r"\b(dog|dogs|puppy|puppies)\b"):
        return "dog"
    if _has_re(qn, r"\bpet\b"):
        return "pet"
    return ""


def _pet_name_from_text(text: str) -> str:
    patterns = (
        r"\bmy\s+(?:dog|cat|pet)\s+([A-Za-z][A-Za-z'-]{1,31})\b",
        r"^\s*([A-Za-z][A-Za-z'-]{1,31})'s\s+(?:stool|poo|poop|diarrhea|diarrhoea|vomit|vomiting)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _pet_symptom_phrase(text: str) -> str:
    qn = _norm_text(text)
    if _has_re(qn, r"\brunny\s+poo\b"):
        return "has runny poo"
    if _has_re(qn, r"\brunny\s+stool\b"):
        return "has runny stool"
    if _has_re(qn, r"\bloose\s+stool\b|\bstool\s+is\s+loose\b"):
        return "has loose stool"
    if _has_re(qn, r"\bsoft\s+stool\b|\bstool\s+is\s+soft\b"):
        return "has soft stool"
    if _has_re(qn, r"\bdiarrhea\b|\bdiarrhoea\b"):
        return "has diarrhea"
    if _has_re(qn, r"\bvomiting\b|\bvomit\b"):
        return "is vomiting"
    if _has_re(qn, r"\blethargic\b|\blethargy\b"):
        return "is lethargic"
    return ""


def _is_pet_medical_topic(text: str) -> bool:
    qn = _norm_text(text)
    return _has_re(qn, r"\b(dog|dogs|cat|cats|pet|pets|puppy|puppies|kitten|kittens)\b") and _has_re(
        qn,
        r"\b(stool|poo|poop|diarrhea|diarrhoea|vomit|vomiting|lethargy|lethargic|symptom|symptoms|vet|veterinarian|toxic|poison|poisonous)\b",
    )


def _pet_followup_resolved_question(previous_question: str, question: str) -> str:
    qn = _norm_text(question)
    previous_symptom = _pet_symptom_phrase(previous_question)
    if previous_symptom:
        clarify = re.match(
            r"^\s*i meant my (dog|cat|pet)(?:\s+([A-Za-z][A-Za-z'-]{1,31}))?[\s.!?]*$",
            question or "",
            flags=re.IGNORECASE,
        )
        if clarify:
            pet_type = clarify.group(1).lower()
            pet_name = clarify.group(2) or _pet_name_from_text(previous_question)
            subject = f"My {pet_type}"
            if pet_name:
                subject += f" {pet_name}"
            return f"{subject} {previous_symptom}."

    pronoun = re.match(r"^\s*(he|she)\s+(has|is)\b", question or "", flags=re.IGNORECASE)
    if pronoun and _is_pet_medical_topic(previous_question):
        pet_type = _pet_type_from_text(previous_question) or "pet"
        pet_name = _pet_name_from_text(previous_question)
        symptom = _pet_symptom_phrase(question)
        if symptom:
            subject = f"My {pet_type}"
            if pet_name:
                subject += f" {pet_name}"
            return f"{subject} {symptom}."
    return ""


def resolve_contextual_followup(question: str, root: str) -> Optional[Dict[str, str]]:
    previous_question, context_source = _latest_user_context(root)
    if not previous_question:
        return None

    pet_resolved = _pet_followup_resolved_question(previous_question, question)
    if pet_resolved:
        return {
            "resolved_question": pet_resolved,
            "route_reason_override": "contextual_pet_medical_followup",
            "contextual_followup_kind": "pet_medical",
        }

    if not _is_short_followup_prompt(question):
        return None

    # A fresh explicit medication topic should not inherit stale context.
    # Under-specified frames like "what are the known interactions?" should
    # still carry forward the previous medication subject.
    try:
        current_medical = detect_human_medication_query(question)
    except Exception:
        current_medical = {}
    explicit_medication_subject = _clean_candidate_subject(
        str(current_medical.get("normalized_candidate") or current_medical.get("candidate_medication") or "")
    )
    if has_human_medication_topic_query(question) and explicit_medication_subject:
        return None

    if _is_media_reliability_topic(previous_question):
        publication = _media_followup_publication_name(question)
        if publication:
            return {
                "resolved_question": f"How reliable or biased is {publication}?",
                "route_reason_override": "contextual_media_reliability_followup",
                "contextual_followup_kind": "media_reliability",
            }

    if context_source == "memory" and _is_comparison_followup(question):
        comparison_pair = _comparison_pair_from_question(previous_question)
        if comparison_pair:
            left, right = comparison_pair
            return {
                "resolved_question": f"Which is better: {left} or {right}?",
                "route_reason_override": "contextual_comparison_followup",
                "contextual_followup_kind": "comparison",
            }

    if context_source == "memory" and (_is_repeat_explanation_followup(question) or _is_more_about_subject_followup(question)):
        subject = _single_subject_from_question(previous_question)
        if subject:
            resolved_question = f"Explain {subject}."
            if _is_more_about_subject_followup(question):
                resolved_question = f"Tell me more about {subject}."
            return {
                "resolved_question": resolved_question,
                "route_reason_override": "contextual_single_subject_followup",
                "contextual_followup_kind": "single_subject",
            }

    tail = _followup_tail_text(question)
    if not tail:
        return None

    if _is_travel_advisory_topic(previous_question):
        return {
            "resolved_question": f"Is it safe now to travel to {tail}?",
            "route_reason_override": "contextual_travel_followup",
            "contextual_followup_kind": "travel_advisory",
        }

    if _is_news_topic(previous_question):
        anchor = _news_anchor_topic(previous_question)
        resolved_question = f"What are the latest developments about {tail} today?"
        if anchor:
            resolved_question = f"What are the latest developments about {tail} related to {anchor} today?"
        return {
            "resolved_question": resolved_question,
            "route_reason_override": "contextual_news_followup",
            "contextual_followup_kind": "news",
        }

    if _is_medical_topic(previous_question):
        resolved_question = _medical_followup_resolved_question(previous_question, tail)
        if resolved_question:
            return {
                "resolved_question": resolved_question,
                "route_reason_override": "contextual_medical_followup",
                "contextual_followup_kind": "medical",
            }

    return None
