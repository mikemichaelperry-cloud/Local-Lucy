# Local Lucy V11 — Known Limitations and Accepted Holdout Misroutes

Created during final requalification (2026-08-06).

## Holdout result

Locked holdout: **13/15** correct (2 failures).
Both failures are anaphoric search imperatives recorded as `real_hmi_failure` cases.

---

## HOLD-ANAPH-001 — "Can you search again?"

| Field | Value |
|---|---|
| Case ID | HOLD-ANAPH-001 |
| Original query | "Can you search again?" |
| Conversation context | Implicit prior web topic (the case was harvested after a web-route exchange). |
| Expected route | `AUGMENTED` |
| Raw classifier route | `LOCAL` |
| Final post-guard route (before fix) | `LOCAL` |
| Candidate scores | Classifier k-NN fallback had no topic to inherit; policy gates did not match the bare imperative. |
| Triggered guards | None (bare imperative). |
| Capabilities affected | Web search / anaphora inheritance. |
| Network behaviour | No network request performed. |
| Evidence policy | N/A |
| Downstream outcome | Local model answered with a capability statement or fallback text instead of searching the prior topic. |
| Safety/privacy impact | No boundary crossed; user-visible behaviour was unhelpful but safe. |

**Classification:** `ACTIVE_DEFECT` — fixed during requalification.

**Root cause:** The search-imperative resolver in `tools/router_py/main.py` only matched explicit tool names ("Use DuckDuckGo search", "search the web", etc.) and did not cover generic "search again" / "search once more" follow-ups.

**Fix:** Extended `_SEARCH_TOOL_IMPERATIVE_PATTERN` to include `(?:can you\s+)?search\s+(?:again|once\s+more)` with optional trailing "please". Added regression tests in `tools/router_py/test_search_imperative_anaphora.py`.

**Why the holdout metric still reports it as a failure:** `qualification/compute_baseline_metrics.py` evaluates `classify_question` + `select_route_for_question` in isolation; it does not run the `main.py` anaphora resolver. The locked holdout case is therefore unchanged, but the actual user-visible path now resolves correctly.

---

## HMI-ANAPH-001 — "Use DuckDuckGo search"

| Field | Value |
|---|---|
| Case ID | HMI-ANAPH-001 |
| Original query | "Use DuckDuckGo search" |
| Conversation context | Implicit prior web topic (harvested after a web-route exchange). |
| Expected route | `AUGMENTED` |
| Raw classifier route | `LOCAL` |
| Final post-guard route | `AUGMENTED` when the `main.py` anaphora resolver has a prior web-route exchange; `LOCAL` in isolation. |
| Candidate scores | Classifier k-NN fallback had no topic to inherit. |
| Triggered guards | None (bare imperative). |
| Capabilities affected | Web search / anaphora inheritance. |
| Network behaviour | No network request when routed `LOCAL`. |
| Evidence policy | N/A |
| Downstream outcome | With prior web context, the resolver replaces the imperative with the prior query and routes `AUGMENTED`. Without context, it stays `LOCAL` and asks what to search for. |
| Safety/privacy impact | No boundary crossed. |

**Classification:** `TEST_EXPECTATION_ERROR` (holdout-metric scope).

**Rationale:** The holdout evaluation intentionally excludes anaphora/context resolution performed in `main.py` (see `baseline_metrics.json` note: "Baseline metrics measure classify+route only; anaphora/context resolution in main.py is excluded."). The bare imperative "Use DuckDuckGo search" cannot be routed to `AUGMENTED` by the classifier alone because it carries no topic. The expectation that it should route `AUGMENTED` is only valid when the surrounding conversation context is available, which the metric does not provide. The real HMI path was fixed in DEF-005 and remains functional.

---

## Other accepted limitations

1. **Persistent-fact correction authority.** The memory service stores contradictory facts verbatim and retrieves them by semantic similarity. It does not automatically prefer a newer fact over an older contradictory fact or mark one as superseded. This is documented and tested in `tools/tests/test_memory_requalification.py::TestMemoryRequalification::test_newer_correction_is_retrievable`. Users must explicitly manage/approve persistent facts.

2. **Generic low-confidence → AUGMENTED fallback is not implemented.** The completion report previously recommended a confidence-based AUGMENTED fallback. This was rejected because low classifier confidence does not prove that external information is required. The current behaviour is preserved.

3. **Holdout metric excludes anaphora/context resolution.** As noted in `baseline_metrics.json`, the routing corpus metrics measure `classify_question` + `select_route_for_question` only. Anaphoric imperatives, location rewriting, and search-imperative inheritance are handled in `main.py` and are validated by dedicated tests, not by the holdout accuracy figure.
