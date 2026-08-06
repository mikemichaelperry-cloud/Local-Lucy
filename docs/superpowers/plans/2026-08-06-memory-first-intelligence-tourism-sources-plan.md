# Local Lucy V11 — Memory-First Intelligence & Tourism Sources Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Local Lucy V11's memory/continuity failures, add usable Israel/general tourism sources, and verify both Gemma and Llama behave consistently without dual-model residency.

**Architecture:** Extend the existing SQLite memory service to store full assistant output, split context budget for continuations, and strengthen memory prompts. Add a trusted tourism fetcher for Israel (`israel.travel` / Go Israel / Wikivoyage) and generalise to Wikivoyage for other destinations. Enforce single-model residency in every model-touching stage and HMI test.

**Tech Stack:** Python 3.10, SQLite (WAL), pytest, Ollama, sentence-transformers, existing Local Lucy toolchain.

## Global Constraints

- Work only in `/home/mike/lucy-v11`; V10 must remain untouched.
- Every behavioural change must have a test or stage scenario.
- No dual Local Lucy model residency at any point during model tests.
- Travel/tourism must stay within trusted-sources policy; do not add open web search.
- Keep existing env vars and defaults unless explicitly overridden by new env vars.
- Commit each task independently; never combine unrelated fixes in one commit.
- Update `qualification/TEST_STATUS.json`, `TEST_TODO.md`, and `SESSION_HANDOFF.md` as phases complete.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/memory/memory_service.py` | SQLite schema, turn storage, retrieval, context assembly. |
| `tools/router_py/local_answer_core/engine.py` | Local model prompt building, truncation detection, model-aware shaping. |
| `tools/router_py/main.py` | Orchestration, memory persistence, location/search anaphora. |
| `tools/router_py/execution_engine/helpers.py` | Memory loading wrapper, budget enforcement. |
| `tools/unverified_context_trusted.py` | Trusted-source fetcher for travel/tourism. |
| `config/trust/generated/travel_runtime.txt` | Allowlisted travel domains. |
| `tools/router_py/model_residency.py` | New helper: single-model residency assertions. |
| `tools/router_py/test_memory_continuation.py` | New regression tests for continuation/recall. |
| `tools/router_py/test_travel_israel.py` | New tests for Israel tourism routing/fetch. |
| `tools/router_py/test_travel_general.py` | New tests for general-country Wikivoyage fetch. |
| `tools/router_py/stage_09_gemma_scenario_suite.py` | Extended Gemma memory scenarios. |
| `tools/router_py/stage_11_llama_scenario_suite.py` | Extended Llama memory scenarios + parity. |
| `tools/router_py/stage_13_model_switch.py` | Extended model-switch memory continuity. |
| `tools/router_py/stage_17_live_network.py` | Extended live-network travel cases. |

---

## Phase 1 — Memory-First Core

### Task 1: Store full assistant output for truncated turns

**Files:**
- Modify: `tools/memory/memory_service.py` (schema + `store_turn`)
- Modify: `tools/router_py/local_answer_core/engine.py` (return truncation signal)
- Modify: `tools/router_py/main.py` (persist `full_text`)
- Test: `tools/router_py/test_memory_continuation.py`

**Interfaces:**
- Consumes: `LocalAnswer.generate_answer` returns `(text, metadata)` where `metadata["truncated"]` is `True` when `finish_reason == "length"`.
- Produces: `memory_service.store_turn(session_id, role, text, full_text=None)` persists both columns.

- [ ] **Step 1: Add `full_text` column to schema**

In `tools/memory/memory_service.py`, locate `_SCHEMA` and add to `conversation_turns`:

```sql
full_text TEXT DEFAULT NULL,
truncated INTEGER DEFAULT 0
```

Add a migration block after schema creation:

```python
# Migration: ensure full_text/truncated columns exist for older DBs
cursor.execute("ALTER TABLE conversation_turns ADD COLUMN full_text TEXT DEFAULT NULL")
cursor.execute("ALTER TABLE conversation_turns ADD COLUMN truncated INTEGER DEFAULT 0")
```

Wrap each `ALTER TABLE` in `try/except sqlite3.OperationalError: pass` so reruns are safe.

- [ ] **Step 2: Update `store_turn` signature and insert**

Change:

```python
def store_turn(session_id: str, role: str, text: str, turn_index: int = None, metadata: dict = None):
```

to:

```python
def store_turn(session_id: str, role: str, text: str, turn_index: int = None, metadata: dict = None, full_text: str = None):
```

Inside the function, compute `truncated = 1 if full_text and full_text != text else 0`. Insert both columns.

- [ ] **Step 3: Return truncation from `LocalAnswer.generate_answer`**

In `tools/router_py/local_answer_core/engine.py`, locate where `_call_ollama` response is processed. Add to the returned dict/metadata:

```python
metadata["truncated"] = (response.get("done_reason") == "length" or response.get("finish_reason") == "length")
```

- [ ] **Step 4: Persist `full_text` in `main.py`**

In `tools/router_py/main.py:_persist_memory_turn()`, after calling the local model, pass `full_text=response_text if metadata.get("truncated") else None` to `store_turn`.

- [ ] **Step 5: Write failing test**

Create `tools/router_py/test_memory_continuation.py`:

```python
def test_truncated_turn_stores_full_text(tmp_path):
    from memory.memory_service import MemoryService
    svc = MemoryService(db_path=str(tmp_path / "mem.db"))
    svc.store_turn("s1", "assistant", "short visible", full_text="long full text that was truncated")
    rows = svc.get_recent_turns("s1", limit=1)
    assert rows[0]["text"] == "short visible"
    assert rows[0]["full_text"] == "long full text that was truncated"
    assert rows[0]["truncated"] == 1
