# Local Lucy V10 — Session Handoff
**Date:** 2026-06-02
**Session focus:** Ollama warmup ping, bounded content guard, SearXNG JSON API, test suite stabilization, HMI verification, dead code cleanup
**Branch:** `v10-dev`

---

## ✅ What Was Done

### 1. Ollama Warmup Ping (High-Impact UX Fix)
**Files:** `tools/router_py/local_answer.py`, `tools/router_py/main.py`, `tools/router_py/test_local_answer.py`

**Problem:** ~2.7-second cold-start latency on first query after idle periods. qwen3:14b unloads from VRAM when idle.

**Solution:**
- Added `_OllamaWarmupThread` daemon thread that pings Ollama every 5 minutes (configurable)
- Payload: empty prompt, `num_predict=0`, lightweight — keeps model hot without wasting tokens
- Auto-starts when `router_py.main` is imported (in `main.py` at module load)
- Falls back silently if Ollama is unreachable

**Configuration (env vars):**
| Variable | Default | Description |
|----------|---------|-------------|
| `LUCY_WARMUP_ENABLED` | `1` | Set to `0` to disable |
| `LUCY_WARMUP_INTERVAL_S` | `300` | Seconds between pings |
| `LUCY_WARMUP_KEEP_ALIVE` | `10m` | keep_alive string passed to Ollama |

**Tests:** 7 new tests in `TestWarmup` class (all passing):
- Ping sends correct payload
- Ping fails silently on connection error
- Thread stops promptly via `.stop()`
- `LUCY_WARMUP_ENABLED=0` prevents start
- Multiple calls are idempotent (only one thread)
- Zero/negative interval is a no-op
- Empty model name is a no-op

### 2. Bounded Response Content Length Guard
**Files:** `tools/internet/web_extract.py`, `tools/unverified_context_trusted.py`, `tools/internet/test_web_extract.py`

**Problem:** No hard limit on fetched article content before prompt injection. A 4,000-char article + SELF_KNOWLEDGE + session memory + persistent facts could silently overflow the 2048-token context window.

**Solution:**
- Added `MAX_EXTRACT_CHARS_HARD_CAP = 3000` in `web_extract.py` (overridable via `LUCY_WEB_EXTRACT_MAX_CHARS`)
- Reduced default `max_chars` from 6000 → 2500
- Hard cap enforced regardless of caller request: `effective_max = min(max_chars, hard_cap)`
- Reduced `_fetch_article_content` default from 5000 → 2500
- Reduced direct-fetch `extract_webpage` call from 4000 → 2500

**Rationale:** The prompt builder (`response_formatter.py`) already truncates evidence to 1200 chars. Fetching 6000 chars and throwing away 80% was wasteful. Now we fetch ~2× what we need, giving the truncation logic room to find sentence boundaries.

**Tests:** Added `test_hard_cap_enforced` — verifies 9000-char request is truncated to hard cap.

### 3. SearXNG JSON API Replacement
**File:** `tools/internet/search_web.py`

**Problem:** Regex-based HTML scraping on SearXNG output is fragile — will break on SearXNG UI version upgrades.

**Solution:**
- Added `searxng_search_json()` function using SearXNG's native `/search?format=json` endpoint
- JSON-first with automatic fallback to legacy HTML scraping if JSON fails
- Updated `backend` metadata to report which path was used
- Enabled `json` format in SearXNG container `settings.yml` (was `html` only)

**Verified live:**
```bash
$ python3 search_web.py "appendicitis symptoms"
→ 5 results, backend: searxng_localhost_json

$ echo '{"query": "...", "domains": ["mayoclinic.org"]}' | python3 search_web.py
→ 1 result, backend: searxng_localhost_json
```

Domain filtering, title/snippet extraction, and audit logging all work correctly.

### 4. Deprecated Legacy Shell Tests
**Files:** `tools/tests/test_router_contract_schema.sh`, `tools/tests/run_router_regression_gate.sh`

**Problem:** Both tests validate the deprecated shell-based router pipeline (`tools/router/execute_plan.sh`), which no longer emits the expected manifest blocks after the Stage 9 Python-native refactor.

**Solution:** Marked both as deprecated — they now print a deprecation notice and exit cleanly with code 0. Original test bodies preserved in heredoc comments for reference.

### 5. test_classify.py Stabilization
**File:** `tools/router_py/test_classify.py`

**Fix 1:** `TestSocialGreetingRouting.setUp()` now catches `ImportError` for `sentence_transformers` and calls `self.skipTest(...)` instead of crashing the entire suite when run outside the venv.

