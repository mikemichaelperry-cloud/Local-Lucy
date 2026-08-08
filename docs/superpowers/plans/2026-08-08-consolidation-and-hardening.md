# Local Lucy v11 Consolidation & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address the five assessment concerns — carried test failures, brittle scenario assertions, legacy accretion, auto-learn default, and stale live config — with surgical, verified changes.

**Architecture:** No product-behavior changes except one deliberate default flip (auto-learn → opt-in). All other tasks fix stale tests, deduplicate harness logic, or delete dead code. No prompt/routing/memory-path changes, so **no STAGE_19 re-run is required**; verification is the CPU suite + targeted HMI offscreen tests + (Task 3 only) the two GPU scenario suites.

**Tech Stack:** Python 3.10 (`ui-v10/.venv`), pytest, Ollama (Gemma/Llama for Task 3 verification only).

## Global Constraints

- Repo: `/home/mike/lucy-v11`, branch `main`, HEAD `77afa8a`. Read `AGENTS.md` + `SESSION_CONTEXT.md` first.
- MINIMAL diffs; match existing style; no unrelated cleanup.
- TDD where behavior changes; commit after every task (message style: `fix(tests): ...`, `feat(qual): ...`, etc.).
- GPU discipline: only Task 3's verification loads models; run stage scripts sequentially, verify `curl -s localhost:11434/api/ps` is empty first. Never run two model-bearing scripts at once.
- Files under `SHA256SUMS` discipline: after modifying hashed files, regenerate manifests with `make sha` (root) and the ui-v10 equivalent if ui-v10 files change.
- Docs culture: behavior-affecting decisions get a DEC entry in `qualification/DECISIONS.md` (highest used: DEC-016; format `## DEC-NNN — YYYY-MM-DD — Title` with **Context:** / **Decision:** / **Alternatives considered:** / **Consequences:**).
- Do not touch: SQLite schemas, router classification behavior, HMI redesign, model weights, `tools/voice/` runtime.
- Every task ends with `git status --short` clean except intended files.

## Verified Ground Truth (recon 2026-08-08 — trust these)

- Full CPU suite on HEAD: **2 failed / 1588 passed / 7 skipped** (`pytest tools/router_py/ tools/tests/ -q --tb=no -rf`, ~7.5 min). The 2 failures are stale expectations of the pre-`5591c1a` text-file fallback contract.
- Current contract (`tools/router_py/execution_engine/helpers.py:335-352`): text-file fallback happens **only when SQLite assembly raises**; an empty SQLite result is honored (prevents cross-session leakage).
- Auto-learn conflict: `tools/runtime_control.py:404` reads `os.environ.get("LUCY_AUTO_LEARN", "1")` (defaults ON); `models/router/background_learner.py:124` reads default `"0"` (OFF). Existing trigger tests set `LUCY_AUTO_LEARN=1` explicitly, so flipping the default breaks nothing.
- Concept-check logic is duplicated character-for-character at `stage_09_gemma_scenario_suite.py:225-258` and `stage_11_llama_scenario_suite.py:277-315` (stage_11 wraps concepts via `_adapt_concepts_for_llama`, lines 192-203). Both suites now record `response_text`.
- `LUCY_ROUTER_PY`/`LUCY_EXEC_PY`: no functional reads; one cosmetic read at `ui-v10/app/services/state_store.py:238-239` (`_detect_router` display string). Set sites: `START_LUCY.sh:73-74`, `lucy_chat.sh:40-41`, `tools/lucy_voice_ptt.sh:1110-1112`, `tools/router_py/benchmark_e2e_latency.py:43-44`, `tools/thrash_test_fast.py:18-19`, `compare_v10_v11_accuracy.py:49`, `ui-v10/app/backend/router/execute_plan.sh:6`, `ui-v10/app/services/runtime_bridge.py:281-289`, `ui-v10/tests/unified/conftest.py:20-21`, `tools/router_py/test_voice_integration.py:68`.
- `models/router/qwen3_router.py` is dead (referenced only in `SHA256SUMS:133` and `SHA256SUMS.clean:133`). `models/router/hybrid_router_v2.py` is the LIVE primary router — do not touch.
- Stale live config: `config/system_prompt.txt:6` says "The default fast path is qwen3:14b" — false since the llama31 default.
- Default-model outlier: `tools/router_py/test_synthetic_adversarial.py:66` defaults `LUCY_LOCAL_MODEL` to `local-lucy-fast` (all real defaults are `local-lucy-llama31`).
- `local-lucy-memory` Ollama tag: zero references anywhere. Other legacy tags appear only in test fixtures (by name string, no pulls) and `config/quarantined/` Modelfiles.
- `qualification/TEST_STATUS.json` has no field for known-failing tests (`active_defects` is at line ~152).