```

- [ ] **Step 6: Run test to verify it fails**

```bash
cd /home/mike/lucy-v11 && python3 -m pytest tools/router_py/test_memory_continuation.py -v
```

Expected: FAIL because `full_text` column does not exist yet.

- [ ] **Step 7: Implement and rerun**

Apply schema/migration and `store_turn` changes, rerun the test.

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/memory/memory_service.py tools/router_py/test_memory_continuation.py
git commit -m "memory: store full_text for truncated assistant turns"
```

---

### Task 2: Continuation budget splitting

**Files:**
- Modify: `tools/router_py/execution_engine/helpers.py`
- Modify: `tools/memory/memory_service.py` (`assemble_context_with_telemetry`)
- Test: `tools/router_py/test_execution_engine_memory.py`

**Interfaces:**
- Consumes: `_load_session_memory_context_with_telemetry` passes `is_continuation` flag.
- Produces: Memory assembly reserves `LUCY_MEMORY_CONTINUATION_RESERVE_CHARS` for the most recent assistant turn when continuing.

- [ ] **Step 1: Add env var default**

In `tools/memory/memory_service.py`, add:

```python
LUCY_MEMORY_CONTINUATION_RESERVE_CHARS = int(os.environ.get("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "800"))
```

- [ ] **Step 2: Add continuation detection helper**

In `tools/router_py/execution_engine/helpers.py`, add:

```python
_CONTINUATION_RE = re.compile(
    r"\b(continue|go on|finish|complete|repeat that|say it again|tell me more|elaborate)\b",
    re.IGNORECASE,
)

def _is_continuation_query(query: str) -> bool:
    return bool(_CONTINUATION_RE.search(query or ""))
```

- [ ] **Step 3: Pass continuation flag to memory assembly**

Change `assemble_context_with_telemetry` signature to accept `is_continuation: bool = False`.

In `helpers.py:_load_session_memory_context_with_telemetry`, compute:

```python
is_continuation = _is_continuation_query(query)
```

and pass it through.

