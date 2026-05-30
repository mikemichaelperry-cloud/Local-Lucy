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

import json
import os
import re
import sys
import subprocess
import xml.etree.ElementTree as ET
import html
from pathlib import Path
from typing import Any

# Web extraction adapter (webclaw → fallback)
sys.path.insert(0, str(Path(__file__).resolve().parent / "internet"))
try:
    from web_extract import extract_webpage
    HAS_WEB_EXTRACT = True
except Exception:
    HAS_WEB_EXTRACT = False


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
        for prefix in ['www.', 'feeds.', 'rss.']:
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _detect_news_region(question: str) -> str:
    """Detect which news region the query is asking about."""
    q_lower = question.lower()
    
    # Israel-specific keywords
    israel_keywords = [
        'israel', 'israeli', 'gaza', 'idf', 'west bank', 'jerusalem', 
        'tel aviv', 'netanyahu', 'hamas', 'hezbollah', 'knesset',
        'haaretz', 'ynet', 'jpost'
    ]
    if any(kw in q_lower for kw in israel_keywords):
        return "news_israel"
    
    # Australia-specific keywords
    au_keywords = [
        'australia', 'australian', 'canberra', 'sydney', 'melbourne',
        'brisbane', 'perth', 'adelaide', 'abc.net.au', 'sbs.com.au'
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
        'veterinary', 'vet', 'veterinarian', 'animal health',
        'dog', 'dogs', 'puppy', 'puppies',
        'cat', 'cats', 'kitten', 'kittens',
        'pet', 'pets', 'parvovirus', 'parvo',
        'rabies', 'distemper', 'bordetella', 'leptospirosis',
        'heartworm', 'flea', 'tick', 'tapeworm', 'roundworm',
        'spay', 'neuter', 'neutering', 'spaying',
        'kennel cough', 'hip dysplasia', 'bloat', 'gastric dilatation',
        'pancreatitis', 'diabetes', 'hyperthyroidism', 'hypothyroidism',
        'renal failure', 'kidney disease', 'liver disease',
        'arthritis', 'osteoarthritis', 'dysplasia',
        'vaccination', 'vaccine', 'deworm', 'deworming',
        'grooming', 'dental', 'teeth cleaning',
        'merck vet', 'avma', 'vca', 'aaha', 'aspca',
    ]
    if any(kw in q_lower for kw in veterinary_keywords):
        return ("vet", "vet")

    # Check for medical queries
    medical_keywords = [
        'medical', 'medication', 'medicine', 'drug', 'dose', 'dosage',
        'side effect', 'interaction', 'contraindication', 'health',
        'prescription', 'treatment', 'amoxicillin', 'aspirin', 
        'tadalafil', 'cialis', 'viagra', 'metformin', 'insulin',
        'antibiotic', 'pharmacy', 'pharmacist', 'doctor', 'physician'
    ]
    if any(kw in q_lower for kw in medical_keywords):
        return ("medical", "medical")
    
    # Check for finance queries
    finance_keywords = [
        'finance', 'stock', 'market', 'economy', 'currency',
        'exchange rate', 'investment', 'financial'
    ]
    if any(kw in q_lower for kw in finance_keywords):
        return ("finance", "finance")
    
    # Check for news queries
    news_keywords = ['news', 'headline', 'headlines', 'breaking', 'latest news', 'world news']
    if any(kw in q_lower for kw in news_keywords):
        region = _detect_news_region(question)
        return (region, "news")
    
    return (None, None)


def _fetch_rss(url: str, timeout: int = 30) -> str | None:
    """Fetch RSS content from URL."""
    root = _get_root()
    gate_fetch = root / "tools" / "internet" / "run_fetch_with_gate.sh"
    
    try:
        result = subprocess.run(
            [str(gate_fetch), url],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, Exception):
        pass
    return None


def _parse_rss(xml_content: str) -> list[dict[str, str]]:
    """Parse RSS/Atom XML and extract items."""
    items = []
    if not xml_content or not xml_content.strip():
        return items
    
    # Check if it looks like RSS/Atom
    if not re.search(r'<(rss|feed|channel)', xml_content, re.I):
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
            desc = re.sub(r'<[^>]+>', ' ', desc)
            desc = re.sub(r'\s+', ' ', desc).strip()
        
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


