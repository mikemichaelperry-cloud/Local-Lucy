# Local Lucy v8 — Comprehensive Technical Architecture Report

**Date:** 2026-05-02  
**System:** Local Lucy v8 Alpha — Desktop AI Assistant with PySide6 HMI  
**Hardware:** NVIDIA RTX 3060 12GB VRAM  
**Authority Root:** `~/lucy-v8/snapshots/opt-experimental-v9-dev/`  
**Report Focus:** Architecture, routing logic, VRAM management, source handling, with special emphasis on the NEWS path implementation.

---

## 1. Executive Summary

Local Lucy v8 is a multi-mode local AI desktop assistant built on PySide6. It supports three operational modes — **LOCAL** (Ollama), **AUGMENTED** (Wikipedia → OpenAI → Kimi), and **NEWS** (RSS feeds) — with an intent-based router that classifies queries and dispatches them to the appropriate backend. The system runs entirely on the user's machine, with optional paid API augmentation, and features a full voice pipeline (Whisper STT + Kokoro TTS).

Key architectural principles:
- **Backend authoritative, UI must not fabricate state** (`AGENTS.md`)
- **No optimistic behavior, no silent side effects**
- **Flattened execution chain** — UI → `RuntimeBridge` → `ExecutionEngine.execute()` → backend directly, with no shell subprocess hops for normal operation
- **Two-Python strategy** — System Python runs router/voice/backend; UI-v8 `.venv` provides Kokoro TTS and UI packages

---

## 2. Architecture Overview

### 2.1 Component Map

```
┌─────────────────────────────────────────────────────────────────────┐
│                              USER                                    │
│  (Text Input │ Voice PTT │ Mode Toggles │ Model Selector)          │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │   UI-v8 (PySide6)   │
                    │   main_window.py    │
                    └──────────┬──────────┘
                               │
           ┌───────────────────┼───────────────────┐
           │                   │                   │
    ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
    │ Conversation│   │   Control   │   │   Status    │
    │   Panel     │   │   Panel     │   │   Panel     │
    └─────────────┘   └─────────────┘   └─────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  runtime_bridge.py  │
                    │  (direct execution) │
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │  ExecutionEngine    │
                    │  (execute_async)    │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
      ┌───────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
      │  classify.py │ │local_answer │ │  evidence   │
      │(intent +    │ │  (Ollama)   │ │  fetchers   │
      │ route pick)  │ │             │ │             │
      └───────┬──────┘ └─────────────┘ └─────────────┘
              │
     ┌────────┼────────┬────────┐
     │        │        │        │
    LOCAL AUGMENTED  NEWS    TIME
     │        │        │        │
  Ollama  Wikipedia  RSS     TimeAPI
          OpenAI     Feeds    (subproc)
          Kimi
```

### 2.2 Authority & State Contract

The snapshot at `~/lucy-v8/snapshots/opt-experimental-v9-dev/` is the runtime authority. All state mutations go through `runtime_control.py` with `fcntl.LOCK_EX` file locking. The UI root must be named `ui-v9` (V8 isolation — `ui-v7` is explicitly rejected).

State files live under `~/.codex-api-home/lucy/runtime-v9/state/`:
- `current_state.json` — profile, mode, model, status
- `request_history.jsonl` — append-only query log
- `last_route.json`, `last_preprocess.json` — routing telemetry
- `health.json`, `runtime_lifecycle.json` — health/lifecycle (not present in v8, fallbacks used)

---

## 3. Mode Router Logic

### 3.1 Intent Classification

`classify_intent(query, surface="cli")` → `ClassificationResult`

The classifier inspects query text for:
- **News keywords**: "latest news", "what's happening in Israel", "Australian politics"
- **Time keywords**: "what time is it", "current date"
- **Medical keywords**: "diagnose", "treatment", "symptoms"
- **Creative markers**: stories, poems, fiction → `force_local=True`
- **Evidence mode**: medical context, conflict/live events, source verification requests

