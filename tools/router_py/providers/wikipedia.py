"""Wikipedia response formatter."""

from typing import Any


def format_wikipedia_response(
    prompt: str,
    evidence: dict[str, Any] | None,
    context: dict[str, Any] | None = None,
) -> str:
    """Format Wikipedia evidence into a response with attribution."""
    if not evidence:
        return "No Wikipedia information available for this query."

    context_text = evidence.get("context", "")
    title = evidence.get("title", "")
    url = evidence.get("url", "")

    if not context_text:
        return "No information found on Wikipedia for this topic."

    response_parts = [context_text]
    if title or url:
        response_parts.append("\n\n---")
        if title:
            response_parts.append(f"Source: Wikipedia - {title}")
        if url:
            response_parts.append(f"Read more: {url}")

    return "\n".join(response_parts)