---

### Task 1: Fix the two stale memory-fallback tests

**Files:**
- Modify: `tools/router_py/test_request_pipeline_contract.py` (~line 100-150, `TestMemoryRecallQuery::test_memory_recall_uses_stored_fact`)
- Modify: `tools/tests/test_memory_integration.py` (~line 80-110, `test_execution_engine_falls_back_to_text_file_when_sqlite_empty`)

**Interfaces:**
- Consumes: `_load_session_memory_context_with_telemetry()` in `tools/router_py/execution_engine/helpers.py:305` — falls back to text file ONLY on exception from `assemble_context_with_telemetry`.
- Produces: green suite; no new symbols.

- [ ] **Step 1: Reproduce the failures**

Run: `cd /home/mike/lucy-v11 && source ui-v10/.venv/bin/activate && python -m pytest tools/router_py/test_request_pipeline_contract.py::TestMemoryRecallQuery::test_memory_recall_uses_stored_fact tools/tests/test_memory_integration.py::TestMemoryIntegration::test_execution_engine_falls_back_to_text_file_when_sqlite_empty -q`
Expected: 2 FAILED (`assert 'blue' in ''`; `'User: Fallback question' not found in ''`).

- [ ] **Step 2: Update both tests to the post-`5591c1a` contract**

In `test_request_pipeline_contract.py`: the test mocks `assemble_context_with_telemetry` to return `("", ...)`. Change the expectation so an **empty** SQLite result is honored (loaded context is empty; no text-file content leaks in), and add a comment: `# Post-5591c1a contract: empty SQLite context is honored; text-file fallback only on exception.`

Then add a companion test in the same class proving the fallback still fires on exception. Procedure: copy the existing test method verbatim as `test_memory_recall_falls_back_to_text_file_on_sqlite_error`, keep its fixtures unchanged, make exactly two edits — (1) change the mock on `assemble_context_with_telemetry` from `return_value=("", ...)` to `side_effect=RuntimeError("boom")`, (2) change the assertion to expect the seeded text-file fact (`"blue"`) to appear in the loaded context. No other changes.

In `test_memory_integration.py::test_execution_engine_falls_back_to_text_file_when_sqlite_empty`: either (a) repoint it to the exception path (rename to `..._when_sqlite_raises`, make the SQLite call raise, keep the `'User: Fallback question'` assertion), or (b) if the fixture cannot easily force an exception, delete the test and add the exception-path assertion to the companion test above. Prefer (a).

- [ ] **Step 3: Run the two test files to green**

Run: `python -m pytest tools/router_py/test_request_pipeline_contract.py tools/tests/test_memory_integration.py -q`
Expected: all passed.

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/test_request_pipeline_contract.py tools/tests/test_memory_integration.py
git commit -m "fix(tests): align memory text-file fallback tests with post-5591c1a contract"
```

---

### Task 2: Make auto-learn opt-in (flip `runtime_control.py` default)

**Files:**
- Modify: `tools/runtime_control.py:399-407` (`_resolve_initial_learner_state`)
- Test: `tools/tests/test_runtime_toggles.py` (add cases; file exists, see its current env-fixture style around line 36)
- Modify: `qualification/DECISIONS.md` (add DEC-017)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `_resolve_initial_learner_state()` returns `"off"` when neither `.learner_disable` flag nor env is set; `"on"` only when `LUCY_AUTO_LEARN=1`.

- [ ] **Step 1: Write the failing test**

In `tools/tests/test_runtime_toggles.py`, add (matching the file's existing monkeypatch/tmp_path style; note the real flag path is `models/router/.learner_disable` — assert against the real resolver, ensuring the flag does not exist during the test):

```python
def test_learner_defaults_off_without_env(monkeypatch):
    monkeypatch.delenv("LUCY_AUTO_LEARN", raising=False)
    from runtime_control import _resolve_initial_learner_state
    flag = __import__("pathlib").Path(__import__("runtime_control").__file__).resolve().parent.parent / "models" / "router" / ".learner_disable"
    assert not flag.exists(), "precondition: no disable flag"
    assert _resolve_initial_learner_state() == "off"