### 3.2 Route Selection (`select_route`)

```python
# tools/router_py/classify.py:175-282
def select_route(classification, policy="fallback_only", forced_mode=None):
    if forced_mode == "FORCED_OFFLINE":
        return _make_local_decision(classification)
    if forced_mode == "FORCED_ONLINE":
        return _make_augmented_decision(classification, prefer_paid=True)
    if classification.force_local:
        return _make_local_decision(classification)
    if classification.clarify_required:
        return RoutingDecision(route="CLARIFY", ...)
    if policy == "disabled":
        return _make_local_decision(classification)

    # NEWS and TIME are hard-routed when needs_web + current_evidence
    if classification.needs_web and classification.intent_family == "current_evidence":
        if classification.category in ("news_world", "news_israel", "news_australia"):
            return _make_news_decision(classification)
        if classification.category == "time_query":
            return _make_time_decision(classification)

    # Fallback/default paths
    if classification.intent_family == "current_evidence":
        if policy == "fallback_only":
            return _make_local_with_fallback(classification)
        ...
    if classification.evidence_mode == "required":
        return _make_augmented_decision(classification, prefer_paid=True)
    ...
    return _make_local_decision(classification)
```

**Policies:**
- `disabled` — always LOCAL
- `fallback_only` — try LOCAL first, fall back to AUGMENTED on low confidence
- `direct_allowed` — go directly to AUGMENTED for evidence queries

### 3.3 Critical Design: News Does Not Fall Through

When the classifier detects a news query (`news_world`, `news_israel`, `news_australia`), it is **always** routed to `NEWS`. If RSS fetching fails, the execution engine returns a hard failure — it does **not** fall back to the local LLM. This prevents hallucinated "news" from a model with a knowledge cutoff.

---

## 4. VRAM Management

### 4.1 GPU & Model Configuration

| Model | Backend Name | Size | VRAM | Status |
|-------|-------------|------|------|--------|
| llama3.1 8B | `local-lucy` | ~4.9GB | ~5GB | Active |
| qwen3 14B | `local-lucy-qwen3` | ~9.3GB | ~9.5GB | Active |
| qwen3 30B | `qwen3:30b` | ~18GB | >12GB | Excluded from UI |

### 4.2 Ollama Serialization Lock

```python
# tools/router_py/local_answer.py:39-42
import threading
_ollama_call_lock = threading.Lock()

# tools/router_py/local_answer.py:751-754
for attempt in range(max_attempts):
    session = await self._get_session()
    with _ollama_call_lock:
        async with session.post(self.config.ollama_url, json=payload) as response:
            ...
```

A **global `threading.Lock`** serializes all Ollama API calls. This prevents model unload/load races when switching between models (e.g., 8B → 14B). The lock is held for the entire HTTP request, which can be 5–30 seconds. **This blocks the async event loop thread**, freezing concurrent operations.

### 4.3 Retry Logic for Model Loading

```python
# tools/router_py/local_answer.py:746-774
max_attempts = 5
base_delay = 2.0
for attempt in range(max_attempts):
    ...
    with _ollama_call_lock:
        async with session.post(...) as response:
            data = await response.json()
            text = data.get("response", "")
            if not text and data.get("thinking"):
                text = data["thinking"].strip()  # Qwen3 thinking fallback
            ...
    if not text:
        delay = base_delay * (2 ** attempt)  # 2s, 4s, 8s, 16s, 32s
        await asyncio.sleep(delay)
```

Exponential backoff (2→4→8→16→32s) handles Ollama's 5–10s model load time. The Qwen3 thinking fix (`thinking` → `response` fallback) addresses models that consume the token budget in reasoning before generating a visible response.

### 4.4 UI Cooldown

A 5-second cooldown in `main_window.py` prevents rapid model switching in the UI. However, this is **client-side only** — direct `runtime_control.py` calls or multiple UI instances can still trigger Ollama unload/load races.

### 4.5 VRAM Monitoring

