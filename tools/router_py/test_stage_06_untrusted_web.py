#!/usr/bin/env python3
"""STAGE_06 untrusted-web security tests."""

from __future__ import annotations

from unittest.mock import patch

from router_py.escalation.fetcher import FetchResult, fetch_general_knowledge


def _fake_ddg_response(html: str) -> object:
    class FakeResponse:
        def read(self) -> bytes:
            return html.encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return FakeResponse()


def test_s06_uw_001_misinformation_domain_is_dropped():
    """S06-UW-001: DuckDuckGo result on a known misinformation domain is dropped."""
    html = """
    <html>
      <body>
        <div class="result">
          <a class="result__a" href="https://naturalnews.com/fake-article">Bad source</a>
          <a class="result__snippet">Snip</a>
          <a class="result__url" href="https://naturalnews.com/fake-article"></a>
        </div>
        <div class="result">
          <a class="result__a" href="https://example.gov/real-article">Good source</a>
          <a class="result__snippet">Real snippet</a>
          <a class="result__url" href="https://example.gov/real-article"></a>
        </div>
      </body>
    </html>
    """

    with patch(
        "router_py.escalation.fetcher.urllib.request.urlopen",
        return_value=_fake_ddg_response(html),
    ):
        result = fetch_general_knowledge("some query")

    assert isinstance(result, FetchResult)
    assert result.url == "https://example.gov/real-article"
    assert result.title == "Good source"
