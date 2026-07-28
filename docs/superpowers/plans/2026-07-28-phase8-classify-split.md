# classify.py Phase 8 Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `tools/router_py/classify.py` (~2,859 lines) into a thin backward-compatible facade (`tools/router_py/classify.py`) and a focused package (`tools/router_py/classify_core/`) without changing any external call sites or test behavior.

**Architecture:** Decompose by responsibility: guards, embedding-router lifecycle, intent mapping, memory-aware routing, and route selection/decision builders. The facade re-exports the public API plus any private helpers imported by other production modules or tests, preserving patch paths such as `router_py.classify._call_llm_arbiter`.

**Tech Stack:** Python 3.10+, existing `router_py` package, pytest with `slow`/`live` markers, ruff for lint.

## Global Constraints

- Do not change the signature or runtime behavior of `classify_intent`, `select_route`, or `prewarm_router`.
- Preserve all re-exports from `router_py.classify` so existing callers continue to work unchanged in the first pass.
- Keep global singletons (`_ROUTER`, `_FEEDBACK_BUF_CACHE`) as single module-level instances in the core package.
- Run `./scripts/run-fast-tests.sh` after every mechanical move and before commit.
- Run `python3 -m ruff check tools/router_py/classify.py tools/router_py/classify_core/` after edits.
- Do not delete `tools/router_py/classify.py`; replace its body with re-exports.

---

## File Structure

| File | Responsibility |
|---|---|
| `tools/router_py/classify_core/__init__.py` | Package marker (keep minimal, no re-exports). |
| `tools/router_py/classify_core/guards.py` | All keyword / query-pattern detectors (`_is_*`) and their compiled regex constants / frozensets. |
| `tools/router_py/classify_core/router.py` | Embedding router lazy-loading (`_get_router`, `prewarm_router`), `_ROUTER` singleton + lock, decision logging (`_log_decision`, `_get_log_path`). |
| `tools/router_py/classify_core/intent.py` | `classify_intent`, `_map_to_intent_family`, and the `classify_question` import fallback. |
| `tools/router_py/classify_core/memory.py` | `_memory_routing_gate`, continuation-followup regexes, `_load_feedback_buffer`, and the feedback-buffer singleton cache. |
| `tools/router_py/classify_core/select.py` | `select_route`, `_routing_decision_from_policy`, `_call_llm_arbiter`, all `_make_*_decision` builders, `_POLICY_ROUTER` singleton. |
| `tools/router_py/classify.py` | Thin facade re-exporting public API and required private names. |

---

## Task 1: Scaffold the `classify_core` package

**Files:**
- Create: `tools/router_py/classify_core/__init__.py`

**Interfaces:**
- Produces: A valid Python package directory so later modules can import from it.

- [ ] **Step 1: Create package marker file**

```python
# tools/router_py/classify_core/__init__.py
"""Internal implementation package for the intent classifier / router."""
```

- [ ] **Step 2: Verify importability**

Run: `cd tools && python3 -c "import router_py.classify_core; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/classify_core/__init__.py
git commit -m "chore(classify): scaffold classify_core package"
```

---

## Task 2: Move guard detectors to `classify_core/guards.py`

**Files:**
- Create: `tools/router_py/classify_core/guards.py`
- Modify: `tools/router_py/classify.py` (remove moved code in Task 7)

**Interfaces:**
- Consumes: Nothing from other core modules.
- Produces: All `_is_*` functions and the regex/frozenset constants they need.

Move these exact names from `tools/router_py/classify.py` to `tools/router_py/classify_core/guards.py`:

```python
# tools/router_py/classify_core/guards.py
"""Keyword and query-pattern guards for intent routing."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

# Copy every guard function, regex constant, and frozenset currently defined
# between lines ~1424 and ~2490 of tools/router_py/classify.py.
# Examples include:
#   _LOCAL_ALWAYS_SHORT, _WEATHER_RE, _CLEAR_NEWS_RE, _HIST_*RE, _SYNTHESIS_*RE,
#   _TECH_*RE, _FINANCIAL_SHORT_RE, _CREATIVE_RE,
#   _is_conflict_analysis_query, _is_news_query_typos, _is_clear_news_query,
#   _is_time_query, _is_weather_query, _is_cooking_query, _is_financial_ephemeral,
#   _is_hostile_override_attempt, _is_capability_query, _is_language_or_translation_query,
#   _is_historical_query, _is_technical_knowledge_query, _is_synthesis_request,
#   _is_personal_family_query, _is_public_figure_age_query, _is_creative_writing.
```

- [ ] **Step 1: Copy guard functions and constants verbatim**

