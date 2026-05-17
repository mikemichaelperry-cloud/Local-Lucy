#!/usr/bin/env python3
import argparse
import re
import shlex
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from medical_query_heuristics import detect_human_medication_query, normalize_for_medical_match


TRUSTED_MEDICAL_DOMAINS = {
    "medlineplus.gov",
    "dailymed.nlm.nih.gov",
    "pubmed.ncbi.nlm.nih.gov",
}

DOMAIN_PRIORITY = {
    "dailymed.nlm.nih.gov": 0,
    "medlineplus.gov": 1,
    "pubmed.ncbi.nlm.nih.gov": 2,
}

SECTION_STOP_PATTERNS: Tuple[str, ...] = (
    r"^boxed warning$",
    r"^warnings?( and precautions)?$",
    r"^precautions$",
    r"^contraindications$",
    r"^drug interactions$",
    r"^interactions$",
    r"^adverse reactions$",
    r"^side effects$",
    r"^indications?( and usage)?$",
    r"^uses?$",
    r"^dosage( and administration)?$",
    r"^recommended dosage$",
    r"^how supplied$",
    r"^description$",
    r"^clinical pharmacology$",
    r"^clinical studies$",
    r"^references$",
    r"^patient counseling information$",
)

INTERACTION_COUNTERPART_STOPWORDS = {
    "about",
    "and",
    "are",
    "can",
    "correct",
    "does",
    "drug",
    "for",
    "have",
    "interact",
    "interaction",
    "interactions",
    "is",
    "it",
    "medication",
    "medicine",
    "react",
    "safe",
    "take",
    "the",
    "what",
    "with",
}


def normalize_domain(domain: str) -> str:
    value = (domain or "").strip().lower()
    if value.startswith("www."):
        value = value[4:]
    return value


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def parse_evidence_pack(pack_file: str) -> List[Dict[str, str]]:
    text = Path(pack_file).read_text(encoding="utf-8", errors="ignore")
    items: List[Dict[str, str]] = []
    pattern = re.compile(r"BEGIN_EVIDENCE_ITEM\n(.*?)\nEND_EVIDENCE_ITEM", flags=re.DOTALL)
    for match in pattern.finditer(text):
        block = match.group(1)
        header, sep, body = block.partition("\n----\n")
        if not sep:
            continue
        meta: Dict[str, str] = {}
        for raw_line in header.splitlines():
            line = raw_line.strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            meta[key] = value.strip()
        domain = normalize_domain(meta.get("DOMAIN", ""))
        if not domain:
            continue
        items.append(
            {
                "key": meta.get("KEY", ""),
                "domain": domain,
                "body": body.strip(),
            }
        )
    items.sort(key=lambda item: (DOMAIN_PRIORITY.get(item["domain"], 50), item["domain"], item["key"]))
    return items


def domains_from_file(domains_file: str) -> List[str]:
    domains: List[str] = []
    if not domains_file:
        return domains
    path = Path(domains_file)
    if not path.is_file():
        return domains
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        domain = normalize_domain(raw_line)
        if domain and domain in TRUSTED_MEDICAL_DOMAINS and domain not in domains:
            domains.append(domain)
    return sorted(domains, key=lambda domain: (DOMAIN_PRIORITY.get(domain, 50), domain))


def derive_query_family(query: str, detector: Dict[str, object]) -> str:
    normalized = str(detector.get("normalized_query") or normalize_for_medical_match(query))
    pattern_family = str(detector.get("pattern_family") or "")
    if re.search(r"\bcontraindication(?:s)?\b", normalized, flags=re.IGNORECASE):
        return "contraindications"
    if re.search(r"\b(interaction|interactions|interact|react with|safe with|alcohol|grapefruit)\b", normalized, flags=re.IGNORECASE):
        return "interactions"
    if re.search(r"\b(dose|dosage|mg|mcg|g|ml)\b", normalized, flags=re.IGNORECASE):
        return "dose"
    if pattern_family == "safe_with":
        return "interactions"
    if pattern_family in {"interactions", "dose"}:
        return pattern_family
    return ""