def _search_restricted(query: str, domains: list[str], max_results: int = 3) -> list[dict[str, str]]:
    """Search SearXNG restricted to a domain allowlist."""
    root = _get_root()
    search_script = root / "tools" / "internet" / "search_web.py"
    if not search_script.exists():
        return []
    try:
        payload = json.dumps({"query": query, "max_results": max_results, "domains": domains})
        result = subprocess.run(
            [str(sys.executable), str(search_script)],
            input=payload,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            return data.get("results", [])
    except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        pass
    return []


def _fetch_article_content(url: str, max_chars: int = 5000) -> str | None:
    """Fetch and extract clean text from a trusted URL."""
    if not HAS_WEB_EXTRACT:
        return None
    try:
        return extract_webpage(url, max_chars=max_chars, timeout=15)
    except Exception:
        return None


def _try_direct_fetch(question: str, category: str) -> tuple[str, str] | None:
    """When SearXNG search fails, try fetching directly from trusted sources.

    Returns (content, source_name) or None if all fail.
    """
    if not HAS_WEB_EXTRACT:
        return None

    q_lower = question.lower()
    q_encoded = question.replace(" ", "%20")
    q_dashed = q_lower.replace(" ", "-")

    # Extract likely topic keywords from the query
    stop_words = {"what", "are", "the", "symptoms", "of", "is", "a", "an",
                  "my", "i", "have", "do", "does", "how", "why", "when",
                  "where", "who", "can", "should", "would", "could", "will",
                  "treatment", "for", "cause", "causes", "signs", "diagnosis",
                  "side", "effects", "definition", "explain", "tell", "about"}
    words = [w for w in re.findall(r'[a-z]+', q_lower) if w not in stop_words and len(w) > 2]

    candidates: list[tuple[str, str]] = []

    if category == "medical":
        # --- MedlinePlus (primary US gov health source) ---
        for word in words:
            candidates.append(
                (f"https://medlineplus.gov/{word}.html", "MedlinePlus")
            )
        for word in words:
            candidates.append(
                (f"https://medlineplus.gov/ency/article/{word}.htm", "MedlinePlus")
            )
        # MedlinePlus search
        candidates.append(
            (f"https://medlineplus.gov/search.html?query={q_encoded}", "MedlinePlus")
        )

        # --- DailyMed (FDA drug labels) ---
        candidates.append(
            (f"https://dailymed.nlm.nih.gov/dailymed/search.cfm?labeltype=all&query={q_encoded}", "DailyMed")
        )

        # --- Mayo Clinic ---
        candidates.append(
            (f"https://www.mayoclinic.org/search/search-results?q={q_encoded}", "Mayo Clinic")
        )
        # Try direct Mayo topic pages for each keyword
        for word in words:
            candidates.append(
                (f"https://www.mayoclinic.org/diseases-conditions/{word}/symptoms-causes/syc-20300000", "Mayo Clinic")
            )

        # --- CDC ---
        candidates.append(
            (f"https://search.cdc.gov/search/?query={q_encoded}&affiliate=cdc-main", "CDC")
        )

        # --- WHO ---
        candidates.append(
            (f"https://www.who.int/search?q={q_encoded}", "WHO")
        )

    elif category == "vet":
        # --- Merck Veterinary Manual ---
        # Try pet-owner landing pages based on animal keywords
        animal_map = {
            "dog": "dog-owners",
            "dogs": "dog-owners",
            "cat": "cat-owners",
            "cats": "cat-owners",
            "horse": "horse-owners",
            "horses": "horse-owners",
            "rabbit": "exotic-animals",
            "rabbits": "exotic-animals",
            "bird": "exotic-animals",
            "birds": "exotic-animals",
            "reptile": "exotic-animals",
            "reptiles": "exotic-animals",
        }
        for word in words:
            if word in animal_map:
                candidates.append(
                    (f"https://www.merckvetmanual.com/{animal_map[word]}", "Merck Veterinary Manual")
                )
        # Merck search page
        candidates.append(
            (f"https://www.merckvetmanual.com/search?query={q_encoded}", "Merck Veterinary Manual")
        )
        # Merck home page as last resort
        candidates.append(
            ("https://www.merckvetmanual.com/home", "Merck Veterinary Manual")
        )

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
        candidates.append(
            (f"https://vcahospitals.com/search?query={q_encoded}", "VCA Hospitals")
        )

        # --- AVMA ---
        candidates.append(
            ("https://www.avma.org/resources-tools/pet-owners/petcare", "AVMA")
        )

    for url, name in candidates:
        try:
            content = extract_webpage(url, max_chars=4000, timeout=15)
            # Reject "sorry" / error / redirect pages
            if content and len(content) > 300:
                lower = content.lower()
                if any(bad in lower for bad in ["we're sorry", "page not found", "404", "sorrypages", "no results"]):
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
) -> dict[str, str]:
    return {
        "ANSWER_BASIS": answer_basis,
        "LIVE_FETCH_STATUS": live_fetch_status,
        "CONFIDENCE": confidence,
        "DEGRADED_REASON": degraded_reason,
    }


