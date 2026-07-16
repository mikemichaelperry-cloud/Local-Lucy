# Design: Dedicated Gemma 4 Coding and Code-Review Model

**Date:** 2026-07-16
**Branch target:** `v10-dev`
**Approach:** Extend existing `SelfAnalysisEngine` / `SELF_REVIEW` path (Approach A)

## 1. Goal

Integrate the specialist model
`hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M`
into Local Lucy’s existing Code Review and Analysis mode. Use it exclusively for
code review, static analysis, architecture analysis, debugging, defect
investigation, test-generation planning, patch planning, and carefully bounded
coding tasks. Keep it out of normal conversation.

## 2. Non-goals

- Do not make the specialist model the default conversational model.
- Do not alter normal Local Lucy routing.
- Do not create a parallel code-review subsystem.
- Do not refactor unrelated components.
- Do not remove or overwrite existing model definitions.
- Do not delete any installed model.
- Do not weaken security, privacy, tool-access, or command-execution controls.

## 3. Audit summary

The current Code Review / Analysis mode is activated by the `self_analysis_mode`
toggle in runtime state. `ExecutionEngine.execute_async` detects query keywords
(`analyze`, `review`, `improve`, `inspect`) and a file reference, then calls
`execute_self_analysis`, which runs `SelfAnalysisEngine.suggest_improvements`.
That method builds a static-analysis block and calls `LocalAnswer.generate_answer`
with `route_mode="SELF_REVIEW"`. The active model is whatever
`LocalAnswerConfig.from_env().model` returns (usually the user-selected model).

The inference path does not load Whisper or Kokoro, but the HMI still passes the
response to Kokoro TTS after it returns.

There is also a secondary CLI path in `tools/runtime_request.py` that is **not**
used by the HMI; this design leaves it unchanged.

## 4. Design

### 4.1 Model registration

Add one clearly named backend alias:

```text
gemma4_code_review_agentic
```

Map it to the exact Ollama identifier:

```text
hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M
```

Add the mapping to `_MODEL_IDENTITIES` in `tools/router_py/local_answer.py` so
self-knowledge answers are accurate.

### 4.2 Configuration

Add a new runtime state field and env var:

- State key: `code_review_model`
- Env var: `LUCY_CODE_REVIEW_MODEL`
- Default: `gemma4_code_review_agentic`

Add an enable flag so the feature can be rolled back without source changes:

- State key: `code_review_specialist_enabled`
- Env var: `LUCY_CODE_REVIEW_SPECIALIST_ENABLED`
- Default: `on` (use specialist model when available)

Both fields are managed by `tools/runtime_control.py` like other toggles.

### 4.3 Fallback chain

`ExecutionEngine` resolves the effective review model in this order:

1. Specialist model from `code_review_model` state/env, **only if**
   `code_review_specialist_enabled == "on"` and the model is installed.
2. Existing stock Gemma 4 12B: `gemma4:12b-it-qat`.
3. Previously working fallback: the normally configured local model
   (`LocalAnswerConfig.from_env().model`).
4. Error if none can run.

Every fallback is logged with the reason.

### 4.4 Model availability check

Before running inference in Code Review mode, probe Ollama for installed models
via the existing `/api/tags` endpoint or `ollama list`. If the specialist model
is not present, log a clear message and fall back. Do not auto-download during a
normal user request.

If the user explicitly installs the model, the Ollama command is:

```bash
ollama run hf.co/yuxinlu1/gemma-4-12B-agentic-fable5-composer2.5-v2-3.5x-tau2-GGUF:Q4_K_M
```

### 4.5 Activation / Engineering mode

The existing `self_analysis_mode` toggle becomes the **Engineering mode**
activation. When enabled, the HMI/state writer also sets generation parameters
suitable for code review (see 4.7). The specialist model selection is scoped to
this mode only.

No new parallel subsystem is created. The same `ExecutionEngine` dispatch and
`SelfAnalysisEngine` analysis path are reused.

