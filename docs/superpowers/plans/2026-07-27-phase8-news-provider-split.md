# Phase 8 — Split `tools/router_py/news_provider.py`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tools/router_py/news_provider.py` into a focused `tools/router_py/news/` package and migrate callers, preserving behavior.

**Architecture:** Move the shared `NewsResult` dataclass to `news/models.py`, utility helpers to `news/utils.py`, the RSS provider to `news/rss.py`, the NewsAPI provider to `news/api.py`, and the unified `NewsProvider` plus `fetch_latest_news` to `news/provider.py`. Expose the public API through `news/__init__.py`. Migrate direct callers to import from `router_py.news`. Delete the old monolithic module after callers are migrated.

**Tech Stack:** Python 3, pytest, aiohttp, ruff, git

## Global Constraints

- Preserve all existing behavior; no functional changes.
- Remove `tools/router_py/news_provider.py` only after callers are migrated.
- Run `./scripts/run-fast-tests.sh` (the fast default suite) after each task; no regressions allowed.
- Run `ruff check tools/router_py/news/` after code changes.
- Commit after each task.
- Do not touch modules outside `news_provider.py` and its direct callers.
- Keep the `.env` loading side effect so `NEWSAPI_API_KEY` is still discovered on import.

---

### Task 1: Add characterization tests for `news_provider`

**Files:**
- Create: `tools/router_py/test_news_provider_characterization.py`

**Interfaces:**
- Consumes: existing `router_py.news_provider.NewsResult`, `NewsProvider`, `RSSNewsProvider`, `NewsAPIProvider`, `fetch_latest_news`.
- Produces: passing tests that exercise the public API and must continue to pass after the split.

- [ ] **Step 1: Write the characterization test file**

Create `tools/router_py/test_news_provider_characterization.py`:

```python
#!/usr/bin/env python3
"""Characterization tests for the news_provider public API.

These tests must pass before and after the news_provider.py split.
They mock external network calls so they remain fast and deterministic.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from news_provider import (
    NewsAPIProvider,
    NewsProvider,
    NewsResult,
    RSSNewsProvider,
    fetch_latest_news,
)


def test_news_result_dataclass():
    result = NewsResult(ok=True, text="headline", source="rss")
    assert result.ok is True
    assert result.text == "headline"
    assert result.source == "rss"


@pytest.mark.asyncio
async def test_news_provider_fetch_news_prefers_newsapi_when_key_set(monkeypatch):
    monkeypatch.setenv("NEWSAPI_API_KEY", "fake-key")
    expected = NewsResult(ok=True, text="newsapi news", source="newsapi")
    with patch.object(
        NewsAPIProvider, "fetch_world_news", return_value=expected
    ):
        result = await NewsProvider.fetch_news("latest", for_voice=False)
    assert result.ok is True
    assert result.source == "newsapi"


@pytest.mark.asyncio
async def test_news_provider_fetch_news_falls_back_to_rss(monkeypatch):
    monkeypatch.delenv("NEWSAPI_API_KEY", raising=False)
    expected = NewsResult(ok=True, text="rss news", source="rss")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", return_value=expected
    ):
        result = await NewsProvider.fetch_news("latest", for_voice=False)
    assert result.ok is True
    assert result.source == "rss"


def test_fetch_latest_news_returns_text_on_success():
    expected = NewsResult(ok=True, text="plain news", source="rss")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", new=AsyncMock(return_value=expected)
    ):
        text = fetch_latest_news("query")
    assert "plain news" in text


def test_fetch_latest_news_returns_error_on_failure():
    expected = NewsResult(ok=False, text="", source="rss", error="network down")
    with patch.object(
        RSSNewsProvider, "fetch_world_news_async", new=AsyncMock(return_value=expected)
    ):
        text = fetch_latest_news("query")
    assert "network down" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_plain():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "http://example.com/a",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    text = RSSNewsProvider._format_news_response_plain(articles, "query")
    assert "Title A" in text
    assert "Source A" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_voice():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    text = RSSNewsProvider._format_news_response_voice(articles, "query")
    assert "Title A" in text
    assert "Source A" in text


@pytest.mark.asyncio
async def test_rss_news_provider_format_response_html():
    articles = [
        {
            "title": "Title A",
            "description": "Desc A",
            "url": "http://example.com/a",
            "source": "Source A",
            "published": "",
            "time_ago": "recently",
            "timestamp": "",
        }
    ]
    html_text = RSSNewsProvider._format_news_response_html(articles, "query")
    assert "Title A" in html_text
    assert "http://example.com/a" in html_text
```

