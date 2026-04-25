#!/usr/bin/env python3
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Final, List, Tuple


HUMAN_MEDICATION_HIGH_RISK_PATTERN: Final[str] = (
    r"(^|[^a-z])("
    r"tadalafil|tadalifil|cialis|viagra|sildenafil|vardenafil|"
    r"metformin|statin|insulin|ibuprofen|acetaminophen|paracetamol|atorvastatin|amoxicillin|"
    r"arrhythmia|afib|qt|palpitations|dose|dosage|mg|"
    r"side effect|side effects|contraindication|contraindications|"
    r"interaction|interactions|medication|drug|drugs|alcohol|"
    r"covered by insurance|hmo|kupat holim|hypertension|antihypertensive"
    r")([^a-z]|$)|react\s+with"
)

MEDICATION_SUFFIXES: Final[Tuple[str, ...]] = (
    "afil",
    "azole",
    "caine",
    "cillin",
    "cycline",
    "dipine",
    "formin",
    "gliflozin",
    "gliptin",
    "mab",
    "mycin",
    "olol",
    "oxetine",
    "prazole",
    "pril",
    "sartan",
    "setron",
    "statin",
    "tidine",
    "vir",
    "xaban",
)

KNOWN_MEDICATION_TOKENS: Final[set[str]] = {
    "acetaminophen",
    "amlodipine",
    "amoxicillin",
    "aspirin",
    "atorvastatin",
    "ibuprofen",
    "insulin",
    "lisinopril",
    "metformin",
    "naproxen",
    "omeprazole",
    "paracetamol",
    "sildenafil",
    "simvastatin",
    "tadalafil",
    "vardenafil",
    "warfarin",
}

MEDICATION_STOPWORDS: Final[set[str]] = {
    "about",
    "affect",
    "alcohol",
    "am",
    "and",
    "are",
    "correct",
    "do",
    "does",
    "dose",
    "dosage",
    "drug",
    "drugs",
    "effect",
    "effects",
    "for",
    "grapefruit",
    "interaction",
    "interactions",
    "is",
    "medication",
    "medicine",
    "mg",
    "of",
    "safe",
    "side",
    "tablet",
    "tablets",
    "take",
    "what",
    "with",
}

CAPTURED_CANDIDATE_PATTERNS: Final[Tuple[Tuple[str, str], ...]] = (
    ("side_effects", r"\bside effects?\s+of\s+([a-z][a-z0-9-]{2,24})\b"),
    ("interactions", r"\bdoes\s+([a-z][a-z0-9-]{2,24})\s+(?:interact|react)\b"),
    ("interactions", r"\b([a-z][a-z0-9-]{2,24})\s+(?:alcohol|grapefruit)\s+interaction\b"),
    ("definition", r"\bwhat(?:'s| is)\s+([a-z][a-z0-9-]{2,24})\b"),
    ("definition", r"\bwhat\s+does\s+([a-z][a-z0-9-]{2,24})\s+do\b"),
    ("safe_with", r"\bis\s+([a-z][a-z0-9-]{2,24})\s+safe\s+with\b"),
    ("dose", r"\bdose(?:\s+of)?\s+([a-z][a-z0-9-]{2,24})\b"),
)

MEDICATION_RISK_FRAME_PATTERN: Final[str] = (
    r"\b(side effect|side effects|interaction|interactions|interact|react\s+with|"
    r"contraindication|contraindications|safe with|dose|dosage|mg|alcohol|grapefruit)\b"
)

MEDICATION_DEFINITION_FRAME_PATTERN: Final[str] = r"\b(what(?:'s| is)|what does|does|is|dose(?: of)?)\b"
MEDICATION_TOPIC_FRAME_PATTERN: Final[str] = (
    r"\b(what(?:'s| is)|what does|does|is|explain|describe|tell me about|tell me more about|"
    r"used for|use for|take for|treat|treatment|for|with|safe|safer|better)\b"
)
MEDICATION_CONDITION_PATTERN: Final[str] = (
    r"\b(blood pressure|high blood pressure|hypertension|cholesterol|diabetes|blood sugar|"
    r"pain|headache|migraine|fever|infection|anxiety|depression|asthma|allergy|heartburn|"
    r"erectile dysfunction|ed|sleep|insomnia|nausea|inflammation)\b"
)


def _config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "config"