def test_learner_on_with_explicit_env(monkeypatch):
    monkeypatch.setenv("LUCY_AUTO_LEARN", "1")
    from runtime_control import _resolve_initial_learner_state
    assert _resolve_initial_learner_state() == "on"
```

- [ ] **Step 2: Run to verify the first test fails**

Run: `python -m pytest tools/tests/test_runtime_toggles.py -k learner -q`
Expected: `test_learner_defaults_off_without_env` FAILS (currently returns `"on"`).

- [ ] **Step 3: Flip the default**

`tools/runtime_control.py:404`: change `os.environ.get("LUCY_AUTO_LEARN", "1") == "0"` logic so unset means off. Minimal form:

```python
    if os.environ.get("LUCY_AUTO_LEARN", "0").strip().lower() in ("1", "true", "yes", "on"):
        return "on"
    return "off"
```

- [ ] **Step 4: Run to verify pass + no collateral**

Run: `python -m pytest tools/tests/test_runtime_toggles.py -k learner -q && python -m pytest models/router/ tools/router_py/test_feedback_loop_integration.py -q`
Expected: all passed (feedback tests set the env explicitly).

- [ ] **Step 5: DEC-017 + docs**

Add `## DEC-017 — 2026-08-08 — Auto-learn defaults to opt-in` to `qualification/DECISIONS.md`: Context (conflicting defaults; `runtime_control` ON vs `background_learner` OFF; silent self-modification risk), Decision (flip `runtime_control` to opt-in, matching `background_learner`), Alternatives (keep ON — rejected: silent embedding rebuilds from conversational feedback), Consequences (fresh installs ship learner off; enable via HMI toggle or `LUCY_AUTO_LEARN=1`). Update `AGENTS.md` env section: remove "(effective default is ON via runtime_control.py)" / change `LUCY_AUTO_LEARN` comment to `default OFF (opt-in)`; same for the `LUCY_AUTO_LEARN` row in `SESSION_CONTEXT.md`.

- [ ] **Step 6: Commit**

```bash
git add tools/runtime_control.py tools/tests/test_runtime_toggles.py qualification/DECISIONS.md AGENTS.md SESSION_CONTEXT.md
git commit -m "fix(runtime): default auto-learn to opt-in (DEC-017)"
```

---

### Task 3: Share and harden scenario-concept checking (stage 09/11)

**Files:**
- Create: `tools/router_py/scenario_checks.py`
- Create: `tools/router_py/test_scenario_checks.py`
- Modify: `tools/router_py/stage_09_gemma_scenario_suite.py:225-258` (replace inline block)
- Modify: `tools/router_py/stage_11_llama_scenario_suite.py:277-315` (replace inline block; keep `_adapt_concepts_for_llama`)
- Modify: `qualification/scenarios/shared_scenario_suite.json` (S09-GEM-007 entry → use new any-of field)

**Interfaces:**
- Produces: `evaluate_response(scenario: dict, final_outcome) -> tuple[bool, list[str]]` — the single evaluation entry point both suites call. Supports scenario keys: `expected_route` (str or list), `required_answer_concepts` (all-of), `required_answer_concepts_any` (any-of, NEW), `forbidden_answer_claims`, `required_structure` (`"haiku"`).

- [ ] **Step 1: Write the failing unit tests**

Create `tools/router_py/test_scenario_checks.py`:

```python
from types import SimpleNamespace

from scenario_checks import evaluate_response


def _outcome(route="LOCAL", text=""):
    return SimpleNamespace(route=route, response_text=text)


def test_required_concepts_all_of():
    sc = {"expected_route": "LOCAL", "required_answer_concepts": ["Local Lucy", "assistant"]}
    assert evaluate_response(sc, _outcome(text="I am Local Lucy, your assistant")) == (True, [])
    passed, notes = evaluate_response(sc, _outcome(text="I am your assistant"))
    assert not passed and notes == ["missing required concept: Local Lucy"]


def test_required_concepts_any_of():
    sc = {"required_answer_concepts_any": ["because", "since", "therefore"]}
    assert evaluate_response(sc, _outcome(text="Sky is blue since..."))[0] is True
    passed, notes = evaluate_response(sc, _outcome(text="Sky is blue."))
    assert not passed and "any of" in notes[0]


def test_expected_route_accepts_list():
    sc = {"expected_route": ["AUGMENTED", "LOCAL"]}
    assert evaluate_response(sc, _outcome(route="LOCAL", text="x"))[0] is True
    assert evaluate_response(sc, _outcome(route="WEATHER", text="x"))[0] is False


def test_forbidden_claims_and_haiku():
    sc = {"forbidden_answer_claims": ["OpenAI"]}
    assert evaluate_response(sc, _outcome(text="made by OpenAI"))[0] is False
    haiku = {"required_structure": "haiku"}
    assert evaluate_response(haiku, _outcome(text="one\ntwo\nthree"))[0] is True
    assert evaluate_response(haiku, _outcome(text="one\ntwo"))[0] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tools/router_py/test_scenario_checks.py -q`
Expected: FAIL (`ModuleNotFoundError: scenario_checks`).

- [ ] **Step 3: Implement `tools/router_py/scenario_checks.py`**

```python
"""Shared response evaluation for the stage 09/11 scenario suites.

Single source of truth for concept/structure assertions. Substring checks on
free-form model output flake on phrasing; prefer required_answer_concepts_any
where the concept matters but the vocabulary does not (see DEC-016).
"""
from __future__ import annotations


def evaluate_response(scenario: dict, final_outcome) -> tuple[bool, list[str]]:
    """Evaluate a scenario's final outcome. Returns (passed, notes)."""
    raw_text = final_outcome.response_text or ""
    response_text = raw_text.lower()
    notes: list[str] = []
    passed = True

    expected_route = scenario.get("expected_route")
    if expected_route:
        allowed = expected_route if isinstance(expected_route, list) else [expected_route]
        if final_outcome.route not in allowed:
            notes.append(f"route expected {expected_route}, got {final_outcome.route}")
            passed = False

    for concept in scenario.get("required_answer_concepts", []):
        if concept.lower() not in response_text:
            notes.append(f"missing required concept: {concept}")
            passed = False

    any_concepts = scenario.get("required_answer_concepts_any", [])
    if any_concepts and not any(c.lower() in response_text for c in any_concepts):
        notes.append(f"missing required concept (any of: {any_concepts})")
        passed = False

    for claim in scenario.get("forbidden_answer_claims", []):
        if claim.lower() in response_text:
            notes.append(f"forbidden claim present: {claim}")
            passed = False

    if scenario.get("required_structure") == "haiku":
        lines = [line for line in raw_text.strip().splitlines() if line.strip()]
        if len(lines) != 3:
            notes.append("haiku does not have 3 lines")
            passed = False

    return passed, notes
```

- [ ] **Step 4: Run unit tests to green**

Run: `python -m pytest tools/router_py/test_scenario_checks.py -q`
Expected: 4 passed.

- [ ] **Step 5: Wire both suites to the helper; move S09-GEM-007 to the generic field**

In `stage_09_gemma_scenario_suite.py`: delete lines 225-258's inline logic (keep the `response_text` capture line if used elsewhere) and replace with:

```python
    passed, notes = evaluate_response(scenario, final_outcome)
```

(add `from scenario_checks import evaluate_response` to imports, matching how the suite imports sibling modules — check its existing import block, e.g. `sys.path` style vs package-relative, and copy that idiom.)

Remove the hardcoded `if scenario.get("id") == "S09-GEM-007"` special case entirely.

