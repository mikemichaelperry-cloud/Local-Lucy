# ADR 0001: Background Learner Ingests Only Explicit User Feedback

## Status
Accepted — implemented 2026-06-07

## Context
The auto-learn pipeline originally ingested three signal sources:
1. Router logs
2. Heuristic auto-feedback
3. Explicit user feedback

Analysis showed that router logs and auto-feedback were noisy and often correlated with symptoms (e.g., a route was wrong) rather than causation (e.g., what the correct route should be). Ingesting them degraded routing quality over time.

## Decision
- **Auto-feedback is telemetry-only.** `process_auto_feedback()` returns `[]` and is logged, not ingested.
- **Router logs are telemetry-only.** Removed from `learn_once()`.
- **Only explicit user feedback is ingested**, after passing a safety gate.
- **High-stakes feedback** (medical, veterinary, finance, legal, EVIDENCE) is queued to `pending_review.jsonl` for human review.
- **Conflict-preserving deduplication:** duplicate/conflicting examples are logged as audit events instead of silently overwriting.

## Consequences
- Training set stays smaller and cleaner.
- Medical/vet/finance/legal routes cannot be silently corrupted by unsupervised learning.
- Human review queue requires occasional manual triage.
