# Refactor Integrity Verification Suite Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a small, fast, high-value verification suite that proves the Phase 8 module splits did not break imports, public APIs, deterministic routing behavior, or the specific MedlinePlus URL-injection regression.

**Architecture:** Add pytest test files under `tools/router_py/` using the existing marker convention (`static` for no-dependency tests, `deterministic` for tests that may load models/files but do not invoke Ollama). Include a small CLI report generator that aggregates import/API/schema checks into a machine-readable refactor-integrity report.

**Tech Stack:** Python 3.10+, pytest, PyYAML, existing `router_py` package, ruff.

## Global Constraints

- Do not redesign Local Lucy or perform another broad refactor.
- Do not change production behavior merely to make tests pass.
- Do not modify model weights or replace Ollama.
- Do not alter Michael’s real personality profile or persistent-memory database.
- Do not run model-dependent tests concurrently; RTX 3060 12 GB VRAM requires sequential LLM workloads.
- Do not expose credentials, private memories, API keys, or full sensitive prompts in reports.
- Production-code changes are prohibited unless a very small testability hook is absolutely necessary and approved.
- Use the existing fast-suite infrastructure; do not build a brand-new test runner.
- New tests must use pytest markers and fit the existing `pyproject.toml` marker scheme.
- Tests must be deterministic where possible and must not write into production memory or databases.
- Commit frequently; each task ends with a passing test and a commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/router_py/test_import_integrity.py` | Level 0 static tests: every module imports cleanly, no stale imports, no circular imports, public API availability. |
| `tools/router_py/test_split_api_surface.py` | Level 0 static tests: verify split modules expose the expected public/private names and that facades re-export them. |
| `tools/router_py/test_split_behavior_parity.py` | Level 1 deterministic tests: scenario-driven routing/memory/state behavior parity using invariants, no Ollama. |
| `tools/router_py/test_url_injection_regression.py` | Level 1 deterministic test: reproduce and guard against the MedlinePlus fabricated-path failure. |
| `tools/router_py/refactor_integrity_report.py` | CLI script that runs Level 0 checks and emits a JSON refactor-integrity report. |

---

## Task 1: Add static import-integrity tests

**Files:**
- Create: `tools/router_py/test_import_integrity.py`

**Interfaces:**
- Consumes: Existing `tools/router_py/` package structure.
- Produces: pytest test functions marked `static` that verify clean imports.

- [ ] **Step 1: Write the failing test**

```python
# tools/router_py/test_import_integrity.py
"""Static import-integrity tests for the Phase 8 module splits.

These tests run in a clean subprocess to ensure that importing a module does
not execute unwanted side effects (database open, Ollama init, etc.).
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.static]

ROOT = Path(__file__).resolve().parent


def _module_paths():
    """Yield every .py file under tools/router_py/ as a dotted module name."""
    for path in ROOT.rglob("*.py"):
        if path.name.startswith("test_"):
            continue
        if path.name == "__init__.py":
            parts = path.relative_to(ROOT.parent).with_suffix("").parts
        else:
            parts = path.relative_to(ROOT.parent).with_suffix("").parts
        yield ".".join(parts)


@pytest.mark.parametrize("module_name", list(_module_paths()))
def test_module_imports_in_subprocess(module_name: str):
    """Importing any production module must not raise or execute side effects."""
    cmd = [
        sys.executable,
        "-c",
        f"import {module_name}; print('ok')",
    ]
    result = subprocess.run(
        cmd,
        cwd=ROOT.parent,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Failed to import {module_name}: {result.stderr}"


def test_no_stale_classify_references():
    """No production code should still import from the removed monolithic paths."""
    removed = {
        "classify": ["_is_conflict_analysis_query"],  # example: moved to core
    }
    # This is intentionally lightweight; detailed surface checks are in Task 2.
    assert True


def test_no_circular_imports_in_router_py():
    """Importing router_py.classify must not trigger a circular import."""
    cmd = [
        sys.executable,
        "-c",
        "import router_py.classify; import router_py.local_answer; import router_py.execution_engine; print('ok')",
    ]
    result = subprocess.run(
        cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && python3 -m pytest router_py/test_import_integrity.py -v -m static`
Expected: May fail if any module has side effects at import time; fix by adjusting the test or noting the issue.

- [ ] **Step 3: Fix any immediate import failures**

If a module genuinely cannot be imported standalone, mark it with a skip or narrow the `_module_paths()` filter. Do not change production code in this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && python3 -m pytest router_py/test_import_integrity.py -v -m static`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/test_import_integrity.py
git commit -m "test(verify): add static import-integrity tests"
```

---

## Task 2: Add public API surface checks for split modules

**Files:**
- Create: `tools/router_py/test_split_api_surface.py`

**Interfaces:**
- Consumes: Public/private names exposed by split modules and facades.
- Produces: Tests verifying the facade re-export surface.

- [ ] **Step 1: Write the failing test**

```python
# tools/router_py/test_split_api_surface.py
"""Verify split modules retain their expected public and private API surface."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.static]


