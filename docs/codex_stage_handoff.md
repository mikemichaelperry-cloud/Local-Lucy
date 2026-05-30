STATUS: IN_PROGRESS

CURRENT STAGE: Stage 3 - Fallback / Degradation Metadata
CURRENT BRANCH: codex-v10-staged-review

FILES INSPECTED:
- tools/router_py/classify.py
- tools/router_py/policy.py
- tools/router_py/provider_resolver.py
- tools/router_py/request_pipeline.py
- tools/router_py/execution_engine.py
- tools/router_py/execution_engine_state.py
- tools/router_py/local_answer.py
- tools/router_py/response_formatter.py
- tools/router_py/request_types.py
- tools/memory/memory_service.py
- tools/unverified_context_trusted.py
- tools/unverified_context_provider_dispatch.py
- tools/internet/search_web.py
- tools/internet/web_extract.py
- tools/internet/run_fetch_with_gate.sh
- tools/internet/url_safety.py
- config/trust/trust_catalog.yaml
- config/trust/policy.yaml
- config/trust/generated/medical_runtime.txt
- config/trust/generated/vet_runtime.txt
- config/trust/generated/allowlist_fetch.txt
- config/trust/generated/medical.txt
- config/trust/generated/vet.txt
- tools/trust/generate_trust_lists.py
- tools/trust/verify_trust_lists.sh
- ui-v10/app/services/runtime_bridge_consolidated.py
- ui-v10/app/services/state_store.py
- ui-v10/app/panels/status_panel.py

FILES PLANNED FOR EDIT:
- docs/codex_stage_handoff.md
- tools/unverified_context_trusted.py
- tools/router_py/execution_engine.py
- tools/router_py/execution_engine_state.py
- ui-v10/app/services/state_store.py
- ui-v10/app/panels/status_panel.py
- targeted tests only

FILES PLANNED FOR INSPECTION:
- tools/unverified_context_trusted.py
- tools/router_py/execution_engine.py
- tools/router_py/execution_engine_state.py
- ui-v10/app/services/state_store.py
- ui-v10/app/panels/status_panel.py
- tools/tests/test_trusted_evidence_unit.py
- tools/router_py/test_execution_engine_state.py
- relevant ui-v10 tests if needed

EXACT INTENDED CHANGE:
- Add loud trusted-evidence degradation metadata:
- `ANSWER_BASIS`, `LIVE_FETCH_STATUS`, `CONFIDENCE`, `DEGRADED_REASON`
- Preserve routing/provider behavior and bounded-response text
- Persist metadata into HMI-readable JSON state
- Show a compact HMI warning for limited/low confidence or failed/unavailable live fetch
- Keep old result objects parseable
- Do not change routing, provider selection, medical/vet detection, memory, or local-answer logic

STAGE 1 REVIEW SUMMARY:
- High: `tools/router_py/local_answer.py` bulk-injects all persistent facts; minimal Stage 2 patch is query-scoped retrieval using existing embeddings in `tools/memory/memory_service.py`.
- High: `tools/unverified_context_trusted.py` silently degrades medical/vet/news answers to static source-list templates when live search/fetch fails.
- High: `tools/router_py/execution_engine.py` marks strict EVIDENCE miss as `status=completed` / `outcome_code=evidence_not_found` with no degradation metadata.
- High: `tools/router_py/execution_engine.py` maps trusted bounded responses to normal completed answers without `ANSWER_BASIS` / `LIVE_FETCH_STATUS` / `CONFIDENCE` / `DEGRADED_REASON`.
- Medium: `tools/router_py/execution_engine_state.py` HMI payload builder has no fields for evidence degradation metadata; `ui-v10/app/panels/status_panel.py` therefore renders degraded evidence as normal evidence-backed output.
- Medium: `tools/unverified_context_trusted.py` supports classifier-driven `evidence_reason`, but `tools/unverified_context_provider_dispatch.py` and `tools/router_py/execution_engine.py` do not pass it through, so symptom-style queries can lose classifier guidance.
- Medium: `tools/internet/search_web.py` still relies on regex HTML scraping of SearXNG and only reports a generic backend failure.
- Medium: `config/trust/generated/medical_runtime.txt` does not match deterministic generator output implied by `config/trust/trust_catalog.yaml` + `config/trust/policy.yaml`; `config/trust/generated/vet_runtime.txt` is smaller than `vet.txt` because runtime lists are filtered to fetch tiers 1 and 2.
- Low: medical/vet routing invariants are enforced at classify/provider selection time (`classify.py`, `provider_resolver.py`), and EVIDENCE does not fall back to local LLM or general providers.
- Low: Stage 3 metadata should be threaded through `ExecutionResult.metadata` -> `RouterOutcome.metadata` -> `execution_engine_state.py` JSON payload -> `state_store.py` / `status_panel.py`; avoid growing `execution_engine.py` beyond pass-through.