- [ ] **Step 4: Reserve continuation budget in assembly**

In `assemble_context_with_telemetry`:

```python
effective_max_chars = max_chars
if is_continuation:
    effective_max_chars = max(0, max_chars - LUCY_MEMORY_CONTINUATION_RESERVE_CHARS)
```

Use `effective_max_chars` for the main context assembly. Then append the most recent assistant turn (prefer `full_text` if truncated) up to `LUCY_MEMORY_CONTINUATION_RESERVE_CHARS`.

- [ ] **Step 5: Write test**

```python
def test_continuation_reserves_budget(monkeypatch):
    monkeypatch.setenv("LUCY_MEMORY_CONTINUATION_RESERVE_CHARS", "100")
    from router_py.execution_engine.helpers import _load_session_memory_context_with_telemetry
    text, telemetry = _load_session_memory_context_with_telemetry(
        session_id="s1", query="continue", max_chars=400
    )
    assert telemetry["continuation_reserve_chars"] == 100
    assert telemetry["memory_max_chars_used"] <= 300
```

- [ ] **Step 6: Run test, implement, commit**

Run test, fix until pass, then:

```bash
git add tools/memory/memory_service.py tools/router_py/execution_engine/helpers.py tools/router_py/test_execution_engine_memory.py
git commit -m "memory: reserve continuation budget and detect continuation queries"
```

---

### Task 3: Continuation re-generation prompt

**Files:**
- Modify: `tools/router_py/local_answer_core/engine.py`
- Test: `tools/router_py/test_memory_continuation.py`

**Interfaces:**
- Consumes: `_build_prompt` receives `session_memory` and `is_continuation` flag.
- Produces: Prompt contains continuation instruction when prior turn was truncated.

- [ ] **Step 1: Pass continuation flag to `_build_prompt`**

In `generate_answer`, compute `is_continuation` using the same helper or by checking the query. Pass to `_build_prompt`.

- [ ] **Step 2: Add continuation instruction**

In `_build_prompt`, after the memory block and before the current query, add when `is_continuation`:

```python
if is_continuation:
    lines.append("The previous answer was cut off. Continue from exactly where it left off. Do not repeat what has already been said.")
```

- [ ] **Step 3: Detect prior truncation**

When the most recent assistant turn has `truncated=1`, set `is_continuation=True` automatically even if the query is not an explicit continuation.

- [ ] **Step 4: Test**

```python
def test_continuation_prompt_includes_instruction():
    from router_py.local_answer_core.engine import LocalAnswer
    ans = LocalAnswer(model_name="local-lucy-llama31:latest")
    prompt = ans._build_prompt("continue", session_memory="previous: ...", is_continuation=True)
    assert "cut off" in prompt
```

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/local_answer_core/engine.py tools/router_py/test_memory_continuation.py
git commit -m "memory: add continuation re-generation instruction to prompt"
```

---

### Task 4: Strengthen memory-priority prompt instruction

**Files:**
- Modify: `tools/router_py/local_answer_core/engine.py` (`_build_prompt`)
- Modify: `tools/router_py/execution_engine/__init__.py` (augmented path)
- Test: `tools/router_py/test_local_answer.py` and `tools/router_py/test_execution_engine_memory.py`

- [ ] **Step 1: Update local model memory preamble**

Change the existing preamble in `_build_prompt` from:

```
The user has enabled session memory. Use the facts below to answer follow-up questions.
```

to:

```
The conversation history below is authoritative. Use it to answer the user's question.
If the user refers to something earlier, look at the history first.
```

- [ ] **Step 2: Update augmented path preamble**

In `tools/router_py/execution_engine/__init__.py`, update the augmented path memory block with the same stronger wording.

- [ ] **Step 3: Place memory after system persona, before current query**

Ensure the memory block appears immediately before the final `User:` / `Assistant:` exchange in both paths.

- [ ] **Step 4: Test**

```python
def test_memory_preamble_is_authoritative():
    from router_py.local_answer_core.engine import LocalAnswer
    ans = LocalAnswer(model_name="local-lucy-llama31:latest")
    prompt = ans._build_prompt("what did I say earlier?", session_memory="user: hello")
    assert "authoritative" in prompt
    assert prompt.find("authoritative") < prompt.find("User:")