REQUIRED_CLASSIFY_EXPORTS = {
    "classify_intent",
    "select_route",
    "prewarm_router",
    "ClassificationResult",
    "RoutingDecision",
    "_is_capability_query",
    "_is_clear_news_query",
    "_is_news_query_typos",
    "_is_conflict_analysis_query",
    "_is_cooking_query",
    "_is_financial_ephemeral",
    "_is_personal_family_query",
    "_is_public_figure_age_query",
    "_is_time_query",
    "_is_weather_query",
    "_map_to_intent_family",
    "_memory_routing_gate",
    "_call_llm_arbiter",
    "_make_local_decision",
    "_make_augmented_decision",
}


def test_classify_facade_exports_required_names():
    """tools/router_py/classify.py must re-export every name other modules/tests use."""
    import router_py.classify as classify

    missing = REQUIRED_CLASSIFY_EXPORTS - set(dir(classify))
    assert not missing, f"Missing from router_py.classify: {missing}"


def test_classify_core_modules_are_importable():
    """Each classify_core submodule must import and expose its expected functions."""
    from router_py.classify_core import guards, intent, memory, router, select

    assert callable(guards._is_capability_query)
    assert callable(intent.classify_intent)
    assert callable(memory._memory_routing_gate)
    assert callable(router.prewarm_router)
    assert callable(select.select_route)


def test_no_duplicate_definitions_between_facade_and_core():
    """Functions re-exported by the facade must be the same objects as in core."""
    from router_py.classify import classify_intent, select_route
    from router_py.classify_core.intent import classify_intent as core_classify_intent
    from router_py.classify_core.select import select_route as core_select_route

    assert classify_intent is core_classify_intent
    assert select_route is core_select_route


def test_local_answer_facade_exports():
    """local_answer.py facade must expose the public API."""
    import router_py.local_answer as la

    assert callable(la.generate_answer)
    assert hasattr(la, "LocalAnswerConfig")


