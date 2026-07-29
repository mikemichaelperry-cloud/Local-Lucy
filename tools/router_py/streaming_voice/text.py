"""HTML stripping / TTS text cleaning helpers for streaming voice."""

from __future__ import annotations

import re


def _strip_html_for_tts(text: str) -> str:
    """Strip HTML tags from text for TTS synthesis."""

    if not text:
        return ""

    # Remove script and style elements
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)

    # Replace <br>, <p> etc with newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<p[^>]*>", "", text, flags=re.IGNORECASE)

    # Replace <li> with bullet points
    text = re.sub(r"<li[^>]*>", "\n• ", text, flags=re.IGNORECASE)
    text = re.sub(r"</li>", "", text, flags=re.IGNORECASE)

    # Replace <a href="...">text</a> with just "text"
    # Use lambda to avoid backreference interpretation issues with $ in content
    text = re.sub(
        r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>',
        lambda m: m.group(2),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"<a[^>]*>([^<]*)</a>", lambda m: m.group(1), text, flags=re.IGNORECASE)

    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Decode common HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&#x27;", "'")
    text = text.replace("&nbsp;", " ").replace("&#160;", " ")
    text = text.replace("&#8211;", "–").replace("&#8212;", "—")
    text = text.replace("&#8216;", "'").replace('&#8217;', "'")
    text = text.replace("&#8220;", '"').replace("&#8221;", '"')

    # Normalize whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


def _clean_for_tts(text: str) -> str:
    """Clean text for TTS - strip HTML, news first, sources at the end."""

    # Strip HTML tags first
    text = _strip_html_for_tts(text)

    # Remove common filler phrases at the start
    filler_patterns = [
        r"^(?:According to|Based on|From what I can see|It appears that)\s+",
        r"^(?:I found that|I see that|It seems)\s+",
    ]

    cleaned = text
    for pattern in filler_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)

    # Handle evidence source catalogs
    if "From current sources:" in cleaned or "Latest items extracted" in cleaned:
        lines = cleaned.split("\n")
        news_items = []
        sources = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Skip header/metadata lines
            if line.startswith("From current sources:"):
                continue
            if line.startswith("Latest items extracted"):
                continue
            if line.startswith("Key items:"):
                continue
            if line.startswith("Conflicts/uncertainty:"):
                continue
            if "None assessed" in line and len(line) < 50:
                continue

            # Extract news from bullet points
            if line.startswith("- ["):
                match = re.match(r"- \[([^\]]+)\]\s*(?:\([^)]+\))?:?\s*(.+)", line)
                if match:
                    source = match.group(1)
                    content = match.group(2)
                    content = re.sub(r"\s+", " ", content).strip()
                    if content:
                        news_items.append(content)
                        if source not in sources:
                            sources.append(source)
            elif line.startswith("• "):
                content = line[2:].strip()
                if content:
                    news_items.append(content)
            elif line.startswith("Sources:") or line.startswith("Source:"):
                # Skip source lines - extract domain for tracking but don't speak it
                if line.startswith("Source: "):
                    domain = line[8:].strip()
                    if domain and domain not in sources:
                        sources.append(domain)
                continue
            elif line.startswith("- ") and "." not in line:
                domain = line[2:].strip()
                if domain and " " not in domain and domain not in sources:
                    sources.append(domain)
            else:
                if len(line) > 10 and not line.startswith("-"):
                    news_items.append(line)

        result_parts = news_items
        # Sources intentionally omitted from TTS - only show in display text
        # if sources:
        #     result_parts.append(f"Sources: {', '.join(sources)}")

        cleaned = ". ".join(result_parts)

    # Remove evidence disabled messages
    cleaned = re.sub(
        r"Evidence disabled by operator control\.?\s*", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"Enable evidence to allow evidence routes\.?\s*", "", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"Best-effort recovery \(not source-backed answer\):\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"From this unverified background,\s*", "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()