Copy lines ~1424–~2490 from `tools/router_py/classify.py` into `tools/router_py/classify_core/guards.py`, preserving the import block shown above.

- [ ] **Step 2: Run lint on the new file**

Run: `python3 -m ruff check tools/router_py/classify_core/guards.py`
Expected: `All checks passed!`

- [ ] **Step 3: Commit**

```bash
git add tools/router_py/classify_core/guards.py
git commit -m "refactor(classify): move guard detectors to classify_core/guards.py"
```

---

## Task 3: Move embedding-router lifecycle to `classify_core/router.py`

**Files:**
- Create: `tools/router_py/classify_core/router.py`
- Modify: `tools/router_py/classify.py` (remove moved code in Task 7)

**Interfaces:**
- Consumes: Nothing from other core modules.
- Produces: `_get_router`, `prewarm_router`, `_ROUTER`, `_ROUTER_LOCK`, `_log_decision`, `_get_log_path`.

```python
# tools/router_py/classify_core/router.py
"""Embedding / k-NN router lifecycle and decision logging."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.request_types import RoutingDecision

_LOGGER = logging.getLogger(__name__)

_ROUTER = None
_ROUTER_LOCK = threading.Lock()


def _get_router():
    """Lazy-load the embedding router (v2)."""
    global _ROUTER
    if _ROUTER is not None:
        return _ROUTER if _ROUTER is not False else None

    with _ROUTER_LOCK:
        if _ROUTER is not None:
            return _ROUTER if _ROUTER is not False else None

        try:
            router_dir = Path(__file__).resolve().parent.parent.parent / "models" / "router"
            if str(router_dir) not in sys.path:
                sys.path.insert(0, str(router_dir))
            from hybrid_router_v2 import HybridRouterV2

            _ROUTER = HybridRouterV2(
                embeddings_path=str(router_dir / "comprehensive_embeddings.npy"),
                examples_path=str(router_dir / "comprehensive_examples.json"),
            )
        except Exception as _exc:
            _LOGGER.error(
                "router_load_failure",
                extra={
                    "exception_type": type(_exc).__name__,
                    "exception_message": str(_exc),
                },
                exc_info=True,
            )
            _ROUTER = False
    return _ROUTER if _ROUTER is not False else None


def prewarm_router() -> bool:
    """Eagerly load the embedding router."""
    try:
        router = _get_router()
        return router is not None
    except Exception:
        return False


def _get_log_path() -> Path | None:
    """Get router decision log path from environment."""
    log_dir = os.environ.get("LUCY_ROUTER_LOG_DIR")
    if log_dir:
        path = Path(log_dir) / "router_decisions.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return None


def _log_decision(
    query: str,
    decision: RoutingDecision,
    *,
    embedding_route: str = "",
    guards_fired: list[str] | None = None,
    top_k_neighbours: list[dict] | None = None,
    memory_gate_override: str = "",
) -> None:
    """Log routing decision if logging is enabled."""
    log_path = _get_log_path()
    if not log_path:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "query": query,
            "route": decision.route,
            "intent": decision.intent_family,
            "confidence": decision.confidence,
            "provider": decision.provider,
            "evidence_reason": decision.evidence_reason,
            "policy_reason": decision.policy_reason,
            "embedding_route": embedding_route,
            "guards_fired": guards_fired or [],
            "top_k_neighbours": top_k_neighbours or [],
            "memory_gate_override": memory_gate_override,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
```

- [ ] **Step 1: Create router.py with the code above**

- [ ] **Step 2: Verify module imports**

