# ChatGPT Review Report (Memory-Aware Routing + NEWS Region Filter Enforcement)
Date: February 26, 2026
Time: 22:38:35 +0200

- Project root: `/home/mike/lucy/snapshots/opt-experimental-v2-dev`
- Snapshot (Opt primary dev line): `/home/mike/lucy/snapshots/opt-experimental-v2-dev`
- Frozen baseline (immutable): `/home/mike/lucy/snapshots/FROZEN/opt-experimental-v1-FROZEN-20260224`
- Latest continuity handoff used: `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T22-22-41+0200.md`
- Technical implementation handoff used for active code context: `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/SESSION_HANDOFF_2026-02-26T22-02-15+0200.md`

## 1. Session Goal
Implement two structural routing fixes identified from a manual transcript analysis:

1. NEWS region filtering for prompts like `Whats the latest Australian news?` (prevent silent fallback to global feeds).
2. Memory-aware routing for pronoun-based follow-ups like `Do you know if he likes cats?` after session memory contains a recent referent (e.g., `Oscar is our dog.`).

User explicitly deprioritized the optional numeric consistency guard (`809` vs `807`) for this session.

## 2. Final Outcome (Summary)
Status: PASS

Implemented and validated:
- Deterministic `region_filter` detection in router classifier for NEWS prompts (`IL`, `AU`, `GB`) with explicit pattern matching.
- Deterministic region-specific NEWS key enforcement in `lucy_chat.sh` key seeding path.
- Deterministic no-fallback behavior when a region is detected but no region-specific feeds are configured.
- Memory-aware pronoun routing layer in classifier (pre-routing) using session memory file/context.
- Narrow memory override guardrails (no override for explicit recency/news/web/source requests; requires exactly one candidate entity).
- Regression fix for classifier false-positive NEWS routing caused by substring `now` matching inside `know`.
- New and updated regressions covering AU region filtering and memory-pronoun routing.

Result:
- `Whats the latest Australian news?` now routes as NEWS with `region_filter=AU`, and the executor enforces AU-only NEWS keys (no silent world-feed contamination).
- If AU-specific keys are not configured, the system returns a deterministic message instead of silently using global feeds.
- `Do you know if he likes cats?` can now remain local (`needs_web=false`) when session memory has one clear referent.

## 3. Why These Were Structural Routing Defects (Not Model Issues)
### 3.1 NEWS region issue
Before this session:
- Classifier detected NEWS intent, but emitted no geographic source filter (`region_filter` absent / null).
- Executor selected keys via mapping/fallback without enforcing geographic subset semantics.
- This allowed prompts explicitly requesting regional news sources to degrade into world/global feeds.

This is a routing/execution planning defect because:
- The requested scope (regional sourcing) was present in the prompt.
- The system had no deterministic representation of that constraint to pass into execution.

### 3.2 Memory-aware pronoun issue
Before this session:
- Routing was finalized before any memory-based referent reasoning.
- Generic interrogative/time-sensitive heuristics could push pronoun follow-ups into web/news paths.
- Session memory injection only happened later in the local-answer producer path, after routing.

This is a routing order defect because:
- The prompt semantics (`he`) depend on prior session context.
- The router must consider session memory *before* deciding `needs_web` for such prompts.

## 4. Architectural Approach Chosen
### 4.1 Keep classifier deterministic and narrow
No NLP dependency was introduced.
Changes use:
- regex pattern matching
- small alias maps
- deterministic session-memory parsing heuristics

### 4.2 Memory-aware override is guarded, not broad
The new memory-aware routing candidate applies only when:
- pronouns are present (`he/she/it/they` and common variants), and
- no explicit recency/news indicators are present, and
- no explicit source/web request indicators are present, and
- exactly one candidate entity can be extracted from recent session memory.

This avoids over-triggering LOCAL routing in ambiguous contexts.

### 4.3 Region filtering enforced at NEWS key seeding (not just classification)
Classifier now emits `region_filter`, but execution also enforces it in `seed_evidence_session()`.
This is defense-in-depth against query-to-key mappings that mix region keys with global keys.

