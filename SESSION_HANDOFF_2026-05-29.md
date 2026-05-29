# Local Lucy V10 — Session Handoff
**Date:** 2026-05-29  
**Session focus:** Persistent memory SQL migration, self-knowledge fix, routing guards, voice pipeline audit, HMI memory dialog  
**Branch:** `main` (tracks V10)

---

## ✅ What Was Done

### 1. Persistent Memory — SQL-Native (Major)
- **`tools/memory/memory_service.py`**: Added `persistent_facts` table (`id`, `fact_text`, `category`, `created_at`)
- **`tools/memory_cli.py`**: New CLI for CRUD — `list`, `add`, `delete`, `import-memory-txt`, `reset`
- **`tools/router_py/local_answer.py`**: Replaced legacy `memory/memory.txt` text-file loader with `_get_persistent_facts()` from SQLite. Facts injected as `[PERSISTENT FACTS]` block in every LOCAL prompt.
- **Deprecated**: `memory/memory.txt` moved to `memory.txt.deprecated`, `lucy-mem.sh`/`lucy-mem-approve.sh`/`lucy-mem-commit.sh` marked legacy.
- **Deleted**: `runtime/lucy_core.py` (hardcoded V8 paths, unreachable in V10)

### 2. Self-Knowledge Fix (Critical)
- **Root cause**: `_strip_identity_preamble()` was cutting "I am Local Lucy..." off **every** response, including answers to "Who are you?"
- **Fix**: Made `_strip_identity_preamble` conditional — preserves identity preamble when query is about identity ("who are you", "what is your name", "tell me about yourself", "introduce yourself")
- **Bonus**: Compressed `SELF_KNOWLEDGE` from **1028 → ~188 tokens** to free up context window
- **Cache**: Added SELF_KNOWLEDGE hash to cache key so prompt changes auto-invalidate stale cache entries

### 3. Ollama Modelfile Sync
- **Updated**: `config/Modelfile.local-lucy` and `config/Modelfile.local-lucy-fast`
  - Changed "No internet access" → "Internet access via AUGMENTED/NEWS/WEATHER"
  - Changed "No persistent memory unless explicitly enabled" → "Persistent memory loaded automatically when relevant"
- **Rebuilt**: `ollama create local-lucy-fast --file config/Modelfile.local-lucy-fast`

### 4. Personal/Family Routing Guard
- **`tools/router_py/classify.py`**: Added `_is_personal_family_query()` guard
  - Catches: "my children", "my wife", "my dog", "who are my...", "how many children do I have", "do I have any kids", "tell me about my family"
  - Forces LOCAL route before embedding router runs
  - Prevents "Who are my children?" from routing to Wikipedia (soap opera)

### 5. Voice Pipeline Audit
- **Fixed**: `tools/router_py/streaming_tts.py` — missing `import os` (would crash)
- **Fixed**: `tools/router_py/voice_tool.py` — implemented missing `VoicePipeline.voice_interaction()` method so `quick_voice_interaction()` works end-to-end
- **Not tested live**: Actual audio recording/playback not verified in this session

### 6. HMI Memory Management Dialog
- **`ui-v10/app/widgets/memory_manager_dialog.py`**: New Qt dialog for viewing/adding/deleting persistent facts
- **`ui-v10/app/panels/control_panel.py`**: Added "Manage Memory Facts" button in Actions group
- **Not tested live**: Qt app not launched to verify visual rendering

### 7. Tests
- **66/66 unit tests passing**: `test_local_answer.py` (28), `test_memory_gate.py` (18), `test_classify.py` (20)

---

## ⚠️ Known Issues / Release Blockers

### High Priority

