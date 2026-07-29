# V11 Pipeline Split + Conservative Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `request_pipeline.py` and `plan_to_pipeline_cli.py` into responsibility-focused packages; add conservative source attribution and escalation capabilities behind feature flags.

**Architecture:** Keep the existing `process()` and `main()` entry points as thin facades. Move internal orchestration into `router_py/pipeline/` and `router_py/planner/` packages. Add a new `router_py/escalation/` package that can suggest (not silently perform) web fetches for general knowledge, while enforcing trusted-source-only policy for critical categories. All new behaviour is gated by `config/capability_flags.yaml` and defaults to off.

**Tech Stack:** Python 3.11+, existing v11 pytest suite, dataclasses, standard library `urllib`/`http.client` for web fetch (no new external dependencies unless OpenAI integration is explicitly requested later).

## Global Constraints

- v11 working tree on `main` at `/home/mike/lucy-v11`.
- v10 must remain untouched and available as fallback.
- Fast suite (`scripts/run-fast-tests.sh`) must pass after every task.
- Existing public entry points (`request_pipeline.process()`, `plan_to_pipeline_cli.py` CLI) must keep identical signatures and default behaviour.
- New behaviour is behind feature flags; default-off means v11 behaves exactly as before.
- No production memory or state modifications from tests.
- Medical, financial, legal, safety, and personal identity queries are classified as critical and restricted to trusted sources.
- All web sources are labelled `untrusted` unless explicitly allowlisted.

---

## File Structure

### New packages

```text
tools/router_py/pipeline/
    __init__.py          # exports process(), public types
    config.py            # capability flag loader
    classify.py          # intent classification wrapper
    route.py             # route selection + policy normalization
    resolve_provider.py  # provider resolution
    build_context.py     # PipelineContext assembly
    execute.py           # ExecutionEngine invocation
    outcome.py           # ExecutionResult → RouterOutcome conversion
    attribution.py       # source attribution and trust labels

tools/router_py/planner/
    __init__.py          # exports main() compatibility
    config.py            # planner feature flags
    plan_builder.py      # plan construction helpers
    policy_resolver.py   # contextual/local/pet-food/medical policies
    news_rewriter.py     # news query rewriting
    contract_builder.py  # execution contract assembly
    cli.py               # argparse + JSON output wrapper

tools/router_py/escalation/
    __init__.py
    config.py
    suggestion.py        # decides whether to suggest escalation
    fetcher.py           # general-knowledge web fetch (DuckDuckGo, allowlist)
    critical_guard.py    # blocks untrusted sources for critical categories

config/
    capability_flags.yaml  # new file
```

### Retained as thin facades

- `tools/router_py/request_pipeline.py`
- `tools/router_py/plan_to_pipeline_cli.py`

### Modified types

- `tools/router_py/request_types.py` — extend `RouterOutcome` with `source_attribution` field.

---

## Task 1: Add capability flags configuration

**Files:**
- Create: `config/capability_flags.yaml`
- Create: `tools/router_py/pipeline/config.py`
- Test: `tools/router_py/test_pipeline_config.py`

**Interfaces:**
- Produces: `load_capability_flags() -> CapabilityFlags` dataclass.
- Produces: `CapabilityFlags` with fields:
  - `source_attribution: bool = False`
  - `suggest_web_escalation: bool = False`
  - `auto_web_general_knowledge: bool = False`
  - `trusted_sources_only_critical: bool = True`

- [ ] **Step 1: Write the failing test**

```python
def test_load_capability_flags_defaults():
    from router_py.pipeline.config import load_capability_flags
    flags = load_capability_flags()
    assert flags.source_attribution is False
    assert flags.suggest_web_escalation is False
    assert flags.auto_web_general_knowledge is False
    assert flags.trusted_sources_only_critical is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/mike/lucy-v11 && python -m pytest tools/router_py/test_pipeline_config.py::test_load_capability_flags_defaults -v`