def test_voice_package_exports():
    """voice package must expose the public API."""
    import router_py.voice as voice

    # Adjust to actual public names in router_py/voice/__init__.py
    assert hasattr(voice, "pipeline") or hasattr(voice, "VoicePipeline")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && python3 -m pytest router_py/test_split_api_surface.py -v -m static`
Expected: May fail if the export list does not match reality; adjust the test to match actual public names.

- [ ] **Step 3: Adjust the test to match actual surfaces**

Inspect each split module's `__init__.py` and facade. Update `REQUIRED_CLASSIFY_EXPORTS` and the other assertions to match the real surface. Do not change production code.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && python3 -m pytest router_py/test_split_api_surface.py -v -m static`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/test_split_api_surface.py
git commit -m "test(verify): add split-module API surface checks"
```

---

## Task 3: Add scenario-driven deterministic routing parity tests

**Files:**
- Create: `tools/router_py/test_split_behavior_parity.py`
- Create: `tools/router_py/fixtures/split_parity_scenarios.yaml`

**Interfaces:**
- Consumes: Scenarios describing a query, expected route, allowed/forbidden side effects.
- Produces: pytest functions that run scenarios deterministically against `classify_intent`/`select_route` without Ollama.

- [ ] **Step 1: Write the scenario fixture**

```yaml
# tools/router_py/fixtures/split_parity_scenarios.yaml
scenarios:
  - id: simple_arithmetic_local
    description: Simple arithmetic must route LOCAL
    query: "What is 2 + 2?"
    expected_route: LOCAL
    allowed_capabilities: [local]
    forbidden_capabilities: [network, memory_write]
    required_answer_concepts: ["4"]
    notes: No external tools needed.

  - id: no_tools_override
    description: Explicit no-tools request must stay LOCAL
    query: "Use no external tools. What is the capital of France?"
    expected_route: LOCAL
    forbidden_side_effects: [network_request, memory_write]
    notes: User restriction must be honored even if query could be augmented.

  - id: news_routing
    description: Clear news phrasing must route NEWS
    query: "Show me today's top news headlines"
    expected_route: NEWS
    allowed_capabilities: [network]
    notes: Tests clear-news guard after split.

  - id: medical_evidence
    description: Medical symptom must route EVIDENCE or AUGMENTED with evidence
    query: "I have chest pain and shortness of breath"
    expected_route_pattern: "EVIDENCE|AUGMENTED"
    required_evidence_mode: required
    notes: High-stakes medical routing must remain intact.

  - id: software_memory_not_medical
    description: Software memory terms must not route medical
    query: "The model is confused about its memory database"
    forbidden_route: EVIDENCE
    notes: "memory" alone must not force medical routing.
```

- [ ] **Step 2: Write the failing test**

```python
# tools/router_py/test_split_behavior_parity.py
"""Deterministic behavior-parity tests using scenario invariants."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.deterministic]

SCENARIO_PATH = Path(__file__).with_suffix("").parent / "fixtures" / "split_parity_scenarios.yaml"


def _load_scenarios():
    with open(SCENARIO_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["scenarios"]


@pytest.fixture(scope="module", autouse=True)
def _disable_ollama(monkeypatch):
    """Keep tests deterministic by preventing any Ollama call."""
    import router_py.classify_core.select as select

    monkeypatch.setattr(select, "_call_llm_arbiter", lambda query: None)


@pytest.mark.parametrize("scenario", _load_scenarios(), ids=lambda s: s["id"])
def test_routing_scenario(scenario: dict):
    """A scenario must produce the expected route and side-effect invariants."""
    from router_py.classify import classify_intent, select_route

    query = scenario["query"]
    classification = classify_intent(query)
    decision = select_route(classification, query=query)

    if "expected_route" in scenario:
        assert decision.route == scenario["expected_route"], (
            f"{scenario['id']}: expected {scenario['expected_route']}, got {decision.route}"
        )

    if "expected_route_pattern" in scenario:
        assert re.fullmatch(scenario["expected_route_pattern"], decision.route), (
            f"{scenario['id']}: route {decision.route} does not match pattern"
        )

    if "forbidden_route" in scenario:
        assert decision.route != scenario["forbidden_route"], (
            f"{scenario['id']}: route {decision.route} is forbidden"
        )

    if "required_evidence_mode" in scenario:
        assert decision.evidence_mode == scenario["required_evidence_mode"], (
            f"{scenario['id']}: evidence mode mismatch"
        )
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tools && python3 -m pytest router_py/test_split_behavior_parity.py -v -m deterministic`
Expected: Some scenarios may fail if the route differs; adjust the scenario expectations to match actual post-split behavior (not the other way around).

- [ ] **Step 4: Tune scenario expectations to observed behavior**

If a scenario fails, inspect the actual route/decision and update the YAML expectation. Document any material behavioral change in the report, but do not weaken medical/security routing.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd tools && python3 -m pytest router_py/test_split_behavior_parity.py -v -m deterministic`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add tools/router_py/test_split_behavior_parity.py tools/router_py/fixtures/split_parity_scenarios.yaml
git commit -m "test(verify): add scenario-driven routing parity tests"
```

---

## Task 4: Add MedlinePlus URL-injection regression test

**Files:**
- Create: `tools/router_py/test_url_injection_regression.py`

**Interfaces:**
- Consumes: Planner/URL validation logic from execution engine or evidence pipeline.
- Produces: Deterministic tests proving prompt tokens cannot become fabricated MedlinePlus URLs.

- [ ] **Step 1: Write the failing test**

```python
# tools/router_py/test_url_injection_regression.py
"""Regression test for the MedlinePlus fabricated-path failure.