`state_store.py` polls `nvidia-smi` (with 2s timeout) and `ollama ps` to report GPU status. No **proactive VRAM enforcement** exists — if `qwen3:30b` is requested manually, Ollama will attempt to load it, spilling to system RAM and potentially triggering the OOM killer.

---

## 5. Source Handling (Evidence / Augmented / Local)

### 5.1 Evidence Dispatcher

```python
# tools/router_py/execution_engine.py:2037-2083
async def _fetch_evidence(self, question, route, for_voice=False):
    if route.route == "TIME":
        return await self._fetch_time_evidence(question)
    if route.route == "NEWS":
        return await self._fetch_news_evidence(question, for_voice=for_voice)
    if route.provider == "wikipedia":
        return await self._fetch_wikipedia_evidence(question)
    if route.provider in ("kimi", "openai"):
        return await self._fetch_api_evidence(question, route.provider)
```

### 5.2 Provider Chain (AUGMENTED)

The AUGMENTED route attempts evidence in this order:
1. **Wikipedia** (free, unverified context)
2. **OpenAI** (paid, if configured)
3. **Kimi** (paid, if configured)

Evidence is fetched **before** the LLM call. The prompt is then augmented with the evidence text.

### 5.3 Time Route

TIME calls `current_time_tool.py` via subprocess (10s timeout) to fetch from TimeAPI.io. No LLM is involved.

### 5.4 Local Guard for Time-Sensitive Queries

```python
# In local_answer.py / execution_engine.py
if route_mode not in {"AUGMENTED", "NEWS"} and is_time_sensitive(query):
    # Block — local model cannot answer current events
```

Time-sensitive queries (news, live events) are explicitly blocked from the LOCAL route to prevent hallucinations.

---

## 6. NEWS Path — Deep Dive

### 6.1 Routing

When a user asks "What's the latest world news?":
1. `classify_intent()` → `intent_family="current_evidence"`, `category="news_world"`, `needs_web=True`
2. `select_route()` → `_make_news_decision()` → `route="NEWS"`, `provider="news"`
3. `execute_async()` → `_execute_full_route_python()` → `_fetch_evidence()` → `_fetch_news_evidence()`

### 6.2 RSS Feed Architecture

```python
# tools/router_py/news_provider.py:103-174
RSS_FEEDS = {
    "bbc_world":        {"url": "http://feeds.bbci.co.uk/news/world/rss.xml",           "region": "world"},
    "guardian_world":   {"url": "https://www.theguardian.com/world/rss",                "region": "world"},
    "nyt_world":        {"url": "https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "region": "world"},
    "npr_world":        {"url": "https://feeds.npr.org/1001/rss.xml",                   "region": "world"},
    "bbc_middle_east":  {"url": "http://feeds.bbci.co.uk/news/world/middle_east/rss.xml", "region": "middle_east"},
    "times_of_israel":  {"url": "https://www.timesofisrael.com/feed/",                  "region": "middle_east"},
    "israel_hayom":     {"url": "https://www.israelhayom.com/feed/",                    "region": "middle_east"},
    "guardian_australia": {"url": "https://www.theguardian.com/australia-news/rss",     "region": "australia"},
    "abc_australia":    {"url": "https://abc.net.au/news/feed/2942460/rss.xml",         "region": "australia"},
    "smh":              {"url": "https://www.smh.com.au/rss/feed.xml",                  "region": "australia"},
    "the_age":          {"url": "https://www.theage.com.au/rss/feed.xml",               "region": "australia"},
    "news_com_au":      {"url": "https://www.news.com.au/feed/",                        "region": "australia"},
    "crikey":           {"url": "https://www.crikey.com.au/feed/",                      "region": "australia"},
}
```

**14 feeds** across three regions. Region detection is keyword-based:
- `middle_east`: israel, gaza, hamas, lebanon, iran, palestine, etc.
- `australia`: australia, sydney, melbourne, albo, anzac, etc.
- default: `world`

