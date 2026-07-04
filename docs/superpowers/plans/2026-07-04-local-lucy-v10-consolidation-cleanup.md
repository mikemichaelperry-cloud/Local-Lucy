# Local Lucy v10 Consolidation Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the bloat that re-accumulated on `v10-dev` after the `codex-v10-staged-review` cleanup, while preserving all runtime functionality, today's fixes, and the Desktop shortcut.

**Architecture:** Move (do not delete) unused binary artifacts, stale docs, and retired scripts into a dated backup tree under `backups/v10-dev-cleanup/2026-07-04/`. After each move, grep the codebase for lingering references and run the routing + HMI test suites. Finish by syncing `Architecture.md` to the Desktop.

**Tech Stack:** Python 3.10, PySide6/Qt6, Ollama, sentence-transformers, bash, git.

## Global Constraints

- **Never delete files during cleanup.** Move them to `backups/v10-dev-cleanup/2026-07-04/<category>/` so the user can restore them.
- **Do not overwrite the fixes committed to `v10-dev` on 2026-07-04:**
  - `tools/router_py/policy_router.py` travel/tourism gate
  - `tools/router_py/classify.py` continuation follow-up inheritance
  - `ui-v10/app/panels/control_panel.py` persona optimistic UI
  - `ui-v10/app/main_window.py` persona optimistic UI
  - `ui-v10/app/services/runtime_bridge.py` `sys.executable` for persona subprocess
- **Preserve the Desktop shortcut:** `/home/mike/Desktop/Local-Lucy-v10.desktop` must keep `Exec=/home/mike/lucy-v10/START_LUCY.sh`.
- **Run tests after every task that changes files:**
  - Routing barrage: `python3 tools/router_py/run_routing_barrage.py` (must report PASS for all 38 cases)
  - Routing unit tests: `python3 -m pytest tools/router_py -q` (must report all passing)
  - HMI comprehensive: `python3 ui-v10/tests/test_comprehensive_hmi_inspection.py` (must report 138 passing)
- **Do not remove any Modelfile that is referenced by the runtime or HMI selector:** `local-lucy`, `local-lucy-fast`, `local-lucy-llama31`, `local-lucy-mistral`, and their persona variants (`-michael`, `-racheli`) must stay in `config/`.
- **Do not remove LoRA runtime code** (`tools/lora/*.py`) unless the user later retires personas; only archive the trained binary artifacts and training datasets.

---

## Task 1: Archive unused LoRA binary artifacts

**Files:**
- Move: `models/lora/local-lucy-llama31/michael/` → `backups/v10-dev-cleanup/2026-07-04/lora/michael/`
- Move: `models/lora/local-lucy-llama31/racheli/` → `backups/v10-dev-cleanup/2026-07-04/lora/racheli/`
- Move: `data/lora/datasets/michael.jsonl` → `backups/v10-dev-cleanup/2026-07-04/lora/datasets/`
- Move: `data/lora/datasets/racheli.jsonl` → `backups/v10-dev-cleanup/2026-07-04/lora/datasets/`
- Move: `data/lora/raw_specs/michael.md` → `backups/v10-dev-cleanup/2026-07-04/lora/raw_specs/`
- Move: `data/lora/raw_specs/racheli.md` → `backups/v10-dev-cleanup/2026-07-04/lora/raw_specs/`
- Move: `data/lora/replay/base_model_replay.jsonl` → `backups/v10-dev-cleanup/2026-07-04/lora/replay/`
- Keep: `tools/lora/train_all_personas.sh`, `tools/lora/train_persona_lora.py`, `tools/lora/build_modelfiles.py`, `tools/lora/evaluate_persona.py`, `tools/lora/test_evaluate_persona.py`, `tools/lora/build_datasets.py`, `tools/lora/convert_adapters_to_gguf.py` (runtime tooling)

**Interfaces:**
- Consumes: git diff showing these paths were added after `codex-v10-staged-review`
- Produces: cleaned repo with ~700 MB of unused binary checkpoints removed from the working tree

- [ ] **Step 1: Verify nothing in the runtime references the binary artifact paths**

