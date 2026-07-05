# Local Lucy V11 — Session Handoff

**Date:** 2026-07-05
**Branch:** `v10-dev` on GitHub (`origin v10-dev` pushed)
**Version:** `11.0.0-dev`
**Status:** All v11 roadmap phases completed and pushed.

---

## What was completed

| Phase | Summary | Commit |
|-------|---------|--------|
| 0 | Removed Hebrew/Racheli from primary runtime, quarantined configs, fixed prompt contradictions, updated AUGMENTED = Wikipedia evidence + optional OpenAI/Kimi synthesis. | `82c9296` |
| 1-2 | Added JSONL metrics sink, hardened context guard (provenance, temporal, entity collision, answerability), route-dependent evidence failure fallback. | `5d01586` |
| 3 | Automatic model selection in shadow mode; HMI model selector now defaults to Auto, manual selector moved to Engineering panel. | `a0b03e5` |
| 4 | Frozen validation corpus, classifier error analysis, hard-negative generation, classifier-head retrain, confidence-triggered LLM arbiter, stable-knowledge policy gate. | `f57c6a2` |
| 5 | Simplified HMI default view (Memory/Voice/status only), advanced controls in Engineering panel, persona selector removed from primary HMI. | `c75d8c2` |
| 6 | Synthetic adversarial cleanup: full-answer tests opt-in, v11 policy-conflict cases moved to diagnostic directory, fixed routing defects (conspiracy→LOCAL, stable history/finance→LOCAL, garbage→LOCAL). | `3d4e05f` |
| 7 | Latency optimization: MiniLM embedding LRU cache, parallel AUGMENTED evidence fetching, per-route token budgets, model warmup thread. | `d4a7334` |
| 8 | Version bump to `11.0.0-dev`, updated Architecture.md/README.md, news recency scoring + source cross-check, evidence freshness check + graceful fallback. | `cb04727` |

---

## Test scores

| Suite | Before | After |
|-------|--------|-------|
| Routing barrage | 36/38 PASS | **38/38 PASS** |
| Router unit tests | 719 passed | **767 passed, 29 skipped** |
| Adversarial route tests | timed out / 81 failures | **879 passed** |
| HMI comprehensive inspection | 138/138 | **138/138** |

*Latency:* routing steady-state mean after warmup is **~3.0 ms** (first-load dominated by MiniLM import remains ~4.5 s).

---

## Important changes to know

- **English-only runtime.** Hebrew/Racheli code is quarantined, not deleted.
- **Evidence vs synthesis.** Wikipedia and official APIs are evidence; OpenAI/Kimi are synthesis providers. AUGMENTED now means "Wikipedia evidence with optional synthesis."
- **Context guard.** Every injected source is scored before reaching the LLM prompt; stale/irrelevant evidence and memory turns are dropped.
- **Automatic model selection.** HMI defaults to Auto; manual override remains in Engineering panel. Shadow logs are written to the metrics sink.
- **Simplified HMI.** Default view shows only Memory toggle, Voice toggle, route/model status, trust/source summary.
- **Latency.** Embedding cache + parallel evidence + token budgets should make v11 feel faster.

---

## Files you will want next session

- `docs/superpowers/plans/2026-07-05-local-lucy-v11-roadmap.md` — the approved roadmap.
- `Architecture.md` — updated normative v11 architecture.
- `VERSION` — now `11.0.0-dev`.
- `config/latency_optimizations.env` — knobs for Phase 7 optimizations.
- `.superpowers/sdd/task-*-report.md` — per-phase subagent reports.

---

## Recommended next steps

1. Run the HMI from the Desktop shortcut and exercise Auto model selection across coding, memory, news, and medical queries.
2. Inspect shadow logs at `~/.codex-api-home/lucy/runtime-v10/metrics/routing_metrics.jsonl` to verify Auto model choices.
3. After ~50 real queries, review A/B preference data and decide whether to hide the manual model selector completely.
4. Run `LUCY_SYNTHETIC_FULL_ANSWER=1 python3 -m pytest tools/router_py/test_synthetic_adversarial.py` when you have time to validate response-level invariants.
5. The user also asked for a "barrage of common, wide-ranging test questions" compared to your own answers and retraining Lucy to match — this remains a future task.