| Issue | Details | Path Forward |
|-------|---------|--------------|
| **"How many children do I have?"** | qwen3 counts stepchildren as children despite explicit "biological children" fact. Model conflates terminology regardless of prompt instructions. | Model-level: needs fine-tuning or semantic fact-retriever (inject only relevant facts per query) |
| **"Do I have any kids?"** | qwen3 privacy guardrail refuses. Prompt engineering, few-shot examples, and instruction rewording all failed. | Model-level limitation. Accept for now. |
| **Token bloat** | All 10 facts injected into EVERY LOCAL prompt (~200 tokens). At 50 facts this becomes unsustainable. | Build a semantic fact-retriever: embed facts, do similarity search against query, inject only top-k |
| **Embedding router lacks family examples** | Keyword guard is a safety net. The 899-example embedding index has zero family/personal examples. | Add ~10-20 training examples to `comprehensive_examples.json` + rebuild embeddings |
| **Finance/news keywords still fall through** | "gold price", "stock market today", "todays headlines" → LOCAL due to low embedding confidence | Expand keyword guards in `classify.py` or add training examples |
| **Ollama cold start** | First query after idle ~2.7s, warm ~0.5s | Add background warmup ping (thread that hits Ollama every N minutes) or bump `keep_alive` |

### Medium Priority

| Issue | Details |
|-------|---------|
| **Voice not tested end-to-end** | Fixed code bugs but never ran actual audio through Whisper → Kokoro → aplay |
| **HMI memory dialog not visually verified** | Code written, Qt app not launched |
| **num_ctx stuck at 2048** | Need hardware upgrade (VRAM at 11.5/12GB). qwen3:14b at 4096 ctx = ~10.5GB, no headroom for Whisper GPU |

---

## 📁 Key Files Changed

```
config/Modelfile.local-lucy              # Updated SYSTEM prompt
config/Modelfile.local-lucy-fast         # Updated SYSTEM prompt
memory/memory.txt                        # DELETED (moved to .deprecated)
runtime/lucy_core.py                     # DELETED

# New files:
tools/memory_cli.py                      # CLI for persistent facts CRUD
ui-v10/app/widgets/memory_manager_dialog.py  # Qt memory dialog

# Modified:
tools/memory/memory_service.py           # Added persistent_facts table + CRUD
tools/router_py/local_answer.py          # SQL facts injection, SELF_KNOWLEDGE compression, cache key fix, identity strip fix
tools/router_py/classify.py              # Personal/family routing guard
tools/router_py/streaming_tts.py         # Added missing `import os`
tools/router_py/voice_tool.py            # Implemented voice_interaction() method
tools/router_py/test_local_answer.py     # Updated tests for new behavior
ui-v10/app/panels/control_panel.py       # Added "Manage Memory Facts" button
tools/lucy-mem.sh                        # Marked deprecated
tools/lucy-mem-approve.sh                # Marked deprecated
tools/lucy-mem-commit.sh                 # Marked deprecated
```

---

## 🧠 Current Memory State (SQLite)

Run `python tools/memory_cli.py list` to see current facts. As of this session:

```
1. Mike's biological children are Tom, Sahar, and Kim.
2. Netta is Rachel's daughter from Rachel's previous marriage. Netta is Mike's stepdaughter, not his biological child.
3. Omer is Rachel's son from Rachel's previous marriage. Omer is Mike's stepson, not his biological child.
4. Oscar is Mike's dog. He has a fixation on cats; training approach uses leave-it, distance, and reward.
5. Netta is an adult.
6. Omer is an adult.
7. Tom is an adult.
8. Sahar is an adult.
9. Kim is an adult.
10. Mike has two grandchildren: Nibar and Arbel.
```

---

## 🚀 Next Session Recommendations

1. **Semantic fact-retriever** — Most impactful. Embed facts, similarity-search against query, inject only top-k. Solves token bloat + "children" counting bug.
2. **Router training examples** — Add 10-20 family/personal + 10-20 finance/news examples to `comprehensive_examples.json`, rebuild embeddings.
3. **Warmup ping** — Background thread to keep Ollama model hot. 5-line change, big UX win.
4. **Live voice test** — Actually run audio through the pipeline.
5. **Git commit + push** — All changes are staged and ready.