### 6.3 Fetch & Deduplication

```python
# tools/router_py/news_provider.py:236-295
async def fetch_news(cls, query, for_voice=False):
    # Detect region from query
    region = cls._detect_region(query)
    
    # Fetch feeds (sequential, 10s timeout each)
    articles = []
    for feed_id, feed in feeds.items():
        try:
            data = urllib.request.urlopen(feed["url"], timeout=cls.TIMEOUT)
            parsed = ET.fromstring(data.read())
            articles.extend(cls._parse_feed(parsed, feed))
        except Exception as e:
            logger.error(f"Feed {feed_id} failed: {e}")
    
    # Sort by timestamp, newest first
    all_articles.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    all_articles = all_articles[:cls.MAX_TOTAL_ARTICLES]  # 10 total
    
    # Deduplicate by normalized title
    seen_titles = set()
    unique_articles = []
    for article in all_articles:
        normalized = article["title"].lower().strip().rstrip(".!?:;")
        if normalized not in seen_titles:
            seen_titles.add(normalized)
            unique_articles.append(article)
    
    return cls._format_news_response(unique_articles, query, for_voice=for_voice)
```

### 6.4 Dual-Format Output

The NEWS route produces **two formats** simultaneously:

**Display format** (plain text, numbered):
```
Latest news about 'world news':
(Fetched: 2026-05-02 18:38:09)

1. Israel and Hamas agree to extend truce
   Source: BBC World News • 2 hours ago
   mediators announced a 48-hour extension...
   Read more: https://www.bbc.co.uk/news/...

2. ...
```

**Voice format** (condensed, TTS-friendly):
```
Israel and Hamas agree to extend truce, from BBC World News. 
 mediators announced a 48-hour extension..., from Times of Israel. 
```

The voice format is constructed in `execution_engine.py` and passed via `metadata["voice_text"]` to the TTS pipeline.

### 6.5 Display Rendering

```python
# ui-v9/app/panels/conversation_panel.py
def _auto_link_urls(text):
    escaped = html.escape(text)
    paragraphs = escaped.split('\n\n')
    for para in paragraphs:
        linked = re.sub(r'(https?://[^\s<>"{}|\\^`\[\]]+)', 
                        r'<a href="\1">\1</a>', para)
        linked = linked.replace('\n', '<br>')
        parts.append(f'<p style="margin: 8px 0;">{linked}</p>')
    return f'<html><body style="...">{ "".join(parts) }</body></html>'
```

URLs in the plain text news output are auto-detected and wrapped in clickable `<a>` tags. Line breaks are preserved as `<br>`.

### 6.6 Critical: No LLM Involved

The NEWS route is the only "full" route that **bypasses the LLM entirely**. The response is raw RSS content, formatted and deduplicated. There is no summarization, no synthesis, no opinion — just headlines, sources, and links.

---

## 7. Security & Risk Analysis

### 7.1 Critical Risks

| Risk | File | Severity | Description |
|------|------|----------|-------------|
| **Weak rmtree guard** | `execution_engine.py:922-928` | **Critical** | Namespace cleanup uses `"namespaces" in str(path)` — trivially bypassed path traversal |
| **XML bomb in RSS** | `news_provider.py:327` | **Critical** | `ET.fromstring()` on untrusted RSS with no size/entity limits |
| **Thread lock blocks event loop** | `local_answer.py:753` | **Critical** | `threading.Lock()` inside async function freezes all concurrent I/O for 5–30s |
| **Duplicate code (3,600+ lines)** | `runtime_bridge.py` vs `runtime_request.py` | **Critical** | Dual history writers, dual payload builders, diverging schemas |

### 7.2 High Risks

| Risk | File | Severity | Description |
|------|------|----------|-------------|
| **Event loop race** | `execution_engine.py:800-817` | **High** | `loop.is_running()` check is non-atomic; can race with other threads |
| **SQLite connection leak** | `state_manager.py:177-194` | **High** | Thread-local connections with `check_same_thread=False`, no cleanup limit |
| **Unlocked history writes** | `runtime_bridge.py:820-845` | **High** | `runtime_bridge` appends to `request_history.jsonl` without `fcntl` locking |
| **VRAM spillover** | Model config | **High** | `qwen3:30b` (18GB) not enforced at backend; manual env var can OOM |
| **No RSS caching** | `news_provider.py` | **High** | Every news query re-fetches all 14 feeds; no TTL, ETag, or disk cache |
| **Subprocess overhead** | `execution_engine.py` | **High** | Every evidence fetch spawns a subprocess (~50–200ms latency each) |

### 7.3 Medium Risks

- **Sequential RSS fetch**: Feeds are fetched in a for-loop, not parallelized
- **Weak deduplication**: Title-only normalization misses near-duplicate headlines
- **Incomplete HTML entity decoding**: Only `&amp;`, `&lt;`, `&gt;`, `&quot;`, `&#39;`, `&nbsp;` handled
- **State drift**: `runtime_bridge._build_payload_from_result()` reads `os.environ` fallbacks, not authoritative state file
- **Stale namespaces**: 372 directories in `state/namespaces/` accumulating indefinitely
- **Model switch cooldown client-side only**: No backend enforcement