## 5. Code Changes Applied (Detailed)
### 5.1 `tools/router/classify_intent.py`
Primary changes:
- Added session memory loading helpers:
  - reads `LUCY_SESSION_MEMORY_CONTEXT` (if present)
  - otherwise reads launcher/NL memory files via `LUCY_CHAT_MEMORY_FILE` / `LUCY_NL_MEMORY_FILE`
- Added deterministic session-memory entity extraction from recent memory lines (`User:` / `Assistant:` blocks)
- Added `memory_routing_candidate()` to detect pronoun follow-ups that should remain local
- Added `NEWS_REGION_ALIASES` and `detect_news_region_filter()` for `AU`, `IL`, `GB`
- Added `region_filter` field to plan JSON (default `null`)
- Added `routing_reason="MEMORY_CONTEXT"` and `memory_entity` metadata when memory override applies
- Added `has_time_trigger_phrase()` and replaced substring `has_any(time_triggers)` NEWS detection to prevent false matches (e.g., `know` accidentally matching `now`)
- Prevented generic NEWS heuristic from stomping a `memory_context` decision

Behavioral effect:
- `Do you know if he likes cats?` + a single clear session-memory referent can remain `LOCAL_KNOWLEDGE` / `needs_web=false`
- `Whats the latest Australian news?` emits `intent=WEB_NEWS` and `region_filter=AU`

### 5.2 `lucy_chat.sh`
Primary changes:
- `route_with_classifier_mapper()` now returns classifier `region_filter` as an additional output line
- Added process-wide `CURRENT_NEWS_REGION_FILTER` to thread route metadata into `run_news()` in router-bypass execution mode
- Added `news_region_key_prefix()` mapping:
  - `IL -> news_israel_`
  - `AU -> news_au_`
  - `GB -> news_gb_`
- Added `filter_news_keys_by_region()` to enforce region-only NEWS key subsets
- Updated `seed_evidence_session()` to accept optional `news_region_filter`
- If region detected but region-specific keys are absent after filtering, returns deterministic message:
  - `No region-specific feeds configured for <REGION>.`
  - and does not silently fall back to world/global keys
- Updated `run_news()` to call region-aware seeding and surface deterministic no-config message cleanly
- Main routing path now captures `region_filter` from router output and sets `CURRENT_NEWS_REGION_FILTER`

Behavioral effect:
- Mixed query mappings (e.g., `news_au_*` plus `news_world_*`) no longer leak world keys into AU-targeted NEWS requests.

### 5.3 `tools/router/execute_plan.sh`
Primary changes:
- Reads `region_filter` from classifier plan JSON
- Includes `REGION_FILTER` in dry-run output for easier inspection
- Passes `LUCY_NEWS_REGION_FILTER=<region>` into `lucy_chat.sh` when invoking router-bypass execution

Intent:
- Preserve parity for direct `execute_plan.sh` usage and tests, not only the in-process `lucy_chat.sh` routing path.

### 5.4 `tools/router/router_regression.sh` (updated)
Added coverage for:
- `region_filter=IL` for Israel-news prompt
- `region_filter=AU` for Australian-news prompts
- memory-aware pronoun routing using a temporary launcher-style session memory file containing:
  - `User: Oscar is our dog.`
  - then classifier check for `Do you know if he likes cats?`

### 5.5 `tools/tests/test_news_region_filter_au_enforcement.sh` (new)
New end-to-end regression validates:
1. AU-targeted prompt with mixed query mapping keys (`news_au_*` + `news_world_*`) results in AU-only seeded keys.
2. AU-targeted prompt with no `news_au_*` keys configured returns deterministic no-config message and does not fall back to `news_world_*`.

## 6. Defects Encountered During Implementation (and Fixes)
### 6.1 Hidden classifier false-positive: `know` triggered NEWS via substring `now`
Observed during regression run:
- New memory-pronoun routing test still returned `WEB_NEWS` unexpectedly.

Root cause:
- Existing NEWS heuristic used substring matching (`has_any(time_triggers)`), and `now` matched inside `know`.
- Prompt `Do you know if he likes cats?` was incorrectly treated as time-sensitive.

Fix:
- Replaced substring-based time trigger detection with regex word-boundary matching (`has_time_trigger_phrase()`)
- Added guard to avoid generic NEWS override when `category == "memory_context"`

Status:
- Fixed in same session; regression passes.