Expected: FAIL — `ModuleNotFoundError` or function not defined.

- [ ] **Step 3: Write minimal implementation**

Create `config/capability_flags.yaml`:

```yaml
source_attribution: false
suggest_web_escalation: false
auto_web_general_knowledge: false
trusted_sources_only_critical: true
```

Create `tools/router_py/pipeline/config.py`:

```python
from __future__ import annotations
import dataclasses
import os
from pathlib import Path
from typing import Any

import yaml


@dataclasses.dataclass(frozen=True)
class CapabilityFlags:
    source_attribution: bool = False
    suggest_web_escalation: bool = False
    auto_web_general_knowledge: bool = False
    trusted_sources_only_critical: bool = True


def load_capability_flags(path: str | Path | None = None) -> CapabilityFlags:
    if path is None:
        root = Path(__file__).resolve().parent.parent.parent.parent
        path = root / "config" / "capability_flags.yaml"
    path = Path(path)
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.environ.get(name)
        if raw is None:
            return default
        return raw.strip().lower() in ("1", "true", "on", "yes")
    return CapabilityFlags(
        source_attribution=_env_bool("LUCY_SOURCE_ATTRIBUTION", data.get("source_attribution", False)),
        suggest_web_escalation=_env_bool("LUCY_SUGGEST_WEB_ESCALATION", data.get("suggest_web_escalation", False)),
        auto_web_general_knowledge=_env_bool("LUCY_AUTO_WEB_GENERAL_KNOWLEDGE", data.get("auto_web_general_knowledge", False)),
        trusted_sources_only_critical=_env_bool("LUCY_TRUSTED_SOURCES_ONLY_CRITICAL", data.get("trusted_sources_only_critical", True)),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tools/router_py/test_pipeline_config.py::test_load_capability_flags_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/capability_flags.yaml tools/router_py/pipeline/config.py tools/router_py/test_pipeline_config.py
git commit -m "feat(pipeline): add capability_flags config with conservative defaults"
```

---

## Task 2: Extend RouterOutcome with source attribution

**Files:**
- Modify: `tools/router_py/request_types.py`
- Test: `tools/router_py/test_request_types.py` (or add to existing)

**Interfaces:**
- Consumes: existing `RouterOutcome` dataclass.
- Produces: `RouterOutcome` with new optional fields:
  - `source_attribution: SourceAttribution | None = None`
  - `trust_label: str = ""`
  - `escalation_suggestion: str = ""`

`SourceAttribution` dataclass:
- `basis: str` — e.g. "local", "augmented", "evidence", "web_untrusted", "none"
- `sources: list[str]` — domain or source identifiers
- `confidence: str` — "high", "medium", "low", "unknown"

- [ ] **Step 1: Write the failing test**

```python
def test_router_outcome_source_attribution():
    from router_py.request_types import RouterOutcome, SourceAttribution
    outcome = RouterOutcome(
        status="completed",
        outcome_code="ok",
        route="LOCAL",
        provider="local",
        provider_usage_class="local",
        intent_family="local_knowledge",
        confidence=0.9,
        response_text="hello",
        source_attribution=SourceAttribution(basis="local", sources=[], confidence="high"),
    )
    assert outcome.source_attribution.basis == "local"
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `SourceAttribution` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `tools/router_py/request_types.py`:

```python
@dataclasses.dataclass
class SourceAttribution:
    basis: str = "none"  # local, augmented, evidence, web_untrusted, none
    sources: list[str] = dataclasses.field(default_factory=list)
    confidence: str = "unknown"  # high, medium, low, unknown
