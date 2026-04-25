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
    keymap_path = root / "config" / "evidence_keymap_v1.tsv"
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
    
    # Check for medical queries FIRST
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
    if intent_family == "current_evidence" or any(kw in q_lower for kw in news_keywords):
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


def _format_medical_response(domains: list[str], question: str) -> str:
    """Format medical response based on query type."""
    q_lower = question.lower()
    deduped = _dedupe_domains(domains)
    
    # Check for specific medication
    medication_match = re.search(
        r'\b(amoxicillin|aspirin|tadalafil|cialis|viagra|metformin|insulin|ibuprofen|acetaminophen|paracetamol)\b', 
        q_lower
    )
    
    if medication_match:
        medication = medication_match.group(1).lower()
        
        # Dose query
        if any(word in q_lower for word in ["dose", "dosage", "how much", "how many"]):
            return (
                f"Standard dosing for {medication} varies by indication and patient factors. "
                f"Consult a clinician or pharmacist for personalized dosing guidance.\n\n"
                f"Trusted medical sources:\n" +
                "\n".join(f"- {src}" for src in deduped[:6])
            )
        
        # What is / usage query
        if any(phrase in q_lower for phrase in ["what is", "what's", "used for", "what does"]):
            return (
                f"{medication.capitalize()} is a medication covered by trusted medical sources. "
                f"Use those sources for official indication, dosing, and safety details. "
                f"Do not start, stop, or change medication without clinician guidance.\n\n"
                f"Trusted medical sources:\n" +
                "\n".join(f"- {src}" for src in deduped[:6])
            )
    
    # Generic medical response
    return (
        "Medical information is available from trusted sources. "
        "Consult a healthcare professional for personal medical advice.\n\n"
        f"Trusted medical sources:\n" +
        "\n".join(f"- {src}" for src in deduped[:6])
    )


def _format_finance_response(domains: list[str], question: str) -> str:
    """Format finance response based on query type."""
    q_lower = question.lower()
    deduped = _dedupe_domains(domains)
    
    # Currency/FX queries
    if any(word in q_lower for word in ["exchange rate", "currency", "usd", "ils", "eur", "gbp"]):
        return (
            "Currency exchange rates fluctuate continuously. "
            "Check current rates from official financial sources.\n\n"
            f"Trusted financial sources:\n" +
            "\n".join(f"- {src}" for src in deduped[:6])
        )
    
    # Generic finance response
    return (
        "Financial information is available from trusted sources. "
        "Consult a financial advisor for personal investment decisions.\n\n"
        f"Trusted financial sources:\n" +
        "\n".join(f"- {src}" for src in deduped[:6])
    )


def _format_news_response_with_headlines(items: list[dict[str, str]], region: str) -> str:
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
        return "\n".join(lines)
    
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
    
    return "\n".join(lines)


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


def fetch_context(question: str, intent_family: str = "") -> dict[str, Any] | None:
    """
    Main entry point to fetch trusted context for a question.
    Returns None if not applicable (should fall back to other providers).
    """
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
        content = _format_news_response_with_headlines(headlines, category)
    elif sub_type == "medical":
        # For complex medical queries, return None to fall through to LLM
        # The LLM will be constrained to medical domains via allow_domains_file
        if _is_complex_medical_query(question):
            return None
        content = _format_medical_response(domains, question)
    elif sub_type == "finance":
        content = _format_finance_response(domains, question)
    else:
        content = "Information available from trusted sources."
    
    return {
        "ok": True,
        "provider": "trusted",
        "category": category,
        "content": content,
        "sources": _dedupe_domains(domains)[:10],
        "bounded_response": True,
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