- [ ] **Step 2: Run the characterization tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_news_provider_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/test_news_provider_characterization.py
git commit -m "test(news): add news_provider characterization tests before split"
```

---

### Task 2: Create the `tools/router_py/news/` package

**Files:**
- Create: `tools/router_py/news/__init__.py`
- Create: `tools/router_py/news/models.py`
- Create: `tools/router_py/news/utils.py`
- Create: `tools/router_py/news/rss.py`
- Create: `tools/router_py/news/api.py`
- Create: `tools/router_py/news/provider.py`

**Interfaces:**
- Consumes: existing code in `tools/router_py/news_provider.py`.
- Produces: a package with the same public symbols as the old module.

- [ ] **Step 1: Create `tools/router_py/news/__init__.py`**

```python
#!/usr/bin/env python3
"""Local Lucy news fetching package."""

from router_py.news.models import NewsResult
from router_py.news.provider import NewsProvider, fetch_latest_news
from router_py.news.rss import RSSNewsProvider
from router_py.news.api import NewsAPIProvider

__all__ = [
    "NewsResult",
    "NewsProvider",
    "fetch_latest_news",
    "RSSNewsProvider",
    "NewsAPIProvider",
]
```

- [ ] **Step 2: Create `tools/router_py/news/models.py`**

Create the file with this header, then copy the `NewsResult` dataclass verbatim from `tools/router_py/news_provider.py` lines 68-80:

```python
#!/usr/bin/env python3
"""Shared news data models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsResult:
    # ... copy verbatim from news_provider.py lines 68-80
```

- [ ] **Step 3: Create `tools/router_py/news/utils.py`**

Create the file with this header, then copy these functions verbatim from `tools/router_py/news_provider.py`:

```python
#!/usr/bin/env python3
"""News utility helpers."""

from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


def _clean_html(text: str) -> str:
    # ... copy verbatim from news_provider.py lines 83-97


def _parse_rfc822_date(date_str: str) -> datetime | None:
    # ... copy verbatim from news_provider.py lines 100-128


def _query_asks_for_history(query: str) -> bool:
    # ... copy verbatim from news_provider.py lines 131-148


def _article_is_stale(pub_date: str, days: int = 7) -> bool:
    # ... copy verbatim from news_provider.py lines 151-162


def _format_time_ago(published: str) -> str:
    # ... copy verbatim from news_provider.py lines 165-212


def _detect_source_disagreement(articles: list[dict[str, Any]]) -> bool:
    # ... copy verbatim from news_provider.py lines 215-343
```

- [ ] **Step 4: Create `tools/router_py/news/rss.py`**

Create the file with this header, then copy the `RSSNewsProvider` class verbatim from `tools/router_py/news_provider.py` lines 346-1106. Update imports to use the new package modules:

```python
#!/usr/bin/env python3
"""RSS news provider."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import string
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiohttp

from router_py.news.models import NewsResult
from router_py.news.utils import (
    _article_is_stale,
    _clean_html,
    _detect_source_disagreement,
    _format_time_ago,
    _parse_rfc822_date,
    _query_asks_for_history,
)

logger = logging.getLogger(__name__)


class RSSNewsProvider:
    # ... copy verbatim from news_provider.py lines 346-1106