```

And extend `RouterOutcome`:

```python
source_attribution: SourceAttribution | None = None
trust_label: str = ""  # e.g. "verified", "untrusted", "local_only"
escalation_suggestion: str = ""  # e.g. "Enable web search for more current sources."
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/request_types.py tools/router_py/test_request_types.py
git commit -m "feat(request_types): add SourceAttribution to RouterOutcome"
```

---

## Task 3: Split request_pipeline.py — classify and route modules

**Files:**
- Create: `tools/router_py/pipeline/classify.py`
- Create: `tools/router_py/pipeline/route.py`
- Modify: `tools/router_py/request_pipeline.py` — remove `_self_analysis_*`, `_gemma4_*`, `_forced_route_*`, `_looks_like_*` helpers; delegate classification/routing
- Test: `tools/router_py/test_request_pipeline_characterization.py` (or extend existing)

**Interfaces:**
- Produces: `classify_question(question, surface, model, route_prefix, context) -> ClassificationResult | RouterOutcome`
- Produces: `select_route_for_question(classification, question, policy, context) -> RoutingDecision`

These functions must preserve current behaviour including env bypass, Gemma 4 smart routing, and request constraints.

- [ ] **Step 1: Write characterization tests capturing current process() outputs for representative inputs**

Inputs to cover:
- Simple local question
- News query
- Evidence query
- Medical query
- Request with `route_prefix="news"`
- Request with `augmented_direct_once=True`

Record route, provider, outcome_code, and status. Run against current `process()` before changes.

- [ ] **Step 2: Move classification helpers and logic into `classify.py`**

Include: `_self_analysis_state_path`, `_self_analysis_mode_enabled`, `_self_analysis_file_reference`, `_is_gemma4_smart_routing_enabled`, `_gemma4_bypass_decision`, `_forced_route_from_env`, `_bypass_classification_decision`, `_looks_like_news`, `_looks_like_evidence`, and the classification block from `process()`.

- [ ] **Step 3: Move routing block into `route.py`**

Include: route selection, request-scoped capability constraints, evidence-disabled operator gate, and route prefix / augmented_direct_once overrides.

- [ ] **Step 4: Update `request_pipeline.py` to import and call the new modules**

Keep `process()` signature identical. Move the classification/routing steps to helper calls.

- [ ] **Step 5: Run characterization tests and fast suite**

Run:
```bash
python -m pytest tools/router_py/test_request_pipeline_characterization.py -v
bash scripts/run-fast-tests.sh
```

Expected: all pass, behaviour unchanged.

- [ ] **Step 6: Commit**

```bash
git add tools/router_py/pipeline/classify.py tools/router_py/pipeline/route.py tools/router_py/request_pipeline.py tools/router_py/test_request_pipeline_characterization.py
git commit -m "refactor(pipeline): extract classify and route modules from request_pipeline"
```

---

## Task 4: Split request_pipeline.py — provider, context, execute, outcome modules

**Files:**
- Create: `tools/router_py/pipeline/resolve_provider.py`
- Create: `tools/router_py/pipeline/build_context.py`
- Create: `tools/router_py/pipeline/execute.py`
- Create: `tools/router_py/pipeline/outcome.py`
- Modify: `tools/router_py/request_pipeline.py` — reduce to thin facade
- Test: extend characterization tests

**Interfaces:**
- `resolve_provider(decision, classification, context) -> RoutingDecision`
- `build_pipeline_context(question, surface, context, classification) -> PipelineContext`
- `execute_request(classification, decision, pipeline_ctx, model, timeout) -> ExecutionResult`
- `build_outcome(result, classification, decision, start_time, profile) -> RouterOutcome`

- [ ] **Step 1: Move provider resolution into `resolve_provider.py`**

- [ ] **Step 2: Move PipelineContext assembly into `build_context.py`**

- [ ] **Step 3: Move ExecutionEngine invocation into `execute.py`**

- [ ] **Step 4: Move ExecutionResult → RouterOutcome conversion into `outcome.py`**

- [ ] **Step 5: Reduce `request_pipeline.py` to a thin facade**

```python
def process(question, *, policy="fallback_only", timeout=130, surface="cli", ...):
    from .pipeline import classify, route, resolve_provider, build_context, execute, outcome
    classification_or_outcome = classify.classify_question(...)
    if isinstance(classification_or_outcome, RouterOutcome):
        return classification_or_outcome, None, None
    decision_or_outcome = route.select_route_for_question(...)
    if isinstance(decision_or_outcome, RouterOutcome):
        return decision_or_outcome, classification_or_outcome, None
    decision = resolve_provider.resolve_provider(...)
    pipeline_ctx = build_context.build_pipeline_context(...)
    result = execute.execute_request(...)
    return outcome.build_outcome(...), classification_or_outcome, decision