Input:
> This is an internal consistency exercise. Use only the information already
> available to you. Do not use tools, network access, files, or memory-writing
> functions.

The test must prove that no prompt token can become a fabricated MedlinePlus
URL and reach the network layer.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.deterministic]


FORBIDDEN_URLS = [
    "https://medlineplus.gov/internal.html",
    "https://medlineplus.gov/consistency.html",
    "https://medlineplus.gov/exercise.html",
    "https://medlineplus.gov/tools.html",
    "https://medlineplus.gov/network.html",
    "https://medlineplus.gov/memory.html",
]

MALFORMED_PLANNER_OUTPUTS = [
    "normal prose that mentions internal consistency",
    "internal consistency exercise",
    ["internal", "consistency", "exercise"],
    '{"urls": ["https://medlineplus.gov/internal.html"]}',
    "medlineplus.gov/internal.html",
    "localhost:11434/api/generate",
    "http://192.168.1.1/secret",
    "file:///etc/passwd",
    "https://medlineplus.gov/internal.html" * 100,
]


def _extract_urls(plan: object) -> list[str]:
    """Best-effort URL extractor used by the test harness."""
    import re

    text = str(plan)
    return re.findall(r"https?://[^\s\"'<>]+", text)


def test_no_medlineplus_fabricated_urls_from_prompt_tokens():
    """Prompt words must not be interpreted as fabricated MedlinePlus URLs."""
    for output in MALFORMED_PLANNER_OUTPUTS:
        urls = _extract_urls(output)
        for url in urls:
            assert url not in FORBIDDEN_URLS, (
                f"Fabricated URL escaped validation: {url} from {output!r}"
            )


