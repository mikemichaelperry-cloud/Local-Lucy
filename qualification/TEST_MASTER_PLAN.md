# Local Lucy V11 — Staged Independent End-to-End Qualification Programme

**Programme start:** 2026-07-30  
**Repository:** `/home/mike/lucy-v11`  
**Branch:** `main`  
**Last updated:** 2026-07-30

---

## 1. Objectives

Establish, as far as practical, that Local Lucy V11:

1. Starts and shuts down correctly.
2. Preserves behaviour after the Python module splits.
3. Preserves database schema and stored information.
4. Routes equivalent requests consistently.
5. Supplies semantically equivalent requests to Gemma and Llama.
6. Allows acceptable model-specific answer differences without architectural divergence.
7. Enforces permissions outside the language model.
8. Does not perform unintended network, file, tool, or memory operations.
9. Rejects malformed planner output before execution.
10. Handles model, provider, parser and database failures honestly.
11. Does not leak route, model, capability or session state.
12. Remains stable under sequential operation on an RTX 3060.
13. Produces diagnostics that identify the first failing stage.
14. Can be rerun after future Local Lucy changes.
15. Labels untrusted web sources correctly and does not present them as trusted evidence.
16. Blocks untrusted web sources for critical, current, and conspiracy-prone topics.
17. Exercises the HMI surface path (`RuntimeBridge` → `runtime_request.submit_request`) end-to-end, not only backend `request_pipeline.process()` or CLI paths.

The suite does **not** prove that models never hallucinate. It tests whether the surrounding architecture limits, detects, reports and avoids amplifying model failures.

---

## 2. Non-negotiable restrictions

- No broad architectural refactor.
- No router replacement.
- No redesign of production modules merely to simplify testing.
- No changes to Gemma/Llama weights, quantisation or Modelfiles.
- No replacement of Ollama.
- No modification of Michael’s real personality profile.
- No modification of the production memory database.
- No destructive tests against real user data.
- No weakening of medical, financial, security, privacy or permission controls.
- No hardcoding of expected prose answers.
- No requirement for Gemma and Llama to produce identical wording.
- No LLM as the sole test-result judge.
- No concurrent LLM inference.
- No `pytest-xdist` or equivalent for model tests.
- No test failures writing into production memory.
- No exposure of credentials, secrets or private memory in reports.
- No silent repair of production defects during test creation.
- No test marked passed merely because no exception occurred.
- No continuation into a dependent stage when a foundational failure makes its results invalid.
- No `fast` test bypasses the HMI surface; `model-smoke` and `full-qualification` must include HMI injection-to-output scenarios.

Production-code changes are allowed only for minimal, isolated, disabled-by-default testability hooks.

---

## 3. Stage list and dependencies