def _token_looks_like_medication(token: str) -> bool:
    token = (token or "").strip().lower()
    if not token or token in MEDICATION_STOPWORDS:
        return False
    if token in KNOWN_MEDICATION_TOKENS:
        return True
    return any(token.endswith(suffix) for suffix in MEDICATION_SUFFIXES)


def _extract_exact_word_pattern(pattern: str) -> str:
    match = re.fullmatch(r"\\b([a-z0-9-]{2,32})\\b", pattern.strip().lower())
    return match.group(1) if match else ""


@lru_cache(maxsize=1)
def _load_medical_alias_data() -> Tuple[List[Tuple[re.Pattern[str], str]], Dict[str, str]]:
    rules: List[Tuple[re.Pattern[str], str]] = []
    token_aliases: Dict[str, str] = {}
    path = _config_dir() / "evidence_normalization_aliases_v1.tsv"
    if not path.is_file():
        return rules, token_aliases
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = raw_line.split("\t")
        if len(parts) < 5 or parts[0].strip().lower() != "medical":
            continue
        pattern = parts[3].strip()
        replacement = parts[4].strip().lower()
        if not pattern or not replacement:
            continue
        try:
            rules.append((re.compile(pattern, flags=re.IGNORECASE), replacement))
        except re.error:
            continue
        alias = _extract_exact_word_pattern(pattern)
        if alias and _token_looks_like_medication(replacement):
            token_aliases[alias] = replacement
    return rules, token_aliases


def _apply_medical_alias_rules(text: str) -> str:
    rewritten = text
    for pattern, replacement in _load_medical_alias_data()[0]:
        rewritten = pattern.sub(replacement, rewritten)
    return re.sub(r"\s+", " ", rewritten).strip()


def _tokenize(text: str) -> List[str]:
    return re.findall(r"[a-z][a-z0-9-]{1,24}", text or "")


def _normalize_candidate(token: str) -> str:
    normalized = re.sub(r"^[^a-z0-9]+|[^a-z0-9]+$", "", (token or "").strip().lower())
    alias_map = _load_medical_alias_data()[1]
    return alias_map.get(normalized, normalized)


def _extract_candidate(raw_text: str, normalized_text: str) -> Tuple[str, str]:
    for family, pattern in CAPTURED_CANDIDATE_PATTERNS:
        raw_match = re.search(pattern, raw_text, flags=re.IGNORECASE)
        if raw_match:
            return raw_match.group(1).lower(), family
    alias_map = _load_medical_alias_data()[1]
    for token in _tokenize(raw_text):
        if token in alias_map:
            return token, "alias_catalog"
    if re.search(MEDICATION_RISK_FRAME_PATTERN, normalized_text, flags=re.IGNORECASE):
        for token in _tokenize(normalized_text):
            if _token_looks_like_medication(token):
                return token, "risk_frame_scan"
    return "", ""


def _confidence(score: float) -> Tuple[str, float]:
    bounded = round(max(0.0, min(1.0, score)), 2)
    if bounded >= 0.9:
        return "high", bounded
    if bounded >= 0.72:
        return "medium", bounded
    if bounded > 0:
        return "low", bounded
    return "none", bounded