TESTS PLANNED:
- `pytest tools/tests/test_trusted_evidence_unit.py -q`
- `pytest tools/router_py/test_execution_engine_state.py -q`
- targeted UI/state tests if needed
- mandatory stage-closure checks:
- `git status --short`
- `git diff --stat`
- `git diff --check`

ROLLBACK COMMAND:
- `rm docs/codex_stage_handoff.md`

CURRENT SAFETY STATUS:
- Safe. Stage 2 changes preserved; Stage 3 code changes made and verified with targeted tests.

STAGE 3 IMPLEMENTATION NOTES:
- `tools/unverified_context_trusted.py` now emits trusted-evidence metadata:
- `ANSWER_BASIS`
- `LIVE_FETCH_STATUS`
- `CONFIDENCE`
- `DEGRADED_REASON`
- Metadata is attached to both live trusted answers and trusted-domain/static/error fallbacks without changing answer text.
- `tools/router_py/execution_engine.py` now passes trusted metadata through bounded trusted responses and marks strict EVIDENCE misses as degraded.
- `tools/router_py/execution_engine_state.py` now writes the new fields into `last_request_result.json` / history payloads and preserves `trusted` as the provider for EVIDENCE results.
- `ui-v10/app/services/state_store.py` now recognizes `trusted` and still honors legacy provider strings.
- `ui-v10/app/panels/status_panel.py` now shows compact degraded-evidence labels/notes when trusted fetch confidence is limited/low or live fetch failed/unavailable.

FILES CHANGED IN STAGE 3:
- docs/codex_stage_handoff.md
- tools/unverified_context_trusted.py
- tools/router_py/execution_engine.py
- tools/router_py/execution_engine_state.py
- ui-v10/app/services/state_store.py
- ui-v10/app/panels/status_panel.py
- tools/tests/test_trusted_evidence_unit.py
- tools/router_py/test_execution_engine_state.py
- ui-v10/tests/test_state_store_last_request_provider_truth.py
- ui-v10/tests/test_status_panel_trusted_metadata.py

TEST RESULTS:
- `pytest tools/tests/test_trusted_evidence_unit.py -q` -> 16 passed
- `pytest tools/router_py/test_execution_engine_state.py -q` -> 41 passed
- `HOME=/home/mike QT_QPA_PLATFORM=offscreen pytest ui-v10/tests/test_status_panel_trusted_metadata.py -q` -> 2 passed
- `HOME=/home/mike python3 ui-v10/tests/test_state_store_last_request_provider_truth.py` -> passed
- Broad `ui-v10/tests/test_comprehensive_hmi_inspection.py` not run; replaced with a narrow offscreen status-panel unit test to keep Stage 3 small and stable