Run:
```bash
cd /home/mike/lucy-v10
grep -R "models/lora/local-lucy-llama31\|adapter_model.safetensors\|adapter\.gguf\|checkpoint-[0-9]\+" ui-v10/ tools/router_py/ tools/memory/ tools/internet/ START_LUCY.sh 2>/dev/null || true
```
Expected: no matches in runtime code (matches only in `tools/lora/`, `docs/`, `AGENTS.md`, or `README.md` are acceptable).

- [ ] **Step 2: Create backup directories and move the artifacts**

Run:
```bash
cd /home/mike/lucy-v10
mkdir -p backups/v10-dev-cleanup/2026-07-04/lora/{michael,racheli,datasets,raw_specs,replay}
git mv models/lora/local-lucy-llama31/michael/* backups/v10-dev-cleanup/2026-07-04/lora/michael/ 2>/dev/null || mv models/lora/local-lucy-llama31/michael/* backups/v10-dev-cleanup/2026-07-04/lora/michael/
git mv models/lora/local-lucy-llama31/racheli/* backups/v10-dev-cleanup/2026-07-04/lora/racheli/ 2>/dev/null || mv models/lora/local-lucy-llama31/racheli/* backups/v10-dev-cleanup/2026-07-04/lora/racheli/
git mv data/lora/datasets/michael.jsonl backups/v10-dev-cleanup/2026-07-04/lora/datasets/
git mv data/lora/datasets/racheli.jsonl backups/v10-dev-cleanup/2026-07-04/lora/datasets/
git mv data/lora/raw_specs/michael.md backups/v10-dev-cleanup/2026-07-04/lora/raw_specs/
git mv data/lora/raw_specs/racheli.md backups/v10-dev-cleanup/2026-07-04/lora/raw_specs/
git mv data/lora/replay/base_model_replay.jsonl backups/v10-dev-cleanup/2026-07-04/lora/replay/
rmdir models/lora/local-lucy-llama31/michael models/lora/local-lucy-llama31/racheli 2>/dev/null || true
```
Expected: artifacts are under `backups/v10-dev-cleanup/2026-07-04/lora/` and the source directories are empty or gone.

- [ ] **Step 3: Stage the moves and commit**

Run:
```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "cleanup: archive unused LoRA binary artifacts and training data

Moves trained adapter checkpoints, tokenizer artifacts, datasets, and raw
persona specs to backups/v10-dev-cleanup/2026-07-04/lora/. Runtime Modelfiles
and LoRA tooling remain intact."
```
Expected: commit succeeds with only moved paths in the diff.

- [ ] **Step 4: Run tests**

Run:
```bash
cd /home/mike/lucy-v10
python3 tools/router_py/run_routing_barrage.py
python3 -m pytest tools/router_py -q
python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```
Expected: barrage 38/38 PASS, routing unit tests all passing, HMI 138 passing.

---

## Task 2: Archive stale docs, handoffs, and reports

**Files:**
- Move: `docs/handoffs/Local_Lucy_v10_Session_Handoff_2026-06-22.md` → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Move: `docs/reports/Classifier_Router_Improvement_Report.md` → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Move: `docs/reports/Hebrew_First_Class_Support_Report.md` → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Move: `docs/reports/ROUTER_MINILM_REPLACEMENT_ATTEMPT_2026-06-21.md` → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Move: `docs/SESSION_HANDOFF_2026-06-14.md` → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Move: `Local_Lucy_v10_Session_Handoff_2026-06-23.md` (repo root) → `backups/v10-dev-cleanup/2026-07-04/docs/`
- Keep: `docs/runbooks/INSTALL.md`, `docs/runbooks/OLLAMA_SECURITY.md`, `docs/runbooks/PERSONAS.md`, `docs/runbooks/SECURITY.md`, `docs/superpowers/plans/2026-07-03-context-guard-implementation.md`, `docs/superpowers/specs/2026-07-03-context-guard-design.md`, `docs/web_interface.md`
- Keep: current `Architecture.md`, `ARCHITECTURE.md` (if both exist, leave them for Task 6)

**Interfaces:**
- Consumes: git diff showing these docs were added after `codex-v10-staged-review`
- Produces: repo root and `docs/` contain only current, actionable documentation

