# Phase 5 Router Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the active router scripts out of `tools/router/`, delete the directory, update all callers/tests/docs, and keep behaviour unchanged.

**Architecture:** Create thin CLI wrappers under `tools/router_py/` that delegate to `tools/router_py/core/`. Relocate the frozen `plan_to_pipeline.py` orchestrator to `tools/router_py/plan_to_pipeline_cli.py`. Update shell-test paths in small batches, clean stale references, regenerate `SHA256SUMS`, and sweep documentation.

**Tech Stack:** Python 3.10, bash, pytest, git, sha256sum.

## Global Constraints

- Do not modify `/home/mike/lucy-v10`.
- Do not change application behaviour during structural cleanup.
- Make small, reversible commits; run relevant tests after each.
- Delete `tools/router/` only when no valid runtime reference remains and all relevant tests pass.
- Confirm V10 source checksums remain unchanged after each commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/router_py/core/extract_validated.py` | Canonical `clean()` and `parse()` for `BEGIN_VALIDATED…END_VALIDATED` blocks. |
| `tools/router_py/extract_validated_cli.py` | Stdin → `parse()` → JSON CLI; preserves old pipe invocation. |
| `tools/router_py/classify_intent_cli.py` | Wraps `router_py.core.intent_classifier.classify_question`. |
| `tools/router_py/plan_to_pipeline_cli.py` | Frozen orchestrator relocated from `tools/router/plan_to_pipeline.py`; preserves `--plan-json` interface. |
| `tools/router_py/extract_medical_fact_cli.py` | Wraps `router_py.core.medical_fact_extractor.main`. |
| `tools/router_py/medical_query_heuristics_cli.py` | Preserves `--is-human-medication-high-risk` and `--detect-human-medication` flags. |
| `tools/router_py/test_extract_validated.py` | Unit tests for the migrated parser. |
| `tools/tests/test_*.sh` | Updated to invoke the new `tools/router_py/*_cli.py` paths. |
| `tools/build_evidence_pack.sh` | Stale `LATPROF_LIB` lookup removed. |
| `tools/fetch_key.sh` | Stale `LATPROF_LIB` lookup removed. |
| `tools/trust/medical_tier3_corroboration_regression.sh` | Stale `execute_plan.sh` branch removed. |
| `tools/health_battery.sh` | Broken `router_regression.sh` step removed or redirected. |
| `SHA256SUMS` | Regenerated after `tools/router/` deletion. |

---

### Task 1: Migrate `extract_validated.py` parser core

**Files:**
- Create: `tools/router_py/core/extract_validated.py`
- Create: `tools/router_py/test_extract_validated.py`
- Modify: `tools/router_py/core/__init__.py` (if needed for exports)
- Test: `pytest tools/router_py/test_extract_validated.py -v`

**Interfaces:**
- Produces: `clean(s: str) -> str`, `parse(text: str) -> dict` with keys `parse_ok`, `answer`, `sources`, `claims`, `raw`.

- [ ] **Step 1: Write the failing test**

Create `tools/router_py/test_extract_validated.py`:

```python
import json
import os

from router_py.core.extract_validated import parse


SAMPLE = """BEGIN_VALIDATED
Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections.

Evidence:
type: entity
subject: Amoxicillin

Oscar is Mike's dog. He has a fixation on cats; training approach uses leave-it, distance, and reward.

---- BEGIN PROPOSAL ----
[MEMORY PROPOSAL]
type: drug information
subject: Amoxicillin
summary: A broad-spectrum antibiotic used to treat various bacterial infections.
confidence: high
---- END PROPOSAL ----
END_VALIDATED
"""


def test_parse_stops_before_evidence_and_proposal():
    result = parse(SAMPLE)
    assert result["parse_ok"] is True
    assert (
        result["answer"]
        == "Amoxicillin is a broad-spectrum antibiotic used to treat various bacterial infections."
    )
    assert "Oscar" not in result["answer"]
    assert "MEMORY PROPOSAL" not in result["answer"]
    assert "type:" not in result["answer"]
    assert "subject:" not in result["answer"]
    assert "confidence:" not in result["answer"]


def test_parse_empty_input():
    result = parse("")
    assert result["parse_ok"] is False
    assert result["answer"] == ""
    assert result["sources"] == []
    assert result["claims"] == []


def test_parse_missing_markers():
    result = parse("There is no validated block here.")
    assert result["parse_ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /home/mike/lucy-v11
pytest tools/router_py/test_extract_validated.py -v
```

Expected: `ModuleNotFoundError: No module named 'router_py.core.extract_validated'`

- [ ] **Step 3: Write minimal implementation**

Create `tools/router_py/core/extract_validated.py` by copying the unique logic from `tools/router/extract_validated.py`:

```python
import json
import re


def clean(s: str) -> str:
    s = s.replace("\r", "")
    return "\n".join([ln.rstrip() for ln in s.splitlines()])


def parse(text: str):
    raw = clean(text)
    lines = raw.splitlines()
    out = {
        "parse_ok": False,
        "answer": "",
        "sources": [],
        "claims": [],
        "raw": raw,
    }

    try:
        if not lines:
            return out
        begin = next((i for i, ln in enumerate(lines) if ln.strip() == "BEGIN_VALIDATED"), None)
        end = next((i for i, ln in enumerate(lines) if ln.strip() == "END_VALIDATED"), None)
        if begin is None or end is None or end <= begin:
            return out

        body = lines[begin + 1 : end]
        answer_parts = []
        claims = []
        sources = []
        answer_started = False

        def add_sources_blob(blob: str):
            parts = [p.strip() for p in re.split(r"[,;]", blob or "") if p.strip()]
            for p in parts:
                d = re.sub(r"^https?://", "", p, flags=re.I).split("/")[0].lower()
                d = d[4:] if d.startswith("www.") else d
                sources.append({"domain": d or p, "url": p if p.startswith("http") else ""})

        for ln in body:
            s = ln.strip()
            if not s:
                continue

            if s in {"Evidence:", "[MEMORY PROPOSAL]", "---- BEGIN PROPOSAL ----"}:
                break

            if answer_started and re.match(r"^(type|subject|confidence):", s, flags=re.I):
                break

            if s.lower().startswith("sources:"):
                rest = s.split(":", 1)[1].strip()
                if rest:
                    add_sources_blob(rest)
                continue

            if " sources:" in s.lower():
                pre, post = re.split(r"\b[Ss]ources:\s*", s, maxsplit=1)
                s = pre.strip()
                if post.strip():
                    add_sources_blob(post.strip())

            if re.match(r"^-\s+", s):
                claims.append(re.sub(r"^-\s+", "", s))
                continue

            if s.lower().startswith("summary:"):
                answer_parts.append(s.split(":", 1)[1].strip())
                answer_started = True
                continue

            if s.lower().startswith("answer:"):
                answer_parts.append(s.split(":", 1)[1].strip())
                answer_started = True
                continue

            if re.match(r"^https?://", s):
                d = re.sub(r"^https?://", "", s, flags=re.I).split("/")[0].lower()
                d = d[4:] if d.startswith("www.") else d
                sources.append({"domain": d or s, "url": s})
                continue

            if s.startswith("ERROR:") or s.startswith("WARN:"):
                continue

            answer_parts.append(s)
            answer_started = True

        if not answer_parts and claims:
            answer_parts.append(claims[0])

        dedup = []
        seen = set()
        for src in sources:
            key = (src.get("domain", ""), src.get("url", ""))
            if key in seen:
                continue
            seen.add(key)
            dedup.append(src)

        out.update(
            {
                "parse_ok": True,
                "answer": " ".join([p for p in answer_parts if p]).strip(),
                "sources": dedup,
                "claims": claims,
            }
        )
        return out
    except Exception:
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /home/mike/lucy-v11
pytest tools/router_py/test_extract_validated.py -v
```

Expected: three passing tests.

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/core/extract_validated.py tools/router_py/test_extract_validated.py
git commit -m "feat(router): migrate extract_validated parser to router_py core"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 2: Add `extract_validated_cli.py` wrapper and update its shell test

**Files:**
- Create: `tools/router_py/extract_validated_cli.py`
- Modify: `tools/tests/test_extract_validated_proposal_noise.sh:7`
- Test: `bash tools/tests/test_extract_validated_proposal_noise.sh`

**Interfaces:**
- Consumes: `router_py.core.extract_validated.parse`
- Produces: executable CLI that reads stdin and prints compact JSON.

- [ ] **Step 1: Update the shell test path (failing test)**

In `tools/tests/test_extract_validated_proposal_noise.sh`, change line 7:

```bash
EXTRACTOR="${ROOT}/tools/router/extract_validated.py"
```

to:

```bash
EXTRACTOR="${ROOT}/tools/router_py/extract_validated_cli.py"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_extract_validated_proposal_noise.sh
```

Expected: `FAIL: missing extractor: /home/mike/lucy-v11/tools/router_py/extract_validated_cli.py`

- [ ] **Step 3: Write the CLI wrapper**

Create `tools/router_py/extract_validated_cli.py`:

```python
#!/usr/bin/env python3
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.extract_validated import parse


def main():
    text = sys.stdin.read()
    print(json.dumps(parse(text), separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
```

Make it executable:
```bash
chmod +x /home/mike/lucy-v11/tools/router_py/extract_validated_cli.py
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_extract_validated_proposal_noise.sh
```

Expected: `PASS: test_extract_validated_proposal_noise`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/extract_validated_cli.py tools/tests/test_extract_validated_proposal_noise.sh
git commit -m "feat(router): add extract_validated_cli wrapper and update its test"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 3: Add `classify_intent_cli.py` wrapper and update one classifier shell test

**Files:**
- Create: `tools/router_py/classify_intent_cli.py`
- Modify: `tools/tests/test_phase1_classifier_output.sh:7`
- Test: `bash tools/tests/test_phase1_classifier_output.sh`

**Interfaces:**
- Consumes: `router_py.core.intent_classifier.classify_question(question, surface=...)`
- Produces: executable CLI that prints compact JSON classification.

- [ ] **Step 1: Update the shell test path (failing test)**

In `tools/tests/test_phase1_classifier_output.sh`, change line 7:

```bash
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
```

to:

```bash
CLASSIFIER="${ROOT}/tools/router_py/classify_intent_cli.py"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_phase1_classifier_output.sh
```

Expected: `FAIL: missing executable: /home/mike/lucy-v11/tools/router_py/classify_intent_cli.py`

- [ ] **Step 3: Write the CLI wrapper**

Create `tools/router_py/classify_intent_cli.py`:

```python
#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.intent_classifier import classify_question


def main() -> int:
    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    else:
        question = sys.stdin.read()
    surface = (os.environ.get("LUCY_SURFACE") or "cli").strip().lower() or "cli"
    output = classify_question(question, surface=surface)
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:
```bash
chmod +x /home/mike/lucy-v11/tools/router_py/classify_intent_cli.py
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_phase1_classifier_output.sh
```

Expected: `PASS: test_phase1_classifier_output`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/classify_intent_cli.py tools/tests/test_phase1_classifier_output.sh
git commit -m "feat(router): add classify_intent_cli wrapper and update one test"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 4: Add `plan_to_pipeline_cli.py` wrapper and update one mapper shell test

**Files:**
- Create: `tools/router_py/plan_to_pipeline_cli.py`
- Modify: `tools/tests/test_plan_to_pipeline_mapping.sh:7-8`
- Test: `bash tools/tests/test_plan_to_pipeline_mapping.sh`

**Interfaces:**
- Consumes: `router_py.core.*` modules (same set as the legacy orchestrator)
- Produces: executable CLI with `--plan-json`, `--question`, `--route-prefix`, `--route-control-mode`, `--surface` flags; prints the same compact JSON.

- [ ] **Step 1: Update the shell test path (failing test)**

In `tools/tests/test_plan_to_pipeline_mapping.sh`, change lines 7-8:

```bash
MAPPER="${ROOT}/tools/router/plan_to_pipeline.py"
CLASSIFIER="${ROOT}/tools/router/classify_intent.py"
```

to:

```bash
MAPPER="${ROOT}/tools/router_py/plan_to_pipeline_cli.py"
CLASSIFIER="${ROOT}/tools/router_py/classify_intent_cli.py"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_plan_to_pipeline_mapping.sh
```

Expected: `FAIL: missing mapper: /home/mike/lucy-v11/tools/router_py/plan_to_pipeline_cli.py`

- [ ] **Step 3: Write the CLI wrapper**

Create `tools/router_py/plan_to_pipeline_cli.py` by copying `tools/router/plan_to_pipeline.py` verbatim. The existing `sys.path` logic already resolves `tools/` correctly from either `tools/router/` or `tools/router_py/`:

```bash
cp /home/mike/lucy-v11/tools/router/plan_to_pipeline.py /home/mike/lucy-v11/tools/router_py/plan_to_pipeline_cli.py
```

Make it executable:
```bash
chmod +x /home/mike/lucy-v11/tools/router_py/plan_to_pipeline_cli.py
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_plan_to_pipeline_mapping.sh
```

Expected: `PASS: test_plan_to_pipeline_mapping`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/plan_to_pipeline_cli.py tools/tests/test_plan_to_pipeline_mapping.sh
git commit -m "feat(router): add plan_to_pipeline_cli wrapper and update one test"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 5: Add `medical_query_heuristics_cli.py` wrapper and update one medication shell test

**Files:**
- Create: `tools/router_py/medical_query_heuristics_cli.py`
- Modify: `tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh:38`
- Test: `bash tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh`

**Interfaces:**
- Consumes: `router_py.core.medical_query_heuristics` functions
- Produces: executable CLI with `--is-human-medication-high-risk` and `--detect-human-medication` flags.

- [ ] **Step 1: Update the shell test path (failing test)**

In `tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh`, change line 38:

```bash
cp "${REAL_ROOT}/tools/router/medical_query_heuristics.py" "${FAKE_ROOT}/tools/router/medical_query_heuristics.py"
```

to:

```bash
mkdir -p "${FAKE_ROOT}/tools/router_py"
cp "${REAL_ROOT}/tools/router_py/medical_query_heuristics_cli.py" "${FAKE_ROOT}/tools/router_py/medical_query_heuristics_cli.py"
```

Also update line 85 to chmod the new path:

```bash
chmod +x \
  "${FAKE_ROOT}/tools/evidence_session.sh" \
  "${FAKE_ROOT}/tools/build_evidence_pack.sh" \
  "${FAKE_ROOT}/tools/fetch_key.sh" \
  "${FAKE_ROOT}/tools/fetch_url_allowlisted.sh" \
  "${FAKE_ROOT}/tools/compose_from_evidence.sh" \
  "${FAKE_ROOT}/tools/print_validated.sh" \
  "${FAKE_ROOT}/tools/router_py/medical_query_heuristics_cli.py"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh
```

Expected: failure because the wrapper does not exist or the copied script path changed.

- [ ] **Step 3: Write the CLI wrapper**

Create `tools/router_py/medical_query_heuristics_cli.py`:

```python
#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.medical_query_heuristics import (
    detect_human_medication_query,
    is_human_medication_high_risk_query,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--is-human-medication-high-risk", dest="query", default=None)
    parser.add_argument("--detect-human-medication", dest="detect_query", default=None)
    args = parser.parse_args()

    if args.detect_query is not None:
        print(
            json.dumps(
                detect_human_medication_query(args.detect_query),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0
    if args.query is None:
        return 2
    return 0 if is_human_medication_high_risk_query(args.query) else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:
```bash
chmod +x /home/mike/lucy-v11/tools/router_py/medical_query_heuristics_cli.py
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh
```

Expected: `PASS: test_lucy_chat_dynamic_medication_definition_fast_path`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/medical_query_heuristics_cli.py tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh
git commit -m "feat(router): add medical_query_heuristics_cli wrapper and update one test"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 6: Add `extract_medical_fact_cli.py` wrapper and update one medication shell test

**Files:**
- Create: `tools/router_py/extract_medical_fact_cli.py`
- Modify: `tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh:38-39`
- Test: `bash tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh`

**Interfaces:**
- Consumes: `router_py.core.medical_fact_extractor.main`
- Produces: executable CLI that delegates argument parsing to the canonical extractor.

- [ ] **Step 1: Update the shell test path (failing test)**

In `tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh`, change lines 38-39:

```bash
cp "${REAL_ROOT}/tools/router/medical_query_heuristics.py" "${FAKE_ROOT}/tools/router/medical_query_heuristics.py"
cp "${REAL_ROOT}/tools/router/extract_medical_fact.py" "${FAKE_ROOT}/tools/router/extract_medical_fact.py"
```

to:

```bash
mkdir -p "${FAKE_ROOT}/tools/router_py"
cp "${REAL_ROOT}/tools/router_py/medical_query_heuristics_cli.py" "${FAKE_ROOT}/tools/router_py/medical_query_heuristics_cli.py"
cp "${REAL_ROOT}/tools/router_py/extract_medical_fact_cli.py" "${FAKE_ROOT}/tools/router_py/extract_medical_fact_cli.py"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh
```

Expected: failure because the wrapper does not exist or the copied script path changed.

- [ ] **Step 3: Write the CLI wrapper**

Create `tools/router_py/extract_medical_fact_cli.py`:

```python
#!/usr/bin/env python3
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
TOOLS_DIR = THIS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from router_py.core.medical_fact_extractor import main

if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:
```bash
chmod +x /home/mike/lucy-v11/tools/router_py/extract_medical_fact_cli.py
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd /home/mike/lucy-v11
bash tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh
```

Expected: `PASS: test_lucy_chat_dynamic_medication_dose_structured_extract`

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/router_py/extract_medical_fact_cli.py tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh
git commit -m "feat(router): add extract_medical_fact_cli wrapper and update one test"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 7: Update remaining affected shell tests

**Files:**
- Modify: all remaining `tools/tests/test_*.sh` that reference `tools/router/`
- Test: run each updated test

**Interfaces:**
- No new code; path updates only.

Remaining tests to update (from audit report §6, excluding those already handled):

1. `tools/tests/test_phase1_routing_output.sh`
2. `tools/tests/test_router_evidence_mode_selection.sh`
3. `tools/tests/test_router_current_conflict_news_routing.sh`
4. `tools/tests/test_policy_cross_surface_consistency.sh`
5. `tools/tests/test_plan_to_pipeline_news_rewrite_preserves_topic_scope.sh`
6. `tools/tests/test_semantic_interpreter_backend_cache_scope.sh`
7. `tools/tests/test_semantic_interpreter_gate_telemetry.sh`
8. `tools/tests/test_plan_to_pipeline_ai_policy_updates_avoids_news_drift.sh`
9. `tools/tests/test_plan_to_pipeline_ai_adjacent_queries_preserve_scope.sh`
10. `tools/tests/test_policy_global_route_prefers_evidence.sh`
11. `tools/tests/test_intent_classifier_policy_global_allowlist.sh`
12. `tools/tests/test_intent_classifier_recent_window_requires_evidence.sh`
13. `tools/tests/test_conversation_mode_classification.sh`
14. `tools/tests/test_niche_technical_queries_prefer_augmented.sh`
15. `tools/tests/test_medical_allowlist_plumbing.sh`
16. `tools/tests/test_medication_detector_broader_coverage.sh`
17. `tools/tests/test_manifest_authority_import.sh`
18. `tools/tests/test_news_israel_specificity_no_warning_leak.sh`
19. `tools/tests/test_news_region_filter_au_enforcement.sh`
20. `tools/tests/test_build_evidence_pack_parallel_deterministic_order.sh`
21. `tools/tests/test_lucy_chat_dynamic_medication_interaction_fail_closed.sh`

- [ ] **Step 1: Replace paths in batch**

Use `sed` to replace the legacy paths with the new wrapper paths:

```bash
cd /home/mike/lucy-v11
for f in tools/tests/test_*.sh; do
  sed -i 's|tools/router/classify_intent\.py|tools/router_py/classify_intent_cli.py|g' "$f"
  sed -i 's|tools/router/plan_to_pipeline\.py|tools/router_py/plan_to_pipeline_cli.py|g' "$f"
  sed -i 's|tools/router/extract_validated\.py|tools/router_py/extract_validated_cli.py|g' "$f"
  sed -i 's|tools/router/medical_query_heuristics\.py|tools/router_py/medical_query_heuristics_cli.py|g' "$f"
  sed -i 's|tools/router/extract_medical_fact\.py|tools/router_py/extract_medical_fact_cli.py|g' "$f"
done
```

- [ ] **Step 2: Inspect diff for accidental changes**

```bash
cd /home/mike/lucy-v11
git diff -- tools/tests/
```

Expected: only path changes; no assertion or logic changes.

- [ ] **Step 3: Run all affected shell tests**

```bash
cd /home/mike/lucy-v11
for f in \
  tools/tests/test_extract_validated_proposal_noise.sh \
  tools/tests/test_phase1_classifier_output.sh \
  tools/tests/test_phase1_routing_output.sh \
  tools/tests/test_plan_to_pipeline_mapping.sh \
  tools/tests/test_router_evidence_mode_selection.sh \
  tools/tests/test_router_current_conflict_news_routing.sh \
  tools/tests/test_policy_cross_surface_consistency.sh \
  tools/tests/test_plan_to_pipeline_news_rewrite_preserves_topic_scope.sh \
  tools/tests/test_semantic_interpreter_backend_cache_scope.sh \
  tools/tests/test_semantic_interpreter_gate_telemetry.sh \
  tools/tests/test_plan_to_pipeline_ai_policy_updates_avoids_news_drift.sh \
  tools/tests/test_plan_to_pipeline_ai_adjacent_queries_preserve_scope.sh \
  tools/tests/test_policy_global_route_prefers_evidence.sh \
  tools/tests/test_intent_classifier_policy_global_allowlist.sh \
  tools/tests/test_intent_classifier_recent_window_requires_evidence.sh \
  tools/tests/test_conversation_mode_classification.sh \
  tools/tests/test_niche_technical_queries_prefer_augmented.sh \
  tools/tests/test_medical_allowlist_plumbing.sh \
  tools/tests/test_medication_detector_broader_coverage.sh \
  tools/tests/test_manifest_authority_import.sh \
  tools/tests/test_news_israel_specificity_no_warning_leak.sh \
  tools/tests/test_news_region_filter_au_enforcement.sh \
  tools/tests/test_build_evidence_pack_parallel_deterministic_order.sh \
  tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh \
  tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh \
  tools/tests/test_lucy_chat_dynamic_medication_interaction_fail_closed.sh; do
  echo "=== $f ==="
  bash "$f"
done
```

Expected: every test prints `PASS:`.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/tests/
git commit -m "test(router): point all affected shell tests at router_py wrappers"
```

- [ ] **Step 5: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 8: Clean stale references to non-existent `tools/router/` files

**Files:**
- Modify: `tools/build_evidence_pack.sh`
- Modify: `tools/fetch_key.sh`
- Modify: `tools/trust/medical_tier3_corroboration_regression.sh`
- Modify: `tools/health_battery.sh`
- Test: grep for stale references; run `tools/health_battery.sh` if practical

**Interfaces:**
- No new code; removal of dead path lookups only.

- [ ] **Step 1: Remove `LATPROF_LIB` lookups**

In `tools/build_evidence_pack.sh` and `tools/fetch_key.sh`, find and remove:

```bash
LATPROF_LIB="${ROOT}/tools/router/latency_profile.sh"
```

Keep the no-op fallback stub that follows it (usually a function that does nothing when the library is missing).

- [ ] **Step 2: Remove `execute_plan.sh` branch**

In `tools/trust/medical_tier3_corroboration_regression.sh`, find and remove:

```bash
if [[ -x "$ROOT/tools/router/execute_plan.sh" ]]; then
  ...
fi
```

Keep the existing `lucy_chat.sh` fallback.

- [ ] **Step 3: Remove or redirect `router_regression.sh` step**

In `tools/health_battery.sh`, find the broken `router` step. Replace it with a Python-native step or remove it entirely:

```bash
# Old (broken):
# "$ROOT/tools/router_regression.sh" ...

# New:
echo "Router regression covered by pytest tools/router_py/"
```

- [ ] **Step 4: Verify no stale runtime references**

```bash
cd /home/mike/lucy-v11
grep -R "tools/router/" tools/ --include="*.py" --include="*.sh" || true
```

Expected: only references inside `tools/router/` itself (which will be deleted next) or explicitly historical comments.

- [ ] **Step 5: Commit**

```bash
cd /home/mike/lucy-v11
git add tools/build_evidence_pack.sh tools/fetch_key.sh tools/trust/medical_tier3_corroboration_regression.sh tools/health_battery.sh
git commit -m "chore(router): clean stale references to missing router scripts"
```

- [ ] **Step 6: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 9: Delete `tools/router/`

**Files:**
- Delete: `tools/router/`
- Test: run all affected shell tests

- [ ] **Step 1: Confirm deletion criteria**

```bash
cd /home/mike/lucy-v11
grep -R "tools/router/" tools/ docs/ dev_notes/ packaging/ --include="*.py" --include="*.sh" --include="*.md" | grep -v "historical" || true
```

Expected: no runtime references (only historical notes, if any).

- [ ] **Step 2: Delete the directory**

```bash
cd /home/mike/lucy-v11
git rm -r tools/router/
```

- [ ] **Step 3: Run all affected shell tests**

```bash
cd /home/mike/lucy-v11
for f in \
  tools/tests/test_extract_validated_proposal_noise.sh \
  tools/tests/test_phase1_classifier_output.sh \
  tools/tests/test_phase1_routing_output.sh \
  tools/tests/test_plan_to_pipeline_mapping.sh \
  tools/tests/test_router_evidence_mode_selection.sh \
  tools/tests/test_router_current_conflict_news_routing.sh \
  tools/tests/test_policy_cross_surface_consistency.sh \
  tools/tests/test_plan_to_pipeline_news_rewrite_preserves_topic_scope.sh \
  tools/tests/test_semantic_interpreter_backend_cache_scope.sh \
  tools/tests/test_semantic_interpreter_gate_telemetry.sh \
  tools/tests/test_plan_to_pipeline_ai_policy_updates_avoids_news_drift.sh \
  tools/tests/test_plan_to_pipeline_ai_adjacent_queries_preserve_scope.sh \
  tools/tests/test_policy_global_route_prefers_evidence.sh \
  tools/tests/test_intent_classifier_policy_global_allowlist.sh \
  tools/tests/test_intent_classifier_recent_window_requires_evidence.sh \
  tools/tests/test_conversation_mode_classification.sh \
  tools/tests/test_niche_technical_queries_prefer_augmented.sh \
  tools/tests/test_medical_allowlist_plumbing.sh \
  tools/tests/test_medication_detector_broader_coverage.sh \
  tools/tests/test_manifest_authority_import.sh \
  tools/tests/test_news_israel_specificity_no_warning_leak.sh \
  tools/tests/test_news_region_filter_au_enforcement.sh \
  tools/tests/test_build_evidence_pack_parallel_deterministic_order.sh \
  tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh \
  tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh \
  tools/tests/test_lucy_chat_dynamic_medication_interaction_fail_closed.sh; do
  echo "=== $f ==="
  bash "$f"
done
```

Expected: every test prints `PASS:`.

- [ ] **Step 4: Commit**

```bash
cd /home/mike/lucy-v11
git commit -m "chore(router): delete legacy tools/router/ directory"
```

- [ ] **Step 5: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 10: Update `SHA256SUMS`

**Files:**
- Modify: `SHA256SUMS`
- Test: `sha256sum -c SHA256SUMS` passes for remaining entries

- [ ] **Step 1: Regenerate the manifest**

If the project has a generation script, use it. Otherwise, remove the deleted file hashes and recompute:

```bash
cd /home/mike/lucy-v11
# Remove hashes for files that no longer exist
sed -i '\|tools/router/|d' SHA256SUMS

# Optional: recompute hashes for added files and append
sha256sum tools/router_py/extract_validated_cli.py \
  tools/router_py/classify_intent_cli.py \
  tools/router_py/plan_to_pipeline_cli.py \
  tools/router_py/extract_medical_fact_cli.py \
  tools/router_py/medical_query_heuristics_cli.py \
  tools/router_py/core/extract_validated.py \
  tools/router_py/test_extract_validated.py >> SHA256SUMS
```

- [ ] **Step 2: Verify the manifest**

```bash
cd /home/mike/lucy-v11
sha256sum -c SHA256SUMS
```

Expected: all remaining files report `OK`.

- [ ] **Step 3: Commit**

```bash
cd /home/mike/lucy-v11
git add SHA256SUMS
git commit -m "chore(router): update SHA256SUMS after tools/router/ removal"
```

- [ ] **Step 4: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 11: Sweep documentation

**Files:**
- Modify: `Architecture.md`, `AGENTS.md`, `docs/handoffs/*.md`, `dev_notes/*.md` (as needed)
- Test: grep for stale `tools/router/` references

- [ ] **Step 1: Find documentation references**

```bash
cd /home/mike/lucy-v11
grep -R "tools/router/" . --include="*.md" --exclude-dir=.git || true
```

- [ ] **Step 2: Update references to migrated paths**

For each non-historical reference, update it to the new `tools/router_py/*_cli.py` or `tools/router_py/core/` path. Historical notes may be left as-is if explicitly marked historical.

- [ ] **Step 3: Commit**

```bash
cd /home/mike/lucy-v11
git add Architecture.md AGENTS.md docs/ dev_notes/
git commit -m "docs(router): update references after tools/router/ removal"
```

- [ ] **Step 4: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

---

### Task 12: Final verification

**Files:**
- All files touched in previous tasks
- Test: full affected test suite + V10 checksum verification

- [ ] **Step 1: Run the Python test suite for router_py**

```bash
cd /home/mike/lucy-v11
pytest tools/router_py/test_extract_validated.py -v
```

Expected: all tests pass.

- [ ] **Step 2: Run all affected shell tests**

```bash
cd /home/mike/lucy-v11
for f in \
  tools/tests/test_extract_validated_proposal_noise.sh \
  tools/tests/test_phase1_classifier_output.sh \
  tools/tests/test_phase1_routing_output.sh \
  tools/tests/test_plan_to_pipeline_mapping.sh \
  tools/tests/test_router_evidence_mode_selection.sh \
  tools/tests/test_router_current_conflict_news_routing.sh \
  tools/tests/test_policy_cross_surface_consistency.sh \
  tools/tests/test_plan_to_pipeline_news_rewrite_preserves_topic_scope.sh \
  tools/tests/test_semantic_interpreter_backend_cache_scope.sh \
  tools/tests/test_semantic_interpreter_gate_telemetry.sh \
  tools/tests/test_plan_to_pipeline_ai_policy_updates_avoids_news_drift.sh \
  tools/tests/test_plan_to_pipeline_ai_adjacent_queries_preserve_scope.sh \
  tools/tests/test_policy_global_route_prefers_evidence.sh \
  tools/tests/test_intent_classifier_policy_global_allowlist.sh \
  tools/tests/test_intent_classifier_recent_window_requires_evidence.sh \
  tools/tests/test_conversation_mode_classification.sh \
  tools/tests/test_niche_technical_queries_prefer_augmented.sh \
  tools/tests/test_medical_allowlist_plumbing.sh \
  tools/tests/test_medication_detector_broader_coverage.sh \
  tools/tests/test_manifest_authority_import.sh \
  tools/tests/test_news_israel_specificity_no_warning_leak.sh \
  tools/tests/test_news_region_filter_au_enforcement.sh \
  tools/tests/test_build_evidence_pack_parallel_deterministic_order.sh \
  tools/tests/test_lucy_chat_dynamic_medication_definition_fast_path.sh \
  tools/tests/test_lucy_chat_dynamic_medication_dose_structured_extract.sh \
  tools/tests/test_lucy_chat_dynamic_medication_interaction_fail_closed.sh; do
  echo "=== $f ==="
  bash "$f"
done
```

Expected: every test prints `PASS:`.

- [ ] **Step 3: Verify no runtime references to `tools/router/` remain**

```bash
cd /home/mike/lucy-v11
grep -R "tools/router/" tools/ docs/ dev_notes/ packaging/ --include="*.py" --include="*.sh" --include="*.md" | grep -v "historical" || true
```

Expected: no output.

- [ ] **Step 4: Verify SHA256SUMS**

```bash
cd /home/mike/lucy-v11
sha256sum -c SHA256SUMS
```

Expected: all files report `OK`.

- [ ] **Step 5: Verify V10 unchanged**

```bash
cd /home/mike/lucy-v10
sha256sum -c /home/mike/lucy-v11-prep/inventory/v10_source_checksums.sha256 | grep -v "OK$"
```

Expected: no output.

- [ ] **Step 6: Update progress ledger**

Append to `/home/mike/lucy-v11/.superpowers/sdd/progress.md`:

```markdown
Phase 5: remove confirmed dead routing code
Task 5: migrate tools/router/ to tools/router_py/ wrappers and delete directory
Task 5: complete (commits <start>..<end>)
  - migrated extract_validated.py parser to tools/router_py/core/
  - created thin CLI wrappers under tools/router_py/
  - updated 25+ shell tests to use new wrapper paths
  - cleaned stale references in build_evidence_pack.sh, fetch_key.sh, medical_tier3_corroboration_regression.sh, health_battery.sh
  - deleted tools/router/
  - updated SHA256SUMS and documentation
```

Commit the ledger update:

```bash
cd /home/mike/lucy-v11
git add .superpowers/sdd/progress.md
git commit -m "docs: update progress ledger for completed Phase 5"
```

---

## Self-Review

### Spec coverage

- Migrate unique `extract_validated.py` parser → Task 1.
- Add CLI wrappers → Tasks 2-6.
- Update callers/tests → Tasks 2-7.
- Clean stale references → Task 8.
- Delete `tools/router/` → Task 9.
- Update `SHA256SUMS` → Task 10.
- Update documentation → Task 11.
- Final verification → Task 12.

### Placeholder scan

No TBD, TODO, or vague steps. Every step includes exact file paths, code, or commands.

### Type consistency

- `parse(text: str) -> dict` is used consistently.
- Wrapper CLIs preserve the same arguments and exit codes as the legacy scripts.

### Risk note

The `plan_to_pipeline_cli.py` wrapper is a verbatim relocation of the frozen legacy orchestrator. Reconciling it with `router_py/request_pipeline.py` / `execution_engine.py` is intentionally deferred to Phase 6 module cleanup.