def derive_counterpart(query: str, candidate: str) -> str:
    normalized = normalize_for_medical_match(query)
    for literal in ("alcohol", "grapefruit", "nitrate", "nitrates"):
        if re.search(rf"\b{literal}\b", normalized, flags=re.IGNORECASE):
            return literal
    for pattern in (
        r"\bsafe with\s+([a-z][a-z0-9-]{2,24})\b",
        r"\b(?:interact|react)\s+with\s+([a-z][a-z0-9-]{2,24})\b",
    ):
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            counterpart = match.group(1).lower()
            if counterpart != candidate:
                return counterpart
    for token in re.findall(r"[a-z][a-z0-9-]{2,24}", normalized):
        if token == candidate or token in INTERACTION_COUNTERPART_STOPWORDS:
            continue
        return token
    return ""


def looks_like_heading(line: str) -> bool:
    line = normalize_space(line)
    if not line or len(line) > 80:
        return False
    lowered = line.lower()
    if any(re.fullmatch(pattern, lowered) for pattern in SECTION_STOP_PATTERNS):
        return True
    letters = re.sub(r"[^A-Za-z]", "", line)
    return bool(letters) and letters.upper() == letters and len(letters) >= 4


def truncate_fact(text: str, limit: int = 180) -> str:
    cleaned = normalize_space(text).strip(" .;:-")
    if len(cleaned) <= limit:
        return cleaned
    shortened = cleaned[: limit - 1].rsplit(" ", 1)[0].strip()
    return f"{shortened}..."


def split_sentences(text: str) -> List[str]:
    collapsed = normalize_space(text)
    if not collapsed:
        return []
    return [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", collapsed) if sentence.strip()]


def extract_section_block(body: str, heading_patterns: Sequence[str]) -> str:
    lines = [normalize_space(line) for line in body.splitlines()]
    for idx, line in enumerate(lines):
        if not line:
            continue
        if not any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in heading_patterns):
            continue
        block_lines: List[str] = []
        for next_idx in range(idx + 1, min(idx + 10, len(lines))):
            candidate_line = lines[next_idx]
            if not candidate_line:
                if block_lines:
                    break
                continue
            if looks_like_heading(candidate_line) and block_lines:
                break
            block_lines.append(candidate_line)
        if block_lines:
            return " ".join(block_lines)
    return ""


def sentence_with_patterns(text: str, required_patterns: Sequence[str], context_patterns: Sequence[str] = ()) -> str:
    for sentence in split_sentences(text):
        if not all(re.search(pattern, sentence, flags=re.IGNORECASE) for pattern in required_patterns):
            continue
        if context_patterns and not any(re.search(pattern, sentence, flags=re.IGNORECASE) for pattern in context_patterns):
            continue
        return truncate_fact(sentence)
    return ""


def extract_dose_fact(items: Sequence[Dict[str, str]]) -> Tuple[str, str]:
    heading_patterns = (r"\bdosage and administration\b", r"\brecommended dosage\b", r"\bdosage\b", r"\busual adult dose\b")
    sentence_patterns = (
        r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|mL)\b",
        r"\b(once daily|twice daily|daily|every\s+\d+\s*(?:to\s*\d+\s*)?hours?)\b",
    )
    fallback_patterns = (
        r"\b(?:usual adult dose|recommended dose|initial dose|starting dose)\b[^.]{0,160}",
    )
    for item in items:
        for body in (extract_section_block(item["body"], heading_patterns), item["body"]):
            body = normalize_space(body)
            if not body:
                continue
            fact = sentence_with_patterns(body, sentence_patterns)
            if fact:
                return fact, item["domain"]
            for pattern in fallback_patterns:
                match = re.search(pattern, body, flags=re.IGNORECASE)
                if match:
                    return truncate_fact(match.group(0)), item["domain"]
    return "", ""


def extract_contraindication_fact(items: Sequence[Dict[str, str]]) -> Tuple[str, str]:
    heading_patterns = (r"\bcontraindications\b",)
    for item in items:
        block = extract_section_block(item["body"], heading_patterns)
        if not block:
            continue
        fact = sentence_with_patterns(block, (r"\bcontraindicat(?:ed|ion|ions)\b",))
        if fact:
            return fact, item["domain"]
        sentences = split_sentences(block)
        if sentences:
            return truncate_fact(sentences[0]), item["domain"]
    return "", ""