### 4.6 Staged review prompt (hybrid C)

Replace the current single review instruction with a structured two-call prompt.

#### Call 1 — Code map, broad audit, and coverage ledger

Prompt sections:

1. System instruction enforcing coverage-before-depth.
2. Static analysis context (metrics, hotspots, TODOs, ruff output, source).
3. Stage A: code map (modules, classes, functions, entry points, data flow,
   state ownership, dependencies, security boundaries, routing/fallback paths,
   error-handling paths). No fixes yet.
4. Stage B: broad audit checklist (functional correctness, logic errors, edge
   cases, error handling, state consistency, concurrency, routing/classifier
   behaviour, security, resource management, performance, dead/duplicated logic,
   maintainability, logging, test gaps).
5. Stage C: coverage ledger listing each major component with status
   (complete/partial/not reviewed), reason, candidate concerns, and components
   with no material issue.
6. Output schema: scope received, architecture summary, coverage ledger,
   confirmed findings, probable findings, rejected concerns, severity/confidence,
   recommended corrections, required tests, components not adequately reviewed.

Confidence labels: `confirmed`, `high confidence`, `moderate confidence`,
`low confidence`. No fabricated numerical confidence.

#### Call 2 — Deep investigation and fix planning (conditional)

If Call 1 produced at least one candidate finding with moderate confidence or
higher, run a second call that receives:

- The original code context.
- The coverage ledger.
- The candidate findings.

It performs Stage D (trace each finding, confirm or reject, consider
interactions) and Stage E (rank by severity/likelihood, smallest safe correction,
regression risks, targeted tests). This call is skipped if Call 1 reports no
material issues.

Both calls are read-only. The model is explicitly instructed not to edit files,
apply patches, run commands, install dependencies, or commit changes unless the
user later requests implementation.

### 4.7 Generation parameters

Add config fields for code-review-specific parameters, overridable via env:

| Field | Default | Env var |
|-------|---------|---------|
| `code_review_temperature` | `1.0` | `LUCY_CODE_REVIEW_TEMPERATURE` |
| `code_review_top_p` | `0.95` | `LUCY_CODE_REVIEW_TOP_P` |
| `code_review_top_k` | `64` | `LUCY_CODE_REVIEW_TOP_K` |
| `code_review_context_target` | `16384` | `LUCY_CODE_REVIEW_CONTEXT_TARGET` |
| `code_review_max_tokens` | `4096` | `LUCY_CODE_REVIEW_MAX_TOKENS` |
| `code_review_context_chars` | `200000` | `LUCY_CODE_REVIEW_CONTEXT_CHARS` |

These are used only when `route_mode == "SELF_REVIEW"`. Normal chat parameters
are unchanged.

### 4.8 GPU and runtime behaviour

- Do not load Whisper.
- Do not load Kokoro for output in this mode.
- Do not keep a second LLM loaded; unload the previous Ollama model before
  loading the code-review model if necessary.
- Prevent parallel model execution.
- Prefer full GPU offload when it fits.
- Detect and log CPU offloading / system-memory spill as performance warnings.
- Start with a 16K context target; allow 24K via config for later testing.

### 4.9 Voice suppression

In `ui-v10/app/main_window.py`, skip `_speak_response_text` when the response
route is `SELF_REVIEW`. This is the only HMI change.

### 4.10 Read-only enforcement

By default the mode may only:

- Read supplied code.
- Analyse code.
- Search within the supplied project.
- Produce findings.
- Suggest patches in text.
- Propose tests.

It must not edit files, apply patches, run destructive commands, change
configuration, install dependencies, delete files, commit, or push. Any
write-enabled mode must be a separate explicit action with existing permission
controls preserved.

### 4.11 Context construction and truncation

Preserve clear boundaries in the prompt: file/component boundaries, line
numbers, code vs explanatory text, current vs proposed code, production vs test
code, config vs runtime code.

