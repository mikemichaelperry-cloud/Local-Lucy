# Phase 8b Completion Report — Split `tools/router_py/news_provider.py`

**Date:** 2026-07-27  
**Branch:** `phase8-news-provider-split` (HEAD `433cfa4`, ahead of `main` at `d2e5a51`)  
**Scope:** `tools/router_py/news_provider.py` → `tools/router_py/news/` package  
**V10 preservation:** The `lucy-v10/` tree is untouched; this refactor applies only to V11 (`lucy-v11/`).

## Objective

Split the monolithic `tools/router_py/news_provider.py` into a focused `tools/router_py/news/` package and migrate callers, preserving behavior.

## Changes

### New files

| File | Purpose |
|------|---------|
| `tools/router_py/news/__init__.py` | Public re-exports |
| `tools/router_py/news/models.py` | `NewsResult` dataclass |
| `tools/router_py/news/utils.py` | Helper functions (`_clean_html`, `_parse_rfc822_date`, `_query_asks_for_history`, `_article_is_stale`, `_format_time_ago`, `_detect_source_disagreement`) |
| `tools/router_py/news/rss.py` | `RSSNewsProvider` |
| `tools/router_py/news/provider.py` | Unified `NewsProvider` and `fetch_latest_news` |
| `tools/router_py/test_news_provider_characterization.py` | Characterization tests for the public API |

### Deleted file

- `tools/router_py/news_provider.py`
- `tools/router_py/news/api.py` (created during the split but removed after review because `NewsAPIProvider` was dead code — no API key is installed and the app uses RSS feeds exclusively).

### Callers migrated

- `tools/router_py/execution_engine.py`
- `tools/router_py/providers/evidence.py`
- `tools/router_py/test_voice_integration.py`
- `tools/router_py/test_news_provider.py`
- `tools/router_py/test_news_provider_characterization.py`

All imports now use `from router_py.news import ...`.

### Remaining references

```bash
grep -R "from router_py\.news_provider\|import router_py\.news_provider" \
  --include="*.py" tools/ ui-v10/
```

Result: `No remaining references`

## Verification

### Lint

```bash
python3 -m ruff check tools/router_py/news/
```

Result: `All checks passed!`

### Characterization tests

```bash
python3 -m pytest tools/router_py/test_news_provider_characterization.py -q --tb=line
```

Result: `7 passed in 0.05s`

### Fast router suite

```bash
./scripts/run-fast-tests.sh
```

Result: `693 passed, 7 skipped, 261 deselected, 169 subtests passed in 145.35s`

## Gate assessment

| Gate | Status | Evidence |
|------|--------|----------|
| Behavior preserved | ✅ | Characterization tests pass; public API symbols unchanged |
| Dead code removed | ✅ | `NewsAPIProvider` removed because no key is installed and RSS is the active source |
| Callers migrated | ✅ | Grep shows no remaining `router_py.news_provider` imports |
| Old module removed | ✅ | `git rm tools/router_py/news_provider.py` committed |
| Lint clean | ✅ | `ruff check tools/router_py/news/` passes |
| Fast suite passes | ✅ | 693 passed, no regressions |
| Scope respected | ✅ | Only `news_provider.py`, new `news/` package, and direct callers touched |

## Notes

- **Intentional behavior change:** `NewsAPIProvider` was removed as a user-approved functional simplification. No NewsAPI key is installed in this environment, and the application relies on RSS feeds exclusively for news. This is not an accidental regression; it is a deliberate reduction in scope that eliminates dead code while keeping the public `NewsProvider.fetch_news(...)` API unchanged.
- The `.env` loading side effect was preserved in `provider.py` so any future news configuration is discovered on import.
- The split follows the same pattern as `state_manager.py`: characterization tests → package → migrate callers → delete old file.

## Next steps

Continue Phase 8 with the next module split. Recommended order:
1. `tools/router_py/voice_tool.py`
2. `tools/router_py/policy.py`
3. `tools/router_py/policy_router.py`
4. `tools/router_py/local_answer.py`
5. `tools/router_py/execution_engine.py`
6. `tools/router_py/classify.py` (last — highest risk)