| Stage | Name | Depends on | Purpose |
|-------|------|------------|---------|
| STAGE_00 | Discovery, baseline and safety setup | — | Understand layout, create safe baseline, build control files. |
| STAGE_01 | Test harness and resumability framework | STAGE_00 | Scenario loader, runner, trace writer, resume mechanism. |
| STAGE_02 | Static, import and module-split integrity | STAGE_01 | Compile/import checks, circular imports, public interfaces. |
| STAGE_03 | Database, schema, queries and state | STAGE_02 | Disposable DB, transactions, rollback, query compatibility. |
| STAGE_04 | Persistent memory and self-learning | STAGE_03 | Facts, proposals, approval, contamination resistance. |
| STAGE_05 | Deterministic router, classifier and capability controls | STAGE_02 | Routing matrix, restrictions, state isolation, and untrusted-web routing decisions. |
| STAGE_06 | Planner, URL, provider and untrusted-web security | STAGE_02 | Malformed planner output, private-network blocks, mock providers, source-quality controls, misinformation tropes. |
| STAGE_07 | Prompt construction and semantic model parity | STAGE_05 | Gemma/Llama payload equivalence without full model suites. |
| STAGE_08 | Gemma model smoke qualification | STAGE_07 | Core real-model path with Gemma, sequential. |
| STAGE_09 | Full Gemma shared scenario suite | STAGE_08 | Complete common prompt catalogue on Gemma. |
| STAGE_10 | Model release and Llama smoke qualification | STAGE_08 | Release Gemma, run Llama smoke. |
| STAGE_11 | Full Llama shared suite and parity analysis | STAGE_09, STAGE_10 | Compare Llama against Gemma baseline. |
| STAGE_12 | Ollama, output parsing, HMI and limit handling | STAGE_08 | Response extraction, HMI surface injection-to-output, and boundary conditions. |
| STAGE_13 | Long-session continuity and model switching | STAGE_08, STAGE_12 | Multi-turn interaction, model switches. |
| STAGE_14 | Controlled fault injection and recovery | STAGE_03–STAGE_07 | Safe behaviour when components fail. |
| STAGE_15 | File, tool, privacy and audit controls | STAGE_02 | Permissions, path containment, redaction. |
| STAGE_16 | Performance, stability and RTX 3060 soak | STAGE_11 | Sequential stability measurements. |
| STAGE_17 | Optional live-network provider validation | STAGE_06 | Real external integrations, separately enabled. |
| STAGE_18 | Optional voice-path smoke validation | STAGE_12 | Voice components do not damage text path. |
| STAGE_19 | Final clean-run qualification | STAGE_00–STAGE_16 | Approved profiles from a clean process. |

---

## 4. Stage entry and exit criteria

### STAGE_00 exit criteria

- Production data locations are known and protected.
- Disposable test environment is available.
- Existing tests have been run and recorded.
- Newly introduced failures can be distinguished from pre-existing ones.
- No production data has been modified.

### STAGE_01 exit criteria

- A dummy multi-stage run can stop and resume correctly.
- Failed tests preserve evidence.
- TODO and status files update automatically.
- Parallel model execution is prevented.
- Production database use is blocked.
- Session handoff is generated automatically.

### STAGE_02–STAGE_19

Each stage has its own exit criteria in the full programme specification. In brief:

- Structural failures are resolved or formally blocked before Stage 03.
- No high-severity database defect remains before Stage 04.
- No high-severity routing defect remains before Stage 06.
- Untrusted-web fallback is correctly labelled and constrained before Stage 07.
- No unsafe failure remains unexplained before Stage 10.
- Sequential operation is stable before Stage 19.

---

## 5. Test profiles

Planned command profiles:

| Profile | Stages covered |
|---|---|
| `fast` | 02, 03 (part), 04 (part), 05, 06, 07, 12 (part), 14 (part), 15 (part). Static HMI surface smoke is allowed, but does not replace end-to-end HMI tests. |
| `model-smoke` | 08, 10, minimal switch tests, HMI surface injection-to-output (no models) |
| `gemma-full` | 09 |
| `llama-full` | 11 (Llama side) |
| `model-parity` | 11 (comparison) |
| `long-session` | 13 |
| `faults` | 14 |
| `performance` | 16 |
| `live-network` | 17 (separately enabled) |
| `voice-smoke` | 18 (separately enabled) |
| `full-qualification` | All mandatory stages in dependency order, including HMI surface injection-to-output scenarios |

Each profile supports `--resume`, `--from-test`, `--stage`, `--stop-on-critical`, `--preserve-failed-fixtures`, `--diagnostic`, `--no-production-data`.

---

## 6. Reporting

At the end of the programme, produce:

1. Machine-readable result set.
2. Human-readable programme summary.
3. Refactor-integrity report.
4. Gemma/Llama comparison.
5. Defect report ranked by severity.
6. Coverage and limitations statement.
7. Final qualification decision: `QUALIFIED`, `QUALIFIED_WITH_KNOWN_LIMITATIONS`, `NOT_QUALIFIED`, or `INCOMPLETE`.

---

## 7. Session continuity