```

- [ ] **Step 5: Create `tools/router_py/news/api.py`**

Create the file with this header, then copy the `NewsAPIProvider` class verbatim from `tools/router_py/news_provider.py` lines 1109-1219. Preserve the `.env` loading side effect by calling `_load_project_dotenv()` at module import time. Update imports to use the new package modules:

```python
#!/usr/bin/env python3
"""NewsAPI news provider."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from router_py.news.models import NewsResult
from router_py.news.provider import _load_project_dotenv
from router_py.news.rss import RSSNewsProvider
from router_py.news.utils import _format_time_ago

logger = logging.getLogger(__name__)

_load_project_dotenv()


class NewsAPIProvider:
    # ... copy verbatim from news_provider.py lines 1109-1219
```

- [ ] **Step 6: Create `tools/router_py/news/provider.py`**

Create the file with this header, then copy the `_load_project_dotenv` function (lines 42-56), the `NewsProvider` class (lines 1222-1260), and the `fetch_latest_news` function (lines 1263-1277) verbatim from `tools/router_py/news_provider.py`. Update imports:

```python
#!/usr/bin/env python3
"""Unified news provider entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv

    _dotenv_available = True
except ImportError:
    _dotenv_available = False

from router_py.news.api import NewsAPIProvider
from router_py.news.models import NewsResult
from router_py.news.rss import RSSNewsProvider

logger = logging.getLogger(__name__)


def _load_project_dotenv() -> None:
    """Load lucy-v11/.env so NEWSAPI_API_KEY is available."""
    if not _dotenv_available:
        return
    for root in (
        os.environ.get("LUCY_RUNTIME_AUTHORITY_ROOT"),
        os.environ.get("LUCY_ROOT"),
        str(Path(__file__).resolve().parent.parent.parent),
    ):
        if not root:
            continue
        env_path = Path(root).expanduser().resolve() / ".env"
        if env_path.exists():
            load_dotenv(env_path, override=False)
            break


_load_project_dotenv()


class NewsProvider:
    # ... copy verbatim from news_provider.py lines 1222-1260


def fetch_latest_news(query: str = "") -> str:
    # ... copy verbatim from news_provider.py lines 1263-1277
```

- [ ] **Step 7: Verify package imports cleanly**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.news import NewsResult, NewsProvider, RSSNewsProvider, NewsAPIProvider, fetch_latest_news; print('ok')"
```

Expected: `ok`

- [ ] **Step 8: Commit**

```bash
git add tools/router_py/news/
git commit -m "refactor(news): split news_provider.py into focused package"
```

---

### Task 3: Migrate callers

**Files:**
- Modify: `tools/router_py/execution_engine.py:299`
- Modify: `tools/router_py/providers/evidence.py:38`
- Modify: `tools/router_py/test_voice_integration.py:264`
- Modify: `tools/router_py/test_news_provider.py:12`
- Modify: `tools/router_py/test_news_provider_characterization.py:12`

**Interfaces:**
- No interface change; only import paths change from `router_py.news_provider` / `news_provider` to `router_py.news`.

- [ ] **Step 1: Update imports in source files**

In `tools/router_py/execution_engine.py`, replace:
```python
from router_py.news_provider import NewsProvider, NewsResult
```
with:
```python
from router_py.news import NewsProvider, NewsResult
```

In `tools/router_py/providers/evidence.py`, replace:
```python
from router_py.news_provider import NewsProvider
```
with:
```python
from router_py.news import NewsProvider
```

In `tools/router_py/test_voice_integration.py`, replace:
```python
from router_py.news_provider import RSSNewsProvider
```
with:
```python
from router_py.news import RSSNewsProvider
```

- [ ] **Step 2: Update imports in test files**

In `tools/router_py/test_news_provider.py`, replace the existing import block:
```python
from news_provider import (
    RSSNewsProvider,
    _article_is_stale,
    _detect_source_disagreement,
    _query_asks_for_history,
)
```
with:
```python
from router_py.news import RSSNewsProvider
from router_py.news.utils import (
    _article_is_stale,
    _detect_source_disagreement,
    _query_asks_for_history,
)
```