In `stage_11_llama_scenario_suite.py`: keep `_adapt_concepts_for_llama`; build the adapted scenario and call the helper:

```python
    required_concepts, forbidden_claims = _adapt_concepts_for_llama(scenario)
    adapted = {**scenario, "required_answer_concepts": required_concepts,
               "forbidden_answer_claims": forbidden_claims}
    passed, notes = evaluate_response(adapted, final_outcome)
```

Delete the duplicated substring/haiku block (lines ~277-315).

In `qualification/scenarios/shared_scenario_suite.json`, S09-GEM-007 entry: replace `"required_answer_concepts": ["because", "since", "therefore"]` with `"required_answer_concepts_any": ["because", "since", "therefore"]` (verify exact current key names in that entry first).

Do NOT change S09-MEM-003 — it stays strict (the identity name matters; flakes are now diagnosable via `response_text`).

- [ ] **Step 6: Verify — unit suites, then GPU scenario suites (sequential)**

Run: `python -m pytest tools/router_py/test_scenario_checks.py tools/router_py/test_stage_07_prompt_parity.py -q` → passed.
Then GPU (check `curl -s localhost:11434/api/ps` empty first; run one at a time, ~5 min and ~1 min):
`python3 tools/router_py/stage_09_gemma_scenario_suite.py` → expect 16/16.
`python3 tools/router_py/stage_11_llama_scenario_suite.py` → expect 16/16 (12/12 route+outcome parity lines as before).
If a scenario fails on wording, read `response_text` in `qualification/results/stage_*_scenarios.json` before touching anything — do not relax assertions silently.

- [ ] **Step 7: Commit**

```bash
git add tools/router_py/scenario_checks.py tools/router_py/test_scenario_checks.py \
  tools/router_py/stage_09_gemma_scenario_suite.py tools/router_py/stage_11_llama_scenario_suite.py \
  qualification/scenarios/shared_scenario_suite.json qualification/results/
git commit -m "refactor(qual): share scenario evaluation, add required_answer_concepts_any"
```

---

### Task 4: Remove dead `LUCY_ROUTER_PY` / `LUCY_EXEC_PY` env plumbing

**Files:**
- Modify: `START_LUCY.sh:73-74`, `lucy_chat.sh:40-41`, `tools/lucy_voice_ptt.sh:1110-1112`, `tools/router_py/benchmark_e2e_latency.py:43-44`, `tools/thrash_test_fast.py:18-19`, `compare_v10_v11_accuracy.py:49`, `ui-v10/app/backend/router/execute_plan.sh:6`, `ui-v10/app/services/runtime_bridge.py:281-289`, `ui-v10/tests/unified/conftest.py:20-21`, `tools/router_py/test_voice_integration.py:68`
- Modify: `ui-v10/app/services/state_store.py:238-239` (`_detect_router`)

**Interfaces:**
- Consumes: nothing. Produces: zero remaining references (verified by grep); `_detect_router()` returns the constant string `"Python"`.

- [ ] **Step 1: Baseline grep**

Run: `grep -rn "LUCY_ROUTER_PY\|LUCY_EXEC_PY" --include="*.py" --include="*.sh" . | grep -v backups/ | wc -l`
Expected: ~12 lines (the set sites above + state_store read).

- [ ] **Step 2: Delete the set sites**

Remove the export/setdefault lines at each location listed above (in `runtime_bridge.py:281-289` delete the whole passthrough block including `LUCY_ROUTER_PY_PERCENTAGE/_DETERMINISTIC/_EMERGENCY_KILL` if those are also unread — verify with grep first; delete only what nothing reads). In `test_voice_integration.py:68` remove the setenv and its comment.

- [ ] **Step 3: Simplify `_detect_router`**

In `ui-v10/app/services/state_store.py`, replace the env-reading logic at :238-239 with `return "Python"` (keep the function name/signature — the status panel calls it).

- [ ] **Step 4: Verify**