---

## 8. Performance Characteristics

### 8.1 Latency Budget (Typical Query)

| Stage | Path | Time |
|-------|------|------|
| Intent classification | Python (local) | ~5–20ms |
| Route selection | Python (local) | ~1ms |
| Evidence fetch (Wikipedia) | HTTP + thread pool | ~200–800ms |
| Evidence fetch (RSS/news) | HTTP × 10 feeds | ~2–8s |
| Evidence fetch (OpenAI/Kimi) | HTTP + subprocess | ~1–3s |
| LLM generation (8B) | Ollama API | ~2–5s |
| LLM generation (14B) | Ollama API | ~3–8s |
| TTS synthesis (Kokoro) | Subprocess to ui-v9 | ~0.5–2s |

### 8.2 Bottlenecks

1. **RSS fetch is I/O-bound and sequential** — 10 feeds × 1–3s each = 10–30s worst case
2. **Ollama model loading** — 5–10s on first query after switch; mitigated by retry backoff
3. **Subprocess spawn** — Every evidence provider spawns a new process
4. **No connection pooling** — New `aiohttp.ClientSession` per `ExecutionEngine` instance

---

## 9. Data Integrity Concerns

### 9.1 Dual History Writers

Both `runtime_request.py` (subprocess path) and `runtime_bridge.py` (direct path) write to `request_history.jsonl`:
- `runtime_request.py`: Uses `locked_state_file()`, checks for duplicate `request_id`s
- `runtime_bridge.py`: Opens file with `"a"`, no locking, no dedup

The two paths use **different ID namespaces**:
- Direct: `f"direct_{sha256(text)[:16]}_{time.time_ns()}"`
- Subprocess: `f"{iso_now()}-{os.getpid()}"`

### 9.2 State File Drift

`runtime_bridge.py` builds `control_state` from `os.environ` fallbacks:
```python
# runtime_bridge.py (approximate)
control_state = {
    "mode": os.environ.get("LUCY_MODE", "auto"),
    "model": os.environ.get("LUCY_LOCAL_MODEL", "local-lucy"),
    ...
}
```

If the user changes mode via CLI (`runtime_control.py set-mode ...`), the env vars become stale. The history entry will contain incorrect `control_state`.

### 9.3 SQLite/File Dual-Write Mismatch

`_write_state_files()` writes to both SQLite and JSON files. If one fails, `verify_state_consistency()` logs a warning but does **not** repair the mismatch.

---

## 10. Recommended Improvements

### Immediate (Security & Stability)