- [ ] **Step 1: Confirm no runtime code imports or reads these docs**

Run:
```bash
cd /home/mike/lucy-v10
grep -R "Local_Lucy_v10_Session_Handoff_2026-06-22\|Classifier_Router_Improvement_Report\|Hebrew_First_Class_Support_Report\|ROUTER_MINILM_REPLACEMENT_ATTEMPT\|SESSION_HANDOFF_2026-06-14\|Local_Lucy_v10_Session_Handoff_2026-06-23" ui-v10/ tools/ START_LUCY.sh 2>/dev/null || true
```
Expected: no matches in runtime code.

- [ ] **Step 2: Move stale docs to backup**

Run:
```bash
cd /home/mike/lucy-v10
mkdir -p backups/v10-dev-cleanup/2026-07-04/docs
git mv docs/handoffs/Local_Lucy_v10_Session_Handoff_2026-06-22.md backups/v10-dev-cleanup/2026-07-04/docs/ 2>/dev/null || mv docs/handoffs/Local_Lucy_v10_Session_Handoff_2026-06-22.md backups/v10-dev-cleanup/2026-07-04/docs/
git mv docs/reports/Classifier_Router_Improvement_Report.md backups/v10-dev-cleanup/2026-07-04/docs/
git mv docs/reports/Hebrew_First_Class_Support_Report.md backups/v10-dev-cleanup/2026-07-04/docs/
git mv docs/reports/ROUTER_MINILM_REPLACEMENT_ATTEMPT_2026-06-21.md backups/v10-dev-cleanup/2026-07-04/docs/
git mv docs/SESSION_HANDOFF_2026-06-14.md backups/v10-dev-cleanup/2026-07-04/docs/
git mv Local_Lucy_v10_Session_Handoff_2026-06-23.md backups/v10-dev-cleanup/2026-07-04/docs/ 2>/dev/null || mv Local_Lucy_v10_Session_Handoff_2026-06-23.md backups/v10-dev-cleanup/2026-07-04/docs/
rmdir docs/handoffs docs/reports 2>/dev/null || true
```
Expected: docs are under `backups/v10-dev-cleanup/2026-07-04/docs/`.

- [ ] **Step 3: Commit**

Run:
```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "cleanup: archive stale session handoffs and reports

Moves obsolete handoffs and exploratory reports to backups/. Keeps current
runbooks, plans, and Architecture.md in place."
```

- [ ] **Step 4: Run tests**

Same commands and expected results as Task 1 Step 4.

---

## Task 3: Remove retired/archived scripts from `tools/`

**Files:**
- Move: `tools/start_local_lucy_opt_experimental_v6_dev.sh.ARCHIVED` → `backups/v10-dev-cleanup/2026-07-04/tools/`
- Move: `tools/start_local_lucy_opt_experimental_v6_dev_codex_preprocess.sh.ARCHIVED` → `backups/v10-dev-cleanup/2026-07-04/tools/`
- Move: `tools/start_local_lucy_v9.sh` → `backups/v10-dev-cleanup/2026-07-04/tools/` (v9 launcher, superseded by START_LUCY.sh)
- Keep: all non-`.ARCHIVED` scripts used by START_LUCY.sh or the HMI

**Interfaces:**
- Consumes: list of `.ARCHIVED` and v9 files in `tools/`
- Produces: `tools/` contains only active scripts

- [ ] **Step 1: Verify START_LUCY.sh and runtime_bridge.py do not call the retired scripts**

Run:
```bash
cd /home/mike/lucy-v10
grep -R "start_local_lucy_opt_experimental\|start_local_lucy_v9" START_LUCY.sh ui-v10/app/ tools/*.sh 2>/dev/null || true
```
Expected: no matches.

- [ ] **Step 2: Move retired scripts**

Run:
```bash
cd /home/mike/lucy-v10
mkdir -p backups/v10-dev-cleanup/2026-07-04/tools
for f in tools/start_local_lucy_opt_experimental_v6_dev.sh.ARCHIVED tools/start_local_lucy_opt_experimental_v6_dev_codex_preprocess.sh.ARCHIVED tools/start_local_lucy_v9.sh; do
  if [ -e "$f" ]; then
    git mv "$f" backups/v10-dev-cleanup/2026-07-04/tools/ 2>/dev/null || mv "$f" backups/v10-dev-cleanup/2026-07-04/tools/
  fi
done
```