```

- [ ] **Step 6: Run characterization tests and fast suite**

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tools/router_py/pipeline/*.py tools/router_py/request_pipeline.py
git commit -m "refactor(pipeline): split provider, context, execute, outcome modules"
```

---

## Task 5: Split plan_to_pipeline_cli.py — plan builder and policy resolver

**Files:**
- Create: `tools/router_py/planner/plan_builder.py`
- Create: `tools/router_py/planner/policy_resolver.py`
- Create: `tools/router_py/planner/news_rewriter.py`
- Modify: `tools/router_py/plan_to_pipeline_cli.py`
- Test: `tools/router_py/test_plan_to_pipeline_characterization.py`

**Interfaces:**
- `build_effective_plan(plan, route_prefix) -> dict[str, object]`
- `apply_contextual_policies(plan, effective_plan, original_question, question_for_execution, root_dir) -> tuple[plan, effective_plan, local_response_text, ...]`
- `rewrite_news_query(question: str) -> str`

- [ ] **Step 1: Capture current CLI output for representative plans**

Build a set of input plan JSONs and expected output keys:
- Local knowledge plan
- News plan with route_prefix="news"
- Medical plan
- Pet food plan

- [ ] **Step 2: Move `_legacy_plan`, `_patch_classification_for_effective_plan`, `_patch_plan_with_classification`, route-prefix patch logic into `plan_builder.py`**

- [ ] **Step 3: Move contextual followup, local context response, pet food policy, local response ID matching into `policy_resolver.py`**

- [ ] **Step 4: Move `_rewrite_news_query` into `news_rewriter.py`**

- [ ] **Step 5: Update `plan_to_pipeline_cli.py` to call new modules**

Keep `main()` behaviour identical.