def extract_interaction_fact(items: Sequence[Dict[str, str]], counterpart: str) -> Tuple[str, str]:
    if not counterpart:
        return "", ""
    heading_patterns = (r"\bdrug interactions\b", r"\binteractions\b")
    context_patterns = (
        r"\b(interact|interaction|interactions|avoid|contraindicat|coadminister|concomitant|increase|decrease)\b",
    )
    counterpart_pattern = rf"\b{re.escape(counterpart)}\b"
    for item in items:
        for body in (extract_section_block(item["body"], heading_patterns), item["body"]):
            body = normalize_space(body)
            if not body:
                continue
            fact = sentence_with_patterns(body, (counterpart_pattern,), context_patterns)
            if fact:
                return fact, item["domain"]
    return "", ""


def action_hint_for_family(family: str) -> str:
    if family == "dose":
        return "review the listed trusted medical sources directly and confirm the exact dose with a clinician or pharmacist"
    if family == "interactions":
        return "review the listed trusted medical sources directly and ask a clinician or pharmacist to check the exact combination"
    if family == "contraindications":
        return "review the listed trusted medical sources directly and confirm contraindications against the patient's history with a clinician or pharmacist"
    return "review the listed trusted medical sources directly or ask a clinician or pharmacist for medication-specific guidance"


def extract_fact(query: str, pack_file: str, domains_file: str = "") -> Dict[str, str]:
    detector = detect_human_medication_query(query)
    candidate = str(detector.get("normalized_candidate") or "").strip().lower()
    family = derive_query_family(query, detector)
    result: Dict[str, str] = {
        "MEDICAL_STRUCTURED_SUPPORTED": "false",
        "MEDICAL_STRUCTURED_STATUS": "unsupported",
        "MEDICAL_STRUCTURED_REASON": "family_unsupported",
        "MEDICAL_STRUCTURED_QUERY_FAMILY": family,
        "MEDICAL_STRUCTURED_CANDIDATE": candidate,
        "MEDICAL_STRUCTURED_COUNTERPART": "",
        "MEDICAL_STRUCTURED_FACT": "",
        "MEDICAL_STRUCTURED_EVIDENCE_DOMAIN": "",
        "MEDICAL_STRUCTURED_ACTION_HINT": "",
    }
    if detector.get("detector_fired") is not True or not candidate or family not in {"dose", "interactions", "contraindications"}:
        return result

    trusted_domains = domains_from_file(domains_file)
    items = [item for item in parse_evidence_pack(pack_file) if item["domain"] in TRUSTED_MEDICAL_DOMAINS]
    result["MEDICAL_STRUCTURED_SUPPORTED"] = "true"
    result["MEDICAL_STRUCTURED_ACTION_HINT"] = action_hint_for_family(family)

    if len(trusted_domains) < 2:
        result["MEDICAL_STRUCTURED_STATUS"] = "insufficient"
        result["MEDICAL_STRUCTURED_REASON"] = "insufficient_domains"
        return result

    if family == "dose":
        fact, evidence_domain = extract_dose_fact(items)
    elif family == "contraindications":
        fact, evidence_domain = extract_contraindication_fact(items)
    else:
        counterpart = derive_counterpart(query, candidate)
        result["MEDICAL_STRUCTURED_COUNTERPART"] = counterpart
        fact, evidence_domain = extract_interaction_fact(items, counterpart)

    if not fact:
        result["MEDICAL_STRUCTURED_STATUS"] = "insufficient"
        result["MEDICAL_STRUCTURED_REASON"] = "no_bounded_fact"
        return result

    result["MEDICAL_STRUCTURED_STATUS"] = "answered"
    result["MEDICAL_STRUCTURED_REASON"] = "bounded_fact_found"
    result["MEDICAL_STRUCTURED_FACT"] = fact
    result["MEDICAL_STRUCTURED_EVIDENCE_DOMAIN"] = evidence_domain
    return result


def write_env(path: str, values: Dict[str, str]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for key in sorted(values):
            handle.write(f"{key}={shlex.quote(str(values[key]))}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--pack-file", required=True)
    parser.add_argument("--domains-file", default="")
    parser.add_argument("--env-out", required=True)
    args = parser.parse_args()

    values = extract_fact(args.query, args.pack_file, domains_file=args.domains_file)
    write_env(args.env_out, values)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