Detect truncation before inference. If the static-analysis source block is
truncated, record it and include a warning in the report. Do not silently
truncate.

### 4.12 Logging and observability

Log per review request:

- Requested review model
- Actual model used
- Whether fallback occurred and reason
- Context length / input size
- Whether input was truncated
- GPU offload status (from `nvidia-smi` / Ollama response if available)
- CPU offloading or memory spill warnings
- Prompt-processing time and generation time
- Review stages completed
- Coverage count
- Model/backend errors

Do not log private source-code contents unless existing Local Lucy logging
policy permits it.

## 5. Files to change

- `tools/router_py/local_answer.py` — add `_MODEL_IDENTITIES` entry, add
  code-review config fields, use code-review params for `SELF_REVIEW`.
- `tools/router_py/self_analysis.py` — staged prompt builder, deep-dive
  orchestration, truncation detection.
- `tools/router_py/execution_engine.py` — model resolver, availability probe,
  fallback chain, pass resolved model to `SelfAnalysisEngine`.
- `tools/runtime_control.py` — add `code_review_model` and
  `code_review_specialist_enabled` to state/env.
- `ui-v10/app/panels/control_panel.py` — expose Engineering mode toggle and
  specialist enable (possibly behind existing self-analysis checkbox).
- `ui-v10/app/main_window.py` — suppress Kokoro TTS for `SELF_REVIEW`.
- `tools/router_py/test_self_analysis.py` — add tests for fallback, model
  selection, staged prompt, read-only guard, truncation.
- `ui-v10/tests/test_self_analysis_mode_offscreen.py` — add TTS suppression
  test.

## 6. Tests

### Routing and selection

- Code Review mode selects the specialist model when available and enabled.
- Normal conversation does not select it.
- Voice remains available in normal mode.
- Voice is bypassed only in Code Review mode.
- Existing model selection unchanged elsewhere.

### Fallback

- Specialist available.
- Specialist missing.
- Specialist fails to load.
- Ollama unavailable.
- Fallback model unavailable.
- Clear final error when no model can run.

### Review behaviour

Use code samples containing:

- Several unrelated defects.
- One conspicuous minor defect followed by a subtle critical defect.
- Correct code with no genuine defects.
- A false-positive trap where validation elsewhere prevents the apparent issue.
- Cross-function state inconsistency.
- Missing error handling.
- Dead code.
- A security-sensitive command path.
- More than 2,000 lines of representative Local Lucy-style code.

Verify:

- Broad review before deep analysis.
- Coverage ledger produced.
- No invented defects in every category.
- Confirmed findings separated from suspicions.
- No edits proposed before discovery completes.
- No changes executed in read-only mode.

### Regression

Run existing router, model-selection, Code Review mode, voice-path, normal
conversational, security, and full regression suites.

## 7. Comparative validation (Phase 12)

Run identical representative reviews with:

1. Existing stock `gemma4:12b-it-qat`.
2. New specialist model.

Compare valid findings, false positives, missed defects, breadth, depth,
fixation on first issue, recommended tests, latency, VRAM, context capacity, and
stability. Document results honestly. Do not promote the specialist model solely
on verbosity.

## 8. Rollback

Disable the feature entirely by setting:

```bash
LUCY_CODE_REVIEW_SPECIALIST_ENABLED=0
```

or via runtime control:

```bash
python3 tools/runtime_control.py set-code-review-specialist-enabled --value off
```

This restores the previous Code Review model (the user-selected local model) and
the previous single-stage prompt behaviour. No source-code reversal is required.

## 9. Risks and open questions

- The specialist model tag is very long; Ollama must accept it exactly.
- A 12 GB VRAM target may require quantization or partial CPU offload for 12B +
large context; needs measurement.
- Two sequential Ollama calls increase wall-clock latency; may need a user-facing
progress indicator.
- Staged prompts rely on model compliance; may need iteration.