def _with_trusted_metadata(
    content: str,
    *,
    include_metadata: bool,
    answer_basis: str,
    live_fetch_status: str,
    confidence: str,
    degraded_reason: str = "",
) -> str | tuple[str, dict[str, str]]:
    metadata = _trusted_metadata(
        answer_basis=answer_basis,
        live_fetch_status=live_fetch_status,
        confidence=confidence,
        degraded_reason=degraded_reason,
    )
    if include_metadata:
        return content, metadata
    return content


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
    if search_results:
        degraded_reason = "article_fetch_failed"
        top_url = search_results[0].get("url", "")
        top_title = search_results[0].get("title", "")
        if top_url:
            content = _fetch_article_content(top_url, max_chars=5000)
            if content and len(content) > 200:
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
                )
            if not HAS_WEB_EXTRACT:
                live_fetch_status = "unavailable"
                degraded_reason = "extractor_unavailable"
    else:
        # SearXNG search failed — try direct fetch from known trusted sources
        direct = _try_direct_fetch(question, "medical")
        if direct:
            content, source_name = direct
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
        r'\b(amoxicillin|aspirin|tadalafil|cialis|viagra|metformin|insulin|ibuprofen|acetaminophen|paracetamol)\b',
        q_lower
    )

    if medication_match:
        medication = medication_match.group(1).lower()

        # Dose query
        if any(word in q_lower for word in ["dose", "dosage", "how much", "how many"]):
            return _with_trusted_metadata(
                f"Standard dosing for {medication} varies by indication and patient factors. "
                f"Consult a clinician or pharmacist for personalized dosing guidance.\n\n"
                f"Trusted medical sources:\n" +
                "\n".join(f"- {src}" for src in deduped[:6]),
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
                f"Trusted medical sources:\n" +
                "\n".join(f"- {src}" for src in deduped[:6]),
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
        f"Trusted medical sources:\n" +
        "\n".join(f"- {src}" for src in deduped[:6]),
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
            f"Trusted financial sources:\n" +
            "\n".join(f"- {src}" for src in deduped[:6]),
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
        f"Trusted financial sources:\n" +
        "\n".join(f"- {src}" for src in deduped[:6]),
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
    emergency_keywords = ['vomiting', 'diarrhea', 'seizure', 'bleeding', 'collapse',
                          'unconscious', 'not breathing', 'choking', 'bloat',
                          'poison', 'toxin', 'toxic', 'emergency', 'urgent']
    is_emergency = any(word in q_lower for word in emergency_keywords)
    degraded_reason = "search_no_results"
    live_fetch_status = "failed"

    # Try to fetch live content from trusted veterinary sources
    search_results = _search_restricted(question, deduped, max_results=3)
    if search_results:
        degraded_reason = "article_fetch_failed"
        top_url = search_results[0].get("url", "")
        top_title = search_results[0].get("title", "")
        if top_url:
            content = _fetch_article_content(top_url, max_chars=5000)
            if content and len(content) > 200:
                lines = []
                if is_emergency:
                    lines.append("This may be a veterinary emergency. Contact a veterinarian or emergency animal hospital immediately.")
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
                )
            if not HAS_WEB_EXTRACT:
                live_fetch_status = "unavailable"
                degraded_reason = "extractor_unavailable"
    else:
        # SearXNG search failed — try direct fetch from known trusted sources
        direct = _try_direct_fetch(question, "vet")
        if direct:
            content, source_name = direct
            lines = []
            if is_emergency:
                lines.append("This may be a veterinary emergency. Contact a veterinarian or emergency animal hospital immediately.")
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
            f"Trusted veterinary sources:\n" +
            "\n".join(f"- {src}" for src in deduped[:6]),
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
        f"Trusted veterinary sources:\n" +
        "\n".join(f"- {src}" for src in deduped[:6]),
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
        date = item.get("date", "")
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


def _is_complex_medical_query(question: str) -> bool:
    """
    Check if this is a complex medical query that needs LLM synthesis.
    
    Simple queries (like "what is tadalafil") can use generic templates.
    Complex queries (interactions, side effects, specific questions) need
    informative answers from LLM constrained to medical domains.
    """
    q_lower = question.lower()
    
    # Specific medication names indicate complex queries
    medication_names = [
        'tadalafil', 'cialis', 'viagra', 'sildenafil',
        'amoxicillin', 'aspirin', 'metformin', 'insulin',
        'ibuprofen', 'acetaminophen', 'paracetamol', 'advil',
        'warfarin', 'atorvastatin', 'lipitor', 'omeprazole'
    ]
    has_medication = any(med in q_lower for med in medication_names)
    
    # Complex query indicators
    complex_indicators = [
        'interaction', 'interact', 'grapefruit', 'alcohol', 
        'side effect', 'adverse', 'contraindication', 'warning',
        'can i', 'should i', 'is it safe', 'can you',
        'while taking', 'with', 'and', 'cause', 'risk'
    ]
    has_complex = any(ind in q_lower for ind in complex_indicators)
    
    # If it has a medication AND complex indicators, it's complex
    return has_medication and has_complex


def fetch_context(question: str, intent_family: str = "", evidence_reason: str = "") -> dict[str, Any] | None:
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
        content, metadata = _format_news_response_with_headlines(headlines, category, include_metadata=True)
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