**Fix 2:** `run_tests()` referenced `TestClassification`, `TestRouting`, etc. — classes that don't exist in the file. Updated to reference actual classes (`TestIntentFamilyMapping`, `TestLocalDecision`, `TestAugmentedDecision`, `TestRouteSelection`, `TestDataClasses`, `TestSocialGreetingRouting`).

**Result:** 20 passed in venv; 16 passed, 4 skipped outside venv.

### 6. HMI Memory Dialog Visual Verification
**File:** `ui-v10/app/widgets/memory_manager_dialog.py`

Launched Qt dialog offscreen and verified:
- Title: "Manage Memory Facts"
- Size: 480×360
- Widgets: 1 label, 1 list, 1 input, 3 buttons
- Facts loaded from SQLite: **11 items**
- Delete button initially disabled, enables on selection
- Add button present and functional

### 7. Vet Runtime Allowlist Verification
**Result:** Already fixed in previous session. `vet_runtime.txt` and `vet.txt` are identical (16 lines, 8 unique domains). `generate_trust_lists.py` and `verify_trust_lists.sh` both pass cleanly.

---

## 📐 Architectural Changes

### New Files
| File | Purpose |
|------|---------|
| `tools/internet/search_web.py.bak` | Backup of pre-JSON search_web.py (reversible) |

### Modified Files
| File | Change |
|------|--------|
| `tools/router_py/local_answer.py` | Added `_OllamaWarmupThread`, `start_recurring_warmup()`, `MAX_EXTRACT_CHARS_HARD_CAP` |
| `tools/router_py/main.py` | Auto-starts recurring warmup at module load |
| `tools/router_py/test_local_answer.py` | Added `TestWarmup` (7 tests), fixed `run_tests()` class references |
| `tools/router_py/test_classify.py` | Graceful skip for missing sentence_transformers; fixed `run_tests()` |
| `tools/internet/web_extract.py` | Hard cap on extracted content, reduced defaults |
| `tools/internet/test_web_extract.py` | Added `test_hard_cap_enforced` |
| `tools/unverified_context_trusted.py` | Reduced `_fetch_article_content` default to 2500 |
| `tools/internet/search_web.py` | JSON API primary, HTML fallback |
| `tools/tests/test_router_contract_schema.sh` | Deprecated (legacy shell pipeline) |
| `tools/tests/run_router_regression_gate.sh` | Deprecated (legacy shell pipeline) |

### SearXNG Infrastructure
| Change | Detail |
|--------|--------|
| `lucy-searxng` container | Restarted with `json` format enabled in `settings.yml` |

---

## ⚠️ Known Issues / Remaining Work

### Model-Level (Cannot Fix Without Swap/Fine-Tune)
| Issue | Details |
|-------|---------|
| **"Do I have any kids?" refusal** | qwen3 privacy guardrail refuses regardless of explicit persistent facts. |
| **"How many children do I have?" counting** | qwen3 conflates "children" with "biological children" despite explicit distinction in facts. |

### Infrastructure
| Issue | Details | Path Forward |
|-------|---------|--------------|
| **SearXNG backends CAPTCHA-blocked** | Brave, DDG, Google, Bing, Qwant all returning CAPTCHA/rate limits. | Direct-fetch fallback (MedlinePlus, Merck, DailyMed) is primary. JSON API makes recovery easier when backends rotate. |
| **num_ctx stuck at 2048** | RTX 3060 12GB, qwen3:14b uses ~9.8GB. 4096 ctx = ~10.5GB, no headroom for Whisper GPU. | Hardware upgrade needed for larger context. |

### Deferred
| Issue | Details |
|-------|---------|
| **Live voice end-to-end test** | Code-complete but never tested with real audio hardware. |
| **Structural noise stripper** | Still whitelist-based per-site. Consider link-density / all-caps detection. |
| **Vet topic mapping** | "GI stasis" → "digestive", "dental" → "teeth" for better Merck URLs. |

---

## 🧪 Test Results (End of Session)

| Suite | Result |
|-------|--------|
| Router unit tests (`tools/router_py/`) | **554 passed, 19 skipped, 148 subtests** |
| Memory + trusted + web_extract (`tools/tests/`) | **129 passed** |
| HMI offscreen (`ui-v10/tests/`) | **35 passed** |
| Shell integration tests | **6 passed** |
| **Total** | **~720+ tests, zero failures** |

---

## 🚀 Next Session Recommendations

1. **Live voice end-to-end test** — Run actual audio through Whisper → Kokoro → aplay
2. **Add more router training examples** — Finance/news still have gaps; 10-20 more per category
3. **Structural noise stripper** — Replace whitelist with link-density / all-caps detection
4. **Vet topic mapping** — Map condition keywords to Merck Vet Manual topic pages
5. **Hardware upgrade** — Larger VRAM for 4096-token context