- [ ] **Step 6: Run characterization tests and fast suite**

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add tools/router_py/planner/*.py tools/router_py/plan_to_pipeline_cli.py tools/router_py/test_plan_to_pipeline_characterization.py
git commit -m "refactor(planner): split plan_builder, policy_resolver, news_rewriter from CLI"
```

---

## Task 6: Split plan_to_pipeline_cli.py — contract builder and CLI wrapper

**Files:**
- Create: `tools/router_py/planner/contract_builder.py`
- Create: `tools/router_py/planner/cli.py`
- Modify: `tools/router_py/plan_to_pipeline_cli.py` — reduce to thin facade

**Interfaces:**
- `build_contract(plan, effective_plan, route_decision, route_manifest, question, resolved_question, local_response_text, route_control_mode, route_prefix, surface) -> dict[str, object]`
- `run_cli(argv=None) -> int` — argparse + JSON output wrapper

- [ ] **Step 1: Move `build_execution_contract` call and output assembly into `contract_builder.py`**

- [ ] **Step 2: Move argparse and JSON printing into `cli.py`**

- [ ] **Step 3: Reduce `plan_to_pipeline_cli.py` to a thin facade**

```python
from router_py.planner.cli import run_cli
if __name__ == "__main__":
    sys.exit(run_cli())
```

- [ ] **Step 4: Run characterization tests and fast suite**

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/planner/contract_builder.py tools/router_py/planner/cli.py tools/router_py/plan_to_pipeline_cli.py
git commit -m "refactor(planner): split contract_builder and CLI wrapper"
```

---

## Task 7: Add source attribution to pipeline outcome

**Files:**
- Modify: `tools/router_py/pipeline/outcome.py`
- Create: `tools/router_py/pipeline/attribution.py`
- Test: `tools/router_py/test_source_attribution.py`

**Interfaces:**
- `build_source_attribution(decision, result) -> SourceAttribution`
- `build_trust_label(attribution) -> str`

Rules:
- route LOCAL + no evidence → basis "local", confidence "medium"
- route AUGMENTED → basis "augmented", confidence "medium"
- route EVIDENCE with trusted domains → basis "evidence", confidence "high"
- route NEWS → basis "evidence", confidence "medium"
- no source metadata → basis "none", confidence "unknown"

Only active when `source_attribution` flag is enabled; otherwise return None.

- [ ] **Step 1: Write failing tests for attribution rules**

- [ ] **Step 2: Implement `attribution.py`**

- [ ] **Step 3: Wire into `outcome.py`**

- [ ] **Step 4: Run tests and fast suite**

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/pipeline/attribution.py tools/router_py/pipeline/outcome.py tools/router_py/test_source_attribution.py
git commit -m "feat(pipeline): add source attribution behind capability flag"
```

---

## Task 8: Add escalation suggestion module

**Files:**
- Create: `tools/router_py/escalation/suggestion.py`
- Create: `tools/router_py/escalation/config.py`
- Test: `tools/router_py/test_escalation_suggestion.py`

**Interfaces:**
- `suggest_escalation(classification, decision, attribution, flags) -> str`

Rules (conservative):
- If route is LOCAL and basis is "none" or confidence is "low" → suggest web search for general knowledge.
- If route is LOCAL but question signals current info need → suggest web search.
- Never suggest escalation for critical categories (medical, financial, legal, safety, personal identity).
- Only active when `suggest_web_escalation` flag is enabled.

- [ ] **Step 1: Write failing tests**

- [ ] **Step 2: Implement `suggestion.py`**

- [ ] **Step 3: Wire into `outcome.py` so `escalation_suggestion` field is populated**

- [ ] **Step 4: Run tests and fast suite**

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/escalation/suggestion.py tools/router_py/escalation/config.py tools/router_py/test_escalation_suggestion.py
git commit -m "feat(escalation): add conservative escalation suggestions behind flag"
```

---

## Task 9: Add general-knowledge web fetcher

**Files:**
- Create: `tools/router_py/escalation/fetcher.py`
- Create: `tools/router_py/escalation/critical_guard.py`
- Test: `tools/router_py/test_web_fetcher.py`

**Interfaces:**
- `is_critical_category(classification) -> bool` — returns True for medical, financial, legal, safety, personal identity.
- `fetch_general_knowledge(query: str, allowed_domains: list[str] | None = None) -> FetchResult`
- `FetchResult` dataclass with `url: str`, `title: str`, `snippet: str`, `source_type: str`.

Implementation:
- Use DuckDuckGo HTML results parsing (no API key).
- Respect `auto_web_general_knowledge` flag.
- Blocked for critical categories regardless of flag.
- Only fetch allowlisted domains when configured; otherwise use DuckDuckGo top results.
- All results marked `source_type: "web_untrusted"`.

- [ ] **Step 1: Write failing tests with mocked HTTP responses**

- [ ] **Step 2: Implement `critical_guard.py`**

- [ ] **Step 3: Implement `fetcher.py` with DuckDuckGo parser**

- [ ] **Step 4: Wire fetcher into pipeline only when flag enabled and not critical**

Add a new optional post-execution step in `request_pipeline.py` facade:

```python
if flags.auto_web_general_knowledge and attribution.basis in ("none", "low") and not critical_guard.is_critical_category(classification):
    fetched = fetcher.fetch_general_knowledge(question)
    outcome.escalation_suggestion = f"Web sources found (untrusted): {fetched.title} — {fetched.url}"
```

For this conservative stage, do **not** replace the answer with fetched content. Only attach attribution/suggestion.

- [ ] **Step 5: Run tests and fast suite**

- [ ] **Step 6: Commit**

```bash
git add tools/router_py/escalation/fetcher.py tools/router_py/escalation/critical_guard.py tools/router_py/test_web_fetcher.py
git commit -m "feat(escalation): add general-knowledge web fetcher behind flag"
```

---

## Task 10: Enforce trusted-sources-only for critical info

**Files:**
- Modify: `tools/router_py/pipeline/route.py`
- Modify: `tools/router_py/escalation/critical_guard.py`
- Test: `tools/router_py/test_critical_source_guard.py`

**Interfaces:**
- `apply_critical_source_policy(decision, classification, context=None, *, start_time=None) -> RoutingDecision | RouterOutcome`

Rules:
- If `trusted_sources_only_critical` is True and category is critical:
  - If route is NEWS → block untrusted web, require evidence/trusted domains.
  - If route is AUGMENTED → restrict to configured trusted sources.
  - If route is EVIDENCE → keep, but ensure `allow_domains_file` points to trusted list.
- If no trusted source available → return RouterOutcome with `operator_blocked` and clear explanation.

- [ ] **Step 1: Write failing tests for medical/financial/legal queries**

- [ ] **Step 2: Implement policy application in `route.py`**

- [ ] **Step 3: Run tests and fast suite**

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/pipeline/route.py tools/router_py/escalation/critical_guard.py tools/router_py/test_critical_source_guard.py
git commit -m "feat(escalation): enforce trusted-sources-only for critical categories"
```

---

## Task 11: Update fast suite and add integration tests

**Files:**
- Modify existing tests as needed
- Create: `tools/router_py/test_pipeline_integration_flags.py`

**Tests to add:**
- With all flags off, `process()` output is unchanged from baseline.
- With `source_attribution=1`, outcome includes source attribution.
- With `suggest_web_escalation=1`, thin local question receives escalation suggestion.
- With `auto_web_general_knowledge=1`, non-critical question receives web fetch suggestion.
- With `auto_web_general_knowledge=1`, critical question does not fetch web.
- With `trusted_sources_only_critical=1`, critical query blocked from untrusted web.

- [ ] **Step 1: Add integration tests**

- [ ] **Step 2: Run full fast suite**

Run: `bash scripts/run-fast-tests.sh`
Expected: pass.

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/test_pipeline_integration_flags.py
git commit -m "test(pipeline): add integration tests for capability flags"
```

---

## Task 12: Update Architecture.md and create session handoff

**Files:**
- Modify: `Architecture.md`
- Create: `dev_notes/SESSION_HANDOFF_*.md`
- Create: Desktop copy of handoff

**Content:**
- Document new `router_py/pipeline/` and `router_py/planner/` packages.
- Document `router_py/escalation/` package and feature flags.
- Document critical-source policy.
- List files changed and public interfaces preserved.
- Include rollback instructions: disable flags in `config/capability_flags.yaml` or set env vars to `0`.

- [ ] **Step 1: Update Architecture.md**

- [ ] **Step 2: Write session handoff**

- [ ] **Step 3: Copy handoff to Desktop**

- [ ] **Step 4: Commit**

```bash
git add Architecture.md dev_notes/SESSION_HANDOFF_*.md
git commit -m "docs: update architecture and session handoff for pipeline split and escalation"
```

---

## Self-Review

- **Spec coverage:** The conservative design (splits + source attribution + escalation suggestion + trusted-source guard) is covered.
- **Placeholder scan:** No TBDs or vague steps; every task has concrete deliverables.
- **Type consistency:** `CapabilityFlags`, `SourceAttribution`, and `RouterOutcome` fields are consistent across tasks.
- **Gaps:** Live model testing and HMI rendering of trust labels are out of scope for this stage; they require the HMI layer to consume the new `RouterOutcome` fields.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-29-v11-pipeline-split-escalation-plan.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

**Which approach?**