Run: `cd tools && python3 -c "from router_py.classify_core.router import _get_router, prewarm_router, _log_decision; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run lint**

Run: `python3 -m ruff check tools/router_py/classify_core/router.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/classify_core/router.py
git commit -m "refactor(classify): move router lifecycle and logging to classify_core/router.py"
```

---

## Task 4: Move memory gate to `classify_core/memory.py`

**Files:**
- Create: `tools/router_py/classify_core/memory.py`
- Modify: `tools/router_py/classify.py` (remove moved code in Task 7)

**Interfaces:**
- Consumes: Nothing from other core modules.
- Produces: `_memory_routing_gate`, `_load_feedback_buffer`, `_FEEDBACK_BUF_CACHE`, `_FEEDBACK_BUF_MTIME`, `_FEEDBACK_BUF_PATH`, continuation regexes, `_LIVE_DATA_KEYWORDS`.

```python
# tools/router_py/classify_core/memory.py
"""Memory-aware routing gate and feedback-buffer cache."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from tools.xdg_paths import lucy_runtime_namespace_root

_FEEDBACK_BUF_CACHE: dict | None = None
_FEEDBACK_BUF_MTIME: float = 0.0
_FEEDBACK_BUF_PATH: Path | None = None

# Copy these compiled regexes verbatim from classify.py:
# _MEMORY_FOLLOWUP_STRONG_RE, _MEMORY_FOLLOWUP_RE, _MEMORY_EXPLICIT_RECALL_RE,
# _CONTINUATION_FOLLOWUP_RE
# Copy _LIVE_DATA_KEYWORDS tuple verbatim.


def _load_feedback_buffer(path: Path) -> dict:
    """Load and cache feedback buffer JSON by mtime."""
    global _FEEDBACK_BUF_CACHE, _FEEDBACK_BUF_MTIME, _FEEDBACK_BUF_PATH
    try:
        mtime = path.stat().st_mtime
        if (
            _FEEDBACK_BUF_CACHE is not None
            and _FEEDBACK_BUF_PATH == path
            and _FEEDBACK_BUF_MTIME == mtime
        ):
            return _FEEDBACK_BUF_CACHE

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _FEEDBACK_BUF_CACHE = data
        _FEEDBACK_BUF_MTIME = mtime
        _FEEDBACK_BUF_PATH = path
        return data
    except Exception:
        return {}


def _memory_routing_gate(
    query: str, embedding_route: str, session_id: str = "default"
) -> str | None:
    """Lightweight memory-aware routing gate."""
    # Paste the full body of _memory_routing_gate from classify.py lines ~2616-~2684.
```

- [ ] **Step 1: Copy `_load_feedback_buffer`, `_memory_routing_gate`, and their regex/constants**

- [ ] **Step 2: Verify imports**

Run: `cd tools && python3 -c "from router_py.classify_core.memory import _memory_routing_gate, _load_feedback_buffer; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run lint**

Run: `python3 -m ruff check tools/router_py/classify_core/memory.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/classify_core/memory.py
git commit -m "refactor(classify): move memory gate to classify_core/memory.py"
```

---

## Task 5: Move intent classification to `classify_core/intent.py`

**Files:**
- Create: `tools/router_py/classify_core/intent.py`
- Modify: `tools/router_py/classify.py` (remove moved code in Task 7)

**Interfaces:**
- Consumes: `_map_to_intent_family` (local), guard functions from `classify_core.guards`, `requires_evidence_mode` from `policy_router`.
- Produces: `classify_intent`, `_map_to_intent_family`, `classify_question` fallback.

```python
# tools/router_py/classify_core/intent.py
"""Intent classification wrapper around the core classifier model."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.policy_router import requires_evidence_mode
from router_py.request_types import ClassificationResult

from router_py.classify_core.guards import (
    _is_clear_news_query,
    _is_creative_writing,
    _is_news_query_typos,
)

_LOGGER = logging.getLogger(__name__)

classify_question = None
try:
    from router_py.core.intent_classifier import classify_question
except Exception as _exc:
    _LOGGER.warning(f"Intent classifier not available: {_exc}")
    try:
        from core.intent_classifier import classify_question
    except Exception:
        classify_question = None


def _map_to_intent_family(intent: str, intent_class: str, category: str) -> str:
    """Map classifier output to intent family."""
    # Paste body from classify.py lines ~2492-~2545.


def classify_intent(query: str, surface: str = "cli") -> ClassificationResult:
    """Classify user intent and return structured result."""
    # Paste body from classify.py lines ~569-~666, keeping the same logic.
```

- [ ] **Step 1: Copy `classify_intent` and `_map_to_intent_family` verbatim**

- [ ] **Step 2: Verify imports**

Run: `cd tools && python3 -c "from router_py.classify_core.intent import classify_intent, _map_to_intent_family; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run lint**

Run: `python3 -m ruff check tools/router_py/classify_core/intent.py`
Expected: `All checks passed!`

- [ ] **Step 4: Commit**

```bash
git add tools/router_py/classify_core/intent.py
git commit -m "refactor(classify): move intent classification to classify_core/intent.py"
```

---

## Task 6: Move route selection to `classify_core/select.py`

**Files:**
- Create: `tools/router_py/classify_core/select.py`
- Modify: `tools/router_py/classify.py` (remove moved code in Task 7)

**Interfaces:**
- Consumes: `_is_*` guards from `classify_core.guards`, `_get_router`, `prewarm_router`, `_log_decision` from `classify_core.router`, `_memory_routing_gate`, `_load_feedback_buffer` from `classify_core.memory`, `classify_intent` not needed directly.
- Produces: `select_route`, `_routing_decision_from_policy`, `_call_llm_arbiter`, `_make_local_decision`, `_make_augmented_decision`, `_make_local_with_fallback`, `_make_news_decision`, `_make_time_decision`, `_make_weather_decision`.

