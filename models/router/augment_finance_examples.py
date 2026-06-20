#!/usr/bin/env python3
"""Add validated FINANCE-route training examples.

The FINANCE route is triggered by a keyword guard in classify.py before the
embedding router runs, so this script validates candidates with the actual
select_route() pipeline rather than with HybridRouterV2 alone.  Only queries
that are unambiguously routed to FINANCE are added.
"""

from __future__ import annotations

import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
EXAMPLES_PATH = ROOT / "comprehensive_examples.json"
BACKUP_PATH = ROOT / "comprehensive_examples.json.bak"

sys.path.insert(0, str(ROOT.parent.parent / "tools" / "router_py"))
sys.path.insert(0, str(ROOT.parent.parent / "tools"))
from classify import classify_intent, select_route  # type: ignore[import-not-found]


_STOCK_TEMPLATES = [
    "What is the stock price of {company}?",
    "{company} share price",
    "Current price of {company} stock",
    "How is {company} trading today?",
    "{company} ticker",
    "Show me {company} stock",
    "What was {company}'s closing price?",
    "Is {company} up or down today?",
    "{company} premarket",
    "After-hours price for {company}",
    "What is the current price of {company} stock today?",
    "{company} stock price now",
    "{company} stock today",
    "Current value of {company} shares",
    "What is {company} trading at right now?",
    "Latest {company} stock price",
    "{company} stock price today",
]

_COMPANIES = [
    "Apple",
    "Tesla",
    "Microsoft",
    "Amazon",
    "Google",
    "Meta",
    "NVIDIA",
    "AMD",
    "Intel",
    "Netflix",
    "IBM",
    "Oracle",
    "Salesforce",
    "Adobe",
    "Qualcomm",
    "Samsung",
    "Toyota",
    "Boeing",
    "JPMorgan",
    "Bank of America",
    "Walmart",
    "Coca-Cola",
    "Pepsi",
    "McDonald's",
    "Visa",
    "Mastercard",
    "ExxonMobil",
]

_CRYPTO_TEMPLATES = [
    "What is the price of {coin}?",
    "{coin} price today",
    "Current {coin} value",
    "How much is {coin} worth?",
    "{coin} to USD",
    "{coin} chart",
    "Is {coin} going up?",
    "{coin} market cap",
    "Current price of {coin}",
    "{coin} price now",
    "What is {coin} trading at today?",
    "Live {coin} price",
]

_COINS = [
    "Bitcoin",
    "Ethereum",
    "Solana",
    "Cardano",
    "Ripple",
    "Dogecoin",
    "Litecoin",
    "Polkadot",
    "Avalanche",
    "Chainlink",
]

_Forex_TEMPLATES = [
    "{base} to {target}",
    "Convert {base} to {target}",
    "What is the exchange rate between {base} and {target}?",
    "How many {target} is one {base}?",
    "{base}{target} rate",
    "{base} {target} forex",
]

_CURRENCIES = [
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "AUD",
    "CAD",
    "CHF",
    "CNY",
    "INR",
    "MXN",
    "NZD",
    "SGD",
    "ZAR",
    "SEK",
    "NOK",
    "PLN",
    "ILS",
    "BRL",
    "KRW",
    "HKD",
]

_INDEX_TEMPLATES = [
    "What is the {index}?",
    "{index} current value",
    "How did the {index} close?",
    "{index} today",
    "Is the {index} up or down?",
    "{index} futures",
    "{index} now",
    "Current value of the {index}",
    "What is the {index} trading at?",
]

_INDICES = [
    "S&P 500",
    "Dow Jones",
    "NASDAQ",
    "FTSE 100",
    "DAX",
    "Nikkei 225",
    "Hang Seng",
    "CAC 40",
    "ASX 200",
    "Russell 2000",
    "VIX",
]

_NET_WORTH_TEMPLATES = [
    "How much is {person} worth?",
    "{person} net worth",
    "What is {person}'s net worth today?",
    "Is {person} a billionaire?",
    "Is {person} a trillionaire?",
    "How much is {person} worth right now?",
]

_PEOPLE = [
    "Elon Musk",
    "Jeff Bezos",
    "Bill Gates",
    "Warren Buffett",
    "Mark Zuckerberg",
    "Larry Ellison",
    "Larry Page",
    "Sergey Brin",
    "Bernard Arnault",
    "Mukesh Ambani",
]

_COMMODITY_TEMPLATES = [
    "What is the price of {commodity}?",
    "{commodity} price today",
    "Current {commodity} price per ounce",
    "{commodity} spot price",
    "{commodity} price now",
    "Current price of {commodity}",
    "What is {commodity} trading at today?",
]

_COMMODITIES = [
    "gold",
    "silver",
    "crude oil",
    "natural gas",
    "copper",
    "platinum",
    "palladium",
    "wheat",
    "corn",
    "coffee",
    "bitcoin",
    "ethereum",
]

_MARKET_TEMPLATES = [
    "How are the markets doing?",
    "Stock market today",
    "Is the market open?",
    "When does the stock market close?",
    "Market futures",
    "Pre-market movers",
    "After hours trading",
    "How is the stock market doing today?",
    "Current stock market status",
    "Market open now?",
]

