# Self-Analysis Large-File and Large-Response Support

**Date:** 2026-07-15
**Scope:** `tools/router_py/self_analysis.py`, `tools/router_py/local_answer.py`, tests
**Status:** Approved

## Problem

Self-analysis mode currently produces short, summary-level reviews because:

1. The LLM prompt contains only static metrics (line counts, hotspots, TODOs, ruff diagnostics) — the actual source code is not shown to the model.
2. Self-analysis calls `LocalAnswer.generate_answer(..., route_mode="LOCAL")`, which is budgeted for short chat answers (`local_max_tokens` defaults to 256).
3. There is no explicit size validation when reading a target file.

As a result, users cannot ask Local Lucy to review large files or receive long, detailed code reviews.

## Goals

- Feed the file's source code into the self-analysis prompt.
- Allow very long responses (thousands of tokens) when the user explicitly asks for a code review.
- Prevent abuse or accidental reads of huge/non-file paths.
- Keep the feature safe with model-appropriate context limits.

## Non-goals

- Automatic chunking or multi-pass analysis of files larger than the model context.
- Changing the default `num_ctx` in Ollama Modelfiles.
- Generalizing the feature beyond Python source files.

## Design

### 1. Include source code in the self-analysis prompt

In `tools/router_py/self_analysis.py`:

- After building the existing metrics context, append the raw file source under a `Source code:` header.
- If the source is too long for the configured `self_review_context_chars` budget, truncate from the end and append a notice: `"[truncated at N characters; consider reviewing a smaller module]"`.
- The prompt ordering is:
  1. Task instruction
  2. Metrics / hotspots / TODOs / diagnostics
  3. Source code (possibly truncated)

### 2. Dedicated `SELF_REVIEW` route budget

In `tools/router_py/local_answer.py`:

- Add `self_review_max_tokens` and `self_review_context_chars` to `LocalAnswerConfig`.
- Read them from environment variables `LUCY_SELF_REVIEW_MAX_TOKENS` and `LUCY_SELF_REVIEW_CONTEXT_CHARS` with defaults of `4096` and `200000` respectively.
- Add a `route == "SELF_REVIEW"` branch in `_set_generation_profile()` that returns a `("self_review", self_review_max_tokens, "- Provide a thorough, detailed code review with concrete, minimal improvements.")` profile.
- Disable the local repeat cache when `route_mode == "SELF_REVIEW"` so repeated analysis of a changed file does not return stale output.

### 3. Safety checks for large files

In `tools/router_py/self_analysis.py`:

- Add `candidate.is_file()` before `read_text()` so directories named `*.py` do not raise `IsADirectoryError`.
- Add a 5 MB size cap before reading. Files above this limit raise a clear `ValueError` with the path and size.

### 4. Caller update

In `tools/router_py/self_analysis.py`:

- Change `await answer.generate_answer(query=prompt, route_mode="LOCAL")` to `route_mode="SELF_REVIEW")`.

### 5. Context limits and model selection

- The effective context limit is still the active Ollama model's `num_ctx`.
- `local-lucy-llama31` (llama3.1:8b) uses `num_ctx 8192` in its Modelfile, so files up to a few thousand lines typically fit.
- `gemma4:12b-it-qat` supports 128k context and is the recommended model for very large files.
- The implementation will not silently increase `num_ctx`; instead it relies on the user selecting a model with sufficient context.

## Files to modify

- `tools/router_py/self_analysis.py`
- `tools/router_py/local_answer.py`
- `tools/router_py/test_self_analysis.py`

## Testing

- `test_self_analysis_source_code_in_prompt`: verify source code appears in the prompt sent to `LocalAnswer`.
- `test_self_analysis_uses_self_review_route`: verify `generate_answer` is called with `route_mode="SELF_REVIEW"`.
- `test_self_analysis_large_file_truncation`: verify files longer than `self_review_context_chars` are truncated with a notice.
- `test_self_analysis_rejects_huge_file`: verify files above 5 MB raise `ValueError`.
- `test_self_analysis_rejects_directory`: verify a directory named `*.py` raises `ValueError`.
- Keep existing self-analysis tests passing.

## Risks and mitigations

| Risk | Mitigation |
|------|------------|
| Very large prompts exceed model context | Truncate source to `self_review_context_chars`; user can select Gemma 4 for huge files. |
| Repeat analysis returns cached output | Disable cache for `SELF_REVIEW` route. |
| Reading huge files hangs or OOMs | 5 MB read cap and `is_file()` check. |
| Existing LOCAL chat behavior affected | Changes are isolated to the new `SELF_REVIEW` route; `LOCAL` stays unchanged. |