STAGE CLOSURE:
- `git status --short`:
- ` M tools/memory/memory_service.py`
- ` M tools/router_py/execution_engine.py`
- ` M tools/router_py/execution_engine_state.py`
- ` M tools/router_py/local_answer.py`
- ` M tools/router_py/test_execution_engine_state.py`
- ` M tools/router_py/test_local_answer.py`
- ` M tools/tests/test_memory_service_unit.py`
- ` M tools/tests/test_trusted_evidence_unit.py`
- ` M tools/unverified_context_trusted.py`
- ` M ui-v10/app/panels/status_panel.py`
- ` M ui-v10/app/services/state_store.py`
- ` M ui-v10/tests/test_state_store_last_request_provider_truth.py`
- `?? docs/codex_stage_handoff.md`
- `?? ui-v10/tests/test_status_panel_trusted_metadata.py`
- `git diff --stat`:
- `tools/memory/memory_service.py | 52 +++++-`
- `tools/router_py/execution_engine.py | 57 ++++++-`
- `tools/router_py/execution_engine_state.py | 7 +-`
- `tools/router_py/local_answer.py | 10 +-`
- `tools/router_py/test_execution_engine_state.py | 28 ++++`
- `tools/router_py/test_local_answer.py | 79 +++++++--`
- `tools/tests/test_memory_service_unit.py | 54 ++++++`
- `tools/tests/test_trusted_evidence_unit.py | 20 +++`
- `tools/unverified_context_trusted.py | 182 ++++++++++++++++++---`
- `ui-v10/app/panels/status_panel.py | 56 ++++++-`
- `ui-v10/app/services/state_store.py | 10 +-`
- `ui-v10/tests/test_state_store_last_request_provider_truth.py | 4 +`
- `12 files changed, 503 insertions(+), 56 deletions(-)`
- `git diff --check`: clean

RESUME POINT:

* Stage: Stage 3 - Fallback / Degradation Metadata
* Status: SAFE_TO_RESUME
* Branch: codex-v10-staged-review
* Files changed: docs/codex_stage_handoff.md, tools/memory/memory_service.py, tools/router_py/execution_engine.py, tools/router_py/execution_engine_state.py, tools/router_py/local_answer.py, tools/router_py/test_execution_engine_state.py, tools/router_py/test_local_answer.py, tools/tests/test_memory_service_unit.py, tools/tests/test_trusted_evidence_unit.py, tools/unverified_context_trusted.py, ui-v10/app/panels/status_panel.py, ui-v10/app/services/state_store.py, ui-v10/tests/test_state_store_last_request_provider_truth.py, ui-v10/tests/test_status_panel_trusted_metadata.py
* Tests run: pytest tools/tests/test_trusted_evidence_unit.py -q; pytest tools/router_py/test_execution_engine_state.py -q; HOME=/home/mike QT_QPA_PLATFORM=offscreen pytest ui-v10/tests/test_status_panel_trusted_metadata.py -q; HOME=/home/mike python3 ui-v10/tests/test_state_store_last_request_provider_truth.py; git status --short; git diff --stat; git diff --check
* Tests passed: all listed Stage 3 targeted tests; git diff --check
* Tests failed: none
* Safe to commit: yes
* Safe to continue: yes
* Rollback command: git checkout -- tools/router_py/execution_engine.py tools/router_py/execution_engine_state.py tools/tests/test_trusted_evidence_unit.py tools/unverified_context_trusted.py ui-v10/app/panels/status_panel.py ui-v10/app/services/state_store.py ui-v10/tests/test_state_store_last_request_provider_truth.py && rm -f ui-v10/tests/test_status_panel_trusted_metadata.py docs/codex_stage_handoff.md
* Next recommended prompt: Review Stage 3 results and, if approved, proceed to Stage 4 only.

STAGE 2 IMPLEMENTATION NOTES:
- Added `get_relevant_persistent_facts(query, category=None, limit=3, threshold=0.35)` to `tools/memory/memory_service.py`.
- Retrieval uses existing embedding + cosine similarity helpers and returns `[]` on embedding/runtime failure.
- `tools/router_py/local_answer.py` now injects only relevant persistent facts for the current query.
- No routing, execution engine, trusted evidence, provider selection, HMI, or voice files were touched.

