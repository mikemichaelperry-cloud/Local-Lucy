#!/usr/bin/env python3
"""
Trusted sources provider for category-specific queries (news, medical, finance).

Supports regional news:
- news_world: International news sources
- news_israel: Israel-specific news sources
- news_australia: AU-specific news sources

Fetches from domain allowlists in config/trust/generated/ and formats
deterministic responses. For news, it fetches actual RSS feeds and extracts headlines.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Web extraction adapter (webclaw → fallback) and pure-Python fetch gate
_INTERNET_DIR = str(Path(__file__).resolve().parent / "internet")
sys.path.insert(0, _INTERNET_DIR)
try:
    from web_extract import _is_substantive_content, extract_webpage

    HAS_WEB_EXTRACT = True
except Exception:
    HAS_WEB_EXTRACT = False

    def _is_substantive_content(text: str, **_: Any) -> bool:  # type: ignore[misc]
        return bool(text and len(text) > 300)


try:
    import fetch_gate
    import search_web

    HAS_FETCH_GATE = True
except Exception:
    HAS_FETCH_GATE = False


def _print_fail(reason: str) -> int:
    print(json.dumps({"ok": False, "provider": "trusted", "reason": reason}))
    return 1


def _get_root() -> Path:
    return Path(os.environ.get("LUCY_ROOT") or Path(__file__).resolve().parents[1]).expanduser()


def _load_domain_allowlist(category: str) -> list[str]:
    """Load domain allowlist for a category."""
    root = _get_root()
    for filename in [f"{category}_runtime.txt", f"{category}.txt"]:
        path = root / "config" / "trust" / "generated" / filename
        if path.exists():
            domains = []
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    domain = line.strip().lower()
                    if domain and not domain.startswith("#"):
                        domains.append(domain)
            return domains
    # Fallback for news categories
    if category.startswith("news_"):
        return _load_domain_allowlist("news_world")
    return []


def _load_keymap() -> dict[str, tuple[str, str]]:
    """Load evidence keymap. Returns dict of key -> (url, domain)."""
    root = _get_root()
    keymap_path = root / "config" / "evidence_keymap.tsv"
    keys = {}
    if keymap_path.exists():
        with open(keymap_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if line.startswith("#") or not line.strip():
                    continue
                parts = line.strip().split("\t")
                if len(parts) >= 3:
                    keys[parts[0]] = (parts[1], parts[2])
    return keys


def _dedupe_domains(domains: list[str]) -> list[str]:
    """Remove duplicate domains (www. vs non-www, feeds. prefixes, etc)."""
    seen = set()
    result = []
    for domain in domains:
        normalized = domain
        for prefix in ["www.", "feeds.", "rss."]:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _detect_news_region(question: str) -> str:
    """Detect which news region the query is asking about."""
    q_lower = question.lower()

    # Israel-specific keywords
    israel_keywords = [
        "israel",
        "israeli",
        "gaza",
        "idf",
        "west bank",
        "jerusalem",
        "tel aviv",
        "netanyahu",
        "hamas",
        "hezbollah",
        "knesset",
        "haaretz",
        "ynet",
        "jpost",
    ]
    if any(kw in q_lower for kw in israel_keywords):
        return "news_israel"

    # Australia-specific keywords
    au_keywords = [
        "australia",
        "australian",
        "canberra",
        "sydney",
        "melbourne",
        "brisbane",
        "perth",
        "adelaide",
        "abc.net.au",
        "sbs.com.au",
    ]
    if any(kw in q_lower for kw in au_keywords):
        return "news_australia"

    # Default to world news
    return "news_world"


def _is_category_supported(intent_family: str, question: str) -> tuple[str | None, str | None]:
    """
    Determine if this query should use trusted sources.
    Returns (category, sub_type) or (None, None).
    """
    q_lower = question.lower()

    # Check for veterinary queries FIRST (before medical, to avoid false overlap)
    veterinary_keywords = [
        "veterinary",
        "vet",
        "veterinarian",
        "animal health",
        "dog",
        "dogs",
        "puppy",
        "puppies",
        "cat",
        "cats",
        "kitten",
        "kittens",
        "pet",
        "pets",
        "parvovirus",
        "parvo",
        "rabies",
        "distemper",
        "bordetella",
        "leptospirosis",
        "heartworm",
        "flea",
        "tick",
        "tapeworm",
        "roundworm",
        "spay",
        "neuter",
        "neutering",
        "spaying",
        "kennel cough",
        "hip dysplasia",
        "bloat",
        "gastric dilatation",
        "pancreatitis",
        "diabetes",
        "hyperthyroidism",
        "hypothyroidism",
        "renal failure",
        "kidney disease",
        "liver disease",
        "arthritis",
        "osteoarthritis",
        "dysplasia",
        "vaccination",
        "vaccine",
        "deworm",
        "deworming",
        "grooming",
        "dental",
        "teeth cleaning",
        "merck vet",
        "avma",
        "vca",
        "aaha",
        "aspca",
    ]
    if any(kw in q_lower for kw in veterinary_keywords):
        return ("vet", "vet")

    # Check for medical queries
    medical_keywords = [
        "medical",
        "medication",
        "medicine",
        "drug",
        "dose",
        "dosage",
        "side effect",
        "interaction",
        "contraindication",
        "health",
        "prescription",
        "treatment",
        "amoxicillin",
        "aspirin",
        "tadalafil",
        "cialis",
        "viagra",
        "metformin",
        "insulin",
        "antibiotic",
        "pharmacy",
        "pharmacist",
        "doctor",
        "physician",
    ]
    if any(kw in q_lower for kw in medical_keywords):
        return ("medical", "medical")

    # Check for finance queries
    finance_keywords = [
        "finance",
        "stock",
        "market",
        "economy",
        "currency",
        "exchange rate",
        "investment",
        "financial",
    ]
    if any(kw in q_lower for kw in finance_keywords):
        return ("finance", "finance")

    # Check for news queries
    news_keywords = ["news", "headline", "headlines", "breaking", "latest news", "world news"]
    if any(kw in q_lower for kw in news_keywords):
        region = _detect_news_region(question)
        return (region, "news")

    return (None, None)


def _fetch_rss(url: str, timeout: int = 30) -> str | None:
    """Fetch RSS content from URL via the pure-Python fetch gate."""
    if not HAS_FETCH_GATE:
        return None
    try:
        reason, text = fetch_gate.fetch_url_text(url, timeout=timeout)
        if reason == fetch_gate.OK and text:
            return text
    except Exception:
        pass
    return None


def _parse_rss(xml_content: str) -> list[dict[str, str]]:
    """Parse RSS/Atom XML and extract items."""
    items = []
    if not xml_content or not xml_content.strip():
        return items

    # Check if it looks like RSS/Atom
    if not re.search(r"<(rss|feed|channel)", xml_content, re.I):
        return items

    try:
        root = ET.fromstring(xml_content)
    except Exception:
        return items

    # RSS: <channel><item>...
    for item_elem in root.findall(".//item"):
        title = ""
        date = ""
        desc = ""

        title_elem = item_elem.find("title")
        if title_elem is not None and title_elem.text:
            title = html.unescape(title_elem.text.strip())

        date_elem = item_elem.find("pubDate")
        if date_elem is not None and date_elem.text:
            date = html.unescape(date_elem.text.strip())

        desc_elem = item_elem.find("description")
        if desc_elem is not None and desc_elem.text:
            desc = html.unescape(desc_elem.text.strip())
            # Clean HTML tags
            desc = re.sub(r"<[^>]+>", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()

        if title:
            items.append({"title": title, "date": date, "desc": desc})

    # Atom: <entry>...
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for entry_elem in root.findall(".//atom:entry", ns):
        title = ""
        date = ""
        desc = ""

        title_elem = entry_elem.find("atom:title", ns)
        if title_elem is not None and title_elem.text:
            title = html.unescape(title_elem.text.strip())

        date_elem = entry_elem.find("atom:updated", ns)
        if date_elem is not None and date_elem.text:
            date = html.unescape(date_elem.text.strip())

        desc_elem = entry_elem.find("atom:summary", ns)
        if desc_elem is not None and desc_elem.text:
            desc = html.unescape(desc_elem.text.strip())

        if title:
            items.append({"title": title, "date": date, "desc": desc})

    return items


def _get_news_keys_for_region(region: str) -> list[str]:
    """Get evidence keys for a news region."""
    keymap = _load_keymap()
    prefix = region  # e.g., "news_world", "news_israel", "news_australia"
    keys = []
    for key in sorted(keymap.keys()):
        if key.startswith(prefix + "_"):
            keys.append(key)
    return keys


def _fetch_news_headlines(region: str, max_items: int = 8) -> list[dict[str, str]]:
    """Fetch and parse RSS feeds for a news region."""
    keys = _get_news_keys_for_region(region)
    keymap = _load_keymap()
    all_items = []

    for key in keys[:4]:  # Max 4 sources
        if key not in keymap:
            continue
        url, domain = keymap[key]
        xml_content = _fetch_rss(url, timeout=15)
        if xml_content:
            items = _parse_rss(xml_content)
            for item in items[:3]:  # Max 3 items per source
                item["source"] = domain
                all_items.append(item)
        if len(all_items) >= max_items:
            break

    return all_items[:max_items]


def _search_restricted(
    query: str, domains: list[str], max_results: int = 3
) -> list[dict[str, str]]:
    """Search the web restricted to a domain allowlist."""
    if not HAS_FETCH_GATE:
        return []
    try:
        _backend, results = search_web.multi_backend_search(query, max_results=max_results * 2)
        filtered: list[dict[str, str]] = []
        for r in results:
            url = r.get("url", "").strip()
            title = r.get("title", "").strip()
            snippet = r.get("snippet", r.get("body", "")).strip()
            if title and url and search_web.domain_allowed(url, domains):
                filtered.append({"title": title, "url": url, "snippet": snippet})
            if len(filtered) >= max_results:
                break
        return filtered
    except Exception:
        pass
    return []


def _fetch_article_content(
    url: str, max_chars: int = 2500, _telemetry_out: dict[str, Any] | None = None
) -> str | None:
    """Fetch and extract clean text from a trusted URL."""
    if not HAS_WEB_EXTRACT:
        return None
    try:
        telemetry: dict[str, Any] = {}
        result = extract_webpage(url, max_chars=max_chars, timeout=15, _telemetry_out=telemetry)
        if _telemetry_out is not None:
            _telemetry_out.update(telemetry)
        return result
    except Exception:
        if _telemetry_out is not None:
            _telemetry_out["fallback_used"] = True
            _telemetry_out["primary_failed"] = "article_extraction"
            _telemetry_out["fallback_to"] = ""
            _telemetry_out["successful_backend"] = ""
            _telemetry_out["degradation_level"] = "low"
        return None


def _try_direct_fetch(question: str, category: str) -> tuple[str, str] | None:
    """When SearXNG search fails, try fetching directly from trusted sources.

    Returns (content, source_name) or None if all fail.
    """
    if not HAS_WEB_EXTRACT:
        return None

    q_lower = question.lower()
    q_encoded = question.replace(" ", "%20")

    # Extract likely topic keywords from the query
    stop_words = {
        "what",
        "are",
        "the",
        "symptoms",
        "of",
        "is",
        "a",
        "an",
        "my",
        "i",
        "have",
        "do",
        "does",
        "how",
        "why",
        "when",
        "where",
        "who",
        "can",
        "should",
        "would",
        "could",
        "will",
        "treatment",
        "for",
        "cause",
        "causes",
        "signs",
        "diagnosis",
        "side",
        "effects",
        "definition",
        "explain",
        "tell",
        "about",
    }
    words = [w for w in re.findall(r"[a-z]+", q_lower) if w not in stop_words and len(w) > 2]

    candidates: list[tuple[str, str]] = []

    if category == "medical":
        # --- MedlinePlus (primary US gov health source) ---
        for word in words:
            candidates.append((f"https://medlineplus.gov/{word}.html", "MedlinePlus"))
        for word in words:
            candidates.append((f"https://medlineplus.gov/ency/article/{word}.htm", "MedlinePlus"))
        # MedlinePlus search
        candidates.append((f"https://medlineplus.gov/search.html?query={q_encoded}", "MedlinePlus"))

        # --- DailyMed (FDA drug labels) ---
        candidates.append(
            (
                f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query={q_encoded}",
                "DailyMed",
            )
        )

        # --- Mayo Clinic ---
        candidates.append(
            (f"https://www.mayoclinic.org/search/search-results?q={q_encoded}", "Mayo Clinic")
        )
        # Try direct Mayo topic pages for each keyword
        for word in words:
            candidates.append(
                (
                    f"https://www.mayoclinic.org/diseases-conditions/{word}/symptoms-causes/syc-20300000",
                    "Mayo Clinic",
                )
            )

        # --- CDC ---
        candidates.append(
            (f"https://search.cdc.gov/search/?query={q_encoded}&affiliate=cdc-main", "CDC")
        )

        # --- WHO ---
        candidates.append((f"https://www.who.int/search?q={q_encoded}", "WHO"))

    elif category == "vet":
        # --- Merck Veterinary Manual ---
        # Map common animal keywords to Merck owner-page prefixes.
        # Focused on dog-owners (primary user interest); exotic animals included
        # for completeness but cat/horse owners omitted per user preference.
        _MERCK_ANIMAL_MAP = {
            "dog": "dog-owners",
            "dogs": "dog-owners",
            "rabbit": "rabbit-owners",
            "rabbits": "rabbit-owners",
            "bird": "bird-owners",
            "birds": "bird-owners",
            "reptile": "reptile-owners",
            "reptiles": "reptile-owners",
            "guinea": "guinea-pig-owners",
            "pig": "guinea-pig-owners",
            "ferret": "ferret-owners",
            "ferrets": "ferret-owners",
        }

        # Map common condition keywords to Merck section paths
        # Only high-confidence mappings that have verified pages are listed.
        _MERCK_CONDITION_SECTIONS = {
            # Digestive
            "vomiting": "digestive-disorders-of-{animal}s/vomiting-in-{animal}s",
            "diarrhea": "digestive-disorders-of-{animal}s/diarrhea-in-{animal}s",
            "constipation": "digestive-disorders-of-{animal}s/constipation-in-{animal}s",
            "pancreatitis": "digestive-disorders-of-{animal}s/pancreatitis-and-other-disorders-of-the-pancreas-in-{animal}s",
            "bloat": "digestive-disorders-of-{animal}s/bloat-in-{animal}s",
            "gi": "digestive-disorders-of-{animal}s",
            "digestive": "digestive-disorders-of-{animal}s",
            "stomach": "digestive-disorders-of-{animal}s/disorders-of-the-stomach-and-intestines-in-{animal}s",
            "colic": "digestive-disorders-of-{animal}s/colic-in-{animal}s",
            # Skin
            "skin": "skin-disorders-of-{animal}s",
            "itching": "skin-disorders-of-{animal}s/itching-and-scratching-in-{animal}s",
            "allergy": "skin-disorders-of-{animal}s/allergies-in-{animal}s",
            "fleas": "skin-disorders-of-{animal}s/fleas-in-{animal}s",
            "mange": "skin-disorders-of-{animal}s/mange-in-{animal}s",
            # Ear
            "ear": "ear-disorders-of-{animal}s",
            "ear infection": "ear-disorders-of-{animal}s/ear-infections-in-{animal}s",
            # Eye
            "eye": "eye-disorders-of-{animal}s",
            "cataract": "eye-disorders-of-{animal}s/cataracts-in-{animal}s",
            # Heart
            "heart": "heart-and-blood-vessel-disorders-of-{animal}s",
            "heartworm": "heart-and-blood-vessel-disorders-of-{animal}s/heartworm-disease-in-{animal}s",
            # Respiratory
            "cough": "lung-and-airway-disorders-of-{animal}s/coughing-in-{animal}s",
            "kennel": "lung-and-airway-disorders-of-{animal}s/kennel-cough-in-{animal}s",
            "respiratory": "lung-and-airway-disorders-of-{animal}s",
            # Urinary
            "kidney": "kidney-and-urinary-tract-disorders-of-{animal}s",
            "urinary": "kidney-and-urinary-tract-disorders-of-{animal}s",
            "bladder": "kidney-and-urinary-tract-disorders-of-{animal}s/bladder-stones-in-{animal}s",
            # Reproductive
            "pregnant": "reproductive-disorders-of-{animal}s",
            "pregnancy": "reproductive-disorders-of-{animal}s",
            "spay": "reproductive-disorders-of-{animal}s/spaying-in-{animal}s",
            "neuter": "reproductive-disorders-of-{animal}s/neutering-in-{animal}s",
            # Behavioral / general
            "anxiety": "behavior-of-{animal}s/behavior-problems-in-{animal}s",
            "seizure": "brain-spinal-cord-and-nerve-disorders-of-{animal}s/seizures-in-{animal}s",
            "paralysis": "brain-spinal-cord-and-nerve-disorders-of-{animal}s/leg-paralysis-in-{animal}s",
            "lameness": "bone-joint-and-muscle-disorders-of-{animal}s/lameness-in-{animal}s",
            "arthritis": "bone-joint-and-muscle-disorders-of-{animal}s/osteoarthritis-degenerative-joint-disease",
            "hip": "bone-joint-and-muscle-disorders-of-{animal}s/hip-dysplasia",
            "diabetes": "hormonal-disorders-of-{animal}s/diabetes-mellitus-in-{animal}s",
            "thyroid": "hormonal-disorders-of-{animal}s/thyroid-disorders-in-{animal}s",
            "obesity": "metabolic-disorders-of-{animal}s/obesity-in-{animal}s",
            "poison": "disorders-affecting-multiple-body-systems-of-{animal}s/poisoning-in-{animal}s",
            "toxin": "disorders-affecting-multiple-body-systems-of-{animal}s/poisoning-in-{animal}s",
            "heat": "disorders-affecting-multiple-body-systems-of-{animal}s/heat-stroke-in-{animal}s",
            "rabies": "infectious-diseases-of-{animal}s/rabies-in-{animal}s",
            "parvo": "infectious-diseases-of-{animal}s/parvovirus-in-{animal}s",
            "distemper": "infectious-diseases-of-{animal}s/distemper-in-{animal}s",
            "leptospirosis": "infectious-diseases-of-{animal}s/leptospirosis-in-{animal}s",
            "lyme": "infectious-diseases-of-{animal}s/lyme-disease-in-{animal}s",
            "tick": "infectious-diseases-of-{animal}s/tick-borne-diseases-in-{animal}s",
            "anemia": "blood-disorders-of-{animal}s/anemia-in-{animal}s",
            "cancer": "cancer-and-tumors-of-{animal}s",
            "tumor": "cancer-and-tumors-of-{animal}s",
        }

        # Build high-confidence Merck direct URLs from condition + animal mapping
        detected_animal = None
        for w in words:
            if w in _MERCK_ANIMAL_MAP:
                detected_animal = _MERCK_ANIMAL_MAP[w]
                break

        if detected_animal:
            animal_token = detected_animal.replace("-owners", "")
            # Owner landing page
            candidates.append(
                (f"https://www.merckvetmanual.com/{detected_animal}", "Merck Veterinary Manual")
            )
            # Condition-specific pages (only if both condition and animal known)
            for w in words:
                if w in _MERCK_CONDITION_SECTIONS:
                    section = _MERCK_CONDITION_SECTIONS[w].format(animal=animal_token)
                    candidates.append(
                        (
                            f"https://www.merckvetmanual.com/{detected_animal}/{section}",
                            "Merck Veterinary Manual",
                        )
                    )
            # Two-word condition phrases (e.g., "ear infection")
            for i in range(len(words) - 1):
                phrase = words[i] + " " + words[i + 1]
                if phrase in _MERCK_CONDITION_SECTIONS:
                    section = _MERCK_CONDITION_SECTIONS[phrase].format(animal=animal_token)
                    candidates.append(
                        (
                            f"https://www.merckvetmanual.com/{detected_animal}/{section}",
                            "Merck Veterinary Manual",
                        )
                    )

        # Merck search (homepage with query param)
        candidates.append(
            (f"https://www.merckvetmanual.com/?q={q_encoded}", "Merck Veterinary Manual")
        )
        # Merck home page as last resort
        candidates.append(("https://www.merckvetmanual.com/home", "Merck Veterinary Manual"))

        # --- VCA Hospitals ---
        # Try direct "know-your-pet" topic URLs for common conditions
        for word in words:
            candidates.append(
                (f"https://vcahospitals.com/know-your-pet/{word}-in-dogs", "VCA Hospitals")
            )
            candidates.append(
                (f"https://vcahospitals.com/know-your-pet/{word}-in-cats", "VCA Hospitals")
            )
        # VCA search
        candidates.append((f"https://vcahospitals.com/search?query={q_encoded}", "VCA Hospitals"))

        # --- AVMA ---
        candidates.append(("https://www.avma.org/resources-tools/pet-owners/petcare", "AVMA"))

    for url, name in candidates:
        try:
            content = extract_webpage(url, max_chars=2500, timeout=15)
            # Reject "sorry" / error / redirect pages
            if not content or len(content) <= 300:
                continue
            lower = content.lower()
            if any(
                bad in lower
                for bad in ["we're sorry", "page not found", "404", "sorrypages", "no results"]
            ):
                continue
            # Reject table-of-contents / navigation-only landing pages
            if not _is_substantive_content(content):
                continue
            return content, name
        except Exception:
            continue

    return None


def _trusted_metadata(
    *,
    answer_basis: str,
    live_fetch_status: str,
    confidence: str,
    degraded_reason: str = "",
    fallback_telemetry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "ANSWER_BASIS": answer_basis,
        "LIVE_FETCH_STATUS": live_fetch_status,
        "CONFIDENCE": confidence,
        "DEGRADED_REASON": degraded_reason,
    }
    if fallback_telemetry:
        meta.update(fallback_telemetry)
    return meta


def _with_trusted_metadata(
    content: str,
    *,
    include_metadata: bool,
    answer_basis: str,
    live_fetch_status: str,
    confidence: str,
    degraded_reason: str = "",
    fallback_telemetry: dict[str, Any] | None = None,
) -> str | tuple[str, dict[str, Any]]:
    metadata = _trusted_metadata(
        answer_basis=answer_basis,
        live_fetch_status=live_fetch_status,
        confidence=confidence,
        degraded_reason=degraded_reason,
        fallback_telemetry=fallback_telemetry,
    )
    if include_metadata:
        return content, metadata
    return content


# Stop words for relevance checking — includes common auxiliaries and animal names
# because veterinary sources are inherently about dogs/cats.
_RELEVANCE_STOP_WORDS: set[str] = {
    "the",
    "and",
    "are",
    "for",
    "dogs",
    "dog",
    "cats",
    "cat",
    "puppy",
    "puppies",
    "what",
    "how",
    "when",
    "where",
    "why",
    "who",
    "which",
    "this",
    "that",
    "these",
    "those",
    "with",
    "from",
    "have",
    "has",
    "had",
    "was",
    "were",
    "been",
    "being",
    "will",
    "would",
    "could",
    "should",
    "may",
    "might",
    "can",
    "about",
    "into",
    "over",
    "under",
    "again",
    "further",
    "then",
    "once",
    "here",
    "there",
    "all",
    "any",
    "both",
    "each",
    "few",
    "more",
    "most",
    "other",
    "some",
    "such",
    "only",
    "own",
    "same",
    "so",
    "than",
    "too",
    "very",
    "just",
    "now",
    "get",
    "you",
    "your",
    "his",
    "her",
    "its",
    "our",
    "their",
    "them",
    "they",
    "she",
    "he",
    "we",
    "us",
    "me",
    "my",
    "i",
    "am",
    "is",
    "are",
    "was",
    "be",
    "being",
    "do",
    "does",
    "did",
    "done",
    "a",
    "an",
    "to",
    "of",
    "in",
    "on",
    "at",
    "by",
    "as",
    "or",
    "if",
    "it",
    "not",
    "no",
    "but",
    "up",
    "out",
    "down",
    "off",
    "healthy",
    "safe",
    "good",
    "bad",
    "best",
    "better",
    "well",
    "animal",
    "animals",
    "pet",
    "pets",
    "owner",
    "owners",
    "tell",
    "know",
    "like",
    "need",
    "should",
    "use",
    "using",
}


def _is_content_relevant(question: str, content: str, min_matches: int = 1) -> bool:
    """Return True if content contains at least min_matches query keywords.

    Prevents returning unrelated article snippets when a search engine or
    landing page returns content that is substantive but off-topic.
    """
    content_lower = content.lower()
    words = re.findall(r"[a-z]{3,}", question.lower())
    keywords = [w for w in words if w not in _RELEVANCE_STOP_WORDS]
    if not keywords:
        # Question has no discernible keywords — be permissive
        return True
    matches = sum(1 for kw in keywords if kw in content_lower)
    return matches >= min_matches


def _format_medical_response(
    domains: list[str],
    question: str,
    include_metadata: bool = False,
) -> str | tuple[str, dict[str, str]]:
    """Format medical response based on query type."""
    q_lower = question.lower()
    deduped = _dedupe_domains(domains)
    degraded_reason = "search_no_results"
    live_fetch_status = "failed"

    # Try to fetch live content from trusted medical sources
    search_results = _search_restricted(question, deduped, max_results=3)
    extract_telemetry: dict[str, Any] = {}
    if search_results:
        degraded_reason = "article_fetch_failed"
        top_url = search_results[0].get("url", "")
        top_title = search_results[0].get("title", "")
        if top_url:
            content = _fetch_article_content(
                top_url, max_chars=5000, _telemetry_out=extract_telemetry
            )
            if (
                content
                and len(content) > 200
                and _is_substantive_content(content)
                and _is_content_relevant(question, content)
            ):
                lines = [
                    f"Source: {top_title or top_url}",
                    "",
                    content,
                    "",
                    "Consult a healthcare professional for personal medical advice.",
                ]
                return _with_trusted_metadata(
                    "\n".join(lines),
                    include_metadata=include_metadata,
                    answer_basis="live_trusted_source",
                    live_fetch_status="success",
                    confidence="normal",
                    fallback_telemetry=extract_telemetry if extract_telemetry else None,
                )
            if not HAS_WEB_EXTRACT:
                live_fetch_status = "unavailable"
                degraded_reason = "extractor_unavailable"
    else:
        # SearXNG search failed — try direct fetch from known trusted sources
        direct = _try_direct_fetch(question, "medical")
        if direct:
            content, source_name = direct
            if _is_content_relevant(question, content):
                lines = [
                    f"Source: {source_name}",
                    "",
                    content,
                    "",
                    "Consult a healthcare professional for personal medical advice.",
                ]
                return _with_trusted_metadata(
                    "\n".join(lines),
                    include_metadata=include_metadata,
                    answer_basis="live_trusted_source",
                    live_fetch_status="success",
                    confidence="normal",
                )

    # Check for specific medication
    medication_match = re.search(
        r"\b(amoxicillin|aspirin|tadalafil|cialis|viagra|metformin|insulin|ibuprofen|acetaminophen|paracetamol)\b",
        q_lower,
    )

    if medication_match:
        medication = medication_match.group(1).lower()

        # Dose query
        if any(word in q_lower for word in ["dose", "dosage", "how much", "how many"]):
            return _with_trusted_metadata(
                f"Standard dosing for {medication} varies by indication and patient factors. "
                f"Consult a clinician or pharmacist for personalized dosing guidance.\n\n"
                f"Trusted medical sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
                include_metadata=include_metadata,
                answer_basis="trusted_domain_fallback",
                live_fetch_status=live_fetch_status,
                confidence="limited",
                degraded_reason=degraded_reason,
            )

        # What is / usage query
        if any(phrase in q_lower for phrase in ["what is", "what's", "used for", "what does"]):
            return _with_trusted_metadata(
                f"{medication.capitalize()} is a medication covered by trusted medical sources. "
                f"Use those sources for official indication, dosing, and safety details. "
                f"Do not start, stop, or change medication without clinician guidance.\n\n"
                f"Trusted medical sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
                include_metadata=include_metadata,
                answer_basis="trusted_domain_fallback",
                live_fetch_status=live_fetch_status,
                confidence="limited",
                degraded_reason=degraded_reason,
            )

    # Generic medical response
    return _with_trusted_metadata(
        "Medical information is available from trusted sources. "
        "Consult a healthcare professional for personal medical advice.\n\n"
        "Trusted medical sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
        include_metadata=include_metadata,
        answer_basis="trusted_domain_fallback",
        live_fetch_status=live_fetch_status,
        confidence="limited",
        degraded_reason=degraded_reason,
    )


def _format_finance_response(
    domains: list[str],
    question: str,
    include_metadata: bool = False,
) -> str | tuple[str, dict[str, str]]:
    """Format finance response based on query type."""
    q_lower = question.lower()
    deduped = _dedupe_domains(domains)

    # Currency/FX queries
    if any(word in q_lower for word in ["exchange rate", "currency", "usd", "ils", "eur", "gbp"]):
        return _with_trusted_metadata(
            "Currency exchange rates fluctuate continuously. "
            "Check current rates from official financial sources.\n\n"
            "Trusted financial sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
            include_metadata=include_metadata,
            answer_basis="static_template",
            live_fetch_status="skipped",
            confidence="limited",
            degraded_reason="static_finance_template",
        )

    # Generic finance response
    return _with_trusted_metadata(
        "Financial information is available from trusted sources. "
        "Consult a financial advisor for personal investment decisions.\n\n"
        "Trusted financial sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
        include_metadata=include_metadata,
        answer_basis="static_template",
        live_fetch_status="skipped",
        confidence="limited",
        degraded_reason="static_finance_template",
    )


def _format_vet_response(
    domains: list[str],
    question: str,
    include_metadata: bool = False,
) -> str | tuple[str, dict[str, str]]:
    """Format veterinary response based on query type."""
    q_lower = question.lower()
    deduped = _dedupe_domains(domains)

    # Emergency / symptom queries — always prepend emergency guidance
    emergency_keywords = [
        "vomiting",
        "diarrhea",
        "seizure",
        "bleeding",
        "collapse",
        "unconscious",
        "not breathing",
        "choking",
        "bloat",
        "poison",
        "toxin",
        "toxic",
        "emergency",
        "urgent",
    ]
    is_emergency = any(word in q_lower for word in emergency_keywords)
    degraded_reason = "search_no_results"
    live_fetch_status = "failed"

    # Try to fetch live content from trusted veterinary sources
    search_results = _search_restricted(question, deduped, max_results=3)
    extract_telemetry: dict[str, Any] = {}
    if search_results:
        degraded_reason = "article_fetch_failed"
        top_url = search_results[0].get("url", "")
        top_title = search_results[0].get("title", "")
        if top_url:
            content = _fetch_article_content(
                top_url, max_chars=5000, _telemetry_out=extract_telemetry
            )
            if (
                content
                and len(content) > 200
                and _is_substantive_content(content)
                and _is_content_relevant(question, content)
            ):
                lines = []
                if is_emergency:
                    lines.append(
                        "This may be a veterinary emergency. Contact a veterinarian or emergency animal hospital immediately."
                    )
                    lines.append("")
                lines.append(f"Source: {top_title or top_url}")
                lines.append("")
                lines.append(content)
                lines.append("")
                lines.append("Always consult a licensed veterinarian for diagnosis and treatment.")
                return _with_trusted_metadata(
                    "\n".join(lines),
                    include_metadata=include_metadata,
                    answer_basis="live_trusted_source",
                    live_fetch_status="success",
                    confidence="normal",
                    fallback_telemetry=extract_telemetry if extract_telemetry else None,
                )
            if not HAS_WEB_EXTRACT:
                live_fetch_status = "unavailable"
                degraded_reason = "extractor_unavailable"
    else:
        # SearXNG search failed — try direct fetch from known trusted sources
        direct = _try_direct_fetch(question, "vet")
        if direct:
            content, source_name = direct
            if _is_content_relevant(question, content):
                lines = []
                if is_emergency:
                    lines.append(
                        "This may be a veterinary emergency. Contact a veterinarian or emergency animal hospital immediately."
                    )
                    lines.append("")
                lines.append(f"Source: {source_name}")
                lines.append("")
                lines.append(content)
                lines.append("")
                lines.append("Always consult a licensed veterinarian for diagnosis and treatment.")
                return _with_trusted_metadata(
                    "\n".join(lines),
                    include_metadata=include_metadata,
                    answer_basis="live_trusted_source",
                    live_fetch_status="success",
                    confidence="normal",
                )

    if is_emergency:
        return _with_trusted_metadata(
            "This may be a veterinary emergency. "
            "Contact a veterinarian or emergency animal hospital immediately.\n\n"
            "Trusted veterinary sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
            include_metadata=include_metadata,
            answer_basis="trusted_domain_fallback",
            live_fetch_status=live_fetch_status,
            confidence="limited",
            degraded_reason=degraded_reason,
        )

    # Generic veterinary response
    return _with_trusted_metadata(
        "Veterinary information is available from trusted animal-health sources. "
        "Always consult a licensed veterinarian for diagnosis and treatment.\n\n"
        "Trusted veterinary sources:\n" + "\n".join(f"- {src}" for src in deduped[:6]),
        include_metadata=include_metadata,
        answer_basis="trusted_domain_fallback",
        live_fetch_status=live_fetch_status,
        confidence="limited",
        degraded_reason=degraded_reason,
    )


def _format_news_response_with_headlines(
    items: list[dict[str, str]],
    region: str,
    include_metadata: bool = False,
) -> str | tuple[str, dict[str, str]]:
    """Format news response with actual headlines."""
    if region == "news_israel":
        region_name = "Israel"
    elif region == "news_australia":
        region_name = "Australia"
    else:
        region_name = "international"

    if not items:
        # Fallback to source list if no headlines fetched
        domains = _load_domain_allowlist(region)
        deduped = _dedupe_domains(domains)
        lines = [
            f"Current {region_name} news sources are available.",
            "",
            "Trusted news sources:",
        ]
        for src in deduped[:8]:
            lines.append(f"- {src}")
        lines.append("")
        lines.append("Note: Live headlines temporarily unavailable. Visit sources directly.")
        return _with_trusted_metadata(
            "\n".join(lines),
            include_metadata=include_metadata,
            answer_basis="trusted_domain_fallback",
            live_fetch_status="failed",
            confidence="limited",
            degraded_reason="rss_headlines_unavailable",
        )

    lines = [f"Latest {region_name} news headlines:", ""]

    for item in items:
        title = item.get("title", "")
        source = item.get("source", "")
        desc = item.get("desc", "")

        if title:
            lines.append(f"• {title}")
            if source:
                lines.append(f"  Source: {source}")
            if desc and len(desc) > 20:
                # Use full description (was truncated to 120 chars, now allowing full text)
                lines.append(f"  {desc}")
            lines.append("")

    return _with_trusted_metadata(
        "\n".join(lines),
        include_metadata=include_metadata,
        answer_basis="live_trusted_source",
        live_fetch_status="success",
        confidence="normal",
    )


def fetch_context(
    question: str, intent_family: str = "", evidence_reason: str = ""
) -> dict[str, Any] | None:
    """
    Main entry point to fetch trusted context for a question.
    Returns None if not applicable (should fall back to other providers).
    """
    # If the classifier already identified this as medical/vet, trust it
    # and bypass keyword matching (which often misses symptom/disease names).
    if evidence_reason in ("medical_context", "medical_body_symptom"):
        category, sub_type = "medical", "medical"
    elif evidence_reason == "veterinary_context":
        category, sub_type = "vet", "vet"
    else:
        category, sub_type = _is_category_supported(intent_family, question)
    if not category:
        return None

    domains = _load_domain_allowlist(category)
    if not domains:
        return None

    # Format response based on category
    if sub_type == "news":
        # Try to fetch actual RSS headlines
        headlines = _fetch_news_headlines(category, max_items=8)
        content, metadata = _format_news_response_with_headlines(
            headlines, category, include_metadata=True
        )
    elif sub_type == "medical":
        content, metadata = _format_medical_response(domains, question, include_metadata=True)
    elif sub_type == "finance":
        content, metadata = _format_finance_response(domains, question, include_metadata=True)
    elif sub_type == "vet":
        content, metadata = _format_vet_response(domains, question, include_metadata=True)
    else:
        content = "Information available from trusted sources."
        metadata = _trusted_metadata(
            answer_basis="static_template",
            live_fetch_status="skipped",
            confidence="limited",
            degraded_reason="static_trusted_template",
        )

    return {
        "ok": True,
        "provider": "trusted",
        "category": category,
        "content": content,
        "sources": _dedupe_domains(domains)[:10],
        "bounded_response": True,
        **metadata,
    }


def main() -> int:
    if len(sys.argv) < 2:
        return _print_fail("missing_question")

    question = " ".join(sys.argv[1:]).strip()
    if not question:
        return _print_fail("empty_question")

    intent_family = os.environ.get("LUCY_INTENT_FAMILY", "")

    result = fetch_context(question, intent_family)
    if result is None:
        return _print_fail("not_applicable")

    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