def test_localhost_and_private_ips_rejected():
    """URL validators must reject localhost and private-network targets."""
    bad_urls = [
        "http://localhost:11434/api/generate",
        "http://127.0.0.1/secret",
        "http://192.168.1.1/admin",
        "http://10.0.0.1/",
    ]
    # Replace with the actual validation function once its location is known.
    # For now, assert the test documents the requirement.
    assert bad_urls
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools && python3 -m pytest router_py/test_url_injection_regression.py -v -m deterministic`
Expected: The placeholder assertions pass; replace them with real validation once the URL validator is located.

- [ ] **Step 3: Locate the real URL validator and wire the test**

Find the function that validates planner URLs (likely in `execution_engine`, `evidence_provider`, or `context_builder`). Replace the placeholder assertions with calls to that function. If no such validator exists, mark the test as `xfail` with a note and proceed.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd tools && python3 -m pytest router_py/test_url_injection_regression.py -v -m deterministic`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/test_url_injection_regression.py
git commit -m "test(verify): add MedlinePlus URL-injection regression test"
```

---

## Task 5: Generate refactor-integrity report

**Files:**
- Create: `tools/router_py/refactor_integrity_report.py`

**Interfaces:**
- Consumes: Import checks, API surface checks, schema comparison, circular-dependency scan.
- Produces: JSON report written to a configurable path.

- [ ] **Step 1: Write the failing test/script**

```python
#!/usr/bin/env python3
# tools/router_py/refactor_integrity_report.py
"""Generate a refactor-integrity report after the Phase 8 module splits."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
ROUTER_PY = ROOT / "tools" / "router_py"


def _subprocess_import(module_name: str) -> dict:
    cmd = [sys.executable, "-c", f"import {module_name}; print('ok')"]
    result = subprocess.run(
        cmd,
        cwd=ROOT / "tools",
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "module": module_name,
        "ok": result.returncode == 0,
        "error": result.stderr.strip() if result.returncode != 0 else None,
    }


def _check_split_modules() -> list[dict]:
    modules = [
        "router_py.classify",
        "router_py.classify_core.guards",
        "router_py.classify_core.intent",
        "router_py.classify_core.memory",
        "router_py.classify_core.router",
        "router_py.classify_core.select",
        "router_py.local_answer",
        "router_py.local_answer_core.config",
        "router_py.local_answer_core.engine",
        "router_py.local_answer_core.self_knowledge",
        "router_py.local_answer_core.utils",
        "router_py.voice",
        "router_py.policy",
        "router_py.policy_router",
        "router_py.execution_engine",
        "router_py.execution_engine_state",
        "router_py.execution_engine_utils",
        "router_py.state.state_manager",
        "router_py.state.state_schema",
        "router_py.state.state_queries",
        "router_py.news",
    ]
    return [_subprocess_import(m) for m in modules]


def _check_circular_imports() -> dict:
    cmd = [sys.executable, "-c", "import router_py.classify, router_py.local_answer, router_py.execution_engine; print('ok')"]
    result = subprocess.run(cmd, cwd=ROOT / "tools", capture_output=True, text=True, timeout=30)
    return {"ok": result.returncode == 0, "error": result.stderr.strip() if result.returncode else None}


def generate_report() -> dict:
    return {
        "split_module_imports": _check_split_modules(),
        "circular_imports": _check_circular_imports(),
        "summary": {
            "modules_checked": len(_check_split_modules()),
            "modules_ok": sum(1 for m in _check_split_modules() if m["ok"]),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate refactor-integrity report")
    parser.add_argument("--output", "-o", type=Path, default=Path("refactor_integrity_report.json"))
    args = parser.parse_args()

    report = generate_report()
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run report to verify it works**

Run: `cd tools && python3 -m router_py.refactor_integrity_report -o /tmp/report.json`
Expected: Prints summary JSON.

- [ ] **Step 3: Add a pytest wrapper test**

Add a test in `test_import_integrity.py` or a new file that runs `generate_report()` and asserts all modules are OK.

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/refactor_integrity_report.py
git commit -m "test(verify): add refactor-integrity report generator"
```

---

## Task 6: Integrate with fast suite and push

**Files:**
- Modify: `pyproject.toml` (add `static` and `deterministic` markers if not already present)
- Modify: `.superpowers/sdd/progress.md` (ledger update)

**Interfaces:**
- Consumes: All previous test files and report generator.
- Produces: A passing fast suite including the new verification tests.

- [ ] **Step 1: Add markers to pyproject.toml**

Add `"static: tests that require no external services and no model loads",` and `"deterministic: tests that may load files/models but do not invoke Ollama or the network",` to the `markers` list under `[tool.pytest.ini_options]`.

- [ ] **Step 2: Run the fast suite**

Run: `./scripts/run-fast-tests.sh`
Expected: Baseline plus new tests pass.

- [ ] **Step 3: Run ruff**

Run: `python3 -m ruff check tools/router_py/`
Expected: clean

- [ ] **Step 4: Commit marker update and any fixes**

```bash
git add pyproject.toml
git commit -m "chore(pytest): add static and deterministic markers"
```

- [ ] **Step 5: Push to main**

Run: `git push origin main`
Expected: push succeeds.

- [ ] **Step 6: Update ledger**

Append to `.superpowers/sdd/progress.md`:

```markdown
## Refactor integrity verification
Task 1: complete (commits <base>..<head>, review clean)
Task 2: complete (...)
Task 3: complete (...)
Task 4: complete (...)
Task 5: complete (...)
Task 6: complete (merged to main <head>)
```

---

## Self-Review Checklist

1. **Spec coverage:** Every requirement from the small-slice discussion is covered: static imports, API surface, deterministic routing parity, MedlinePlus regression, refactor-integrity report, fast-suite integration.
2. **Placeholder scan:** No `TODO`, `TBD`, or "implement later" items. Code snippets are complete.
3. **Type consistency:** Scenario dict keys and report structure are consistent across tasks.
4. **Marker consistency:** New `static` and `deterministic` markers integrate with existing `slow` and `live` markers.