```

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/local_answer_core/engine.py tools/router_py/execution_engine/__init__.py tools/router_py/test_local_answer.py tools/router_py/test_execution_engine_memory.py
git commit -m "memory: strengthen memory-authority prompt instruction"
```

---

### Task 5: Model-aware prompt shaping

**Files:**
- Modify: `tools/router_py/local_answer_core/engine.py`
- Test: `tools/router_py/test_stage_07_prompt_parity.py`

**Interfaces:**
- Consumes: `model_name` string (e.g., `local-lucy-gemma4:latest`, `local-lucy-llama31:latest`).
- Produces: Slightly different preamble repetition/instruction format per model family.

- [ ] **Step 1: Add `PromptShaper` class**

Create a small nested class or module function:

```python
class _PromptShaper:
    @staticmethod
    def memory_preamble(model_name: str) -> str:
        family = "gemma" if "gemma" in model_name.lower() else "llama"
        base = "The conversation history below is authoritative. Use it to answer the user's question."
        if family == "gemma":
            return base + " If the user refers to something earlier, look at the history first."
        return base
```

- [ ] **Step 2: Use shaper in `_build_prompt`**

Replace the hardcoded preamble with `_PromptShaper.memory_preamble(self.model_name)`.

- [ ] **Step 3: Test parity**

Ensure both model names produce the core authoritative message; only the optional clause differs.

```python
def test_prompt_shaper_per_model_family():
    from router_py.local_answer_core.engine import _PromptShaper
    assert "authoritative" in _PromptShaper.memory_preamble("local-lucy-llama31:latest")
    assert "authoritative" in _PromptShaper.memory_preamble("local-lucy-gemma4:latest")
```

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/local_answer_core/engine.py tools/router_py/test_stage_07_prompt_parity.py
git commit -m "memory: add thin model-family prompt shaper"
```

---

### Task 6: Phase 1 regression gate

- [ ] **Step 1: Run memory-service tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/tests/test_memory_service_unit.py tools/tests/test_memory_requalification.py tools/router_py/test_execution_engine_memory.py tools/router_py/test_memory_gate.py tools/router_py/test_local_answer.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 2: Run router_py fast tests**

```bash
python3 -m pytest tools/router_py -v --tb=short -m "not slow and not live"
```

Expected: all pass.

- [ ] **Step 3: Update status**

Update `qualification/TEST_TODO.md` and `qualification/TEST_STATUS.json` to mark Phase 1 tasks complete.

- [ ] **Step 4: Commit**

```bash
git add qualification/TEST_TODO.md qualification/TEST_STATUS.json
git commit -m "status: mark Phase 1 memory core complete"
```

---

## Phase 2 — Tourism & Travel Sources

### Task 7: Improve Israel destination extraction

**Files:**
- Modify: `tools/unverified_context_trusted.py`
- Test: `tools/router_py/test_travel_israel.py`

- [ ] **Step 1: Add Israel keyword map**

In `_TRAVEL_DESTINATION_MAP`, ensure:

```python
"israel": "Israel",
"eretz": "Israel",
"tel aviv": "Tel Aviv",
"jerusalem": "Jerusalem",
"haifa": "Haifa",
"eilat": "Eilat",
"galilee": "Galilee",
"dead sea": "Dead Sea",
"negev": "Negev",
```

- [ ] **Step 2: Improve `_extract_travel_destination`**

Handle patterns:
- “recommend places to visit in Israel”
- “what should I see in Jerusalem?”
- “things to do in Tel Aviv”

Use regex `(?:in|to|visit|see|do)\s+(?:the\s+)?([A-Z][A-Za-z\s]+)` and map against `_TRAVEL_DESTINATION_MAP`.

- [ ] **Step 3: Test**

```python
def test_israel_destination_extraction():
    from unverified_context_trusted import _extract_travel_destination
    assert _extract_travel_destination("places to visit in Israel") == "Israel"
    assert _extract_travel_destination("what to see in Jerusalem") == "Jerusalem"
