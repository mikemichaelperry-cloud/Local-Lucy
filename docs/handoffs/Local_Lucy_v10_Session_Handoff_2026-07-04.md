# Local Lucy v10 Session Handoff — 2026-07-04

**Project:** Local Lucy v10 → v11 planning
**Session focus:** Consolidation cleanup, Git LFS push, and v11 roadmap
**Branch:** `v10-dev` (pushed to `origin/v10-dev`)
**Status:** Cleanup complete; ready for v11 implementation
**Next session:** Begin revised v11 roadmap (`docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md`). Start with Phase 0 (scope correction) and Phase 1 (measurements), not HMI changes.

---

## What was completed

1. **v10-dev consolidation cleanup**
   - Archived ~1.4 GB of unused LoRA binary artifacts and training data to `backups/v10-dev-cleanup/2026-07-04/lora/`
   - Archived stale session handoffs and reports to `backups/v10-dev-cleanup/2026-07-04/docs/`
   - Archived retired v9/experimental launchers to `backups/v10-dev-cleanup/2026-07-04/tools/`
   - Updated stale references in `AGENTS.md`, `ARCHITECTURE.md`, `docs/runbooks/PERSONAS.md`, `SHA256SUMS`, and persona Modelfiles
   - Fixed `tools/runtime_lifecycle.py` default launcher from retired `start_local_lucy_v9.sh` to `START_LUCY.sh`

2. **Test fix**
   - Updated stale `test_gate_tell_me_more` to match the continuation-follow-up inheritance design
   - Routing barrage: 38/38 PASS
   - Router unit tests: 719 passed, 29 skipped
   - HMI comprehensive inspection: 138/138 PASS

3. **GitHub push**
   - Installed Git LFS locally (`~/.local/bin/git-lfs-3.5.1/`)
   - Migrated four 160 MB `optimizer.pt` checkpoint files to LFS
   - Force-pushed `v10-dev`; branch is now in sync with origin

4. **Desktop cleanup**
   - Archived old handoffs and `Architecture.md` to `archived_handoffs/` and `archive_reports/`
   - Kept only `Local_Lucy_V10_Architecture_2026-07-04.md` on the Desktop
   - Verified `Local-Lucy-v10.desktop` still points to `/home/mike/lucy-v10/START_LUCY.sh`

5. **v11 roadmap created, revised, and approved**
   - Saved to `docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md`
   - Approved with four amendments:
     1. Hebrew code paths: aim for separation (not reachable/loaded/maintained in primary runtime), not destructive deletion of shared utilities.
     2. Shadow-mode model selection: treat manual choice as one signal; add blind A/B answer comparisons and continue collecting data after the 50-query gate.
     3. Failed evidence retrieval: add route-dependent fallback rules so high-stakes queries do not silently fall back to unverified local answers.
     4. Voice GPU configuration: confirm actual Kokoro device (CPU vs CUDA) and document one source of truth before changing defaults.
   - Additional metric added: context-guard telemetry including unused accepted context, citation coverage, context disagreement, and entity collision.
   - Phase order:
     - Phase 0: Correct scope (English-only, evidence vs synthesis)
     - Phase 1: Establish measurements (frozen validation corpus, confusion matrix, latency baselines)
     - Phase 2: Context provenance and guard
     - Phase 3: Automatic model selection in shadow mode
     - Phase 4: Classifier hardening
     - Phase 5: HMI simplification (only after auto-routing is reliable)
     - Phase 6: Test cleanup
     - Phase 7: Latency optimization
     - Phase 8: Evidence/news improvements, version bump/docs

---

## Current repository state

- Branch: `v10-dev` (HEAD)
- Working tree: clean
- Git LFS: tracking 4 optimizer.pt files
- Desktop shortcut: correct
- Current architecture doc: `Local_Lucy_V10_Architecture_2026-07-04.md`

Recent commits (last 10):
```
1ad56ad docs: revise v11 roadmap after review feedback
caa7659 docs: add session handoff for 2026-07-04
ce367a3 docs: add Local Lucy v11 roadmap
95a0a7a docs: fix broken links in SESSION_HANDOFF_2026-06-27.md to archived reports
463c97f docs: update links after archival cleanup
2248b78 cleanup: point runtime lifecycle and codex hints at START_LUCY.sh
02ff7d3 cleanup: archive retired v9 and experimental launchers
1f80e44 cleanup: archive stale session handoffs and reports
cb39261 docs: correct test commands in cleanup plan
262d390 fix: update stale test_gate_tell_me_more to match continuation-follow-up design
```

---

## Known issues carried forward

- Synthetic adversarial tests still have ~90 routing-expectation failures; treat as diagnostic, not CI gate
- `test_changes_verification.py::test_fail_loud_no_env_vars` fails because subprocess uses system python lacking PySide6
- Router accuracy is ~81%; needs hard negatives and possibly a stronger model or LLM arbiter
- HMI still exposes too many toggles; persona selector jumps back to Auto
- Model selection is manual in the UI but should be automatic

---

## Files to read first next session

1. **This handoff** — `/home/mike/Desktop/Local_Lucy_v10_Session_Handoff_2026-07-04.md` (also at `docs/handoffs/Local_Lucy_v10_Session_Handoff_2026-07-04.md`)
2. **v11 roadmap** — `docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md`
3. **Current architecture** — `Architecture.md` and `Local_Lucy_V10_Architecture_2026-07-04.md`
4. **ChatGPT report** — `/home/mike/Desktop/Local_Lucy_v10_to_v11_Report_For_ChatGPT_2026-07-04.md`

---

## Recommended first actions next session

1. Read the revised v11 roadmap and the ChatGPT report. The key corrections are:
   - Local Lucy v11 is English-only; Hebrew/Racheli is a separate system.
   - OpenAI/Kimi synthesize evidence; they are not evidence sources.
   - Context guard must use entity, intent, temporal, lexical, provenance, and answerability checks — not just embedding similarity.
   - Automatic model selection starts in shadow mode with full logging; manual selectors stay until shadow mode proves reliable.
2. Run the verification commands to confirm baseline:
   ```bash
   cd /home/mike/lucy-v10
   python3 tools/router_py/run_routing_barrage.py
   python3 -m pytest tools/router_py -q
   python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
   ```
3. Start with Phase 0 (scope correction) and Phase 1 (measurements). Do not start HMI simplification until Phase 3 shadow mode is reliable.
4. Do not add new models or LoRAs until the classifier and context guard are fixed.

---

## Notes

- Git LFS binary is installed at `~/.local/bin/git-lfs-3.5.1/git-lfs` with a symlink at `~/.local/bin/git-lfs`. Future sessions may need to ensure it is on PATH.
- The cleanup used `git mv` where possible, so file history is preserved in `backups/`.
- If anything is missing from this handoff, the detailed ledger is at `.superpowers/sdd/progress.md`.