## 7. Regression / Validation Results (This Session)
All listed checks passed.

### 7.1 Syntax / parse checks
- `bash -n` on changed shell scripts:
  - `lucy_chat.sh`
  - `tools/router/execute_plan.sh`
  - `tools/router/router_regression.sh`
  - `tools/tests/test_news_region_filter_au_enforcement.sh`
- `python3 -m py_compile`:
  - `tools/router/classify_intent.py`
  - `tools/router/plan_to_pipeline.py`

### 7.2 New / updated targeted regressions
- `tools/router/router_regression.sh`
  - PASS (includes new AU region filter and memory-pronoun routing assertions)
- `tools/tests/test_news_region_filter_au_enforcement.sh`
  - PASS
  - validates AU-only key seeding and deterministic no-config behavior

### 7.3 Existing high-signal regressions re-run after routing changes
- `tools/tests/test_news_israel_specificity_no_warning_leak.sh`
  - PASS
  - confirms NEWS warning suppression and Israel key specificity still hold
- `tools/tests/test_lucy_chat_router_forced_mode_strict.sh`
  - PASS
  - confirms router-forced mode behavior unchanged by new route metadata threading

## 8. User-Facing Behavioral Changes (Expected)
### 8.1 Regional NEWS prompts
Examples:
- `Whats the latest Australian news?`
- `Whats the latest news from Australian sources?`

Expected now:
- Classifier emits `WEB_NEWS` + `region_filter=AU`
- NEWS execution seeds only `news_au_*` keys
- If none exist, returns:
  - `No region-specific feeds configured for AU.`

No silent fallback to global/world NEWS keys.

### 8.2 Memory-pronoun follow-up prompts
Example sequence:
- `Oscar is our dog.`
- `Do you know if he likes cats?`

Expected now (when memory file/context is present and unambiguous):
- Classifier keeps route local (`LOCAL_KNOWLEDGE`, `needs_web=false`)
- Memory-aware resolution can happen in the local path instead of misrouting to NEWS/web

## 9. Guardrails / Intentional Limits
- Memory-aware routing does **not** override explicit recency/news/source requests.
- Memory-aware routing requires exactly one candidate referent from recent memory (ambiguity -> no forced LOCAL override).
- No new broad NLP or probabilistic entity resolution was introduced.
- Region support implemented this session is intentionally small and explicit (`IL`, `AU`, `GB`).
- `GB` support is classifier/executor-ready, but effective behavior depends on presence of `news_gb_*` keys in configured allowlists/query maps.

## 10. Deferred / Not Implemented (By User Choice)
### 10.1 Numeric entity consistency guard
The optional deterministic post-generation numeric token validator (e.g., prompt `809` vs response `807`) was not implemented in this session because the user explicitly stated they will provide context and did not require this hardening now.

No changes were made for:
- numeric token integrity validation
- MJ502 datasheet extraction features
- tone/conversational-literalism behaviors

## 11. Risk / Residual Notes
- Memory-aware entity extraction is intentionally simple and based on heuristic parsing of recent memory text. It is designed to be conservative, not comprehensive.
- If future memory formats change significantly, classifier-side entity extraction may need a small parser update.
- Region filtering depends on key naming conventions (`news_au_*`, `news_israel_*`, `news_gb_*`) remaining consistent.

## 12. Artifacts Produced In This Session
### 12.1 This report (repo copy)
- `/home/mike/lucy/snapshots/opt-experimental-v2-dev/dev_notes/CHATGPT_REVIEW_REPORT_memory_aware_routing_and_news_region_filter_enforcement_2026-02-26T22-38-35+0200.md`

### 12.2 Desktop copy (requested)
- `/home/mike/Desktop/CHATGPT_REVIEW_REPORT_memory_aware_routing_and_news_region_filter_enforcement_2026-02-26T22-38-35+0200.md`

## 13. Recommended Next Steps (Optional)
1. If/when desired, add a `GB`-specific NEWS regression once `news_gb_*` keys are configured in the allowlist/query map.
2. If future false positives appear in memory-pronoun routing, add ambiguity/negative regressions (multiple candidate entities, no candidate entity) to lock down behavior further.
3. If the optional numeric consistency guard is revisited later, scope it narrowly to electronics/tube/component intents to avoid noisy false positives.