```

- [ ] **Step 4: Commit**

```bash
git add tools/unverified_context_trusted.py tools/router_py/test_travel_israel.py
git commit -m "travel: improve Israel destination extraction"
```

---

### Task 8: Add Israel Ministry of Tourism fetcher

**Files:**
- Modify: `tools/unverified_context_trusted.py`
- Modify: `config/trust/generated/travel_runtime.txt`
- Test: `tools/router_py/test_travel_israel.py`

- [ ] **Step 1: Update allowlist**

Append to `config/trust/generated/travel_runtime.txt`:

```
israel.travel
goisrael.com
```

- [ ] **Step 2: Implement Israel fetcher**

Add function `_fetch_israel_travel_summary(destination: str) -> dict`:

```python
def _fetch_israel_travel_summary(destination: str) -> dict:
    urls = [
        f"https://israel.travel/en/{destination.lower().replace(' ', '-')}",
        f"https://goisrael.com/en/{destination.lower().replace(' ', '-')}",
    ]
    for url in urls:
        try:
            text = _fetch_url_text(url, timeout=10)
            if text:
                return {"source": url, "text": _extract_opengraph_description(text) or text[:1500]}
        except Exception:
            continue
    return None
```

- [ ] **Step 3: Wire into `_format_travel_response`**

When destination is in Israel keyword set, call `_fetch_israel_travel_summary`. If it returns content, use it. Otherwise fall back to Wikivoyage.

- [ ] **Step 4: Add 24-hour cache**

In `~/.local/share/local-lucy-v11/state/travel_cache.json`, cache key `destination|source`. TTL 24h via `LUCY_TRAVEL_CACHE_TTL_SECONDS` (default 86400).

- [ ] **Step 5: Test with mocked fetch**

```python
def test_israel_fetcher_uses_allowlisted_source(monkeypatch):
    monkeypatch.setattr("unverified_context_trusted._fetch_url_text", lambda url, timeout: "Israel tourism content")
    from unverified_context_trusted import _fetch_israel_travel_summary
    result = _fetch_israel_travel_summary("Israel")
    assert "israel.travel" in result["source"] or "goisrael" in result["source"]
```

- [ ] **Step 6: Commit**

```bash
git add tools/unverified_context_trusted.py config/trust/generated/travel_runtime.txt tools/router_py/test_travel_israel.py
git commit -m "travel: add Israel Ministry of Tourism / Go Israel fetcher with cache"
```

---

### Task 9: Generalise travel to Wikivoyage

**Files:**
- Modify: `tools/unverified_context_trusted.py`
- Modify: `config/trust/generated/travel_runtime.txt`
- Test: `tools/router_py/test_travel_general.py`

- [ ] **Step 1: Extend destination map for major countries/cities**

Add entries for at least: UK, France, Germany, Italy, Spain, Japan, Thailand, USA, Canada, Australia, Egypt, Greece.

- [ ] **Step 2: Improve Wikivoyage fetch**

Use `https://en.wikivoyage.org/api/rest_v1/page/summary/{page}` where `page` is the destination title with spaces replaced by underscores.

```python
def _fetch_wikivoyage_summary(destination: str) -> dict:
    page = destination.replace(" ", "_")
    url = f"https://en.wikivoyage.org/api/rest_v1/page/summary/{page}"
    data = _fetch_json(url, timeout=10)
    if data and "extract" in data:
        return {"source": url, "text": data["extract"], "title": data.get("title", destination)}
    return None
```