FILES CHANGED IN STAGE 2:
- docs/codex_stage_handoff.md
- tools/memory/memory_service.py
- tools/router_py/local_answer.py
- tools/router_py/test_local_answer.py
- tools/tests/test_memory_service_unit.py

TEST RESULTS:
- `pytest tools/tests/test_memory_service_unit.py -q` -> 18 passed
- `pytest tools/router_py/test_local_answer.py -q` -> 31 passed
- `pytest tools/tests/test_memory_*.py -q` -> 3 failed in `tools/tests/test_memory_toggle.py` because `Path.home()` resolved to `/home/mike/.codex-api-home` in this shell, producing a duplicated runtime path
- `HOME=/home/mike pytest tools/tests/test_memory_*.py -q` -> 94 passed

STAGE CLOSURE:
- `git status --short`:
- ` M tools/memory/memory_service.py`
- ` M tools/router_py/local_answer.py`
- ` M tools/router_py/test_local_answer.py`
- ` M tools/tests/test_memory_service_unit.py`
- `?? docs/codex_stage_handoff.md`
- `git diff --stat`:
- `tools/memory/memory_service.py | 52 +++++++++++++++++++++-`
- `tools/router_py/local_answer.py | 10 ++---`
- `tools/router_py/test_local_answer.py | 79 ++++++++++++++++++++++++++-------`
- `tools/tests/test_memory_service_unit.py | 54 ++++++++++++++++++++++`
- `4 files changed, 172 insertions(+), 23 deletions(-)`
- `git diff --check`: clean

RESUME POINT:

* Stage: Stage 2 - Semantic Persistent-Fact Retrieval
* Status: SAFE_TO_RESUME
* Branch: codex-v10-staged-review
* Files changed: docs/codex_stage_handoff.md, tools/memory/memory_service.py, tools/router_py/local_answer.py, tools/router_py/test_local_answer.py, tools/tests/test_memory_service_unit.py
* Tests run: pytest tools/tests/test_memory_service_unit.py -q; pytest tools/router_py/test_local_answer.py -q; pytest tools/tests/test_memory_*.py -q; HOME=/home/mike pytest tools/tests/test_memory_*.py -q; git status --short; git diff --stat; git diff --check
* Tests passed: tools/tests/test_memory_service_unit.py; tools/router_py/test_local_answer.py; tools/tests/test_memory_*.py with HOME=/home/mike; git diff --check
* Tests failed: tools/tests/test_memory_*.py in current shell env only, due existing Path.home()/HOME runtime-path mismatch in tools/tests/test_memory_toggle.py
* Safe to commit: yes
* Safe to continue: yes
* Rollback command: git checkout -- tools/memory/memory_service.py tools/router_py/local_answer.py tools/router_py/test_local_answer.py tools/tests/test_memory_service_unit.py && rm docs/codex_stage_handoff.md
* Next recommended prompt: Review Stage 2 results and, if approved, proceed to Stage 3 only.

STAGE CLOSURE:
- `git status --short`: `?? docs/codex_stage_handoff.md`
- `git diff --stat`: no output (only untracked file)
- `git diff --check`: clean

RESUME POINT:

* Stage: Stage 1 - Read-Only Targeted Review
* Status: SAFE_TO_RESUME
* Branch: codex-v10-staged-review
* Files changed: docs/codex_stage_handoff.md
* Tests run: git status --short; git diff --stat; git diff --check
* Tests passed: git diff --check
* Tests failed: none
* Safe to commit: yes
* Safe to continue: yes
* Rollback command: rm docs/codex_stage_handoff.md
* Next recommended prompt: Review the Stage 1 findings and, if approved, proceed to Stage 2 only.