1. **Fix `shutil.rmtree` guard** — Use `path.resolve().is_relative_to(ROOT / "state" / "namespaces")`
2. **Replace `threading.Lock()` with `asyncio.Lock()`** — Or run the locked section in a dedicated executor thread
3. **Harden RSS XML parsing** — Use `defusedxml` or set `parser = ET.XMLParser(resolve_entities=False)`
4. **Add file locking to `runtime_bridge._write_history_entry()`** — Match `runtime_request.py` behavior

### Short-Term (Performance & Reliability)

5. **Implement RSS caching** — 5-minute TTL with `ETag`/`Last-Modified` support; cache parsed feeds in SQLite or JSON
6. **Parallelize RSS fetching** — Use `asyncio.gather()` with `aiohttp` instead of sequential `urllib`
7. **Add backend VRAM check** — Before model load, verify `nvidia-smi` free VRAM > model size
8. **Unify history writing** — Extract a single `HistoryWriter` class used by both direct and subprocess paths
9. **Connection pooling for Ollama** — Reuse `aiohttp.ClientSession` across `ExecutionEngine` instances

### Medium-Term (Architecture)

10. **Remove symlink hell in snapshot** — Replace `voice/`, `state/voice/`, `runtime/voice/bin/` symlinks with copies or path resolution
11. **Centralize path resolver** — Replace 156+ hardcoded `.codex-api-home` references with a shared `paths.py`
12. **Add news summarization option** — Optional lightweight LLM pass to synthesize a 2-sentence summary from RSS headlines
13. **Implement feed health monitoring** — Track per-feed success rate and auto-disable failing feeds
14. **Add HTML entity full decoder** — Use `html.unescape()` instead of manual partial mapping

---

## Appendix A: Verified Code Snippets

### A.1 NEWS Route Execution (No Fallthrough)
```python
# tools/router_py/execution_engine.py:1946-1988
if route.route == "NEWS":
    if evidence and evidence.get("context"):
        full_text = evidence["context"]
        voice_text = ""
        articles = evidence.get("articles")
        if articles:
            voice_lines = [f"{a['title']}, from {a['source']}." for a in articles[:6]]
            voice_text = " ".join(voice_lines)
        return ExecutionResult(
            status="completed",
            outcome_code="answered",
            route="NEWS",
            provider="news",
            provider_usage_class="free",
            response_text=full_text,
            metadata={
                "route_type": "news_live",
                "evidence_fetched": True,
                "trust_class": "unverified",
                "voice_text": voice_text,
            },
        )
    # News fetch failed — do not fall through to local model
    return ExecutionResult(
        status="failed",
        outcome_code="news_fetch_failed",
        route="NEWS",
        provider="news",
        provider_usage_class="free",
        response_text="Unable to fetch live news at this time...",
        error_message="News provider returned no articles",
        metadata={"route_type": "news_live_failed", "real_route_preserved": True},
    )
```

### A.2 Ollama Call with Retry
```python
# tools/router_py/local_answer.py:746-774
max_attempts = 5
base_delay = 2.0
for attempt in range(max_attempts):
    try:
        session = await self._get_session()
        with _ollama_call_lock:
            async with session.post(self.config.ollama_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()
                text = data.get("response", "")
                if not text and data.get("thinking"):
                    text = data["thinking"].strip()
                duration_ms = int((time.time() - start_time) * 1000)
                if text:
                    return text, duration_ms
                delay = base_delay * (2 ** attempt)
                await asyncio.sleep(delay)
    except Exception as e:
        logger.error(f"Ollama API call failed: {e}")
        raise
```

### A.3 Namespace Cleanup Guard (Weak)
```python
# tools/router_py/execution_engine.py:922-928
try:
    if (
        self._state_dir.exists()
        and "namespaces" in str(self._state_dir)
        and self._execution_namespace in str(self._state_dir)
    ):
        shutil.rmtree(self._state_dir, ignore_errors=True)
except Exception as e:
    self._logger.warning(f"Failed to cleanup namespace directory: {e}")
```

---

*Report compiled from live codebase analysis on 2026-05-02. All file paths are relative to `~/lucy-v8/`.*