- [ ] **Step 3: Use Wikivoyage as primary for non-Israel destinations**

In `_format_travel_response`:
- If destination in Israel set → try Israel source, then Wikivoyage.
- Else → try Wikivoyage.
- If all fail → return safe fallback asking user to specify country/region.

- [ ] **Step 4: Add per-country ministry fallback (optional, later)**

Document in code that per-country ministry sites can be added to `travel_runtime.txt` and `_try_direct_fetch` without changing routing.

- [ ] **Step 5: Test**

```python
def test_wikivoyage_general_destination(monkeypatch):
    monkeypatch.setattr("unverified_context_trusted._fetch_json", lambda url, timeout: {"extract": "Japan travel guide", "title": "Japan"})
    from unverified_context_trusted import _fetch_wikivoyage_summary
    result = _fetch_wikivoyage_summary("Japan")
    assert "Japan" in result["text"]
```

- [ ] **Step 6: Commit**

```bash
git add tools/unverified_context_trusted.py config/trust/generated/travel_runtime.txt tools/router_py/test_travel_general.py
git commit -m "travel: generalise to Wikivoyage for arbitrary destinations"
```

---

### Task 10: Update travel routing to use trusted provider

**Files:**
- Modify: `tools/router_py/policy_router/gates.py` (if needed)
- Modify: `tools/router_py/pipeline/route.py`
- Test: `tools/router_py/test_travel_routing.py`

- [ ] **Step 1: Keep travel advisory on trusted**

No change to `apply_critical_source_policy` for `travel_advisory` — still forced to `EVIDENCE/trusted`.

- [ ] **Step 2: Allow tourism recommendations via trusted provider**

For queries matching `gate_travel_tourism` but NOT containing safety/advisory keywords, route `AUGMENTED` with `provider="trusted"`, `evidence_reason="travel_tourism"`.

Safety/advisory keywords: “dangerous,” “safe,” “warning,” “advisory,” “current situation,” “war,” “conflict,” “terrorism.”

- [ ] **Step 3: Clear message on source failure**

When trusted travel fetch returns no content, produce:

```
I don't have current trusted travel information for that destination. Please specify the country or region, or enable a broader source.
```

- [ ] **Step 4: Test**

```python
def test_tourism_recommendation_routes_augmented_trusted():
    from router_py.pipeline.route import select_route_for_question
    result = select_route_for_question("recommend places to visit in Israel")
    assert result.route == "AUGMENTED"
    assert result.provider == "trusted"
```

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/policy_router/gates.py tools/router_py/pipeline/route.py tools/router_py/test_travel_routing.py
git commit -m "travel: route tourism recommendations to trusted provider"
```

---

### Task 11: Phase 2 regression gate

- [ ] **Step 1: Run travel tests**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py/test_travel_routing.py tools/router_py/test_travel_israel.py tools/router_py/test_travel_general.py tools/router_py/test_policy_router.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 2: Update status**

Update `qualification/TEST_TODO.md` and `qualification/TEST_STATUS.json`.

- [ ] **Step 3: Commit**

```bash
git add qualification/TEST_TODO.md qualification/TEST_STATUS.json
git commit -m "status: mark Phase 2 tourism sources complete"
```

---

## Phase 3 — Verification & Cross-Model Guarantees

### Task 12: Add model residency helper

**Files:**
- Create: `tools/router_py/model_residency.py`
- Test: `tools/router_py/test_model_residency.py`

- [ ] **Step 1: Implement helper**

```python
import subprocess
from typing import List

LOCAL_LUCY_MODEL_PREFIXES = ("local-lucy-",)

def list_loaded_ollama_models() -> List[str]:
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10, check=False)
        lines = out.stdout.strip().splitlines()
        return [line.split()[0] for line in lines[1:] if line.strip()]
    except Exception:
        return []