_PREFIXES = [
    "",
    "Quick question: ",
    "Can you check ",
    "Hey Lucy, ",
    "I need ",
    "What's ",
    "Tell me ",
]


def _format(template: str, **kwargs: str) -> str:
    return template.format(**kwargs)


def _make_example(query: str) -> dict:
    return {
        "query": query,
        "labels": {
            "intent_family": "current_evidence",
            "evidence_mode": "not_required",
            "route": "FINANCE",
            "policy_override": "none",
        },
        "metadata": {
            "source": "synthetic_finance_augmentation",
            "feedback_type": "finance_guard_validated",
        },
    }


def _generate_candidates(target: int = 250) -> list[dict]:
    """Generate a diverse pool of finance-route candidate examples."""
    candidates: list[dict] = []
    used: set[str] = set()

    def add(query: str) -> None:
        q = query.strip()
        if q.lower() not in used:
            used.add(q.lower())
            candidates.append(_make_example(q))

    # Stocks
    for company in _COMPANIES:
        for template in _STOCK_TEMPLATES:
            add(_format(template, company=company))
        # Ticker-only variant
        ticker = "".join(c for c in company.upper() if c.isupper())[:4]
        if ticker:
            add(f"{ticker} price")
            add(f"What is {ticker}?")

    # Crypto
    for coin in _COINS:
        for template in _CRYPTO_TEMPLATES:
            add(_format(template, coin=coin))
        symbol = coin[:3].upper()
        add(f"{symbol} price")
        add(f"{symbol} USD")

    # Forex
    for base in _CURRENCIES:
        for target_cur in _CURRENCIES:
            if base == target_cur:
                continue
            for template in _Forex_TEMPLATES:
                add(_format(template, base=base, target=target_cur))

    # Indices
    for index in _INDICES:
        for template in _INDEX_TEMPLATES:
            add(_format(template, index=index))

    # Net worth
    for person in _PEOPLE:
        for template in _NET_WORTH_TEMPLATES:
            add(_format(template, person=person))

    # Commodities
    for commodity in _COMMODITIES:
        for template in _COMMODITY_TEMPLATES:
            add(_format(template, commodity=commodity))

    # Market summaries
    for template in _MARKET_TEMPLATES:
        add(template)

    # Apply conversational prefixes to a subset.
    prefixed: list[dict] = []
    for ex in candidates:
        if random.random() < 0.25:
            prefix = random.choice(_PREFIXES)
            q = ex["query"]
            if prefix and not q.startswith(prefix.strip()):
                new_q = prefix + q[0].lower() + q[1:]
                if new_q.lower() not in used:
                    used.add(new_q.lower())
                    prefixed.append(_make_example(new_q))
    candidates.extend(prefixed)

    return candidates[:target]


def _validate_candidates(
    candidates: list[dict], existing_queries: set[str]
) -> tuple[list[dict], dict[str, int]]:
    """Keep only candidates that the full routing pipeline sends to FINANCE."""
    accepted: list[dict] = []
    stats: dict[str, int] = {"accepted": 0, "rejected": 0, "duplicate": 0}

    for ex in candidates:
        q = ex["query"].strip()
        q_lower = q.lower()
        if q_lower in existing_queries:
            stats["duplicate"] += 1
            continue

        try:
            classification = classify_intent(q)
            decision = select_route(classification, "fallback_only", None, q, None)
        except Exception:
            stats["rejected"] += 1
            continue

        if decision.route == "FINANCE":
            accepted.append(ex)
            existing_queries.add(q_lower)
            stats["accepted"] += 1
        else:
            stats["rejected"] += 1

    return accepted, stats


def main() -> int:
    random.seed(42)

    print(f"Loading {EXAMPLES_PATH}...")
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        existing = json.load(f)
    print(f"  Existing examples: {len(existing)}")

    existing_queries = {ex["query"].strip().lower() for ex in existing}
    before = Counter(ex["labels"]["route"] for ex in existing)

    print("\nGenerating FINANCE candidates...")
    candidates = _generate_candidates(250)
    print(f"  Candidates generated: {len(candidates)}")

    print("Validating candidates with full routing pipeline...")
    accepted, stats = _validate_candidates(candidates, existing_queries)
    print(f"  Accepted: {stats['accepted']}")
    print(f"  Rejected: {stats['rejected']}")
    print(f"  Duplicates skipped: {stats['duplicate']}")

    merged = existing + accepted
    after = Counter(ex["labels"]["route"] for ex in merged)

    print("\n--- BEFORE vs AFTER ---")
    print(f"{'Route':<15} {'Before':>8} {'After':>8} {'+/-':>8}")
    print("-" * 42)
    for route in sorted(set(before) | set(after)):
        b = before.get(route, 0)
        a = after.get(route, 0)
        print(f"{route:<15} {b:>8} {a:>8} {a-b:>+8}")
    print(f"\nTotal: {len(existing)} -> {len(merged)} (+{len(accepted)})")

    print(f"\nBacking up original to {BACKUP_PATH}...")
    shutil.copy2(EXAMPLES_PATH, BACKUP_PATH)

    print(f"Writing merged dataset to {EXAMPLES_PATH}...")
    with open(EXAMPLES_PATH, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print("\nDone. Rebuild embeddings next:")
    print("  python scripts/rebuild_embeddings.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