def normalize_for_medical_match(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    normalized = re.sub(r"\barrhythia\b", "arrhythmia", normalized)
    normalized = re.sub(r"\beffect\b", "affect", normalized)
    normalized = re.sub(r"\bside affects\b", "side effects", normalized)
    normalized = re.sub(r"\bside affect\b", "side effect", normalized)
    return _apply_medical_alias_rules(normalized)


def detect_human_medication_query(text: str) -> Dict[str, object]:
    original = re.sub(r"\s+", " ", (text or "").strip())
    normalized = normalize_for_medical_match(original)
    candidate_raw, pattern_family = _extract_candidate(original.lower(), normalized)
    normalized_candidate = _normalize_candidate(candidate_raw)
    high_risk_terms = re.search(HUMAN_MEDICATION_HIGH_RISK_PATTERN, normalized, flags=re.IGNORECASE) is not None
    hypertension_rule = (
        re.search(r"(high blood pressure|blood pressure|hypertension)", normalized, flags=re.IGNORECASE) is not None
        and re.search(
            r"(medication|medicine|drug|drugs|treatment|treat|tablet|tablets|pill|pills|dose|dosage|safe|correct)",
            normalized,
            flags=re.IGNORECASE,
        )
        is not None
    )
    risk_frame = re.search(MEDICATION_RISK_FRAME_PATTERN, normalized, flags=re.IGNORECASE) is not None
    definition_frame = re.search(MEDICATION_DEFINITION_FRAME_PATTERN, normalized, flags=re.IGNORECASE) is not None
    topic_frame = re.search(MEDICATION_TOPIC_FRAME_PATTERN, normalized, flags=re.IGNORECASE) is not None
    condition_context = re.search(MEDICATION_CONDITION_PATTERN, normalized, flags=re.IGNORECASE) is not None
    explicit_followup_frame = re.search(r"^\s*(what about|how about)\b", normalized, flags=re.IGNORECASE) is not None
    alias_map = _load_medical_alias_data()[1]

    fired = False
    detection_source = "not_detected"
    notes: List[str] = []
    score = 0.0

    if candidate_raw:
        if candidate_raw in alias_map:
            notes.append("alias_catalog_match")
        if normalized_candidate and normalized_candidate != candidate_raw:
            notes.append("alias_normalized_candidate")
        if pattern_family:
            notes.append(f"pattern_family={pattern_family}")
        if risk_frame and (candidate_raw in alias_map or _token_looks_like_medication(normalized_candidate or candidate_raw)):
            fired = True
            detection_source = "alias_catalog" if candidate_raw in alias_map else "candidate_heuristic"
            score = 0.97 if candidate_raw in alias_map else 0.9
        elif definition_frame and (candidate_raw in alias_map or _token_looks_like_medication(normalized_candidate or candidate_raw)):
            fired = True
            detection_source = "alias_catalog" if candidate_raw in alias_map else "candidate_heuristic"
            score = 0.92 if candidate_raw in alias_map else 0.82

    if not candidate_raw:
        for token in _tokenize(normalized):
            if not _token_looks_like_medication(token):
                continue
            candidate_raw = token
            normalized_candidate = _normalize_candidate(token)
            pattern_family = "topic_scan"
            notes.append("pattern_family=topic_scan")
            break

    if not fired and high_risk_terms:
        fired = True
        detection_source = "known_high_risk_terms"
        score = 0.9
        notes.append("known_high_risk_terms")

    if not fired and candidate_raw and _token_looks_like_medication(normalized_candidate or candidate_raw) and (
        topic_frame or condition_context or explicit_followup_frame
    ):
        fired = True
        detection_source = "topic_frame"
        score = 0.88 if condition_context else 0.82
        notes.append("topic_frame")

    if hypertension_rule:
        fired = True
        detection_source = "hypertension_rule"
        score = max(score, 0.95)
        notes.append("hypertension_medication_rule")

    confidence, confidence_score = _confidence(score)
    if not fired:
        pattern_family = ""
        candidate_raw = ""
        normalized_candidate = ""
        normalized = ""
    return {
        "detector_fired": fired,
        "original_query": original,
        "resolved_execution_query": original,
        "normalized_query": normalized,
        "detection_source": detection_source,
        "pattern_family": pattern_family or "",
        "candidate_medication": candidate_raw,
        "normalized_candidate": normalized_candidate,
        "confidence": confidence,
        "confidence_score": confidence_score,
        "provenance_notes": notes[:4],
    }


def has_human_medication_high_risk_terms(text: str) -> bool:
    normalized = normalize_for_medical_match(text)
    return re.search(HUMAN_MEDICATION_HIGH_RISK_PATTERN, normalized, flags=re.IGNORECASE) is not None


def is_human_medication_high_risk_query(text: str) -> bool:
    return bool(detect_human_medication_query(text).get("detector_fired"))


def has_human_medication_topic_query(text: str) -> bool:
    normalized = normalize_for_medical_match(text)
    if not normalized:
        return False
    if detect_human_medication_query(text).get("detector_fired"):
        return True
    medication_tokens = [token for token in _tokenize(normalized) if _token_looks_like_medication(token)]
    if not medication_tokens:
        return False
    if re.search(r"^\s*(what about|how about)\b", normalized, flags=re.IGNORECASE):
        return True
    if re.search(MEDICATION_TOPIC_FRAME_PATTERN, normalized, flags=re.IGNORECASE):
        return True
    if re.search(MEDICATION_CONDITION_PATTERN, normalized, flags=re.IGNORECASE):
        return True
    return False