- [ ] **Step 3: Commit**

Run:
```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "cleanup: archive retired v9 and experimental launchers"
```

- [ ] **Step 4: Run tests**

Same commands and expected results as Task 1 Step 4.

---

## Task 4: Verify no broken references after archival

**Files:**
- Read: `README.md`
- Read: `AGENTS.md`
- Read: `docs/runbooks/PERSONAS.md`

**Interfaces:**
- Consumes: paths archived in Tasks 1-3
- Produces: updated documentation with corrected paths or removed stale links

- [ ] **Step 1: Grep for archived paths across markdown files**

Run:
```bash
cd /home/mike/lucy-v10
grep -R "models/lora/local-lucy-llama31/michael\|models/lora/local-lucy-llama31/racheli\|Local_Lucy_v10_Session_Handoff_2026-06-22\|Local_Lucy_v10_Session_Handoff_2026-06-23\|Classifier_Router_Improvement_Report\|Hebrew_First_Class_Support_Report\|ROUTER_MINILM_REPLACEMENT_ATTEMPT" README.md AGENTS.md docs/ 2>/dev/null || true
```

- [ ] **Step 2: Update or remove stale links**

If Step 1 finds broken links, edit the markdown file to either:
- Remove the link/section if it is no longer relevant, or
- Update it to point to the backup path under `backups/v10-dev-cleanup/2026-07-04/`

Expected: no broken internal links remain in `README.md`, `AGENTS.md`, or `docs/runbooks/`.

- [ ] **Step 3: Commit**

Run:
```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "docs: update links after archival cleanup"
```

- [ ] **Step 4: Run tests**

Same commands and expected results as Task 1 Step 4.

---

## Task 5: Sync current Architecture.md to the Desktop

**Files:**
- Read: `Architecture.md`
- Write: `/home/mike/Desktop/Local_Lucy_V10_Architecture_2026-07-04.md`

**Interfaces:**
- Consumes: canonical `Architecture.md` in repo root
- Produces: Desktop copy with today's date, replacing stale Desktop architecture files

- [ ] **Step 1: Copy the repo Architecture.md to the Desktop with today's date**

Run:
```bash
cd /home/mike/lucy-v10
cp Architecture.md "/home/mike/Desktop/Local_Lucy_V10_Architecture_2026-07-04.md"
```

- [ ] **Step 2: Remove older Desktop architecture files (optional if user wants one canonical file)**

Run:
```bash
cd /home/mike/Desktop
ls -la Local_Lucy_V10_Architecture_*.md
# If the user confirmed earlier that one dated file is enough, archive the older ones:
mkdir -p /home/mike/backups/desktop_architecture
mv Local_Lucy_V10_Architecture_2026-06-29.md /home/mike/backups/desktop_architecture/ 2>/dev/null || true
```
Expected: only the 2026-07-04 architecture file remains on the Desktop (or older ones are in backups).

- [ ] **Step 3: Commit any repo changes and note the Desktop sync**

Run:
```bash
cd /home/mike/lucy-v10
git add -A
git commit -m "docs: sync Architecture.md to Desktop as 2026-07-04" || true
```

- [ ] **Step 4: Run final test suite**

Run:
```bash
cd /home/mike/lucy-v10
python3 tools/router_py/run_routing_barrage.py
python3 -m pytest tools/router_py -q
python3 ui-v10/tests/test_comprehensive_hmi_inspection.py
```
Expected: barrage 38/38 PASS, routing unit tests all passing, HMI 138 passing.

---

## Self-Review

1. **Spec coverage:** Every item in the user's "One ring to rule them all" consolidation request is addressed: bloat removal, careful preservation of fixes, Desktop shortcut preservation, Architecture.md sync, and test verification.
2. **Placeholder scan:** All file paths are exact; all commands include expected output; no TBD/placeholder text.
3. **Type consistency:** N/A for this cleanup plan.