def get_local_lucy_loaded_models() -> List[str]:
    return [m for m in list_loaded_ollama_models() if any(m.startswith(p) for p in LOCAL_LUCY_MODEL_PREFIXES)]

def assert_single_local_lucy_model(label: str = "") -> None:
    loaded = get_local_lucy_loaded_models()
    if len(loaded) > 1:
        raise RuntimeError(f"{label}: more than one Local Lucy model loaded: {loaded}")
```

- [ ] **Step 2: Test**

```python
def test_residency_helper_detects_multiple(monkeypatch):
    from router_py.model_residency import get_local_lucy_loaded_models
    monkeypatch.setattr("router_py.model_residency.list_loaded_ollama_models", lambda: ["local-lucy-gemma4:latest", "local-lucy-llama31:latest"])
    assert len(get_local_lucy_loaded_models()) == 2
```

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/model_residency.py tools/router_py/test_model_residency.py
git commit -m "verification: add model residency assertion helper"
```

---

### Task 13: Enforce residency in stage scripts

**Files:**
- Modify: `tools/router_py/stage_08_gemma_smoke.py`
- Modify: `tools/router_py/stage_10_llama_smoke.py`
- Modify: `tools/router_py/stage_09_gemma_scenario_suite.py`
- Modify: `tools/router_py/stage_11_llama_scenario_suite.py`
- Modify: `tools/router_py/stage_13_model_switch.py`
- Modify: `tools/router_py/stage_16_hmi_soak.py`

- [ ] **Step 1: Add import and before/after checks**

At the top of each script:

```python
from router_py.model_residency import assert_single_local_lucy_model, get_local_lucy_loaded_models
```

At start:

```python
assert_single_local_lucy_model("start")
```

At end:

```python
assert_single_local_lucy_model("end")
loaded_after = get_local_lucy_loaded_models()
assert len(loaded_after) <= 1, loaded_after
```

- [ ] **Step 2: Commit**

```bash
git add tools/router_py/stage_*.py
git commit -m "verification: enforce single-model residency in all model stages"
```

---

### Task 14: Extend Gemma and Llama scenario suites with memory cases

**Files:**
- Modify: `tools/router_py/stage_09_gemma_scenario_suite.py`
- Modify: `tools/router_py/stage_11_llama_scenario_suite.py`

- [ ] **Step 1: Add shared memory scenarios**

Add scenarios:
- `S09-MEM-001`: Tell a 500-word story, ask to continue, verify completion.
- `S09-MEM-002`: Ask a question, then “what did I ask earlier?”
- `S09-MEM-003`: State a fact, then “what did I say about X?”
- `S09-MEM-004`: Correction — state a fact, then correct it, then ask current value.

- [ ] **Step 2: Implement outcome parity assertion**

