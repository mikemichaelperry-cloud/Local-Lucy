"""URL provenance and fetch validation types.

Separates fetchable URLs from arbitrary prompt text. Only URLs from
explicitly trusted provenances with syntactically valid HTTPS addresses
and explicit hostnames are allowed to be fetched.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse


class URLProvenance(Enum):
    """Origin classification for a candidate fetch URL."""

    USER_SUPPLIED = "user_supplied"
    SEARCH_RESULT = "search_result"
    TRUSTED_API = "trusted_api"
    TRUSTED_LINK = "trusted_link"
    PREDEFINED_ENDPOINT = "predefined_endpoint"
    INVENTED_KEYWORD = "invented_keyword"


@dataclass(frozen=True)
class FetchURL:
    """A validated, fetchable HTTPS URL with its provenance."""

    url: str
    provenance: URLProvenance


@dataclass(frozen=True)
class SearchQuery:
    """A free-text search query; not a fetchable URL."""

    text: str


# Provenances that are allowed to result in an actual HTTPS fetch.
_FETCHABLE_PROVENANCES = {
    URLProvenance.USER_SUPPLIED,
    URLProvenance.SEARCH_RESULT,
    URLProvenance.TRUSTED_API,
    URLProvenance.TRUSTED_LINK,
    URLProvenance.PREDEFINED_ENDPOINT,
}


def validate_fetch_url(url: str, provenance: URLProvenance | None) -> FetchURL | None:
    """Return a FetchURL only for allowed provenances with valid HTTPS URLs.

    Rejects INVENTED_KEYWORD and any URL that is not HTTPS or lacks an
    explicit hostname. Non-string input (e.g. a SearchQuery) is rejected.
    """
    if not isinstance(url, str):
        return None
    if provenance not in _FETCHABLE_PROVENANCES:
        return None

    parsed = urlparse(url)
    if parsed.scheme != "https":
        return None
    if not parsed.hostname:
        return None

    return FetchURL(url=url, provenance=provenance)
