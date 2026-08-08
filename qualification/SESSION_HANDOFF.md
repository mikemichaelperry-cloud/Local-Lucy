# Local Lucy V11 Qualification — Session Handoff

**Session end:** 2026-08-07T18:17Z  
**Final qualification decision:** `QUALIFIED` on HEAD `8c80cdb docs: update AGENTS.md active branch to main` (STAGE_19 re-run #2: 7/7, no dual-model residency)  
**HEAD commit (unchanged throughout session):** `8c80cdb`  
**Previous qualification:** `ed26695` (memory-tourism phase; superseded by this requalification on HEAD)  
**Working tree:** uncommitted documentation/harness changes only (see Modified files); no commits made this session  
**V10 status:** untouched  

---

## Work completed this session

### 1. Documentation corrections (triggered by external review of the 2026-08-06 report/handoff)

- `qualification/COMPLETION_REPORT_2026-08-06.md`: overstated "all stages pass" claims qualified (STAGE_00–03 never ran standalone; pointers added to `STAGE_00_03_TRACEABILITY.md` and the `_REVISED` report); memory `max_chars` history corrected (memory-service default 500 → 2000 via new `LUCY_MEMORY_MAX_CHARS`; execution-engine caller passes 2400); wrong path `execution_engine_helpers.py` → `execution_engine/helpers.py`; S09-GEM-007 row now references DEC-016.
- `qualification/SESSION_HANDOFF.md` (previous revision): rollback block rewritten — env approximation `LUCY_MEMORY_RECENT_TURN_LIMIT=4` / `LUCY_MEMORY_MAX_INJECTED_TURNS=4` / `LUCY_MEMORY_MAX_CHARS=500` with note that env vars cannot undo the code-only topic-shift bypass; git rollback corrected to `git checkout 3249092 -- tools/memory/memory_service.py` (`3249092` = parent of memory-expansion commit `1930946`; previously documented `ed26695` already contained the change, verified via `git merge-base`). That revision is archived on the desktop (see Deliverables).
- `qualification/DECISIONS.md`: new DEC-016 recording the S09-GEM-007 relaxation (accept any single reasoning marker of because/since/therefore in stage_09/stage_11 suites).
- `tools/memory/memory_service.py`: stale docstring fixed — `LUCY_MEMORY_SIMILARITY_THRESHOLD` default 0.55 → 0.70 (matches code at ~line 1628).

### 2. Qualification gap closed — STAGE_19 re-run on HEAD

The memory-retrieval expansion (`1930946`) landed after the original STAGE_19 pass on `ed26695`, so HEAD was requalified:

- **Re-run #1:** 6/7 — STAGE_09 failed only on S09-MEM-003 ("Recall a stated fact about assistant identity"): literal concept `"Local Lucy"` missing from a 49-char Gemma response ("assistant" present).
- **Root cause:** retrieval path healthy (memory code unchanged since the passing `ed26695` run, 2400-char budget ample, no dual residency). Concluded model-wording flake under temperature-0 near-tie nondeterminism, not a retrieval defect. Evidence: `qualification/results/stage_09_gemma_scenarios.json`.
- **Harness improvement:** `tools/router_py/stage_09_gemma_scenario_suite.py` now records `response_text` and `turn_responses` per scenario in the results JSON (diagnostics only; no pass criteria changed).
- **STAGE_09 standalone re-run:** 16/16 passed; S09-MEM-003 passed with near-verbatim recall `"You said that I am Local Lucy, your personal AI assistant."` — flake hypothesis confirmed.
- **Re-run #2 (full STAGE_19):** **7/7 PASSED**, `all_passed=true`, no dual-model residency at any point, `final_loaded_models=[]`. Evidence: `qualification/results/stage_19_clean_run.json`.

### 3. Verification evidence

| Command | Result |
|---|---|
| `python3 tools/router_py/stage_09_gemma_scenario_suite.py` (standalone re-run) | 16/16 passed (S09-MEM-003 passed) |
| `python3 tools/router_py/stage_19_clean_run.py` (re-run #2 on `8c80cdb`) | **7/7 passed**, `all_passed=true`, `final_loaded_models=[]` |

Per-stage elapsed in re-run #2: STAGE_08 50s, STAGE_09 271s, STAGE_10 18s, STAGE_11 65s, STAGE_13 95s, STAGE_16 42s, STAGE_16_WX 28s.

### 4. Desktop housekeeping

- Loose stale `~/Desktop/COMPLETION_REPORT_2026-08-06.md` and `~/Desktop/SESSION_HANDOFF.md` were byte-identical duplicates of files already in `Local_Lucy_V11_Archive/` and were removed.
- Stale `Local_Lucy_V11_DECISIONS.md` archived as `Local_Lucy_V11_Archive/Local_Lucy_V11_DECISIONS_2026-08-01_stale.md` and replaced with the current repo `DECISIONS.md`.

---

## Deliverables

- `qualification/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md` — this session's completion report
- `qualification/SESSION_HANDOFF.md` — this file
- `qualification/results/stage_19_clean_run.json` — final 7/7 clean run
- `qualification/results/stage_09_gemma_scenarios.json` — scenario results with recorded responses

Copies on the desktop:

```text
~/Desktop/Local Lucy V11/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md
~/Desktop/Local Lucy V11/SESSION_HANDOFF.md
```

Archived this session:

```text
~/Desktop/Local Lucy V11/Local_Lucy_V11_Archive/SESSION_HANDOFF_2026-08-07_pre_final_requal.md
~/Desktop/Local Lucy V11/Local_Lucy_V11_Archive/Local_Lucy_V11_DECISIONS_2026-08-01_stale.md
```

---

## Modified files (uncommitted working-tree changes)

- `qualification/COMPLETION_REPORT_2026-08-06.md`
- `qualification/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md` (new)
- `qualification/DECISIONS.md` (DEC-016)
- `qualification/SESSION_HANDOFF.md` (this file)
- `qualification/results/stage_08_gemma_smoke.json`
- `qualification/results/stage_09_gemma_scenarios.json`
- `qualification/results/stage_10_llama_smoke.json`
- `qualification/results/stage_11_llama_scenarios.json`
- `qualification/results/stage_13_model_switch.json`
- `qualification/results/stage_16_hmi_soak.json`
- `qualification/results/stage_19_clean_run.json`
- `tools/memory/memory_service.py` (docstring only)
- `tools/router_py/stage_09_gemma_scenario_suite.py` (diagnostics only)

---

## What is safe to run next

- Commit this session's documentation, harness, and results changes (not yet committed; see Modified files).
- HMI live testing of memory recall and tourism/travel queries.
- Routing failure corpus expansion and classifier-head retraining.
- v10-labelled file cleanup in v11.
- Further voice testing with `LUCY_ENABLE_VOICE_TESTS=1` once a reproducible text-display scenario is found.

## What must not be rerun unnecessarily

- Do not retrain `classifier_head.pt` without first verifying against the frozen validation corpus.
- Do not run model tests concurrently; the RTX 3060 cannot load two Local Lucy models at once.

---

## Rollback

If memory retrieval regresses (env-var approximation only; env vars cannot undo the topic-shift bypass for explicit recall queries, which is a code-only change with no env gate):

```bash
cd /home/mike/lucy-v11
export LUCY_MEMORY_RECENT_TURN_LIMIT=4
export LUCY_MEMORY_MAX_INJECTED_TURNS=4
export LUCY_MEMORY_MAX_CHARS=500
```

Or revert the memory-service change (commit 1930946) via its parent:

```bash
git checkout 3249092 -- tools/memory/memory_service.py
```

(Only this file matters for that change; the `max_chars=2400` in `tools/router_py/execution_engine/helpers.py` came later in b4cb9f9.)

Full rollback to the last qualified state:

```bash
cd /home/mike/lucy-v11
git checkout 8c80cdb
```

---

## Known limitations and active defects

- See `qualification/KNOWN_LIMITATIONS.md` for the complete list.
- Active defects: **none**.
- New residual notes from this session:
  - S09-MEM-003 uses a literal case-insensitive substring check on free-form model output; rare wording flakes remain possible, now diagnosable via recorded `response_text`. If it recurs, consider a DEC entry relaxing the concept check — do not relax silently.
  - STAGE_16_WX stderr shows benign `[FACTS] Direct SQLite location fallback failed: no such table: persistent_facts` noise from an unseeded namespace DB; the stage passes; cosmetic.
- Accepted limitations carried forward:
  - Two locked-holdout routing cases remain misclassified at the raw classifier level; final guards keep them acceptable.
  - Voice text-display issue remains `UNREPRODUCED`.
  - Expanded memory window increases privacy surface; mitigated by existing redaction and canary tests.
  - Persistent-fact correction authority is not enforced automatically.
  - Generic low-confidence → AUGMENTED fallback is not implemented and was not added during stabilisation.

---

## Resume command

```bash
cd /home/mike/lucy-v11 && cat qualification/COMPLETION_REPORT_2026-08-07_FINAL_REQUAL.md qualification/SESSION_HANDOFF.md qualification/TEST_STATUS.json qualification/KNOWN_LIMITATIONS.md
```
