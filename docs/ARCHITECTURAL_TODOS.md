# Local Lucy — Architectural TODOs

> Outstanding architecture, design-debt, and follow-up items identified during implementation and code review. Items are grouped by area and tagged with priority and origin.

---

## Self-Analysis / SELF_REVIEW

| # | Item | Priority | Origin | Notes |
|---|------|----------|--------|-------|
| 1 | Report true file size in oversized-file error | Minor | Whole-branch review | `tools/router_py/self_analysis.py` currently reports `_MAX_FILE_SIZE_BYTES + 1` because it reads only that many bytes. Either stat the file after the safe read or rephrase the message. |
| 2 | Add dedicated SELF_REVIEW bypass tests for policy, tube-DB, and personal-fact short-circuits | Minor | Whole-branch review | Only the 807 short-circuit bypass is explicitly tested. Add lightweight tests for the remaining three guards to prevent future regressions. |
| 3 | Warn when SELF_REVIEW prompt may exceed model context | Minor | Whole-branch review | Default `self_review_context_chars=100000` can exceed `local-lucy-llama31`'s 8192 context. Emit a `logger.warning` when the estimated prompt tokens approach the active model's `num_ctx`. |
| 4 | Document thinking-model budget behavior | Minor | Whole-branch review | Thinking models get no extra reasoning headroom beyond `self_review_max_tokens` for `SELF_REVIEW`. Add a note to the design spec or user docs. |
| 5 | Cache `LocalAnswerConfig.from_env()` in execution engine | Minor | Whole-branch review | `execution_engine.py` creates a fresh `LocalAnswerConfig.from_env()` on every self-analysis call. Cache it to avoid redundant env/state-file reads. |
| 6 | Add symlink-outside-project-root regression test | Minor | Whole-branch review | `_resolve_file` blocks traversal via `resolve()` + `relative_to()`, but no test exercises a symlink pointing outside `project_root`. |
| 7 | Cross-file / call-graph analysis | Future | Design spec Option B | Extend self-analysis to build a code-review graph for architectural hotspot queries across modules. |

---

## General Routing / Local Answer

| # | Item | Priority | Origin | Notes |
|---|------|----------|--------|-------|
| 8 | Centralize short-circuit skip logic | Minor | Whole-branch review | `is_self_review` is checked in multiple places. Consider a single helper such as `_should_apply_qa_shortcuts(route_mode)` to make future routes less error-prone. |
| 9 | Add `pytest-timeout` to dev dependencies | Minor | Test environment | Subagent test runs could not use `--timeout=60` because `pytest-timeout` is not installed. Add it to `pyproject.toml` or `requirements-dev.txt`. |

---

## Documentation / Ops

| # | Item | Priority | Origin | Notes |
|---|------|----------|--------|-------|
| 10 | Document `LUCY_SELF_REVIEW_MAX_TOKENS` and `LUCY_SELF_REVIEW_CONTEXT_CHARS` | Minor | Whole-branch review | Add the new env vars to runtime-config docs so operators know how to tune large-file review behavior. |

---

*Last updated: 2026-07-16T17:32:55+0300*
