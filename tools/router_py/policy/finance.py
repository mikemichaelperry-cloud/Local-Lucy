#!/usr/bin/env python3
"""Personal finance reasoning detection."""

import re

# Pre-compiled financial anchor regexes for _is_personal_finance_reasoning
_FINANCIAL_ANCHOR_RE = tuple(
    re.compile(rf"\b{re.escape(anchor)}\b")
    for anchor in (
        "bank",
        "balance",
        "savings",
        "retirement",
        "pension",
        "budget",
        "budgeting",
        "invest",
        "investing",
        "investment",
        "stock",
        "stocks",
        "bond",
        "bonds",
        "portfolio",
        "401k",
        "ira",
        "roth",
        "mutual fund",
        "etf",
        "mortgage",
        "loan",
        "debt",
        "credit",
        "income",
        "salary",
        "expense",
        "expenses",
        "net worth",
        "wealth",
        "financial",
        "money",
        "cash",
        "fund",
        "funds",
        "asset",
        "assets",
        "tax",
        "taxes",
        "risk tolerance",
        "credit score",
        "capital gains",
        "insurance",
        "premium",
    )
)

# Pre-compiled historical query regexes for _is_historical_query

def _is_personal_finance_reasoning(query: str) -> bool:
    """
    Detect whether a query is asking for personal-finance *reasoning/advice*
    rather than live financial *data*.

    Examples of reasoning (should stay LOCAL):
        - "What would you consider a comfortable bank balance?"
        - "How should I budget for retirement?"
        - "Should I invest in stocks or bonds?"
        - "What is your opinion on my pension plan?"

    Examples of data lookups (should trigger evidence):
        - "What is the current stock price of Apple?"
        - "Bitcoin price today"
        - "Current inflation rate in Israel"

    Returns True if the query is a reasoning/planning/advice request.
    """
    if not query:
        return False
    q_lower = query.lower()

    # Reasoning/advice indicators — these signal the user wants opinion/planning
    reasoning_indicators = [
        "what would you consider",
        "what do you consider",
        "what is a good",
        "what is a comfortable",
        "what is a reasonable",
        "what do you think",
        "what is your opinion",
        "what is your take",
        "how should i",
        "how much should i",
        "how do i",
        "how do taxes",
        "how does",
        "explain how",
        "should i",
        "would it be better",
        "is it worth",
        "is it a good idea",
        "advice on",
        "advice about",
        "advice",
        "plan for",
        "planning for",
        "strategy for",
        "help me decide",
        "help me choose",
        "recommend",
        "rules",
    ]

    # Financial topic anchors — ensure we only downgrade when financial topics
    # are actually present (prevent unrelated reasoning from bypassing evidence)
    financial_anchors = [
        "bank",
        "balance",
        "savings",
        "retirement",
        "pension",
        "budget",
        "budgeting",
        "invest",
        "investing",
        "investment",
        "stock",
        "stocks",
        "bond",
        "bonds",
        "portfolio",
        "401k",
        "ira",
        "roth",
        "mutual fund",
        "etf",
        "mortgage",
        "loan",
        "debt",
        "credit",
        "income",
        "salary",
        "expense",
        "expenses",
        "net worth",
        "wealth",
        "financial",
        "money",
        "cash",
        "fund",
        "funds",
        "asset",
        "assets",
        "tax",
        "taxes",
        "risk tolerance",
        "credit score",
        "capital gains",
        "insurance",
        "premium",
    ]

    has_reasoning = any(ind in q_lower for ind in reasoning_indicators)
    has_financial = any(p.search(q_lower) for p in _FINANCIAL_ANCHOR_RE)

    return has_reasoning and has_financial
