# ADR 0005: Embedding-First Routing with Keyword Guards

## Status
Accepted — implemented 2026-06-14

## Context
Earlier routers relied on a "keyword fortress" that routed by pattern matching. This was brittle and required constant manual tuning as query patterns evolved.

## Decision
Make embedding k-NN the primary routing authority, with keyword guards retained only for hard safety catches:
- Medical / veterinary → EVIDENCE
- Weather → WEATHER
- News → NEWS
- Finance (ephemeral) → FINANCE

Keyword guards run after embedding similarity and can override only for safety-critical categories.

## Consequences
- More generalizable routing for unseen phrasings.
- Reduced manual rule maintenance.
- Requires high-quality, curated training examples and periodic review.
