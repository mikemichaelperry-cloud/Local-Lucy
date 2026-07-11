# Local Lucy V11 — Session Handoff

**Date:** 2026-07-11
**Branch:** `v10-dev`
**Latest commit:** `999739d`
**Repo:** `/home/mike/lucy-v10`

---

## What was done this session

- Fixed the Grok top-priority issues plus the related state/voice bugs discovered while verifying them:
  1. **Control toggles ↔ live state:** `ensure_control_env()` and `_apply_state_to_env()` now overwrite process env from `current_state.json` on every HMI action and router submit.
  2. **HMI shutdown crash:** `RuntimeActionTask.cancel()` stops the worker cooperatively and prevents the shutdown `AttributeError`.
  3. **Learner fail-closed:** high-stakes feedback gate treats any policy exception as high-stakes; `LUCY_AUTO_LEARN` defaults off.
  4. **Memory DB path:** resolves via `xdg_paths.lucy_memory_db_path()` with `LUCY_MEMORY_DB_PATH` override.
  5. **Voice PTT workspace root:** `tools/lucy_voice_ptt.sh` now uses the correct `LUCY_WORKSPACE_ROOT`.
  6. **State file resolution:** `load_state_from_file()` reads the HMI's actual namespace state file, not the legacy project-root path.
  7. **Model unload on switch:** heartbeat and warmup threads restart when the selected model changes so the previous model is not kept warm.
  8. **Test cleanup:** removed stale shell-router comparison tests from `tools/router_py/test_utils.py`.

- Raised the Kimi turn limit to `max_steps_per_turn = 1000` in `/home/mike/.kimi-code/config.toml`.

---

## Current state

- All changes are committed locally on `v10-dev`.
- Working tree is clean except for three untracked files:
  - `count_inotify_watches.py` (diagnostic script from the inotify investigation)
  - `docs/Session_Report_Grok_2026-07-10_Ubuntu_Chess_and_Local_Lucy.md`
  - `docs/superpowers/plans/2026-07-11-grok-top-issues.md`

### Verification evidence

| Suite | Result |
|---|---|
| `LUCY_TEST_LIVE_APIS=1 make test` | **1073 passed, 10 skipped, 1 deselected** |
| `tools/router_py/test_e2e_hmi_voice.py` | **15/15 passed** |
| `tools/tests/test_voice_*.sh` (5 scripts) | **5/5 passed** |
| `tools/router_py/test_local_answer.py` + `test_utils.py` | **70/70 passed** |
| `tools/thrash_test_fast.py` | **28/28 passed** |
| Voice E2E stress loop (5 runs) | **75/75 passed** |
| `tools/router_py/run_barrage.py` | **12/12 completed** |

- inotify usage is **499/524,288 watches** — no current pressure.

---

## Known limitations / next session

1. **Bloat cleanup is the next priority.** The repo has accumulated large, repetitive files from earlier agents. The next session should audit and trim them without changing runtime behavior.
2. **10 semantic-regression tests are skipped** because goldens were recorded for `local-lucy-llama31` but the current model resolves to `local-lucy`. Re-record with `LUCY_SEMANTIC_REGRESSION_RECORD=1` when the model choice is stable.
3. `run_barrage.py` has no `--count` option; it always runs the fixed pilot list.

---

## Resume commands

```bash
cd /home/mike/lucy-v10
git status
git log --oneline -5
make test
```

End of handoff.