- Every session begins by reading `TEST_MASTER_PLAN.md`, `TEST_STATUS.json`, `TEST_TODO.md`, `SESSION_HANDOFF.md`, `DEFECT_REGISTER.md`, and `DECISIONS.md`.
- Every session ends by updating those files and writing the exact resume command.
- The programme is successful when it creates a durable, repeatable and resumable qualification framework.

---

## 8. Untrusted-web source specifics

Local Lucy V11 now has a general-knowledge web fallback that fetches a single DuckDuckGo result when primary evidence providers fail. This path is **distinct** from trusted evidence routes and must be qualified explicitly.

### Must verify

1. The fallback fires only for ordinary `AUGMENTED` factual queries.
2. The fallback is **blocked** for:
   - `EVIDENCE` route queries;
   - high-stakes evidence reasons (`medical_context`, `medical_safety`, `medical_body_symptom`, `veterinary_context`, `legal_context`, `financial_high_stakes`, `financial_data`);
   - live/current topics (`current_information`, `conflict_live`, `news_synthesis`);
   - explicit `network=False` request constraints;
   - known conspiracy/hoax tropes (flat earth, moon-landing hoax, chemtrails, vaccine microchips, climate-change hoax, etc.).
3. When used, the answer is prefixed with an explicit untrusted-source caveat.
4. `RouterOutcome` fields reflect `provider=web_untrusted` and `trust_label=untrusted`.
5. Source URL and title are captured in metadata and redacted from normal logs if they contain private query text.

### Source-quality roadmap

- **Stage 06** must include adversarial cases where DuckDuckGo returns a known low-quality domain and prove the engine drops it or labels it honestly.
- **Stage 15** must verify that untrusted-source metadata does not leak into production memory or ordinary logs.
- **Stage 17** live-network tests must distinguish trusted evidence from untrusted web results and not treat a DuckDuckGo hit as verified evidence.
- A future source-quality layer (domain allowlist/blocklist, cross-source agreement) may be added; the qualification programme must be updated accordingly.

---

## 9. HMI injection-to-output coverage

The HMI submit path is `ui-v10/app/services/runtime_bridge.py::RuntimeBridge.submit_request()` → `_run_submit_request_direct()` → `tools/runtime_request.py::submit_request(surface="hmi")`.

`RuntimeBridge` applies `current_state.json` toggles to the process environment, runs shadow model selection, handles model unload/load, and adds HMI-specific display metadata on top of the canonical backend payload. This is the layer the user wants exercised end-to-end.

### Required coverage

1. **Static HMI path smoke (no Ollama, no network)** — instantiate `RuntimeBridge` with a disposable namespace and state file, mock `runtime_request.submit_request`, submit a trivial request, and assert the returned `CommandResult.payload` carries a valid route/outcome.
2. **HMI state propagation** — changing a toggle in `current_state.json` (e.g., `evidence`, `memory`, `voice`) must be reflected in the environment before the backend request runs.
3. **HMI surface in model-smoke** — at least one real-model request must be submitted through `RuntimeBridge` (or equivalent HMI surface wrapper) rather than calling `request_pipeline.process()` directly.
4. **HMI voice-disabled path** — with `voice=off`, a submitted request must not invoke voice workers and must still return a text answer.
5. **HMI error path** — a backend failure returned by `submit_request` must be translated into a `CommandResult` with accurate `status`, `stderr`, and `payload`.

### Implementation note

For static tests, the harness must:

- set `LUCY_RUNTIME_CONTRACT_REQUIRED=0`;
- set `LUCY_RUNTIME_AUTHORITY_ROOT=/home/mike/lucy-v11`;
- use a temporary `LUCY_RUNTIME_NAMESPACE_ROOT`;
- disable background warmup (`LUCY_DISABLE_BACKGROUND_WARMUP=1` or run under pytest);
- mock or bypass Ollama/model-loading calls;
- avoid touching production `current_state.json` or memory databases.