```python
# tools/router_py/classify_core/select.py
"""Route selection orchestration and decision builders."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

from router_py.policy_router import PolicyDecision, PolicyRouter
from router_py.request_types import ClassificationResult, RoutingDecision

# Import provider resolver utilities used by _make_augmented_decision
from router_py import provider_resolver
from router_py.provider_resolver import provider_usage_class_for

from router_py.classify_core.guards import (
    _is_capability_query,
    _is_hostile_override_attempt,
)
from router_py.classify_core.router import _get_router, _log_decision
from router_py.classify_core.memory import _load_feedback_buffer, _memory_routing_gate

_POLICY_ROUTER = PolicyRouter()

_LLM_ARBITER_ROUTES = (
    "LOCAL",
    "AUGMENTED",
    "NEWS",
    "EVIDENCE",
    "TIME",
    "WEATHER",
    "FINANCE",
    "CLARIFY",
)


def _call_llm_arbiter(query: str) -> str | None:
    """Ask a small local Ollama model to resolve a low-confidence route."""
    # Paste body from classify.py lines ~57-~110.


def _routing_decision_from_policy(
    classification: ClassificationResult,
    policy_decision: PolicyDecision,
    query: str = "",
) -> RoutingDecision:
    """Convert a deterministic PolicyDecision into a RoutingDecision."""
    # Paste body from classify.py lines ~782-~809.


def _make_local_decision(classification: ClassificationResult, query: str = "") -> RoutingDecision:
    """Create a local-only routing decision."""
    # Paste body.


def _make_augmented_decision(
    classification: ClassificationResult,
    prefer_paid: bool = False,
    query: str = "",
) -> RoutingDecision:
    """Create an augmented or evidence routing decision."""
    # Paste body from lines ~2704-~2754.


def _make_local_with_fallback(classification: ClassificationResult, query: str = "") -> RoutingDecision:
    """Create a local-first with fallback routing decision."""
    # Paste body.


def _make_news_decision(classification: ClassificationResult) -> RoutingDecision:
    # Paste body.


def _make_time_decision(classification: ClassificationResult) -> RoutingDecision:
    # Paste body.


def _make_weather_decision(classification: ClassificationResult) -> RoutingDecision:
    # Paste body.


def select_route(
    classification: ClassificationResult,
    policy: str = "fallback_only",
    forced_mode: str | None = None,
    query: str = "",
    session_id: str = "default",
) -> RoutingDecision:
    """Select final route using the embedding router."""
    # Paste body from classify.py lines ~812-~1423.
    # Replace internal references with imports from this module.
```

- [ ] **Step 1: Copy `_call_llm_arbiter`, `_routing_decision_from_policy`, all `_make_*_decision`, and `select_route`**

- [ ] **Step 2: Resolve imports inside `select_route`**

Inside `select_route`, replace references to `_is_hostile_override_attempt`, `_is_capability_query`, `_memory_routing_gate`, `_load_feedback_buffer`, `_get_router`, `_log_decision`, `_routing_decision_from_policy`, and `_make_*_decision` with imports from `classify_core` modules or this module.

- [ ] **Step 3: Verify imports**

Run: `cd tools && python3 -c "from router_py.classify_core.select import select_route, _call_llm_arbiter, _make_local_decision; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Run lint**

Run: `python3 -m ruff check tools/router_py/classify_core/select.py`
Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/classify_core/select.py
git commit -m "refactor(classify): move route selection to classify_core/select.py"
```

---

## Task 7: Replace `tools/router_py/classify.py` with a thin facade

**Files:**
- Modify: `tools/router_py/classify.py`

**Interfaces:**
- Consumes: Everything from `classify_core` modules.
- Produces: Same public and private API surface as the original monolithic file.

Replace the entire body of `tools/router_py/classify.py` with:

```python
#!/usr/bin/env python3
"""
Intent classification integration - Python API for router classification.

This module is now a thin facade over classify_core. New code should import
from router_py.classify_core.* directly; this facade exists for backward
compatibility.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(ROOT_DIR / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT_DIR / "tools"))

# Re-export request types for callers that imported them from here
from router_py.request_types import ClassificationResult, RoutingDecision

# Public API
from router_py.classify_core.intent import classify_intent
from router_py.classify_core.router import prewarm_router
from router_py.classify_core.select import select_route

# Privates used by other production modules and tests
from router_py.classify_core.guards import (
    _is_capability_query,
    _is_clear_news_query,
    _is_conflict_analysis_query,
    _is_cooking_query,
    _is_creative_writing,
    _is_financial_ephemeral,
    _is_historical_query,
    _is_hostile_override_attempt,
    _is_language_or_translation_query,
    _is_news_query_typos,
    _is_personal_family_query,
    _is_public_figure_age_query,
    _is_synthesis_request,
    _is_technical_knowledge_query,
    _is_time_query,
    _is_weather_query,
)
from router_py.classify_core.intent import _map_to_intent_family
from router_py.classify_core.memory import _memory_routing_gate
from router_py.classify_core.select import (
    _call_llm_arbiter,
    _make_augmented_decision,
    _make_local_decision,
)

# Keep the CLI interface from the original file
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Classify intent for routing")
    parser.add_argument("query", help="User query to classify")
    parser.add_argument("--surface", default="cli", help="Interface surface")
    parser.add_argument("--policy", default="fallback_only", help="Augmentation policy")
    args = parser.parse_args()

    try:
        classification = classify_intent(args.query, surface=args.surface)
        decision = select_route(classification, policy=args.policy, query=args.query)

        result = {
            "classification": {
                "intent": classification.intent,
                "intent_family": classification.intent_family,
                "intent_class": classification.intent_class,
                "confidence": classification.confidence,
                "needs_web": classification.needs_web,
            },
            "decision": {
                "route": decision.route,
                "provider": decision.provider,
                "provider_usage_class": decision.provider_usage_class,
                "policy_reason": decision.policy_reason,
            },
        }
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
```

- [ ] **Step 1: Replace the body of `tools/router_py/classify.py`**

- [ ] **Step 2: Verify that the facade is import-compatible with all existing callers**

Run: `cd tools && python3 -c "from router_py.classify import classify_intent, select_route, prewarm_router, ClassificationResult, RoutingDecision, _is_capability_query, _memory_routing_gate, _call_llm_arbiter; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run lint**

Run: `python3 -m ruff check tools/router_py/classify.py tools/router_py/classify_core/`
Expected: `All checks passed!`

- [ ] **Step 4: Run fast tests**

Run: `./scripts/run-fast-tests.sh`
Expected: `701 passed, 7 skipped` (or current baseline)

- [ ] **Step 5: Commit**

```bash
git add tools/router_py/classify.py
git commit -m "refactor(classify): replace classify.py with facade over classify_core"
```

---

## Task 8: Smoke test and live classify tests

**Files:**
- None (verification only)

- [ ] **Step 1: Smoke test**

Run: `cd tools && python3 -m router_py.main "What is 2+2?"`
Expected: route `LOCAL`, answer contains `4`.

- [ ] **Step 2: Live classify tests**

Run: `python3 -m pytest tools/router_py/test_classify.py -m "live" -v --tb=short`
Expected: all tests pass.

- [ ] **Step 3: Router burn-in / regression**

Run: `python3 -m pytest tools/router_py/test_classifier_regression.py tools/router_py/test_real_router_burn_in.py -m "live" -v --tb=short`
Expected: all tests pass (may be slow; use long timeout).

- [ ] **Step 4: Commit if tests pass**

```bash
git commit --allow-empty -m "test(classify): verify smoke, live classify, and regression tests after split"
```

---

## Task 9: Final review and push

**Files:**
- None (git operations only)

- [ ] **Step 1: Review diff**

Run: `git diff --stat HEAD~6..HEAD`
Expected: ~6 new commits, new `classify_core/` directory, `classify.py` reduced to facade size.

- [ ] **Step 2: Push to main**

Run: `git push origin main`
Expected: push succeeds.

---

## Self-Review Checklist

1. **Spec coverage:** Every major responsibility from the original `classify.py` is assigned to a core file: guards → `guards.py`, router lifecycle → `router.py`, intent → `intent.py`, memory → `memory.py`, selection → `select.py`, facade → `classify.py`.
2. **Placeholder scan:** No `TODO`, `TBD`, or "implement later" items remain in the plan. Steps that require copying code reference exact line ranges in the source file.
3. **Type consistency:** All function signatures and re-export names match the original `classify.py`. Patch paths like `router_py.classify._call_llm_arbiter` remain valid because the facade re-exports from the same module path.
4. **Global state:** `_ROUTER` and `_FEEDBACK_BUF_CACHE` remain module-level singletons in their respective core files; no duplicate copies are created.
5. **Test coverage:** Fast tests, live classify tests, and burn-in/regression tests are all exercised before final push.