Run: `grep -rn "LUCY_ROUTER_PY\|LUCY_EXEC_PY" --include="*.py" --include="*.sh" . | grep -v backups/` → expect zero hits (README historical mentions in *.md may stay).
Run HMI offscreen + voice tests: `QT_QPA_PLATFORM=offscreen python3 ui-v10/tests/test_comprehensive_hmi_inspection.py` → checks passed; `python -m pytest tools/router_py/test_voice_integration.py ui-v10/tests/ -q` → passed.
Regenerate manifests (hashed files changed): `make sha` and the ui-v10 manifest equivalent if the repo has one (`ui-v10/SHA256SUMS*` — regenerate per repo convention, check Makefile target).

- [ ] **Step 5: Commit**

```bash
git add -A  # review the staged list first: only the intended files + manifests
git commit -m "chore: remove dead LUCY_ROUTER_PY/LUCY_EXEC_PY plumbing"
```

---

### Task 5: Prune dead code, stale live config, and orphaned model tags

**Files:**
- Delete: `models/router/qwen3_router.py` (+ drop lines 133 from `SHA256SUMS` and `SHA256SUMS.clean` via `make sha`)
- Modify: `config/system_prompt.txt:6` (stale qwen3 line)
- Modify: `tools/router_py/test_synthetic_adversarial.py:66` (default outlier)
- Host-level (NOT git): `ollama rm` of orphaned tags — **requires explicit user approval at execution time**

**Interfaces:**
- Consumes: nothing. Produces: no functional interface changes.

- [ ] **Step 1: Delete the dead router script**

`git rm models/router/qwen3_router.py`, then `make sha` to regenerate manifests. Run: `python -m pytest tools/router_py/ -q -k "sha or manifest or discipline"` → passed (repo has discipline tests for the manifests).

- [ ] **Step 2: Fix the stale live system-prompt line**

Read `config/system_prompt.txt` fully first. Replace the false sentence at line 6 ("The default fast path is qwen3:14b") with the true default (`local-lucy-llama31`, llama3.1:8b), mirroring the identity wording in `tools/router_py/local_answer_core/self_knowledge.py:261-267`. Run: `python -m pytest tools/router_py/test_gemma4_identity.py tools/router_py/test_stage_07_prompt_parity.py -q` → passed (parity tests compare prompt blocks; adjust only if they assert the old sentence).

- [ ] **Step 3: Fix the default-model outlier in the deselected test**

`tools/router_py/test_synthetic_adversarial.py:66`: change the fallback `"local-lucy-fast"` → `"local-lucy-llama31"`, and fix the docstring line ~28 likewise. (File is pytest-ignored by addopts; no run needed beyond `python -m py_compile`.)

- [ ] **Step 4: Prune orphaned Ollama tags (user-approved, host-level)**

Proposed removal list (zero or fixture-only references): `local-lucy-memory` (fully orphaned), `local-lucy-qwen3`, `local-lucy-mistral`, `local-lucy-stable`, `local-lucy`, `local-lucy-fast`, `qwen3:30b`, `qwen3:14b`, `mistral-nemo:latest`.
KEEP: `local-lucy-llama31`, `local-lucy-gemma4`, `local-lucy-llama31-michael`, `local-lucy-llama31-racheli`, `gemma4_code_review_agentic`, `llama3.1:8b` (base image), `gemma4:12b-it-qat` (identity-map references), `hf.co/yuxinlu1/...` (FROM base of the code-review Modelfile).
Present the list to the user for approval; execute only approved removals via `ollama rm <tag>`. Then run `python -m pytest tools/router_py/test_ollama_cleanup.py tools/router_py/test_model_selector.py -q` → passed.

- [ ] **Step 5: Commit**

```bash
git add -A  # review staged list first
git commit -m "chore: prune dead qwen3 router script and stale model references"
```

---

### Task 6 (OPTIONAL — recommend defer): Rename `ui-v10/` → `ui/`

**Recommendation: skip in this pass.** Blast radius is broad (~200 references, isolation guards at `tools/runtime_control.py:342` and `tools/router_py/voice/pipeline.py:883` validate the literal directory name, `ui-v10/.venv` has baked-in absolute paths requiring `make install` to recreate, both SHA manifests regenerate). Value is cosmetic. If the user still wants it, execute as its own dedicated session: `git mv ui-v10 ui` → sed the reference list (from recon item 5) → update the two isolation guards → recreate venv → `make sha` → full CPU suite + HMI offscreen + one GPU smoke (stage_08). Do not combine with any other task.