For Llama scenarios, assert that the answer contains the same key entities as the Gemma baseline (recorded in a JSON fixture).

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/stage_09_gemma_scenario_suite.py tools/router_py/stage_11_llama_scenario_suite.py
git commit -m "verification: add cross-model memory continuity scenarios"
```

---

### Task 15: Extend model switch with memory continuity

**Files:**
- Modify: `tools/router_py/stage_13_model_switch.py`

- [ ] **Step 1: Add memory switch scenario**

After the existing switch steps, add:

1. On Gemma: “Tell me a short story about Oscar.”
2. Switch to Llama.
3. On Llama: “Continue the story.”
4. Verify the answer references Oscar and continues the prior narrative.

- [ ] **Step 2: Commit**

```bash
git add tools/router_py/stage_13_model_switch.py
git commit -m "verification: model switch preserves memory continuity"
```

---

### Task 16: Add HMI residency assertions

**Files:**
- Modify: `tools/router_py/test_hmi_real_routing.py`

- [ ] **Step 1: Add residency check after local-model requests**

After each request that routes LOCAL, call `assert_single_local_lucy_model(f"after {test_name}")`.

- [ ] **Step 2: Commit**

```bash
git add tools/router_py/test_hmi_real_routing.py
git commit -m "verification: assert single-model residency in HMI real-routing tests"
```

---

### Task 17: Phase 3 regression gate

- [ ] **Step 1: Run model smoke and switch**

```bash
cd /home/mike/lucy-v11
python3 tools/router_py/stage_08_gemma_smoke.py
python3 tools/router_py/stage_10_llama_smoke.py
python3 tools/router_py/stage_13_model_switch.py
```

Expected: all pass, no dual residency.

- [ ] **Step 2: Update status**

Update `qualification/TEST_TODO.md` and `qualification/TEST_STATUS.json`.

- [ ] **Step 3: Commit**

```bash
git add qualification/TEST_TODO.md qualification/TEST_STATUS.json
git commit -m "status: mark Phase 3 verification complete"
```

---

## Phase 4 — Reporting & Final Qualification

### Task 18: Run full qualification

- [ ] **Step 1: Full deterministic regression**

```bash
cd /home/mike/lucy-v11
python3 -m pytest tools/router_py -v --tb=short
```

Expected: zero new failures.

- [ ] **Step 2: Memory-service suite**

```bash
python3 -m pytest tools/tests/test_memory_service_unit.py tools/tests/test_memory_requalification.py -v --tb=short
```

Expected: all pass.

- [ ] **Step 3: Final clean run**

```bash
python3 tools/router_py/stage_19_clean_run.py
```

Expected: 7/7 passed (or more if stages added).

- [ ] **Step 4: Commit result recordings**

```bash
git add qualification/results/
git commit -m "requal: record final clean-run results after memory+tourism upgrade"
```

---

### Task 19: Update reports and handoff

**Files:**
- Modify: `qualification/TEST_STATUS.json`
- Modify: `qualification/TEST_TODO.md`
- Modify: `qualification/SESSION_HANDOFF.md`
- Create: `qualification/COMPLETION_REPORT_2026-08-06_MEMORY_TOURISM.md`

- [ ] **Step 1: Update status and todo**

Mark all new tasks complete. Record test counts.

- [ ] **Step 2: Write completion report**

Summarise:
- What changed (memory core, tourism sources, verification).
- Test results.
- Known limitations.
- Next recommendations.

- [ ] **Step 3: Update handoff**

Update `qualification/SESSION_HANDOFF.md` with final commits, test counts, and what is safe to run next.

- [ ] **Step 4: Copy to desktop and archive stale**

```bash
cp qualification/COMPLETION_REPORT_2026-08-06_MEMORY_TOURISM.md "/home/mike/Desktop/Local Lucy V11/"
cp qualification/SESSION_HANDOFF.md "/home/mike/Desktop/Local Lucy V11/"
```

Archive old desktop report/handoff to `Local_Lucy_V11_Archive/`.

- [ ] **Step 5: Commit**

```bash
git add qualification/TEST_STATUS.json qualification/TEST_TODO.md qualification/SESSION_HANDOFF.md qualification/COMPLETION_REPORT_2026-08-06_MEMORY_TOURISM.md
git commit -m "docs: final status, handoff and completion report for memory+tourism upgrade"
```

---

## Self-Review Checklist

- [ ] Spec coverage: every design section (§4.1–§4.6, §5.1–§5.4, §6.1–§6.3) has at least one task.
- [ ] Placeholder scan: no “TBD”, “TODO”, or vague “handle edge cases” steps.
- [ ] Type consistency: `store_turn`, `assemble_context_with_telemetry`, `_build_prompt` signatures match across tasks.
- [ ] Testability: every task ends with a runnable test and expected result.
- [ ] No V10 touches: all paths are under `/home/mike/lucy-v11`.
- [ ] No open web search for travel: all tourism routes use `trusted` provider with allowlisted domains.
- [ ] Single-model residency: every model stage and HMI test has residency assertions.
