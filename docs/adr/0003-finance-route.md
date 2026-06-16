# ADR 0003: Dedicated FINANCE Route for Live Market Data

## Status
Accepted — implemented 2026-06-15

## Context
Financial queries previously routed through AUGMENTED or EVIDENCE with generic web-search. This produced inconsistent source quality and no clear separation between live market data (e.g., "BTC price") and personal-finance reasoning (e.g., "how do I budget?").

## Decision
Add a dedicated `FINANCE` route:
- **FX rates:** `exchangerate-api.com`
- **Crypto:** CoinGecko (BTC, ETH, SOL, XRP, ADA, DOGE)
- **Stocks/indices:** Yahoo Finance primary, web-search fallback on rate-limit
- **Net worth:** web search restricted to trusted finance sources
- **Personal-finance reasoning** continues to route `LOCAL`.

All FINANCE answers include source citations; fallbacks are explicitly labelled.

## Consequences
- Consistent, citable answers for live market data.
- Clear boundary between ephemeral market data and personal financial advice.
- New dependency on external free APIs with their own rate limits.