---

### Task 7: Closeout — status tracking, docs, full verification

**Files:**
- Modify: `qualification/TEST_STATUS.json` (add `known_failing_tests` field near `active_defects`)
- Modify: `qualification/DECISIONS.md` (DEC-018)
- Modify: `SESSION_CONTEXT.md` (new session section; clear TODO #27 wording; mark TODOs 24-28 progress)
- Modify: `AGENTS.md` (footgun 7: point to `scenario_checks.py`; remove resolved warnings)
- Sync: Desktop copies of `SESSION_CONTEXT.md`, `SESSION_HANDOFF.md` (if regenerated), `Local_Lucy_V11_DECISIONS.md`

- [ ] **Step 1: Add carried-failure tracking to TEST_STATUS.json**

Add after `active_defects`:

```json
  "known_failing_tests": [],
```

(with a one-line `"known_failing_tests_note": "Must stay empty; any carried failure needs a DEC entry."` if the file's style allows sibling notes — check its formatting first and preserve exact JSON validity.)

- [ ] **Step 2: DEC-018 — scenario assertion hardening**

Add `## DEC-018 — 2026-08-08 — Shared scenario evaluation and any-of concept checks`: Context (duplicated substring logic in stage_09/11; S09-MEM-003 flake 2026-08-07; hardcoded S09-GEM-007 special case), Decision (single `scenario_checks.evaluate_response`; new `required_answer_concepts_any` JSON field; S09-MEM-003 stays strict), Alternatives (relax S09-MEM-003 to accept "Lucy" — rejected: identity name is the point of the scenario), Consequences (flake surface reduced; future relaxations are schema changes, not code special cases).

- [ ] **Step 3: Update SESSION_CONTEXT.md and AGENTS.md**

SESSION_CONTEXT: new "Consolidation & Hardening — 2026-08-08" section (tasks 1-5 summary + results); TODO list: mark #27 resolved-by-DEC-018, add #29 "ui-v10 rename deferred (see plan)". AGENTS.md footgun 7: rewrite to reference `tools/router_py/scenario_checks.py` and the `required_answer_concepts_any` field.

- [ ] **Step 4: Full verification**

Run: `source ui-v10/.venv/bin/activate && python -m pytest tools/router_py/ tools/tests/ models/router/ tools/lora/ -q -p no:cacheprovider --tb=short -rf` (background task, ~8 min, no GPU).
Expected: **0 failed** (1588+39+2-fixed ≈ 1629 passed), 7 skipped.

- [ ] **Step 5: Sync Desktop copies and commit**

`cp` the three updated docs to `~/Desktop/Local Lucy V11/` (`SESSION_CONTEXT.md`, `Local_Lucy_V11_DECISIONS.md` ← `qualification/DECISIONS.md`). Verify with `diff -q`. Then:

```bash
git add qualification/TEST_STATUS.json qualification/DECISIONS.md SESSION_CONTEXT.md AGENTS.md
git commit -m "docs: consolidation closeout, DEC-018, known_failing_tests tracking"
```

---

## Verification Summary (whole plan)

| Gate | Command | Expected |
|---|---|---|
| Unit (per task) | see task steps | green |
| GPU scenario suites (Task 3) | `stage_09...` then `stage_11...` (sequential) | 16/16 each |
| HMI offscreen (Task 4) | `test_comprehensive_hmi_inspection.py` | all checks passed |
| Full CPU suite (Task 7) | `pytest tools/router_py/ tools/tests/ models/router/ tools/lora/ -q` | **0 failed** |
| Grep gates | no `LUCY_ROUTER_PY`/`LUCY_EXEC_PY`; no qwen3 default text | zero hits |

Not required: STAGE_19 re-run (no prompt/routing/memory-path behavior changes; auto-learn flip does not affect the qualified request path — learning is post-response). If the user wants belt-and-braces, run `python3 tools/router_py/stage_19_clean_run.py` after Task 7 (~18 min).