In `tools/router_py/test_news_provider_characterization.py`, replace:
```python
from news_provider import (
    NewsAPIProvider,
    NewsProvider,
    NewsResult,
    RSSNewsProvider,
    fetch_latest_news,
)
```
with:
```python
from router_py.news import (
    NewsAPIProvider,
    NewsProvider,
    NewsResult,
    RSSNewsProvider,
    fetch_latest_news,
)
```

- [ ] **Step 3: Verify caller imports**

```bash
cd /home/mike/lucy-v11/tools
python3 -c "from router_py.execution_engine import ExecutionEngine"
python3 -c "from router_py.providers.evidence import EvidenceProvider"
python3 -c "import router_py.test_voice_integration"
python3 -c "import router_py.test_news_provider"
python3 -c "import router_py.test_news_provider_characterization"
```

Expected: all imports succeed.

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/execution_engine.py \
        tools/router_py/providers/evidence.py \
        tools/router_py/test_voice_integration.py \
        tools/router_py/test_news_provider.py \
        tools/router_py/test_news_provider_characterization.py
git commit -m "refactor(news): migrate callers from news_provider to news package"
```

---

### Task 4: Delete the old `news_provider.py`

**Files:**
- Delete: `tools/router_py/news_provider.py`

**Interfaces:**
- Removes the old monolithic module; all callers now use `router_py.news`.

- [ ] **Step 1: Delete the file**

```bash
cd /home/mike/lucy-v11
rm tools/router_py/news_provider.py
```

- [ ] **Step 2: Confirm no remaining references in source**

```bash
cd /home/mike/lucy-v11
grep -R "from router_py\.news_provider\|import router_py\.news_provider" --include="*.py" tools/ ui-v10/ || true
```

Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git rm tools/router_py/news_provider.py
git commit -m "refactor(news): remove monolithic news_provider.py"
```

---

### Task 5: Run tests and lint

**Files:**
- None (verification only).

**Interfaces:**
- Confirm no regressions.

- [ ] **Step 1: Run ruff**

```bash
cd /home/mike/lucy-v11
python3 -m ruff check tools/router_py/news/
```

Expected: `All checks passed!`

- [ ] **Step 2: Run characterization tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_news_provider_characterization.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run the fast router suite**

```bash
cd /home/mike/lucy-v11
./scripts/run-fast-tests.sh
```

Expected: the suite passes with the same baseline counts as before (686 passed, 7 skipped, 261 deselected, 169 subtests).

- [ ] **Step 4: Commit verification results (optional)**

No code changes; record the final counts in the Phase 8 report.

---

### Task 6: Write the news-provider split report

**Files:**
- Create: `lucy-v11-prep/reports/phase8_news_provider_split_2026-07-27.md`

**Interfaces:**
- No code interface; report documents the change.

- [ ] **Step 1: Write the report**

The report should include:

- Date, branch, V10 preservation statement.
- Objective: split `news_provider.py`.
- New files: `tools/router_py/news/__init__.py`, `models.py`, `utils.py`, `rss.py`, `api.py`, `provider.py`.
- Deleted file: `tools/router_py/news_provider.py`.
- Callers migrated: `execution_engine.py`, `providers/evidence.py`, `test_voice_integration.py`, `test_news_provider.py`, plus the characterization tests.
- Verification: grep results, ruff result, pytest summary.
- Gate assessment table.
- Next steps: continue with the next Phase 8 module split (`voice_tool.py` or `policy.py`).

- [ ] **Step 2: Commit the report**

```bash
git add lucy-v11-prep/reports/phase8_news_provider_split_2026-07-27.md
git commit -m "docs: Phase 8 report for news_provider.py split"
```

---

## Self-review checklist

- [ ] Spec coverage: package creation, caller migration, deletion, characterization tests, fast suite, lint, report.
- [ ] Placeholder scan: no TBD/TODO/"fill in details".
- [ ] Type consistency: public symbols unchanged; utility functions moved to `news.utils`.
- [ ] Scope: only `news_provider.py` and callers touched.
